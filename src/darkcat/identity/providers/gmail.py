# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Gmail signup profile — manual-assist only.

Gmail signup over Tor is functionally blocked: Google's anti-abuse
flow gates new accounts on phone verification almost universally for
suspicious source IPs (which Tor exits always are). There is no
documented no-phone path that survives current detection.

This profile exists so the operator who needs a Gmail (e.g. for
recovery email on platforms that demand a mainstream provider) sees a
clear writeup of *what does not work* and the limited paths that
sometimes do.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_WEBMAIL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="gmail",
    display_name="Gmail",
    category=CATEGORY_WEBMAIL,
    signup_url="https://accounts.google.com/signup",
    network_or_domain="mail.google.com",
    fields=(
        ProviderField("first_name", "display_name",
                      notes="form expects two name fields; split the generated display_name"),
        ProviderField("last_name", "display_name"),
        ProviderField("username", "handle"),
        ProviderField("password", "password"),
        ProviderField("birthdate", "birthdate"),
        ProviderField("recovery_email", "recovery_email", required=False,
                      notes="Google recommends one but does not strictly require it for non-mobile signups"),
    ),
    no_phone_path=(
        "Gmail's published flow can ask for either a phone number OR a "
        "recovery email; the variant shown depends on heuristics about "
        "the source IP, browser fingerprint, and account-creation rate. "
        "Tor exits almost always get the phone-required variant, so "
        "expect it to fail. Paths that *sometimes* work, in order of "
        "reliability:\n"
        "  1. Use a residential VPN exit (not Tor) the first time, then "
        "     re-pin to Tor only after the account is established.\n"
        "  2. On mobile, the Google Family Link or Workspace flow can "
        "     bypass phone, but requires existing infrastructure.\n"
        "If neither applies, do not waste the slot — pick a privacy "
        "provider instead."
    ),
    transport_recommendation="proxy",
    tos_warning=(
        "Google's Terms of Service explicitly forbid creating accounts "
        "by automated means and forbid creating multiple accounts to "
        "evade restrictions. Compartmentalising one account per project "
        "is at the operator's risk; Google may suspend without notice."
    ),
    notes=(
        "Realistic expectation: Gmail will block ~95% of fresh signups "
        "from non-residential IPs without a phone. Plan around it."
    ),
))
