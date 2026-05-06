"""Darkcat visual theme — palette, ASCII banner, Rich helpers.

Underground / phosphor-CRT aesthetic: neon green on pure black with
magenta + cyan accents. Used by the CLI, REPL, TUI status messages, and
the GUI's color tokens.

Public API:

* ``LOGO``, ``LOGO_MINI`` — ASCII art (multi-line and one-liner).
* ``TAGLINE``               — one-line subtitle.
* color constants            — for direct use in non-Rich contexts (Tkinter).
* ``logo_asset(name)``       — absolute path to a packaged PNG asset.
* ``get_console()``          — themed Rich Console factory (auto-degrades when piped).
* ``banner(console, ...)``   — print the logo + tagline (with nyan art on the right).
* ``rule(console, label)``   — themed horizontal rule.
* ``panel(title, body)``     — themed Rich Panel.
* ``table(*headers)``        — themed Rich Table.
* ``status_dot(ok)``         — markup snippet for ●/○ indicators.
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Optional

from rich.box import HEAVY
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

try:
    from darkcat._nyan_ascii import NYAN_LINES, NYAN_WIDTH
except Exception:  # pragma: no cover — keep banner usable if asset missing
    NYAN_LINES = []
    NYAN_WIDTH = 0


# --- Palette ----------------------------------------------------------------
# Tk uses these constants directly; Rich uses them through the theme below.

PURE_BLACK = "#000000"
DEEP_BG    = "#050a06"   # near-black with a green tint, looks better than pure on most terms
PANEL_BG   = "#080d09"
NEON_GREEN = "#00ff66"
DARK_GREEN = "#3a6b4c"
DEEP_GREEN = "#0a3320"
DIM_FG     = "#5c8c70"
NEON_PINK  = "#ff00aa"
NEON_CYAN  = "#00e5ff"
AMBER      = "#ffb000"
NEON_RED   = "#ff1a4b"


_THEME = Theme(
    {
        # Logical roles — keep call sites readable.
        "ok":           f"bold {NEON_GREEN}",
        "fail":         f"bold {NEON_RED}",
        "warn":         AMBER,
        "info":         NEON_GREEN,
        "muted":        DIM_FG,
        "key":          f"bold {NEON_CYAN}",
        "value":        NEON_GREEN,
        "url":          f"underline {NEON_CYAN}",
        "title":        f"bold {NEON_PINK}",
        "tagline":      f"italic {DIM_FG}",
        "prompt":       f"bold {NEON_GREEN}",
        "tag":          f"bold {NEON_CYAN}",
        "score.high":   f"bold {NEON_GREEN}",
        "score.mid":    AMBER,
        "score.low":    DIM_FG,
        # Rich built-in slots.
        "rule.line":    NEON_PINK,
        "rule.text":    f"bold {NEON_PINK}",
        "table.header": f"bold {NEON_PINK}",
        "panel.border": NEON_PINK,
    }
)


LOGO = r"""██████╗  █████╗ ██████╗ ██╗  ██╗ ██████╗ █████╗ ████████╗
██╔══██╗██╔══██╗██╔══██╗██║ ██╔╝██╔════╝██╔══██╗╚══██╔══╝
██║  ██║███████║██████╔╝█████╔╝ ██║     ███████║   ██║
██║  ██║██╔══██║██╔══██╗██╔═██╗ ██║     ██╔══██║   ██║
██████╔╝██║  ██║██║  ██║██║  ██╗╚██████╗██║  ██║   ██║
╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝   ╚═╝"""

LOGO_MINI = "▓▒░ darkcat ░▒▓"

TAGLINE = "// multi-protocol darknet × overlay-network crawler"


# --- Button labels & glyphs -------------------------------------------------
# Single source of truth for button text — keeps GUI/TUI/REPL in lockstep.

GLYPH_RUN     = "▶"
GLYPH_STOP    = "■"
GLYPH_SEARCH  = "⌕"
GLYPH_FETCH   = "⤓"
GLYPH_REFRESH = "↻"
GLYPH_PULSE   = "◉"
GLYPH_BULLET  = "●"
GLYPH_DOT_OFF = "○"
GLYPH_ARROW   = "›"

BTN_CRAWL    = f"{GLYPH_RUN}  CRAWL"
BTN_STOP     = f"{GLYPH_STOP}  ABORT"
BTN_SEARCH   = f"{GLYPH_SEARCH}  SEARCH"
BTN_FETCH    = f"{GLYPH_FETCH}  FETCH"
BTN_REFRESH  = f"{GLYPH_REFRESH}  REFRESH"
BTN_RESCAN   = f"{GLYPH_REFRESH}  RESCAN"


def hint_markup(key: str, label: str) -> str:
    """Format a keyboard hint as ``[KEY] label`` with Rich markup."""
    return f"[bold {NEON_PINK}]\\[{key}][/] [{DIM_FG}]{label}[/]"


def hint_plain(key: str, label: str) -> str:
    """Plain-text variant of :func:`hint_markup` for non-Rich surfaces."""
    return f"[{key}] {label}"


def get_console(
    *,
    stderr: bool = False,
    force_terminal: Optional[bool] = None,
) -> Console:
    """Return a themed Rich console. Auto-degrades to plain text when piped."""
    return Console(
        theme=_THEME,
        stderr=stderr,
        force_terminal=force_terminal,
        highlight=False,
        emoji=False,
    )


def logo_asset(name: str) -> Path:
    """Absolute path to a packaged PNG under ``darkcat/assets/<name>``.

    Uses ``importlib.resources`` so it works after pip install (wheel) and
    from a source checkout. Falls back to a path next to this file.
    """
    try:
        ref = resources.files("darkcat") / "assets" / name
        # ``files()`` returns a Traversable — coerce to a real filesystem
        # path. For wheels installed unpacked this is a no-op; for zipped
        # installs the caller may need to use ``as_file`` instead.
        return Path(str(ref))
    except (ModuleNotFoundError, FileNotFoundError):
        return Path(__file__).parent / "assets" / name


def darkcat_logo(size: int = 256, *, variant: str = "") -> Path:
    """Path to the canonical darkcat mark under ``darkcat/assets/logos/``.

    Sizes available in the bundle: 64, 128, 256, 512, 1024, 2048.
    Variants: ``""`` (default rounded mark), ``"black"``, ``"white"``.
    Always transparent. Masters are steg-embedded — never resize or recolor.
    """
    suffix = f"_{variant}" if variant else ""
    name = f"darkcat_rounded_transparent_{size}x{size}{suffix}.png"
    try:
        ref = resources.files("darkcat") / "assets" / "logos" / name
        return Path(str(ref))
    except (ModuleNotFoundError, FileNotFoundError):
        return Path(__file__).parent / "assets" / "logos" / name


def banner(console: Console, *, subtitle: str = TAGLINE, version: str = "") -> None:
    """Render the Darkcat logo + tagline with the nyan-cat sidekick on the right."""
    logo_lines = LOGO.splitlines()
    width = max(len(line) for line in logo_lines)
    nyan_lines = NYAN_LINES if NYAN_LINES else []
    gutter = "  "

    txt = Text()
    for i, line in enumerate(logo_lines):
        txt.append(line.ljust(width), style=NEON_GREEN)
        if i < len(nyan_lines):
            txt.append(gutter)
            # NYAN_LINES already carry their own ANSI escapes — emit raw.
            txt.append_text(Text.from_ansi(nyan_lines[i]))
        txt.append("\n")
    sub = f"{subtitle}    v{version}" if version else subtitle
    txt.append(sub.ljust(width), style=f"italic {DIM_FG}")
    console.print(txt)
    console.print()


def rule(console: Console, label: str = "") -> None:
    """Themed horizontal rule using ═ characters."""
    console.print(Rule(label, characters="═", style=NEON_PINK))


def panel(title: str, body, *, border: str = NEON_PINK) -> Panel:
    """Heavy-bordered panel with magenta accents."""
    return Panel(
        body,
        title=f"[{NEON_PINK}]▓▒░[/] [bold {NEON_PINK}]{title}[/] [{NEON_PINK}]░▒▓[/]",
        title_align="left",
        border_style=border,
        box=HEAVY,
        padding=(1, 2),
    )


def table(*headers: str, title: Optional[str] = None) -> Table:
    """Pre-styled Rich Table for status/top/search/stats output."""
    t = Table(
        title=(f"[bold {NEON_PINK}]▓▒░ {title} ░▒▓[/]" if title else None),
        title_justify="left",
        box=HEAVY,
        border_style=NEON_PINK,
        header_style=f"bold {NEON_PINK}",
        show_lines=False,
        expand=False,
        padding=(0, 1),
    )
    for h in headers:
        t.add_column(h, style=NEON_GREEN, no_wrap=False, overflow="fold")
    return t


def status_dot(ok: bool) -> str:
    """Rich markup for an up/down status pip."""
    return f"[bold {NEON_GREEN}]●[/]" if ok else f"[bold {NEON_RED}]○[/]"


def score_style(score: float) -> str:
    """Rich style name for a topic score (high → green, mid → amber, low → dim)."""
    if score >= 1.0:
        return "score.high"
    if score >= 0.3:
        return "score.mid"
    return "score.low"


# --- About / splash rendering ----------------------------------------------
# Half-block (▀) rendering puts two stacked pixels into one terminal cell:
# the upper pixel as foreground colour, the lower as background. That gives
# us a portable, dependency-light way to show the logo inside the TUI's
# About modal and the CLI's `darkcat about` output — works on any 24-bit
# colour terminal without Sixel / Kitty / iTerm-specific protocols.
#
# Pillow is imported lazily so darkcat still runs (and the TUI still opens)
# on installs where it isn't present — the helpers degrade to None and the
# About panel falls back to the ASCII LOGO.

# Treat alpha < this as "background" — keeps the rounded mask crisp instead
# of bleeding semi-transparent fringes into the panel's solid background.
_ALPHA_CUTOFF = 24


def render_logo_halfblock(
    png_path: Path,
    *,
    cell_width: int = 24,
) -> Optional[Text]:
    """Render *png_path* as a Rich :class:`Text` using upper-half-block cells.

    Each cell encodes 1×2 pixels: upper as foreground, lower as background.
    Returns ``None`` when Pillow is missing or the file is unreadable —
    callers should fall back to ASCII art in that case.

    The terminal cell aspect ratio (~1:2 wide-to-tall) means a square logo
    needs to be rendered into ``cell_width × cell_width//2`` cells to look
    visually square. We pick a target pixel canvas of
    ``cell_width × cell_width`` (each cell is 2 px tall → ``cell_width``
    rows of pixels = ``cell_width // 2`` rows of cells).
    """
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        return None
    if not png_path.exists():
        return None
    try:
        img = Image.open(png_path).convert("RGBA")
    except Exception:
        return None

    src_w, src_h = img.size
    aspect = src_h / src_w
    target_w = max(2, int(cell_width))
    target_h = max(2, int(round(cell_width * aspect)))
    if target_h % 2:
        target_h += 1
    img = img.resize((target_w, target_h), Image.LANCZOS)
    px = img.load()

    out = Text()
    for y in range(0, target_h, 2):
        for x in range(target_w):
            tr, tg, tb, ta = px[x, y]
            br, bg_, bb, ba = px[x, y + 1]
            top_visible = ta >= _ALPHA_CUTOFF
            bot_visible = ba >= _ALPHA_CUTOFF
            if not top_visible and not bot_visible:
                out.append(" ")
            elif top_visible and not bot_visible:
                fg = f"#{tr:02x}{tg:02x}{tb:02x}"
                out.append("▀", style=fg)
            elif bot_visible and not top_visible:
                bg_hex = f"#{br:02x}{bg_:02x}{bb:02x}"
                # ▄ = lower half block — opposite role of ▀.
                out.append("▄", style=bg_hex)
            else:
                fg = f"#{tr:02x}{tg:02x}{tb:02x}"
                bg_hex = f"#{br:02x}{bg_:02x}{bb:02x}"
                out.append("▀", style=f"{fg} on {bg_hex}")
        if y + 2 < target_h:
            out.append("\n")
    return out


def about_panel(
    version: str,
    *,
    url: str = "",
    tagline: str = TAGLINE,
    license_str: str = "GPL-3.0-or-later",
    maintainer: str = "Overdrive (Borja Tarraso)",
    logo_cols: int = 28,
) -> Panel:
    """Compose the About panel: half-block logo + name/version/tagline/url/license."""
    from rich.align import Align
    from rich.console import Group

    logo: Optional[Text] = None
    try:
        png = darkcat_logo(64)
        logo = render_logo_halfblock(png, cell_width=logo_cols)
    except Exception:
        logo = None
    if logo is None:
        logo = Text(LOGO, style=NEON_GREEN)

    body = Text()
    body.append(f"darkcat {version}\n", style=f"bold {NEON_GREEN}")
    body.append(f"{tagline}\n\n", style=f"italic {DIM_FG}")
    body.append("License:    ", style=DIM_FG)
    body.append(f"{license_str}\n", style=NEON_GREEN)
    if url:
        body.append("Source:     ", style=DIM_FG)
        body.append(f"{url}\n", style=f"underline {NEON_CYAN}")
    body.append("Maintainer: ", style=DIM_FG)
    body.append(f"{maintainer}\n", style=NEON_GREEN)

    return Panel(
        Group(Align.center(logo), Text(""), Align.center(body)),
        title=f"[bold {NEON_PINK}]▓▒░ About darkcat ░▒▓[/]",
        title_align="center",
        border_style=NEON_PINK,
        box=HEAVY,
        padding=(1, 3),
    )
