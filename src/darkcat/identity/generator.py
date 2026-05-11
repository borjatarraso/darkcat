# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Persona-attribute generators for the Identity Generator.

Builds on top of :mod:`darkcat.personas` (which already supplies
``generate_handle`` and ``generate_password``) by adding the rest of the
fields a typical signup form asks for: display name, locale, timezone,
birthdate, short bio.

The generators are intentionally boring — they pick from small curated
wordlists and return values that look human but are not derived from any
real person. No external API calls.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date
from typing import Optional

from darkcat import personas as _pv


# Locale codes paired with a plausible IANA timezone. Pairings stay
# consistent so a generated identity doesn't claim to be in Berlin while
# its locale says en_US — the kind of mismatch that gets flagged by
# anti-fraud scoring.
_LOCALE_TZ = (
    ("en_US", "America/New_York"),
    ("en_US", "America/Chicago"),
    ("en_US", "America/Denver"),
    ("en_US", "America/Los_Angeles"),
    ("en_GB", "Europe/London"),
    ("de_DE", "Europe/Berlin"),
    ("fr_FR", "Europe/Paris"),
    ("es_ES", "Europe/Madrid"),
    ("it_IT", "Europe/Rome"),
    ("pt_PT", "Europe/Lisbon"),
    ("nl_NL", "Europe/Amsterdam"),
    ("sv_SE", "Europe/Stockholm"),
    ("pl_PL", "Europe/Warsaw"),
    ("ja_JP", "Asia/Tokyo"),
    ("en_AU", "Australia/Sydney"),
    ("en_CA", "America/Toronto"),
)

# Bland first / last names — common enough to look unremarkable in a
# signup form, not so famous that they read as a fictional character.
_FIRST_NAMES = (
    "alex", "jamie", "sam", "robin", "casey", "morgan", "taylor", "jordan",
    "riley", "quinn", "harper", "rowan", "skyler", "drew", "blake", "cameron",
    "kerry", "dana", "kai", "ari", "remy", "sasha", "noor", "elliot",
)
_LAST_NAMES = (
    "lane", "ashford", "park", "hall", "shaw", "knox", "vega", "frost",
    "oakley", "wren", "north", "ellis", "hart", "rivers", "moss", "vale",
    "blackwood", "fairchild", "reyes", "lin", "brand", "carmichael",
)

# Bio fragments — short, generic, rotate. Avoid niche hobbies that make
# an account memorable across forums.
_BIO_OPENERS = (
    "reader", "writer", "cyclist", "tinkerer", "linux user",
    "self-hosted everything", "occasional photographer", "tea drinker",
    "long-form podcast listener", "weekend hiker", "library regular",
)
_BIO_CONNECTORS = (" • ", " | ", ", ", " — ")
_BIO_CLOSERS = (
    "opinions are my own", "no DMs", "lurking mostly",
    "don't take it personally", "here for the threads",
    "low-key", "anti-engagement-farming", "muting freely",
    "elsewhere as well", "RT ≠ endorsement",
)


@dataclass
class GeneratedIdentity:
    """All the freshly-generated values for a new persona, before it gets
    stored. Caller copies fields into a :class:`darkcat.personas.Persona`."""

    handle: str
    password: str
    display_name: str
    locale: str
    timezone: str
    birthdate: str   # YYYY-MM-DD
    bio: str


def generate_display_name(rng: Optional[secrets.SystemRandom] = None) -> str:
    """``First Last`` with title-case. Two words, no diacritics — wide
    compatibility with signup-form validators that reject non-ASCII."""
    rng = rng or secrets.SystemRandom()
    first = rng.choice(_FIRST_NAMES).capitalize()
    last = rng.choice(_LAST_NAMES).capitalize()
    return f"{first} {last}"


def generate_locale(rng: Optional[secrets.SystemRandom] = None) -> tuple[str, str]:
    """Pick a (locale, timezone) pair. They're returned together so the
    caller can store both consistently."""
    rng = rng or secrets.SystemRandom()
    return rng.choice(_LOCALE_TZ)


def generate_timezone(rng: Optional[secrets.SystemRandom] = None) -> str:
    """Standalone timezone picker — defers to :func:`generate_locale` and
    drops the locale half. Useful when the caller already has a locale
    but didn't get a TZ with it."""
    return generate_locale(rng)[1]


def generate_birthdate(
    rng: Optional[secrets.SystemRandom] = None,
    *,
    min_age: int = 22,
    max_age: int = 55,
) -> str:
    """ISO date, bounded so the generated age is plausible-adult and not
    so old that a service flags account-recovery questions about it.
    Floor at 22 dodges age-gates that distrust new 18-year-old signups."""
    if min_age > max_age:
        raise ValueError("min_age > max_age")
    rng = rng or secrets.SystemRandom()
    today = date.today()
    age = rng.randrange(min_age, max_age + 1)
    # Random month/day — Feb 29 collapses to Feb 28 outside leap years.
    month = rng.randrange(1, 13)
    day_max = 28 if month == 2 else (30 if month in (4, 6, 9, 11) else 31)
    day = rng.randrange(1, day_max + 1)
    year = today.year - age
    return f"{year:04d}-{month:02d}-{day:02d}"


def generate_bio(rng: Optional[secrets.SystemRandom] = None) -> str:
    """Three short fragments joined by a separator. Length stays under
    most platforms' bio cap (Mastodon ~500, X/Twitter ~160) by design."""
    rng = rng or secrets.SystemRandom()
    opener = rng.choice(_BIO_OPENERS)
    middle = rng.choice([s for s in _BIO_OPENERS if s != opener])
    closer = rng.choice(_BIO_CLOSERS)
    sep = rng.choice(_BIO_CONNECTORS)
    return f"{opener}{sep}{middle}{sep}{closer}"


def new_identity(
    *,
    password_length: int = 24,
    rng: Optional[secrets.SystemRandom] = None,
) -> GeneratedIdentity:
    """One-call helper: generate every persona attribute at once."""
    rng = rng or secrets.SystemRandom()
    locale, tz = generate_locale(rng)
    return GeneratedIdentity(
        handle=_pv.generate_handle(rng),
        password=_pv.generate_password(password_length),
        display_name=generate_display_name(rng),
        locale=locale,
        timezone=tz,
        birthdate=generate_birthdate(rng),
        bio=generate_bio(rng),
    )


__all__ = [
    "GeneratedIdentity",
    "generate_birthdate",
    "generate_bio",
    "generate_display_name",
    "generate_locale",
    "generate_timezone",
    "new_identity",
]
