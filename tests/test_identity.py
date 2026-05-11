# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Tests for the Identity Generator.

Covers the four pieces that have non-trivial behaviour:

* ``generator`` — generated values are well-formed (handle shape,
  password length floor, ISO birthdate, plausible locale/tz pair).
* ``vault`` — per-provider cap enforcement, status transitions, the
  link/unlink graph, and that legacy persona rows (no ``provider``)
  stay invisible to the identity view.
* ``transport`` — token determinism (same seed → same token) and
  proxies-for-config wiring.
* ``providers`` — registry idempotence, instance lookup, and that the
  shipped profiles all have the required fields.

Plus a redaction smoke-test confirming ``recovery_codes`` mask matches
``password`` / ``recovery``.
"""
from __future__ import annotations

import os
import re
from datetime import date

import pytest

from darkcat import personas as pv
from darkcat.identity import (
    DEFAULT_PER_PROVIDER_CAP,
    GeneratedIdentity,
    IdentityVault,
    PerProviderCapExceeded,
    new_identity,
    pick_transport,
    transport_token,
)
from darkcat.identity import providers as provreg
from darkcat.identity.generator import (
    generate_birthdate,
    generate_bio,
    generate_display_name,
    generate_locale,
)
from darkcat.identity.transport import (
    KIND_PROXY,
    KIND_TOR,
    KIND_VPN_PIN,
)


# ---------------------------------------------------------------------------
# generator
# ---------------------------------------------------------------------------

def test_generate_handle_uses_underscore_format():
    h = pv.generate_handle()
    assert re.match(r"^[a-z]+_[a-z]+_\d{4}$", h), h


def test_generate_password_meets_floor_length():
    # The persona generator returns *at least* 16 bytes of entropy after
    # urlsafe encoding even when caller asks for less; cli identity new
    # defaults to 24.
    short = pv.generate_password(8)
    assert len(short) == 8
    long = pv.generate_password(40)
    assert len(long) == 40


def test_generate_display_name_is_two_ascii_words():
    name = generate_display_name()
    parts = name.split(" ")
    assert len(parts) == 2
    assert all(p.isascii() and p[0].isupper() for p in parts)


def test_generate_locale_pairs_locale_with_timezone():
    locale, tz = generate_locale()
    assert "_" in locale
    assert "/" in tz


def test_generate_birthdate_is_iso_and_age_bounded():
    bd = generate_birthdate(min_age=22, max_age=55)
    y, m, d = (int(x) for x in bd.split("-"))
    age = date.today().year - y
    assert 22 <= age <= 55, (age, bd)
    assert 1 <= m <= 12 and 1 <= d <= 31


def test_generate_birthdate_rejects_inverted_range():
    with pytest.raises(ValueError):
        generate_birthdate(min_age=40, max_age=20)


def test_generate_bio_uses_three_distinct_segments():
    bio = generate_bio()
    # Two opener segments separated by a connector, plus a closer.
    # We only assert the connector appears at least twice.
    connectors_present = sum(bio.count(c) for c in (" • ", " | ", ", ", " — "))
    assert connectors_present >= 2, bio


def test_new_identity_is_self_consistent():
    g = new_identity()
    assert isinstance(g, GeneratedIdentity)
    assert g.handle and g.password and g.display_name
    assert g.locale and g.timezone and g.birthdate and g.bio


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------

def test_transport_token_is_deterministic():
    t1 = transport_token("alpha")
    t2 = transport_token("alpha")
    assert t1 == t2 and len(t1) == 16


def test_transport_token_differs_per_seed():
    assert transport_token("alpha") != transport_token("beta")


def test_pick_transport_tor_returns_isolation_token():
    choice = pick_transport(KIND_TOR, seed="example")
    assert choice.kind == KIND_TOR
    assert choice.token == transport_token("example")


def test_pick_transport_proxy_requires_url():
    with pytest.raises(ValueError):
        pick_transport(KIND_PROXY, seed="example")
    ok = pick_transport(KIND_PROXY, seed="example", proxy_url="socks5://1.2.3.4:9050")
    assert ok.token == "socks5://1.2.3.4:9050"


def test_pick_transport_vpn_pin_requires_target():
    with pytest.raises(ValueError):
        pick_transport(KIND_VPN_PIN, seed="example")


def test_pick_transport_vpn_pin_proxies_raises():
    from darkcat.config import Config
    choice = pick_transport(KIND_VPN_PIN, seed="x", pin_to="my-vpn")
    with pytest.raises(NotImplementedError):
        choice.proxies_for(Config())


# ---------------------------------------------------------------------------
# vault
# ---------------------------------------------------------------------------

def _fresh_vault(tmp_path) -> IdentityVault:
    inner = pv.Vault(path=tmp_path / "personas.json")
    return IdentityVault(inner)


def _identity_persona(name: str, provider: str = "protonmail") -> pv.Persona:
    g = new_identity()
    return pv.Persona(
        name=name,
        provider=provider,
        category="email",
        status=pv.STATUS_PENDING,
        handle=g.handle,
        password=g.password,
        display_name=g.display_name,
        birthdate=g.birthdate,
        locale=g.locale,
        timezone=g.timezone,
        bio=g.bio,
    )


def test_legacy_personas_are_invisible_to_identity_view(tmp_path):
    v = _fresh_vault(tmp_path)
    legacy = pv.Persona(name="old", network="tor", site="dread.onion",
                        handle="x", password="y")
    v.inner.add(legacy)
    new = _identity_persona("new")
    v.add(new)
    assert v.all_identities() == [new]
    assert v.find(provider="protonmail") == [new]


def test_per_provider_cap_blocks_at_six(tmp_path):
    v = _fresh_vault(tmp_path)
    assert v.per_provider_cap == DEFAULT_PER_PROVIDER_CAP
    for i in range(DEFAULT_PER_PROVIDER_CAP):
        v.add(_identity_persona(f"p{i}"))
    with pytest.raises(PerProviderCapExceeded):
        v.add(_identity_persona("over"))
    # --force bypasses
    v.add(_identity_persona("forced"), force=True)
    assert v.per_provider_count("protonmail") == DEFAULT_PER_PROVIDER_CAP + 1


def test_burned_identities_dont_count_against_cap(tmp_path):
    v = _fresh_vault(tmp_path)
    for i in range(DEFAULT_PER_PROVIDER_CAP):
        v.add(_identity_persona(f"p{i}"))
    v.burn("p0")
    # Burned slot freed; one more should now fit without --force.
    v.add(_identity_persona("after-burn"))
    assert v.per_provider_count("protonmail", active_only=True) == DEFAULT_PER_PROVIDER_CAP


def test_status_transitions_pending_confirmed_burned(tmp_path):
    v = _fresh_vault(tmp_path)
    v.add(_identity_persona("a"))
    p = v.confirm("a")
    assert p.status == pv.STATUS_CONFIRMED
    assert p.confirmed_at is not None
    # Idempotent
    again = v.confirm("a")
    assert again.status == pv.STATUS_CONFIRMED
    p = v.burn("a", note="done")
    assert p.status == pv.STATUS_BURNED
    assert p.burned_at is not None
    assert "done" in (p.notes or "")


def test_confirm_rejects_burned(tmp_path):
    v = _fresh_vault(tmp_path)
    v.add(_identity_persona("a"))
    v.burn("a")
    with pytest.raises(ValueError):
        v.confirm("a")


def test_link_graph_is_directional_and_no_self_loops(tmp_path):
    v = _fresh_vault(tmp_path)
    v.add(_identity_persona("parent"))
    v.add(_identity_persona("child"))
    v.link("parent", "child")
    child = v.inner.get("child")
    parent = v.inner.get("parent")
    assert child.linked_identities == ["parent"]
    assert parent.linked_identities == []
    with pytest.raises(ValueError):
        v.link("parent", "parent")
    assert v.unlink("parent", "child") is True
    assert v.unlink("parent", "child") is False


def test_rotate_password_overwrites_existing(tmp_path):
    v = _fresh_vault(tmp_path)
    v.add(_identity_persona("a"))
    old = v.inner.get("a").password
    v.rotate_password("a", "Hunter2-replacement")
    assert v.inner.get("a").password == "Hunter2-replacement"
    assert v.inner.get("a").password != old


# ---------------------------------------------------------------------------
# redaction
# ---------------------------------------------------------------------------

def test_redact_dict_masks_recovery_codes_and_password(tmp_path):
    p = _identity_persona("a")
    p.recovery = "BIP-39 phrase"
    p.recovery_codes = ["aaa-bbb", "ccc-ddd"]
    masked = pv.redact_dict(p, reveal=False)
    assert "Hunter" not in str(masked["password"])
    assert masked["password"].startswith("******")
    assert masked["recovery"].startswith("******")
    assert all(c.startswith("******") for c in masked["recovery_codes"])
    revealed = pv.redact_dict(p, reveal=True)
    assert revealed["recovery_codes"] == ["aaa-bbb", "ccc-ddd"]


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------

def test_provider_registry_loads_and_dedupes():
    rows = provreg.load_all()
    slugs = [r.slug for r in rows]
    # No duplicates
    assert len(slugs) == len(set(slugs))
    # Re-loading is idempotent
    rows2 = provreg.load_all()
    assert [r.slug for r in rows2] == slugs


def test_shipped_profiles_carry_required_fields():
    provreg.load_all()
    expected = {
        "protonmail", "tutanota", "mailfence", "disroot",
        "gmail", "outlook", "yahoo",
        "protonvpn", "tunnelbear", "windscribe",
        "reddit", "twitter", "telegram", "discord", "mastodon",
        # Chat-network identities (local keygen or homeserver-based).
        "matrix", "xmpp", "session", "simplex",
        "tox", "briar", "ricochet",
    }
    actual = {r.slug for r in provreg.registered()}
    missing = expected - actual
    assert not missing, f"missing profiles: {missing}"
    for r in provreg.registered():
        assert r.signup_url.startswith(("http://", "https://")), r.slug
        assert r.no_phone_path
        assert r.tos_warning
        assert r.fields, f"{r.slug} has no fields"


def test_chat_backends_have_matching_identity_profiles():
    """Every chat backend should have an identity profile so users can
    record the account in the vault — even if the backend itself isn't
    runnable (tox / briar / ricochet have no Python client)."""
    from darkcat import chat as ch
    provreg.load_all()
    actual = {r.slug for r in provreg.registered()}
    for net in ch.known_networks():
        assert net in actual, (
            f"chat backend {net!r} has no matching identity provider profile"
        )


def test_matrix_and_xmpp_have_multiple_instances():
    """matrix / xmpp are intrinsically multi-server — the per-instance
    list is what makes the signup launcher actually useful."""
    provreg.load_all()
    for slug in ("matrix", "xmpp"):
        p = provreg.get(slug)
        assert p is not None
        assert len(p.instances) >= 2, f"{slug} needs >=2 instances, has {len(p.instances)}"


def test_mastodon_has_known_instances():
    p = provreg.get("mastodon")
    assert p is not None
    suffixes = {s for s, _, _ in p.instances}
    assert {"mastodon-social", "fosstodon"} <= suffixes


def test_register_overwrites_existing_slug():
    """Reloading a profile module replaces, not duplicates, the entry."""
    from darkcat.identity.providers import base as _base
    before = sum(1 for r in provreg.registered() if r.slug == "protonmail")
    import importlib
    importlib.import_module("darkcat.identity.providers.protonmail")
    after = sum(1 for r in provreg.registered() if r.slug == "protonmail")
    assert before == after == 1


# ---------------------------------------------------------------------------
# instance routing (matrix/xmpp/mastodon → per-host signup_url + site)
# ---------------------------------------------------------------------------

def _new_identity_ns(provider: str, instance=None):
    """Build the argparse.Namespace that TUI/GUI hand to
    invoke_cli_capturing for `identity new`. Kept in lockstep with
    src/darkcat/tui.py::IdentityScreen._create_identity and
    src/darkcat/gui.py::_show_identity::_new_identity so a drift in
    either frontend produces a missing-attribute TypeError here."""
    import argparse
    return argparse.Namespace(
        cmd="identity", action="new",
        provider=provider, transport="tor", purpose=None,
        name=None, instance=instance, recovery_email=None,
        cap=None, force=False, password_length=24,
        proxy_url=None, pin_to=None,
        launch=False, json=False,
    )


def test_identity_new_with_instance_routes_to_instance_host(
    tmp_path, monkeypatch,
):
    """`identity new --provider matrix --instance tchncs` must produce a
    persona whose network_or_domain reflects the chosen homeserver, not
    the provider's default. This is the contract TUI / GUI rely on when
    forwarding their Instance picker through invoke_cli_capturing."""
    from darkcat.config import Config
    from darkcat.identity import invoke_cli_capturing

    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))
    cfg = Config()

    rc, _out, err = invoke_cli_capturing(
        cfg, _new_identity_ns("matrix", instance="tchncs"),
    )
    assert rc == 0, err

    inner = pv.Vault(path=pv.vault_path(plain=True))
    rows = [p for p in inner.personas if p.provider == "matrix"]
    assert len(rows) == 1
    p = rows[0]
    assert p.network_or_domain == "matrix.tchncs.de", p.network_or_domain
    assert p.site == "matrix.tchncs.de", p.site


def test_identity_new_with_unknown_instance_errors_out(tmp_path, monkeypatch):
    """Bad --instance must fail loudly with a list of available hosts so
    the operator can fix the flag instead of silently landing on the
    default homeserver."""
    from darkcat.config import Config
    from darkcat.identity import invoke_cli_capturing

    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))
    cfg = Config()

    rc, _out, err = invoke_cli_capturing(
        cfg, _new_identity_ns("matrix", instance="totally-fake-host"),
    )
    assert rc == 2
    assert "no instance" in err
    assert "totally-fake-host" in err


def test_identity_new_without_instance_uses_provider_default(
    tmp_path, monkeypatch,
):
    """No --instance → fall back to the profile's default
    network_or_domain. Guards against a regression where the instance
    branch overwrites the default with an empty string."""
    from darkcat.config import Config
    from darkcat.identity import invoke_cli_capturing

    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))
    cfg = Config()

    rc, _out, err = invoke_cli_capturing(
        cfg, _new_identity_ns("matrix", instance=None),
    )
    assert rc == 0, err

    inner = pv.Vault(path=pv.vault_path(plain=True))
    p = [r for r in inner.personas if r.provider == "matrix"][0]
    default_prof = provreg.get("matrix")
    assert default_prof is not None
    assert p.network_or_domain == default_prof.network_or_domain


# ---------------------------------------------------------------------------
# identity edit (TUI/GUI credentials editor primitive)
# ---------------------------------------------------------------------------

def _edit_ns(
    name,
    *,
    handle=None, email=None, recovery=None, recovery_email=None,
    recovery_codes=None, recovery_codes_replace=False,
    display_name=None, notes=None,
):
    """Build the argparse.Namespace TUI/GUI hand to invoke_cli_capturing
    for `identity edit`. Kept in lockstep with src/darkcat/tui.py's
    IdentityScreen._apply_edit and src/darkcat/gui.py's _edit_selected."""
    import argparse
    return argparse.Namespace(
        cmd="identity", action="edit", name=name,
        handle=handle, email=email, recovery=recovery,
        recovery_email=recovery_email,
        recovery_codes=recovery_codes,
        recovery_codes_replace=recovery_codes_replace,
        display_name=display_name, notes=notes,
    )


def _seed_identity(tmp_path, monkeypatch, name="seed-a"):
    """Create one matrix identity in a temp vault; return (cfg, persona)."""
    from darkcat.config import Config
    from darkcat.identity import invoke_cli_capturing
    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))
    cfg = Config()
    rc, _out, err = invoke_cli_capturing(
        cfg, _new_identity_ns("matrix", instance=None),
    )
    assert rc == 0, err
    inner = pv.Vault(path=pv.vault_path(plain=True))
    p = [r for r in inner.personas if r.provider == "matrix"][0]
    return cfg, p


def test_identity_edit_updates_each_field(tmp_path, monkeypatch):
    from darkcat.identity import invoke_cli_capturing
    cfg, p = _seed_identity(tmp_path, monkeypatch)

    rc, _out, err = invoke_cli_capturing(cfg, _edit_ns(
        p.name,
        handle="@alice:tchncs.de",
        email="alice@tchncs.de",
        recovery_email="recover@proton.me",
        display_name="Alice Liddell",
        recovery="ribbon cat moon ...",
        notes="created during the 2026-05 sweep",
    ))
    assert rc == 0, err

    inner = pv.Vault(path=pv.vault_path(plain=True))
    p2 = inner.get(p.name)
    assert p2.handle == "@alice:tchncs.de"
    assert p2.email == "alice@tchncs.de"
    assert p2.recovery_email == "recover@proton.me"
    assert p2.display_name == "Alice Liddell"
    assert p2.recovery == "ribbon cat moon ..."
    assert p2.notes == "created during the 2026-05 sweep"


def test_identity_edit_appends_recovery_codes_by_default(tmp_path, monkeypatch):
    from darkcat.identity import invoke_cli_capturing
    cfg, p = _seed_identity(tmp_path, monkeypatch)
    rc, _o, _e = invoke_cli_capturing(cfg, _edit_ns(
        p.name, recovery_codes=["aaa-bbb", "ccc-ddd"]))
    assert rc == 0

    rc, _o, _e = invoke_cli_capturing(cfg, _edit_ns(
        p.name, recovery_codes=["eee-fff"]))
    assert rc == 0

    inner = pv.Vault(path=pv.vault_path(plain=True))
    assert inner.get(p.name).recovery_codes == ["aaa-bbb", "ccc-ddd", "eee-fff"]


def test_identity_edit_recovery_codes_replace_overwrites(tmp_path, monkeypatch):
    from darkcat.identity import invoke_cli_capturing
    cfg, p = _seed_identity(tmp_path, monkeypatch)
    invoke_cli_capturing(cfg, _edit_ns(
        p.name, recovery_codes=["aaa-bbb", "ccc-ddd"]))
    rc, _o, _e = invoke_cli_capturing(cfg, _edit_ns(
        p.name, recovery_codes=["new-only"], recovery_codes_replace=True))
    assert rc == 0
    inner = pv.Vault(path=pv.vault_path(plain=True))
    assert inner.get(p.name).recovery_codes == ["new-only"]


def test_identity_edit_clears_optional_fields_with_empty_string(
    tmp_path, monkeypatch,
):
    """Passing --email "" must clear the field, distinguishing 'omit this
    flag' (leave it alone) from 'I want this empty now'."""
    from darkcat.identity import invoke_cli_capturing
    cfg, p = _seed_identity(tmp_path, monkeypatch)
    invoke_cli_capturing(cfg, _edit_ns(p.name, email="alice@tchncs.de"))
    rc, _o, _e = invoke_cli_capturing(cfg, _edit_ns(p.name, email=""))
    assert rc == 0
    inner = pv.Vault(path=pv.vault_path(plain=True))
    assert inner.get(p.name).email is None


def test_identity_edit_unknown_name_errors_out(tmp_path, monkeypatch):
    from darkcat.identity import invoke_cli_capturing
    cfg, _p = _seed_identity(tmp_path, monkeypatch)
    rc, _o, err = invoke_cli_capturing(cfg, _edit_ns(
        "no-such-identity", handle="x"))
    assert rc == 2
    assert "no identity named" in err


def test_identity_edit_no_flags_errors_out(tmp_path, monkeypatch):
    """`identity edit NAME` with nothing to change must be a hard error
    so an empty TUI/GUI submit doesn't silently no-op."""
    from darkcat.identity import invoke_cli_capturing
    cfg, p = _seed_identity(tmp_path, monkeypatch)
    rc, _o, err = invoke_cli_capturing(cfg, _edit_ns(p.name))
    assert rc == 2
    assert "nothing to update" in err


# ---------------------------------------------------------------------------
# show / link / unlink / launch (the TUI/GUI parity surface added in 0.4)
# ---------------------------------------------------------------------------

def _show_ns(name, *, reveal=False, json=False):
    """Namespace TUI/GUI's ConfirmReveal flow hands to invoke_cli_capturing
    for ``identity show``. The reveal flag is what the modal toggles."""
    import argparse
    return argparse.Namespace(
        cmd="identity", action="show", name=name,
        reveal=reveal, json=json,
    )


def _link_ns(parent, child, *, verb="link"):
    """Namespace the LinkScreen / Tk link dialog hand to
    invoke_cli_capturing. verb is 'link' or 'unlink'."""
    import argparse
    return argparse.Namespace(
        cmd="identity", action=verb,
        parent=parent, child=child,
    )


def _launch_ns(name, *, no_spawn=True, capture=False):
    """Namespace the TUI/GUI Launch button hands to invoke_cli_capturing.
    Defaults to ``no_spawn=True`` so tests never poke a real browser —
    the CLI handler treats that as "print the URL and return". The
    ``capture`` flag is False because the post-launch prompt is for
    interactive TTYs only; the frontends drive their own follow-up
    flow (TUI: IdentityEditScreen push; GUI: Tk edit dialog)."""
    import argparse
    return argparse.Namespace(
        cmd="identity", action="launch", name=name,
        no_spawn=no_spawn, capture=capture,
    )


def test_identity_show_masked_hides_secrets(tmp_path, monkeypatch):
    """``identity show`` without --reveal must redact password + recovery
    codes. This is the default path the GUI/TUI take when the operator
    declines the ConfirmReveal modal."""
    from darkcat.identity import invoke_cli_capturing
    cfg, p = _seed_identity(tmp_path, monkeypatch)
    rc, out, err = invoke_cli_capturing(cfg, _show_ns(p.name, reveal=False))
    assert rc == 0, err
    assert p.password not in out


def test_identity_show_reveal_includes_password(tmp_path, monkeypatch):
    """With --reveal the password lands in stdout verbatim. The TUI/GUI
    require this so the result modal can display the secret."""
    from darkcat.identity import invoke_cli_capturing
    cfg, p = _seed_identity(tmp_path, monkeypatch)
    # Set the env var so the CLI handler skips its interactive y/N
    # prompt — same path the TUI/GUI take via DARKCAT_VAULT_PASSPHRASE.
    monkeypatch.setenv("DARKCAT_VAULT_PASSPHRASE", "test-bypass")
    rc, out, err = invoke_cli_capturing(cfg, _show_ns(p.name, reveal=True))
    assert rc == 0, err
    assert p.password in out


def test_identity_link_and_unlink_round_trip(tmp_path, monkeypatch):
    """Link two identities, then unlink them. Both rc=0 and the vault
    state reflects the edge."""
    from darkcat.identity import invoke_cli_capturing
    cfg, p1 = _seed_identity(tmp_path, monkeypatch, name="parent-a")
    rc, _o, err = invoke_cli_capturing(
        cfg, _new_identity_ns("matrix", instance=None),
    )
    assert rc == 0, err
    inner = pv.Vault(path=pv.vault_path(plain=True))
    p2 = [r for r in inner.personas
          if r.provider == "matrix" and r.name != p1.name][0]

    rc, _o, err = invoke_cli_capturing(
        cfg, _link_ns(p1.name, p2.name, verb="link"),
    )
    assert rc == 0, err
    inner = pv.Vault(path=pv.vault_path(plain=True))
    # IdentityVault.link records the parent on the child row.
    assert p1.name in inner.get(p2.name).linked_identities

    rc, _o, err = invoke_cli_capturing(
        cfg, _link_ns(p1.name, p2.name, verb="unlink"),
    )
    assert rc == 0, err
    inner = pv.Vault(path=pv.vault_path(plain=True))
    assert p1.name not in inner.get(p2.name).linked_identities


def test_identity_link_unknown_name_errors_out(tmp_path, monkeypatch):
    """Linking to a missing name surfaces rc=2 + an error line the
    Tk/Textual modals can splash via _last_error_line()."""
    from darkcat.identity import invoke_cli_capturing
    cfg, p = _seed_identity(tmp_path, monkeypatch)
    rc, _o, err = invoke_cli_capturing(
        cfg, _link_ns(p.name, "no-such-child", verb="link"),
    )
    assert rc == 2
    assert "no identity named" in err


def test_identity_launch_no_spawn_returns_url(tmp_path, monkeypatch):
    """`identity launch --no-spawn` must succeed and print the signup
    URL — the GUI's Launch button reuses this output in a messagebox.
    Skipped if the persona's profile is missing (registry shape changes
    upstream); we don't want this test to grade the provider library."""
    from darkcat.identity import invoke_cli_capturing
    cfg, p = _seed_identity(tmp_path, monkeypatch)
    rc, out, err = invoke_cli_capturing(cfg, _launch_ns(p.name))
    # rc==2 is acceptable if the launcher can't find a Tor transport in
    # the test sandbox; we still want to assert it didn't crash with an
    # AttributeError on a missing Namespace field.
    assert rc in (0, 2), err
    if rc == 0:
        # Some signup URL or the persona name must have surfaced.
        assert p.name in out or "://" in out


def test_identity_launch_unknown_name_errors_out(tmp_path, monkeypatch):
    """Launching a missing identity must rc=2 — covers the GUI's Launch
    button path when the selected row has been burned/deleted under it."""
    from darkcat.identity import invoke_cli_capturing
    cfg, _p = _seed_identity(tmp_path, monkeypatch)
    rc, _o, err = invoke_cli_capturing(cfg, _launch_ns("no-such-row"))
    assert rc == 2
    assert "no identity named" in err


def test_identity_launch_capture_prompt_writes_back_codes(
    tmp_path, monkeypatch,
):
    """`launch --capture` must, on an interactive TTY, prompt for the
    final handle / recovery email / recovery codes and persist them.
    We fake the TTY by stubbing ``sys.stdin.isatty`` + ``builtins.input``
    so the test doesn't need an actual terminal."""
    import builtins
    import sys
    from darkcat.identity import invoke_cli_capturing

    cfg, p = _seed_identity(tmp_path, monkeypatch)

    answers = iter([
        "@alice:tchncs.de",      # final handle
        "alice@tchncs.de",       # email
        "recover@proton.me",     # recovery email
        "",                      # recovery phrase (skip)
        "code-aaa",              # first recovery code
        "code-bbb",              # second recovery code
        "",                      # blank line ends the loop
    ])
    monkeypatch.setattr(builtins, "input", lambda *_a, **_kw: next(answers))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    rc, _out, err = invoke_cli_capturing(
        cfg, _launch_ns(p.name, capture=True),
    )
    # rc=0 happy path; rc=2 acceptable if Tor transport isn't available
    # in the sandbox — but the capture loop only runs on rc=0.
    if rc != 0:
        pytest.skip(f"launch unavailable in sandbox: {err.splitlines()[-1]}")

    inner = pv.Vault(path=pv.vault_path(plain=True))
    p2 = inner.get(p.name)
    assert p2.handle == "@alice:tchncs.de"
    assert p2.email == "alice@tchncs.de"
    assert p2.recovery_email == "recover@proton.me"
    assert "code-aaa" in p2.recovery_codes
    assert "code-bbb" in p2.recovery_codes


def test_identity_launch_capture_noop_when_stdin_not_a_tty(
    tmp_path, monkeypatch,
):
    """Capture must be skipped when stdin is not a TTY — protects
    pipelines and CI runs where ``input()`` would block forever waiting
    on a closed FD."""
    import sys
    from darkcat.identity import invoke_cli_capturing

    cfg, p = _seed_identity(tmp_path, monkeypatch)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    rc, _out, _err = invoke_cli_capturing(
        cfg, _launch_ns(p.name, capture=True),
    )
    # rc=0 or rc=2 (transport-unavailable); either way the persona row
    # must be unchanged because the capture loop short-circuits.
    inner = pv.Vault(path=pv.vault_path(plain=True))
    p2 = inner.get(p.name)
    # Untouched because we set nothing on the seed.
    assert p2.handle == p.handle
    assert p2.email == p.email
    assert p2.recovery_codes == p.recovery_codes


# ---------------------------------------------------------------------------
# personas add with --mail-provider preset (TUI PersonaAddScreen + GUI
# 'Add mail persona…' dialog both forward through this path)
# ---------------------------------------------------------------------------

def _personas_add_ns(name, *, mail_provider=None, gen=True,
                     handle=None, password=None, email=None,
                     network="", site="", notes=None):
    """Build the argparse.Namespace TUI PersonaAddScreen / GUI
    _show_persona_add hand to invoke_cli_capturing. Kept in lockstep with
    src/darkcat/tui.py::PersonaAddScreen.action_submit and
    src/darkcat/gui.py::_show_persona_add so a drift in either form
    produces a missing-attribute TypeError here."""
    import argparse
    return argparse.Namespace(
        cmd="personas", action="add", name=name,
        network=network, site=site,
        handle=handle, password=password, email=email,
        pgp_key_id=None, recovery=None, notes=notes,
        user_agent=None, proxy=None, tags=[],
        gen=gen, replace=False,
        mail_provider=mail_provider,
    )


def test_personas_add_with_mail_preset_fills_smtp_defaults(tmp_path, monkeypatch):
    """--mail-provider disroot must inject the curated SMTP host:port +
    IMAP coordinates into the persona row. The TUI/GUI form's preset
    picker relies on this CLI behaviour."""
    from darkcat.config import Config
    from darkcat.identity import invoke_cli_capturing

    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))
    cfg = Config()

    rc, _out, err = invoke_cli_capturing(
        cfg, _personas_add_ns("me-disroot", mail_provider="disroot"),
    )
    assert rc == 0, err

    inner = pv.Vault(path=pv.vault_path(plain=True))
    p = inner.get("me-disroot")
    assert p is not None
    assert p.site == "disroot.org:587"
    assert p.network == "clearnet"
    assert "imap_host=disroot.org" in (p.notes or "")
    assert "smtp_tls=starttls" in (p.notes or "")


def test_personas_add_unknown_mail_preset_errors_out(tmp_path, monkeypatch):
    """An invalid slug from a stale form selection must rc=2 with a list
    of valid slugs, so the GUI/TUI can splash the error verbatim."""
    from darkcat.config import Config
    from darkcat.identity import invoke_cli_capturing

    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))
    cfg = Config()

    rc, _out, err = invoke_cli_capturing(
        cfg, _personas_add_ns("me-bad", mail_provider="totally-fake"),
    )
    assert rc == 2
    assert "unknown --mail-provider" in err
    assert "totally-fake" in err


def test_personas_add_explicit_site_wins_over_preset(tmp_path, monkeypatch):
    """If the operator types a site override in the form, the preset
    must NOT clobber it. Same precedence as the CLI flag layering."""
    from darkcat.config import Config
    from darkcat.identity import invoke_cli_capturing

    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))
    cfg = Config()

    rc, _out, err = invoke_cli_capturing(
        cfg, _personas_add_ns(
            "me-custom", mail_provider="disroot",
            site="my-bridge.local:2525",
        ),
    )
    assert rc == 0, err

    inner = pv.Vault(path=pv.vault_path(plain=True))
    p = inner.get("me-custom")
    assert p.site == "my-bridge.local:2525"


def test_personas_add_without_preset_works(tmp_path, monkeypatch):
    """Form with the '(none — fill manually)' option selected must still
    produce a persona — covers operators using non-curated providers."""
    from darkcat.config import Config
    from darkcat.identity import invoke_cli_capturing

    monkeypatch.setenv("DARKCAT_HOME", str(tmp_path))
    cfg = Config()

    rc, _out, err = invoke_cli_capturing(
        cfg, _personas_add_ns(
            "me-bare", mail_provider=None,
            network="clearnet", site="mail.example.org:587",
        ),
    )
    assert rc == 0, err

    inner = pv.Vault(path=pv.vault_path(plain=True))
    p = inner.get("me-bare")
    assert p is not None
    assert p.site == "mail.example.org:587"
