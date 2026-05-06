"""Ricochet backend — stub.

The original Ricochet (v2 onions, 2015–2019) is unmaintained. Its
successor, **Ricochet Refresh** (v3 onions), has a desktop GUI but no
daemon mode and no programmatic API; all I/O is done through the GUI's
local Qt event loop.

Until Ricochet Refresh ships an RPC surface we treat this backend the
same way as Briar: we recognize ``ricochet:<onion-address>`` URIs in
crawled content but we don't try to drive a chat session.
"""
from __future__ import annotations

from darkcat.chat.base import (
    BackendUnavailable, ChatChannel, ChatMessage, Messenger,
)


DEP_NAME = "ricochet-refresh"
INSTALL_HINT = (
    "Ricochet Refresh is GUI-only. Darkcat extracts ricochet: URIs from "
    "crawled pages but cannot drive a chat. Use the official desktop client."
)

HAS_RICOCHET = False


class RicochetMessenger(Messenger):
    network = "ricochet"

    def __init__(self, persona, *, sessions_dir=None) -> None:
        super().__init__(persona, sessions_dir=sessions_dir)
        raise BackendUnavailable(
            "ricochet backend is a stub — " + INSTALL_HINT
        )

    def connect(self): raise NotImplementedError
    def disconnect(self): raise NotImplementedError
    def list_channels(self, *, limit: int = 100): raise NotImplementedError
    def read(self, channel_id, *, limit: int = 50): raise NotImplementedError
    def send(self, channel_id, text): raise NotImplementedError


__all__ = ["RicochetMessenger", "HAS_RICOCHET", "DEP_NAME", "INSTALL_HINT"]
