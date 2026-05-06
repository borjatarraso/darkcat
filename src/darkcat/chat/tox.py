"""Tox backend — stub.

Tox has C bindings (toxcore) but no maintained pure-Python client. The
two community libraries — ``py-toxcore-c`` and ``PyTox`` — both expect
you to compile against the system ``libtoxcore.so`` and have rough
asyncio integration. Rather than ship a half-working binding we surface
a placeholder: it knows how to *recognize* Tox identities (76-hex) and
how to point you at a real client, and that's it.

If you want darkcat to drive Tox for real, the cleanest path is to
shell out to ``qtox-cli`` (https://github.com/qTox/qTox) once that
ships, or wrap toxcore through ``ctypes`` here. PRs welcome.
"""
from __future__ import annotations

from darkcat.chat.base import (
    BackendUnavailable, ChatChannel, ChatMessage, Messenger,
)


DEP_NAME = "toxcore (C library) + ctypes wrapper"
INSTALL_HINT = (
    "No supported Python client. Install qTox or uTox for desktop use; "
    "darkcat will recognize Tox IDs in crawled pages but cannot send messages."
)

HAS_TOXCORE = False  # honest until someone wires up ctypes


class ToxMessenger(Messenger):
    network = "tox"

    def __init__(self, persona, *, sessions_dir=None) -> None:
        super().__init__(persona, sessions_dir=sessions_dir)
        raise BackendUnavailable(
            "tox backend is a stub — " + INSTALL_HINT
        )

    def connect(self): raise NotImplementedError
    def disconnect(self): raise NotImplementedError
    def list_channels(self, *, limit: int = 100): raise NotImplementedError
    def read(self, channel_id, *, limit: int = 50): raise NotImplementedError
    def send(self, channel_id, text): raise NotImplementedError


__all__ = ["ToxMessenger", "HAS_TOXCORE", "DEP_NAME", "INSTALL_HINT"]
