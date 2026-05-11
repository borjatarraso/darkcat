# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Mastodon signup profile (instance-aware).

There is no single Mastodon — each instance is independent. Several
instances accept new accounts without phone numbers and without an
invite code; ``instances`` lists a few well-known ones, but any
ActivityPub-compatible Mastodon /auth/sign_up URL works the same way.

Some instances require a short text answer ("why do you want to join?")
which the operator types manually — there's no canned answer that
won't read as bot output, so don't generate one.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_SOCIAL,
    ProviderField,
    ProviderProfile,
    register,
)


_PROFILE = ProviderProfile(
    slug="mastodon",
    display_name="Mastodon",
    category=CATEGORY_SOCIAL,
    signup_url="https://mastodon.social/auth/sign_up",
    network_or_domain="mastodon.social",
    fields=(
        ProviderField("username", "handle"),
        ProviderField("email", "recovery_email",
                      notes="needs a working inbox for the confirmation link"),
        ProviderField("password", "password"),
        ProviderField("display_name", "display_name", required=False),
        ProviderField("bio", "bio", required=False),
    ),
    no_phone_path=(
        "Mastodon does not ask for a phone number at any standard "
        "instance. The blocker is the email-confirmation link — point "
        "it at a recovery_email you control (a Proton or Tutanota "
        "account already in this vault) and link the two with "
        "'darkcat identity link'."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Each Mastodon instance has its own rules. Read the chosen "
        "instance's 'Server rules' page before signup; many forbid "
        "automation, multi-account spam, or scraping. This tool will "
        "not help you violate them."
    ),
    instances=(
        ("mastodon-social", "https://mastodon.social/auth/sign_up",
         "flagship; relatively strict moderation"),
        ("mstdn-social", "https://mstdn.social/auth/sign_up",
         "general-purpose, English-leaning"),
        ("fosstodon", "https://fosstodon.org/auth/sign_up",
         "FOSS topic; manual approval"),
        ("infosec-exchange", "https://infosec.exchange/auth/sign_up",
         "security topic; closed signups intermittently"),
    ),
    notes=(
        "Pick the instance whose moderation policy fits the project the "
        "identity is for. Once joined, you can follow accounts on any "
        "other instance — picking a single home server is not a "
        "long-term lock-in."
    ),
)


register(_PROFILE)
