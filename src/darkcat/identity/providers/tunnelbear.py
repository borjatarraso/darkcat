# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""TunnelBear signup profile."""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_VPN,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="tunnelbear",
    display_name="TunnelBear",
    category=CATEGORY_VPN,
    signup_url="https://www.tunnelbear.com/account/create",
    network_or_domain="tunnelbear.com",
    fields=(
        ProviderField("email", "recovery_email",
                      notes="TunnelBear's primary identifier is the email; "
                            "use a vault email entry"),
        ProviderField("password", "password"),
    ),
    no_phone_path=(
        "TunnelBear does not request a phone number for the free 2GB "
        "tier; signup completes after clicking the email-confirmation "
        "link. The link must be opened from a browser that can reach "
        "the recovery_email's webmail — keep the same transport active "
        "while clicking it."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "TunnelBear ToS forbid commercial use of the free tier and "
        "forbid creating multiple free accounts for additional quota. "
        "Compartmentalised personal use is grey-area."
    ),
))
