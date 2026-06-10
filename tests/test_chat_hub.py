# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Unit tests for the multi-protocol chat-hub aggregator + config.

Covers the pieces the CLI / TUI / GUI all share:

* ``hub_config.parse_interval`` accepts presets, ``s``/``m``/``h`` suffixes,
  bare seconds, and the ``off`` sentinel; rejects garbage.
* ``hub_config.get_interval`` / ``set_interval`` round-trip through a
  redirected ``HUB_CONFIG_PATH`` (no host-file pollution).
* ``chat.hub.aggregate`` walks a vault, picks chat-capable personas via
  the ``provider`` field, and tolerates per-backend failures by capturing
  them on the returned :class:`HubEntry` instead of raising.

The aggregator is exercised against a fake backend whose dep marker is
``HAS_FAKE = True``, registered transparently for the duration of one
test through ``_BACKENDS``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from darkcat import hub_config
from darkcat.chat import hub as chat_hub
from darkcat.chat.base import ChatChannel, Messenger
from darkcat.personas import Persona, Vault


# --- hub_config -----------------------------------------------------------

def test_parse_interval_presets():
    assert hub_config.parse_interval("10s") == 10
    assert hub_config.parse_interval("30s") == 30
    assert hub_config.parse_interval("1m")  == 60
    assert hub_config.parse_interval("10m") == 600
    assert hub_config.parse_interval("1h")  == 3600
    assert hub_config.parse_interval("off") == 0
    assert hub_config.parse_interval("0")   == 0


def test_parse_interval_units_and_bare_seconds():
    assert hub_config.parse_interval("45s") == 45
    assert hub_config.parse_interval("2m")  == 120
    assert hub_config.parse_interval("2h")  == 7200
    assert hub_config.parse_interval("90")  == 90
    assert hub_config.parse_interval(120)   == 120
    assert hub_config.parse_interval(-5)    == 0


def test_parse_interval_rejects_garbage():
    with pytest.raises(ValueError):
        hub_config.parse_interval("bogus")
    with pytest.raises(ValueError):
        hub_config.parse_interval("10x")


def test_get_set_interval_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(hub_config, "HUB_CONFIG_PATH",
                        tmp_path / "hub.json")
    assert hub_config.get_interval() == hub_config.DEFAULT_INTERVAL_SECONDS
    hub_config.set_interval(45)
    assert hub_config.get_interval() == 45
    raw = json.loads((tmp_path / "hub.json").read_text())
    assert raw["refresh_interval_seconds"] == 45


def test_get_interval_survives_corrupt_file(tmp_path, monkeypatch):
    p = tmp_path / "hub.json"
    p.write_text("not-valid-json{")
    monkeypatch.setattr(hub_config, "HUB_CONFIG_PATH", p)
    # Falls back to the default rather than raising.
    assert hub_config.get_interval() == hub_config.DEFAULT_INTERVAL_SECONDS


def test_interval_label_round_trip():
    assert hub_config.interval_label(30) == "30s"
    assert hub_config.interval_label(60) == "1m"
    assert hub_config.interval_label(3600) == "1h"
    assert hub_config.interval_label(0) == "off"


# --- aggregator -----------------------------------------------------------

class _FakeMessenger(Messenger):
    """In-process backend used to drive the aggregator without touching
    the network. Configured per-class for unit-test purposes."""

    network = "fake"
    channels: list[ChatChannel] = []
    raise_on_connect: Exception | None = None
    raise_on_list: Exception | None = None

    def connect(self) -> None:
        if self.raise_on_connect is not None:
            raise self.raise_on_connect
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def list_channels(self, *, limit: int = 100):
        if self.raise_on_list is not None:
            raise self.raise_on_list
        return list(self.channels)[:limit]

    def read(self, channel_id, *, limit=50):
        return []

    def send(self, channel_id, text):
        raise NotImplementedError


def _register_fake(monkeypatch, **cls_attrs):
    """Wire ``_FakeMessenger`` into the chat registry as ``fake`` for
    the duration of one test, with optional class-attr overrides."""
    import types

    from darkcat import chat as ch

    fake_mod = types.ModuleType("darkcat.chat._fake_for_hub_test")
    fake_mod.HAS_FAKE = True
    fake_mod.DEP_NAME = "(none — in-process fake)"
    fake_mod.INSTALL_HINT = ""
    for k, v in cls_attrs.items():
        setattr(_FakeMessenger, k, v)
    fake_mod.FakeMessenger = _FakeMessenger

    monkeypatch.setitem(ch._BACKENDS, "fake", (fake_mod.__name__, "HAS_FAKE"))

    # Patch importlib so _import_backend picks up our in-memory module.
    real_import = ch.importlib.import_module

    def fake_import(name):
        if name == fake_mod.__name__:
            return fake_mod
        return real_import(name)

    monkeypatch.setattr(ch.importlib, "import_module", fake_import)


def _vault_with(*personas, tmp_path):
    path = tmp_path / "personas.json"
    path.write_text(json.dumps({
        "version": 2,
        "personas": [p.__dict__ for p in personas],
    }))
    return Vault(path=path)


def test_aggregate_empty_vault(tmp_path):
    vault = _vault_with(tmp_path=tmp_path)
    entries = chat_hub.aggregate(vault)
    assert entries == []


def test_aggregate_skips_non_chat_personas(tmp_path):
    """A persona whose provider isn't a known chat backend (e.g.
    ``protonmail``) must be ignored — the hub is chat-only."""
    p = Persona(name="mail-1", provider="protonmail")
    vault = _vault_with(p, tmp_path=tmp_path)
    assert chat_hub.aggregate(vault) == []


def test_aggregate_picks_up_provider_field(tmp_path, monkeypatch):
    _register_fake(
        monkeypatch,
        channels=[ChatChannel(id="c1", name="general", participants=3)],
        raise_on_connect=None, raise_on_list=None,
    )
    p = Persona(name="alice", provider="fake", transport_used="tor:abc")
    vault = _vault_with(p, tmp_path=tmp_path)
    entries = chat_hub.aggregate(vault)
    assert len(entries) == 1
    e = entries[0]
    assert e.persona_name == "alice"
    assert e.network == "fake"
    assert e.transport == "tor:abc"
    assert e.status == chat_hub.STATUS_OK
    assert len(e.channels) == 1
    assert e.channels[0].name == "general"


def test_aggregate_captures_auth_error_without_raising(tmp_path, monkeypatch):
    from darkcat.chat.base import AuthError

    _register_fake(
        monkeypatch,
        channels=[], raise_on_connect=AuthError("session expired"),
        raise_on_list=None,
    )
    p = Persona(name="alice", provider="fake")
    vault = _vault_with(p, tmp_path=tmp_path)
    entries = chat_hub.aggregate(vault)
    assert len(entries) == 1
    e = entries[0]
    assert e.status == chat_hub.STATUS_AUTH
    assert "session expired" in e.error
    assert e.channels == []


def test_aggregate_marks_unavailable_when_dep_missing(tmp_path, monkeypatch):
    """When the backend's HAS_* marker is False, the entry must be
    flagged ``unavailable`` and connect() must never be attempted."""
    _register_fake(
        monkeypatch, channels=[],
        raise_on_connect=RuntimeError("would not run"),
        raise_on_list=None,
    )
    # Force the marker off.
    from darkcat import chat as ch
    mod = ch.importlib.import_module(ch._BACKENDS["fake"][0])
    mod.HAS_FAKE = False

    p = Persona(name="alice", provider="fake")
    vault = _vault_with(p, tmp_path=tmp_path)
    entries = chat_hub.aggregate(vault)
    assert entries[0].status == chat_hub.STATUS_UNAVAILABLE
    assert "dependency not installed" in entries[0].error


def test_aggregate_filters_by_networks(tmp_path, monkeypatch):
    _register_fake(
        monkeypatch,
        channels=[ChatChannel(id="x", name="x")],
        raise_on_connect=None, raise_on_list=None,
    )
    p1 = Persona(name="alice", provider="fake")
    p2 = Persona(name="bob",   provider="matrix")  # not installed → would be 'unavailable'
    vault = _vault_with(p1, p2, tmp_path=tmp_path)
    entries = chat_hub.aggregate(vault, networks=["fake"])
    assert [e.persona_name for e in entries] == ["alice"]


def test_summarize_totals():
    e1 = chat_hub.HubEntry(
        persona_name="a", network="fake",
        channels=[ChatChannel(id="1", name="x", unread=2)],
        status=chat_hub.STATUS_OK,
    )
    e2 = chat_hub.HubEntry(
        persona_name="b", network="fake",
        channels=[], status=chat_hub.STATUS_AUTH, error="bad",
    )
    s = chat_hub.summarize([e1, e2])
    assert s == {"personas": 2, "channels": 1, "unread": 2, "errors": 1}
