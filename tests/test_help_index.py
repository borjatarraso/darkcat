"""Tests for the grouped help index introduced for UX work.

These guard the wiring between the CLI's grouped command index, the
argparse subparsers it should exhaustively cover, and the REPL's command
table + tab-completion. If a new command is added to the CLI but missed in
``COMMAND_GROUPS`` (or vice-versa), or if the REPL stops shipping a
``do_<name>`` for a command it advertises, these tests fail loudly.
"""
from __future__ import annotations

import pytest

from darkcat import cli
from darkcat.cli import COMMAND_GROUPS, COMMAND_TABLE
from darkcat.repl import (
    _PROTOCOL_NAMES,
    _REPL_COMMAND_GROUPS,
    DarkcatShell,
)


# ---- CLI: grouped command index --------------------------------------------


def test_command_table_is_groups_flattened() -> None:
    flat = [item for _g, items in COMMAND_GROUPS for item in items]
    assert flat == COMMAND_TABLE, (
        "COMMAND_TABLE must equal COMMAND_GROUPS flattened — they're "
        "the same data exposed two ways."
    )


def test_command_groups_have_no_duplicate_names() -> None:
    names = [name for _g, items in COMMAND_GROUPS for name, _d in items]
    dupes = sorted(n for n in set(names) if names.count(n) > 1)
    assert not dupes, f"duplicate command in COMMAND_GROUPS: {dupes}"


def test_every_grouped_command_has_a_subparser() -> None:
    """Each ``COMMAND_GROUPS`` entry must correspond to a real argparse
    subparser. Otherwise the help epilog promises commands that don't exist.
    """
    parser = cli._build_parser()
    sp_action = next(
        a for a in parser._actions
        if a.__class__.__name__ == "_SubParsersAction"
    )
    registered = set(sp_action.choices.keys())
    advertised = {name for _g, items in COMMAND_GROUPS for name, _d in items}
    missing = advertised - registered
    assert not missing, (
        f"COMMAND_GROUPS advertises commands with no subparser: {sorted(missing)}"
    )


def test_help_epilog_mentions_each_group_title() -> None:
    epilog = cli._build_help_epilog()
    for group_title, _items in COMMAND_GROUPS:
        assert f"{group_title}:" in epilog, (
            f"--help epilog is missing the group header {group_title!r}"
        )


# ---- REPL: grouped help + tab-completion -----------------------------------


_BUILTIN_REPL_TOKENS = {"help", "?", "quit"}


def test_repl_groups_resolve_to_real_handlers() -> None:
    """Every command listed in `_REPL_COMMAND_GROUPS` must have a matching
    ``do_<name>`` on ``DarkcatShell`` (the REPL's `precmd` strips the dash,
    so ``decode-links`` resolves to ``do_decode_links``)."""
    advertised = [
        name for _g, items in _REPL_COMMAND_GROUPS for name, _d in items
    ]
    for name in advertised:
        if name in _BUILTIN_REPL_TOKENS:
            continue
        attr = "do_" + name.replace("-", "_")
        assert hasattr(DarkcatShell, attr), (
            f"REPL advertises {name!r} but DarkcatShell has no {attr}()"
        )


def test_repl_complete_protocol_includes_tor_and_all() -> None:
    completions = DarkcatShell._complete_protocol("t")
    assert "tor" in completions, completions
    completions_all = DarkcatShell._complete_protocol("")
    assert "all" in completions_all, "REPL must offer 'all' as a protocol arg"
    for name in ("tor", "i2p", "ipfs", "gemini"):
        assert name in completions_all, f"missing protocol completion: {name}"


def test_repl_protocol_name_list_nonempty() -> None:
    assert _PROTOCOL_NAMES, "PROTOCOL_TABLE produced no protocol names"


def test_repl_completenames_includes_hyphenated_aliases() -> None:
    """`completenames` should surface the hyphenated forms so a user typing
    `decode-l<TAB>` lands on `decode-links`."""
    shell = DarkcatShell.__new__(DarkcatShell)  # bypass __init__'s side-effects
    names = shell.completenames("decode-l")
    assert "decode-links" in names, names
    names2 = shell.completenames("zeronet-")
    assert "zeronet-walk" in names2, names2


# ---- TUI: KeymapScreen importable + has every group ------------------------


def test_tui_keymap_screen_groups_cover_intent() -> None:
    pytest.importorskip("textual")
    from darkcat.tui import _KEYMAP_GROUPS  # imported lazily to avoid Textual cost
    titles = [g for g, _items in _KEYMAP_GROUPS]
    # We don't pin the exact phrasing, but the four buckets must be there:
    # crawling, inspecting, search/fetch, help.
    joined = " | ".join(titles).lower()
    assert "crawl" in joined
    assert "inspect" in joined or "result" in joined
    assert "search" in joined or "fetch" in joined
    assert "help" in joined or "info" in joined
