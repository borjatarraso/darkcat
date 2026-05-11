# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Identity-aware view over the existing persona vault.

This is a *thin wrapper*: storage, encryption, atomic writes, and the
``Persona`` schema all live in :mod:`darkcat.personas`. What this module
adds:

- queries the identity workflow needs (``per_provider_count``,
  ``by_status``, ``by_purpose``, link-graph helpers);
- a soft per-provider cap that refuses to create a new active identity
  past the limit, so a single project's identity sprawl can't grow
  unnoticed.

The cap is a guardrail, not an enforcement. ``--force`` bypasses it
because legitimate edge cases exist (e.g. replacing a burned account on
the same provider before the burn is final).
"""
from __future__ import annotations

import time
from typing import Optional

from darkcat import personas as _pv


# Per-provider soft cap on simultaneously-active identities. "Active"
# means status in {pending, confirmed} — burned and locked don't count.
# Sized for the use case Borja described: a few projects per provider,
# never bulk. Override with --cap on the CLI.
DEFAULT_PER_PROVIDER_CAP = 5


class PerProviderCapExceeded(RuntimeError):
    """Raised when adding an identity would exceed the per-provider cap.

    The CLI catches this and tells the operator to use ``--force`` if
    they really mean it.
    """


class IdentityVault:
    """Identity-flavoured wrapper around :class:`darkcat.personas.Vault`.

    Intentionally does *not* subclass — it forwards a small surface and
    keeps the underlying vault accessible as ``.inner`` for callers that
    want to fall through to plain-persona operations.
    """

    def __init__(
        self,
        inner: _pv.Vault,
        *,
        per_provider_cap: int = DEFAULT_PER_PROVIDER_CAP,
    ) -> None:
        self.inner = inner
        self.per_provider_cap = per_provider_cap

    # ---- queries ----------------------------------------------------

    @staticmethod
    def _is_active(p: _pv.Persona) -> bool:
        return p.status in (_pv.STATUS_PENDING, _pv.STATUS_CONFIRMED)

    def all_identities(self) -> list[_pv.Persona]:
        """Personas that have been touched by the identity workflow.

        We treat any persona with a ``provider`` field set as an
        identity-managed record. Plain credential-bag personas (the v1
        layout) lack ``provider`` and stay invisible to this view.
        """
        return [p for p in self.inner.personas if p.provider]

    def per_provider_count(self, provider: str, *, active_only: bool = True) -> int:
        rows = [p for p in self.all_identities() if p.provider == provider]
        if active_only:
            rows = [p for p in rows if self._is_active(p)]
        return len(rows)

    def by_status(self, status: str) -> list[_pv.Persona]:
        return [p for p in self.all_identities() if p.status == status]

    def by_purpose(self, purpose: str) -> list[_pv.Persona]:
        return [p for p in self.all_identities() if (p.purpose_tag or "") == purpose]

    def find(
        self,
        *,
        provider: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        purpose: Optional[str] = None,
    ) -> list[_pv.Persona]:
        out = self.all_identities()
        if provider:
            out = [p for p in out if p.provider == provider]
        if category:
            out = [p for p in out if p.category == category]
        if status:
            out = [p for p in out if p.status == status]
        if purpose:
            out = [p for p in out if (p.purpose_tag or "") == purpose]
        return out

    # ---- mutation ---------------------------------------------------

    def add(
        self,
        persona: _pv.Persona,
        *,
        replace: bool = False,
        force: bool = False,
    ) -> None:
        """Insert ``persona`` into the underlying vault.

        Refuses when the per-provider cap would be exceeded unless
        ``force=True``. The cap counts pending+confirmed; burned and
        locked don't.
        """
        if persona.provider and not force:
            existing = self.per_provider_count(persona.provider, active_only=True)
            # Replacing an active identity in the same slot is a wash; only
            # *additional* slots count toward the cap.
            already_in_vault = self.inner.get(persona.name) is not None
            projected = existing if (already_in_vault and replace) else existing + 1
            if projected > self.per_provider_cap:
                raise PerProviderCapExceeded(
                    f"adding {persona.name!r} would put {persona.provider} at "
                    f"{projected} active identities (cap is "
                    f"{self.per_provider_cap}); pass --force to override"
                )
        self.inner.add(persona, replace=replace)

    def confirm(self, name: str) -> _pv.Persona:
        """Promote ``pending`` → ``confirmed`` and stamp ``confirmed_at``."""
        p = self.inner.get(name)
        if p is None:
            raise KeyError(name)
        if p.status == _pv.STATUS_CONFIRMED:
            return p  # idempotent
        if p.status not in (_pv.STATUS_PENDING, _pv.STATUS_LOCKED):
            raise ValueError(
                f"cannot confirm {name!r} from status {p.status!r}; expected pending or locked"
            )
        p.status = _pv.STATUS_CONFIRMED
        p.confirmed_at = time.time()
        return p

    def burn(self, name: str, *, note: Optional[str] = None) -> _pv.Persona:
        """Mark identity as burned. Doesn't delete the row — the audit
        trail (when, what was on it) stays in the vault for forensics.
        """
        p = self.inner.get(name)
        if p is None:
            raise KeyError(name)
        p.status = _pv.STATUS_BURNED
        p.burned_at = time.time()
        if note:
            p.notes = ((p.notes or "") + f"\n[burned {time.strftime('%Y-%m-%d')}] {note}").strip()
        return p

    def rotate_password(self, name: str, new_password: str) -> _pv.Persona:
        p = self.inner.get(name)
        if p is None:
            raise KeyError(name)
        p.password = new_password
        return p

    # ---- link graph -------------------------------------------------

    def link(self, parent: str, child: str) -> None:
        """Record that identity ``parent`` was used to confirm ``child``
        (e.g. a Gmail used as ProtonMail's recovery address).

        The edge is one-directional and stored on the *child* — that's
        the side that operationally depends on the parent.
        """
        if self.inner.get(parent) is None:
            raise KeyError(parent)
        c = self.inner.get(child)
        if c is None:
            raise KeyError(child)
        if parent == child:
            raise ValueError("cannot link an identity to itself")
        if parent not in c.linked_identities:
            c.linked_identities.append(parent)

    def unlink(self, parent: str, child: str) -> bool:
        c = self.inner.get(child)
        if c is None or parent not in c.linked_identities:
            return False
        c.linked_identities.remove(parent)
        return True

    # ---- pass-throughs ----------------------------------------------

    def save(self) -> None:
        self.inner.save()


__all__ = [
    "DEFAULT_PER_PROVIDER_CAP",
    "IdentityVault",
    "PerProviderCapExceeded",
]
