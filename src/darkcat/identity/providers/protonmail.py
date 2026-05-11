# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""ProtonMail signup profile.

Free-tier ProtonMail accounts can be created without a phone number when
either (a) you complete a CAPTCHA challenge instead, or (b) you use a
disposable recovery email (a Tutanota / Disroot / Mailfence account
created earlier in the chain). The CAPTCHA path is preferred for
isolation — no second account couples to it.

Proton works through Tor; they ship an onion mirror. Use that rather
than the clearnet entry point so the signup itself never leaves the
overlay.
"""
from __future__ import annotations

from darkcat.identity.providers.base import (
    CATEGORY_EMAIL,
    ProviderField,
    ProviderProfile,
    register,
)


_PROFILE = ProviderProfile(
    slug="protonmail",
    display_name="Proton Mail",
    category=CATEGORY_EMAIL,
    # Proton's onion is the canonical privacy signup entry point. The
    # clearnet URL works too if Tor is unavailable.
    signup_url="https://protonmailrmez3lotccipshtkleegetolb73fuirgj7r4o4vfu7ozyd.onion/mail/signup",
    network_or_domain="mail.proton.me",
    fields=(
        ProviderField("username", "handle",
                      notes="becomes the @proton.me address"),
        ProviderField("password", "password"),
        ProviderField("display_name", "display_name", required=False),
        ProviderField("recovery_email", "recovery_email", required=False,
                      notes="optional; if you set one it becomes a linked-identity edge"),
    ),
    no_phone_path=(
        "On the verification step pick 'CAPTCHA' instead of 'Phone' or "
        "'Email'. Proton sometimes also shows a 'human verification' "
        "puzzle for Tor exits — solve it manually; do not try to "
        "automate. If only Phone/Email are offered, refresh through a "
        "new Tor circuit ('darkcat tor newnym') and reload the form."
    ),
    transport_recommendation="tor",
    tos_warning=(
        "Proton's Terms of Service permit one free account per person; "
        "creating multiple compartmentalised accounts is in a grey area. "
        "Operator's responsibility to comply with local law and ToS."
    ),
    notes=(
        "Proton charges no fee for signup. After confirmation, log in "
        "once via the onion mirror and enable two-factor (TOTP, not SMS) "
        "before you store anything on the account."
    ),
)


register(_PROFILE)
