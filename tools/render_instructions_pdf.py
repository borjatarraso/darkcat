#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Render ``instructions.txt`` to ``instructions.pdf``.

Uses ``fpdf2`` because it's the smallest dependency that lays out a
fixed-width, multi-page text document well — no LaTeX, no headless
browser. The page is A4 portrait, 9pt Courier, 1cm margins. Long lines
are soft-wrapped on the natural break the source already provides; we
do not re-wrap, since the txt is already hand-formatted.

Usage::

    python tools/render_instructions_pdf.py
    # or:
    python tools/render_instructions_pdf.py path/to/in.txt path/to/out.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos


# Candidate Unicode-capable monospaced TTFs. We try them in order; the
# first one that exists wins. fpdf2's built-in Courier is latin-1 only
# and chokes on em-dashes / bullets / box-drawing — so a real Unicode
# font is required for instructions.txt as written.
_FONT_CANDIDATES = (
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/Library/Fonts/Menlo.ttc",
    "C:/Windows/Fonts/consola.ttf",
)


def _pick_font() -> Path | None:
    for p in _FONT_CANDIDATES:
        path = Path(p)
        if path.exists():
            return path
    return None


# When no Unicode font is found we fall back to Courier and transliterate
# the few non-ASCII characters our source actually uses. This keeps the
# tool usable without any extra system fonts at the cost of a slightly
# uglier PDF (— becomes --, • becomes *, etc.).
_ASCII_SUBS = str.maketrans({
    "—": "--", "–": "-", "→": "->", "←": "<-", "•": "*",
    "“": '"', "”": '"', "‘": "'", "’": "'", "…": "...",
    "≥": ">=", "≤": "<=", "·": ".", "▸": ">",
})


def render(src: Path, dst: Path) -> None:
    text = src.read_text(encoding="utf-8")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.set_margins(left=12, top=12, right=12)
    pdf.add_page()

    font_path = _pick_font()
    if font_path is not None:
        pdf.add_font("DejaVuMono", "", str(font_path))
        pdf.set_font("DejaVuMono", size=8.5)
    else:
        pdf.set_font("Courier", size=8.5)
        text = text.translate(_ASCII_SUBS)

    line_h = 3.6  # mm per line @ 8.5pt mono
    page_width = pdf.w - pdf.l_margin - pdf.r_margin

    for raw in text.splitlines():
        # Clip ultra-long lines so they don't overflow the right margin.
        # 95 chars @ 8.5pt mono fits in ~186mm (A4 page minus margins).
        for chunk in _hard_wrap(raw, 95):
            pdf.cell(
                page_width, line_h, chunk,
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )

    pdf.output(str(dst))


def _hard_wrap(line: str, width: int) -> list[str]:
    if not line:
        return [""]
    parts: list[str] = []
    while len(line) > width:
        parts.append(line[:width])
        line = line[width:]
    parts.append(line)
    return parts


def main() -> int:
    here = Path(__file__).resolve().parent.parent
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "instructions.txt"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else here / "instructions.pdf"

    if not src.exists():
        print(f"ERROR: source not found: {src}", file=sys.stderr)
        return 2

    render(src, dst)
    print(f"wrote {dst} ({dst.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
