# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Session (Oxen) signup profile.

Session accounts have **no signup form** — the "account ID" is a public
key derived from a locally generated 13-word seed. There is no server
asking for an email or phone. So the manual-assist path here is:

1. Generate the seed + Session ID locally (Session desktop GUI, or
   ``session-cli accounts new``).
2. Record the resulting Session ID + seed in the darkcat persona vault
   so the chat backend can talk to ``session-cli`` against this identity.

The "signup URL" field points at the Session download page since there
is no web signup; the launcher uses it only as a courtesy when the
operator picks the wrong starting point.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_SOCIAL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="session",
    display_name="Session (Oxen)",
    category=CATEGORY_SOCIAL,
    # Session has no web signup. Download page is the closest thing.
    signup_url="https://getsession.org/download",
    network_or_domain="getsession.org",
    fields=(
        ProviderField("session_id", "handle",
                      notes="66-hex Account ID starting 05 — paste from "
                            "Session desktop or `session-cli accounts new`"),
        ProviderField("recovery_phrase", "recovery",
                      notes="13-word seed; the only way to restore the account"),
        ProviderField("display_name", "display_name", required=False),
    ),
    no_phone_path=(
        "Session never asks for a phone or email. Account creation is "
        "fully local:\n"
        "  1. Install Session desktop from https://getsession.org/download "
        "or `npm i -g session-cli`.\n"
        "  2. In Session: 'Create Account' → write down the 13-word "
        "recovery phrase → set a display name. CLI equivalent: "
        "`session-cli accounts new --json`.\n"
        "  3. Copy the Session ID (66-hex, starts 05) into the persona's "
        "`handle` field and the seed into `recovery`.\n"
        "Pin your Session traffic through Tor for transport isolation if "
        "your threat model needs network-layer anonymity (Session itself "
        "uses Oxen's onion routing, but the bootstrap snode list is "
        "fetched in the clear)."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Session is decentralised and has no central ToS. The Oxen "
        "Foundation publishes a code of conduct for its hosted "
        "infrastructure; respect it on Session-run service-nodes."
    ),
    notes=(
        "After registering, `darkcat chat login session --persona <name>` "
        "verifies session-cli can see the account. Use "
        "`darkcat chat addcontact --persona <name> <peer_session_id>` to "
        "start a DM."
    ),
))
