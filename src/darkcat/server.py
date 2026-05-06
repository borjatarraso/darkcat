"""HIBP-style read-only HTTP server over the findings table.

Endpoints (all GET, plain text responses):
    /healthz                    "ok"
    /                           help text
    /range/<3..8 hex chars>     one line per match: <suffix>:<n>:<cat>:<proto>
    /digest/<64 hex chars>      <category>:<protocol>:<count> or 404

The findings DB never stores raw secrets — only salted SHA-256 digests —
so this endpoint is safe to expose internally to other security tooling.
Bind to localhost by default; binding to 0.0.0.0 prints a warning.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


_HEX_RX = re.compile(r"^[0-9a-f]+$")
_HELP = (
    "darkcat range server\n"
    "  GET /healthz\n"
    "  GET /range/<3..8 hex chars>\n"
    "  GET /digest/<64 hex chars>\n"
)


def _hex(s: str, lo: int, hi: int) -> bool:
    return lo <= len(s) <= hi and bool(_HEX_RX.fullmatch(s))


class _Handler(BaseHTTPRequestHandler):
    DB_PATH: str = ""

    def _text(self, code: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            return self._text(200, "ok\n")
        if path in ("/", ""):
            return self._text(200, _HELP)
        if path.startswith("/range/"):
            prefix = path[len("/range/"):].lower()
            if not _hex(prefix, 3, 8):
                return self._text(400, "bad prefix; expect 3..8 hex chars\n")
            conn = self._conn()
            try:
                rows = conn.execute(
                    "SELECT digest, category, protocol, COUNT(*) AS n "
                    "FROM findings WHERE digest LIKE ? "
                    "GROUP BY digest, category, protocol "
                    "ORDER BY digest LIMIT 5000",
                    (prefix + "%",),
                ).fetchall()
            finally:
                conn.close()
            body = "\n".join(
                f"{r['digest'][len(prefix):]}:{r['n']}:{r['category']}:{r['protocol']}"
                for r in rows
            )
            return self._text(200, body + ("\n" if body else ""))
        if path.startswith("/digest/"):
            digest = path[len("/digest/"):].lower()
            if not _hex(digest, 64, 64):
                return self._text(400, "bad digest; expect 64 hex chars\n")
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT category, protocol, COUNT(*) AS n FROM findings "
                    "WHERE digest = ? GROUP BY category, protocol",
                    (digest,),
                ).fetchone()
            finally:
                conn.close()
            if not row:
                return self._text(404, "not found\n")
            return self._text(200, f"{row['category']}:{row['protocol']}:{row['n']}\n")
        return self._text(404, "not found\n")

    def log_message(self, fmt: str, *args) -> None:  # noqa: N802
        # Quiet default access log; users wanting one can wrap behind nginx.
        return


def _make_handler(db_path: str) -> type:
    return type("_BoundHandler", (_Handler,), {"DB_PATH": db_path})


def serve(db_path: str, bind: str) -> int:
    if ":" not in bind:
        print(f"--bind expects HOST:PORT (got {bind!r})", file=sys.stderr)
        return 2
    host, port_str = bind.rsplit(":", 1)
    try:
        port = int(port_str)
    except ValueError:
        print(f"port must be integer (got {port_str!r})", file=sys.stderr)
        return 2
    if host in ("0.0.0.0", "::"):
        print(
            f"warning: binding to {host} exposes the findings range "
            "endpoint to the network. Localhost is safer.",
            file=sys.stderr,
        )
    server = ThreadingHTTPServer((host, port), _make_handler(db_path))
    print(
        f"darkcat range server listening on http://{host}:{port}/  "
        f"(db={db_path})\nGET /range/<prefix>  GET /digest/<full>  GET /healthz"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.server_close()
    return 0
