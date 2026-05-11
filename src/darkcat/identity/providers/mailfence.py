# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Mailfence signup profile."""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_EMAIL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="mailfence",
    display_name="Mailfence",
    category=CATEGORY_EMAIL,
    signup_url="https://mailfence.com/en/signup.jsp",
    network_or_domain="mailfence.com",
    fields=(
        ProviderField("username", "handle"),
        ProviderField("password", "password"),
        ProviderField("recovery_email", "recovery_email",
                      notes="Mailfence requires an external recovery address — "
                            "use a separate vault entry, then `identity link`"),
        ProviderField("display_name", "display_name", required=False),
    ),
    no_phone_path=(
        "Mailfence does not ask for a phone number on the free tier. "
        "It does require a working recovery email, so create that "
        "account first (Tutanota or Disroot work) and pass it as "
        "--recovery-email on the Mailfence identity."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Mailfence is based in Belgium and applies EU data-protection "
        "rules. ToS allow personal use; one account per real person "
        "is the published expectation."
    ),
))
