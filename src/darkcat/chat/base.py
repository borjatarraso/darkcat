"""Common chat-backend abstractions for darkcat.

A *Messenger* is the unified surface darkcat exposes for any messaging
network — Telegram, Matrix, XMPP, SimpleX, Session, Tox, etc. Concrete
backends live in sibling modules and register themselves with the
registry in :mod:`darkcat.chat`.

Design notes
------------

We deliberately do not use :mod:`asyncio` in the public surface. Some
backends are async-native (matrix-nio, telethon, slixmpp), some are
sync (shell-out to ``session-cli`` or ``simplex-chat``), and a few are
neither (mobile-only Briar). Forcing every caller to choose a single
event-loop dialect would make the CLI awkward. Instead, async backends
keep an internal event loop and expose blocking, conventional methods.
This trades a little throughput for a much smaller cognitive surface.

The :class:`Messenger` ABC is intentionally minimal — five methods plus
two dataclasses. If a backend can do more (file uploads, reactions,
typing indicators), it should expose those as backend-specific helpers
rather than bloating the base. The CLI only uses the lowest common
denominator; richer features are accessible from Python code.

Persona integration
-------------------

Each Messenger carries a reference to its :class:`darkcat.personas.Persona`.
The persona's ``handle`` doubles as the auth identity, ``password`` as
the password / token, and ``recovery`` as a backup phrase or device-key
seed when the protocol has one. Per-backend session files (Telethon
``.session``, Matrix store DB, XMPP cert) live under
``~/.darkcat/chat-sessions/<persona-name>/`` so a persona is a
self-contained bundle of "everything needed to act as this identity".
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class ChatChannel:
    """One conversation surface. ``id`` is whatever the backend uses to
    address it (Telegram int, Matrix room id, XMPP JID, SimpleX queue
    URI). ``name`` is the human-readable label. ``kind`` is one of
    ``dm``, ``group``, ``channel`` — backend-defined; used only for
    presentation."""

    id: str
    name: str
    kind: str = "dm"
    participants: int = 0
    unread: int = 0
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ChatMessage:
    """One message. ``ts`` is a unix timestamp in seconds (float). The
    ``raw`` field is whatever native object the backend returned, so
    advanced callers can downcast for things the abstract layer drops
    (reactions, edits, replies, attachments)."""

    channel_id: str
    msg_id: str
    sender: str
    text: str
    ts: float
    raw: object = None


class MessengerError(RuntimeError):
    """Base exception for backend errors. Backends should subclass this
    when they want callers to be able to react specifically to e.g.
    ``RateLimitError`` or ``AuthError``."""


class AuthError(MessengerError):
    """Authentication failed — bad password, expired token, missing
    2FA code, account locked, etc. The CLI surfaces this with a hint
    to re-run ``darkcat chat login``."""


class BackendUnavailable(MessengerError):
    """The optional dependency / external binary that this backend
    needs is not installed. The CLI uses this to print a one-liner
    install hint instead of a stack trace."""


class Messenger(abc.ABC):
    """Abstract interface for a messaging backend.

    Lifetime: ``connect()`` once, then any number of read/send/list
    calls, then ``disconnect()``. Concrete backends should be safe to
    instantiate without connecting (the constructor must not block on
    network I/O).

    Methods raise :class:`MessengerError` on protocol-level failures.
    A returned empty list is **not** an error — it just means no rooms /
    no recent messages.
    """

    #: Short name of the network ("telegram", "matrix", ...). Subclasses
    #: must override.
    network: str = "abstract"

    def __init__(
        self,
        persona,
        *,
        sessions_dir: Optional[Path] = None,
    ) -> None:
        self.persona = persona
        self.sessions_dir = (
            Path(sessions_dir) if sessions_dir
            else Path.home() / ".darkcat" / "chat-sessions" / persona.name
        )
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.sessions_dir.chmod(0o700)
        except OSError:
            pass
        self._connected: bool = False

    # ---- lifecycle (override these) --------------------------------

    @abc.abstractmethod
    def connect(self) -> None:
        """Authenticate and open a session. Idempotent — calling twice
        is a no-op. Raises :class:`AuthError` if the persona's stored
        credentials are invalid or absent."""

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Close the session cleanly. Safe to call from a finally
        block even if connect() failed."""

    # ---- queries (override these) ----------------------------------

    @abc.abstractmethod
    def list_channels(self, *, limit: int = 100) -> list[ChatChannel]:
        """Return the channels / rooms / DMs this persona is in."""

    @abc.abstractmethod
    def read(
        self,
        channel_id: str,
        *,
        limit: int = 50,
    ) -> list[ChatMessage]:
        """Return the most recent ``limit`` messages from a channel,
        oldest-first inside the returned list."""

    @abc.abstractmethod
    def send(self, channel_id: str, text: str) -> ChatMessage:
        """Post ``text`` to ``channel_id``. Returns the canonical
        ChatMessage the backend persisted (populated msg_id, server
        ts, etc.)."""

    # ---- conveniences ----------------------------------------------

    def is_connected(self) -> bool:
        return self._connected

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.disconnect()
        finally:
            self._connected = False
        return False


__all__ = [
    "ChatChannel",
    "ChatMessage",
    "Messenger",
    "MessengerError",
    "AuthError",
    "BackendUnavailable",
]
