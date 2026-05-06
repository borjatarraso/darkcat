"""Persistent cookie jar for darkcat — authenticated crawls.

Most darknet forums (Dread, Breach mirrors, paywalled paste sites) gate
listings behind a login. Without a way to ride a session cookie we only ever
see the public landing page. This module provides a simple Netscape-format
cookie jar that:

* Persists across runs (default ``~/.darkcat/cookies.txt``).
* Attaches to every ``requests.Session`` built by HTTP-based transports.
* Exports to Playwright's ``storage_state`` format for the JS renderer, so
  ``--render`` and the plain transport see the same logged-in session.
* Lets the user populate it from a manual login: paste cookies in via
  ``darkcat cookies set`` or import a Netscape file exported from Firefox /
  Tor Browser via ``darkcat cookies import``.

OPSEC note: cookies are credentials. Treat the jar file as a secret and
never put it in a repo. The default location is ``~/.darkcat`` — same
directory as the crawl DB.
"""
from __future__ import annotations

import http.cookiejar
import time
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse


class CookieStore:
    """Wraps :class:`http.cookiejar.MozillaCookieJar` with a few darknet-
    friendly defaults and helpers for the CLI / Playwright integration."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path: Optional[Path] = Path(path) if path else None
        self.jar = http.cookiejar.MozillaCookieJar(
            str(self.path) if self.path else None
        )
        if self.path is not None and self.path.exists():
            try:
                # ignore_discard=True keeps session cookies (no Expires) on
                # disk — most darkweb auth tokens are session cookies.
                # ignore_expires=True is loose, but onions often clock-skew
                # against host time and we'd rather over-keep than lock the
                # user out of their own login.
                self.jar.load(ignore_discard=True, ignore_expires=True)
            except (OSError, http.cookiejar.LoadError):
                # Corrupt or unreadable jar — start fresh; don't crash.
                pass

    # ---- lifecycle ------------------------------------------------------

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.jar.save(ignore_discard=True, ignore_expires=True)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def attach(self, session) -> None:
        """Bind this jar to a ``requests.Session`` so cookies set during
        fetches accumulate into our store."""
        session.cookies = self.jar

    # ---- mutation -------------------------------------------------------

    def set(
        self,
        url: str,
        name: str,
        value: str,
        *,
        path: str = "/",
        secure: Optional[bool] = None,
        expires: Optional[int] = None,
    ) -> None:
        """Set a single cookie scoped to the host of ``url``.

        ``secure`` defaults to True for ``https://`` and False otherwise.
        ``expires`` defaults to one year from now."""
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not host:
            raise ValueError(f"can't extract host from {url!r}")
        if secure is None:
            secure = parsed.scheme in ("https", "gemini")
        if expires is None:
            expires = int(time.time()) + 365 * 24 * 3600
        c = http.cookiejar.Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=host,
            domain_specified=True,
            domain_initial_dot=False,
            path=path,
            path_specified=True,
            secure=secure,
            expires=expires,
            discard=False,
            comment=None,
            comment_url=None,
            rest={"HttpOnly": None},
            rfc2109=False,
        )
        self.jar.set_cookie(c)

    def merge_playwright_cookies(self, cookies: Iterable[dict]) -> int:
        """Update jar from Playwright's ``storage_state['cookies']`` shape.
        Returns the number of cookies added/updated."""
        n = 0
        for c in cookies:
            domain = c.get("domain") or ""
            if not domain:
                continue
            expires = c.get("expires", -1)
            cookie = http.cookiejar.Cookie(
                version=0,
                name=c.get("name", ""),
                value=c.get("value", ""),
                port=None, port_specified=False,
                domain=domain,
                domain_specified=True,
                domain_initial_dot=domain.startswith("."),
                path=c.get("path") or "/",
                path_specified=True,
                secure=bool(c.get("secure", False)),
                expires=int(expires) if expires and expires > 0 else None,
                discard=expires == -1,
                comment=None, comment_url=None,
                rest={}, rfc2109=False,
            )
            self.jar.set_cookie(cookie)
            n += 1
        return n

    def import_from(self, src_path: Path) -> int:
        """Merge cookies from a Netscape-format file (Firefox / Tor Browser
        exports work). Returns the number of cookies added."""
        other = http.cookiejar.MozillaCookieJar(str(src_path))
        other.load(ignore_discard=True, ignore_expires=True)
        n = 0
        for c in other:
            self.jar.set_cookie(c)
            n += 1
        return n

    def clear(self, host: Optional[str] = None) -> int:
        """Remove cookies (all, or just those whose domain matches ``host``)."""
        if host is None:
            n = len(list(self.jar))
            self.jar.clear()
            return n
        host = host.lower().lstrip(".")
        victims = [
            c for c in self.jar
            if (c.domain or "").lower().lstrip(".").endswith(host)
        ]
        for c in victims:
            self.jar.clear(c.domain, c.path, c.name)
        return len(victims)

    # ---- introspection / export -----------------------------------------

    def list(self, host: Optional[str] = None) -> list[http.cookiejar.Cookie]:
        host_l = host.lower().lstrip(".") if host else None
        out = []
        for c in self.jar:
            if host_l is None or (c.domain or "").lower().lstrip(".").endswith(host_l):
                out.append(c)
        return out

    def to_playwright_state(self) -> dict:
        """Return a dict suitable for ``browser.new_context(storage_state=…)``.

        Playwright's cookie schema is slightly different from Netscape's —
        it wants ``sameSite`` and uses ``-1`` for "session-only" expires."""
        cookies = []
        for c in self.jar:
            cookies.append({
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path or "/",
                "expires": int(c.expires) if c.expires else -1,
                "httpOnly": False,  # MozillaCookieJar doesn't track this
                "secure": bool(c.secure),
                "sameSite": "Lax",
            })
        return {"cookies": cookies, "origins": []}


def open_store(cfg) -> Optional[CookieStore]:
    """Convenience: return a CookieStore if the config points at one."""
    path = getattr(cfg, "cookie_jar_path", None)
    if path is None:
        return None
    return CookieStore(path)


__all__ = ["CookieStore", "open_store"]
