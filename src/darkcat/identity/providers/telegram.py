# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Telegram signup profile.

Telegram is structurally phone-only — there is no email signup. Anonymous
Telegram identities are possible only via the paid 'Anonymous Number'
purchased through Fragment.com (a Telegram-affiliated marketplace), which
costs real money and is the documented official path. This profile
records that and points the operator there; no automation.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_SOCIAL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="telegram",
    display_name="Telegram",
    category=CATEGORY_SOCIAL,
    signup_url="https://web.telegram.org/k/",
    network_or_domain="telegram.org",
    fields=(
        ProviderField("phone_number", "recovery_email",
                      notes="Telegram is phone-only; the field is conceptual — "
                            "store the Fragment.com anonymous number here"),
        ProviderField("display_name", "display_name", required=False),
        ProviderField("bio", "bio", required=False),
    ),
    no_phone_path=(
        "There is no no-phone path for Telegram. The two legitimate "
        "options are:\n"
        "  1. Buy an Anonymous Number through https://fragment.com/ "
        "     (Telegram's official marketplace; costs ~25 TON / ~$50). "
        "     The number works only with Telegram and is not tied to a "
        "     real SIM. This is the supported path for compartmentalised "
        "     identities.\n"
        "  2. Use a real phone number you control. Do not buy second-hand "
        "     numbers from random SMS-receiver sites — they are usually "
        "     already burned and Telegram bans them within minutes."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Telegram's ToS allow one account per phone number and forbid "
        "automation that violates platform integrity. A Fragment number "
        "is treated like a real signup."
    ),
))
