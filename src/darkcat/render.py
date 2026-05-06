"""Headless JS renderer for darkcat.

Optional Playwright-backed transport for JS-heavy onions and eepsites that
the plain ``requests``-based fetcher can't see (SPA forums, sites that
hydrate listings client-side, Cloudflare-style interstitials, etc.).

Design:

* Lazy import — Playwright is *not* a hard dependency. If it's missing,
  ``RenderUnavailable`` is raised the first time a render is requested,
  with installation hints; the rest of darkcat keeps working.
* Per-protocol proxy routing — Tor onions go through the SOCKS5 in
  ``Config.tor_socks_*``; I2P eepsites through the HTTP proxy in
  ``Config.i2p_http_*``; everything else direct.
* Single-browser session — starting Chromium is the expensive part; the
  ``Renderer`` is a context manager that keeps one browser alive across
  multiple ``render()`` calls (used by ``crawl --render``).

Public API::

    from darkcat.render import Renderer, RenderUnavailable, render_one

    # one-shot
    result = render_one(cfg, "http://forum.onion/")

    # session
    with Renderer(cfg) as r:
        for url in seeds:
            result = r.render(url)

Both return a :class:`darkcat.transports.FetchResult` so the existing
extractor / storage path is unchanged.
"""
from __future__ import annotations

import time
from typing import Optional

from darkcat.config import Config
from darkcat.protocols import Protocol, classify, normalize
from darkcat.transports import FetchResult, TransportError


class RenderUnavailable(TransportError):
    """Raised when Playwright (and Chromium) isn't installed."""


_INSTALL_HINT = (
    "Headless rendering requires Playwright.\n"
    "  pip install playwright\n"
    "  playwright install chromium\n"
)


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        return sync_playwright
    except ImportError as e:
        raise RenderUnavailable(_INSTALL_HINT) from e


def _proxy_for(cfg: Config, proto: Protocol) -> Optional[dict]:
    """Pick the right Playwright ``proxy=`` config for a given protocol.

    Returns ``None`` for protocols that should be fetched directly (clearnet
    HTTPS) or that don't make sense to render (Gemini / Gopher / IPFS API)."""
    # Tor onions — Chromium with ``socks5://...`` delegates DNS to the proxy,
    # which is exactly what we need for .onion resolution.
    if proto in (Protocol.TOR, Protocol.LOKINET):
        return {"server": f"socks5://{cfg.tor_socks_host}:{cfg.tor_socks_port}"}
    # I2P — http proxy in front of i2pd / Java I2P.
    if proto == Protocol.I2P:
        return {"server": f"http://{cfg.i2p_http_host}:{cfg.i2p_http_port}"}
    # Hyphanet / Freenet FProxy.
    if proto == Protocol.FREENET:
        return {"server": f"http://{cfg.freenet_fproxy_host}:{cfg.freenet_fproxy_port}"}
    # ZeroNet local UI.
    if proto == Protocol.ZERONET:
        return {"server": f"http://{cfg.zeronet_host}:{cfg.zeronet_port}"}
    return None


_RENDERABLE = {
    Protocol.CLEARNET, Protocol.TOR, Protocol.I2P,
    Protocol.LOKINET, Protocol.FREENET, Protocol.ZERONET, Protocol.YGGDRASIL,
    Protocol.CJDNS, Protocol.NAMECOIN, Protocol.EMERCOIN, Protocol.OPENNIC,
    Protocol.ENS, Protocol.HANDSHAKE, Protocol.HYPER, Protocol.UNSTOPPABLE,
}


def is_renderable(proto: Protocol) -> bool:
    """True if Playwright/Chromium can sensibly drive this protocol."""
    return proto in _RENDERABLE


class Renderer:
    """Context-manager that keeps one Chromium browser alive across renders.

    Use as::

        with Renderer(cfg) as r:
            res = r.render("http://forum.onion/")
    """

    def __init__(
        self,
        cfg: Config,
        *,
        timeout: float = 45.0,
        wait_until: str = "networkidle",
        max_response_bytes: Optional[int] = None,
        cookie_store=None,
    ) -> None:
        self.cfg = cfg
        self.timeout = timeout
        self.wait_until = wait_until
        self.max_response_bytes = max_response_bytes or cfg.max_response_bytes
        self.cookie_store = cookie_store
        # Auto-load when caller didn't pass one but config points at a jar.
        if self.cookie_store is None and getattr(cfg, "cookie_jar_path", None):
            try:
                from darkcat.auth import CookieStore
                self.cookie_store = CookieStore(cfg.cookie_jar_path)
            except Exception:
                self.cookie_store = None
        self._pw = None
        self._pw_ctx = None  # outer playwright handle (for stop)
        # one browser per (protocol -> proxy fingerprint) key, lazily started
        self._browsers: dict[str, object] = {}

    # ---- context manager -------------------------------------------------

    def __enter__(self) -> "Renderer":
        sync_playwright = _import_playwright()
        self._pw_ctx = sync_playwright()
        self._pw = self._pw_ctx.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for b in self._browsers.values():
            try:
                b.close()  # type: ignore[attr-defined]
            except Exception:
                pass
        self._browsers.clear()
        if self._pw_ctx is not None:
            try:
                self._pw_ctx.__exit__(exc_type, exc, tb)
            except Exception:
                pass
        self._pw = None
        self._pw_ctx = None

    # ---- core render -----------------------------------------------------

    def _browser_for(self, proxy: Optional[dict]):
        if self._pw is None:
            raise RenderUnavailable(
                "Renderer used outside its context-manager block. "
                "Wrap calls in `with Renderer(cfg) as r:`."
            )
        key = proxy["server"] if proxy else "_direct_"
        b = self._browsers.get(key)
        if b is None:
            launch_kwargs: dict = {
                "headless": True,
                # Chromium leaks DNS otherwise; --no-sandbox keeps us OK in
                # rootless containers and most desktop installs.
                "args": [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            }
            if proxy:
                launch_kwargs["proxy"] = proxy
            b = self._pw.chromium.launch(**launch_kwargs)  # type: ignore[union-attr]
            self._browsers[key] = b
        return b

    def render(self, url: str) -> FetchResult:
        url = normalize(url)
        proto = classify(url)
        if not is_renderable(proto):
            raise TransportError(
                f"protocol {proto.value} doesn't support JS rendering "
                f"(use the regular fetcher)"
            )
        proxy = _proxy_for(self.cfg, proto)
        browser = self._browser_for(proxy)
        ctx_kwargs: dict = {
            "user_agent": self.cfg.user_agent,
            "ignore_https_errors": True,
            "java_script_enabled": True,
            "viewport": {"width": 1280, "height": 800},
        }
        if self.cookie_store is not None:
            ctx_kwargs["storage_state"] = self.cookie_store.to_playwright_state()
        ctx = browser.new_context(**ctx_kwargs)  # type: ignore[union-attr]
        page = ctx.new_page()
        try:
            response = page.goto(
                url,
                timeout=int(self.timeout * 1000),
                wait_until=self.wait_until,
            )
            status = response.status if response else 0
            final_url = page.url
            content_type = (
                response.headers.get("content-type", "text/html")
                if response else "text/html"
            )
            html = page.content()
            body = html.encode("utf-8", "replace")[: self.max_response_bytes]
            # Merge cookies the page set back into our jar so a Playwright-
            # initiated login is visible to subsequent plain-requests fetches.
            if self.cookie_store is not None:
                try:
                    state = ctx.storage_state()
                    self.cookie_store.merge_playwright_cookies(state.get("cookies", []))
                except Exception:
                    pass
            return FetchResult(
                url=url,
                final_url=final_url,
                status=status,
                content_type=content_type,
                body=body,
                protocol=proto,
            )
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                ctx.close()
            except Exception:
                pass


def render_one(cfg: Config, url: str, *, timeout: float = 45.0) -> FetchResult:
    """One-shot helper: spin up a browser, render once, tear down."""
    with Renderer(cfg, timeout=timeout) as r:
        return r.render(url)


__all__ = [
    "Renderer", "RenderUnavailable", "render_one",
    "is_renderable", "_proxy_for",
]
