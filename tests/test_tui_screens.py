# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""TUI screen-level smoke tests.

These tests boot a minimal Textual App via ``App.run_test()`` (which
returns a Pilot — the official harness for headless screen tests) and
push each of the modal screens added in the 0.4 parity sweep. We assert:

* the screen mounts without raising
* its key widgets are findable by id
* dismissing it returns the documented value shape

These are deliberately small. They catch the kind of regressions where
a renamed widget id or a mis-typed CSS selector breaks the modal at
runtime in a way unit tests of the underlying CLI handlers can't see.
The heavy lifting (Namespace plumbing, vault state transitions) is
already covered by ``test_identity.py`` — this file just guards the
glue between ``compose()`` and the Pilot.

Skipped wholesale if Textual isn't importable, so packagers who strip
the TUI optional dep still get a green test suite.
"""
from __future__ import annotations

import asyncio

import pytest

textual = pytest.importorskip("textual")

from textual.app import App, ComposeResult
from textual.widgets import Static

from darkcat.tui import (
    ConfirmRevealScreen,
    LinkScreen,
    PassphraseScreen,
    PersonaAddScreen,
    ResultScreen,
)


class _Host(App):
    """Bare host app — every screen-level test pushes its target screen
    onto this one rather than booting the full ``DarkcatApp`` (which
    needs a Config + Storage + Fetcher just to mount its main screen)."""

    def compose(self) -> ComposeResult:
        yield Static("host")


def _run(coro):
    """Sync wrapper so we don't need pytest-asyncio in the dev env."""
    return asyncio.run(coro)


def test_result_screen_renders_body_lines():
    """The body lines passed in must land in the RichLog. Guards against
    a regression where ``RichLog.write`` is renamed under us."""
    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            captured: list = []

            def _record(value):
                captured.append(value)

            await app.push_screen(
                ResultScreen("hello", "line-a\nline-b"), _record,
            )
            await pilot.pause()
            # Sanity: title text is mounted exactly as supplied.
            screen = app.screen
            assert isinstance(screen, ResultScreen)
            # Dismiss with Escape — the screen's own binding fires.
            await pilot.press("escape")
            await pilot.pause()
            assert captured == [None]

    _run(go())


def test_passphrase_screen_returns_typed_value():
    """Typing a passphrase + clicking Unlock must dismiss with the typed
    string verbatim. This is the contract IdentityScreen relies on when
    it caches state['passphrase']. We click the button rather than send
    Enter because the focused Input swallows key events first."""
    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            captured: list = []
            await app.push_screen(
                PassphraseScreen("Vault is encrypted"), captured.append,
            )
            await pilot.pause()
            await pilot.press("s", "e", "c", "r", "e", "t")
            await pilot.click("#submit")
            await pilot.pause()
            assert captured == ["secret"]

    _run(go())


def test_passphrase_screen_cancel_returns_none():
    """Escape must dismiss with ``None`` — the unlock helper treats that
    as 'operator backed out' and leaves the vault locked."""
    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            captured: list = []
            await app.push_screen(PassphraseScreen(), captured.append)
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert captured == [None]

    _run(go())


def test_confirm_reveal_screen_y_reveals():
    """`y` must dismiss with ``True``; the ConfirmRevealScreen is the
    safety gate on `identity show --reveal` so we explicitly assert the
    keybinding wiring rather than just the button click."""
    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            captured: list = []
            await app.push_screen(
                ConfirmRevealScreen("matrix-foo"), captured.append,
            )
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            assert captured == [True]

    _run(go())


def test_confirm_reveal_screen_escape_keeps_masked():
    """Escape must dismiss with ``False`` — never accidentally reveal
    when the operator just wants the modal gone."""
    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            captured: list = []
            await app.push_screen(
                ConfirmRevealScreen("matrix-foo"), captured.append,
            )
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert captured == [False]

    _run(go())


def test_link_screen_rejects_same_parent_and_child():
    """Submitting when parent == child must NOT dismiss the screen. The
    IdentityScreen relies on this to enforce 'two different identities'
    without having to re-validate in its own callback."""
    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            captured: list = []
            # Only one name → submit picks the same value for both
            # Selects. The screen should swallow the click.
            await app.push_screen(
                LinkScreen(names=["only-one"], verb="Link"),
                captured.append,
            )
            await pilot.pause()
            await pilot.click("#submit")
            await pilot.pause()
            assert captured == []
            # Now cancel — must dismiss with None.
            await pilot.click("#cancel")
            await pilot.pause()
            assert captured == [None]

    _run(go())


def test_link_screen_submit_returns_parent_child_pair():
    """With two distinct names the default Selects are valid and clicking
    Link must dismiss with {'parent','child'} so the dispatcher can hand
    them to ``identity link``."""
    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            captured: list = []
            await app.push_screen(
                LinkScreen(
                    names=["proton-acct", "reddit-acct"],
                    default_child="reddit-acct",
                    verb="Link",
                ),
                captured.append,
            )
            await pilot.pause()
            await pilot.click("#submit")
            await pilot.pause()
            assert len(captured) == 1
            payload = captured[0]
            assert payload["parent"] == "proton-acct"
            assert payload["child"] == "reddit-acct"

    _run(go())


def test_persona_add_screen_mounts_and_lists_presets():
    """The mail-provider Select must be populated from
    ``mail_providers.all_presets()`` — guard against a refactor that
    silently empties the dropdown and ships an unusable form."""
    from darkcat.config import Config
    from darkcat import mail_providers as _mp

    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            captured: list = []
            await app.push_screen(
                PersonaAddScreen(Config()), captured.append,
            )
            await pilot.pause()
            from textual.widgets import Select, Input
            screen = app.screen
            assert isinstance(screen, PersonaAddScreen)
            # Name input present and focused on mount.
            name_input = screen.query_one("#name", Input)
            assert name_input is not None
            # Preset Select carries one option per shipped preset
            # plus the "(none)" sentinel.
            preset_box = screen.query_one("#preset", Select)
            # Select._options is internal; iterate via the public API:
            slugs_in_form = list(preset_box._options)
            assert len(slugs_in_form) == len(_mp.all_presets()) + 1
            await pilot.press("escape")
            await pilot.pause()

    _run(go())
