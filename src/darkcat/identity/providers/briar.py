# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Briar signup profile.

Briar accounts are local. Each install generates a long-term key pair
on first launch and binds it to a chosen username and passphrase. There
is no central server, no signup form, and no recovery channel — losing
the passphrase loses the account permanently. Contacts are added by
exchanging short ``briar://`` links out of band.

The reference clients are the Android app (Briar) and ``briar-headless``
for Linux servers; there is no maintained Python or pure-CLI client, so
darkcat's role for Briar is identity tracking only. The chat itself
runs in the dedicated client.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_SOCIAL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="briar",
    display_name="Briar",
    category=CATEGORY_SOCIAL,
    signup_url="https://briarproject.org/download-briar/",
    network_or_domain="briarproject.org",
    fields=(
        ProviderField("nickname", "handle",
                      notes="display name shown to your contacts"),
        ProviderField("passphrase", "password",
                      notes="encrypts the on-disk identity; no recovery if lost"),
        ProviderField("briar_link", "site", required=False,
                      notes="paste your `briar://...` invite link here so other "
                            "personas in the vault can link to it"),
    ),
    no_phone_path=(
        "Briar has no concept of a phone or email — every account is a "
        "local Tor hidden-service identity tied to one device.\n"
        "  1. Install Briar (Android, F-Droid) or briar-headless on a "
        "Linux box (https://code.briarproject.org/briar/briar/-/wikis/"
        "Briar-Headless).\n"
        "  2. Create the profile with the generated nickname + a strong "
        "passphrase. The app sets up its own Tor circuits on first run.\n"
        "  3. From inside the client, copy your `briar://...` long-term "
        "contact link and store it on the persona via `darkcat personas "
        "show <name>` -> notes / site.\n"
        "  4. Exchange links with peers face-to-face, over signed mail, "
        "or any other authenticated channel — there is no directory."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Briar is peer-to-peer; there is no operator and no Terms of "
        "Service to violate. The network routes over Tor by default, but "
        "you are responsible for keeping the device that holds the "
        "long-term key physically secure — if it is compromised, every "
        "past message is recoverable from the local store."
    ),
    notes=(
        "darkcat does not bundle a Briar client and `chat backends` will "
        "show briar as unavailable. Use the official client for the "
        "conversation; this vault entry exists so you can link a Briar "
        "identity to other identities (recovery-email chains, project "
        "tags) and burn it cleanly when the project ends."
    ),
))
