# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""X (Twitter) signup profile — manual-assist only.

X demands a phone number on essentially every signup as of 2024+.
There is no documented no-phone path. This profile exists so the
operator who needs an X account knows in advance that the legitimate
options are: (a) accept the phone gate using a phone they control;
(b) skip X and use Mastodon / Bluesky / Nostr instead.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_SOCIAL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="twitter",
    display_name="X (Twitter)",
    category=CATEGORY_SOCIAL,
    signup_url="https://x.com/i/flow/signup",
    network_or_domain="x.com",
    fields=(
        ProviderField("display_name", "display_name"),
        ProviderField("phone_or_email", "recovery_email",
                      notes="X allows email *or* phone here; provide an email "
                            "you control and skip phone"),
        ProviderField("password", "password"),
        ProviderField("birthdate", "birthdate"),
    ),
    no_phone_path=(
        "On the first signup screen, switch from phone to email — the "
        "toggle is small and easy to miss. After confirmation, X "
        "frequently locks the account on first login from Tor and "
        "demands phone verification anyway, which there is no way "
        "around. Realistic outcome from Tor: 1 in 10-20 attempts "
        "completes; the rest get locked.\n"
        "Recommended alternative: use a Mastodon or Bluesky identity "
        "if the project's audience is reachable there."
    ),
    transport_recommendation="proxy",
    tos_warning=(
        "X's ToS forbid creating accounts by automated means and "
        "forbid operating multiple accounts that interact with the "
        "same content (vote brigading, etc.). Operating a single "
        "compartmentalised account per project is grey-area; X "
        "may suspend without notice."
    ),
    notes=(
        "Listed for completeness; consider this provider impractical "
        "from anonymising transports."
    ),
))
