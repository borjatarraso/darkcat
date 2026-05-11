# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Tox signup profile.

Tox has the same shape as Session / SimpleX: there is no signup form
and no central account registry. A Tox ID is a local key pair (76 hex
characters: 32-byte public key + 4-byte nospam + 2-byte checksum)
generated the first time you launch a Tox client. Contacts are added
out-of-band by exchanging Tox IDs.

darkcat does not ship a working Tox messenger (no maintained Python
binding for the ``toxcore`` C library that the rest of the project
trusts). This profile documents the local-keygen flow so the operator
can still record the identity in the vault and link it to other
identities; chat itself happens in qTox / uTox / TRIfA.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_SOCIAL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="tox",
    display_name="Tox",
    category=CATEGORY_SOCIAL,
    signup_url="https://tox.chat/clients.html",
    network_or_domain="tox.chat",
    fields=(
        ProviderField("display_name", "display_name",
                      notes="local profile name shown to peers"),
        ProviderField("tox_id", "handle", required=False,
                      notes="76-hex identifier produced by the client on "
                            "first launch; paste back into the persona once known"),
        ProviderField("status_message", "bio", required=False),
    ),
    no_phone_path=(
        "Tox never asks for a phone, email, or any identifier other than "
        "the locally generated key pair. Account creation is fully local:\n"
        "  1. Install a Tox client from https://tox.chat/clients.html "
        "(qTox on desktop is the reference UI).\n"
        "  2. On first launch, set a username and (optional) password — "
        "the password encrypts the on-disk profile, not your traffic.\n"
        "  3. Copy the 76-hex Tox ID and paste it back into the persona "
        "via `darkcat personas add <name> --network tox --handle <TOXID>` "
        "or `personas show <name> --reveal` to record it.\n"
        "  4. Add peers by exchanging Tox IDs out of band."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Tox is fully peer-to-peer with no central operator and no ToS. "
        "Bootstrap nodes are run by volunteers; their availability and "
        "logging policies vary. Use a network transport that matches the "
        "threat model — the Tox protocol itself does not anonymise the "
        "underlying IP."
    ),
    notes=(
        "darkcat does not bundle a Tox messenger; `chat backends` will "
        "show tox as unavailable. Use qTox / uTox for the actual "
        "conversation and let darkcat track the identity in the vault."
    ),
))
