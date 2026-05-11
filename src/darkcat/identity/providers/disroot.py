# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Disroot signup profile.

Disroot is a community-run mail/XMPP/Nextcloud co-op. Signup is via
form + manual approval; reasonable purpose stated in the form is the
expected path. Phone never asked.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_EMAIL,
    ProviderField,
    ProviderProfile,
    register,
)


register(ProviderProfile(
    slug="disroot",
    display_name="Disroot",
    category=CATEGORY_EMAIL,
    signup_url="https://user.disroot.org/pwm/public/newuser",
    network_or_domain="disroot.org",
    fields=(
        ProviderField("username", "handle"),
        ProviderField("password", "password"),
        ProviderField("recovery_email", "recovery_email", required=False),
        ProviderField("reason", "purpose_tag", required=False,
                      notes="text-area shown to admins; write something honest "
                            "that does not reveal the tool"),
    ),
    no_phone_path=(
        "Disroot never asks for a phone number. The signup form has a "
        "free-form 'reason' field reviewed by humans; one-line "
        "boilerplate ('compartmentalising email per project') is fine, "
        "but do not paste an obviously-templated answer or the request "
        "will be rejected."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Disroot is a small donation-supported co-op. Each free account "
        "consumes their resources — pay or donate if you keep one "
        "long-term, and avoid creating accounts you do not actively use."
    ),
))
