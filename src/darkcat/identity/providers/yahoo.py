# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Yahoo Mail signup profile."""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_WEBMAIL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="yahoo",
    display_name="Yahoo Mail",
    category=CATEGORY_WEBMAIL,
    signup_url="https://login.yahoo.com/account/create",
    network_or_domain="mail.yahoo.com",
    fields=(
        ProviderField("first_name", "display_name"),
        ProviderField("last_name", "display_name"),
        ProviderField("username", "handle"),
        ProviderField("password", "password"),
        ProviderField("birthdate", "birthdate"),
    ),
    no_phone_path=(
        "Yahoo strictly requires a working phone number on the standard "
        "signup form — there is no published no-phone path. The "
        "yahoo-japan and yahoo-other-region flows behave the same way. "
        "If a project genuinely needs a webmail account on Yahoo, plan "
        "to use a phone you control or pick a different provider."
    ),
    transport_recommendation="proxy",
    tos_warning=(
        "Yahoo / Verizon Media ToS prohibit automated signup. The "
        "phone-verification gate will lock the account on the first "
        "attempt that looks scripted."
    ),
    notes=(
        "Listed for completeness; consider this provider impractical "
        "without a real phone."
    ),
))
