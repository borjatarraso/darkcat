"""Onion / overlay-network liveness telemetry.

Periodically GETs known URLs through the right transport, records latency
+ status + body-hash, and surfaces drift over time.

Built on the existing :class:`darkcat.fetcher.Fetcher` so a probe goes
through the same Tor/I2P/Freenet stack as a normal crawl. We don't reuse
``Crawler`` because we deliberately *don't* want page parsing, link
extraction, FTS indexing, etc. — just "did it answer, how fast, did the
content change?"

Storage:

* ``liveness_probes`` row per attempt — see ``SCHEMA`` in storage.py.

Useful queries:

* "Which onions died in the last week?" → most recent ``ok=0`` per url.
* "Which onions changed their content?" → consecutive rows for a url
  where ``content_hash`` differs.

The CLI exposes ``darkcat liveness probe URL [URL ...]`` (one-shot) and
``darkcat liveness loop --interval``-mode for daemons.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from typing import Iterable, Optional

from darkcat.config import Config
from darkcat.fetcher import Fetcher, TransportError, TransportUnavailable
from darkcat.protocols import Protocol, classify, normalize
from darkcat.storage import Storage


log = logging.getLogger("darkcat.liveness")


def _record(
    storage: Storage,
    *,
    url: str,
    protocol: str,
    ok: bool,
    status: Optional[int],
    latency_ms: Optional[int],
    nbytes: Optional[int],
    content_hash: Optional[str],
    error: Optional[str],
) -> None:
    with storage.transaction() as c:
        c.execute(
            """INSERT INTO liveness_probes
               (url, protocol, probed_at, ok, status, latency_ms, bytes,
                content_hash, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (url, protocol, time.time(), 1 if ok else 0,
             status, latency_ms, nbytes, content_hash, error),
        )


def probe_one(fetcher: Fetcher, storage: Storage, url: str) -> dict:
    """Probe a single URL and persist a ``liveness_probes`` row.

    Returns a dict with the recorded fields so callers can render output
    without re-querying."""
    url = normalize(url)
    proto = classify(url).value
    started = time.monotonic()
    out: dict = {
        "url": url, "protocol": proto, "ok": False,
        "status": None, "latency_ms": None, "bytes": None,
        "content_hash": None, "error": None, "drift": False,
    }
    try:
        result = fetcher.fetch(url)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if result is None:
            out["error"] = "no result"
            _record(storage, url=url, protocol=proto, ok=False, status=None,
                    latency_ms=elapsed_ms, nbytes=None, content_hash=None,
                    error="no result")
            return out
        body = result.body or b""
        ch = hashlib.sha256(body).hexdigest() if body else None
        ok = 200 <= int(result.status or 0) < 400
        out.update({
            "ok": ok, "status": result.status,
            "latency_ms": elapsed_ms, "bytes": len(body),
            "content_hash": ch,
        })
        # Drift detection: did the latest content_hash for this url change?
        prev = _last_hash(storage, url)
        out["drift"] = bool(prev and ch and prev != ch)
        _record(
            storage, url=url, protocol=proto, ok=ok, status=result.status,
            latency_ms=elapsed_ms, nbytes=len(body), content_hash=ch,
            error=None if ok else f"http {result.status}",
        )
    except (TransportError, TransportUnavailable) as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        out["error"] = str(e)
        out["latency_ms"] = elapsed_ms
        _record(storage, url=url, protocol=proto, ok=False, status=None,
                latency_ms=elapsed_ms, nbytes=None, content_hash=None,
                error=str(e)[:300])
    except Exception as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        out["error"] = f"unexpected: {e}"
        out["latency_ms"] = elapsed_ms
        _record(storage, url=url, protocol=proto, ok=False, status=None,
                latency_ms=elapsed_ms, nbytes=None, content_hash=None,
                error=str(e)[:300])
    return out


def _last_hash(storage: Storage, url: str) -> Optional[str]:
    with storage._lock:
        row = storage.conn.execute(
            "SELECT content_hash FROM liveness_probes "
            "WHERE url = ? AND content_hash IS NOT NULL "
            "ORDER BY probed_at DESC LIMIT 1",
            (url,),
        ).fetchone()
    return row["content_hash"] if row else None


def probe_many(
    cfg: Config,
    storage: Storage,
    urls: Iterable[str],
    *,
    on_result=None,
) -> list[dict]:
    """Probe every URL in ``urls`` sequentially. Returns list of result dicts."""
    fetcher = Fetcher(cfg)
    out: list[dict] = []
    try:
        for u in urls:
            res = probe_one(fetcher, storage, u)
            out.append(res)
            if on_result is not None:
                try:
                    on_result(res)
                except Exception:
                    log.exception("on_result callback failed")
    finally:
        try:
            fetcher.save_cookies()
        except Exception:
            pass
    return out


def liveness_summary(storage: Storage, *, hours: float = 24.0) -> dict:
    """Aggregate stats for the last ``hours`` hours: total probes,
    unique urls, success-rate, by-protocol breakdown."""
    since = time.time() - hours * 3600
    with storage._lock:
        total = storage.conn.execute(
            "SELECT COUNT(*) n FROM liveness_probes WHERE probed_at >= ?",
            (since,),
        ).fetchone()["n"]
        ok = storage.conn.execute(
            "SELECT COUNT(*) n FROM liveness_probes "
            "WHERE probed_at >= ? AND ok = 1", (since,),
        ).fetchone()["n"]
        urls = storage.conn.execute(
            "SELECT COUNT(DISTINCT url) n FROM liveness_probes "
            "WHERE probed_at >= ?", (since,),
        ).fetchone()["n"]
        per_proto = {
            r["protocol"]: r["n"] for r in storage.conn.execute(
                "SELECT protocol, COUNT(*) AS n FROM liveness_probes "
                "WHERE probed_at >= ? GROUP BY protocol", (since,),
            )
        }
    return {
        "since_hours": hours,
        "total_probes": total,
        "ok_probes": ok,
        "unique_urls": urls,
        "success_rate": (ok / total) if total else 0.0,
        "by_protocol": per_proto,
    }


def latest_per_url(storage: Storage, limit: int = 200) -> list[sqlite3.Row]:
    """Most-recent probe per url, oldest-first by *latest probe time*."""
    with storage._lock:
        return storage.conn.execute(
            """SELECT url, protocol, probed_at, ok, status, latency_ms,
                      bytes, content_hash, error
               FROM liveness_probes
               WHERE id IN (
                   SELECT MAX(id) FROM liveness_probes GROUP BY url
               )
               ORDER BY probed_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()


def history_for(storage: Storage, url: str, limit: int = 100) -> list[sqlite3.Row]:
    with storage._lock:
        return storage.conn.execute(
            "SELECT * FROM liveness_probes WHERE url = ? "
            "ORDER BY probed_at DESC LIMIT ?",
            (url, limit),
        ).fetchall()


def known_urls(storage: Storage, *, protocol: Optional[str] = None,
               limit: int = 500) -> list[str]:
    """URLs we've crawled before — handy default for ``liveness probe``
    when the user doesn't pass any URLs."""
    sql = "SELECT url FROM pages"
    params: list = []
    if protocol:
        sql += " WHERE protocol = ?"; params.append(protocol)
    sql += " ORDER BY fetched_at DESC LIMIT ?"
    params.append(limit)
    with storage._lock:
        return [r["url"] for r in storage.conn.execute(sql, params).fetchall()]


__all__ = [
    "probe_one", "probe_many", "liveness_summary",
    "latest_per_url", "history_for", "known_urls",
]
