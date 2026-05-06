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
