# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Ricochet Refresh signup profile.

A Ricochet identity is a Tor v3 onion service. The client generates a
fresh onion key pair on first launch; that onion address *is* the
account ID and is shown to peers as ``ricochet:<56-char-onion>``. There
is no central registry, no email, no captcha, and no way to "recover"
the identity if the onion key is lost.

The reference (and only maintained) client is Ricochet Refresh — a
desktop GUI; there is no headless / CLI build. darkcat records the
identity for vault hygiene but cannot drive the chat itself.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_SOCIAL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="ricochet",
    display_name="Ricochet Refresh",
    category=CATEGORY_SOCIAL,
    signup_url="https://www.ricochetrefresh.net/",
    network_or_domain="ricochetrefresh.net",
    fields=(
        ProviderField("nickname", "display_name",
                      notes="shown to your contacts; not part of the ID"),
        ProviderField("ricochet_id", "handle", required=False,
                      notes="`ricochet:<56-char-onion>` — copy back into the "
                            "persona once the client has generated it"),
    ),
    no_phone_path=(
        "Ricochet Refresh never asks for a phone, email, or any "
        "centrally-issued identifier. The whole identity is an onion "
        "key pair.\n"
        "  1. Install Ricochet Refresh from "
        "https://www.ricochetrefresh.net/ (signed AppImage on Linux, "
        ".dmg on macOS, .exe on Windows).\n"
        "  2. On first launch the client generates a fresh onion "
        "address; choose a nickname.\n"
        "  3. Copy the `ricochet:<...>` ID and paste it back into the "
        "persona via `darkcat personas add <name> --network ricochet "
        "--handle ricochet:<id>` so the vault can track it.\n"
        "  4. Add peers by exchanging Ricochet IDs out of band."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Ricochet Refresh has no operator and no Terms of Service. "
        "Traffic is metadata-resistant by virtue of running over Tor "
        "onion services. Treat the on-disk profile as sensitive — "
        "anyone with the key file can impersonate you."
    ),
    notes=(
        "darkcat does not bundle a Ricochet client and `chat backends` "
        "will list ricochet as unavailable. Use the desktop GUI for the "
        "conversation; the vault entry is for identity tracking, "
        "linking, and clean burns."
    ),
))
