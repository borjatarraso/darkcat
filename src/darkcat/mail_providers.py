# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Post-signup SMTP/IMAP coordinates for known mail providers.

Distinct from :mod:`darkcat.identity.providers` — those carry signup-flow
metadata (URLs, no-phone paths, ToS warnings). This module just answers
"once the account exists, what host:port/TLS do you point an SMTP/IMAP
client at?". The two are orthogonal: an operator can sign up via the
identity workflow and still need this table to wire up
``darkcat mail send`` afterwards.

Each preset fills the persona's ``site`` (SMTP ``host:port``) and
``notes`` (``smtp_tls=…``, ``imap_host=…``, ``imap_port=…``,
``imap_tls=…``) fields so the operator doesn't have to memorise four
TLS/port combinations per provider. ``personas add --mail-provider
SLUG`` uses these as defaults; any explicit ``--site`` / ``--notes`` on
the command line still wins.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MailProviderPreset:
    """SMTP/IMAP defaults for one provider.

    ``description`` shows up in ``personas mail-providers`` so operators
    can scan the list. ``network`` is what gets written to
    ``persona.network`` — usually ``clearnet`` because SMTP/IMAP traffic
    is destined for a public mail server (Proton Bridge being the
    exception, where you really are talking to localhost)."""

    slug: str
    description: str
    site: str            # SMTP host:port
    notes: str           # imap_host=, imap_port=, smtp_tls=, imap_tls=
    network: str = "clearnet"
    handle_hint: Optional[str] = None  # "use your full @proton.me address"


# Curated table. Keep it short: each row reflects a setup we've
# verified against the provider's published docs, not speculation.
# Tutanota is intentionally absent — they don't expose SMTP/IMAP at
# all (mobile/desktop client only); :mod:`darkcat.mail` can't reach it.
_PRESETS: tuple[MailProviderPreset, ...] = (
    MailProviderPreset(
        slug="proton-bridge",
        description="Proton Mail via local Bridge (Bridge handles E2EE; we talk plain SMTP/IMAP).",
        site="127.0.0.1:1025",
        notes=(
            "smtp_tls=starttls "
            "imap_host=127.0.0.1 imap_port=1143 imap_tls=starttls"
        ),
        handle_hint="full @proton.me address; password = Bridge-generated token",
    ),
    MailProviderPreset(
        slug="disroot",
        description="Disroot — privacy-respecting community mail; standard STARTTLS+SSL.",
        site="disroot.org:587",
        notes=(
            "smtp_tls=starttls "
            "imap_host=disroot.org imap_port=993 imap_tls=ssl"
        ),
        handle_hint="full @disroot.org address",
    ),
    MailProviderPreset(
        slug="mailfence",
        description="Mailfence — Belgian provider; implicit TLS on 465 and 993.",
        site="smtp.mailfence.com:465",
        notes=(
            "smtp_tls=ssl "
            "imap_host=imap.mailfence.com imap_port=993 imap_tls=ssl"
        ),
        handle_hint="full Mailfence address",
    ),
    MailProviderPreset(
        slug="gmail-app-pw",
        description="Gmail via SMTP+IMAP app password (NOT OAuth; requires 2FA + app password).",
        site="smtp.gmail.com:465",
        notes=(
            "smtp_tls=ssl "
            "imap_host=imap.gmail.com imap_port=993 imap_tls=ssl"
        ),
        handle_hint="full @gmail.com address; password = 16-char app password",
    ),
    MailProviderPreset(
        slug="fastmail",
        description="Fastmail — implicit TLS on 465 / 993.",
        site="smtp.fastmail.com:465",
        notes=(
            "smtp_tls=ssl "
            "imap_host=imap.fastmail.com imap_port=993 imap_tls=ssl"
        ),
        handle_hint="full Fastmail address; password = app-specific password",
    ),
)


_BY_SLUG: dict[str, MailProviderPreset] = {p.slug: p for p in _PRESETS}


def slugs() -> tuple[str, ...]:
    """All known mail-provider slugs, sorted for stable CLI output."""
    return tuple(sorted(_BY_SLUG))


def get(slug: str) -> Optional[MailProviderPreset]:
    """Look up a preset by slug. Returns ``None`` if unknown."""
    return _BY_SLUG.get(slug)


def all_presets() -> tuple[MailProviderPreset, ...]:
    """All presets in slug order."""
    return tuple(_BY_SLUG[s] for s in slugs())


__all__ = [
    "MailProviderPreset",
    "all_presets",
    "get",
    "slugs",
]
