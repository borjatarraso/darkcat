# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Transport selection and per-identity pinning.

The identity workflow needs two things from a transport:

1. A *choice* — tor / i2p / proxy chain / vpn-pinned-to-another-identity
   — so the signup request leaves the host through something other than
   the operator's real exit IP.
2. A *stable token* — a short string we can store on the persona so that
   re-logging-in later goes back through a circuit / exit that the
   provider has already seen for that account. Switching exits between
   sessions is one of the more reliable triggers for "verify your
   account" challenges; keeping a per-identity isolation key avoids it.

This module is deliberately thin. It defers the actual networking to
:mod:`darkcat.transports` (for fetches) and :mod:`darkcat.config`
(for SOCKS coordinates) and only deals with which knob to turn.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from darkcat.config import Config


KIND_TOR = "tor"
KIND_I2P = "i2p"
KIND_PROXY = "proxy"
KIND_VPN_PIN = "vpn-pin"   # reuse another identity's exit (a stored VPN persona)
KIND_VALUES = (KIND_TOR, KIND_I2P, KIND_PROXY, KIND_VPN_PIN)


@dataclass
class TransportChoice:
    """How a single identity should reach its provider.

    ``token`` is the *pinning* value — store it on the persona and pass
    it back here on subsequent logins to recreate the same circuit /
    isolation key. For Tor we hash it into the SOCKS auth pair, which
    Tor (with IsolateSOCKSAuth) treats as a circuit-isolation key.
    """

    kind: str
    token: str
    detail: Optional[str] = None  # human-readable: "via 127.0.0.1:9050"

    def proxies_for(self, cfg: Config) -> dict:
        """Return a ``requests``-compatible proxies dict for this choice.

        The dict can be passed straight to :func:`requests.get` /
        :func:`requests.post`, and it's what the manual-assist browser
        launcher will read to set ``HTTP_PROXY`` / ``HTTPS_PROXY``.
        """
        if self.kind == KIND_TOR:
            url = (
                f"socks5h://iso:{self.token}@"
                f"{cfg.tor_socks_host}:{cfg.tor_socks_port}"
            )
            return {"http": url, "https": url}
        if self.kind == KIND_I2P:
            return cfg.i2p_proxies
        if self.kind == KIND_PROXY:
            # Token *is* the proxy URL when caller passed a custom chain.
            return {"http": self.token, "https": self.token}
        if self.kind == KIND_VPN_PIN:
            # The token here is the persona name of a stored VPN identity;
            # the caller resolves it to a proxy URL (out of scope for this
            # module, since it would need to bring up the VPN session).
            raise NotImplementedError(
                "vpn-pin transports require an external VPN session manager; "
                "set the VPN up first, then use --transport proxy with its "
                "local SOCKS endpoint"
            )
        raise ValueError(f"unknown transport kind: {self.kind!r}")


def transport_token(seed: str) -> str:
    """Stable 16-hex token derived from ``seed``.

    Used as the SOCKS isolation key on Tor: same seed → same circuit
    every time. The seed should be something tied to the identity but
    *not* the password — typically the persona name or its UUID.
    """
    return hashlib.sha256(seed.encode("utf-8", "replace")).hexdigest()[:16]


def pick_transport(
    kind: str,
    *,
    seed: str,
    proxy_url: Optional[str] = None,
    pin_to: Optional[str] = None,
) -> TransportChoice:
    """Materialise a transport choice for a new (or returning) identity.

    - ``kind`` is one of :data:`KIND_VALUES`.
    - ``seed`` becomes the pinning key — usually the persona name. Two
      calls with the same seed and kind produce the same token.
    - ``proxy_url`` is required when ``kind == 'proxy'``.
    - ``pin_to`` is required when ``kind == 'vpn-pin'`` and names a
      stored VPN-category persona.
    """
    if kind not in KIND_VALUES:
        raise ValueError(
            f"unknown transport kind {kind!r}; expected one of {KIND_VALUES}"
        )
    if kind == KIND_TOR:
        token = transport_token(seed)
        return TransportChoice(kind=kind, token=token, detail="tor SOCKS isolation")
    if kind == KIND_I2P:
        return TransportChoice(kind=kind, token=transport_token(seed), detail="i2p HTTP proxy")
    if kind == KIND_PROXY:
        if not proxy_url:
            raise ValueError("transport=proxy requires --proxy-url")
        return TransportChoice(kind=kind, token=proxy_url, detail=f"proxy {proxy_url}")
    if kind == KIND_VPN_PIN:
        if not pin_to:
            raise ValueError("transport=vpn-pin requires --pin-to <persona-name>")
        return TransportChoice(kind=kind, token=pin_to, detail=f"pinned to vpn persona {pin_to}")
    raise AssertionError("unreachable")  # pragma: no cover


def describe_token(token: Optional[str]) -> str:
    """Human-readable summary for ``identity show`` / list views."""
    if not token:
        return "-"
    if len(token) == 16 and all(c in "0123456789abcdef" for c in token):
        return f"tor:{token[:8]}…"
    if token.startswith(("socks5://", "socks5h://", "http://", "https://")):
        # A proxy URL — strip credentials before printing.
        try:
            from urllib.parse import urlparse
            u = urlparse(token)
            return f"proxy:{u.scheme}://{u.hostname}:{u.port or '?'}"
        except Exception:
            return "proxy:…"
    return token


__all__ = [
    "KIND_TOR",
    "KIND_I2P",
    "KIND_PROXY",
    "KIND_VPN_PIN",
    "KIND_VALUES",
    "TransportChoice",
    "describe_token",
    "pick_transport",
    "transport_token",
]
