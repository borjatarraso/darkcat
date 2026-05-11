# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Proton VPN signup profile."""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_VPN,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="protonvpn",
    display_name="Proton VPN",
    category=CATEGORY_VPN,
    signup_url="https://account.protonvpn.com/signup",
    network_or_domain="protonvpn.com",
    fields=(
        ProviderField("username", "handle"),
        ProviderField("password", "password"),
        ProviderField("recovery_email", "recovery_email", required=False,
                      notes="usually a Proton Mail account already in this vault"),
    ),
    no_phone_path=(
        "Proton VPN signup uses the same flow as Proton Mail and "
        "supports CAPTCHA-only verification. If the Proton account "
        "already exists, log in to it instead of signing up fresh — "
        "Proton Mail and Proton VPN share an account."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Proton's free tier permits one account per person. Free VPN "
        "exits are rate-limited and noisy; budget for the paid tier "
        "if the VPN identity will see real traffic."
    ),
    notes=(
        "Useful as a confirmation transport for other identities — "
        "create the VPN identity first, then `--transport vpn-pin "
        "--pin-to <protonvpn-name>` to route subsequent signups "
        "through it."
    ),
))
