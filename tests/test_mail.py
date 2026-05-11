# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Tests for darkcat.mail and the new identity providers.

The mail module is the surface most likely to break silently — coords
get pulled out of free-form persona fields (``site``, ``notes``,
``email``), and a typo in the notes parser would just produce wrong
defaults instead of an error. Cover the parser, the resolver, and the
two thin smtplib / imaplib transport functions with stubs (no live
network).
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import Message
from typing import Optional
from unittest.mock import MagicMock

import pytest

from darkcat import mail as mail_mod
from darkcat import personas as pv
from darkcat.identity import providers as provreg
from darkcat.mail import (
    DEFAULT_IMAP_PORT,
    DEFAULT_SMTP_PORT,
    MailCoords,
    MailError,
    MailHeader,
    _parse_notes,
    check_inbox,
    coords_from_persona,
    send_via_persona,
)


# ---------------------------------------------------------------------------
# _parse_notes
# ---------------------------------------------------------------------------

def test_parse_notes_empty_and_none():
    assert _parse_notes(None) == {}
    assert _parse_notes("") == {}
    assert _parse_notes("   ") == {}


def test_parse_notes_extracts_key_value_pairs():
    out = _parse_notes("smtp_port=2525 smtp_tls=starttls")
    assert out == {"smtp_port": "2525", "smtp_tls": "starttls"}


def test_parse_notes_lowercases_keys_keeps_value_case():
    out = _parse_notes("IMAP_HOST=Imap.Example.COM")
    assert out == {"imap_host": "Imap.Example.COM"}


def test_parse_notes_ignores_freeform_prose_between_pairs():
    notes = "operator: alice. smtp_port=465 (provider note) imap_tls=ssl"
    out = _parse_notes(notes)
    assert out == {"smtp_port": "465", "imap_tls": "ssl"}


# ---------------------------------------------------------------------------
# coords_from_persona
# ---------------------------------------------------------------------------

def _mail_persona(**overrides) -> pv.Persona:
    base = dict(
        name="m",
        handle="me@example.org",
        password="hunter2",
        email="me@example.org",
        site="smtp.example.org:587",
        notes=None,
    )
    base.update(overrides)
    return pv.Persona(**base)


def test_coords_resolves_site_host_and_port():
    c = coords_from_persona(_mail_persona())
    assert c.smtp_host == "smtp.example.org"
    assert c.smtp_port == 587
    assert c.smtp_tls == "starttls"
    assert c.username == "me@example.org"
    assert c.password == "hunter2"
    assert c.sender == "me@example.org"
    assert c.imap_host == "smtp.example.org"  # falls back to smtp_host
    assert c.imap_port == DEFAULT_IMAP_PORT
    assert c.imap_tls == "ssl"


def test_coords_defaults_port_when_site_has_no_colon():
    c = coords_from_persona(_mail_persona(site="smtp.example.org"))
    assert c.smtp_port == DEFAULT_SMTP_PORT


def test_coords_falls_back_to_handle_when_email_missing():
    p = _mail_persona(email=None)
    assert coords_from_persona(p).sender == "me@example.org"


def test_coords_notes_override_port_and_tls():
    p = _mail_persona(
        site="proton.example:587",
        notes="smtp_port=465 smtp_tls=ssl imap_host=imap.proton.example imap_port=993 imap_tls=ssl",
    )
    c = coords_from_persona(p)
    assert c.smtp_port == 465
    assert c.smtp_tls == "ssl"
    assert c.imap_host == "imap.proton.example"
    assert c.imap_port == 993
    assert c.imap_tls == "ssl"


def test_coords_falls_back_to_env_when_site_blank(monkeypatch):
    monkeypatch.setenv("DARKCAT_SMTP_HOST", "env.example.org")
    p = _mail_persona(site="")
    c = coords_from_persona(p)
    assert c.smtp_host == "env.example.org"


def test_coords_raises_when_no_host_anywhere(monkeypatch):
    monkeypatch.delenv("DARKCAT_SMTP_HOST", raising=False)
    p = _mail_persona(site="")
    with pytest.raises(MailError, match="SMTP host"):
        coords_from_persona(p)


def test_coords_raises_when_no_credentials(monkeypatch):
    monkeypatch.delenv("DARKCAT_SMTP_USER", raising=False)
    monkeypatch.delenv("DARKCAT_SMTP_PASS", raising=False)
    p = _mail_persona(handle=None, password=None)
    with pytest.raises(MailError, match="credentials"):
        coords_from_persona(p)


def test_coords_picks_up_env_credentials_when_persona_blank(monkeypatch):
    monkeypatch.setenv("DARKCAT_SMTP_USER", "env_user")
    monkeypatch.setenv("DARKCAT_SMTP_PASS", "env_pass")
    p = _mail_persona(handle=None, password=None, email=None)
    c = coords_from_persona(p)
    assert c.username == "env_user"
    assert c.password == "env_pass"
    assert c.sender == "env_user"


# ---------------------------------------------------------------------------
# send_via_persona — stub smtplib so no socket is opened
# ---------------------------------------------------------------------------

class _FakeSMTP:
    """Minimal stand-in for ``smtplib.SMTP`` / ``smtplib.SMTP_SSL``.

    Records the calls darkcat is supposed to make so the test can assert
    against them. ``__enter__`` / ``__exit__`` mirror the context-manager
    protocol the production code uses.
    """

    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, *args, **kwargs):
        self.host = host
        self.port = port
        self.timeout = kwargs.get("timeout")
        self.ehlo_called = 0
        self.starttls_called = False
        self.login_args: Optional[tuple] = None
        self.send_message_args: Optional[tuple] = None
        self.send_message_kwargs: Optional[dict] = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        self.ehlo_called += 1

    def starttls(self, context=None):
        self.starttls_called = True

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, msg, from_addr=None, to_addrs=None):
        self.send_message_args = (msg,)
        self.send_message_kwargs = {"from_addr": from_addr, "to_addrs": to_addrs}


@pytest.fixture(autouse=True)
def _reset_fake_smtp():
    _FakeSMTP.instances.clear()
    yield
    _FakeSMTP.instances.clear()


def test_send_via_persona_uses_starttls_by_default(monkeypatch):
    monkeypatch.setattr(mail_mod.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(mail_mod.smtplib, "SMTP_SSL", _FakeSMTP)

    msg_id = send_via_persona(
        _mail_persona(),
        to=["a@example.com"],
        subject="hi",
        body="hello",
    )
    assert msg_id.startswith("<") and msg_id.endswith(">")
    assert len(_FakeSMTP.instances) == 1
    s = _FakeSMTP.instances[0]
    assert (s.host, s.port) == ("smtp.example.org", 587)
    assert s.starttls_called is True
    assert s.login_args == ("me@example.org", "hunter2")
    # Subject + From + Message-Id must all land on the EmailMessage we passed.
    sent: Message = s.send_message_args[0]
    assert sent["Subject"] == "hi"
    assert sent["From"] == "me@example.org"
    assert sent["Message-Id"] == msg_id


def test_send_via_persona_ssl_branch(monkeypatch):
    monkeypatch.setattr(mail_mod.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(mail_mod.smtplib, "SMTP_SSL", _FakeSMTP)
    p = _mail_persona(site="smtp.example.org:465", notes="smtp_tls=ssl")
    send_via_persona(p, to=["a@example.com"], subject="s", body="b")
    s = _FakeSMTP.instances[0]
    # SSL branch must NOT call starttls (handshake already done by SMTP_SSL).
    assert s.starttls_called is False
    assert s.port == 465


def test_send_via_persona_bcc_recipients_not_in_headers(monkeypatch):
    monkeypatch.setattr(mail_mod.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(mail_mod.smtplib, "SMTP_SSL", _FakeSMTP)
    send_via_persona(
        _mail_persona(),
        to=["a@example.com"],
        cc=["c@example.com"],
        bcc=["shadow@example.com"],
        subject="s",
        body="b",
    )
    s = _FakeSMTP.instances[0]
    recipients = s.send_message_kwargs["to_addrs"]
    assert "shadow@example.com" in recipients
    sent: Message = s.send_message_args[0]
    # BCC must not leak into rendered headers.
    assert "shadow@example.com" not in str(sent)


def test_send_via_persona_wraps_smtp_errors(monkeypatch):
    class _Boom(_FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"nope")

    monkeypatch.setattr(mail_mod.smtplib, "SMTP", _Boom)
    monkeypatch.setattr(mail_mod.smtplib, "SMTP_SSL", _Boom)
    with pytest.raises(MailError, match="SMTP send failed"):
        send_via_persona(_mail_persona(), to=["a@example.com"],
                         subject="s", body="b")


# ---------------------------------------------------------------------------
# check_inbox — stub imaplib so no socket is opened
# ---------------------------------------------------------------------------

def _imap_fetch_payload(uid: str, size: int, *, from_: str, subject: str, date: str):
    meta = f"{uid} (UID {uid} RFC822.SIZE {size} BODY[HEADER.FIELDS (FROM SUBJECT DATE)]".encode()
    body = (
        f"From: {from_}\r\n"
        f"Subject: {subject}\r\n"
        f"Date: {date}\r\n"
    ).encode()
    # imaplib returns: [(meta_bytes, body_bytes), b")"]
    return ("OK", [(meta, body), b")"])


def test_check_inbox_parses_headers(monkeypatch):
    fake_imap = MagicMock()
    fake_imap.search.return_value = ("OK", [b"1 2"])
    fake_imap.fetch.side_effect = [
        _imap_fetch_payload("2", 1234, from_="b@x", subject="two", date="Tue"),
        _imap_fetch_payload("1", 42, from_="a@x", subject="one", date="Mon"),
    ]
    monkeypatch.setattr(mail_mod.imaplib, "IMAP4_SSL",
                        lambda *a, **k: fake_imap)

    headers = check_inbox(_mail_persona(), limit=10)
    # Reversed: newest first.
    assert [h.uid for h in headers] == ["2", "1"]
    assert headers[0].subject == "two"
    assert headers[0].size == 1234
    assert headers[1].from_ == "a@x"
    # readonly=True is critical — verify it was passed.
    fake_imap.select.assert_called_once_with("INBOX", readonly=True)


def test_check_inbox_decodes_rfc2047_subject_and_from(monkeypatch):
    """`=?utf-8?B?...?=` must be decoded — otherwise non-ASCII Subject /
    From values come back as raw quoted-printable noise."""
    fake_imap = MagicMock()
    fake_imap.search.return_value = ("OK", [b"1"])
    # Subject = "Café résumé" (base64 utf-8), From = "Bjørn <b@x>" (q-encoded)
    fake_imap.fetch.return_value = (
        "OK",
        [
            (
                b"1 (UID 1 RFC822.SIZE 99 BODY[HEADER.FIELDS (FROM SUBJECT DATE)]",
                (
                    b"From: =?iso-8859-1?Q?Bj=F8rn?= <b@x>\r\n"
                    b"Subject: =?utf-8?B?Q2Fmw6kgcsOpc3Vtw6k=?=\r\n"
                    b"Date: Mon, 1 Jan 2026 00:00:00 +0000\r\n"
                ),
            ),
            b")",
        ],
    )
    monkeypatch.setattr(mail_mod.imaplib, "IMAP4_SSL",
                        lambda *a, **k: fake_imap)
    headers = check_inbox(_mail_persona())
    assert len(headers) == 1
    assert headers[0].subject == "Café résumé"
    assert "Bjørn" in headers[0].from_


def test_check_inbox_empty_folder_returns_empty_list(monkeypatch):
    fake_imap = MagicMock()
    fake_imap.search.return_value = ("OK", [b""])
    monkeypatch.setattr(mail_mod.imaplib, "IMAP4_SSL",
                        lambda *a, **k: fake_imap)
    assert check_inbox(_mail_persona()) == []


def test_check_inbox_login_error_wraps_to_mail_error(monkeypatch):
    import imaplib as real_imaplib

    class _BoomIMAP:
        def __init__(self, *a, **k):
            raise real_imaplib.IMAP4.error("auth nope")
    monkeypatch.setattr(mail_mod.imaplib, "IMAP4_SSL", _BoomIMAP)
    with pytest.raises(MailError, match="IMAP login failed"):
        check_inbox(_mail_persona())


# ---------------------------------------------------------------------------
# new identity provider profiles (session, simplex)
# ---------------------------------------------------------------------------

def test_session_and_simplex_profiles_registered():
    provreg.load_all()
    slugs = {r.slug for r in provreg.registered()}
    assert {"session", "simplex"} <= slugs


def test_session_profile_fields_well_formed():
    provreg.load_all()
    p = provreg.get("session")
    assert p is not None
    assert p.signup_url.startswith("https://")
    assert p.no_phone_path
    assert p.fields


# ---------------------------------------------------------------------------
# mail provider presets (SMTP/IMAP defaults)
# ---------------------------------------------------------------------------

def test_mail_provider_presets_round_trip_through_coords_from_persona():
    """Every shipped preset must produce a valid MailCoords when applied
    to a persona — a typo in the notes string would surface here."""
    from darkcat import mail_providers as mp
    presets = mp.all_presets()
    assert presets, "no mail provider presets registered"
    for preset in presets:
        p = pv.Persona(
            name=f"t-{preset.slug}",
            network=preset.network,
            site=preset.site,
            handle="user@example.com",
            password="x",
            notes=preset.notes,
        )
        coords = coords_from_persona(p)
        # SMTP TLS must be one of the three recognized modes.
        assert coords.smtp_tls in {"starttls", "ssl", "none"}, (
            preset.slug, coords.smtp_tls,
        )
        assert coords.imap_tls in {"starttls", "ssl", "none"}, (
            preset.slug, coords.imap_tls,
        )
        # And the imap_host / imap_port survived the notes round-trip.
        assert coords.imap_host, preset.slug
        assert coords.imap_port > 0, preset.slug


def test_mail_provider_get_returns_none_for_unknown_slug():
    from darkcat import mail_providers as mp
    assert mp.get("nonsense") is None
    assert mp.get("proton-bridge") is not None


def test_mail_provider_slugs_are_unique_and_sorted():
    from darkcat import mail_providers as mp
    ss = mp.slugs()
    assert len(ss) == len(set(ss))
    assert list(ss) == sorted(ss)


def test_personas_add_with_mail_provider_applies_preset(tmp_path, monkeypatch):
    """`personas add --mail-provider proton-bridge` must fill site/notes."""
    from darkcat import cli as _cli
    from darkcat import mail_providers as mp
    monkeypatch.setattr(pv, "vault_path", lambda: tmp_path / "personas.json")
    monkeypatch.setattr(pv, "default_dir", lambda: tmp_path)

    import argparse
    ns = argparse.Namespace(
        action="add",
        name="proton-test",
        network="",
        site="",
        handle="me@proton.me",
        password="bridge-token",
        email=None,
        pgp_key_id=None,
        recovery=None,
        notes=None,
        user_agent=None,
        proxy=None,
        tags=[],
        gen=False,
        replace=False,
        mail_provider="proton-bridge",
    )
    rc = _cli.cmd_personas(_cli.Config(db_path=tmp_path / "c.db"), ns)
    assert rc == 0
    v = pv.Vault(path=tmp_path / "personas.json")
    p = v.get("proton-test")
    assert p is not None
    expected = mp.get("proton-bridge")
    assert p.site == expected.site
    assert p.notes == expected.notes
    assert p.network == expected.network


def test_personas_add_explicit_site_beats_mail_provider(tmp_path, monkeypatch):
    """If the user passed --site explicitly, the preset must not override."""
    from darkcat import cli as _cli
    monkeypatch.setattr(pv, "vault_path", lambda: tmp_path / "personas.json")
    monkeypatch.setattr(pv, "default_dir", lambda: tmp_path)

    import argparse
    ns = argparse.Namespace(
        action="add",
        name="hybrid",
        network="",
        site="my.custom.host:2525",  # explicit wins
        handle="me@proton.me",
        password="x",
        email=None,
        pgp_key_id=None,
        recovery=None,
        notes=None,
        user_agent=None,
        proxy=None,
        tags=[],
        gen=False,
        replace=False,
        mail_provider="proton-bridge",
    )
    rc = _cli.cmd_personas(_cli.Config(db_path=tmp_path / "c.db"), ns)
    assert rc == 0
    v = pv.Vault(path=tmp_path / "personas.json")
    p = v.get("hybrid")
    assert p.site == "my.custom.host:2525"  # not 127.0.0.1:1025
    # But notes from the preset still applied (since --notes was blank).
    assert p.notes and "imap_host=127.0.0.1" in p.notes


def test_personas_add_rejects_unknown_mail_provider(tmp_path, monkeypatch, capsys):
    from darkcat import cli as _cli
    monkeypatch.setattr(pv, "vault_path", lambda: tmp_path / "personas.json")
    monkeypatch.setattr(pv, "default_dir", lambda: tmp_path)

    import argparse
    ns = argparse.Namespace(
        action="add",
        name="bogus",
        network="",
        site="",
        handle="x",
        password="y",
        email=None,
        pgp_key_id=None,
        recovery=None,
        notes=None,
        user_agent=None,
        proxy=None,
        tags=[],
        gen=False,
        replace=False,
        mail_provider="not-a-real-slug",
    )
    rc = _cli.cmd_personas(_cli.Config(db_path=tmp_path / "c.db"), ns)
    assert rc == 2
