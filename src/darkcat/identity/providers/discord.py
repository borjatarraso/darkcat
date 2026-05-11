# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Discord signup profile."""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_SOCIAL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="discord",
    display_name="Discord",
    category=CATEGORY_SOCIAL,
    signup_url="https://discord.com/register",
    network_or_domain="discord.com",
    fields=(
        ProviderField("email", "recovery_email"),
        ProviderField("username", "handle"),
        ProviderField("display_name", "display_name", required=False),
        ProviderField("password", "password"),
        ProviderField("birthdate", "birthdate"),
    ),
    no_phone_path=(
        "Discord's signup completes with email-only verification — no "
        "phone is required at signup. However, Discord frequently "
        "demands phone verification on the *first server join* if the "
        "account looks suspicious (Tor exit, no friends, fresh account). "
        "Strategy:\n"
        "  1. Sign up over Tor with email-only.\n"
        "  2. Confirm the email link from the same circuit.\n"
        "  3. Wait 24-48h before joining any server; Discord's heuristics "
        "     loosen with account age.\n"
        "  4. Join small / private servers first (an invite from a "
        "     known contact); avoid large public servers on day one — "
        "     they trigger the phone gate."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Discord's ToS forbid alt accounts to evade bans and automation "
        "that violates server rules. Compartmentalising one Discord "
        "identity per community is grey-area; voice/video features will "
        "leak metadata regardless of transport."
    ),
    notes=(
        "Discord uses fingerprinting heavily; do not log into multiple "
        "Discord identities from the same browser profile."
    ),
))
