"""Read-only web dashboard over the crawl DB.

Stdlib-only HTTP server (no Flask). Exposes:

    /                  overview: stats + recent fetches
    /pages             paginated page list + FTS search
    /page?u=URL        single page detail
    /findings          credential / leak findings (filter by category)
    /alerts            watchlist alerts
    /schedules         persistent schedule status
    /mirrors           near-duplicate clusters
    /api/stats         JSON: stats()
    /api/findings      JSON: findings (?category=...&limit=N)
    /api/alerts        JSON: recent alerts
    /api/schedules     JSON: schedules
    /healthz           "ok"

Design choices:

* Single ``ThreadingHTTPServer`` instance — fine for a few dozen QPS in a
  trusted network, which is all this is for. Each handler opens its own
  SQLite connection so we can serve concurrent requests without sharing
  a connection across threads.
* Bind to ``127.0.0.1`` by default. ``0.0.0.0`` prints a warning.
* Optional shared-token auth via ``X-Darkcat-Token`` header *or*
  ``?token=`` query param — for the case where the user puts the dashboard
  behind a reverse proxy on a Tailscale/WireGuard interface and wants a
  cheap second factor.
* All HTML escaped through :func:`html.escape`. Search uses the same
  FTS5 sanitizer as the CLI.
"""
from __future__ import annotations

import html
import json
import sqlite3
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_CSS = """
* { box-sizing: border-box; }
body {
  background: #0c0d10; color: #c8c9cc;
  font: 14px/1.5 ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace;
  margin: 0; padding: 0;
}
header {
  background: #14161b; border-bottom: 1px solid #23262d;
  padding: 12px 22px; display: flex; gap: 18px; align-items: baseline;
}
header h1 { font-size: 16px; margin: 0; color: #e8e9ec; letter-spacing: 1px; }
header nav a {
  color: #8d97ad; text-decoration: none; margin-right: 14px;
}
header nav a.active, header nav a:hover { color: #f0c674; }
main { padding: 22px; max-width: 1280px; margin: 0 auto; }
h2 { color: #e8e9ec; font-size: 14px; margin: 24px 0 8px; letter-spacing: 1px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #1e2128; vertical-align: top; }
th { color: #8d97ad; font-weight: normal; }
tr:hover td { background: #15171c; }
a { color: #81a2be; }
a:hover { color: #f0c674; }
.pill {
  display: inline-block; padding: 0 6px; border: 1px solid #23262d;
  border-radius: 3px; font-size: 11px; color: #b5bd68; background: #15171c;
}
.muted { color: #5e6470; }
.warn { color: #de935f; }
.fail { color: #cc6666; }
.ok { color: #b5bd68; }
.kpi {
  display: inline-block; min-width: 110px; padding: 10px 14px; margin: 4px 6px 4px 0;
  background: #14161b; border: 1px solid #23262d; border-radius: 4px;
}
.kpi .v { font-size: 22px; color: #f0c674; }
.kpi .k { font-size: 11px; color: #8d97ad; letter-spacing: 1px; }
form.search { margin: 0 0 16px; }
form.search input[type=text] {
  background: #15171c; color: #c8c9cc; border: 1px solid #23262d;
  padding: 6px 10px; border-radius: 3px; min-width: 320px;
}
form.search button {
  background: #f0c674; color: #0c0d10; border: 0; padding: 6px 12px;
  border-radius: 3px; cursor: pointer;
}
.url { word-break: break-all; }
.snippet { color: #8d97ad; font-size: 12px; }
"""


def _layout(title: str, body: str, active: str = "") -> str:
    nav_items = [
        ("/", "overview", "overview"),
        ("/pages", "pages", "pages"),
        ("/findings", "findings", "findings"),
        ("/alerts", "alerts", "alerts"),
        ("/schedules", "schedules", "schedules"),
        ("/mirrors", "mirrors", "mirrors"),
        ("/liveness", "liveness", "liveness"),
    ]
    nav = "\n".join(
        f'<a href="{href}" class="{ "active" if k == active else "" }">{label}</a>'
        for href, label, k in nav_items
    )
    return (
        f"<!doctype html><html lang=en><head>"
        f"<meta charset=utf-8>"
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)} — darkcat</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<header><h1>DARKCAT</h1><nav>{nav}</nav>"
        f"<span class=muted>{html.escape(time.strftime('%Y-%m-%d %H:%M'))}</span>"
        f"</header><main>{body}</main></body></html>"
    )


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    DB_PATH: str = ""
    AUTH_TOKEN: str = ""  # empty = no auth

    # -- helpers -----------------------------------------------------------

    def _text(self, code: int, body: str, ct: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, payload) -> None:
        self._text(code, json.dumps(payload, ensure_ascii=False, default=str),
                   ct="application/json; charset=utf-8")

    def _html(self, body: str, *, code: int = 200) -> None:
        self._text(code, body, ct="text/html; charset=utf-8")

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.DB_PATH, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _check_auth(self, qs: dict[str, list[str]]) -> bool:
        if not self.AUTH_TOKEN:
            return True
        hdr = self.headers.get("X-Darkcat-Token", "")
        qtok = (qs.get("token") or [""])[0]
        return hdr == self.AUTH_TOKEN or qtok == self.AUTH_TOKEN

    # -- dispatch ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)
            if path == "/healthz":
                return self._text(200, "ok\n")
            if not self._check_auth(qs):
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Bearer realm="darkcat"')
                self.end_headers()
                return
            route_map = {
                "/": self._page_overview,
                "/pages": self._page_pages,
                "/page": self._page_detail,
                "/findings": self._page_findings,
                "/alerts": self._page_alerts,
                "/schedules": self._page_schedules,
                "/mirrors": self._page_mirrors,
                "/liveness": self._page_liveness,
                "/api/stats": self._api_stats,
                "/api/findings": self._api_findings,
                "/api/alerts": self._api_alerts,
                "/api/schedules": self._api_schedules,
                "/api/liveness": self._api_liveness,
            }
            handler = route_map.get(path)
            if handler is None:
                return self._text(404, "not found\n")
            handler(qs)
        except Exception:
            import traceback
            self._text(500, "internal error\n" + traceback.format_exc())

    def log_message(self, fmt: str, *args) -> None:  # noqa: N802
        return  # quiet

    # -- pages -------------------------------------------------------------

    def _page_overview(self, qs):
        c = self._conn()
        try:
            stats = c.execute(
                "SELECT protocol, COUNT(*) AS n FROM pages GROUP BY protocol"
            ).fetchall()
            total = c.execute("SELECT COUNT(*) n FROM pages").fetchone()["n"]
            links = c.execute("SELECT COUNT(*) n FROM links").fetchone()["n"]
            findings_n = c.execute("SELECT COUNT(*) n FROM findings").fetchone()["n"]
            alerts_n = c.execute("SELECT COUNT(*) n FROM alerts").fetchone()["n"]
            recent = c.execute(
                "SELECT url, title, protocol, score, fetched_at "
                "FROM pages ORDER BY fetched_at DESC LIMIT 25"
            ).fetchall()
        finally:
            c.close()
        kpis = "".join(
            f'<div class=kpi><div class=v>{html.escape(str(v))}</div>'
            f'<div class=k>{html.escape(k)}</div></div>'
            for k, v in (
                ("pages", total), ("links", links),
                ("findings", findings_n), ("alerts", alerts_n),
            )
        )
        proto_rows = "".join(
            f"<tr><td>{html.escape(r['protocol'] or '')}</td>"
            f"<td class=ok>{r['n']}</td></tr>"
            for r in stats
        )
        recent_rows = "".join(
            f"<tr><td><span class=pill>{html.escape(r['protocol'] or '')}</span></td>"
            f"<td>{html.escape((r['title'] or '')[:80] or '(no title)')}</td>"
            f"<td class=muted>{r['score']:.2f}</td>"
            f"<td><a class=url href=\"/page?u={urllib.parse.quote(r['url'])}\">"
            f"{html.escape(r['url'])}</a></td>"
            f"<td class=muted>{_fmt_ts(r['fetched_at'])}</td></tr>"
            for r in recent
        )
        body = (
            "<h2>OVERVIEW</h2>"
            f"<div>{kpis}</div>"
            "<h2>BY PROTOCOL</h2>"
            f"<table><thead><tr><th>protocol</th><th>pages</th></tr></thead>"
            f"<tbody>{proto_rows or '<tr><td colspan=2 class=muted>no data</td></tr>'}</tbody></table>"
            "<h2>RECENT FETCHES</h2>"
            f"<table><thead><tr><th>proto</th><th>title</th><th>score</th>"
            f"<th>url</th><th>when</th></tr></thead>"
            f"<tbody>{recent_rows or '<tr><td colspan=5 class=muted>no fetches yet</td></tr>'}</tbody></table>"
        )
        self._html(_layout("overview", body, active="overview"))

    def _page_pages(self, qs):
        q = (qs.get("q") or [""])[0].strip()
        proto = (qs.get("protocol") or [""])[0].strip()
        limit = _clamp_int(qs.get("limit"), default=50, lo=1, hi=500)
        offset = _clamp_int(qs.get("offset"), default=0, lo=0, hi=10**6)
        c = self._conn()
        try:
            if q:
                from darkcat.storage import Storage
                fts_q = Storage._sanitize_fts5(q)
                rows = c.execute(
                    "SELECT pages.url, pages.title, pages.protocol, pages.score, pages.fetched_at, "
                    "snippet(pages_fts, 2, '<<', '>>', '…', 12) AS sn "
                    "FROM pages_fts JOIN pages ON pages.rowid = pages_fts.rowid "
                    "WHERE pages_fts MATCH ? "
                    "ORDER BY pages.fetched_at DESC LIMIT ? OFFSET ?",
                    (fts_q, limit, offset),
                ).fetchall()
            else:
                clauses, params = ["1=1"], []
                if proto:
                    clauses.append("protocol = ?"); params.append(proto)
                rows = c.execute(
                    f"SELECT url, title, protocol, score, fetched_at, NULL AS sn "
                    f"FROM pages WHERE {' AND '.join(clauses)} "
                    f"ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
                    (*params, limit, offset),
                ).fetchall()
        finally:
            c.close()
        rows_html = "".join(
            f"<tr><td><span class=pill>{html.escape(r['protocol'] or '')}</span></td>"
            f"<td>{html.escape((r['title'] or '')[:80] or '(no title)')}<br>"
            f"<span class=snippet>{r['sn'] or ''}</span></td>"
            f"<td class=muted>{(r['score'] or 0):.2f}</td>"
            f"<td><a class=url href=\"/page?u={urllib.parse.quote(r['url'])}\">"
            f"{html.escape(r['url'])}</a></td>"
            f"<td class=muted>{_fmt_ts(r['fetched_at'])}</td></tr>"
            for r in rows
        )
        next_off = offset + limit
        prev_off = max(0, offset - limit)
        nav_links = (
            f'<a href="?q={urllib.parse.quote(q)}&offset={prev_off}&limit={limit}">prev</a> | '
            f'<a href="?q={urllib.parse.quote(q)}&offset={next_off}&limit={limit}">next</a>'
        )
        body = (
            f"<form class=search><input type=text name=q value=\"{html.escape(q)}\" "
            f"placeholder=\"FTS5 search (title/text)\">"
            f"<button>search</button></form>"
            f"<table><thead><tr><th>proto</th><th>title</th><th>score</th>"
            f"<th>url</th><th>when</th></tr></thead>"
            f"<tbody>{rows_html or '<tr><td colspan=5 class=muted>no matches</td></tr>'}</tbody></table>"
            f"<p class=muted>{len(rows)} row(s); offset={offset} limit={limit} — {nav_links}</p>"
        )
        self._html(_layout("pages", body, active="pages"))

    def _page_detail(self, qs):
        url = (qs.get("u") or [""])[0]
        if not url:
            return self._text(400, "missing ?u=URL\n")
        c = self._conn()
        try:
            row = c.execute(
                "SELECT * FROM pages WHERE url = ?", (url,)
            ).fetchone()
            if row is None:
                return self._text(404, "page not found\n")
            history = c.execute(
                "SELECT captured_at, content_hash FROM page_history "
                "WHERE url = ? ORDER BY captured_at DESC LIMIT 20",
                (url,),
            ).fetchall()
            outlinks = c.execute(
                "SELECT dst FROM links WHERE src = ? ORDER BY dst LIMIT 200",
                (url,),
            ).fetchall()
        finally:
            c.close()
        try:
            hits = json.loads(row["topic_hits"]) if row["topic_hits"] else {}
        except json.JSONDecodeError:
            hits = {}
        text_excerpt = (row["text"] or "")[:6000]
        hist_rows = "".join(
            f"<tr><td class=muted>{_fmt_ts(r['captured_at'])}</td>"
            f"<td class=muted>{r['content_hash'][:16]}…</td></tr>"
            for r in history
        )
        link_rows = "".join(
            f"<tr><td><a class=url href=\"/page?u={urllib.parse.quote(r['dst'])}\">"
            f"{html.escape(r['dst'])}</a></td></tr>" for r in outlinks
        )
        body = (
            f"<h2>{html.escape(row['title'] or '(no title)')}</h2>"
            f"<p><span class=pill>{html.escape(row['protocol'] or '')}</span> "
            f"<span class=muted>status={row['status']}, "
            f"score={row['score']:.2f}, fetched={_fmt_ts(row['fetched_at'])}</span></p>"
            f"<p class=url><a href=\"{html.escape(row['url'])}\">{html.escape(row['url'])}</a></p>"
            f"<h2>TEXT EXCERPT</h2><pre style=\"white-space:pre-wrap;background:#15171c;"
            f"border:1px solid #23262d;padding:12px;border-radius:4px\">{html.escape(text_excerpt)}</pre>"
            f"<h2>TOPIC HITS</h2><pre>{html.escape(json.dumps(hits, indent=2))}</pre>"
            f"<h2>HISTORY ({len(history)})</h2>"
            f"<table>{hist_rows or '<tr><td class=muted>no history</td></tr>'}</table>"
            f"<h2>OUTBOUND LINKS ({len(outlinks)})</h2>"
            f"<table>{link_rows or '<tr><td class=muted>no links</td></tr>'}</table>"
        )
        self._html(_layout(row["title"] or row["url"], body, active="pages"))

    def _page_findings(self, qs):
        cat = (qs.get("category") or [""])[0]
        limit = _clamp_int(qs.get("limit"), default=100, lo=1, hi=1000)
        c = self._conn()
        try:
            sql = "SELECT * FROM findings"
            params = []
            if cat:
                sql += " WHERE category = ?"; params.append(cat)
            sql += " ORDER BY found_at DESC LIMIT ?"; params.append(limit)
            rows = c.execute(sql, params).fetchall()
            cats = c.execute(
                "SELECT category, COUNT(*) AS n FROM findings GROUP BY category ORDER BY n DESC"
            ).fetchall()
        finally:
            c.close()
        cat_links = " · ".join(
            [f'<a href="/findings">all</a>'] +
            [f'<a href="/findings?category={urllib.parse.quote(r["category"])}">'
             f'{html.escape(r["category"])} ({r["n"]})</a>' for r in cats]
        )
        rows_html = "".join(
            f"<tr><td><span class=pill>{html.escape(r['category'])}</span></td>"
            f"<td>{html.escape(r['target'] or '')}</td>"
            f"<td class=muted>{(r['confidence'] or 0):.2f}</td>"
            f"<td><a class=url href=\"/page?u={urllib.parse.quote(r['url'])}\">"
            f"{html.escape(r['url'])}</a></td>"
            f"<td class=muted>{_fmt_ts(r['found_at'])}</td></tr>"
            for r in rows
        )
        body = (
            f"<p>{cat_links}</p>"
            f"<table><thead><tr><th>category</th><th>target</th>"
            f"<th>conf</th><th>url</th><th>when</th></tr></thead>"
            f"<tbody>{rows_html or '<tr><td colspan=5 class=muted>no findings</td></tr>'}</tbody></table>"
        )
        self._html(_layout("findings", body, active="findings"))

    def _page_alerts(self, qs):
        limit = _clamp_int(qs.get("limit"), default=200, lo=1, hi=2000)
        c = self._conn()
        try:
            rows = c.execute(
                "SELECT a.*, w.target AS w_target, w.category AS w_category, w.sink AS w_sink "
                "FROM alerts a LEFT JOIN watchlist w ON a.watch_id = w.id "
                "ORDER BY a.fired_at DESC LIMIT ?", (limit,),
            ).fetchall()
        finally:
            c.close()
        rows_html = "".join(
            f"<tr><td><span class=pill>{html.escape(r['w_category'] or '')}</span></td>"
            f"<td>{html.escape(r['w_target'] or '')}</td>"
            f"<td class=muted>{html.escape(r['w_sink'] or '')}</td>"
            f"<td>{html.escape(r['sink_status'] or '')}</td>"
            f"<td><a class=url href=\"/page?u={urllib.parse.quote(r['url'])}\">"
            f"{html.escape(r['url'])}</a></td>"
            f"<td class=muted>{_fmt_ts(r['fired_at'])}</td></tr>"
            for r in rows
        )
        body = (
            "<table><thead><tr><th>category</th><th>target</th><th>sink</th>"
            "<th>status</th><th>url</th><th>when</th></tr></thead>"
            f"<tbody>{rows_html or '<tr><td colspan=6 class=muted>no alerts</td></tr>'}</tbody></table>"
        )
        self._html(_layout("alerts", body, active="alerts"))

    def _page_schedules(self, qs):
        c = self._conn()
        try:
            rows = c.execute("SELECT * FROM schedules ORDER BY name").fetchall()
        finally:
            c.close()
        now = time.time()
        rows_html = ""
        for r in rows:
            if not r["enabled"]:
                when = '<span class=muted>paused</span>'
            else:
                eta = (r["next_run_at"] or 0) - now
                when = ('<span class=warn>due now</span>' if eta <= 0
                        else f'<span class=muted>in {int(eta)}s</span>')
            try:
                stats_str = json.loads(r["last_stats"]) if r["last_stats"] else None
            except json.JSONDecodeError:
                stats_str = None
            rows_html += (
                f"<tr><td>{'<span class=ok>on</span>' if r['enabled'] else '<span class=muted>off</span>'}</td>"
                f"<td><b>{html.escape(r['name'])}</b></td>"
                f"<td class=muted>every {r['interval_sec']}s</td>"
                f"<td>{when}</td>"
                f"<td class=muted>{_fmt_ts(r['last_run_at']) if r['last_run_at'] else '(never)'}</td>"
                f"<td>{html.escape(r['last_status'] or '')}</td>"
                f"<td class=muted>{html.escape(json.dumps(stats_str) if stats_str else '')}</td></tr>"
            )
        body = (
            "<table><thead><tr><th>state</th><th>name</th><th>interval</th>"
            "<th>next</th><th>last run</th><th>status</th><th>stats</th></tr></thead>"
            f"<tbody>{rows_html or '<tr><td colspan=7 class=muted>no schedules</td></tr>'}</tbody></table>"
            "<p class=muted>Schedules are managed via the CLI: "
            "<code>darkcat schedule add</code> / <code>list</code> / <code>remove</code>.</p>"
        )
        self._html(_layout("schedules", body, active="schedules"))

    def _page_mirrors(self, qs):
        c = self._conn()
        try:
            n = c.execute("SELECT COUNT(*) n FROM page_simhash").fetchone()["n"]
            recent = c.execute(
                "SELECT url, computed_at FROM page_simhash "
                "ORDER BY computed_at DESC LIMIT 50"
            ).fetchall()
        finally:
            c.close()
        rows_html = "".join(
            f"<tr><td><a class=url href=\"/page?u={urllib.parse.quote(r['url'])}\">"
            f"{html.escape(r['url'])}</a></td>"
            f"<td class=muted>{_fmt_ts(r['computed_at'])}</td></tr>"
            for r in recent
        )
        body = (
            f"<p>{n} fingerprinted page(s). Run "
            f"<code>darkcat mirrors</code> in the CLI for cluster computation.</p>"
            f"<table><thead><tr><th>url</th><th>fingerprinted</th></tr></thead>"
            f"<tbody>{rows_html or '<tr><td colspan=2 class=muted>no fingerprints — run `darkcat mirrors --rebuild`</td></tr>'}</tbody></table>"
        )
        self._html(_layout("mirrors", body, active="mirrors"))

    def _page_liveness(self, qs):
        only_down = (qs.get("down") or [""])[0] == "1"
        c = self._conn()
        try:
            rows = c.execute(
                """SELECT url, protocol, probed_at, ok, status, latency_ms,
                          bytes, content_hash, error
                   FROM liveness_probes
                   WHERE id IN (SELECT MAX(id) FROM liveness_probes GROUP BY url)
                   ORDER BY probed_at DESC LIMIT 500"""
            ).fetchall()
            total = c.execute(
                "SELECT COUNT(*) n FROM liveness_probes"
            ).fetchone()["n"]
            since = time.time() - 24 * 3600
            recent_ok = c.execute(
                "SELECT COUNT(*) n FROM liveness_probes WHERE probed_at >= ? AND ok = 1",
                (since,),
            ).fetchone()["n"]
            recent_total = c.execute(
                "SELECT COUNT(*) n FROM liveness_probes WHERE probed_at >= ?",
                (since,),
            ).fetchone()["n"]
        finally:
            c.close()
        if only_down:
            rows = [r for r in rows if not r["ok"]]
        kpis = "".join(
            f'<div class=kpi><div class=v>{html.escape(str(v))}</div>'
            f'<div class=k>{html.escape(k)}</div></div>'
            for k, v in (
                ("probes (all)", total),
                ("ok 24h", recent_ok),
                ("total 24h", recent_total),
                ("urls tracked", len(rows)),
            )
        )
        rows_html = ""
        for r in rows:
            state = ('<span class=ok>●</span>' if r["ok"]
                     else '<span class=fail>●</span>')
            err = (f"<br><span class=fail>{html.escape((r['error'] or '')[:120])}</span>"
                   if not r["ok"] and r["error"] else "")
            rows_html += (
                f"<tr><td>{state}</td>"
                f"<td><span class=pill>{html.escape(r['protocol'] or '')}</span></td>"
                f"<td class=muted>{r['status'] if r['status'] is not None else '-'}</td>"
                f"<td class=muted>{r['latency_ms'] if r['latency_ms'] is not None else '-'}ms</td>"
                f"<td class=muted>{r['bytes'] if r['bytes'] is not None else '-'}</td>"
                f"<td><a class=url href=\"/page?u={urllib.parse.quote(r['url'])}\">"
                f"{html.escape(r['url'])}</a>{err}</td>"
                f"<td class=muted>{_fmt_ts(r['probed_at'])}</td></tr>"
            )
        toggle = ('<a href="/liveness">all</a>' if only_down
                  else '<a href="/liveness?down=1">only-down</a>')
        body = (
            f"<div>{kpis}</div>"
            f"<p>{toggle}</p>"
            "<table><thead><tr><th></th><th>proto</th><th>status</th>"
            "<th>latency</th><th>bytes</th><th>url</th><th>last probe</th></tr></thead>"
            f"<tbody>{rows_html or '<tr><td colspan=7 class=muted>no probes — run `darkcat liveness probe --known`</td></tr>'}</tbody></table>"
        )
        self._html(_layout("liveness", body, active="liveness"))

    # -- json --------------------------------------------------------------

    def _api_stats(self, qs):
        c = self._conn()
        try:
            per_proto = {r["protocol"]: r["n"] for r in c.execute(
                "SELECT protocol, COUNT(*) AS n FROM pages GROUP BY protocol"
            )}
            total = c.execute("SELECT COUNT(*) n FROM pages").fetchone()["n"]
            links = c.execute("SELECT COUNT(*) n FROM links").fetchone()["n"]
            findings_n = c.execute("SELECT COUNT(*) n FROM findings").fetchone()["n"]
            alerts_n = c.execute("SELECT COUNT(*) n FROM alerts").fetchone()["n"]
        finally:
            c.close()
        self._json(200, {
            "total_pages": total, "links": links,
            "findings": findings_n, "alerts": alerts_n,
            "by_protocol": per_proto,
        })

    def _api_findings(self, qs):
        cat = (qs.get("category") or [""])[0]
        limit = _clamp_int(qs.get("limit"), default=100, lo=1, hi=2000)
        c = self._conn()
        try:
            sql = "SELECT * FROM findings"
            params = []
            if cat:
                sql += " WHERE category = ?"; params.append(cat)
            sql += " ORDER BY found_at DESC LIMIT ?"; params.append(limit)
            rows = [dict(r) for r in c.execute(sql, params).fetchall()]
        finally:
            c.close()
        self._json(200, rows)

    def _api_alerts(self, qs):
        limit = _clamp_int(qs.get("limit"), default=200, lo=1, hi=2000)
        c = self._conn()
        try:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM alerts ORDER BY fired_at DESC LIMIT ?", (limit,),
            ).fetchall()]
        finally:
            c.close()
        self._json(200, rows)

    def _api_schedules(self, qs):
        c = self._conn()
        try:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM schedules ORDER BY name"
            ).fetchall()]
        finally:
            c.close()
        self._json(200, rows)

    def _api_liveness(self, qs):
        only_down = (qs.get("down") or [""])[0] == "1"
        c = self._conn()
        try:
            rows = [dict(r) for r in c.execute(
                """SELECT * FROM liveness_probes
                   WHERE id IN (SELECT MAX(id) FROM liveness_probes GROUP BY url)
                   ORDER BY probed_at DESC LIMIT 1000"""
            ).fetchall()]
        finally:
            c.close()
        if only_down:
            rows = [r for r in rows if not r["ok"]]
        self._json(200, rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_ts(ts) -> str:
    if not ts:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except (TypeError, ValueError):
        return ""


def _clamp_int(values, *, default: int, lo: int, hi: int) -> int:
    if not values:
        return default
    try:
        v = int(values[0])
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _make_handler(db_path: str, token: str) -> type:
    return type(
        "_BoundHandler",
        (_Handler,),
        {"DB_PATH": db_path, "AUTH_TOKEN": token},
    )


def serve(db_path: str, bind: str, *, auth_token: str = "") -> int:
    if ":" not in bind:
        print(f"--bind expects HOST:PORT (got {bind!r})", file=sys.stderr)
        return 2
    host, port_str = bind.rsplit(":", 1)
    try:
        port = int(port_str)
    except ValueError:
        print(f"port must be integer (got {port_str!r})", file=sys.stderr)
        return 2
    if host in ("0.0.0.0", "::") and not auth_token:
        print(
            f"warning: binding to {host} with no --auth-token "
            "exposes the dashboard to anyone who can reach this port. "
            "Localhost is safer.",
            file=sys.stderr,
        )
    server = ThreadingHTTPServer(
        (host, port), _make_handler(db_path, auth_token),
    )
    auth_note = " (auth required)" if auth_token else ""
    print(
        f"darkcat dashboard listening on http://{host}:{port}/{auth_note}\n"
        f"  db = {db_path}\n"
        f"  pages: /  /pages  /findings  /alerts  /schedules  /mirrors\n"
        f"  json:  /api/stats  /api/findings  /api/alerts  /api/schedules"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.server_close()
    return 0


__all__ = ["serve"]
