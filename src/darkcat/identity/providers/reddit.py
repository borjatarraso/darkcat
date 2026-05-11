# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Reddit signup profile."""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_SOCIAL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="reddit",
    display_name="Reddit",
    category=CATEGORY_SOCIAL,
    signup_url="https://www.reddit.com/account/register/",
    network_or_domain="reddit.com",
    fields=(
        ProviderField("email", "recovery_email", required=False,
                      notes="email is optional but lets you recover the account"),
        ProviderField("username", "handle"),
        ProviderField("password", "password"),
    ),
    no_phone_path=(
        "Reddit standard signup does not require a phone number. The "
        "blocker for Tor exits is the CAPTCHA + sometimes a 'verify "
        "you are human' interstitial — solve manually. New-account "
        "rate limits are aggressive (1-2 per IP per day) so plan to "
        "use a fresh circuit per signup ('darkcat tor newnym'). "
        "Reddit's onion mirror is at https://reddittorjg6rue252oqsxryoxengawnmo46qy4kyii5wtqnwfj4ooad.onion/account/register/"
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Reddit's ToS forbid creating accounts to evade bans or to "
        "run automated activity. Compartmentalising one account per "
        "subreddit-of-interest is grey-area; do not use the same "
        "voting fingerprint across multiple identities."
    ),
    notes=(
        "After signup, do not log into multiple Reddit identities from "
        "the same browser session — Reddit's anti-evasion looks at "
        "session cookies + browser fingerprint, not just IP."
    ),
))
