"""Tkinter desktop GUI for darkcat — mirrors the TUI in a windowed app."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from darkcat import __license__, __url__, __version__
from darkcat.categorize import SCORE_HELP, categorize_str
from darkcat.config import Config
from darkcat.control import TransportControl
from darkcat.crawler import Crawler, CrawlPolicy
from darkcat.fetcher import Fetcher
from darkcat.protocols import Protocol
from darkcat.seeds import SEEDS_BY_PROTOCOL, all_seeds
from darkcat.storage import Storage
from darkcat.theme import (
    AMBER,
    BTN_CRAWL,
    BTN_FETCH,
    BTN_REFRESH,
    BTN_RESCAN,
    BTN_SEARCH,
    BTN_STOP,
    DARK_GREEN,
    DEEP_BG,
    DIM_FG,
    GLYPH_FETCH,
    LOGO,
    LOGO_MINI,
    NEON_CYAN,
    NEON_GREEN,
    NEON_PINK,
    NEON_RED,
    PANEL_BG,
    TAGLINE,
    darkcat_logo,
    logo_asset,
)
from darkcat.topic_filter import TopicFilter


_POLL_MS = 100  # how often the main loop drains the worker → UI message queue
_LOG_LINE_CAP = 5000  # trim the log Text widget once it exceeds this many lines

# Sane bounds for crawl-form inputs — anything outside these gets clamped and
# the user gets a polite warning in the log.
_PAGES_RANGE = (1, 100_000)
_DEPTH_RANGE = (0, 25)
_THRESHOLD_RANGE = (0.0, 1_000.0)


def _pick_mono_font(root: tk.Tk) -> str:
    """Pick the best available monospaced font for the current platform."""
    families = set(tkfont.families(root))
    for candidate in (
        "Cascadia Mono", "Cascadia Code", "JetBrains Mono", "Fira Code",
        "Source Code Pro", "Hack", "DejaVu Sans Mono", "Menlo", "Consolas",
        "Monaco", "Courier New",
    ):
        if candidate in families:
            return candidate
    return "TkFixedFont"


def _apply_dark_theme(root: tk.Tk) -> tuple[str, str]:
    """Configure ttk + Tk for the darknet dark theme. Returns (mono, mono_bold)."""
    style = ttk.Style(root)
    # 'clam' is the most customisable cross-platform ttk theme.
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    mono = _pick_mono_font(root)
    base_font = (mono, 10)
    bold_font = (mono, 10, "bold")
    head_font = (mono, 11, "bold")

    root.configure(bg=DEEP_BG)
    root.option_add("*Font", base_font)
    root.option_add("*Background", DEEP_BG)
    root.option_add("*Foreground", NEON_GREEN)
    root.option_add("*selectBackground", "#1a0033")
    root.option_add("*selectForeground", NEON_PINK)
    root.option_add("*highlightBackground", DEEP_BG)
    root.option_add("*highlightColor", NEON_CYAN)

    style.configure(".",
        background=DEEP_BG, foreground=NEON_GREEN,
        fieldbackground=PANEL_BG, troughcolor=PANEL_BG,
        bordercolor=DARK_GREEN, lightcolor=DARK_GREEN, darkcolor=DARK_GREEN,
        font=base_font,
    )
    style.configure("TFrame", background=DEEP_BG)
    style.configure("TLabel", background=DEEP_BG, foreground=NEON_GREEN, font=base_font)
    style.configure("Banner.TLabel",
        background=DEEP_BG, foreground=NEON_GREEN, font=(mono, 9))
    style.configure("Tagline.TLabel",
        background=DEEP_BG, foreground=DIM_FG, font=(mono, 9, "italic"))
    style.configure("Status.TLabel",
        background=DEEP_BG, foreground=NEON_GREEN, font=base_font)
    style.configure("Heading.TLabel",
        background=DEEP_BG, foreground=NEON_PINK, font=head_font)
    style.configure("Key.TLabel",
        background=DEEP_BG, foreground=NEON_CYAN, font=bold_font)

    style.configure("TLabelframe",
        background=DEEP_BG, foreground=NEON_PINK,
        bordercolor=NEON_PINK, lightcolor=NEON_PINK, darkcolor=NEON_PINK,
        relief="solid", borderwidth=2,
    )
    style.configure("TLabelframe.Label",
        background=DEEP_BG, foreground=NEON_PINK, font=bold_font)

    # Default (secondary) button — dark-green border, green text.
    style.configure("TButton",
        background=DEEP_BG, foreground=NEON_GREEN,
        bordercolor=DARK_GREEN, lightcolor=DARK_GREEN, darkcolor=DARK_GREEN,
        focuscolor=NEON_CYAN, font=bold_font, padding=(14, 6),
        relief="solid", borderwidth=2,
    )
    style.map("TButton",
        background=[("active", "#0a3320"), ("pressed", PANEL_BG)],
        foreground=[("active", NEON_CYAN), ("pressed", NEON_CYAN)],
        bordercolor=[("active", NEON_CYAN), ("focus", NEON_CYAN)],
        lightcolor=[("active", NEON_CYAN), ("focus", NEON_CYAN)],
        darkcolor=[("active", NEON_CYAN), ("focus", NEON_CYAN)],
    )

    # Primary (CRAWL) — magenta-bordered, bold, pink text.
    style.configure("Primary.TButton",
        background=DEEP_BG, foreground=NEON_PINK,
        bordercolor=NEON_PINK, lightcolor=NEON_PINK, darkcolor=NEON_PINK,
        focuscolor=NEON_CYAN, font=head_font, padding=(16, 6),
        relief="solid", borderwidth=2,
    )
    style.map("Primary.TButton",
        background=[("active", "#1a0033"), ("pressed", PANEL_BG)],
        foreground=[("active", NEON_PINK)],
        bordercolor=[("active", NEON_CYAN), ("focus", NEON_CYAN)],
        lightcolor=[("active", NEON_CYAN), ("focus", NEON_CYAN)],
        darkcolor=[("active", NEON_CYAN), ("focus", NEON_CYAN)],
    )

    # Stop / abort — red-bordered, red text.
    style.configure("Stop.TButton",
        background=DEEP_BG, foreground=NEON_RED,
        bordercolor=NEON_RED, lightcolor=NEON_RED, darkcolor=NEON_RED,
        focuscolor=NEON_CYAN, font=head_font, padding=(16, 6),
        relief="solid", borderwidth=2,
    )
    style.map("Stop.TButton",
        background=[("active", "#330011")],
        foreground=[("active", NEON_RED)],
        bordercolor=[("disabled", DARK_GREEN)],
    )

    # Tool button — flat, used for tiny refresh-style controls.
    style.configure("Tool.TButton",
        background=DEEP_BG, foreground=NEON_CYAN,
        bordercolor=DARK_GREEN, lightcolor=DARK_GREEN, darkcolor=DARK_GREEN,
        font=bold_font, padding=(8, 3), relief="flat", borderwidth=1,
    )
    style.map("Tool.TButton",
        background=[("active", "#0a3320")],
        foreground=[("active", NEON_PINK)],
        bordercolor=[("active", NEON_CYAN), ("focus", NEON_CYAN)],
    )

    # Inline section heading inside the form ("actions", "search", "fetch").
    style.configure("Section.TLabel",
        background=DEEP_BG, foreground=NEON_PINK,
        font=(mono, 9, "bold"),
    )

    style.configure("TEntry",
        fieldbackground=PANEL_BG, foreground=NEON_GREEN,
        insertcolor=NEON_GREEN, bordercolor=DARK_GREEN,
        lightcolor=DARK_GREEN, darkcolor=DARK_GREEN,
        padding=4,
    )
    style.map("TEntry",
        bordercolor=[("focus", NEON_CYAN)],
        lightcolor=[("focus", NEON_CYAN)],
        darkcolor=[("focus", NEON_CYAN)],
    )

    style.configure("TCombobox",
        fieldbackground=PANEL_BG, foreground=NEON_GREEN,
        background=DEEP_BG, bordercolor=DARK_GREEN,
        arrowcolor=NEON_PINK, selectbackground=PANEL_BG,
        selectforeground=NEON_PINK, padding=4,
    )
    style.map("TCombobox",
        bordercolor=[("focus", NEON_CYAN)],
        fieldbackground=[("readonly", PANEL_BG)],
        foreground=[("readonly", NEON_GREEN)],
    )
    # Tk listbox is a *separate* widget under combobox dropdown — needs
    # option_add to pick up colors.
    root.option_add("*TCombobox*Listbox.background", PANEL_BG)
    root.option_add("*TCombobox*Listbox.foreground", NEON_GREEN)
    root.option_add("*TCombobox*Listbox.selectBackground", "#1a0033")
    root.option_add("*TCombobox*Listbox.selectForeground", NEON_PINK)
    root.option_add("*TCombobox*Listbox.font", base_font)

    style.configure("Treeview",
        background=DEEP_BG, fieldbackground=DEEP_BG, foreground=NEON_GREEN,
        bordercolor=NEON_PINK, font=base_font, rowheight=22,
    )
    style.configure("Treeview.Heading",
        background=DEEP_BG, foreground=NEON_PINK,
        bordercolor=NEON_PINK, relief="flat", font=bold_font,
    )
    style.map("Treeview",
        background=[("selected", "#1a0033")],
        foreground=[("selected", NEON_PINK)],
    )
    style.map("Treeview.Heading",
        background=[("active", "#0a3320")],
    )

    style.configure("TScrollbar",
        background=DEEP_BG, troughcolor=PANEL_BG,
        bordercolor=DARK_GREEN, arrowcolor=NEON_PINK, gripcount=0,
    )
    style.map("TScrollbar",
        background=[("active", "#0a3320")],
    )

    style.configure("TPanedwindow", background=DEEP_BG)
    style.configure("TSeparator", background=NEON_PINK)

    return mono, mono


class Tooltip:
    """Tiny delayed hover tooltip — pops up after ``delay_ms`` over a widget."""

    def __init__(self, widget: tk.Widget, text: str, *, delay_ms: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay_ms
        self._after_id: Optional[str] = None
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self) -> None:
        if self._after_id:
            try: self.widget.after_cancel(self._after_id)
            except tk.TclError: pass
            self._after_id = None

    def _show(self) -> None:
        if self._tip or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.configure(bg=NEON_PINK)
        inner = tk.Frame(tip, bg=PANEL_BG, padx=8, pady=3)
        inner.pack(padx=1, pady=1)
        tk.Label(
            inner, text=self.text, bg=PANEL_BG, fg=NEON_CYAN,
            font=("TkFixedFont", 9), justify="left",
        ).pack()
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._tip:
            try: self._tip.destroy()
            except tk.TclError: pass
            self._tip = None


class DarkcatGUI:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.fetcher = Fetcher(cfg)
        self.storage = Storage(cfg.db_path)
        self.control = TransportControl(cfg)
        self.control.set_password_provider(self._ask_sudo_password)
        self._active_crawler: Optional[Crawler] = None
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        # Track in-flight pill toggles so a double-click can't double-spawn.
        self._toggling: set[str] = set()
        # Cache of rows currently displayed in the results pane — populated by
        # `_populate_results`, consumed by `_export_results`.
        self._last_rows: list = []
        # Per-operation in-flight flags. Each lambda below toggles the
        # corresponding button between "" / "disabled" via _set_busy.
        self._busy: dict[str, bool] = {
            "search": False, "results": False, "fetch": False,
            "export": False, "stats": False,
        }
        # Buttons populated by `_build_form` / `_build_key_hints` so the busy
        # state can disable them without re-querying widget paths.
        self.search_btn: Optional[ttk.Button] = None
        self.fetch_btn: Optional[ttk.Button] = None
        self.refresh_btn: Optional[ttk.Button] = None
        self.export_btn: Optional[ttk.Button] = None
        self.stats_btn: Optional[ttk.Button] = None

        root = tk.Tk()
        root.title(f"darkcat {__version__}")
        root.geometry("1200x780")
        self.root = root
        try:
            icon_png = darkcat_logo(64)
            if icon_png.exists():
                self._win_icon = tk.PhotoImage(file=str(icon_png))
                root.iconphoto(True, self._win_icon)
        except tk.TclError:
            pass
        self._mono, _ = _apply_dark_theme(root)

        self._scan_phase = 0  # used by the pulsing "scanning…" indicator
        self._scan_alive = False

        self._build_menu_bar()
        self._build_banner()
        self._build_status_bar()
        self._build_form()
        self._build_panes()
        self._build_message_bar()
        self._build_key_hints()

        self._tick_clock()
        self._refresh_status_async()
        self._schedule_status_autorefresh()
        self._refresh_results()
        self._bind_shortcuts()
        self._log_segments([
            ("title", "▓▒░ "),
            ("ok", "darkcat GUI online"),
            ("title", " ░▒▓"),
            ("muted", "  pick a protocol, set topics, hit "),
            ("info", BTN_CRAWL),
            ("muted", " · keybinds in the footer"),
        ])
        self.root.after(_POLL_MS, self._poll_queue)
        # First-run wizard — only when ~/.darkcat is missing. Scheduled via
        # `after` so the Tk main window is fully realised before the modal
        # grab; otherwise the dialog can render behind the main window.
        if self._needs_first_run():
            self.root.after(150, self._show_welcome_wizard)

    @staticmethod
    def _needs_first_run() -> bool:
        from darkcat.personas import default_dir as _persona_dir
        return not _persona_dir().exists()

    # ---- layout ---------------------------------------------------------

    def _build_menu_bar(self) -> None:
        """Top menu bar — File / View / Help. Mirrors keyboard shortcuts so
        users who don't know the keymap can still find every action via the
        mouse."""
        menubar = tk.Menu(
            self.root, bg=PANEL_BG, fg=NEON_GREEN,
            activebackground=NEON_PINK, activeforeground=DEEP_BG,
            bd=0, relief="flat",
        )

        file_menu = tk.Menu(
            menubar, tearoff=0,
            bg=PANEL_BG, fg=NEON_GREEN,
            activebackground=NEON_PINK, activeforeground=DEEP_BG,
        )
        file_menu.add_command(
            label="Export results…", accelerator="Ctrl+E",
            command=self._export_results,
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Quit", accelerator="Ctrl+Q",
            command=self._on_close,
        )
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(
            menubar, tearoff=0,
            bg=PANEL_BG, fg=NEON_GREEN,
            activebackground=NEON_PINK, activeforeground=DEEP_BG,
        )
        view_menu.add_command(
            label="Refresh results", accelerator="F5",
            command=self._refresh_results,
        )
        view_menu.add_command(
            label="Re-probe transports", accelerator="Ctrl+R",
            command=self._refresh_status_async,
        )
        view_menu.add_command(
            label="Database statistics", accelerator="Ctrl+I",
            command=self._show_stats,
        )
        view_menu.add_separator()
        view_menu.add_command(
            label="Clear log", accelerator="Ctrl+L",
            command=self._clear_log,
        )
        menubar.add_cascade(label="View", menu=view_menu)

        identity_menu = tk.Menu(
            menubar, tearoff=0,
            bg=PANEL_BG, fg=NEON_GREEN,
            activebackground=NEON_PINK, activeforeground=DEEP_BG,
        )
        identity_menu.add_command(
            label="Open vault…", accelerator="Ctrl+Shift+I",
            command=self._show_identity,
        )
        menubar.add_cascade(label="Identity", menu=identity_menu)

        chat_menu = tk.Menu(
            menubar, tearoff=0,
            bg=PANEL_BG, fg=NEON_GREEN,
            activebackground=NEON_PINK, activeforeground=DEEP_BG,
        )
        chat_menu.add_command(
            label="Chat console…", accelerator="Ctrl+Shift+C",
            command=self._show_chat,
        )
        menubar.add_cascade(label="Chat", menu=chat_menu)

        mail_menu = tk.Menu(
            menubar, tearoff=0,
            bg=PANEL_BG, fg=NEON_GREEN,
            activebackground=NEON_PINK, activeforeground=DEEP_BG,
        )
        mail_menu.add_command(
            label="Mail console…", accelerator="Ctrl+Shift+M",
            command=self._show_mail,
        )
        mail_menu.add_command(
            label="Add mail persona…",
            command=self._show_persona_add,
        )
        menubar.add_cascade(label="Mail", menu=mail_menu)

        help_menu = tk.Menu(
            menubar, tearoff=0,
            bg=PANEL_BG, fg=NEON_GREEN,
            activebackground=NEON_PINK, activeforeground=DEEP_BG,
        )
        help_menu.add_command(
            label="Keyboard shortcuts…", accelerator="F2",
            command=self._show_shortcuts,
        )
        help_menu.add_command(
            label="Run doctor…",
            command=self._show_doctor,
        )
        help_menu.add_command(
            label="About darkcat…", accelerator="F1",
            command=self._show_about,
        )
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    def _build_message_bar(self) -> None:
        """Bottom-most status strip — single-line `status_var` for the
        current operation ("idle", "crawling tor (35/200)", "search hit 12
        rows…"). Sits below the keybind footer.
        """
        bar = tk.Frame(self.root, bg=PANEL_BG)
        bar.pack(side="bottom", fill="x")
        tk.Frame(bar, bg=NEON_PINK, height=1).pack(side="top", fill="x")
        inner = tk.Frame(bar, bg=PANEL_BG)
        inner.pack(side="top", fill="x", padx=8, pady=2)

        self.status_var = tk.StringVar(value="idle")
        tk.Label(
            inner, text="▸", bg=PANEL_BG, fg=NEON_PINK,
            font=("TkFixedFont", 9, "bold"),
        ).pack(side="left")
        tk.Label(
            inner, textvariable=self.status_var,
            bg=PANEL_BG, fg=NEON_CYAN,
            font=("TkFixedFont", 9),
        ).pack(side="left", padx=(4, 0))

    def _set_status(self, text: str, *, level: str = "info") -> None:
        """Public helper for other GUI methods to update the bottom message
        bar. ``level`` is ignored at the moment but kept for callers that
        want to express intent — once the message bar gains colour states,
        callers won't need to be revisited. Safe no-op if the bar wasn't
        built yet (e.g., during startup)."""
        del level  # placeholder until the bar is themed by severity
        if hasattr(self, "status_var"):
            try:
                self.status_var.set(text)
            except tk.TclError:
                pass

    def _build_banner(self) -> None:
        """ASCII logo + tagline at the very top, with a magenta divider below."""
        bar = ttk.Frame(self.root, padding=(8, 6, 8, 4))
        bar.pack(side="top", fill="x")
        ttk.Label(bar, text=LOGO, style="Banner.TLabel", justify="left").pack(
            side="left", anchor="w"
        )
        right = ttk.Frame(bar)
        right.pack(side="right", anchor="ne", padx=(8, 4))
        # Animated nyan-cat sidekick — sits above the version pill so the
        # whole right column reads logo → version → tagline → clock. The
        # cat bobs vertically inside a Canvas to fake "flight"; the image
        # reference is held on self so Tk doesn't garbage-collect it.
        self._nyan_img = None
        self._nyan_canvas: Optional[tk.Canvas] = None
        self._nyan_item: Optional[int] = None
        self._nyan_phase = 0
        try:
            png = logo_asset("nyan_cat_h32.png")
            if png.exists():
                self._nyan_img = tk.PhotoImage(file=str(png))
                w = self._nyan_img.width()
                h = self._nyan_img.height()
                # +4 px of head-room on top and bottom for the bob arc.
                self._nyan_canvas = tk.Canvas(
                    right, width=w, height=h + 4, bg=DEEP_BG,
                    bd=0, highlightthickness=0,
                )
                self._nyan_canvas.pack(anchor="e", pady=(0, 2))
                self._nyan_item = self._nyan_canvas.create_image(
                    0, 2, anchor="nw", image=self._nyan_img,
                )
                self._tick_nyan()
        except tk.TclError:
            self._nyan_img = None
        ttk.Label(right, text=f"v{__version__}", style="Heading.TLabel").pack(anchor="e")
        ttk.Label(right, text=TAGLINE, style="Tagline.TLabel").pack(anchor="e")
        self.clock_var = tk.StringVar(value="--:--:--")
        ttk.Label(right, textvariable=self.clock_var, style="Key.TLabel").pack(anchor="e")
        # Magenta separator under the banner.
        sep = tk.Frame(self.root, height=1, bg=NEON_PINK)
        sep.pack(side="top", fill="x")

    # 6-step bob: 0,1,2,3,2,1 — a soft triangle wave that mimics the
    # original GIF's frame cadence.
    _NYAN_BOB = (0, 1, 2, 3, 2, 1)

    def _tick_nyan(self) -> None:
        if not self.root.winfo_exists() or self._nyan_canvas is None:
            return
        if not self._nyan_canvas.winfo_exists():
            return
        y = self._NYAN_BOB[self._nyan_phase % len(self._NYAN_BOB)]
        try:
            self._nyan_canvas.coords(self._nyan_item, 0, y)
        except tk.TclError:
            return
        self._nyan_phase += 1
        self.root.after(140, self._tick_nyan)

    def _tick_clock(self) -> None:
        if not self.root.winfo_exists():
            return
        self.clock_var.set(time.strftime("[ %H:%M:%S ]"))
        self.root.after(1000, self._tick_clock)

    def _build_status_bar(self) -> None:
        bar = tk.Frame(self.root, bg=PANEL_BG)
        bar.pack(side="top", fill="x")
        # Magenta hairline above the pill row.
        tk.Frame(bar, height=1, bg=NEON_PINK).pack(side="top", fill="x")
        inner = tk.Frame(bar, bg=PANEL_BG)
        inner.pack(side="top", fill="x", padx=8, pady=4)

        tk.Label(
            inner, text="▓▒░ TRANSPORTS", bg=PANEL_BG, fg=NEON_PINK,
            font=(self._mono, 9, "bold"),
        ).pack(side="left")

        # Right-side summary + scanning indicator + rescan button.
        right = tk.Frame(inner, bg=PANEL_BG); right.pack(side="right")
        rescan = ttk.Button(
            right, text=BTN_RESCAN, command=self._refresh_status_async,
            style="Tool.TButton",
        )
        rescan.pack(side="right", padx=(8, 0))
        Tooltip(rescan, "Re-probe every transport daemon (Ctrl+R)")
        self.scan_var = tk.StringVar(value="◌ scanning…")
        self.scan_label = tk.Label(
            right, textvariable=self.scan_var, bg=PANEL_BG, fg=DIM_FG,
            font=(self._mono, 9, "italic"),
        )
        self.scan_label.pack(side="right", padx=(8, 0))
        self.summary_var = tk.StringVar(value="—")
        tk.Label(
            right, textvariable=self.summary_var, bg=PANEL_BG, fg=NEON_CYAN,
            font=(self._mono, 9, "bold"),
        ).pack(side="right")

        # The pills row — one neon-bordered LED badge per protocol.
        self.pill_frame = tk.Frame(inner, bg=PANEL_BG)
        self.pill_frame.pack(side="left", fill="x", expand=True, padx=(12, 8))
        self._pills: dict[str, tuple[tk.Frame, tk.Label]] = {}

        self._start_scan_pulse()

    def _render_pill(self, name: str, ok: bool) -> None:
        """Create or update an LED-style pill button for one transport.

        Left-click toggles the daemon (start when down, stop when up) and
        streams every command we run + its stdout/stderr to the log panel.
        Right-click runs a probe-only describe + check.
        """
        color = NEON_GREEN if ok else NEON_RED
        glyph = "●" if ok else "○"
        text = f" {glyph}  {name.upper()} "
        if name in self._pills:
            outer, label = self._pills[name]
            outer.configure(bg=color)
            label.configure(fg=color, text=text)
            return
        outer = tk.Frame(self.pill_frame, bg=color, bd=0, highlightthickness=0)
        outer.pack(side="left", padx=(0, 6), pady=2)
        # Inner label gives us the "bordered pill" look — outer color shows
        # through the 1px gap as the LED bezel.
        label = tk.Label(
            outer, text=text, bg=PANEL_BG, fg=color,
            font=(self._mono, 10, "bold"), padx=8, pady=2,
            cursor="hand2",
        )
        label.pack(padx=1, pady=1)

        def on_enter(_e=None, _l=label):
            _l.configure(bg=DEEP_BG)
        def on_leave(_e=None, _l=label):
            _l.configure(bg=PANEL_BG)
        def on_click(_e=None, _name=name):
            self._toggle_transport(_name)
        def on_right_click(_e=None, _name=name):
            self._probe_transport(_name)
        label.bind("<Enter>", on_enter)
        label.bind("<Leave>", on_leave)
        label.bind("<Button-1>", on_click)
        label.bind("<Button-3>", on_right_click)
        outer.bind("<Button-1>", on_click)
        outer.bind("<Button-3>", on_right_click)
        Tooltip(label, f"{name} — left-click: toggle up/down · right-click: probe")
        self._pills[name] = (outer, label)

    def _start_scan_pulse(self) -> None:
        """Animate ◌ ◐ ● ◑ on the right while a status probe is in-flight."""
        if self._scan_alive:
            return
        self._scan_alive = True
        frames = "◌◐●◑"
        def step():
            if not self._scan_alive or not self.root.winfo_exists():
                return
            ch = frames[self._scan_phase % len(frames)]
            self.scan_var.set(f"{ch} scanning…")
            self.scan_label.configure(fg=AMBER)
            self._scan_phase += 1
            self.root.after(180, step)
        step()

    def _stop_scan_pulse(self) -> None:
        self._scan_alive = False
        if self.scan_label.winfo_exists():
            self.scan_var.set("idle")
            self.scan_label.configure(fg=DIM_FG)

    def _build_form(self) -> None:
        frm = ttk.LabelFrame(self.root, text="▓▒░ console ░▒▓", padding=10)
        frm.pack(side="top", fill="x", padx=8, pady=6)

        # Row 1 — topics span the full width.
        row1 = ttk.Frame(frm); row1.pack(fill="x", pady=(0, 4))
        ttk.Label(row1, text="› topics", style="Section.TLabel").pack(side="left")
        self.topics_var = tk.StringVar()
        topics_entry = ttk.Entry(row1, textvariable=self.topics_var)
        topics_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        Tooltip(topics_entry, "Space-separated keywords. Empty = no filtering.")
        # Pressing Enter in the topics field kicks off the crawl, matching
        # the "(Enter)" affordance in the CRAWL button tooltip.
        topics_entry.bind("<Return>", lambda _e: self._start_crawl())

        # Row 2 — knobs.
        row2 = ttk.Frame(frm); row2.pack(fill="x", pady=4)
        ttk.Label(row2, text="› proto", style="Section.TLabel").pack(side="left")
        protos = list(SEEDS_BY_PROTOCOL.keys()) + ["all"]
        self.protocol_var = tk.StringVar(value="tor")
        proto_box = ttk.Combobox(
            row2, textvariable=self.protocol_var, values=protos,
            state="readonly", width=14,
        )
        proto_box.pack(side="left", padx=(8, 12))
        Tooltip(proto_box, "Transport / overlay network to crawl seeds for.")

        ttk.Label(row2, text="pages", style="Key.TLabel").pack(side="left")
        self.max_pages_var = tk.StringVar(value="50")
        ttk.Entry(row2, textvariable=self.max_pages_var, width=6).pack(side="left", padx=(4, 12))
        ttk.Label(row2, text="depth", style="Key.TLabel").pack(side="left")
        self.max_depth_var = tk.StringVar(value="2")
        ttk.Entry(row2, textvariable=self.max_depth_var, width=4).pack(side="left", padx=(4, 12))
        ttk.Label(row2, text="threshold", style="Key.TLabel").pack(side="left")
        self.threshold_var = tk.StringVar(value="0")
        ttk.Entry(row2, textvariable=self.threshold_var, width=5).pack(side="left", padx=(4, 0))

        # Row 3 — actions, grouped: [crawl/stop] | [search] | [fetch].
        row3 = ttk.Frame(frm); row3.pack(fill="x", pady=(8, 0))

        actions = ttk.Frame(row3); actions.pack(side="left")
        ttk.Label(actions, text="› actions", style="Section.TLabel").pack(anchor="w")
        actions_row = ttk.Frame(actions); actions_row.pack(anchor="w", pady=(2, 0))
        self.crawl_btn = ttk.Button(
            actions_row, text=BTN_CRAWL, command=self._start_crawl,
            style="Primary.TButton",
        )
        self.crawl_btn.pack(side="left")
        Tooltip(self.crawl_btn, "Start a new crawl with these settings  (Enter)")
        self.stop_btn = ttk.Button(
            actions_row, text=BTN_STOP, command=self._stop_crawl,
            state="disabled", style="Stop.TButton",
        )
        self.stop_btn.pack(side="left", padx=(6, 0))
        Tooltip(self.stop_btn, "Stop the running crawl  (Ctrl+C)")

        ttk.Separator(row3, orient="vertical").pack(side="left", fill="y", padx=14)

        search = ttk.Frame(row3); search.pack(side="left")
        ttk.Label(search, text="› search", style="Section.TLabel").pack(anchor="w")
        search_row = ttk.Frame(search); search_row.pack(anchor="w", pady=(2, 0))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_row, textvariable=self.search_var, width=22)
        search_entry.pack(side="left")
        search_entry.bind("<Return>", lambda _e: self._do_search())
        Tooltip(search_entry, "FTS5 query against indexed pages (Enter to search)")
        self.search_btn = ttk.Button(
            search_row, text=BTN_SEARCH, command=self._do_search,
        )
        self.search_btn.pack(side="left", padx=(6, 0))
        Tooltip(self.search_btn, "Run a fuzzy multi-strategy search (Enter)")

        ttk.Separator(row3, orient="vertical").pack(side="left", fill="y", padx=14)

        fetch = ttk.Frame(row3); fetch.pack(side="left", fill="x", expand=True)
        ttk.Label(fetch, text="› fetch", style="Section.TLabel").pack(anchor="w")
        fetch_row = ttk.Frame(fetch); fetch_row.pack(anchor="w", pady=(2, 0), fill="x")
        self.fetch_var = tk.StringVar()
        fetch_entry = ttk.Entry(fetch_row, textvariable=self.fetch_var, width=28)
        fetch_entry.pack(side="left")
        fetch_entry.bind("<Return>", lambda _e: self._do_fetch())
        Tooltip(fetch_entry, "Single-shot URL fetch (Enter to fire)")
        self.fetch_btn = ttk.Button(
            fetch_row, text=BTN_FETCH, command=self._do_fetch,
        )
        self.fetch_btn.pack(side="left", padx=(6, 0))
        Tooltip(self.fetch_btn, "Fetch a single URL through the right transport (Enter)")

    def _build_panes(self) -> None:
        pane = ttk.PanedWindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=6, pady=4)

        log_frame = ttk.LabelFrame(pane, text="▓▒░ log ░▒▓", padding=4)
        self.log = tk.Text(
            log_frame, wrap="word", height=20, state="disabled",
            bg=DEEP_BG, fg=NEON_GREEN, insertbackground=NEON_GREEN,
            selectbackground="#1a0033", selectforeground=NEON_PINK,
            font=(self._mono, 10), bd=0, highlightthickness=0, padx=6, pady=4,
        )
        # Tag-based markup — the `_log_styled` helper picks the tag based on kind.
        self.log.tag_configure("ok",    foreground=NEON_GREEN)
        self.log.tag_configure("err",   foreground=NEON_RED)
        self.log.tag_configure("warn",  foreground=AMBER)
        self.log.tag_configure("muted", foreground=DIM_FG)
        self.log.tag_configure("info",  foreground=NEON_CYAN)
        self.log.tag_configure("title", foreground=NEON_PINK, font=(self._mono, 10, "bold"))
        self.log.tag_configure("url",   foreground=NEON_CYAN, underline=1)
        log_scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        pane.add(log_frame, weight=1)

        res_frame = ttk.LabelFrame(pane, text="▓▒░ results ░▒▓", padding=4)
        cols = ("score", "category", "protocol", "title", "url")
        self.results = ttk.Treeview(
            res_frame, columns=cols, show="headings", height=20
        )
        widths = {
            "score": 60, "category": 120, "protocol": 90,
            "title": 280, "url": 360,
        }
        # Click-to-sort state — keyed by column name. True = next click
        # sorts descending. Numeric columns default to descending (largest
        # first matches what users expect from a leaderboard); text columns
        # default to ascending (alphabetical).
        self._sort_state: dict[str, bool] = {
            "score": True,
            "category": False,
            "protocol": False,
            "title": False,
            "url": False,
        }
        for c in cols:
            self.results.heading(
                c, text=c, command=lambda col=c: self._sort_by(col),
            )
            self.results.column(c, width=widths[c], stretch=(c in ("title", "url")))
        res_scroll = ttk.Scrollbar(res_frame, command=self.results.yview)
        self.results.configure(yscrollcommand=res_scroll.set)
        self.results.pack(side="left", fill="both", expand=True)
        res_scroll.pack(side="right", fill="y")
        # Hover-help: the heading row has no native tooltip, so attach a
        # motion handler that pops a Tooltip when the cursor sits over the
        # `score` or `category` column header.
        self._heading_tip: Optional[tk.Toplevel] = None
        self._heading_tip_for: str = ""
        self.results.bind("<Motion>", self._on_results_motion, add="+")
        self.results.bind("<Leave>", lambda _e: self._hide_heading_tip(), add="+")
        # Right-click context menu on a row (copy URL, fetch, mirrors, history).
        # Button-3 on Linux/Win, Button-2 on macOS — wire both for portability.
        self.results.bind("<Button-3>", self._on_results_right_click, add="+")
        self.results.bind("<Button-2>", self._on_results_right_click, add="+")
        # Double-click a row to copy its URL — common Treeview convention.
        self.results.bind("<Double-Button-1>", lambda _e: self._copy_selected_url())
        pane.add(res_frame, weight=1)

    def _build_key_hints(self) -> None:
        """Bottom footbar — keybind cheatsheet on the left, action buttons
        flush to the right. The buttons (refresh, export, quit) live here so
        the result pane gets every spare pixel of vertical space.
        """
        bar = tk.Frame(self.root, bg=PANEL_BG)
        bar.pack(side="bottom", fill="x")
        # Top edge — magenta hairline.
        tk.Frame(bar, bg=NEON_PINK, height=1).pack(side="top", fill="x")
        inner = tk.Frame(bar, bg=PANEL_BG)
        inner.pack(side="top", fill="x", padx=8, pady=2)

        # --- right side: refresh | export | quit (in that order, packed
        # right-to-left so QUIT lands in the bottom-right corner). ---
        actions = tk.Frame(inner, bg=PANEL_BG)
        actions.pack(side="right")

        quit_btn = ttk.Button(
            actions, text="✕  QUIT", command=self._on_close,
            style="Stop.TButton",
        )
        quit_btn.pack(side="right", padx=(6, 0))
        Tooltip(quit_btn, "Close darkcat (Ctrl+Q)")

        self.export_btn = ttk.Button(
            actions, text=f"{GLYPH_FETCH}  EXPORT", command=self._export_results,
            style="Tool.TButton",
        )
        self.export_btn.pack(side="right", padx=(6, 0))
        Tooltip(self.export_btn, "Save the current results table to a .txt file (Ctrl+E)")

        self.refresh_btn = ttk.Button(
            actions, text=BTN_REFRESH, command=self._refresh_results,
            style="Tool.TButton",
        )
        self.refresh_btn.pack(side="right", padx=(6, 0))
        Tooltip(self.refresh_btn, "Re-query top-scored pages from the database (F5)")

        self.stats_btn = ttk.Button(
            actions, text="📊  STATS", command=self._show_stats,
            style="Tool.TButton",
        )
        self.stats_btn.pack(side="right", padx=(6, 0))
        Tooltip(self.stats_btn, "Show database statistics (Ctrl+I)")

        # --- left side: keybind cheatsheet. ---
        hints = [
            ("ENTER", "run focused field"),
            ("CTRL+R", "rescan transports"),
            ("CTRL+C", "abort crawl"),
            ("F5",     "refresh"),
            ("CTRL+E", "export .txt"),
            ("CTRL+I", "stats"),
            ("CTRL+L", "clear log"),
            ("CTRL+Q", "quit"),
        ]
        hint_frame = tk.Frame(inner, bg=PANEL_BG)
        hint_frame.pack(side="left", fill="x", expand=True)
        for i, (key, label) in enumerate(hints):
            if i:
                tk.Label(
                    hint_frame, text="·", bg=PANEL_BG, fg=DIM_FG,
                    font=("TkFixedFont", 9),
                ).pack(side="left", padx=4)
            tk.Label(
                hint_frame, text=f"[{key}]", bg=PANEL_BG, fg=NEON_PINK,
                font=("TkFixedFont", 9, "bold"),
            ).pack(side="left")
            tk.Label(
                hint_frame, text=label, bg=PANEL_BG, fg=DIM_FG,
                font=("TkFixedFont", 9),
            ).pack(side="left", padx=(4, 0))

    def _bind_shortcuts(self) -> None:
        self.root.bind("<F5>",       lambda _e: self._refresh_results())
        self.root.bind("<Control-r>", lambda _e: self._refresh_status_async())
        # Ctrl+C is overloaded — Tk uses it to copy selected text from Entry/
        # Text widgets. If the focused widget owns a text selection, we let
        # the native copy happen and skip the crawl-abort. Otherwise it acts
        # as the abort shortcut as advertised.
        self.root.bind("<Control-c>", self._on_ctrl_c)
        self.root.bind("<Control-l>", lambda _e: self._clear_log())
        self.root.bind("<Control-e>", lambda _e: self._export_results())
        self.root.bind("<Control-i>", lambda _e: self._show_stats())
        self.root.bind("<Control-q>", lambda _e: self._on_close())
        self.root.bind("<F1>",        lambda _e: self._show_about())
        self.root.bind("<F2>",        lambda _e: self._show_shortcuts())
        self.root.bind("<Control-I>", lambda _e: self._show_identity())
        self.root.bind("<Control-C>", lambda _e: self._show_chat())
        self.root.bind("<Control-M>", lambda _e: self._show_mail())

    def _on_ctrl_c(self, event):
        """Route Ctrl+C: copy if a text widget has a selection, else abort
        the running crawl. Returning None (the default) lets Tk dispatch its
        built-in <<Copy>> binding on the focused widget."""
        w = event.widget
        try:
            # Entry / Text both expose tag_ranges("sel"); ttk.Entry uses
            # selection_present(). Treat any active selection as "user is
            # trying to copy, leave us alone".
            if isinstance(w, tk.Text):
                if w.tag_ranges("sel"):
                    return  # let native copy run
            elif isinstance(w, (tk.Entry, ttk.Entry)):
                if w.selection_present():
                    return
        except (tk.TclError, AttributeError):
            pass
        self._stop_crawl()
        return "break"

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._log_segments([("muted", "// log cleared")])

    # ---- queue plumbing -------------------------------------------------

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                self._dispatch_message(kind, payload)
        except queue.Empty:
            pass
        self.root.after(_POLL_MS, self._poll_queue)

    def _dispatch_message(self, kind: str, payload) -> None:
        if kind == "log":
            self._log(payload)
        elif kind == "control_event":
            level, text = payload
            self._log_control_event(level, text)
        elif kind == "status":
            self._stop_scan_pulse()
            up_count, total, statuses = payload
            self.summary_var.set(f"{up_count}/{total} UP")
            for name, ok in statuses:
                self._render_pill(name, ok)
        elif kind == "search_done":
            q, rows, err = payload
            self._set_busy("search", False)
            if err is not None:
                self._set_status(f"search failed: {err[:80]}")
                self._log_segments([
                    ("err", "✗ search failed: "),
                    ("warn", err),
                ])
                return
            self._populate_results(rows)
            self._set_status(f"search hit {len(rows)} row(s) for: {q}")
            self._log_segments([
                ("info", "  → "),
                ("ok", f"{len(rows)}"),
                ("muted", " hit(s) for "),
                ("title", q),
            ])
        elif kind == "results_done":
            rows, err = payload
            self._set_busy("results", False)
            if err is not None:
                self._log_segments([
                    ("err", "✗ results refresh failed: "),
                    ("warn", err),
                ])
                return
            self._populate_results(rows)
        elif kind == "fetch_done":
            ok, msg = payload
            self._set_busy("fetch", False)
            self._set_status("fetch ok" if ok else "fetch failed")
            self._log(msg)
        elif kind == "stats_done":
            page_stats, find_stats, err = payload
            self._set_busy("stats", False)
            if err is not None:
                self._log_segments([
                    ("err", "✗ stats failed: "),
                    ("warn", err),
                ])
                return
            self._render_stats(page_stats, find_stats)
        elif kind == "export_done":
            ok, path, n, err = payload
            self._set_busy("export", False)
            if not ok:
                self._log_segments([
                    ("err", "✗ export failed: "),
                    ("warn", err or "unknown error"),
                ])
                return
            self._log_segments([
                ("ok", "✓ exported "),
                ("info", f"{n}"),
                ("muted", " result(s) → "),
                ("url", path),
            ])
        elif kind == "crawl_done":
            self._set_crawling(False)
            self._refresh_results()
            self._set_status(f"crawl finished — {payload}")
            self._log_segments([("title", "▓▒░ "), ("ok", payload), ("title", " ░▒▓")])
        elif kind == "init_done":
            ok, err = payload
            if ok:
                self._set_status("first-run init complete — home directory ready.",
                                 level="ok")
                self._log_segments([
                    ("title", "▓▒░ "),
                    ("ok", "init complete — home directory ready"),
                    ("title", " ░▒▓"),
                ])
                self._refresh_status_async()
            else:
                self._set_status(f"init failed — {err}", level="fail")
                self._log_segments([
                    ("err", "✗ init failed: "),
                    ("warn", str(err)[:200]),
                ])
        elif kind == "crawl_event":
            ek, p = payload
            if ek == "fetch":
                score = p["score"]
                tag = "ok" if score >= 1.0 else "warn" if score >= 0.3 else "muted"
                self._log_segments([
                    ("ok", "  ▶ "),
                    ("info", f"[{p['protocol']:<10}] "),
                    (tag, f"{score:>5.2f} "),
                    ("muted", f"d={p.get('depth', 0)}  "),
                    ("title", (p.get("title") or "(no title)")),
                    ("muted", "  "),
                    ("url", p["url"]),
                ])
            elif ek == "error":
                self._log_segments([
                    ("err", "  ✗ "),
                    ("info", f"[{p.get('protocol', '?')}] "),
                    ("warn", f"{p.get('error', '')[:160]}  "),
                    ("url", p["url"]),
                ])
            elif ek == "skip":
                self._log_segments([
                    ("muted", f"  · skip {p.get('reason', '')}: {p['url']}"),
                ])

    def _post(self, kind: str, payload) -> None:
        self._queue.put((kind, payload))

    # ---- status ---------------------------------------------------------

    def _refresh_status_async(self) -> None:
        self._start_scan_pulse()
        threading.Thread(target=self._refresh_status_worker, daemon=True).start()

    def _schedule_status_autorefresh(self, interval_ms: int = 30_000) -> None:
        """Re-probe transports periodically so pills stay live."""
        if not self.root.winfo_exists():
            return
        self.root.after(interval_ms, self._auto_refresh_tick)

    def _auto_refresh_tick(self) -> None:
        if not self.root.winfo_exists():
            return
        self._refresh_status_async()
        self._schedule_status_autorefresh()

    def _refresh_status_worker(self) -> None:
        try:
            statuses = self.fetcher.status()
        except Exception as e:
            self._post("log", f"✗ status probe failed: {e}")
            return
        up = sum(1 for ok in statuses.values() if ok)
        total = len(statuses)
        rows = [(p.value, ok) for p, ok in statuses.items()]
        self._post("status", (up, total, rows))

    # ---- transport toggle / probe --------------------------------------

    # Map control.py event levels to log-text tags.
    _CTRL_TAG = {
        "cmd":    "title",
        "stdout": "muted",
        "stderr": "warn",
        "info":   "info",
        "ok":     "ok",
        "warn":   "warn",
        "err":    "err",
        "muted":  "muted",
    }

    def _log_control_event(self, level: str, text: str) -> None:
        self._log_segments([(self._CTRL_TAG.get(level, "info"), text)])

    def _toggle_transport(self, name: str) -> None:
        """Click handler: probe → start (if down) or stop (if up) → re-probe."""
        if name in self._toggling:
            return
        try:
            proto = Protocol(name)
        except ValueError:
            self._log_segments([("err", f"[{name}] unknown protocol")])
            return
        if not self.control.has_profile(proto):
            self._log_segments([
                ("warn", f"[{name}] no daemon profile — this transport is "
                         "stateless or relies on system DNS"),
            ])
            return
        self._toggling.add(name)
        threading.Thread(
            target=self._toggle_transport_worker,
            args=(name, proto),
            daemon=True,
        ).start()

    def _probe_transport(self, name: str) -> None:
        """Right-click handler: just describe + run the probe (no start/stop)."""
        try:
            proto = Protocol(name)
        except ValueError:
            self._log_segments([("err", f"[{name}] unknown protocol")])
            return
        threading.Thread(
            target=self._probe_transport_worker,
            args=(name, proto),
            daemon=True,
        ).start()

    def _toggle_transport_worker(self, name: str, proto: Protocol) -> None:
        try:
            self._post("control_event", ("title", f"▓▒░ {name.upper()} ░▒▓"))
            running = self.control.is_running(proto)
            for ev in self.control.probe(proto):
                self._post("control_event", ev)
            gen = self.control.down(proto) if running else self.control.up(proto)
            for ev in gen:
                self._post("control_event", ev)
            self._post("control_event", ("muted", "  · re-probing transports…"))
        finally:
            self._toggling.discard(name)
            # Schedule a re-probe so the pill repaints itself.
            self._refresh_status_async()

    def _probe_transport_worker(self, name: str, proto: Protocol) -> None:
        self._post("control_event", ("title", f"▓▒░ {name.upper()} probe ░▒▓"))
        for ev in self.control.probe(proto):
            self._post("control_event", ev)

    # ---- sudo password prompt ------------------------------------------
    #
    # Called from a worker thread by darkcat.elevation.run_elevated. Tk
    # widgets are main-thread only, so we marshal the dialog open via
    # `after_idle` and block the worker on a threading.Event until the
    # user answers. Result is placeholder-passed through a 1-element list.

    def _ask_sudo_password(self, prompt: str) -> Optional[str]:
        if threading.current_thread() is threading.main_thread():
            return self._open_sudo_dialog(prompt)
        done = threading.Event()
        result: list[Optional[str]] = [None]

        def _open() -> None:
            try:
                result[0] = self._open_sudo_dialog(prompt)
            finally:
                done.set()

        try:
            self.root.after_idle(_open)
        except (RuntimeError, tk.TclError):
            return None
        # Block worker until the user clicks OK / Cancel / closes the window.
        done.wait()
        return result[0]

    def _show_welcome_wizard(self) -> None:
        """First-run modal — appears once when ``~/.darkcat`` is missing.

        Offers Run init / Skip. Run init dispatches ``cli.cmd_init`` on a
        worker thread so the probe-daemons step doesn't freeze the UI;
        results are reported back via the existing log pane and a final
        message-bar update."""
        from darkcat.personas import default_dir as _persona_dir
        home = _persona_dir()

        dlg = tk.Toplevel(self.root)
        dlg.title("darkcat — welcome")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        try:
            self.root.update_idletasks()
            px = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - 560) // 2)
            py = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - 360) // 3)
            dlg.geometry(f"560x360+{px}+{py}")
        except tk.TclError:
            dlg.geometry("560x360")

        body = tk.Frame(dlg, bg=DEEP_BG, padx=20, pady=18)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text="Welcome to darkcat",
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 14, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(
            body,
            text=("It looks like this is your first run — the directory below "
                  "doesn't exist yet."),
            fg=NEON_GREEN, bg=DEEP_BG, font=(self._mono, 10),
            wraplength=520, justify="left",
        ).pack(anchor="w")
        tk.Label(
            body, text=str(home),
            fg=NEON_PINK, bg=DEEP_BG, font=(self._mono, 10, "bold"),
        ).pack(anchor="w", pady=(2, 10))

        tk.Label(
            body, text="Run init now? It will:",
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 10, "bold"),
        ).pack(anchor="w")
        for line in (
            "•  create the home directory (mode 0700)",
            "•  set up the SQLite database for crawled pages",
            "•  probe transport reachability (Tor, I2P, …)",
        ):
            tk.Label(
                body, text=line,
                fg=NEON_GREEN, bg=DEEP_BG, font=(self._mono, 10),
            ).pack(anchor="w", padx=(12, 0))

        btns = tk.Frame(body, bg=DEEP_BG)
        btns.pack(anchor="e", pady=(18, 0))

        def _accept() -> None:
            dlg.destroy()
            self._run_init_async()

        def _skip() -> None:
            dlg.destroy()
            self._set_status(
                "first-run init skipped — use the CLI `darkcat init` later.",
                level="warn",
            )

        ttk.Button(
            btns, text="Run init", command=_accept, style="Run.TButton",
        ).pack(side="right", padx=(8, 0))
        ttk.Button(
            btns, text="Skip", command=_skip, style="Stop.TButton",
        ).pack(side="right")

        dlg.bind("<Return>", lambda _e: _accept())
        dlg.bind("<Escape>", lambda _e: _skip())
        dlg.protocol("WM_DELETE_WINDOW", _skip)
        dlg.grab_set()
        dlg.focus_set()

    def _run_init_async(self) -> None:
        """Run ``cli.cmd_init`` on a worker thread. The probe step blocks for
        a few seconds on a slow Tor handshake — keeping it off the Tk main
        loop prevents the window from going unresponsive."""
        self._set_status("running first-run init …", level="info")

        def _work() -> None:
            import argparse as _argparse
            from darkcat import cli as _cli
            try:
                ns = _argparse.Namespace(no_probe=False)
                _cli.cmd_init(self.cfg, ns)
                self._queue.put(("init_done", True, None))
            except Exception as exc:  # noqa: BLE001 — never crash the GUI
                self._queue.put(("init_done", False, str(exc)))

        threading.Thread(target=_work, daemon=True).start()

    def _show_doctor(self) -> None:
        """Modal dialog showing the same health-check matrix that
        ``darkcat doctor`` prints. Uses ``cli.doctor_run`` so the CLI and GUI
        stay in lockstep — adding a new check only needs editing once.
        """
        from darkcat.cli import doctor_run

        rows = doctor_run(self.cfg)
        glyph = {"ok": "✓", "warn": "⚠", "fail": "✗"}
        color = {"ok": NEON_GREEN, "warn": "#ffb000", "fail": "#ff1a4b"}

        dlg = tk.Toplevel(self.root)
        dlg.title("darkcat — doctor")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        try:
            self.root.update_idletasks()
            px = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - 620) // 2)
            py = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - 420) // 3)
            dlg.geometry(f"620x420+{px}+{py}")
        except tk.TclError:
            dlg.geometry("620x420")

        body = tk.Frame(dlg, bg=DEEP_BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text="Health checks",
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 13, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        fails = sum(1 for level, *_ in rows if level == "fail")
        warns = sum(1 for level, *_ in rows if level == "warn")

        for level, label, detail, fix in rows:
            row = tk.Frame(body, bg=DEEP_BG)
            row.pack(anchor="w", fill="x", pady=2)
            tk.Label(
                row, text=glyph[level],
                fg=color[level], bg=DEEP_BG,
                font=(self._mono, 12, "bold"),
                width=2,
            ).pack(side="left")
            cell = tk.Frame(row, bg=DEEP_BG)
            cell.pack(side="left", fill="x", expand=True)
            tk.Label(
                cell, text=label,
                fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 10, "bold"),
            ).pack(anchor="w")
            tk.Label(
                cell, text=detail,
                fg=NEON_GREEN, bg=DEEP_BG, font=(self._mono, 9),
                wraplength=540, justify="left",
            ).pack(anchor="w")
            if fix:
                tk.Label(
                    cell, text=f"→ {fix}",
                    fg=DIM_FG, bg=DEEP_BG, font=(self._mono, 9, "italic"),
                    wraplength=540, justify="left",
                ).pack(anchor="w")

        if fails:
            summary = (
                f"✗ {fails} check(s) failed — fix the items above and re-open Help → Run doctor."
            )
            summary_color = "#ff1a4b"
        elif warns:
            summary = f"⚠ {warns} warning(s) — darkcat works, but some features will be limited."
            summary_color = "#ffb000"
        else:
            summary = "✓ all checks passed."
            summary_color = NEON_GREEN
        tk.Label(
            body, text=summary,
            fg=summary_color, bg=DEEP_BG, font=(self._mono, 10, "bold"),
        ).pack(anchor="w", pady=(10, 0))

        ttk.Button(
            body, text="Close", command=dlg.destroy, style="Run.TButton",
        ).pack(pady=(14, 0))

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.bind("<Return>", lambda _e: dlg.destroy())
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.grab_set()
        dlg.focus_set()

    def _show_shortcuts(self) -> None:
        """Modal listing every GUI keyboard shortcut grouped by intent.

        Mirrors the TUI's KeymapScreen so the two frontends stay in sync —
        users that switch between them don't have to relearn the keymap.
        Bound to F2 and reachable from Help → Keyboard shortcuts.
        """
        groups: list[tuple[str, list[tuple[str, str]]]] = [
            ("Run a crawl", [
                ("Enter (in any form field)", "Start a crawl with the current values"),
                ("Ctrl+C",                    "Abort the running crawl"),
                ("F5",                        "Refresh the results table"),
                ("Ctrl+R",                    "Re-probe transports (rescan pills)"),
            ]),
            ("Inspect a result", [
                ("Right-click a row",   "Copy URL · Fetch · Mirrors · History"),
                ("Ctrl+I",              "Show database statistics"),
                ("Ctrl+E",              "Export current results to .txt"),
            ]),
            ("Search & fetch", [
                ("Type in 'search' + Enter",   "FTS5 search across crawled pages"),
                ("Type in 'fetch URL' + Enter","Fetch one URL through the right transport"),
            ]),
            ("Help & info", [
                ("F1",       "About darkcat (logo, version, license, source)"),
                ("F2",       "This keyboard-shortcuts dialog"),
                ("Ctrl+L",   "Clear the log panel"),
                ("Ctrl+Q",   "Quit darkcat"),
            ]),
        ]

        dlg = tk.Toplevel(self.root)
        dlg.title("darkcat — keyboard shortcuts")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        try:
            self.root.update_idletasks()
            px = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - 520) // 2)
            py = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - 480) // 3)
            dlg.geometry(f"520x480+{px}+{py}")
        except tk.TclError:
            dlg.geometry("520x480")

        body = tk.Frame(dlg, bg=DEEP_BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text="Keyboard shortcuts",
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 13, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        for group_title, items in groups:
            tk.Label(
                body, text=group_title,
                fg=NEON_PINK, bg=DEEP_BG, font=(self._mono, 10, "bold"),
            ).pack(anchor="w", pady=(8, 2))
            for keys, desc in items:
                row = tk.Frame(body, bg=DEEP_BG)
                row.pack(anchor="w", fill="x")
                tk.Label(
                    row, text=keys,
                    fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 9),
                    width=30, anchor="w", justify="left",
                ).pack(side="left")
                tk.Label(
                    row, text=desc,
                    fg=NEON_GREEN, bg=DEEP_BG, font=(self._mono, 9),
                    anchor="w", justify="left",
                ).pack(side="left")

        ttk.Button(
            body, text="Close", command=dlg.destroy, style="Run.TButton",
        ).pack(pady=(14, 0))

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.bind("<Return>", lambda _e: dlg.destroy())
        dlg.bind("<F2>",     lambda _e: dlg.destroy())
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.grab_set()
        dlg.focus_set()

    def _show_about(self) -> None:
        """Modal "About darkcat" — 256×256 logo + version + license + URL.

        Bound to F1. Closes on Esc / Enter / OK button. The PNG goes through
        the canonical ``darkcat_logo()`` helper so the same master ships in
        the wheel that GUI/TUI/CLI all read from.
        """
        dlg = tk.Toplevel(self.root)
        dlg.title("About darkcat")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        try:
            self.root.update_idletasks()
            px = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - 380) // 2)
            py = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - 540) // 3)
            dlg.geometry(f"380x540+{px}+{py}")
        except tk.TclError:
            dlg.geometry("380x540")

        body = tk.Frame(dlg, bg=DEEP_BG, padx=20, pady=16)
        body.pack(fill="both", expand=True)

        try:
            png = darkcat_logo(256)
            if png.exists():
                img = tk.PhotoImage(file=str(png))
                dlg._dc_logo = img  # keep reference; Tk drops on GC otherwise
                tk.Label(body, image=img, bg=DEEP_BG, bd=0).pack(pady=(4, 12))
        except tk.TclError:
            pass

        tk.Label(
            body, text=f"darkcat {__version__}",
            fg=NEON_GREEN, bg=DEEP_BG, font=(self._mono, 14, "bold"),
        ).pack()
        tk.Label(
            body, text=TAGLINE,
            fg=DIM_FG, bg=DEEP_BG, font=(self._mono, 10, "italic"),
        ).pack(pady=(2, 14))

        meta = tk.Frame(body, bg=DEEP_BG)
        meta.pack()
        for label, value, value_fg in (
            ("License",    __license__,                 NEON_GREEN),
            ("Source",     __url__,                     NEON_CYAN),
            ("Maintainer", "Overdrive (Borja Tarraso)", NEON_GREEN),
        ):
            row = tk.Frame(meta, bg=DEEP_BG)
            row.pack(anchor="w", pady=1)
            tk.Label(
                row, text=f"{label}: ",
                fg=DIM_FG, bg=DEEP_BG, font=(self._mono, 9),
            ).pack(side="left")
            tk.Label(
                row, text=value,
                fg=value_fg, bg=DEEP_BG, font=(self._mono, 9),
            ).pack(side="left")

        ttk.Button(
            body, text="Close", command=dlg.destroy, style="Run.TButton",
        ).pack(pady=(16, 0))

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.bind("<Return>", lambda _e: dlg.destroy())
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        dlg.grab_set()
        dlg.focus_set()

    def _show_identity(self) -> None:
        """Modal Identity-vault browser — list / new / confirm / burn / launch.

        Mirrors the TUI's IdentityScreen so the four frontends stay in
        sync. Encrypted vaults are read-only here; the dialog shows a
        notice and steers the operator at the CLI for those.

        Buttons:
          • New         — generate a fresh persona for a chosen provider
                          (e.g. ProtonMail). Asks for provider / transport /
                          purpose, then writes it to the vault.
          • Launch signup — open the selected persona's signup URL through
                          its recorded transport (Tor Browser if installed,
                          otherwise system browser with HTTP(S)_PROXY set).
          • Confirm     — mark a persona ``confirmed`` after manual signup.
          • Burn        — mark a persona ``burned``; the slot frees up.
          • Refresh / Close.
        """
        import argparse as _argparse
        import time as _time

        from darkcat import personas as pv
        from darkcat.identity import IdentityVault, invoke_cli_capturing

        dlg = tk.Toplevel(self.root)
        dlg.title("darkcat — identities")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(self.root)
        try:
            self.root.update_idletasks()
            px = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - 820) // 2)
            py = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - 520) // 3)
            dlg.geometry(f"820x520+{px}+{py}")
        except tk.TclError:
            dlg.geometry("820x520")

        # Treeview dark theme — applied per-dialog so we don't pollute
        # other Treeviews in the GUI. Names are unique to avoid clashing
        # with the global ttk styles set in _apply_dark_theme.
        style = ttk.Style(dlg)
        style.configure(
            "Identity.Treeview",
            background=PANEL_BG, fieldbackground=PANEL_BG,
            foreground=NEON_GREEN, bordercolor=DARK_GREEN,
            lightcolor=DARK_GREEN, darkcolor=DARK_GREEN,
            font=(self._mono, 9), rowheight=22,
        )
        style.configure(
            "Identity.Treeview.Heading",
            background=DEEP_BG, foreground=NEON_PINK,
            font=(self._mono, 9, "bold"),
        )
        style.map(
            "Identity.Treeview",
            background=[("selected", "#1a0033")],
            foreground=[("selected", NEON_CYAN)],
        )

        body = tk.Frame(dlg, bg=DEEP_BG, padx=16, pady=12)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text="Identities",
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 13, "bold"),
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            body,
            text=("Create one persona per project, then click "
                  "'Launch signup' to open the provider's signup page "
                  "through Tor."),
            fg=DIM_FG, bg=DEEP_BG, font=(self._mono, 9),
            wraplength=780, justify="left",
        ).pack(anchor="w", pady=(0, 6))

        notice = tk.Label(
            body, text="", fg=AMBER, bg=DEEP_BG, font=(self._mono, 9),
        )
        notice.pack(anchor="w")

        cols = ("name", "provider", "status", "purpose", "created")
        tree = ttk.Treeview(
            body, columns=cols, show="headings", height=14,
            style="Identity.Treeview",
        )
        tree.heading("name",     text="NAME")
        tree.heading("provider", text="PROVIDER")
        tree.heading("status",   text="STATUS")
        tree.heading("purpose",  text="PURPOSE")
        tree.heading("created",  text="CREATED")
        tree.column("name",     width=200, anchor="w")
        tree.column("provider", width=120, anchor="w")
        tree.column("status",   width=90,  anchor="w")
        tree.column("purpose",  width=220, anchor="w")
        tree.column("created",  width=110, anchor="w")
        tree.pack(fill="both", expand=True, pady=(8, 8))

        # Holds the loaded vault + cached passphrase. ``passphrase`` is
        # set after the operator unlocks an encrypted vault, then threaded
        # into ``_run`` via ``DARKCAT_VAULT_PASSPHRASE`` so the CLI handler
        # can re-open the same file without re-prompting on every action.
        state: dict[str, object] = {
            "vault": None, "encrypted": False, "passphrase": None,
        }

        def _vault_is_encrypted() -> bool:
            path = pv.vault_path()
            return path.exists() and path.suffix == ".gpg"

        def _load_vault() -> Optional[IdentityVault]:
            path = pv.vault_path()
            state["encrypted"] = path.exists() and path.suffix == ".gpg"
            try:
                inner = pv.Vault(path=path, passphrase=state["passphrase"])
            except RuntimeError as e:
                notice.configure(text=f"could not open vault: {e}")
                return None
            return IdentityVault(inner)

        def _unlock_then(callback) -> None:
            """Prompt for a passphrase if the vault is encrypted and we
            don't yet have one cached, verify it opens the file, then run
            ``callback``. Wrong-passphrase loops re-prompt until cancel."""
            if not _vault_is_encrypted() or state["passphrase"] is not None:
                callback()
                return
            pw = self._open_passphrase_dialog(dlg, "Vault is encrypted")
            if pw is None:
                notice.configure(text="vault locked — close and reopen to retry")
                return
            try:
                pv.Vault(path=pv.vault_path(), passphrase=pw)
            except RuntimeError as e:
                messagebox.showerror(
                    "darkcat — vault locked",
                    f"wrong passphrase: {e}", parent=dlg,
                )
                _unlock_then(callback)
                return
            state["passphrase"] = pw
            callback()

        def _refresh() -> None:
            for iid in tree.get_children():
                tree.delete(iid)
            v = _load_vault()
            state["vault"] = v
            if v is None:
                return
            notice.configure(text="")
            for p in v.all_identities():
                created = _time.strftime("%Y-%m-%d", _time.localtime(p.created_at))
                tree.insert(
                    "", "end", iid=p.name,
                    values=(p.name, p.provider or "-", p.status,
                            p.purpose_tag or "-", created),
                )

        def _selected_name() -> Optional[str]:
            sel = tree.selection()
            return sel[0] if sel else None

        def _last_error_line(stderr: str) -> str:
            for line in reversed(stderr.splitlines()):
                line = line.strip()
                if line:
                    return line
            return "operation failed"

        def _run(ns) -> tuple[int, str, str]:
            """Invoke ``cmd_identity`` with stdout / stderr captured. The
            cached vault passphrase (if any) is exposed to the handler
            through ``DARKCAT_VAULT_PASSPHRASE`` so encrypted vaults work
            end-to-end without a second prompt per action."""
            import os as _os
            saved = _os.environ.get("DARKCAT_VAULT_PASSPHRASE")
            if state["passphrase"] is not None:
                _os.environ["DARKCAT_VAULT_PASSPHRASE"] = state["passphrase"]
            try:
                return invoke_cli_capturing(self.cfg, ns)
            except SystemExit as e:
                return (int(e.code) if isinstance(e.code, int) else 2, "", "")
            except Exception as e:
                return (2, "", f"{type(e).__name__}: {e}")
            finally:
                if state["passphrase"] is not None:
                    if saved is None:
                        _os.environ.pop("DARKCAT_VAULT_PASSPHRASE", None)
                    else:
                        _os.environ["DARKCAT_VAULT_PASSPHRASE"] = saved

        def _new_identity() -> None:
            if state["vault"] is None:
                messagebox.showinfo(
                    "darkcat — identity",
                    "Vault is unavailable — check ~/.local/share/darkcat.",
                    parent=dlg,
                )
                return
            payload = self._open_identity_new_dialog(dlg)
            if payload is None:
                return
            ns = _argparse.Namespace(
                cmd="identity", action="new",
                provider=payload["provider"],
                transport=payload["transport"],
                purpose=payload["purpose"] or None,
                name=None, instance=payload.get("instance"),
                recovery_email=None,
                cap=None, force=False, password_length=24,
                proxy_url=None, pin_to=None,
                launch=False, json=False,
            )
            rc, out, err = _run(ns)
            if rc == 0:
                messagebox.showinfo(
                    "darkcat — identity created",
                    out + "\nNext: select the row and click "
                    "'Launch signup' to open the signup page through Tor. "
                    "After completing the signup, click 'Confirm'.",
                    parent=dlg,
                )
            else:
                messagebox.showerror(
                    "darkcat — identity", _last_error_line(err),
                    parent=dlg,
                )
            _refresh()

        def _confirm_selected() -> None:
            name = _selected_name()
            if not name:
                messagebox.showinfo(
                    "darkcat — identity",
                    "Select a row first.",
                    parent=dlg,
                )
                return
            if state["vault"] is None:
                return
            ns = _argparse.Namespace(cmd="identity", action="confirm", name=name)
            rc, _out, err = _run(ns)
            if rc != 0:
                messagebox.showerror(
                    "darkcat — confirm", _last_error_line(err),
                    parent=dlg,
                )
            _refresh()

        def _burn_selected() -> None:
            name = _selected_name()
            if not name:
                messagebox.showinfo(
                    "darkcat — identity",
                    "Select a row first.",
                    parent=dlg,
                )
                return
            if state["vault"] is None:
                return
            if not messagebox.askyesno(
                "darkcat — burn identity",
                f"Mark {name!r} as burned? The slot stops counting against "
                "the per-provider cap, but the row stays in the vault for "
                "audit.",
                parent=dlg,
            ):
                return
            ns = _argparse.Namespace(
                cmd="identity", action="burn", name=name, note=None,
            )
            rc, _out, err = _run(ns)
            if rc != 0:
                messagebox.showerror(
                    "darkcat — burn", _last_error_line(err),
                    parent=dlg,
                )
            _refresh()

        def _launch_selected() -> None:
            name = _selected_name()
            if not name:
                messagebox.showinfo(
                    "darkcat — identity",
                    "Select a row first, then click 'Launch signup' to open "
                    "its signup page.",
                    parent=dlg,
                )
                return
            if state["vault"] is None:
                return
            # capture=False — the CLI capture path is interactive
            # readline, which deadlocks under a Tk modal. We open the
            # edit dialog below instead so the operator can write back
            # the real handle / recovery codes through the GUI.
            ns = _argparse.Namespace(
                cmd="identity", action="launch", name=name,
                no_spawn=False, capture=False,
            )
            rc, out, err = _run(ns)
            if rc != 0:
                messagebox.showerror(
                    "darkcat — launch", _last_error_line(err),
                    parent=dlg,
                )
                return
            # Render the launch block so the operator can read the
            # provider-specific checklist while completing the form.
            self._open_result_dialog(
                dlg, f"Signup launched — {name}", out or "(launched)",
            )
            # Then pop the edit form pre-loaded with the persona row so
            # the values shown once during signup (handle, recovery
            # codes, recovery email) survive the session.
            vault = state["vault"]
            if vault is None:
                return
            p = vault.inner.get(name)
            if p is None:
                _refresh()
                return
            payload = self._open_identity_edit_dialog(dlg, p)
            if not payload:
                return
            action = payload.pop("_action", "edit")
            if action == "rotate-password":
                # The launch flow doesn't go through rotate-password,
                # but the dialog allows it; honour the operator's
                # explicit choice.
                ns_r = _argparse.Namespace(
                    cmd="identity", action="rotate-password",
                    name=name, length=24, print_new=False,
                )
                _run(ns_r)
                _refresh()
                return
            ns_e = _argparse.Namespace(
                cmd="identity", action="edit", name=name,
                handle=payload.get("handle"),
                email=payload.get("email"),
                recovery=payload.get("recovery"),
                recovery_email=payload.get("recovery_email"),
                recovery_codes=payload.get("recovery_codes"),
                recovery_codes_replace=False,
                display_name=payload.get("display_name"),
                notes=payload.get("notes"),
            )
            rc, _o, err = _run(ns_e)
            if rc != 0:
                messagebox.showerror(
                    "darkcat — capture", _last_error_line(err),
                    parent=dlg,
                )
            _refresh()

        def _edit_selected() -> None:
            name = _selected_name()
            if not name:
                messagebox.showinfo(
                    "darkcat — identity",
                    "Select a row first, then click 'Edit' to update its "
                    "credentials.",
                    parent=dlg,
                )
                return
            vault = state["vault"]
            if vault is None:
                return
            p = vault.inner.get(name)
            if p is None:
                messagebox.showerror(
                    "darkcat — edit",
                    f"{name!r} is no longer in the vault.",
                    parent=dlg,
                )
                _refresh()
                return
            payload = self._open_identity_edit_dialog(dlg, p)
            if payload is None:
                return
            action = payload.pop("_action", "edit")
            if action == "rotate-password":
                ns = _argparse.Namespace(
                    cmd="identity", action="rotate-password",
                    name=name, length=24, print_new=False,
                )
                rc, out, err = _run(ns)
                if rc == 0:
                    messagebox.showinfo(
                        "darkcat — password rotated",
                        out + "\nUse 'identity show --reveal' from the CLI "
                        "to retrieve the new password.",
                        parent=dlg,
                    )
                else:
                    messagebox.showerror(
                        "darkcat — rotate", _last_error_line(err),
                        parent=dlg,
                    )
                _refresh()
                return
            ns = _argparse.Namespace(
                cmd="identity", action="edit", name=name,
                handle=payload.get("handle"),
                email=payload.get("email"),
                recovery=payload.get("recovery"),
                recovery_email=payload.get("recovery_email"),
                recovery_codes=payload.get("recovery_codes"),
                recovery_codes_replace=False,
                display_name=payload.get("display_name"),
                notes=payload.get("notes"),
            )
            rc, out, err = _run(ns)
            if rc == 0:
                messagebox.showinfo(
                    "darkcat — identity updated", out, parent=dlg,
                )
            else:
                messagebox.showerror(
                    "darkcat — edit", _last_error_line(err),
                    parent=dlg,
                )
            _refresh()

        def _show_selected() -> None:
            name = _selected_name()
            if not name:
                messagebox.showinfo(
                    "darkcat — identity",
                    "Select a row first, then click 'Show' to view its "
                    "credentials.",
                    parent=dlg,
                )
                return
            if state["vault"] is None:
                return
            reveal = self._open_confirm_reveal_dialog(dlg, name)
            ns = _argparse.Namespace(
                cmd="identity", action="show", name=name,
                reveal=reveal, json=False,
            )
            rc, out, err = _run(ns)
            if rc != 0:
                messagebox.showerror(
                    "darkcat — show", _last_error_line(err),
                    parent=dlg,
                )
                return
            title = (f"{name} (revealed — handle with care)"
                     if reveal else
                     f"{name} (masked — click Show again to reveal)")
            self._open_result_dialog(dlg, title, out or "(no data)")

        def _link_or_unlink(verb: str) -> None:
            def _go() -> None:
                v = state["vault"]
                if v is None:
                    return
                names = [
                    p.name for p in v.inner.personas
                    if p.provider  # identity rows only
                ]
                if len(names) < 2:
                    messagebox.showinfo(
                        f"darkcat — {verb}",
                        "Need at least two identities in the vault first.",
                        parent=dlg,
                    )
                    return
                payload = self._open_link_dialog(
                    dlg, names,
                    default_child=_selected_name(),
                    verb=verb.capitalize(),
                )
                if payload is None:
                    return
                ns = _argparse.Namespace(
                    cmd="identity", action=verb,
                    parent=payload["parent"], child=payload["child"],
                )
                rc, _out, err = _run(ns)
                if rc != 0:
                    messagebox.showerror(
                        f"darkcat — {verb}", _last_error_line(err),
                        parent=dlg,
                    )
                else:
                    messagebox.showinfo(
                        f"darkcat — {verb}",
                        f"{verb}ed {payload['parent']} → {payload['child']}",
                        parent=dlg,
                    )
            _unlock_then(_go)

        def _link_selected() -> None:
            _link_or_unlink("link")

        def _unlink_selected() -> None:
            _link_or_unlink("unlink")

        btns = tk.Frame(body, bg=DEEP_BG)
        btns.pack(fill="x")
        ttk.Button(btns, text="New",            command=_new_identity,     style="Run.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Launch signup",  command=_launch_selected,  style="Run.TButton").pack(side="left", padx=6)
        ttk.Button(btns, text="Show",           command=_show_selected,    style="Run.TButton").pack(side="left", padx=6)
        ttk.Button(btns, text="Confirm",        command=_confirm_selected, style="Run.TButton").pack(side="left", padx=6)
        ttk.Button(btns, text="Edit",           command=_edit_selected,    style="Run.TButton").pack(side="left", padx=6)
        ttk.Button(btns, text="Link",           command=_link_selected,    style="Run.TButton").pack(side="left", padx=6)
        ttk.Button(btns, text="Unlink",         command=_unlink_selected,  style="Run.TButton").pack(side="left", padx=6)
        ttk.Button(btns, text="Burn",           command=_burn_selected,    style="Run.TButton").pack(side="left", padx=6)
        ttk.Button(btns, text="Refresh",        command=_refresh,          style="Run.TButton").pack(side="left", padx=6)
        ttk.Button(btns, text="Close",          command=dlg.destroy,       style="Run.TButton").pack(side="right")

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        dlg.focus_set()
        _unlock_then(_refresh)

    def _open_passphrase_dialog(
        self, parent: tk.Toplevel, prompt: str = "Vault passphrase",
    ) -> Optional[str]:
        """Modal passphrase prompt for an encrypted vault. Returns the
        typed string on submit, or ``None`` on cancel. Used by the
        identity browser to gate access to vault.gpg without forcing
        the operator out to the CLI."""
        dlg = tk.Toplevel(parent)
        dlg.title("darkcat — vault passphrase")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(parent)
        dlg.resizable(False, False)
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx() + max(0, (parent.winfo_width() - 380) // 2)
            py = parent.winfo_rooty() + max(0, (parent.winfo_height() - 180) // 3)
            dlg.geometry(f"380x180+{px}+{py}")
        except tk.TclError:
            dlg.geometry("380x180")

        body = tk.Frame(dlg, bg=DEEP_BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text=prompt,
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 12, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(body, text="Passphrase", fg=DIM_FG, bg=DEEP_BG,
                 font=(self._mono, 9)).pack(anchor="w")
        pw_var = tk.StringVar()
        entry = tk.Entry(
            body, textvariable=pw_var, show="*",
            bg=PANEL_BG, fg=NEON_GREEN,
            insertbackground=NEON_GREEN,
            relief="flat", font=(self._mono, 11),
        )
        entry.pack(fill="x", pady=(2, 10))

        result: dict = {"value": None}

        def _submit(_e=None) -> None:
            v = pw_var.get()
            if not v:
                return
            result["value"] = v
            dlg.destroy()

        def _cancel(_e=None) -> None:
            result["value"] = None
            dlg.destroy()

        btns = tk.Frame(body, bg=DEEP_BG)
        btns.pack(fill="x")
        ttk.Button(btns, text="Unlock", command=_submit,
                   style="Run.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Cancel", command=_cancel,
                   style="Run.TButton").pack(side="left", padx=6)

        dlg.bind("<Return>", _submit)
        dlg.bind("<Escape>", _cancel)
        dlg.protocol("WM_DELETE_WINDOW", _cancel)
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        entry.focus_set()
        parent.wait_window(dlg)
        return result["value"]

    def _open_result_dialog(
        self, parent: tk.Toplevel, title: str, body: str,
    ) -> None:
        """Scrollable read-only dump of captured CLI stdout — used after
        ``show`` / ``launch`` so multi-line tables and revealed secrets
        survive intact rather than being truncated to a messagebox."""
        dlg = tk.Toplevel(parent)
        dlg.title(f"darkcat — {title}")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(parent)
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx() + max(0, (parent.winfo_width() - 720) // 2)
            py = parent.winfo_rooty() + max(0, (parent.winfo_height() - 460) // 3)
            dlg.geometry(f"720x460+{px}+{py}")
        except tk.TclError:
            dlg.geometry("720x460")

        frame = tk.Frame(dlg, bg=DEEP_BG, padx=14, pady=12)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame, text=title,
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 12, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        text_frame = tk.Frame(frame, bg=DEEP_BG)
        text_frame.pack(fill="both", expand=True)
        text = tk.Text(
            text_frame, wrap="none",
            bg=PANEL_BG, fg=NEON_GREEN,
            insertbackground=NEON_GREEN,
            relief="flat", font=(self._mono, 10),
        )
        ysb = ttk.Scrollbar(text_frame, orient="vertical",
                            command=text.yview)
        xsb = ttk.Scrollbar(text_frame, orient="horizontal",
                            command=text.xview)
        text.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        text.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        text.insert("1.0", body or "(no output)")
        text.configure(state="disabled")

        btns = tk.Frame(frame, bg=DEEP_BG)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Close", command=dlg.destroy,
                   style="Run.TButton").pack(side="right")

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        dlg.focus_set()
        parent.wait_window(dlg)

    def _open_confirm_reveal_dialog(
        self, parent: tk.Toplevel, name: str,
    ) -> bool:
        """Two-button modal: ``Reveal`` shows the password + recovery
        codes in plaintext, ``Masked`` keeps them dotted. Closing the
        window is treated as ``Masked`` — never accidentally reveal."""
        dlg = tk.Toplevel(parent)
        dlg.title("darkcat — show identity")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(parent)
        dlg.resizable(False, False)
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx() + max(0, (parent.winfo_width() - 420) // 2)
            py = parent.winfo_rooty() + max(0, (parent.winfo_height() - 200) // 3)
            dlg.geometry(f"420x200+{px}+{py}")
        except tk.TclError:
            dlg.geometry("420x200")

        body = tk.Frame(dlg, bg=DEEP_BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text=f"Show {name}",
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 12, "bold"),
        ).pack(anchor="w", pady=(0, 6))
        tk.Label(
            body,
            text=("Reveal password and recovery codes in plaintext on "
                  "screen? Choose 'Masked' if anyone is shoulder-surfing."),
            fg=DIM_FG, bg=DEEP_BG, font=(self._mono, 9),
            wraplength=380, justify="left",
        ).pack(anchor="w", pady=(0, 10))

        result: dict = {"value": False}

        def _reveal() -> None:
            result["value"] = True
            dlg.destroy()

        def _masked() -> None:
            result["value"] = False
            dlg.destroy()

        btns = tk.Frame(body, bg=DEEP_BG)
        btns.pack(fill="x")
        ttk.Button(btns, text="Masked", command=_masked,
                   style="Run.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Reveal", command=_reveal,
                   style="Run.TButton").pack(side="left", padx=6)

        dlg.bind("<Escape>", lambda _e: _masked())
        dlg.bind("<y>",      lambda _e: _reveal())
        dlg.bind("<n>",      lambda _e: _masked())
        dlg.protocol("WM_DELETE_WINDOW", _masked)
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        dlg.focus_set()
        parent.wait_window(dlg)
        return result["value"]

    def _open_link_dialog(
        self, parent: tk.Toplevel, names: list,
        default_child: Optional[str] = None, verb: str = "Link",
    ) -> Optional[dict]:
        """Sub-modal: pick parent + child personas for link / unlink.

        Returns ``{'parent', 'child'}`` on submit, ``None`` on cancel.
        Parent = the recovery account (ProtonMail, etc.); child = the
        protected one (Reddit, etc.). Errors out on identical picks."""
        dlg = tk.Toplevel(parent)
        dlg.title(f"darkcat — {verb.lower()} identities")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(parent)
        dlg.resizable(False, False)
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx() + max(0, (parent.winfo_width() - 460) // 2)
            py = parent.winfo_rooty() + max(0, (parent.winfo_height() - 260) // 3)
            dlg.geometry(f"460x260+{px}+{py}")
        except tk.TclError:
            dlg.geometry("460x260")

        body = tk.Frame(dlg, bg=DEEP_BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text=f"{verb} identities",
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 12, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        tk.Label(
            body,
            text=("Parent = the recovery account (e.g. ProtonMail). "
                  "Child = the protected one (e.g. Reddit)."),
            fg=DIM_FG, bg=DEEP_BG, font=(self._mono, 9),
            wraplength=420, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(body, text="Parent", fg=DIM_FG, bg=DEEP_BG,
                 font=(self._mono, 9)).pack(anchor="w")
        parent_var = tk.StringVar(value=names[0] if names else "")
        parent_box = ttk.Combobox(
            body, textvariable=parent_var, values=list(names),
            state="readonly",
        )
        parent_box.pack(fill="x", pady=(2, 8))

        tk.Label(body, text="Child", fg=DIM_FG, bg=DEEP_BG,
                 font=(self._mono, 9)).pack(anchor="w")
        child_default = default_child if default_child in names else (
            names[1] if len(names) > 1 else (names[0] if names else "")
        )
        child_var = tk.StringVar(value=child_default)
        child_box = ttk.Combobox(
            body, textvariable=child_var, values=list(names),
            state="readonly",
        )
        child_box.pack(fill="x", pady=(2, 10))

        result: dict = {"value": None}

        def _submit() -> None:
            par = parent_var.get()
            ch = child_var.get()
            if not par or not ch or par == ch:
                messagebox.showerror(
                    "darkcat — " + verb.lower(),
                    "Pick two different identities.",
                    parent=dlg,
                )
                return
            result["value"] = {"parent": par, "child": ch}
            dlg.destroy()

        def _cancel() -> None:
            result["value"] = None
            dlg.destroy()

        btns = tk.Frame(body, bg=DEEP_BG)
        btns.pack(fill="x")
        ttk.Button(btns, text=verb, command=_submit,
                   style="Run.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Cancel", command=_cancel,
                   style="Run.TButton").pack(side="left", padx=6)

        dlg.bind("<Return>", lambda _e: _submit())
        dlg.bind("<Escape>", lambda _e: _cancel())
        dlg.protocol("WM_DELETE_WINDOW", _cancel)
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        dlg.focus_set()
        parent.wait_window(dlg)
        return result["value"]

    def _open_identity_new_dialog(
        self, parent: tk.Toplevel,
    ) -> Optional[dict]:
        """Sub-modal collecting provider / instance / transport / purpose.

        Returns ``{'provider', 'instance', 'transport', 'purpose'}`` on
        submit (``instance`` may be ``None`` for single-host providers),
        or ``None`` on cancel. Blocks until dismissed (Tk ``wait_window``).
        """
        from darkcat.identity import providers as provreg
        provreg.load_all()
        provider_rows = sorted(provreg.registered(), key=lambda x: x.slug)
        provider_labels = [
            f"{p.slug} — {p.display_name} ({p.category})"
            for p in provider_rows
        ]
        profiles_by_slug = {p.slug: p for p in provider_rows}

        dlg = tk.Toplevel(parent)
        dlg.title("darkcat — new identity")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(parent)
        dlg.resizable(False, False)
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx() + max(0, (parent.winfo_width() - 460) // 2)
            py = parent.winfo_rooty() + max(0, (parent.winfo_height() - 330) // 3)
            dlg.geometry(f"460x330+{px}+{py}")
        except tk.TclError:
            dlg.geometry("460x330")

        body = tk.Frame(dlg, bg=DEEP_BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text="New identity",
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 12, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        tk.Label(body, text="Provider", fg=DIM_FG, bg=DEEP_BG,
                 font=(self._mono, 9)).pack(anchor="w")
        provider_var = tk.StringVar(value=provider_labels[0] if provider_labels else "")
        provider_box = ttk.Combobox(
            body, textvariable=provider_var, values=provider_labels,
            state="readonly",
        )
        provider_box.pack(fill="x", pady=(0, 6))

        tk.Label(body, text="Instance (host)", fg=DIM_FG, bg=DEEP_BG,
                 font=(self._mono, 9)).pack(anchor="w")
        instance_var = tk.StringVar(value="(provider default)")
        instance_box = ttk.Combobox(
            body, textvariable=instance_var,
            values=["(provider default)"], state="readonly",
        )
        instance_box.pack(fill="x", pady=(0, 6))

        def _slug_from_label(label: str) -> str:
            return label.split(" — ", 1)[0] if " — " in label else label

        def _refresh_instances(*_args) -> None:
            slug = _slug_from_label(provider_var.get())
            prof = profiles_by_slug.get(slug)
            if prof is None or not prof.instances:
                instance_box.configure(values=["(provider default / N/A)"])
                instance_var.set("(provider default / N/A)")
                return
            opts = ["(provider default)"]
            for suffix, _url, note in prof.instances:
                label = f"{suffix} — {note}" if note else suffix
                opts.append(label)
            instance_box.configure(values=opts)
            instance_var.set(opts[0])

        provider_box.bind("<<ComboboxSelected>>", _refresh_instances)
        _refresh_instances()

        tk.Label(body, text="Transport", fg=DIM_FG, bg=DEEP_BG,
                 font=(self._mono, 9)).pack(anchor="w")
        transport_var = tk.StringVar(value="tor")
        ttk.Combobox(
            body, textvariable=transport_var,
            values=["tor", "i2p", "proxy"], state="readonly",
        ).pack(fill="x", pady=(0, 6))

        tk.Label(body, text="Purpose tag (optional)", fg=DIM_FG, bg=DEEP_BG,
                 font=(self._mono, 9)).pack(anchor="w")
        purpose_var = tk.StringVar(value="")
        tk.Entry(
            body, textvariable=purpose_var,
            bg=PANEL_BG, fg=NEON_GREEN, insertbackground=NEON_GREEN,
            relief="flat", highlightthickness=1,
            highlightbackground=DARK_GREEN, highlightcolor=NEON_CYAN,
        ).pack(fill="x", pady=(0, 10))

        result: dict[str, Optional[str]] = {}

        def _submit() -> None:
            slug = _slug_from_label(provider_var.get())
            if not slug:
                return
            inst_label = instance_var.get()
            instance: Optional[str]
            if inst_label.startswith("(provider default"):
                instance = None
            else:
                instance = inst_label.split(" — ", 1)[0]
            result["provider"]  = slug
            result["instance"]  = instance
            result["transport"] = transport_var.get() or "tor"
            result["purpose"]   = purpose_var.get().strip() or None
            dlg.destroy()

        def _cancel() -> None:
            dlg.destroy()

        btns = tk.Frame(body, bg=DEEP_BG)
        btns.pack(fill="x", pady=(4, 0))
        ttk.Button(btns, text="Create", command=_submit, style="Run.TButton").pack(side="left")
        ttk.Button(btns, text="Cancel", command=_cancel, style="Run.TButton").pack(side="right")

        dlg.bind("<Return>", lambda _e: _submit())
        dlg.bind("<Escape>", lambda _e: _cancel())
        dlg.protocol("WM_DELETE_WINDOW", _cancel)
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        provider_box.focus_set()
        parent.wait_window(dlg)

        if "provider" not in result:
            return None
        return result

    def _open_identity_edit_dialog(
        self, parent: tk.Toplevel, persona,
    ) -> Optional[dict]:
        """Sub-modal that edits credential fields on an existing identity.

        Returns ``None`` on cancel. On submit, returns a dict whose keys
        line up 1:1 with ``identity edit`` CLI flags — only fields whose
        value actually changed are included. A ``Rotate password`` button
        short-circuits with ``{'_action': 'rotate-password'}`` so the
        caller can dispatch to the rotate-password handler instead.
        """
        dlg = tk.Toplevel(parent)
        dlg.title(f"darkcat — edit {persona.name}")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(parent)
        dlg.resizable(False, False)
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx() + max(0, (parent.winfo_width() - 520) // 2)
            py = parent.winfo_rooty() + max(0, (parent.winfo_height() - 480) // 3)
            dlg.geometry(f"520x480+{px}+{py}")
        except tk.TclError:
            dlg.geometry("520x480")

        body = tk.Frame(dlg, bg=DEEP_BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text=f"Edit credentials — {persona.name}",
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 12, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        tk.Label(
            body,
            text=("Leave a field unchanged to keep its current value. "
                  "Empty strings clear optional fields. New recovery codes "
                  "are appended (comma-separated)."),
            fg=DIM_FG, bg=DEEP_BG, font=(self._mono, 9),
            wraplength=480, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        def _field(label: str, initial: str, show: Optional[str] = None):
            tk.Label(body, text=label, fg=DIM_FG, bg=DEEP_BG,
                     font=(self._mono, 9)).pack(anchor="w")
            var = tk.StringVar(value=initial or "")
            kwargs = dict(
                textvariable=var,
                bg=PANEL_BG, fg=NEON_GREEN, insertbackground=NEON_GREEN,
                relief="flat", highlightthickness=1,
                highlightbackground=DARK_GREEN, highlightcolor=NEON_CYAN,
            )
            if show is not None:
                kwargs["show"] = show
            tk.Entry(body, **kwargs).pack(fill="x", pady=(0, 4))
            return var

        handle_var         = _field("Handle / username", persona.handle or "")
        email_var          = _field("Email", persona.email or "")
        recovery_email_var = _field("Recovery email", persona.recovery_email or "")
        display_name_var   = _field("Display name", persona.display_name or "")
        recovery_var       = _field("Recovery phrase / BIP-39", persona.recovery or "", show="*")
        codes_var          = _field(
            f"Add recovery codes (current: {len(persona.recovery_codes)}) — "
            "comma-separated",
            "",
        )
        notes_var          = _field("Notes", persona.notes or "")

        result: dict[str, object] = {}

        def _submit() -> None:
            def _diff(var, current):
                cur = current or ""
                new = var.get()
                return new if new != cur else None

            changes: dict[str, object] = {"_action": "edit"}
            v = _diff(handle_var, persona.handle)
            if v is not None: changes["handle"] = v
            v = _diff(email_var, persona.email)
            if v is not None: changes["email"] = v
            v = _diff(recovery_email_var, persona.recovery_email)
            if v is not None: changes["recovery_email"] = v
            v = _diff(display_name_var, persona.display_name)
            if v is not None: changes["display_name"] = v
            v = _diff(recovery_var, persona.recovery)
            if v is not None: changes["recovery"] = v
            v = _diff(notes_var, persona.notes)
            if v is not None: changes["notes"] = v
            codes_raw = codes_var.get().strip()
            if codes_raw:
                changes["recovery_codes"] = [
                    c.strip() for c in codes_raw.split(",") if c.strip()
                ]
            if len(changes) == 1:
                # Nothing changed apart from the action marker.
                dlg.destroy()
                return
            result.update(changes)
            dlg.destroy()

        def _rotate() -> None:
            result["_action"] = "rotate-password"
            dlg.destroy()

        def _cancel() -> None:
            dlg.destroy()

        btns = tk.Frame(body, bg=DEEP_BG)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Save",            command=_submit, style="Run.TButton").pack(side="left")
        ttk.Button(btns, text="Rotate password", command=_rotate, style="Run.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Cancel",          command=_cancel, style="Run.TButton").pack(side="right")

        dlg.bind("<Return>", lambda _e: _submit())
        dlg.bind("<Escape>", lambda _e: _cancel())
        dlg.protocol("WM_DELETE_WINDOW", _cancel)
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        dlg.focus_set()
        parent.wait_window(dlg)

        if not result:
            return None
        return result

    def _show_persona_add(self) -> None:
        """Modal 'Add mail persona' dialog with mail-provider preset picker.

        Wraps ``personas add NAME --mail-provider SLUG`` so an operator
        can drop in a Disroot / Mailfence / Proton-Bridge persona without
        memorising SMTP/IMAP host:port/TLS. Any explicit field they fill
        still wins over the preset (matches the CLI handler precedence).
        """
        import argparse as _argparse
        from darkcat import mail_providers as _mp
        from darkcat.identity import invoke_cli_capturing

        presets = _mp.all_presets()
        if not presets:
            messagebox.showerror(
                "darkcat — add persona",
                "No mail-provider presets registered.",
                parent=self.root,
            )
            return
        # "(none)" lets the operator fill site/notes manually if their
        # provider isn't in the curated list.
        preset_labels = ["(none — fill manually)"] + [
            f"{p.slug} — {p.description.split(';')[0]}"
            for p in presets
        ]
        preset_by_label = {preset_labels[0]: None}
        for label, p in zip(preset_labels[1:], presets):
            preset_by_label[label] = p

        dlg = tk.Toplevel(self.root)
        dlg.title("darkcat — add mail persona")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        try:
            self.root.update_idletasks()
            px = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - 560) // 2)
            py = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - 520) // 3)
            dlg.geometry(f"560x520+{px}+{py}")
        except tk.TclError:
            dlg.geometry("560x520")

        body = tk.Frame(dlg, bg=DEEP_BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text="Add mail persona",
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 13, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        tk.Label(
            body,
            text=("Pick a mail-provider preset and the SMTP/IMAP host, "
                  "port and TLS mode are filled in for you. Any field "
                  "you override still wins over the preset."),
            fg=DIM_FG, bg=DEEP_BG, font=(self._mono, 9),
            wraplength=520, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        def _field(label_text: str, *, password: bool = False,
                   default: str = "") -> tk.Entry:
            tk.Label(body, text=label_text, fg=DIM_FG, bg=DEEP_BG,
                     font=(self._mono, 9)).pack(anchor="w")
            var = tk.StringVar(value=default)
            kwargs = {"show": "*"} if password else {}
            entry = tk.Entry(
                body, textvariable=var,
                bg=PANEL_BG, fg=NEON_GREEN,
                insertbackground=NEON_GREEN,
                relief="flat", font=(self._mono, 10),
                **kwargs,
            )
            entry.pack(fill="x", pady=(2, 6))
            entry._dc_var = var  # type: ignore[attr-defined]
            return entry

        name_entry = _field("Name (unique persona id)")

        tk.Label(body, text="Mail provider", fg=DIM_FG, bg=DEEP_BG,
                 font=(self._mono, 9)).pack(anchor="w")
        preset_var = tk.StringVar(value=preset_labels[0])
        preset_box = ttk.Combobox(
            body, textvariable=preset_var, values=preset_labels,
            state="readonly",
        )
        preset_box.pack(fill="x", pady=(2, 6))

        handle_entry = _field("Handle (e.g. alice@disroot.org)")
        email_entry = _field("Email (optional)")
        password_entry = _field("Password (leave blank to autogenerate)",
                                password=True)
        network_entry = _field("Network override (optional)")
        site_entry = _field("Site override (optional — e.g. host:port)")
        notes_entry = _field("Notes override (optional)")

        gen_var = tk.BooleanVar(value=True)
        gen_chk = tk.Checkbutton(
            body, text="Auto-generate handle / password if blank",
            variable=gen_var,
            bg=DEEP_BG, fg=NEON_GREEN, selectcolor=PANEL_BG,
            activebackground=DEEP_BG, activeforeground=NEON_PINK,
            font=(self._mono, 9), borderwidth=0, highlightthickness=0,
        )
        gen_chk.pack(anchor="w", pady=(0, 8))

        def _on_preset_change(_e=None) -> None:
            label = preset_var.get()
            preset = preset_by_label.get(label)
            hint = ""
            if preset is not None and preset.handle_hint:
                hint = preset.handle_hint
            # Show the hint as a placeholder-style nudge in handle field
            # only when the field is empty (don't clobber operator input).
            if hint and not handle_entry._dc_var.get():  # type: ignore[attr-defined]
                # Stash the hint in the entry's tooltip-like state.
                pass

        preset_box.bind("<<ComboboxSelected>>", _on_preset_change)

        def _submit() -> None:
            name = name_entry._dc_var.get().strip()  # type: ignore[attr-defined]
            if not name:
                messagebox.showerror(
                    "darkcat — add persona",
                    "Persona name is required.",
                    parent=dlg,
                )
                return
            preset = preset_by_label.get(preset_var.get())
            ns = _argparse.Namespace(
                cmd="personas", action="add",
                name=name,
                network=network_entry._dc_var.get() or "",  # type: ignore[attr-defined]
                site=site_entry._dc_var.get() or "",  # type: ignore[attr-defined]
                handle=handle_entry._dc_var.get() or None,  # type: ignore[attr-defined]
                password=password_entry._dc_var.get() or None,  # type: ignore[attr-defined]
                email=email_entry._dc_var.get() or None,  # type: ignore[attr-defined]
                pgp_key_id=None,
                recovery=None,
                notes=notes_entry._dc_var.get() or None,  # type: ignore[attr-defined]
                user_agent=None,
                proxy=None,
                tags=[],
                gen=gen_var.get(),
                replace=False,
                mail_provider=preset.slug if preset else None,
            )
            try:
                rc, out, err = invoke_cli_capturing(self.cfg, ns)
            except SystemExit as e:
                rc = int(e.code) if isinstance(e.code, int) else 2
                out, err = "", ""
            except Exception as e:
                rc, out, err = 2, "", f"{type(e).__name__}: {e}"
            if rc == 0:
                messagebox.showinfo(
                    "darkcat — persona added",
                    out + ("\nWire it up via "
                           "'Mail console… → Send' afterwards."),
                    parent=dlg,
                )
                dlg.destroy()
            else:
                last = err.splitlines()[-1].strip() if err.strip() else "failed"
                messagebox.showerror("darkcat — add persona",
                                     last, parent=dlg)

        def _cancel() -> None:
            dlg.destroy()

        btns = tk.Frame(body, bg=DEEP_BG)
        btns.pack(fill="x", pady=(4, 0))
        ttk.Button(btns, text="Add", command=_submit,
                   style="Run.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Cancel", command=_cancel,
                   style="Run.TButton").pack(side="left", padx=6)

        dlg.bind("<Return>", lambda _e: _submit())
        dlg.bind("<Escape>", lambda _e: _cancel())
        dlg.protocol("WM_DELETE_WINDOW", _cancel)
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        name_entry.focus_set()

    def _show_chat(self) -> None:
        """Modal Chat-console dialog mirroring the TUI ChatScreen.

        Pick a persona, action, target / channel id / invite link / peer
        id, plus a body. Run dispatches into ``cmd_chat`` via
        ``invoke_cli_capturing`` and renders the result in a scrolling
        log so multi-line tables survive intact.
        """
        import argparse as _argparse

        from darkcat import personas as pv
        from darkcat.identity import invoke_cli_capturing

        dlg = tk.Toplevel(self.root)
        dlg.title("darkcat — chat")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(self.root)
        try:
            self.root.update_idletasks()
            px = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - 820) // 2)
            py = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - 620) // 3)
            dlg.geometry(f"820x620+{px}+{py}")
        except tk.TclError:
            dlg.geometry("820x620")

        body = tk.Frame(dlg, bg=DEEP_BG, padx=16, pady=12)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text="Chat console",
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 13, "bold"),
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            body,
            text=("Run any darkcat chat action against a persona. "
                  "Output of the underlying CLI command appears below."),
            fg=DIM_FG, bg=DEEP_BG, font=(self._mono, 9),
            wraplength=780, justify="left",
        ).pack(anchor="w", pady=(0, 6))

        # Quick-action preset buttons. Each one sets the Network + Action
        # dropdowns below so the operator doesn't have to remember which
        # CLI verb each network uses. Defined here as a list of tuples so
        # the row can be regenerated trivially if the set changes.
        # Shape: (label, network ('' = persona default), action, hint).
        _presets = [
            ("Telegram Join",  "telegram", "join",
             "expects @channel | https://t.me/+invite | numeric id"),
            ("Telegram Leave", "telegram", "leave",
             "expects numeric channel id"),
            ("Add Session",    "session",  "addcontact",
             "expects 66-hex Session ID; body = optional nickname"),
            ("Accept SimpleX", "simplex",  "connect",
             "expects https://simplex.chat/contact#... or simplex:/..."),
            ("Login",          "",         "login",
             "no target needed; press Run"),
            ("List",           "",         "list",
             "no target needed; press Run"),
            ("Backends",       "",         "backends",
             "no target needed; press Run"),
        ]
        presets_row = tk.Frame(body, bg=DEEP_BG)
        presets_row.pack(fill="x", pady=(0, 8))

        # Persona dropdown sourced from the vault. Encrypted vaults are
        # unlocked here, before the form is built, so the Combobox carries
        # real names instead of falling back to a free-form Entry. The
        # cached passphrase is then threaded into the CLI via
        # ``DARKCAT_VAULT_PASSPHRASE`` on Run.
        state: dict[str, object] = {"passphrase": None}

        def _vault_is_encrypted() -> bool:
            path = pv.vault_path()
            return path.exists() and path.suffix == ".gpg"

        def _load_persona_names() -> list[str]:
            try:
                path = pv.vault_path()
                if not path.exists():
                    return []
                v = pv.Vault(path=path, passphrase=state["passphrase"])
                return [p.name for p in v.personas]
            except Exception:
                return []

        # Prompt up-front on encrypted vaults so the persona Combobox
        # populates. Wrong-passphrase loops re-prompt; cancel leaves
        # state['passphrase'] = None and degrades to the Entry fallback.
        if _vault_is_encrypted():
            while True:
                pw = self._open_passphrase_dialog(dlg, "Vault is encrypted")
                if pw is None:
                    break
                try:
                    pv.Vault(path=pv.vault_path(), passphrase=pw)
                except RuntimeError as e:
                    messagebox.showerror(
                        "darkcat — vault locked",
                        f"wrong passphrase: {e}", parent=dlg,
                    )
                    continue
                state["passphrase"] = pw
                break

        persona_names = _load_persona_names()

        form = tk.Frame(body, bg=DEEP_BG)
        form.pack(fill="x", pady=(4, 0))

        def _row(label: str, widget):
            row = tk.Frame(form, bg=DEEP_BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, fg=DIM_FG, bg=DEEP_BG,
                     font=(self._mono, 9), width=14, anchor="w").pack(side="left")
            widget.pack(side="left", fill="x", expand=True)
            return widget

        persona_var = tk.StringVar(value=persona_names[0] if persona_names else "")
        if persona_names:
            persona_w = ttk.Combobox(
                form, textvariable=persona_var, values=persona_names,
                state="readonly",
            )
        else:
            persona_w = tk.Entry(
                form, textvariable=persona_var,
                bg=PANEL_BG, fg=NEON_GREEN, insertbackground=NEON_GREEN,
                relief="flat", highlightthickness=1,
                highlightbackground=DARK_GREEN, highlightcolor=NEON_CYAN,
            )
        _row("Persona", persona_w)

        network_var = tk.StringVar(value="(persona default)")
        network_w = ttk.Combobox(
            form, textvariable=network_var, state="readonly",
            values=["(persona default)", "telegram", "matrix", "xmpp",
                    "simplex", "session"],
        )
        _row("Network", network_w)

        action_var = tk.StringVar(value="list")
        action_w = ttk.Combobox(
            form, textvariable=action_var, state="readonly",
            values=["backends", "login", "list", "read", "send", "ingest",
                    "join", "leave", "connect", "addcontact"],
        )
        _row("Action", action_w)

        target_var = tk.StringVar(value="")
        target_w = tk.Entry(
            form, textvariable=target_var,
            bg=PANEL_BG, fg=NEON_GREEN, insertbackground=NEON_GREEN,
            relief="flat", highlightthickness=1,
            highlightbackground=DARK_GREEN, highlightcolor=NEON_CYAN,
        )
        _row("Target / id", target_w)

        body_var = tk.StringVar(value="")
        body_w = tk.Entry(
            form, textvariable=body_var,
            bg=PANEL_BG, fg=NEON_GREEN, insertbackground=NEON_GREEN,
            relief="flat", highlightthickness=1,
            highlightbackground=DARK_GREEN, highlightcolor=NEON_CYAN,
        )
        _row("Body / limit", body_w)

        tk.Label(
            body,
            text=("Target: @channel | -100… group id | direct:42 | "
                  "05<hex> | https://t.me/+… | invite link. "
                  "Body field doubles as N for read/ingest and "
                  "as the local nickname for addcontact."),
            fg=DIM_FG, bg=DEEP_BG, font=(self._mono, 8),
            wraplength=780, justify="left",
        ).pack(anchor="w", pady=(6, 2))

        log = tk.Text(
            body, height=14, bg=PANEL_BG, fg=NEON_GREEN,
            insertbackground=NEON_GREEN, relief="flat",
            font=(self._mono, 9), highlightthickness=1,
            highlightbackground=DARK_GREEN,
        )
        log.pack(fill="both", expand=True, pady=(6, 6))
        log.configure(state="disabled")

        def _log(msg: str) -> None:
            log.configure(state="normal")
            log.insert("end", msg.rstrip() + "\n")
            log.see("end")
            log.configure(state="disabled")

        def _apply_preset(net: str, act: str, hint: str) -> None:
            """Pre-fill Network + Action dropdowns from one click and
            print a one-line hint about what target value to type next."""
            network_var.set(net if net else "(persona default)")
            action_var.set(act)
            if hint:
                _log(f"hint: {hint}")
            if act not in ("login", "list", "backends"):
                target_w.focus_set()

        for plabel, pnet, pact, phint in _presets:
            ttk.Button(
                presets_row, text=plabel, style="Run.TButton",
                command=lambda n=pnet, a=pact, h=phint: _apply_preset(n, a, h),
            ).pack(side="left", padx=2)

        def _run() -> None:
            persona = persona_var.get().strip()
            action = action_var.get()
            nw = network_var.get()
            network = None if nw == "(persona default)" else nw
            target = target_var.get().strip()
            body_str = body_var.get().strip()

            if not persona and action != "backends":
                _log("error: persona is required")
                return

            ns_kwargs: dict = {"cmd": "chat", "action": action,
                               "persona": persona, "network": network,
                               "json": False}
            if action == "list":
                ns_kwargs["limit"] = 100
            elif action == "read":
                try:
                    ns_kwargs["limit"] = int(body_str) if body_str else 30
                except ValueError:
                    ns_kwargs["limit"] = 30
                ns_kwargs["channel_id"] = target
            elif action == "send":
                ns_kwargs["channel_id"] = target
                ns_kwargs["message"] = body_str
            elif action == "ingest":
                try:
                    ns_kwargs["limit"] = int(body_str) if body_str else 200
                except ValueError:
                    ns_kwargs["limit"] = 200
                ns_kwargs["channel_id"] = target
            elif action == "join":
                ns_kwargs["target"] = target
            elif action == "leave":
                ns_kwargs["channel_id"] = target
            elif action == "connect":
                ns_kwargs["invite_link"] = target
            elif action == "addcontact":
                ns_kwargs["peer_session_id"] = target
                ns_kwargs["name"] = body_str or None

            ns = _argparse.Namespace(**ns_kwargs)

            def _dispatch() -> None:
                import os as _os
                saved = _os.environ.get("DARKCAT_VAULT_PASSPHRASE")
                if state["passphrase"] is not None:
                    _os.environ["DARKCAT_VAULT_PASSPHRASE"] = state["passphrase"]
                try:
                    rc, out, err = invoke_cli_capturing(self.cfg, ns)
                except SystemExit as e:
                    rc = int(e.code) if isinstance(e.code, int) else 2
                    out, err = "", ""
                except Exception as e:
                    rc, out, err = 2, "", f"{type(e).__name__}: {e}"
                finally:
                    if state["passphrase"] is not None:
                        if saved is None:
                            _os.environ.pop("DARKCAT_VAULT_PASSPHRASE", None)
                        else:
                            _os.environ["DARKCAT_VAULT_PASSPHRASE"] = saved
                if out:
                    _log(out)
                if err:
                    _log(err)
                _log(f"-- exit {rc} --")

            _unlock_then(_dispatch)

        def _unlock_then(callback) -> None:
            """Prompt for the vault passphrase if needed, verify it opens
            the file, then run ``callback``. Wrong-passphrase loops re-
            prompt until the operator cancels."""
            if not _vault_is_encrypted() or state["passphrase"] is not None:
                callback()
                return
            pw = self._open_passphrase_dialog(dlg, "Vault is encrypted")
            if pw is None:
                _log("vault locked — close and reopen to retry")
                return
            try:
                pv.Vault(path=pv.vault_path(), passphrase=pw)
            except RuntimeError as e:
                messagebox.showerror(
                    "darkcat — vault locked",
                    f"wrong passphrase: {e}", parent=dlg,
                )
                _unlock_then(callback)
                return
            state["passphrase"] = pw
            callback()

        btns = tk.Frame(body, bg=DEEP_BG)
        btns.pack(fill="x")
        ttk.Button(btns, text="Run",   command=_run,         style="Run.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Close", command=dlg.destroy,  style="Run.TButton").pack(side="right")

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        persona_w.focus_set()

    def _show_mail(self) -> None:
        """Modal Mail-console dialog mirroring the TUI MailScreen.

        Send a plain-text message or list recent INBOX headers for the
        chosen persona. The persona must carry SMTP/IMAP coordinates —
        see `darkcat mail --help` for the persona shape.
        """
        import argparse as _argparse

        from darkcat import personas as pv
        from darkcat.identity import invoke_cli_capturing

        dlg = tk.Toplevel(self.root)
        dlg.title("darkcat — mail")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(self.root)
        try:
            self.root.update_idletasks()
            px = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - 820) // 2)
            py = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - 580) // 3)
            dlg.geometry(f"820x580+{px}+{py}")
        except tk.TclError:
            dlg.geometry("820x580")

        body = tk.Frame(dlg, bg=DEEP_BG, padx=16, pady=12)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text="Mail console",
            fg=NEON_CYAN, bg=DEEP_BG, font=(self._mono, 13, "bold"),
        ).pack(anchor="w", pady=(0, 4))

        tk.Label(
            body,
            text=("Send plain-text email or list recent INBOX headers. "
                  "The persona must carry SMTP/IMAP credentials (see "
                  "`darkcat mail --help`)."),
            fg=DIM_FG, bg=DEEP_BG, font=(self._mono, 9),
            wraplength=780, justify="left",
        ).pack(anchor="w", pady=(0, 6))

        # Persona dropdown sourced from the vault. Encrypted vaults are
        # unlocked here, before the form is built, so the Combobox carries
        # real names instead of falling back to a free-form Entry. Cached
        # passphrase is threaded into the CLI via DARKCAT_VAULT_PASSPHRASE
        # on Run.
        state: dict[str, object] = {"passphrase": None}

        def _vault_is_encrypted() -> bool:
            path = pv.vault_path()
            return path.exists() and path.suffix == ".gpg"

        def _load_persona_names() -> list[str]:
            try:
                path = pv.vault_path()
                if not path.exists():
                    return []
                v = pv.Vault(path=path, passphrase=state["passphrase"])
                return [p.name for p in v.personas]
            except Exception:
                return []

        # Up-front unlock on encrypted vaults so the persona Combobox
        # populates. Cancel falls through to the free-form Entry.
        if _vault_is_encrypted():
            while True:
                pw = self._open_passphrase_dialog(dlg, "Vault is encrypted")
                if pw is None:
                    break
                try:
                    pv.Vault(path=pv.vault_path(), passphrase=pw)
                except RuntimeError as e:
                    messagebox.showerror(
                        "darkcat — vault locked",
                        f"wrong passphrase: {e}", parent=dlg,
                    )
                    continue
                state["passphrase"] = pw
                break

        persona_names = _load_persona_names()

        form = tk.Frame(body, bg=DEEP_BG)
        form.pack(fill="x", pady=(4, 0))

        def _row(label: str, widget):
            row = tk.Frame(form, bg=DEEP_BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, fg=DIM_FG, bg=DEEP_BG,
                     font=(self._mono, 9), width=14, anchor="w").pack(side="left")
            widget.pack(side="left", fill="x", expand=True)
            return widget

        persona_var = tk.StringVar(value=persona_names[0] if persona_names else "")
        if persona_names:
            persona_w = ttk.Combobox(
                form, textvariable=persona_var, values=persona_names,
                state="readonly",
            )
        else:
            persona_w = tk.Entry(
                form, textvariable=persona_var,
                bg=PANEL_BG, fg=NEON_GREEN, insertbackground=NEON_GREEN,
                relief="flat", highlightthickness=1,
                highlightbackground=DARK_GREEN, highlightcolor=NEON_CYAN,
            )
        _row("Persona", persona_w)

        action_var = tk.StringVar(value="send")
        action_w = ttk.Combobox(
            form, textvariable=action_var, state="readonly",
            values=["send", "check"],
        )
        _row("Action", action_w)

        to_var = tk.StringVar(value="")
        to_w = tk.Entry(
            form, textvariable=to_var,
            bg=PANEL_BG, fg=NEON_GREEN, insertbackground=NEON_GREEN,
            relief="flat", highlightthickness=1,
            highlightbackground=DARK_GREEN, highlightcolor=NEON_CYAN,
        )
        _row("To (csv)", to_w)

        cc_var = tk.StringVar(value="")
        cc_w = tk.Entry(
            form, textvariable=cc_var,
            bg=PANEL_BG, fg=NEON_GREEN, insertbackground=NEON_GREEN,
            relief="flat", highlightthickness=1,
            highlightbackground=DARK_GREEN, highlightcolor=NEON_CYAN,
        )
        _row("CC (csv)", cc_w)

        bcc_var = tk.StringVar(value="")
        bcc_w = tk.Entry(
            form, textvariable=bcc_var,
            bg=PANEL_BG, fg=NEON_GREEN, insertbackground=NEON_GREEN,
            relief="flat", highlightthickness=1,
            highlightbackground=DARK_GREEN, highlightcolor=NEON_CYAN,
        )
        _row("BCC (csv)", bcc_w)

        reply_var = tk.StringVar(value="")
        reply_w = tk.Entry(
            form, textvariable=reply_var,
            bg=PANEL_BG, fg=NEON_GREEN, insertbackground=NEON_GREEN,
            relief="flat", highlightthickness=1,
            highlightbackground=DARK_GREEN, highlightcolor=NEON_CYAN,
        )
        _row("Reply-To", reply_w)

        subj_var = tk.StringVar(value="")
        subj_w = tk.Entry(
            form, textvariable=subj_var,
            bg=PANEL_BG, fg=NEON_GREEN, insertbackground=NEON_GREEN,
            relief="flat", highlightthickness=1,
            highlightbackground=DARK_GREEN, highlightcolor=NEON_CYAN,
        )
        _row("Subject/folder", subj_w)

        tk.Label(body, text="Body (send) / limit number (check)",
                 fg=DIM_FG, bg=DEEP_BG, font=(self._mono, 9)).pack(
            anchor="w", pady=(8, 2))
        body_text = tk.Text(
            body, height=6, bg=PANEL_BG, fg=NEON_GREEN,
            insertbackground=NEON_GREEN, relief="flat",
            font=(self._mono, 9), highlightthickness=1,
            highlightbackground=DARK_GREEN,
        )
        body_text.pack(fill="x")

        log = tk.Text(
            body, height=10, bg=PANEL_BG, fg=NEON_GREEN,
            insertbackground=NEON_GREEN, relief="flat",
            font=(self._mono, 9), highlightthickness=1,
            highlightbackground=DARK_GREEN,
        )
        log.pack(fill="both", expand=True, pady=(6, 6))
        log.configure(state="disabled")

        def _log(msg: str) -> None:
            log.configure(state="normal")
            log.insert("end", msg.rstrip() + "\n")
            log.see("end")
            log.configure(state="disabled")

        def _run() -> None:
            persona = persona_var.get().strip()
            action = action_var.get()
            to_raw = to_var.get().strip()
            subj = subj_var.get().strip()
            body_str = body_text.get("1.0", "end").strip()
            if not persona:
                _log("error: persona is required")
                return

            if action == "send":
                recipients = [s.strip() for s in to_raw.split(",") if s.strip()]
                if not recipients or not subj or not body_str:
                    _log("error: need to, subject, body")
                    return
                cc_raw = cc_var.get().strip()
                bcc_raw = bcc_var.get().strip()
                reply_to = reply_var.get().strip() or None
                cc = [s.strip() for s in cc_raw.split(",") if s.strip()] or None
                bcc = [s.strip() for s in bcc_raw.split(",") if s.strip()] or None
                ns = _argparse.Namespace(
                    cmd="mail", action="send", persona=persona,
                    to=recipients, cc=cc, bcc=bcc, reply_to=reply_to,
                    subject=subj, body=body_str, body_file=None,
                    timeout=30.0,
                )
            else:
                try:
                    limit = int(body_str) if body_str else 25
                except ValueError:
                    limit = 25
                ns = _argparse.Namespace(
                    cmd="mail", action="check", persona=persona,
                    folder=subj or "INBOX", limit=limit, timeout=30.0,
                    json=False,
                )

            def _dispatch() -> None:
                import os as _os
                saved = _os.environ.get("DARKCAT_VAULT_PASSPHRASE")
                if state["passphrase"] is not None:
                    _os.environ["DARKCAT_VAULT_PASSPHRASE"] = state["passphrase"]
                try:
                    rc, out, err = invoke_cli_capturing(self.cfg, ns)
                except SystemExit as e:
                    rc = int(e.code) if isinstance(e.code, int) else 2
                    out, err = "", ""
                except Exception as e:
                    rc, out, err = 2, "", f"{type(e).__name__}: {e}"
                finally:
                    if state["passphrase"] is not None:
                        if saved is None:
                            _os.environ.pop("DARKCAT_VAULT_PASSPHRASE", None)
                        else:
                            _os.environ["DARKCAT_VAULT_PASSPHRASE"] = saved
                if out:
                    _log(out)
                if err:
                    _log(err)
                _log(f"-- exit {rc} --")

            _unlock_then(_dispatch)

        def _unlock_then(callback) -> None:
            """Prompt for the vault passphrase if needed, verify it opens
            the file, then run ``callback``. Wrong-passphrase loops re-
            prompt until the operator cancels."""
            if not _vault_is_encrypted() or state["passphrase"] is not None:
                callback()
                return
            pw = self._open_passphrase_dialog(dlg, "Vault is encrypted")
            if pw is None:
                _log("vault locked — close and reopen to retry")
                return
            try:
                pv.Vault(path=pv.vault_path(), passphrase=pw)
            except RuntimeError as e:
                messagebox.showerror(
                    "darkcat — vault locked",
                    f"wrong passphrase: {e}", parent=dlg,
                )
                _unlock_then(callback)
                return
            state["passphrase"] = pw
            callback()

        btns = tk.Frame(body, bg=DEEP_BG)
        btns.pack(fill="x")
        ttk.Button(btns, text="Run",   command=_run,        style="Run.TButton").pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Close", command=dlg.destroy, style="Run.TButton").pack(side="right")

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        persona_w.focus_set()

    def _open_sudo_dialog(self, prompt: str) -> Optional[str]:
        """Modal Toplevel that asks for a sudo password (masked with *).

        Returns the typed password, or None if the user pressed Esc /
        Cancel / closed the dialog. Empty input also counts as cancel.
        """
        dlg = tk.Toplevel(self.root)
        dlg.title("darkcat — privilege required")
        dlg.configure(bg=DEEP_BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        # Position over the parent so the user notices it.
        try:
            self.root.update_idletasks()
            px = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - 460) // 2)
            py = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - 200) // 3)
            dlg.geometry(f"460x180+{px}+{py}")
        except tk.TclError:
            dlg.geometry("460x180")

        result: list[Optional[str]] = [None]

        body = tk.Frame(dlg, bg=DEEP_BG, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text="› sudo password",
            bg=DEEP_BG, fg=NEON_PINK,
            font=(self._mono, 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            body, text=prompt.rstrip(": "),
            bg=DEEP_BG, fg=DIM_FG, font=(self._mono, 9),
            wraplength=420, justify="left",
        ).pack(anchor="w", pady=(2, 8))

        entry = tk.Entry(
            body, show="*",
            bg=PANEL_BG, fg=NEON_GREEN,
            insertbackground=NEON_GREEN,
            relief="flat", bd=0,
            font=(self._mono, 11),
        )
        entry.pack(fill="x", ipady=4)
        entry.focus_set()

        btns = tk.Frame(body, bg=DEEP_BG)
        btns.pack(fill="x", pady=(12, 0))

        def _commit() -> None:
            pw = entry.get()
            result[0] = pw or None
            try:
                entry.delete(0, "end")
            except tk.TclError:
                pass
            dlg.destroy()

        def _cancel(_e: object = None) -> None:
            result[0] = None
            try:
                entry.delete(0, "end")
            except tk.TclError:
                pass
            dlg.destroy()

        ttk.Button(btns, text="OK", command=_commit,
                   style="Primary.TButton").pack(side="right")
        ttk.Button(btns, text="Cancel", command=_cancel).pack(
            side="right", padx=(0, 8))

        dlg.bind("<Return>", lambda _e: _commit())
        dlg.bind("<KP_Enter>", lambda _e: _commit())
        dlg.bind("<Escape>", _cancel)
        dlg.protocol("WM_DELETE_WINDOW", _cancel)

        # Modal: grab focus so the user can't interact with the main window.
        try:
            dlg.grab_set()
        except tk.TclError:
            pass
        self.root.wait_window(dlg)
        return result[0]

    # ---- crawl ----------------------------------------------------------

    def _start_crawl(self) -> None:
        if self._active_crawler is not None:
            self._log_segments([
                ("warn", "⚠ a crawl is already running — click ABORT or press Ctrl+C"),
            ])
            return
        topics = self.topics_var.get().split()
        proto = (self.protocol_var.get() or "").strip()
        if not proto:
            self._log_segments([("err", "✗ pick a protocol from the dropdown")])
            return
        max_pages = self._read_int_clamped(
            self.max_pages_var, default=50, lo=_PAGES_RANGE[0], hi=_PAGES_RANGE[1],
            label="pages",
        )
        max_depth = self._read_int_clamped(
            self.max_depth_var, default=2, lo=_DEPTH_RANGE[0], hi=_DEPTH_RANGE[1],
            label="depth",
        )
        threshold = self._read_float_clamped(
            self.threshold_var, default=0.0,
            lo=_THRESHOLD_RANGE[0], hi=_THRESHOLD_RANGE[1],
            label="threshold",
        )
        seeds = all_seeds() if proto == "all" else SEEDS_BY_PROTOCOL.get(proto, [])
        if not seeds:
            self._log(f"⚠ no built-in seeds for {proto}", tag="warn")
            return
        self._log_segments([
            ("info", "▶ "),
            ("title", "crawl starting"),
            ("muted", f"  proto="),
            ("ok", f"{proto}"),
            ("muted", f"  seeds="),
            ("ok", f"{len(seeds)}"),
            ("muted", f"  pages="),
            ("ok", f"{max_pages}"),
            ("muted", f"  depth="),
            ("ok", f"{max_depth}"),
            ("muted", f"  topics="),
            ("ok", f"{' '.join(topics) or '(none)'}"),
        ])
        self._set_crawling(True)
        self._set_status(
            f"crawling: {proto} · seeds={len(seeds)} · pages≤{max_pages} · depth≤{max_depth}"
        )
        threading.Thread(
            target=self._crawl_worker,
            args=(seeds, topics, max_pages, max_depth, threshold),
            daemon=True,
        ).start()

    def _crawl_worker(self, seeds, topics, max_pages, max_depth, threshold) -> None:
        tf = TopicFilter(topics)
        policy = CrawlPolicy(
            max_pages=max_pages, max_depth=max_depth, score_threshold=threshold,
        )
        crawler = Crawler(self.cfg, self.storage, tf, policy)
        self._active_crawler = crawler

        def on_event(kind: str, payload: dict) -> None:
            self._post("crawl_event", (kind, payload))

        try:
            stats = crawler.crawl(seeds, on_event=on_event)
            msg = (
                f"done. fetched={stats.fetched} errors={stats.errors} "
                f"skipped={stats.skipped}"
            )
        except Exception as e:
            msg = f"crawl crashed: {e}"
        finally:
            self._active_crawler = None
        self._post("crawl_done", msg)

    def _stop_crawl(self) -> None:
        if self._active_crawler:
            self._active_crawler.stop()
            self._log("▣ stop requested", tag="warn")
            self._set_status("abort requested — waiting for crawler to wind down…")

    def _set_crawling(self, value: bool) -> None:
        self.crawl_btn.configure(state=("disabled" if value else "normal"))
        self.stop_btn.configure(state=("normal" if value else "disabled"))

    # ---- search / fetch -------------------------------------------------

    def _do_search(self) -> None:
        if self._busy.get("search"):
            return  # already running — silently ignore double-clicks / Enter mash
        q = self.search_var.get().strip()
        if not q:
            self._log_segments([("muted", "· empty search query — nothing to do")])
            return
        self._set_busy("search", True)
        self._set_status(f"searching: {q}")
        self._log_segments([
            ("info", "▶ "),
            ("title", "search "),
            ("ok", q),
            ("muted", "  · running…"),
        ])
        threading.Thread(
            target=self._search_worker, args=(q,), daemon=True,
        ).start()

    def _search_worker(self, q: str) -> None:
        try:
            rows = self.storage.search(q, limit=200)
        except Exception as e:
            self._post("search_done", (q, [], f"{type(e).__name__}: {e}"))
            return
        self._post("search_done", (q, list(rows), None))

    def _do_fetch(self) -> None:
        if self._busy.get("fetch"):
            return
        url = self.fetch_var.get().strip()
        if not url:
            self._log_segments([("muted", "· empty URL — nothing to fetch")])
            return
        if not self._looks_like_url(url):
            self._log_segments([
                ("err", "✗ "),
                ("warn", f"that doesn't look like a URL: {url[:80]}"),
            ])
            return
        self._set_busy("fetch", True)
        self._set_status(f"fetching: {url[:80]}")
        self._log_segments([("info", "▶ "), ("title", "fetch "), ("url", url)])
        threading.Thread(target=self._fetch_worker, args=(url,), daemon=True).start()

    @staticmethod
    def _looks_like_url(s: str) -> bool:
        """Cheap sanity check — accepts schemed URLs and bare hosts."""
        if not s:
            return False
        if "://" in s or s.startswith(("magnet:", "acct:", "freenet:", "hyphanet:")):
            return True
        # Tor onions, i2p, eepsites, dotted hosts, ipv6 brackets all contain `.`
        # or `:`; reject only blatant garbage.
        return any(c in s for c in ".:") and " " not in s

    def _fetch_worker(self, url: str) -> None:
        try:
            result = self.fetcher.fetch(url)
        except Exception as e:
            self._post("fetch_done", (False, f"✗ fetch failed: {e}"))
            return
        self._post("fetch_done", (
            True,
            f"✓ status={result.status} bytes={len(result.body)} "
            f"ct={result.content_type} → {result.final_url}",
        ))

    # ---- results table --------------------------------------------------

    def _refresh_results(self) -> None:
        if self._busy.get("results"):
            return
        self._set_busy("results", True)
        threading.Thread(target=self._results_worker, daemon=True).start()

    def _results_worker(self) -> None:
        try:
            rows = list(self.storage.top(limit=200))
        except Exception as e:
            self._post("results_done", ([], f"{type(e).__name__}: {e}"))
            return
        self._post("results_done", (rows, None))

    def _populate_results(self, rows) -> None:
        self.results.delete(*self.results.get_children())
        # Cache the raw rows so the EXPORT button can dump exactly what the
        # user sees, in display order, without a second DB query.
        self._last_rows = list(rows)
        # Configure score-tier tag colors once (idempotent — Tk discards a
        # second call with the same tag name). Mirrors the log color scheme:
        # ok (>=1.0) → green, warn (>=0.3) → amber, muted (<0.3) → dim.
        self.results.tag_configure("placeholder", foreground=DIM_FG)
        self.results.tag_configure("score_hi",  foreground=NEON_GREEN)
        self.results.tag_configure("score_mid", foreground=AMBER)
        self.results.tag_configure("score_lo",  foreground=DIM_FG)
        if not self._last_rows:
            self.results.insert(
                "", "end",
                values=(
                    "—", "—", "—",
                    "no results yet — run a crawl or hit refresh",
                    "",
                ),
                tags=("placeholder",),
            )
            return
        for idx, r in enumerate(self._last_rows):
            try:
                score = float(r["score"] or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            # iid = stable index into _last_rows. Used by the right-click /
            # double-click handlers to map the focused Treeview item back
            # to the underlying sqlite Row (we need the *full* URL, not the
            # truncated display string).
            tier = "score_hi" if score >= 1.0 else "score_mid" if score >= 0.3 else "score_lo"
            self.results.insert(
                "", "end", iid=str(idx),
                values=(
                    f"{score:.2f}",
                    self._row_category(r),
                    r["protocol"] or "?",
                    (r["title"] or "")[:60],
                    (r["url"] or "")[:120],
                ),
                tags=(tier,),
            )

    @staticmethod
    def _row_category(row) -> str:
        """Best-effort category label for a result row."""
        # Some Row objects (FTS5 path) may not have every field — be defensive.
        def _g(name: str) -> str:
            try:
                return row[name] or ""
            except (IndexError, KeyError):
                return ""
        return categorize_str(
            _g("title"), _g("snippet"), _g("topic_hits"), _g("url"),
        )

    # ---- score / category header tooltip --------------------------------

    def _on_results_motion(self, event) -> None:
        """Show a help popup when the cursor sits over the score/category
        column header. Other regions hide the popup."""
        try:
            region = self.results.identify_region(event.x, event.y)
            col_id = self.results.identify_column(event.x)
        except tk.TclError:
            self._hide_heading_tip()
            return
        if region != "heading":
            self._hide_heading_tip()
            return
        cols = self.results["columns"]
        try:
            idx = int(col_id.lstrip("#")) - 1
            if idx < 0 or idx >= len(cols):
                raise IndexError
            col_name = cols[idx]
        except (ValueError, IndexError):
            self._hide_heading_tip()
            return
        if col_name not in ("score", "category"):
            self._hide_heading_tip()
            return
        if self._heading_tip_for == col_name and self._heading_tip is not None:
            return
        self._show_heading_tip(event, col_name)

    def _show_heading_tip(self, event, col_name: str) -> None:
        self._hide_heading_tip()
        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            base_x = self.results.winfo_rootx() + event.x + 14
            base_y = self.results.winfo_rooty() + event.y + 18
        except tk.TclError:
            return
        try:
            tip = tk.Toplevel(self.results)
        except tk.TclError:
            return
        tip.wm_overrideredirect(True)
        tip.configure(bg=NEON_PINK)
        inner = tk.Frame(tip, bg=PANEL_BG, padx=10, pady=6)
        inner.pack(padx=1, pady=1)
        tk.Label(
            inner, text=SCORE_HELP, bg=PANEL_BG, fg=NEON_CYAN,
            font=("TkFixedFont", 9), justify="left",
        ).pack(anchor="w")
        # Position the popup, then nudge it back on-screen if it would clip
        # the right or bottom edges. Compute size after a forced update so
        # winfo_reqwidth/reqheight are accurate.
        tip.update_idletasks()
        try:
            tip_w = tip.winfo_reqwidth()
            tip_h = tip.winfo_reqheight()
        except tk.TclError:
            tip_w = tip_h = 0
        x = max(0, min(base_x, screen_w - tip_w - 8))
        y = max(0, min(base_y, screen_h - tip_h - 8))
        tip.wm_geometry(f"+{x}+{y}")
        self._heading_tip = tip
        self._heading_tip_for = col_name

    def _hide_heading_tip(self) -> None:
        if self._heading_tip is not None:
            try: self._heading_tip.destroy()
            except tk.TclError: pass
            self._heading_tip = None
            self._heading_tip_for = ""

    # ---- result-row interactions ----------------------------------------

    def _selected_row(self):
        """Return the underlying sqlite Row for the focused Treeview item, or
        None if the table only holds the placeholder / no row is focused."""
        if not self._last_rows:
            return None
        focus = self.results.focus()
        if not focus:
            return None
        try:
            idx = int(focus)
        except ValueError:
            return None
        if idx < 0 or idx >= len(self._last_rows):
            return None
        return self._last_rows[idx]

    def _copy_selected_url(self) -> None:
        row = self._selected_row()
        if row is None:
            self._log_segments([("warn", "✗ no row selected")])
            return
        url = (row["url"] or "").strip()
        if not url:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            # Tell the X clipboard manager to keep the value after we exit.
            self.root.update()
        except tk.TclError as e:
            self._log_segments([("err", f"✗ clipboard failed: {e}")])
            return
        self._log_segments([("ok", "✓ copied → "), ("url", url)])

    def _fetch_selected_url(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        url = (row["url"] or "").strip()
        if not url:
            return
        # Mirror the search-bar fetch path exactly so the busy-state and
        # logging stay consistent. Set the input value first so the user can
        # see what's running.
        try:
            self.fetch_var.set(url)
        except tk.TclError:
            pass
        self._do_fetch()

    def _mirrors_of_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        url = (row["url"] or "").strip()
        if not url:
            return
        try:
            rows = self.storage.near_duplicates_of(url, distance=3, limit=20)
        except Exception as e:
            self._log_segments([
                ("err", f"✗ mirrors lookup failed: {type(e).__name__}: {e}"),
            ])
            return
        if not rows:
            self._log_segments([
                ("muted", "(no mirrors found within Hamming distance ≤ 3 — "
                          "try `darkcat mirrors --rebuild` first)"),
            ])
            return
        self._log_segments([("title", "▓▒░ mirrors of "), ("url", url),
                            ("title", " ░▒▓")])
        for r in rows:
            self._log_segments([
                ("muted", f"  d={r['distance']:>2}  "),
                ("url", r["url"]),
            ])

    def _history_of_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        url = (row["url"] or "").strip()
        if not url:
            return
        try:
            rows = self.storage.page_history_for(url, limit=10)
        except Exception as e:
            self._log_segments([
                ("err", f"✗ history lookup failed: {type(e).__name__}: {e}"),
            ])
            return
        if not rows:
            self._log_segments([("muted", "(no snapshots recorded)")])
            return
        self._log_segments([("title", "▓▒░ history of "), ("url", url),
                            ("title", " ░▒▓")])
        for r in rows:
            ts = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(r["captured_at"]),
            )
            self._log_segments([
                ("muted", f"  {ts}  score="),
                ("ok", f"{(r['score'] or 0):.2f}"),
                ("muted", f"  bytes={r['bytes'] or 0:>7}  hash="),
                ("url", f"{r['content_hash'][:12]}…"),
            ])

    def _on_results_right_click(self, event) -> None:
        """Show a context menu over the right-clicked row. If the click lands
        on a non-row region (heading, separator, empty area), do nothing."""
        try:
            iid = self.results.identify_row(event.y)
        except tk.TclError:
            return
        if not iid:
            return
        # Focus the right-clicked row so the menu acts on it (matches the
        # convention every desktop file manager uses).
        self.results.selection_set(iid)
        self.results.focus(iid)
        if not self._last_rows:
            return
        menu = tk.Menu(
            self.root, tearoff=0,
            bg=PANEL_BG, fg=NEON_GREEN,
            activebackground="#1a0033", activeforeground=NEON_PINK,
            bd=0,
        )
        menu.add_command(label="Copy URL", command=self._copy_selected_url)
        menu.add_command(label="Fetch this URL", command=self._fetch_selected_url)
        menu.add_separator()
        menu.add_command(label="Show mirrors (SimHash)", command=self._mirrors_of_selected)
        menu.add_command(label="Show history", command=self._history_of_selected)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ---- sortable columns -----------------------------------------------

    def _sort_by(self, col: str) -> None:
        """Click-sort the results by ``col``. Toggles between descending and
        ascending each click. Reorders ``_last_rows`` then re-renders so the
        cached order (used by EXPORT) matches what the user sees."""
        if not self._last_rows:
            return
        descending = self._sort_state.get(col, True)
        # Flip for next click.
        self._sort_state[col] = not descending

        def keyfn(r):
            try:
                if col == "score":
                    return float(r["score"] or 0.0)
                if col == "category":
                    return self._row_category(r)
                if col == "protocol":
                    return (r["protocol"] or "").lower()
                if col == "title":
                    return (r["title"] or "").lower()
                if col == "url":
                    return (r["url"] or "").lower()
            except (KeyError, IndexError, TypeError):
                return ""
            return ""

        self._last_rows.sort(key=keyfn, reverse=descending)
        # Update the heading text with an arrow so users can see direction.
        for c in self.results["columns"]:
            arrow = ""
            if c == col:
                arrow = "  ▼" if descending else "  ▲"
            self.results.heading(c, text=f"{c}{arrow}")
        # Reuse _populate_results — it will redraw with the new order and
        # keep the iid → index mapping consistent.
        rows = list(self._last_rows)
        self._populate_results(rows)

    # ---- stats / info ----------------------------------------------------

    def _show_stats(self) -> None:
        """Kick off a stats query off the UI thread. The aggregate queries can
        scan the whole pages/findings tables and stall the Tk event loop on a
        large DB — punt them to a worker and render via the queue."""
        if self._busy.get("stats"):
            return  # ignore double-clicks while a query is in flight
        self._set_busy("stats", True)
        self._log_segments([("muted", "· computing stats…")])
        threading.Thread(target=self._stats_worker, daemon=True).start()

    def _stats_worker(self) -> None:
        try:
            page_stats = self.storage.stats()
            find_stats = self.storage.findings_stats()
        except Exception as e:
            self._post("stats_done", (None, None, f"{type(e).__name__}: {e}"))
            return
        self._post("stats_done", (page_stats, find_stats, None))

    def _render_stats(self, page_stats: dict, find_stats: dict) -> None:
        # Format counts with thousands separators — a populated DB can hit
        # six- or seven-figure page counts and "1234567" is hard to read.
        per_proto = page_stats.get("by_protocol") or {}
        per_cat = find_stats.get("by_category") or {}
        self._log_segments([("title", "▓▒░ darkcat stats ░▒▓")])
        self._log_segments([
            ("muted", "  pages: "),
            ("ok", f"{page_stats.get('total_pages', 0):,}"),
            ("muted", "   links: "),
            ("ok", f"{page_stats.get('links', 0):,}"),
            ("muted", "   findings: "),
            ("ok", f"{find_stats.get('total', 0):,}"),
        ])
        if per_proto:
            parts: list = [("muted", "  by protocol: ")]
            for k, v in sorted(per_proto.items(), key=lambda kv: -kv[1]):
                parts.append(("info", f"{k}="))
                parts.append(("ok", f"{v:,}"))
                parts.append(("muted", "  "))
            self._log_segments(parts)
        if per_cat:
            parts = [("muted", "  by finding:  ")]
            for k, v in sorted(per_cat.items(), key=lambda kv: -kv[1]):
                parts.append(("info", f"{k}="))
                parts.append(("ok", f"{v:,}"))
                parts.append(("muted", "  "))
            self._log_segments(parts)

    # ---- export ----------------------------------------------------------

    def _export_results(self) -> None:
        """Dump the currently displayed results table to a plain-text file."""
        if self._busy.get("export"):
            return
        rows = list(self._last_rows or [])
        if not rows:
            self._log_segments([
                ("warn", "✗ nothing to export — run a crawl or hit refresh first"),
            ])
            return
        default_name = time.strftime("darkcat-results-%Y%m%d-%H%M%S.txt")
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export results",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        # Pre-compute categories on the worker so we don't block the UI thread
        # for big result sets. Pass plain dicts so the worker doesn't touch
        # the sqlite3 connection.
        snapshot = [
            {
                "score": r["score"], "protocol": r["protocol"],
                "title": r["title"], "url": r["url"],
                "category": self._row_category(r),
            }
            for r in rows
        ]
        self._set_busy("export", True)
        self._log_segments([
            ("info", "▶ "),
            ("title", "export "),
            ("muted", f"{len(snapshot)} row(s) → "),
            ("url", path),
            ("muted", "  · writing…"),
        ])
        threading.Thread(
            target=self._export_worker, args=(path, snapshot), daemon=True,
        ).start()

    def _export_worker(self, path: str, snapshot: list[dict]) -> None:
        try:
            self._write_export(path, snapshot)
        except OSError as e:
            self._post("export_done", (False, path, len(snapshot), str(e)))
            return
        self._post("export_done", (True, path, len(snapshot), None))

    @staticmethod
    def _write_export(path: str, snapshot: list[dict]) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        header = (
            f"# darkcat export — {ts}\n"
            f"# {len(snapshot)} result(s)\n"
            f"# columns: score  category  protocol  title  url\n"
            "# " + "-" * 76 + "\n"
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(header)
            for s in snapshot:
                title = (s.get("title") or "").replace("\n", " ").replace("\t", " ")
                try:
                    score = float(s.get("score") or 0.0)
                except (TypeError, ValueError):
                    score = 0.0
                fh.write(
                    f"{score:>6.2f}\t{s.get('category') or '—':<24}\t"
                    f"{(s.get('protocol') or '?'):<10}\t"
                    f"{title}\t{s.get('url') or ''}\n"
                )

    # ---- busy state / validation helpers -------------------------------

    def _set_busy(self, op: str, value: bool) -> None:
        """Toggle the in-flight flag for an operation and (de)activate the
        relevant button so the user can't double-fire it."""
        self._busy[op] = value
        btn = {
            "search":  self.search_btn,
            "fetch":   self.fetch_btn,
            "results": self.refresh_btn,
            "export":  self.export_btn,
            "stats":   getattr(self, "stats_btn", None),
        }.get(op)
        if btn is not None:
            try:
                btn.configure(state=("disabled" if value else "normal"))
            except tk.TclError:
                pass

    def _read_int_clamped(
        self, var: tk.StringVar, default: int, lo: int, hi: int, label: str,
    ) -> int:
        """Parse ``var`` as int and clamp to [lo, hi]. Logs a warning on
        invalid input or out-of-range values, but never raises."""
        raw = (var.get() or "").strip() or str(default)
        try:
            n = int(raw)
        except ValueError:
            self._log_segments([
                ("warn", f"⚠ {label}={raw!r} is not a number — using {default}"),
            ])
            return default
        if n < lo or n > hi:
            clamped = max(lo, min(hi, n))
            self._log_segments([
                ("warn", f"⚠ {label}={n} out of range [{lo}, {hi}] — clamped to {clamped}"),
            ])
            var.set(str(clamped))
            return clamped
        return n

    def _read_float_clamped(
        self, var: tk.StringVar, default: float, lo: float, hi: float, label: str,
    ) -> float:
        raw = (var.get() or "").strip() or str(default)
        try:
            x = float(raw)
        except ValueError:
            self._log_segments([
                ("warn", f"⚠ {label}={raw!r} is not a number — using {default}"),
            ])
            return default
        if x < lo or x > hi:
            clamped = max(lo, min(hi, x))
            self._log_segments([
                ("warn", f"⚠ {label}={x} out of range [{lo}, {hi}] — clamped to {clamped}"),
            ])
            var.set(f"{clamped:g}")
            return clamped
        return x

    # ---- log ------------------------------------------------------------

    def _log(self, msg: str, *, tag: str = "info") -> None:
        try:
            self.log.configure(state="normal")
            self.log.insert("end", msg + "\n", (tag,))
            self._enforce_log_cap()
            self.log.see("end")
            self.log.configure(state="disabled")
        except tk.TclError:
            pass

    def _log_segments(self, segments) -> None:
        """Append a single line composed of (tag, text) segments — for colored events."""
        try:
            self.log.configure(state="normal")
            for tag, text in segments:
                self.log.insert("end", text, (tag,))
            self.log.insert("end", "\n")
            self._enforce_log_cap()
            self.log.see("end")
            self.log.configure(state="disabled")
        except tk.TclError:
            pass

    def _enforce_log_cap(self) -> None:
        """Trim the oldest 10% of lines once the buffer exceeds _LOG_LINE_CAP.
        Trimming in chunks (rather than line-by-line) keeps the cost amortised
        so long-running crawls don't slow the log down."""
        try:
            end_line = int(self.log.index("end-1c").split(".")[0])
        except (tk.TclError, ValueError):
            return
        if end_line <= _LOG_LINE_CAP:
            return
        # Trim back to ~90% of the cap so we don't trim again on every insert.
        keep_from = max(2, end_line - int(_LOG_LINE_CAP * 0.9))
        try:
            self.log.delete("1.0", f"{keep_from}.0")
        except tk.TclError:
            pass

    # ---- run ------------------------------------------------------------

    def run(self) -> int:
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()
        return 0

    def _on_close(self) -> None:
        # If a crawl is in flight, ask before tearing it down — saves users
        # from accidentally losing a long-running fetch with a stray Ctrl+Q.
        if self._active_crawler is not None:
            confirm = messagebox.askyesno(
                "darkcat",
                "A crawl is currently running.\n\nStop it and quit?",
                parent=self.root, icon="warning", default="no",
            )
            if not confirm:
                return
            try:
                self._active_crawler.stop()
            except Exception:
                pass
            # Give the crawler thread a brief grace window to notice the stop
            # event and exit cleanly. We don't join() — that could hang the UI
            # if a fetch is mid-flight on a slow transport.
            for _ in range(20):  # ~1 s @ 50 ms
                if self._active_crawler is None:
                    break
                self.root.update()
                self.root.after(50)
        # Clean up animation timers so they don't fire after destroy.
        self._scan_alive = False
        # Tear down resources in reverse-init order: fetcher first (it may hold
        # HTTP sessions / cookie jars), then storage. Each step swallows its
        # own exception so a failure in one doesn't leak the others.
        fetcher = getattr(self, "fetcher", None)
        if fetcher is not None:
            close = getattr(fetcher, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        try:
            self.storage.close()
        except Exception:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def run_gui(cfg: Config) -> int:
    return DarkcatGUI(cfg).run()
