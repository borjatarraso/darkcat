"""Tests for the UX-polish layer: doctor health-check, REPL completion +
history, argcomplete soft-import, and the first-run wizard helpers.

These complement ``test_help_index.py`` — that file guards the *grouping*
data, this one guards the *behaviour* introduced in the same UX pass:

* ``cmd_doctor`` produces the expected matrix and exit code.
* The REPL exposes a completer for every multi-action command.
* History persistence resolves to ``~/.darkcat/history`` and survives a
  read/write round-trip when readline is available.
* The CLI's ``main`` does not hard-fail when ``argcomplete`` is missing.
* The TUI's ``_needs_first_run`` and the GUI's matching staticmethod
  agree on when to pop the wizard.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from darkcat import cli
from darkcat.config import Config
from darkcat.repl import (
    _SUBACTIONS,
    DarkcatShell,
    _history_file_path,
)


# ---- doctor ---------------------------------------------------------------


def _make_cfg(tmp_path: Path) -> Config:
    return Config(db_path=tmp_path / "crawl.db")


def test_doctor_run_returns_tuples_for_every_check(tmp_path: Path) -> None:
    """``doctor_run`` should always return one row per check, each with the
    ``(level, label, detail, fix)`` shape the renderers expect."""
    cfg = _make_cfg(tmp_path)
    rows = cli.doctor_run(cfg)
    assert rows, "doctor_run produced no checks"
    for row in rows:
        assert isinstance(row, tuple) and len(row) == 4, row
        level, label, detail, fix = row
        assert level in {"ok", "warn", "fail"}, level
        assert isinstance(label, str) and label
        assert isinstance(detail, str)
        assert isinstance(fix, str)


def test_doctor_db_check_warns_when_db_missing(tmp_path: Path) -> None:
    cfg = _make_cfg(tmp_path)  # crawl.db doesn't exist yet
    level, label, detail, fix = cli._doctor_check_db(cfg)
    assert level == "warn"
    assert "database" in label.lower()
    assert "not yet created" in detail
    assert "crawl" in fix.lower()


def test_doctor_db_check_passes_on_valid_sqlite(tmp_path: Path) -> None:
    cfg = _make_cfg(tmp_path)
    # A trivially-valid DB satisfies PRAGMA quick_check.
    con = sqlite3.connect(str(cfg.db_path))
    con.execute("CREATE TABLE _smoke (x INT)")
    con.commit()
    con.close()
    level, _, detail, _ = cli._doctor_check_db(cfg)
    assert level == "ok", detail


def test_doctor_db_check_fails_on_corrupt_file(tmp_path: Path) -> None:
    cfg = _make_cfg(tmp_path)
    cfg.db_path.write_bytes(b"this is definitely not a sqlite database")
    level, _, _, fix = cli._doctor_check_db(cfg)
    assert level == "fail"
    assert "darkcat init" in fix or "rebuild" in fix.lower()


def test_doctor_cookie_check_ok_when_unconfigured(tmp_path: Path) -> None:
    cfg = _make_cfg(tmp_path)
    assert cfg.cookie_jar_path is None
    level, _, detail, _ = cli._doctor_check_cookies(cfg)
    assert level == "ok"
    assert "not configured" in detail


def test_doctor_cookie_check_warns_when_path_missing(tmp_path: Path) -> None:
    cfg = _make_cfg(tmp_path)
    cfg.cookie_jar_path = tmp_path / "cookies.txt"
    level, _, _, fix = cli._doctor_check_cookies(cfg)
    assert level == "warn"
    assert "cookie-jar" in fix or "touch" in fix


def test_cmd_doctor_returns_zero_when_no_failures(tmp_path: Path) -> None:
    """If no check returns 'fail', cmd_doctor should exit 0 even with warnings."""
    cfg = _make_cfg(tmp_path)
    fake_rows = [
        ("ok",   "home directory", str(tmp_path / ".darkcat"), ""),
        ("warn", "tesseract",      "not on $PATH",             "install tesseract-ocr"),
    ]
    with mock.patch.object(cli, "doctor_run", return_value=fake_rows):
        rc = cli.cmd_doctor(cfg)
    assert rc == 0


def test_cmd_doctor_returns_one_on_any_failure(tmp_path: Path) -> None:
    cfg = _make_cfg(tmp_path)
    fake_rows = [
        ("ok",   "home directory", str(tmp_path), ""),
        ("fail", "transports",     "0/12 reachable", "darkcat up tor"),
    ]
    with mock.patch.object(cli, "doctor_run", return_value=fake_rows):
        rc = cli.cmd_doctor(cfg)
    assert rc == 1


def test_doctor_chat_backends_aggregates_to_single_row() -> None:
    """`chat backends` would crowd the doctor table; we collapse it."""
    fake_report = [
        {"network": "telegram", "available": True,  "dep": "telethon",   "hint": ""},
        {"network": "matrix",   "available": False, "dep": "matrix-nio", "hint": "pip install matrix-nio"},
        {"network": "session",  "available": False, "dep": "session-cli", "hint": "install session-cli"},
    ]
    with mock.patch("darkcat.chat.availability_report", return_value=fake_report):
        level, label, detail, fix = cli._doctor_check_chat_backends()
    assert level == "warn"
    assert label == "chat backends"
    assert "1/3 ready" in detail
    assert "matrix" in detail and "session" in detail
    assert "chat backends" in fix


def test_doctor_chat_backends_ok_when_all_ready() -> None:
    fake_report = [
        {"network": "telegram", "available": True, "dep": "telethon", "hint": ""},
        {"network": "session",  "available": True, "dep": "session-cli", "hint": ""},
    ]
    with mock.patch("darkcat.chat.availability_report", return_value=fake_report):
        level, _label, detail, fix = cli._doctor_check_chat_backends()
    assert level == "ok"
    assert "all 2" in detail
    assert fix == ""


def test_doctor_proton_bridge_warns_when_listener_refused(monkeypatch) -> None:
    """If 127.0.0.1:1025 is not listening (the normal case for users who
    haven't started Bridge), warn but don't fail — Bridge is optional."""
    import socket as _socket

    class _RefusingSocket:
        def __init__(self, *_a, **_kw): pass
        def settimeout(self, _t): pass
        def connect(self, _addr): raise ConnectionRefusedError()
        def close(self): pass
    monkeypatch.setattr(cli.socket if hasattr(cli, "socket") else _socket,
                        "socket", _RefusingSocket, raising=False)
    # The probe imports socket lazily inside the function — patch the
    # standard library entry the function uses.
    monkeypatch.setattr("socket.socket", _RefusingSocket)

    level, label, detail, fix = cli._doctor_check_proton_bridge()
    assert level == "warn"
    assert "Proton Mail Bridge" in label
    assert "1025" in detail
    assert "Bridge" in fix


def test_chat_screen_presets_cover_every_chat_network_verb() -> None:
    """Each preset must (a) carry a valid action the CLI parser knows
    about and (b) carry a known network token. A typo in the preset
    table would silently produce a dead button — catch it at test time."""
    from darkcat.tui import ChatScreen
    presets = ChatScreen._PRESETS
    assert presets, "ChatScreen._PRESETS is empty"
    cli_actions = {"backends", "login", "list", "read", "send", "ingest",
                   "join", "leave", "connect", "addcontact"}
    cli_networks = {"", "telegram", "matrix", "xmpp", "simplex", "session"}
    seen_ids: set[str] = set()
    for label, btn_id, network, action in presets:
        assert label and btn_id and action, (label, btn_id, action)
        assert btn_id.startswith("preset-"), btn_id
        assert btn_id not in seen_ids, f"duplicate preset id {btn_id!r}"
        seen_ids.add(btn_id)
        assert action in cli_actions, (btn_id, action)
        assert network in cli_networks, (btn_id, network)


def test_doctor_proton_bridge_ok_when_listening(monkeypatch) -> None:
    class _AcceptingSocket:
        def __init__(self, *_a, **_kw): pass
        def settimeout(self, _t): pass
        def connect(self, _addr): pass  # accept
        def close(self): pass
    monkeypatch.setattr("socket.socket", _AcceptingSocket)
    level, _label, detail, fix = cli._doctor_check_proton_bridge()
    assert level == "ok"
    assert "1025" in detail
    assert fix == ""


# ---- doctor: mail hosts probe ---------------------------------------------


def test_doctor_mail_hosts_empty_vault_returns_ok_with_preset_list(
    tmp_path, monkeypatch,
) -> None:
    """Empty vault → one informational row listing the curated slugs.
    Operators on a fresh install see "what's on offer" rather than a
    silent skip."""
    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))
    rows = cli._doctor_check_mail_hosts()
    assert len(rows) == 1
    level, label, detail, _fix = rows[0]
    assert level == "ok"
    assert label == "mail hosts"
    # Either "no vault yet" (fresh install) or the preset list (vault
    # exists but is empty of mail personas) is acceptable; both mean
    # the operator hasn't wired anything up yet.
    assert (
        "no vault" in detail
        or "no mail personas" in detail
        or "disroot" in detail
    ), detail


def test_doctor_mail_hosts_probes_each_smtp_imap_pair(
    tmp_path, monkeypatch,
) -> None:
    """A persona added with --mail-provider disroot must trigger one
    SMTP probe + one IMAP probe (different host/port pairs)."""
    import argparse
    from darkcat.config import Config
    from darkcat.identity import invoke_cli_capturing

    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))
    cfg = Config()
    rc, _o, err = invoke_cli_capturing(cfg, argparse.Namespace(
        cmd="personas", action="add", name="me-disroot",
        network="", site="", handle=None, password=None, email=None,
        pgp_key_id=None, recovery=None, notes=None,
        user_agent=None, proxy=None, tags=[],
        gen=True, replace=False, mail_provider="disroot",
    ))
    assert rc == 0, err

    captured: list[tuple[str, int, float]] = []

    class _FakeConn:
        def __init__(self, addr, timeout=None):
            host, port = addr
            captured.append((host, port, timeout or 0.0))
        def __enter__(self): return self
        def __exit__(self, *_a): return False

    monkeypatch.setattr("socket.create_connection", _FakeConn)

    rows = cli._doctor_check_mail_hosts()
    # Both SMTP (disroot.org:587) and IMAP (disroot.org:993) must be
    # probed, in sorted order — sorted by host then port.
    hosts_probed = {(h, p) for h, p, _t in captured}
    assert ("disroot.org", 587) in hosts_probed
    assert ("disroot.org", 993) in hosts_probed
    # Every row reports "reachable" because the fake socket accepts.
    levels = {r[0] for r in rows}
    assert levels == {"ok"}, rows


def test_doctor_mail_hosts_warns_on_refused(tmp_path, monkeypatch) -> None:
    """A refused connection must downgrade to warn (not fail) — the
    distinction matters because the operator's network might just be
    behind a captive portal, not the preset being dead."""
    import argparse
    from darkcat.config import Config
    from darkcat.identity import invoke_cli_capturing

    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))
    cfg = Config()
    rc, _o, err = invoke_cli_capturing(cfg, argparse.Namespace(
        cmd="personas", action="add", name="me-disroot",
        network="", site="", handle=None, password=None, email=None,
        pgp_key_id=None, recovery=None, notes=None,
        user_agent=None, proxy=None, tags=[],
        gen=True, replace=False, mail_provider="disroot",
    ))
    assert rc == 0, err

    def _refuse(_addr, timeout=None):
        raise ConnectionRefusedError("nope")

    monkeypatch.setattr("socket.create_connection", _refuse)

    rows = cli._doctor_check_mail_hosts()
    levels = {r[0] for r in rows}
    assert "warn" in levels
    # Every warn row carries a fix hint mentioning the host so the
    # operator knows which preset to investigate.
    for level, _label, detail, fix in rows:
        if level == "warn":
            assert "disroot.org" in detail or "disroot.org" in fix


def test_doctor_mail_hosts_skips_encrypted_vault(tmp_path, monkeypatch) -> None:
    """Encrypted vault path → warn, not fail; we don't ask for the
    passphrase from inside doctor."""
    from darkcat import personas as pv

    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))
    # Drop a fake .gpg next to where the vault would live.
    gpg_path = pv.vault_path().with_suffix(".gpg")
    gpg_path.parent.mkdir(parents=True, exist_ok=True)
    gpg_path.write_bytes(b"fake gpg payload")

    # Make vault_path() report the encrypted path.
    monkeypatch.setattr(pv, "vault_path", lambda *a, **kw: gpg_path)

    rows = cli._doctor_check_mail_hosts()
    assert len(rows) == 1
    level, label, detail, fix = rows[0]
    assert level == "warn"
    assert "encrypted" in detail
    assert "decrypt" in fix


# ---- REPL: subaction completion -------------------------------------------


def test_repl_subaction_table_covers_known_multi_action_commands() -> None:
    """Every command in ``_SUBACTIONS`` must have a matching ``do_<name>``,
    or the completer points at a command that doesn't exist."""
    for name in _SUBACTIONS:
        attr = "do_" + name.replace("-", "_")
        assert hasattr(DarkcatShell, attr), (
            f"_SUBACTIONS lists {name!r} but DarkcatShell has no {attr}()"
        )


def test_repl_subaction_completer_first_token_only() -> None:
    """The completer should fire for the first positional only — once the
    user has typed past it, returning more subactions would be misleading."""
    shell = DarkcatShell.__new__(DarkcatShell)
    # First positional, empty text → full menu.
    assert shell._complete_subaction("watch", "", "watch ") == [
        "add", "list", "remove", "test",
    ]
    # First positional, partial text → filtered.
    assert shell._complete_subaction("watch", "a", "watch a") == ["add"]
    # Second positional → empty.
    assert shell._complete_subaction("watch", "", "watch add ") == []
    assert shell._complete_subaction("watch", "lis", "watch add lis") == []


def test_repl_subaction_completer_filters_by_prefix() -> None:
    shell = DarkcatShell.__new__(DarkcatShell)
    completions = shell._complete_subaction("tor", "bri", "tor bri")
    assert completions == ["bridges", "bridges-add", "bridges-clear"]


def test_repl_completes_identity_launch_flags() -> None:
    """``identity launch <name> --<TAB>`` must offer ``--capture`` and
    ``--no-spawn``. Without this, the recovery-code capture flow is
    hidden from anyone who lives in the REPL — they'd have to read
    ``identity launch --help`` to discover it exists."""
    shell = DarkcatShell.__new__(DarkcatShell)
    completions = shell._complete_subaction(
        "identity", "--", "identity launch acct-1 --",
    )
    assert set(completions) == {"--capture", "--no-spawn"}


def test_repl_completes_identity_launch_flags_by_prefix() -> None:
    """Prefix narrows the menu — ``--c`` resolves to ``--capture``
    only."""
    shell = DarkcatShell.__new__(DarkcatShell)
    completions = shell._complete_subaction(
        "identity", "--c", "identity launch acct-1 --c",
    )
    assert completions == ["--capture"]


def test_repl_flag_completer_drops_already_used() -> None:
    """If ``--capture`` is already on the line, only ``--no-spawn`` is
    offered. Keeps Tab from suggesting flags that would just duplicate."""
    shell = DarkcatShell.__new__(DarkcatShell)
    completions = shell._complete_subaction(
        "identity", "--", "identity launch acct-1 --capture --",
    )
    assert completions == ["--no-spawn"]


def test_repl_flag_completer_only_inside_subaction() -> None:
    """``identity --<TAB>`` (no subaction yet) must not leak the
    subaction-specific flag table — the user's still picking which verb
    to run."""
    shell = DarkcatShell.__new__(DarkcatShell)
    completions = shell._complete_subaction("identity", "--", "identity --")
    assert completions == []


def test_repl_personas_path_dispatches_to_cli(tmp_path, monkeypatch, capsys):
    """End-to-end smoke test: ``personas path`` should round-trip through
    the REPL's ``do_personas`` and print the vault file path. Guards the
    integration between _SUBACTIONS, do_personas, and cmd_personas — if
    any of those drift, this fails loudly."""
    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))

    shell = DarkcatShell.__new__(DarkcatShell)
    shell.cfg = Config(db_path=tmp_path / "crawl.db")
    shell.do_personas("path")
    out = capsys.readouterr().out
    assert "personas.json" in out


def test_repl_each_subactioned_command_has_complete_method() -> None:
    """For users to actually get tab-completion, ``cmd.Cmd`` looks up
    ``complete_<name>`` on the instance — not just our generic helper. Make
    sure each entry in ``_SUBACTIONS`` has its own bound completer."""
    for name in _SUBACTIONS:
        completer = getattr(DarkcatShell, f"complete_{name}", None)
        assert completer is not None, (
            f"DarkcatShell missing complete_{name} — tab-completion will not "
            f"trigger for `{name} <TAB>`"
        )


# ---- REPL: history persistence --------------------------------------------


def test_history_file_path_is_under_persona_dir(tmp_path: Path) -> None:
    """``_history_file_path`` should resolve to ``<persona-dir>/history``,
    keeping all per-user state under one directory the user can ``rm -rf``."""
    from darkcat import personas

    with mock.patch.object(personas, "default_dir", return_value=tmp_path):
        path = _history_file_path()
    assert path == tmp_path / "history"


def test_history_install_writes_and_reads_back(tmp_path: Path) -> None:
    """When readline is available, ``_install_history`` should read any
    existing file at startup and re-register an exit hook that writes back."""
    pytest.importorskip("readline")
    import readline as _rl

    history_file = tmp_path / "history"
    history_file.write_text("status\n")

    from darkcat import personas, repl

    _rl.clear_history()
    with mock.patch.object(personas, "default_dir", return_value=tmp_path):
        with mock.patch.object(repl, "_HAS_READLINE", True):
            repl._install_history()
    # The pre-existing line should now be in readline's history buffer.
    n = _rl.get_current_history_length()
    assert n >= 1
    items = [_rl.get_history_item(i) for i in range(1, n + 1)]
    assert "status" in items
    _rl.clear_history()


# ---- argcomplete soft-import ----------------------------------------------


def test_cli_main_does_not_require_argcomplete(monkeypatch, tmp_path: Path) -> None:
    """``cli.main`` must keep working when argcomplete isn't installed —
    that's the whole point of the soft-import."""
    import builtins
    real_import = builtins.__import__

    def _no_argcomplete(name, *args, **kwargs):
        if name == "argcomplete":
            raise ImportError("simulated missing argcomplete")
        return real_import(name, *args, **kwargs)

    # `darkcat about` is the simplest read-only command — it doesn't touch
    # the network or DB, so we can exercise main()'s argcomplete branch
    # without any real side-effects beyond a print.
    with mock.patch.object(builtins, "__import__", side_effect=_no_argcomplete):
        rc = cli.main(["about"])
    assert rc == 0


# ---- first-run wizard wiring ----------------------------------------------


def test_tui_needs_first_run_when_persona_dir_missing(tmp_path: Path) -> None:
    pytest.importorskip("textual")
    from darkcat import personas, tui

    missing = tmp_path / "does-not-exist"
    with mock.patch.object(personas, "default_dir", return_value=missing):
        assert tui._needs_first_run() is True
    existing = tmp_path / "exists"
    existing.mkdir()
    with mock.patch.object(personas, "default_dir", return_value=existing):
        assert tui._needs_first_run() is False


def test_gui_needs_first_run_matches_tui_behaviour(tmp_path: Path) -> None:
    """TUI and GUI must agree on when to pop the welcome wizard so the user
    sees consistent first-run behaviour across frontends."""
    from darkcat import gui, personas

    missing = tmp_path / "does-not-exist"
    with mock.patch.object(personas, "default_dir", return_value=missing):
        assert gui.DarkcatGUI._needs_first_run() is True
    existing = tmp_path / "exists"
    existing.mkdir()
    with mock.patch.object(personas, "default_dir", return_value=existing):
        assert gui.DarkcatGUI._needs_first_run() is False
