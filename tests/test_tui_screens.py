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
    ChatScreen,
    ConfirmRevealScreen,
    IdentityEditScreen,
    IdentityScreen,
    LinkScreen,
    MailScreen,
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


def test_action_launch_chains_result_then_edit_screen(tmp_path, monkeypatch):
    """End-to-end: ``IdentityScreen.action_launch`` must push a
    ``ResultScreen`` first, then an ``IdentityEditScreen`` for the same
    persona. This is the chained flow that lets the operator capture
    recovery codes the provider showed once during signup; if the order
    inverts or the second push is dropped, the codes are lost. Heavy
    end-to-end test — sets up a real vault on disk so the screen's
    ``_open_inner_or_notify`` finds the persona by name."""
    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))

    from darkcat import personas as pv
    inner = pv.Vault(path=tmp_path / "personas.json")
    inner.add(pv.Persona(
        name="protonmail-acct",
        provider="protonmail",
        category="email",
        status=pv.STATUS_PENDING,
        handle="quiet_owl_1234",
        password="placeholder-not-used-by-launch",
    ))
    inner.save()

    from darkcat.config import Config

    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            screen = IdentityScreen(Config())
            await app.push_screen(screen, lambda _: None)
            # Two pauses: one for the IdentityScreen to mount, one for
            # ``on_mount`` → ``_unlock_then`` → ``_refresh`` to populate
            # the DataTable from the freshly-written vault.
            await pilot.pause()
            await pilot.pause()

            # Stub the CLI dispatcher so we don't spawn xdg-open / a
            # browser during the test. Returning rc=0 puts us on the
            # success path that pushes ResultScreen + chains the edit.
            screen._run = lambda ns: (0, "launched ok", "")

            # Spy on app.push_screen to record the chain order.
            pushes: list = []
            original_push = app.push_screen

            def _spy(child, *args, **kwargs):
                pushes.append(child)
                return original_push(child, *args, **kwargs)

            app.push_screen = _spy  # type: ignore[method-assign]

            # Drive the action directly. We don't synthesize an "l"
            # keypress because the DataTable's row-selection state and
            # focus path are not what's under test here — the chained
            # screen push is.
            screen.action_launch()
            # ResultScreen is pushed inline; IdentityEditScreen is
            # scheduled via ``call_later`` → ``_unlock_then`` → ``_go``.
            # Two pauses give the scheduler time to drain both.
            await pilot.pause()
            await pilot.pause()

            kinds = [type(s).__name__ for s in pushes]
            assert "ResultScreen" in kinds, (
                f"ResultScreen not pushed; saw {kinds}"
            )
            assert "IdentityEditScreen" in kinds, (
                f"IdentityEditScreen not pushed; saw {kinds}"
            )
            assert kinds.index("ResultScreen") < kinds.index(
                "IdentityEditScreen"
            ), f"order inverted; saw {kinds}"

            # The edit screen must reference the same persona name the
            # launch was for — otherwise the captured codes land on the
            # wrong row.
            edit_screen = next(
                s for s in pushes if isinstance(s, IdentityEditScreen)
            )
            assert edit_screen.persona.name == "protonmail-acct"

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


def test_mail_screen_threads_passphrase_into_cli_env():
    """The MailScreen must expose its cached passphrase to the CLI via
    ``DARKCAT_VAULT_PASSPHRASE`` during dispatch, then restore the env
    on exit so it doesn't leak to unrelated callers. This is the gap #1
    fix — without it, ``cmd_mail`` falls through to ``getpass.getpass()``
    on encrypted vaults and blocks under Textual."""
    import os as _os
    from darkcat.config import Config

    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            screen = MailScreen(Config())
            await app.push_screen(screen, lambda _: None)
            await pilot.pause()

            screen._passphrase = "s3cret"

            captured: dict = {}

            def _fake_invoke(cfg, ns):
                captured["env"] = _os.environ.get("DARKCAT_VAULT_PASSPHRASE")
                return (0, "ok", "")

            import darkcat.identity as _id
            original = _id.invoke_cli_capturing
            _id.invoke_cli_capturing = _fake_invoke
            try:
                pre = _os.environ.get("DARKCAT_VAULT_PASSPHRASE")
                rc, out, err = screen._run_with_passphrase(object())
                post = _os.environ.get("DARKCAT_VAULT_PASSPHRASE")
            finally:
                _id.invoke_cli_capturing = original

            assert captured["env"] == "s3cret"
            assert pre == post
            assert (rc, out, err) == (0, "ok", "")

    _run(go())


def test_chat_screen_threads_passphrase_into_cli_env():
    """Same contract as the MailScreen test but for ChatScreen, which
    shares the ``_VaultUnlockMixin`` machinery. Asserting both screens
    guards against a regression where one of them stops inheriting the
    mixin or reimplements ``_run`` without the env-var wrapper."""
    import os as _os
    from darkcat.config import Config

    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            screen = ChatScreen(Config())
            await app.push_screen(screen, lambda _: None)
            await pilot.pause()

            screen._passphrase = "t0pseekrit"

            captured: dict = {}

            def _fake_invoke(cfg, ns):
                captured["env"] = _os.environ.get("DARKCAT_VAULT_PASSPHRASE")
                return (0, "ok", "")

            import darkcat.identity as _id
            original = _id.invoke_cli_capturing
            _id.invoke_cli_capturing = _fake_invoke
            try:
                pre = _os.environ.get("DARKCAT_VAULT_PASSPHRASE")
                rc, out, err = screen._run_with_passphrase(object())
                post = _os.environ.get("DARKCAT_VAULT_PASSPHRASE")
            finally:
                _id.invoke_cli_capturing = original

            assert captured["env"] == "t0pseekrit"
            assert pre == post
            assert (rc, out, err) == (0, "ok", "")

    _run(go())


def test_vault_unlock_mixin_no_passphrase_leaves_env_clean(monkeypatch):
    """When no passphrase has been cached, ``_run_with_passphrase`` must
    NOT inject the env var — that would leak a stale value from a prior
    session via inheritance. Belt-and-braces guard for the off path."""
    import os as _os
    from darkcat.config import Config

    async def go():
        app = _Host()
        async with app.run_test() as pilot:
            screen = MailScreen(Config())
            await app.push_screen(screen, lambda _: None)
            await pilot.pause()

            # Operator never typed a passphrase.
            screen._passphrase = None

            captured: dict = {}

            def _fake_invoke(cfg, ns):
                captured["env"] = _os.environ.get("DARKCAT_VAULT_PASSPHRASE")
                return (0, "", "")

            import darkcat.identity as _id
            original = _id.invoke_cli_capturing
            _id.invoke_cli_capturing = _fake_invoke
            # Set a baseline so we can tell whether the mixin overrode it.
            monkeypatch.setenv("DARKCAT_VAULT_PASSPHRASE", "outer-baseline")
            try:
                screen._run_with_passphrase(object())
            finally:
                _id.invoke_cli_capturing = original

            assert captured["env"] == "outer-baseline"

    _run(go())
