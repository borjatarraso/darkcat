# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Identity Generator — disposable, compartmentalised identities for darkcat.

The package layers an identity workflow on top of darkcat's existing
``personas`` vault: persona generation (handle / passphrase / display
name / locale / bio / birthdate), provider profiles (signup URL +
documented no-phone path + transport recommendation), per-identity
transport pinning, and status tracking (pending → confirmed → burned).

Signup itself is **manual-assist**: darkcat opens the provider's signup
page through the chosen anonymising transport and prefills generated
values where possible; the operator solves any captcha / verification
challenge and confirms the resulting account back into the vault. There
is no anti-abuse-gate bypass here by design — the workflow is sized for
a handful of accounts per provider, used to keep separate projects from
being trivially correlatable.
"""
from __future__ import annotations

from darkcat.identity.generator import (
    GeneratedIdentity,
    generate_birthdate,
    generate_bio,
    generate_display_name,
    generate_locale,
    generate_timezone,
    new_identity,
)
from darkcat.identity.launcher import LaunchResult, launch, render_block
from darkcat.identity.transport import (
    TransportChoice,
    pick_transport,
    transport_token,
)
from darkcat.identity.vault import (
    DEFAULT_PER_PROVIDER_CAP,
    IdentityVault,
    PerProviderCapExceeded,
)


def invoke_cli_capturing(cfg, ns) -> tuple[int, str, str]:
    """Run a darkcat CLI handler while capturing its Rich output.

    Dispatches on ``ns.cmd`` so frontends (TUI, GUI) get parity with the
    CLI for every command they expose — currently identity, chat, and
    mail. The module-level Rich consoles are temporarily swapped for
    ``StringIO``-backed ones so the captured strings can be dropped into
    a notify / messagebox / log.
    """
    import io
    from rich.console import Console
    from darkcat import cli as _cli

    cmd = getattr(ns, "cmd", "identity")
    handler_map = {
        "identity": _cli.cmd_identity,
        "chat":     _cli.cmd_chat,
        "mail":     _cli.cmd_mail,
        "personas": _cli.cmd_personas,
    }
    handler = handler_map.get(cmd, _cli.cmd_identity)

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    saved_out, saved_err = _cli.console, _cli.err_console
    _cli.console = Console(
        file=out_buf, force_terminal=False, highlight=False, emoji=False,
        width=120,
    )
    _cli.err_console = Console(
        file=err_buf, force_terminal=False, highlight=False, emoji=False,
        width=120,
    )
    try:
        rc = handler(cfg, ns)
    finally:
        _cli.console, _cli.err_console = saved_out, saved_err
    return rc, out_buf.getvalue(), err_buf.getvalue()


__all__ = [
    "DEFAULT_PER_PROVIDER_CAP",
    "GeneratedIdentity",
    "IdentityVault",
    "LaunchResult",
    "PerProviderCapExceeded",
    "TransportChoice",
    "generate_birthdate",
    "generate_bio",
    "generate_display_name",
    "generate_locale",
    "generate_timezone",
    "invoke_cli_capturing",
    "launch",
    "new_identity",
    "pick_transport",
    "render_block",
    "transport_token",
]
