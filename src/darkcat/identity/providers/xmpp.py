# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""XMPP signup profile (server-aware).

XMPP (Jabber) is a federated chat protocol with no central account
registry. Each server runs its own admission policy: some accept
in-band registration straight from a client (``conversations.im``,
``jabber.at``), others only allow signup through a web form, and a
handful require an invite from an existing user.

The signup launcher opens the chosen server's registration entry point
through the recommended transport. Once the account exists, point a
persona at it and use `darkcat chat login xmpp`.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_SOCIAL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="xmpp",
    display_name="XMPP / Jabber",
    category=CATEGORY_SOCIAL,
    signup_url="https://account.disroot.org/",
    network_or_domain="disroot.org",
    fields=(
        ProviderField("localpart", "handle",
                      notes="becomes the local-part of localpart@server.tld (JID)"),
        ProviderField("password", "password"),
        ProviderField("email", "recovery_email", required=False,
                      notes="optional on most servers; needed for password "
                            "reset where supported"),
        ProviderField("display_name", "display_name", required=False),
    ),
    no_phone_path=(
        "XMPP servers almost never request a phone number. The blockers "
        "are (a) per-server captchas and (b) whether the server permits "
        "in-band registration. The shipped instance list points only at "
        "servers known to allow free signup without phone verification "
        "at the time of writing — confirm on the server's homepage before "
        "you start, the situation drifts over time."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Every XMPP server publishes its own Terms of Service and "
        "anti-spam policy. Read the chosen server's rules before "
        "registering — many forbid automation and multi-account abuse. "
        "This tool will not help you violate them."
    ),
    instances=(
        ("disroot", "https://account.disroot.org/",
         "disroot.org — community account portal, account doubles as XMPP JID"),
        ("conversations-im", "https://account.conversations.im/",
         "conversations.im — paid (~€8/yr) with first 6 months free; "
         "extremely reliable, anti-spam by design"),
        ("snopyta", "https://xmpp.snopyta.org/",
         "snopyta.org — privacy-leaning German server (check uptime)"),
        ("jabber-at", "https://jabber.at/account/register/",
         "jabber.at — Austrian server, free, web signup"),
        ("xmpp-jp", "https://xmpp.jp/",
         "xmpp.jp — open server with public homepage; in-band registration"),
    ),
    notes=(
        "After signup, point a persona at the server with `darkcat "
        "personas add <name> --network xmpp --site server.tld --handle "
        "localpart --password <pw>`. OMEMO end-to-end encryption is "
        "client-side; the slixmpp backend used by `darkcat chat xmpp` "
        "currently sends in plaintext — set up OMEMO in a paired client "
        "(Gajim, Conversations) if the conversation needs it."
    ),
))
