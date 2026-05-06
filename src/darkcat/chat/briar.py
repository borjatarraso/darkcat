"""Briar backend — stub (intentionally inert).

Briar is mobile-first: there is no desktop client and no headless
daemon. The protocol — Bramble Transport Protocol over Bluetooth /
Wi-Fi / Tor — is documented but the only reference implementation
runs on Android. ``briar-headless`` (a JVM daemon with a REST API)
exists but is alpha-quality and not packaged on most distros.

Even if you ran briar-headless, the design assumption is that you
*present* the device in person to bootstrap a mutual contact: scanning
each other's QR codes proves both sides hold the secret needed to
deduplicate-the-channel. That step has no clean automation story —
which is the point. Friend-to-friend networks are uncrawlable by
construction; that is a feature.

Darkcat surfaces ``briar://`` invite links via the scanner so you can
manually accept them in a real Briar app, and that's the most useful
thing we can do here without compromising the network's threat model.
"""
from __future__ import annotations

from darkcat.chat.base import (
    BackendUnavailable, ChatChannel, ChatMessage, Messenger,
)


DEP_NAME = "briar-headless (Android-only or JVM daemon)"
INSTALL_HINT = (
    "Briar has no Python client. Install briar-headless and accept "
    "invite links there. Darkcat extracts briar:// links from crawled "
    "pages but cannot crawl the network itself."
)

HAS_BRIAR = False


class BriarMessenger(Messenger):
    network = "briar"

    def __init__(self, persona, *, sessions_dir=None) -> None:
        super().__init__(persona, sessions_dir=sessions_dir)
        raise BackendUnavailable(
            "briar backend is a stub — " + INSTALL_HINT
        )

    def connect(self): raise NotImplementedError
    def disconnect(self): raise NotImplementedError
    def list_channels(self, *, limit: int = 100): raise NotImplementedError
    def read(self, channel_id, *, limit: int = 50): raise NotImplementedError
    def send(self, channel_id, text): raise NotImplementedError


__all__ = ["BriarMessenger", "HAS_BRIAR", "DEP_NAME", "INSTALL_HINT"]
