# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Manual-assist browser launcher for the Identity Generator.

The operator does the actual signup. This module just opens the
provider's signup URL through the chosen transport, prints the
generated values in a copy-paste-friendly block, and returns. There
is no captcha solving, no anti-bot rotation, no automated form
submission — by design.

Launch strategy, in order of preference:

1. **Tor Browser** — if it's on PATH (``tor-browser`` / ``torbrowser-launcher``)
   and the transport is Tor, spawn it pointed at the URL. Tor Browser
   already isolates per-tab, so the SOCKS isolation token from
   :mod:`darkcat.identity.transport` is informational rather than wired
   into the browser session. (Future work: spin up a fresh Tor profile
   per identity to harden isolation.)
2. **Plain xdg-open / open with proxy env** — fall back to the system
   browser launcher with ``HTTP_PROXY`` / ``HTTPS_PROXY`` set, when the
   transport is proxy or i2p. The user's default browser will pick those
   up.
3. **Print-only mode** — if neither launcher works, dump the URL,
   transport coordinates, and generated fields to stdout and let the
   operator paste them somewhere safe. Always succeeds; never fails the
   ``identity new`` command on a failed launch.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from darkcat.identity.generator import GeneratedIdentity
from darkcat.identity.providers.base import ProviderProfile
from darkcat.identity.transport import (
    KIND_I2P,
    KIND_PROXY,
    KIND_TOR,
    KIND_VPN_PIN,
    TransportChoice,
)


@dataclass
class LaunchResult:
    method: str             # "tor-browser" | "xdg-open" | "print-only"
    detail: str             # human-readable summary
    proxies: dict           # what the browser should use, if any
    fields: dict            # form-field-name -> generated value


def _which(*names: str) -> Optional[str]:
    for n in names:
        path = shutil.which(n)
        if path:
            return path
    return None


def _proxies_for_browser(choice: TransportChoice, cfg) -> dict:
    """Like :meth:`TransportChoice.proxies_for` but tolerant of
    ``vpn-pin`` (the launcher doesn't actually need a working proxy
    URL — it just shows the operator what the choice was)."""
    try:
        return choice.proxies_for(cfg)
    except NotImplementedError:
        return {"http": "(vpn-pin)", "https": "(vpn-pin)"}


def _resolve_fields(
    profile: ProviderProfile,
    persona,
    gen: Optional[GeneratedIdentity] = None,
) -> dict:
    """Map ``ProviderField.source`` → the value on the freshly-generated
    persona. ``gen`` is the original generator output, used as a
    fallback for fields that didn't get persisted (e.g. Disroot's
    'reason' field maps to ``purpose_tag``).
    """
    out: dict = {}
    for f in profile.fields:
        source = f.source
        # Persona attribute lookup with a small alias table for fields
        # whose generator name differs from the persona attribute name.
        aliases = {
            "handle": "handle",
            "password": "password",
            "display_name": "display_name",
            "birthdate": "birthdate",
            "locale": "locale",
            "timezone": "timezone",
            "bio": "bio",
            "recovery_email": "recovery_email",
            "purpose_tag": "purpose_tag",
            "recovery_codes": "recovery_codes",
        }
        attr = aliases.get(source, source)
        v = getattr(persona, attr, None)
        if v is None and gen is not None:
            v = getattr(gen, source, None)
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v) if v else None
        out[f.name] = v
    return out


def launch(
    profile: ProviderProfile,
    persona,
    choice: TransportChoice,
    cfg,
    *,
    gen: Optional[GeneratedIdentity] = None,
    signup_url: Optional[str] = None,
    spawn: bool = True,
) -> LaunchResult:
    """Open the provider's signup URL for the operator.

    ``spawn=False`` returns the populated :class:`LaunchResult` without
    actually exec'ing a browser — used by tests and by code paths that
    want to print the helper block without opening anything.
    """
    url = signup_url or profile.signup_url
    proxies = _proxies_for_browser(choice, cfg)
    fields = _resolve_fields(profile, persona, gen)

    if not spawn:
        return LaunchResult(
            method="print-only",
            detail="spawn disabled by caller",
            proxies=proxies,
            fields=fields,
        )

    if choice.kind == KIND_TOR:
        tb = _which("tor-browser", "torbrowser-launcher", "tor-browser-launcher")
        if tb:
            try:
                subprocess.Popen(
                    [tb, url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return LaunchResult(
                    method="tor-browser",
                    detail=f"opened {url} in Tor Browser",
                    proxies=proxies,
                    fields=fields,
                )
            except OSError as e:
                # Fall through to xdg-open with proxy env.
                _ = e

    opener = _which("xdg-open", "open")
    if opener and choice.kind in (KIND_TOR, KIND_I2P, KIND_PROXY):
        env = os.environ.copy()
        # The system browser usually honours these for plain HTTP/HTTPS.
        if proxies.get("http"):
            env["HTTP_PROXY"] = proxies["http"]
            env["http_proxy"] = proxies["http"]
        if proxies.get("https"):
            env["HTTPS_PROXY"] = proxies["https"]
            env["https_proxy"] = proxies["https"]
        try:
            subprocess.Popen(
                [opener, url],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return LaunchResult(
                method="xdg-open",
                detail=(
                    f"opened {url} in default browser with HTTP(S)_PROXY="
                    f"{proxies.get('https') or proxies.get('http') or '-'}"
                ),
                proxies=proxies,
                fields=fields,
            )
        except OSError:
            pass

    # vpn-pin and any failure path drops through here.
    return LaunchResult(
        method="print-only",
        detail=(
            "no Tor Browser found and xdg-open unavailable — open the "
            "URL manually in a transport-isolated browser"
        ),
        proxies=proxies,
        fields=fields,
    )


def render_block(profile: ProviderProfile, result: LaunchResult, url: str) -> str:
    """Return a multi-line copy-paste block for the operator: URL,
    transport, no-phone path, then field-by-field values. Pure text;
    callers can route through Rich for colour or print verbatim.
    """
    lines: list[str] = []
    lines.append(f"signup URL: {url}")
    if result.method != "print-only":
        lines.append(f"launched:   {result.detail}")
    else:
        lines.append(f"manual:     {result.detail}")
    if result.proxies:
        proxy_summary = result.proxies.get("https") or result.proxies.get("http") or "-"
        lines.append(f"transport:  {proxy_summary}")
    lines.append("")
    lines.append("paste these into the form (visible-once for password):")
    for k, v in result.fields.items():
        if v in (None, "", []):
            continue
        lines.append(f"  {k:<16} {v}")
    lines.append("")
    lines.append(f"no-phone path: {profile.no_phone_path}")
    return "\n".join(lines)


__all__ = ["LaunchResult", "launch", "render_block"]
