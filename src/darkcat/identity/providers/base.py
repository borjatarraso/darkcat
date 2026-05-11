# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Provider-profile schema and registry.

A profile is a static description of how to manually create an account
on one provider. There is no automated form-filler here — the operator
stays in the browser; the profile only tells them where to go and which
generated values to paste where.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


CATEGORY_EMAIL = "email"        # privacy-first mail (proton, tuta, …)
CATEGORY_WEBMAIL = "webmail"    # mainstream mail (gmail, outlook, yahoo)
CATEGORY_VPN = "vpn"            # commercial VPN signup
CATEGORY_SOCIAL = "social"      # forums / federated / messengers
CATEGORY_VALUES = (CATEGORY_EMAIL, CATEGORY_WEBMAIL, CATEGORY_VPN, CATEGORY_SOCIAL)


@dataclass(frozen=True)
class ProviderField:
    """One signup-form field the operator will fill from a generated
    value."""

    name: str           # form-key, e.g. "username"
    source: str         # which generated attribute supplies it
    required: bool = True
    notes: str = ""     # human-readable hint, shown in the signup helper


@dataclass(frozen=True)
class ProviderProfile:
    slug: str                       # short id, e.g. "protonmail"
    display_name: str               # human-readable
    category: str                   # CATEGORY_*
    signup_url: str                 # entry point for the signup flow
    network_or_domain: str          # e.g. "mail.proton.me", "mastodon.social"
    fields: tuple[ProviderField, ...]
    no_phone_path: str              # one-paragraph instruction for the operator
    transport_recommendation: str   # tor / i2p / proxy — what survives the form
    tos_warning: str                # surfaced once before signup launches
    notes: str = ""                 # free-form

    # Per-instance providers (Mastodon, XMPP, Matrix) need the operator
    # to pick a host. Tuple of (slug-suffix, default_signup_url, note).
    instances: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)


_REGISTRY: list[ProviderProfile] = []


def register(profile: ProviderProfile) -> None:
    """Add ``profile`` to the global registry. Re-registering the same
    slug overwrites — profiles are pure data, so this is harmless and
    makes hot-reloading test profiles easy."""
    if profile.category not in CATEGORY_VALUES:
        raise ValueError(
            f"profile {profile.slug!r} has unknown category {profile.category!r}; "
            f"expected one of {CATEGORY_VALUES}"
        )
    for i, existing in enumerate(_REGISTRY):
        if existing.slug == profile.slug:
            _REGISTRY[i] = profile
            return
    _REGISTRY.append(profile)


def registered() -> list[ProviderProfile]:
    return list(_REGISTRY)


__all__ = [
    "CATEGORY_EMAIL",
    "CATEGORY_SOCIAL",
    "CATEGORY_VPN",
    "CATEGORY_WEBMAIL",
    "CATEGORY_VALUES",
    "ProviderField",
    "ProviderProfile",
    "register",
    "registered",
]
