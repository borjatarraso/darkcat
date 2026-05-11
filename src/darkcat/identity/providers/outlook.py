# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Outlook.com / Microsoft account signup profile."""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_WEBMAIL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="outlook",
    display_name="Outlook.com",
    category=CATEGORY_WEBMAIL,
    signup_url="https://signup.live.com/",
    network_or_domain="outlook.live.com",
    fields=(
        ProviderField("first_name", "display_name"),
        ProviderField("last_name", "display_name"),
        ProviderField("username", "handle",
                      notes="<handle>@outlook.com or <handle>@hotmail.com"),
        ProviderField("password", "password"),
        ProviderField("birthdate", "birthdate"),
        ProviderField("country", "locale",
                      notes="Microsoft validates country/locale match"),
    ),
    no_phone_path=(
        "Outlook signup historically allowed CAPTCHA-only confirmation "
        "for residential IPs, but as of 2025 the form increasingly "
        "demands phone for any non-residential exit. Workable paths:\n"
        "  1. Solve the visual CAPTCHA shown on the first attempt; if "
        "     phone is requested, abandon and retry from a different "
        "     transport — do not feed it a real number.\n"
        "  2. The free-tier creation flow on signup.live.com has a "
        "     fallback to alt-email confirmation when JS is enabled "
        "     and the IP looks residential.\n"
        "Tor success rate is low but not zero; budget several attempts."
    ),
    transport_recommendation="proxy",
    tos_warning=(
        "Microsoft's MSA Terms forbid automated signup and forbid "
        "creating accounts to circumvent enforcement. Expect Microsoft "
        "to suspend silently if heuristics decide the account looks "
        "automated."
    ),
))
