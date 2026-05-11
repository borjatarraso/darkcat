# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""SimpleX Chat signup profile.

SimpleX has the same shape as Session — no signup form, no central
account registry. The "profile" is a local key pair plus a display name,
created on first launch of the ``simplex-chat`` daemon. Contacts are
exchanged out-of-band: each side generates an invite link and the other
side calls ``/connect`` on it.

This profile records the local-keygen flow so the operator can find it
through ``darkcat identity providers --slug simplex``; the chat backend
talks to a running daemon over WebSocket and doesn't need any of the
fields here at runtime.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_SOCIAL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="simplex",
    display_name="SimpleX Chat",
    category=CATEGORY_SOCIAL,
    # SimpleX has no web signup. Download page is the closest thing.
    signup_url="https://simplex.chat/downloads/",
    network_or_domain="simplex.chat",
    fields=(
        ProviderField("display_name", "display_name",
                      notes="local profile name shown to contacts"),
        ProviderField("daemon_url", "site", required=False,
                      notes="ws://host:port to the local simplex-chat daemon"),
    ),
    no_phone_path=(
        "SimpleX never asks for a phone or email. Account creation is "
        "fully local:\n"
        "  1. Install simplex-chat from https://simplex.chat/cli or the "
        "desktop bundle from https://simplex.chat/downloads.\n"
        "  2. Start the daemon: `simplex-chat -p 5225` (port arbitrary). "
        "First launch asks for a display name and creates the profile "
        "under ~/.simplex.\n"
        "  3. In the daemon REPL: `/address` to publish a long-term "
        "contact link, `/connect <peer_link>` to add somebody.\n"
        "  4. Point a darkcat persona at the daemon: "
        "`darkcat personas add me-simplex --network simplex "
        "--site ws://127.0.0.1:5225/`.\n"
        "SimpleX has no user IDs by design — contacts are addressed via "
        "per-pair queue URIs."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "SimpleX is decentralised; the SimpleX Chat project provides a "
        "set of relay servers under a privacy policy but operates no "
        "user registry. Run your own SMP servers for stricter isolation."
    ),
    notes=(
        "Use `darkcat chat connect --persona <name> <invite_link>` to "
        "accept a contact invitation, then `chat list / read / send` as "
        "usual."
    ),
))
