# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Windscribe signup profile."""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_VPN,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="windscribe",
    display_name="Windscribe",
    category=CATEGORY_VPN,
    signup_url="https://windscribe.com/signup",
    network_or_domain="windscribe.com",
    fields=(
        ProviderField("username", "handle"),
        ProviderField("password", "password"),
        ProviderField("recovery_email", "recovery_email", required=False,
                      notes="optional but required to recover the account"),
    ),
    no_phone_path=(
        "Windscribe's signup is email-optional and never asks for a "
        "phone number. The free tier ships 10GB/month if you confirm "
        "an email, 2GB if you don't. CAPTCHA on signup is solvable "
        "from Tor with a few retries."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Windscribe ToS permit one account per person on the free "
        "tier; multiple free accounts to extend quota are explicitly "
        "forbidden. Compartmentalised use across separate identities "
        "is grey-area."
    ),
))
