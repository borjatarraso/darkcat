"""Seeds — flat URL list per protocol, derived from ``darkcat.entries``.

``entries.py`` is the single source of truth (it carries names + descriptions
for ``--list`` / ``--list-all``). Seeds are just the URLs from that data.
"""
from __future__ import annotations

from darkcat.entries import ENTRY_POINTS


SEEDS_BY_PROTOCOL: dict[str, list[str]] = {
    proto: [e.url for e in entries]
    for proto, entries in ENTRY_POINTS.items()
}


def all_seeds() -> list[str]:
    out: list[str] = []
    for v in SEEDS_BY_PROTOCOL.values():
        out.extend(v)
    return out
