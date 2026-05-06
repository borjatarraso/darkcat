"""Tests for darkcat.theme logo path helpers and packaged-asset shipping.

These tests guard the wiring between :func:`darkcat.theme.darkcat_logo`,
the steg-embedded logo bundle under ``src/darkcat/assets/logos/`` and the
``[tool.setuptools.package-data]`` glob in ``pyproject.toml``. If any of
those drift apart, the GUI window icon and README header silently break
in installed wheels — these tests catch that.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from darkcat.theme import (
    about_panel,
    darkcat_logo,
    logo_asset,
    render_logo_halfblock,
)


SIZES = (64, 128, 256, 512, 1024, 2048)
VARIANTS = ("", "black", "white")


@pytest.mark.parametrize("size", SIZES)
def test_darkcat_logo_default_variant_resolves_to_existing_file(size: int) -> None:
    p = darkcat_logo(size)
    assert p.exists(), f"missing master for size {size}: {p}"
    assert p.suffix == ".png"


@pytest.mark.parametrize("variant", VARIANTS)
def test_darkcat_logo_each_variant_resolves(variant: str) -> None:
    p = darkcat_logo(64, variant=variant)
    assert p.exists(), f"missing 64x64 {variant or 'default'} variant: {p}"


def test_darkcat_logo_lives_under_assets_logos() -> None:
    p = darkcat_logo(256)
    assert p.parent.name == "logos"
    assert p.parent.parent.name == "assets"
    assert p.parent.parent.parent.name == "darkcat"


def test_darkcat_logo_filename_encodes_size_and_transparency() -> None:
    p = darkcat_logo(512, variant="white")
    assert re.match(
        r"^darkcat_rounded_transparent_512x512_white\.png$", p.name
    ), p.name


def test_logo_asset_still_points_at_top_level_assets_dir() -> None:
    # Pre-existing helper must keep working for the older nyan_cat sprites.
    p = logo_asset("nyan_cat_h32.png")
    assert p.exists(), p
    assert p.parent.name == "assets"


def test_full_logo_bundle_has_expected_count() -> None:
    # 6 sizes × 3 variants = 18 PNGs in the steg-embedded bundle.
    bundle_dir = darkcat_logo(64).parent
    pngs = sorted(bundle_dir.glob("darkcat_rounded_transparent_*.png"))
    assert len(pngs) == 18, [p.name for p in pngs]


# ---- Half-block PNG renderer ------------------------------------------------


def test_render_logo_halfblock_returns_text_for_real_master() -> None:
    pytest.importorskip("PIL")
    text = render_logo_halfblock(darkcat_logo(64), cell_width=20)
    assert text is not None
    plain = text.plain
    rows = plain.split("\n")
    # cell_width=20 px wide; aspect=1 → 20 px tall = 10 cell rows.
    assert len(rows) == 10
    assert all(len(r) == 20 for r in rows), [len(r) for r in rows]


def test_render_logo_halfblock_returns_none_for_missing_file(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    bogus = tmp_path / "does-not-exist.png"
    assert render_logo_halfblock(bogus, cell_width=20) is None


def test_render_logo_halfblock_returns_none_when_pillow_missing(monkeypatch) -> None:
    # Pillow is imported lazily inside the helper. Hide it from the importer
    # so the soft-import path runs even on installs that have it.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("simulated missing Pillow")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert render_logo_halfblock(darkcat_logo(64), cell_width=16) is None


# ---- about_panel composition ------------------------------------------------


def test_about_panel_renders_with_logo_present() -> None:
    from rich.console import Console

    panel = about_panel("9.9.9", url="https://example.test/x")
    buf = Console(width=80, record=True, force_terminal=True)
    buf.print(panel)
    out = buf.export_text()
    assert "darkcat 9.9.9" in out
    assert "GPL-3.0-or-later" in out
    assert "https://example.test/x" in out
    assert "About darkcat" in out


def test_about_panel_falls_back_to_ascii_when_renderer_returns_none(monkeypatch) -> None:
    """When Pillow is unavailable the panel still composes with ASCII LOGO."""
    import darkcat.theme as theme

    monkeypatch.setattr(theme, "render_logo_halfblock", lambda *a, **kw: None)
    panel = about_panel("0.0.1", url="")
    from rich.console import Console
    buf = Console(width=80, record=True, force_terminal=True)
    buf.print(panel)
    out = buf.export_text()
    # The fallback embeds the multi-line ASCII LOGO; it always contains
    # the box-drawing block characters.
    assert "darkcat 0.0.1" in out
    assert "GPL-3.0-or-later" in out
