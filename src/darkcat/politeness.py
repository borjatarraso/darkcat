"""Adaptive politeness + reactive Tor circuit rotation.

Two small pieces of state that the crawler consults around every fetch:

* :class:`HostBackoff` — tracks consecutive failures per host and serves an
  exponentially-growing backoff delay. After a successful fetch the host is
  reset. Caps at ``max_delay`` so a single bad onion doesn't freeze the run.

* :class:`TorRotator` — wraps :class:`darkcat.torctl.TorCtl` to fire
  ``SIGNAL NEWNYM`` after N consecutive errors on the same .onion host.
  Tor enforces a 10-second minimum between NEWNYMs (``MaxClientCircuitsPending``
  internally rate-limits), so we self-throttle to avoid the silent drop.

Both are best-effort: if the Tor control port is wrong / unreachable, the
rotator becomes a no-op rather than killing the crawl.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from darkcat.config import Config


log = logging.getLogger("darkcat.politeness")


# Tor's lower bound between NEWNYMs (see tor source: MIN_CIRCUIT_BUILD_INTERVAL).
# Sending another within this window is silently ignored.
TOR_NEWNYM_MIN_INTERVAL = 10.0


@dataclass
class HostBackoff:
    """Per-host exponential backoff over consecutive failures.

    Usage::

        bo = HostBackoff()
        bo.wait("forum.onion")          # sleep current backoff (0 if healthy)
        ok = try_fetch(...)
        if ok: bo.success("forum.onion")
        else:  bo.failure("forum.onion")
    """
    base_delay: float = 1.5
    max_delay: float = 60.0
    factor: float = 2.0
    fails: dict[str, int] = field(default_factory=dict)

    def _delay_for(self, host: str) -> float:
        n = self.fails.get(host, 0)
        if n <= 0:
            return 0.0
        # base * factor**(n-1), capped
        return min(self.max_delay, self.base_delay * (self.factor ** (n - 1)))

    def failure(self, host: str) -> int:
        """Record a failure; returns the new consecutive-failure count."""
        n = self.fails.get(host, 0) + 1
        self.fails[host] = n
        return n

    def success(self, host: str) -> None:
        self.fails.pop(host, None)

    def wait(self, host: str) -> float:
        """Sleep the current per-host backoff. Returns the delay applied."""
        d = self._delay_for(host)
        if d > 0:
            log.debug("backoff host=%s delay=%.2fs", host, d)
            time.sleep(d)
        return d

    def consecutive(self, host: str) -> int:
        return self.fails.get(host, 0)


class TorRotator:
    """Fires ``SIGNAL NEWNYM`` after N consecutive errors on a Tor host.

    The Tor control connection is opened lazily on first rotation request and
    kept open across rotations. Tor's 10-second NEWNYM rate-limit is enforced
    here so back-to-back failures don't waste signals.
    """

    def __init__(
        self,
        cfg: Config,
        *,
        newnym_after: int = 3,
        enabled: bool = True,
    ) -> None:
        self.cfg = cfg
        self.newnym_after = max(1, int(newnym_after))
        self.enabled = enabled
        self._ctl = None  # lazy TorCtl
        self._last_newnym: float = 0.0
        self._fail_streak: dict[str, int] = {}
        self._unavailable = False  # set True once we know Tor control is dead

    def _open(self):
        if not self.enabled or self._unavailable:
            return None
        if self._ctl is not None:
            return self._ctl
        try:
            from darkcat.torctl import TorCtl
            ctl = TorCtl(
                host=self.cfg.tor_socks_host,
                port=self.cfg.tor_control_port,
                password=self.cfg.tor_control_password,
                cookie_path=self.cfg.tor_control_cookie_path,
            )
            ctl.__enter__()
            self._ctl = ctl
            return ctl
        except Exception as e:
            log.warning("Tor control unavailable — circuit rotation disabled: %s", e)
            self._unavailable = True
            return None

    def close(self) -> None:
        if self._ctl is not None:
            try:
                self._ctl.__exit__(None, None, None)
            except Exception:
                pass
            self._ctl = None

    def on_failure(self, host: str) -> bool:
        """Account a failure for ``host``. If the streak hits the threshold
        (and the host is .onion-ish), fire NEWNYM, reset the streak, and
        return True. Otherwise return False."""
        if not self.enabled or self._unavailable:
            return False
        n = self._fail_streak.get(host, 0) + 1
        self._fail_streak[host] = n
        if n < self.newnym_after:
            return False
        # Threshold hit — try a rotation.
        if not host.endswith(".onion"):
            # Still reset so the counter doesn't grow unbounded for non-Tor hosts.
            self._fail_streak[host] = 0
            return False
        return self._fire(host)

    def on_success(self, host: str) -> None:
        self._fail_streak.pop(host, None)

    def _fire(self, host: str) -> bool:
        now = time.time()
        wait = TOR_NEWNYM_MIN_INTERVAL - (now - self._last_newnym)
        if wait > 0:
            log.info("NEWNYM rate-limit: sleeping %.1fs before signal", wait)
            time.sleep(wait)
        ctl = self._open()
        if ctl is None:
            return False
        try:
            resp = ctl.signal_newnym()
            self._last_newnym = time.time()
            self._fail_streak[host] = 0
            log.info("Tor NEWNYM fired (host=%s) -> %s", host, resp[:80])
            return True
        except Exception as e:
            log.warning("NEWNYM failed: %s", e)
            self._unavailable = True
            self.close()
            return False


__all__ = ["HostBackoff", "TorRotator", "TOR_NEWNYM_MIN_INTERVAL"]
