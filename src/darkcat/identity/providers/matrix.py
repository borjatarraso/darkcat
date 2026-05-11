# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Matrix signup profile (homeserver-aware).

Matrix is a federated chat protocol; there is no single ``matrix.org``
account in the same sense as a webmail address. Each homeserver runs
its own registration policy:

* ``matrix.org`` — open registration, requires an email-confirmation
  step and may surface a hCaptcha; new account IDs look like
  ``@local:matrix.org``.
* ``element.io`` — same backend as matrix.org but a different
  Element-branded onboarding.
* Privacy-leaning instances (``disroot.org``, ``riot.im`` mirrors,
  ``tchncs.de``) come and go; some require an invite token.

The signup launcher opens the homeserver's web client / register page
through the recommended transport; darkcat's role is to generate a
username + strong password + recovery email and stand by while the
operator solves the captcha.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_SOCIAL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="matrix",
    display_name="Matrix",
    category=CATEGORY_SOCIAL,
    signup_url="https://app.element.io/#/register",
    network_or_domain="matrix.org",
    fields=(
        ProviderField("username", "handle",
                      notes="becomes the localpart of @user:homeserver"),
        ProviderField("password", "password"),
        ProviderField("email", "recovery_email",
                      notes="needed for password reset and (on matrix.org) "
                            "confirmation; link to an existing mail identity"),
        ProviderField("display_name", "display_name", required=False),
    ),
    no_phone_path=(
        "Matrix does not require a phone number on the default homeservers. "
        "matrix.org asks for an email confirmation — point it at a Proton / "
        "Tutanota / Disroot recovery identity already in this vault and "
        "link the two with `darkcat identity link`. Self-hosted homeservers "
        "(Synapse / Conduit / Dendrite) can be configured to skip email "
        "entirely; use one of those if you want a zero-out-of-band signup."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Every homeserver sets its own Terms of Service. Read the chosen "
        "server's policy page before registering — many forbid bot traffic, "
        "scraping, and abusive multi-account use. This tool will not help "
        "you violate them."
    ),
    instances=(
        ("matrix-org", "https://app.element.io/#/register",
         "flagship homeserver; open registration with hCaptcha + email"),
        ("tchncs", "https://matrix.tchncs.de/_matrix/client/v3/register",
         "tchncs.de — privacy-leaning German server, in-band registration"),
        ("envs-net", "https://matrix.envs.net/_matrix/client/v3/register",
         "envs.net — small community server, no phone"),
        ("disroot", "https://disroot.org/en/services/matrix",
         "disroot — invite/manual signup via their account portal"),
    ),
    notes=(
        "Pick a homeserver whose moderation and uptime policy fits the "
        "project. Federation means you can talk to people on any other "
        "homeserver afterwards — the choice is not a long-term lock-in. "
        "Once registered, point a persona at it with `darkcat personas add "
        "<name> --network matrix --site @local:homeserver.tld --handle "
        "<localpart> --password <pw>` and run `darkcat chat login matrix`."
    ),
))
