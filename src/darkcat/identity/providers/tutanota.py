# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Tuta (formerly Tutanota) signup profile.

Tuta supports signup over Tor and historically does not require a phone
number for the free tier — the signup form gates on a CAPTCHA + a
short waiting period (24-72h) for new free accounts to be reviewed.
The wait is intentional anti-abuse; the profile flags it so the
operator does not assume the account is dead.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_EMAIL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="tutanota",
    display_name="Tuta (Tutanota)",
    category=CATEGORY_EMAIL,
    signup_url="https://app.tuta.com/signup",
    network_or_domain="tuta.com",
    fields=(
        ProviderField("username", "handle",
                      notes="becomes <handle>@tuta.io"),
        ProviderField("password", "password"),
        ProviderField("recovery_code", "recovery_codes", required=False,
                      notes="Tuta generates this; copy the shown value into the vault"),
    ),
    no_phone_path=(
        "Tuta's free tier does not request a phone number. After "
        "signup the account is held for 24-72 hours of human review "
        "before it can send mail; do not interpret the delay as a "
        "soft-ban. Tuta's CAPTCHA must be solved manually — Tor exits "
        "trigger it more often than residential IPs."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Tuta's ToS prohibit operating multiple free accounts to "
        "circumvent quotas. Compartmentalised use across separate "
        "projects is grey-area; act in good faith and pay for any "
        "account you keep long-term."
    ),
    notes=(
        "Tuta generates a recovery code at signup that lets you reset "
        "the password later — store it in the vault immediately or "
        "you will be locked out on password rotation."
    ),
))
