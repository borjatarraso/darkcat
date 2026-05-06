"""Chat-backend registry for darkcat.

Each backend module is imported lazily — we don't want to pay for
loading ``telethon`` (~5 MB at import) every time someone runs
``darkcat status``. The registry tracks which backends are available
(their dependency is installed and the binary, if any, is on $PATH)
and instantiates them on demand against a persona.

Usage from Python::

    from darkcat.chat import open_messenger
    from darkcat.personas import Vault

    vault = Vault()
    persona = vault.get("alice-tg")
    with open_messenger("telegram", persona) as m:
        for ch in m.list_channels():
            print(ch.name, ch.id)
"""
from __future__ import annotations

import importlib
from typing import Optional

from darkcat.chat.base import (
    AuthError,
    BackendUnavailable,
    ChatChannel,
    ChatMessage,
    Messenger,
    MessengerError,
)


# Backend registry: (network name, module path, "marker" attribute that
# the module guarantees to expose iff its optional dependency is
# satisfied — e.g. ``HAS_TELETHON``). If ``HAS_*`` is False, the backend
# can still be instantiated to render a helpful "missing dep" error.
_BACKENDS: dict[str, tuple[str, str]] = {
    "telegram": ("darkcat.chat.telegram", "HAS_TELETHON"),
    "matrix":   ("darkcat.chat.matrix",   "HAS_NIO"),
    "xmpp":     ("darkcat.chat.xmpp",     "HAS_SLIXMPP"),
    "simplex":  ("darkcat.chat.simplex",  "HAS_SIMPLEX_CLI"),
    "session":  ("darkcat.chat.session",  "HAS_SESSION_CLI"),
    "tox":      ("darkcat.chat.tox",      "HAS_TOXCORE"),
    "briar":    ("darkcat.chat.briar",    "HAS_BRIAR"),
    "ricochet": ("darkcat.chat.ricochet", "HAS_RICOCHET"),
}


def known_networks() -> list[str]:
    """Names every backend module knows about, regardless of install state."""
    return list(_BACKENDS.keys())


def _import_backend(network: str):
    if network not in _BACKENDS:
        raise MessengerError(
            f"unknown chat network {network!r}; "
            f"known: {', '.join(_BACKENDS)}"
        )
    mod_path, _ = _BACKENDS[network]
    try:
        return importlib.import_module(mod_path)
    except ImportError as e:
        raise BackendUnavailable(
            f"backend {network} could not be imported: {e}"
        ) from e


def is_available(network: str) -> bool:
    """Return True iff the backend's optional dependency is installed."""
    try:
        mod = _import_backend(network)
    except (MessengerError, BackendUnavailable):
        return False
    _, marker = _BACKENDS[network]
    return bool(getattr(mod, marker, False))


def availability_report() -> list[dict]:
    """Return a list-of-dicts suitable for ``darkcat chat backends``.

    Each entry: ``{network, available, dep, hint}`` — never throws."""
    out: list[dict] = []
    for net in _BACKENDS:
        try:
            mod = _import_backend(net)
        except BackendUnavailable as e:
            out.append({
                "network": net,
                "available": False,
                "dep": "?",
                "hint": str(e)[:200],
            })
            continue
        marker = _BACKENDS[net][1]
        ok = bool(getattr(mod, marker, False))
        out.append({
            "network": net,
            "available": ok,
            "dep": getattr(mod, "DEP_NAME", "?"),
            "hint": getattr(mod, "INSTALL_HINT", ""),
        })
    return out


def open_messenger(network: str, persona, **kw) -> Messenger:
    """Construct a Messenger for ``persona`` on ``network``. Doesn't
    call ``connect()`` — caller decides when to spend network I/O."""
    mod = _import_backend(network)
    cls_name = network.capitalize() + "Messenger"
    if not hasattr(mod, cls_name):
        raise MessengerError(
            f"backend module {mod.__name__} is missing class {cls_name}"
        )
    cls = getattr(mod, cls_name)
    return cls(persona, **kw)


__all__ = [
    "ChatChannel",
    "ChatMessage",
    "Messenger",
    "MessengerError",
    "AuthError",
    "BackendUnavailable",
    "known_networks",
    "is_available",
    "availability_report",
    "open_messenger",
]
