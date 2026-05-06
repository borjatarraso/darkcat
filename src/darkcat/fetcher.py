from __future__ import annotations

import logging
from typing import Optional

from darkcat.config import Config
from darkcat.protocols import Protocol, classify, normalize
from darkcat.transports import (
    FetchResult,
    TransportError,
    TransportUnavailable,
    build_transports,
)

log = logging.getLogger("darkcat.fetcher")


class Fetcher:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        # Single CookieStore is owned here; transports share a reference. A
        # login set during one fetch persists across the whole crawl and (if
        # cfg.cookie_jar_path is set) is saved back to disk on `save()`.
        self.cookie_store = None
        if getattr(cfg, "cookie_jar_path", None) is not None:
            try:
                from darkcat.auth import CookieStore
                self.cookie_store = CookieStore(cfg.cookie_jar_path)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                # Cookie jar load failure must not silently disable auth;
                # log it so the user can see why login state isn't sticking.
                log.warning("cookie store unavailable: %s: %s",
                            type(e).__name__, e)
                self.cookie_store = None
        self.transports = build_transports(cfg, cookie_store=self.cookie_store)

    def protocol_for(self, url: str) -> Protocol:
        return classify(normalize(url))

    def status(self) -> dict[Protocol, bool]:
        return {p: t.check() for p, t in self.transports.items()}

    def fetch(self, url: str) -> Optional[FetchResult]:
        url = normalize(url)
        proto = classify(url)
        transport = self.transports.get(proto)
        if transport is None:
            raise TransportError(f"No transport for protocol {proto}")
        return transport.fetch(url)

    def save_cookies(self) -> None:
        """Flush the shared cookie jar to disk. Idempotent / safe if not configured."""
        if self.cookie_store is not None:
            try:
                self.cookie_store.save()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                log.warning("cookie save failed: %s: %s", type(e).__name__, e)

    def close(self) -> None:
        """Best-effort teardown for transports and the cookie jar.

        Called from the GUI/TUI on app exit so we don't leak HTTP sessions
        or leave a dirty cookie jar on disk.
        """
        self.save_cookies()
        for t in self.transports.values():
            close = getattr(t, "close", None)
            if callable(close):
                try:
                    close()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception as e:
                    log.debug("transport close failed: %s: %s",
                              type(e).__name__, e)


__all__ = ["Fetcher", "FetchResult", "TransportError", "TransportUnavailable"]
