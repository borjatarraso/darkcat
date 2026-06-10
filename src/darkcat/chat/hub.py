"""Multi-protocol chat-hub aggregator.

The hub walks a :class:`~darkcat.personas.Vault`, picks every persona
whose ``provider`` (or legacy ``network``) field names a chat backend
darkcat knows about, and asks each backend to list its channels. The
result is a flat ``list[HubEntry]`` the CLI / TUI / GUI can render
side-by-side — operator sees every conversation across every account
in one view, tagged with both the messaging protocol (matrix, simplex,
telegram, ...) and the transport (tor:<iso>, i2p, clearnet, ...) the
account was created over.

Errors are absorbed per-entry: if Telegram's session is expired we
still want the Matrix accounts to render. Each entry carries an
``error`` string plus a coarse ``status`` flag (``ok`` / ``empty`` /
``unavailable`` / ``auth`` / ``error``) so frontends can colour it
without having to parse the exception text.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

from darkcat import chat as _chat
from darkcat.chat.base import AuthError, BackendUnavailable, ChatChannel


# Per-entry status codes the UI layer can switch on.
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_UNAVAILABLE = "unavailable"
STATUS_AUTH = "auth"
STATUS_ERROR = "error"


@dataclass
class HubEntry:
    """One row in the hub view — a persona × network pairing."""

    persona_name: str
    network: str
    transport: str = ""
    channels: list[ChatChannel] = field(default_factory=list)
    status: str = STATUS_OK
    error: str = ""
    elapsed_ms: int = 0

    @property
    def unread_total(self) -> int:
        return sum(int(c.unread or 0) for c in self.channels)

    def to_dict(self) -> dict:
        return {
            "persona": self.persona_name,
            "network": self.network,
            "transport": self.transport,
            "status": self.status,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "channels": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "kind": c.kind,
                    "participants": c.participants,
                    "unread": c.unread,
                }
                for c in self.channels
            ],
        }


def _persona_chat_network(persona) -> Optional[str]:
    """Pick the chat-backend network name for a persona, or None if
    the persona isn't a chat persona. Looks at ``provider`` first
    (vault v2), then falls back to the legacy ``network`` field for
    old vaults that stored "matrix" / "telegram" directly there."""
    known = set(_chat.known_networks())
    provider = (getattr(persona, "provider", "") or "").strip().lower()
    if provider in known:
        return provider
    network = (getattr(persona, "network", "") or "").strip().lower()
    if network in known:
        return network
    return None


def _select_personas(vault, networks: Optional[Iterable[str]] = None) -> list[tuple[object, str]]:
    """Return ``[(persona, network), …]`` for every chat-capable
    persona in ``vault``. ``networks``, when given, restricts to a
    subset (case-insensitive). Result is sorted by (network, name)
    for stable rendering."""
    wanted = {n.lower() for n in networks} if networks else None
    out: list[tuple[object, str]] = []
    for persona in vault.personas:
        net = _persona_chat_network(persona)
        if not net:
            continue
        if wanted and net not in wanted:
            continue
        out.append((persona, net))
    out.sort(key=lambda pn: (pn[1], pn[0].name))
    return out


def aggregate(
    vault,
    *,
    networks: Optional[Iterable[str]] = None,
    limit: int = 20,
) -> list[HubEntry]:
    """Build a list of :class:`HubEntry` for every chat-capable persona
    in ``vault``. Never raises — per-entry errors are captured in the
    returned objects so one broken backend doesn't blank the whole
    view.

    The hub deliberately calls ``connect()`` synchronously per persona;
    chat backends keep their session caches under
    ``~/.darkcat/chat-sessions/<persona>/`` so the second call is fast.
    ``limit`` is per-persona — keep it small (~20) for an interactive
    refresh loop, larger when exporting.
    """
    entries: list[HubEntry] = []
    for persona, network in _select_personas(vault, networks=networks):
        transport = (getattr(persona, "transport_used", "") or "").strip()
        entry = HubEntry(
            persona_name=persona.name,
            network=network,
            transport=transport,
        )
        start = time.monotonic()
        try:
            if not _chat.is_available(network):
                entry.status = STATUS_UNAVAILABLE
                entry.error = f"backend {network!r} dependency not installed"
                entries.append(entry)
                continue
            messenger = _chat.open_messenger(network, persona)
            try:
                messenger.connect()
                entry.channels = list(messenger.list_channels(limit=limit))
                entry.status = STATUS_OK if entry.channels else STATUS_EMPTY
            finally:
                try:
                    messenger.disconnect()
                except Exception:  # noqa: BLE001
                    pass
        except BackendUnavailable as e:
            entry.status = STATUS_UNAVAILABLE
            entry.error = str(e)[:200]
        except AuthError as e:
            entry.status = STATUS_AUTH
            entry.error = str(e)[:200]
        except Exception as e:  # noqa: BLE001
            entry.status = STATUS_ERROR
            entry.error = f"{type(e).__name__}: {e}"[:200]
        finally:
            entry.elapsed_ms = int((time.monotonic() - start) * 1000)
        entries.append(entry)
    return entries


def summarize(entries: list[HubEntry]) -> dict:
    """Return ``{personas, channels, unread, errors}`` totals for a
    summary line in the UI footer."""
    return {
        "personas": len(entries),
        "channels": sum(len(e.channels) for e in entries),
        "unread": sum(e.unread_total for e in entries),
        "errors": sum(1 for e in entries if e.status in (STATUS_AUTH, STATUS_ERROR, STATUS_UNAVAILABLE)),
    }


__all__ = [
    "HubEntry",
    "STATUS_OK",
    "STATUS_EMPTY",
    "STATUS_UNAVAILABLE",
    "STATUS_AUTH",
    "STATUS_ERROR",
    "aggregate",
    "summarize",
]
