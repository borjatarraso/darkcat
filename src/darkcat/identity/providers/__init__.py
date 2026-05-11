# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Provider profiles for the Identity Generator.

A *profile* is data, not automation: where a service's signup form
lives, which fields it asks for, what the documented no-phone path is,
and which transport works best. The manual-assist signup launcher
reads a profile to drive the operator through a creation flow; the
operator stays in the loop for any captcha / human-verification step.

Profiles auto-register at import. Add a new file under this package
that builds a :class:`ProviderProfile` and calls :func:`register`, and
``darkcat identity providers`` will pick it up on next run.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Iterable, Optional

from darkcat.identity.providers.base import (
    CATEGORY_EMAIL,
    CATEGORY_SOCIAL,
    CATEGORY_VPN,
    CATEGORY_WEBMAIL,
    CATEGORY_VALUES,
    ProviderField,
    ProviderProfile,
    register,
    registered,
)


def load_all() -> list[ProviderProfile]:
    """Import every sibling module so each one's ``register()`` runs.

    Idempotent — re-importing a module that's already been imported is
    cheap and re-registration overwrites the existing entry, which is
    fine because profiles are just data.
    """
    pkg_path = list(__path__)  # type: ignore[name-defined]
    for _finder, modname, _ispkg in pkgutil.iter_modules(pkg_path):
        if modname in ("base", "__init__"):
            continue
        importlib.import_module(f"{__name__}.{modname}")
    return registered()


def get(slug: str) -> Optional[ProviderProfile]:
    """Look up a profile by slug. Triggers :func:`load_all` once so the
    caller doesn't have to remember to prime the registry first."""
    if not registered():
        load_all()
    for p in registered():
        if p.slug == slug:
            return p
    return None


def by_category(category: str) -> Iterable[ProviderProfile]:
    if not registered():
        load_all()
    return [p for p in registered() if p.category == category]


__all__ = [
    "CATEGORY_EMAIL",
    "CATEGORY_SOCIAL",
    "CATEGORY_VPN",
    "CATEGORY_WEBMAIL",
    "CATEGORY_VALUES",
    "ProviderField",
    "ProviderProfile",
    "by_category",
    "get",
    "load_all",
    "register",
    "registered",
]
