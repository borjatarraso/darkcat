"""Textual TUI for darkcat — phosphor-CRT / matrix dark theme."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    Static,
)

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
    BTN_CRAWL,
    BTN_FETCH,
    BTN_REFRESH,
    BTN_SEARCH,
    BTN_STOP,
    LOGO,
    LOGO_MINI,
    TAGLINE,
    about_panel,
)
from darkcat.topic_filter import TopicFilter


class BannerBar(Static):
    """Single-line ASCII logo strip + tagline at the top of the app.

    A compact nyan-cat rainbow trail sits right after the title — its
    colours rotate every tick to fake the original GIF's left-scrolling
    trail, and the cat sprite bobs ±1 row to fake flight.
    """

    # Rainbow stripe colours from the original nyan-cat trail (R/O/Y/G/B/V).
    _NYAN_COLORS = ("#fe0000", "#ff9000", "#f8ff01", "#1bbf20", "#549eff", "#6c0aff")
    # Cat sprite, alternated between two poses for a tiny bob.
    _NYAN_POSES = ("≡^•⩊•^≡", "≡⌒•⩊•⌒≡")
    _TICK_SECS = 0.18

    def __init__(self, **kw) -> None:
        super().__init__("", markup=True, **kw)
        self._phase = 0

    def on_mount(self) -> None:
        self._render()
        # Anchor the wobble to wall-clock so we don't drift if the event
        # loop is busy — set_interval is best-effort, not real-time.
        self.set_interval(self._TICK_SECS, self._tick)

    def _tick(self) -> None:
        self._phase += 1
        self._render()

    def _render(self) -> None:
        # Rotate colours: shift the palette one slot left each tick.
        cols = self._NYAN_COLORS
        n = len(cols)
        rot = [cols[(i + self._phase) % n] for i in range(n)]
        trail = "".join(f"[{fg} on {fg}]██[/]" for fg in rot)
        cat = self._NYAN_POSES[self._phase % len(self._NYAN_POSES)]
        text = (
            f"[bold #ff00aa]▓▒░[/] [bold #00ff66]{LOGO_MINI[4:-4]}[/]"
            f" [bold #ff00aa]░▒▓[/]  "
            f"{trail}[#808080]{cat}[/]  "
            f"[#00e5ff]v{__version__}[/]   "
            f"[italic #5c8c70]{TAGLINE}[/]"
        )
        self.update(text)


class ScoreHelp(Static):
    """Inline caption that explains what `score` and `category` mean.

    Sits just above the results table so users know what they're looking
    at without having to hunt for a tooltip. Press ``?`` to dump the full
    formula into the log.
    """

    def __init__(self, **kw) -> None:
        super().__init__(
            "[#5c8c70]score = topic-keyword frequency / log(words+10) "
            "·  category = keyword classifier (hack, drugs, legal, …)  "
            "·  press [bold #ff00aa]?[/] for details[/]",
            markup=True, **kw,
        )


class TransportPill(Static):
    """Single clickable LED pill for one transport.

    Click → asks the parent app to toggle the daemon (start/stop) and
    stream the internal commands (and the daemon's stdout) into the log.
    """

    DEFAULT_CSS = """
    TransportPill {
        height: 1;
        padding: 0 1;
        margin: 0 1 0 0;
        content-align: center middle;
        background: #ff1a4b;
        color: black;
        text-style: bold;
    }
    TransportPill.-up { background: #00ff66; }
    TransportPill:hover { text-style: bold reverse; }
    """

    def __init__(self, proto: Protocol, ok: bool = False, **kw) -> None:
        self.proto = proto
        glyph = "●" if ok else "○"
        super().__init__(f" {glyph} {proto.value.upper()} ", markup=True, **kw)
        self.set_class(ok, "-up")

    def update_state(self, ok: bool) -> None:
        glyph = "●" if ok else "○"
        self.update(f" {glyph} {self.proto.value.upper()} ")
        self.set_class(ok, "-up")

    def on_click(self) -> None:
        # Bubble to the App-level handler so all the work runs from one place.
        self.app.toggle_transport(self.proto)


class StatusBar(Horizontal):
    """Row of TransportPill widgets + summary count.

    Acts as the container that knows how to refresh every pill from a
    single `fetcher.status()` snapshot. Pills are children — clicks live
    on the pills themselves.
    """

    DEFAULT_CSS = """
    StatusBar { height: 3; padding: 1; }
    StatusBar > .summary { width: auto; padding: 0 2 0 0; color: #00e5ff; text-style: bold; }
    """

    def __init__(self, fetcher: Fetcher, **kw) -> None:
        super().__init__(**kw)
        self.fetcher = fetcher
        self._pills: dict[Protocol, TransportPill] = {}
        self._summary: Optional[Static] = None

    def compose(self) -> ComposeResult:
        self._summary = Static(
            "[bold #ff00aa]▓▒░ TRANSPORTS[/]  [#ffb000]◌ scanning…[/]  ",
            classes="summary", markup=True,
        )
        yield self._summary
        # Pills are added lazily on the first refresh — we don't yet know
        # the transport list at compose time without running the probe.

    def refresh_status(self) -> None:
        try:
            statuses = self.fetcher.status()
        except Exception as e:
            if self._summary is not None:
                self._summary.update(
                    f"[bold #ff1a4b]✗ status probe failed:[/] [#ffb000]{e}[/]"
                )
            return
        up = sum(1 for ok in statuses.values() if ok)
        total = len(statuses)
        if self._summary is not None:
            self._summary.update(
                f"[bold #ff00aa]▓▒░ TRANSPORTS[/]  "
                f"[bold #00e5ff]{up}[/][#5c8c70]/[/][bold #00e5ff]{total}[/] "
                f"[#5c8c70]UP[/]  "
            )
        for p, ok in statuses.items():
            pill = self._pills.get(p)
            if pill is None:
                pill = TransportPill(p, ok)
                self._pills[p] = pill
                self.mount(pill)
            else:
                pill.update_state(ok)


class SudoPasswordScreen(ModalScreen[Optional[str]]):
    """Modal for an in-app sudo prompt — password masked with •.

    Dismissed with the typed password (or ``None`` on cancel). The host
    app marshals worker-thread requests onto the UI loop with
    ``call_from_thread(self.push_screen, ...)`` and blocks on a
    threading.Event until ``dismiss()`` runs.

    Textual's built-in ``Input(password=True)`` masks with ``•`` rather
    than ``*``; functionally equivalent — the field is unreadable.
    """

    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=True),
    ]

    DEFAULT_CSS = """
    SudoPasswordScreen {
        align: center middle;
        background: rgba(0,0,0,0.6);
    }
    SudoPasswordScreen #sudo-card {
        width: 60;
        max-width: 80%;
        height: auto;
        border: round #ff00aa;
        background: #050a06;
        padding: 1 2;
    }
    SudoPasswordScreen #sudo-title {
        color: #ff00aa;
        text-style: bold;
        margin-bottom: 1;
    }
    SudoPasswordScreen #sudo-prompt {
        color: #5c8c70;
        margin-bottom: 1;
    }
    SudoPasswordScreen #sudo-input {
        margin-bottom: 1;
    }
    SudoPasswordScreen #sudo-buttons {
        height: 3;
        align-horizontal: right;
    }
    SudoPasswordScreen Button {
        margin-left: 2;
    }
    """

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="sudo-card"):
            yield Static("› sudo password", id="sudo-title")
            yield Static(self._prompt.rstrip(": "), id="sudo-prompt")
            yield Input(
                password=True, placeholder="(masked)",
                id="sudo-input",
            )
            with Horizontal(id="sudo-buttons"):
                yield Button("Cancel", id="sudo-cancel", variant="default")
                yield Button("OK", id="sudo-ok", variant="primary")

    def on_mount(self) -> None:
        try:
            self.query_one("#sudo-input", Input).focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "sudo-input":
            self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "sudo-ok":
            self._submit()
        elif event.button.id == "sudo-cancel":
            self.action_cancel()

    def _submit(self) -> None:
        try:
            value = self.query_one("#sudo-input", Input).value
        except Exception:
            value = ""
        self.dismiss(value or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


_KEYMAP_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Main menus (Function keys)", [
        ("F1",  "About darkcat (logo, version, license, source)"),
        ("F2",  "This keymap"),
        ("F3",  "Chat hub — aggregated multi-protocol view"),
        ("F4",  "Mail console (SMTP / IMAP per persona)"),
        ("F5",  "Identity vault (new / confirm / launch / burn)"),
        ("F6",  "Add mail persona (preset picker)"),
        ("F7",  "Doctor — self-checks for transports, deps, vault"),
        ("F8",  "Database statistics"),
        ("F9",  "Near-duplicate mirrors of the selected row"),
        ("F10", "Text-snapshot history of the selected row"),
        ("F11", "Examples cheatsheet — common workflows"),
        ("F12", "Quit (asks for confirmation if a crawl is active)"),
    ]),
    ("Run a crawl", [
        ("Crawl button / Enter in form", "Start a crawl with the current form values"),
        ("Stop button / Ctrl+C",         "Abort the active crawl"),
        ("R",                            "Refresh the results table"),
        ("Ctrl+R",                       "Re-probe transports (rescan status pills)"),
    ]),
    ("Inspect a result", [
        ("Click row / arrow keys",       "Move the row cursor"),
        ("Ctrl+Y",                       "Copy the highlighted URL to the clipboard"),
        ("Ctrl+E",                       "Export current results to JSONL"),
        ("?",                            "Score / category formula explanation"),
    ]),
    ("Search & fetch", [
        ("Type in 'search' + Enter",     "Run an FTS5 search across crawled pages"),
        ("Type in 'fetch URL' + Enter",  "Fetch one URL through the right transport"),
    ]),
    ("Letter aliases (kept for muscle memory)", [
        ("i", "Identity vault (same as F5)"),
        ("c", "Chat console — per-persona send/check (the hub is F3)"),
        ("m", "Mail console (same as F4)"),
        ("p", "Add mail persona (same as F6)"),
        ("d", "Doctor (same as F7)"),
        ("q", "Quit (same as F12)"),
    ]),
]


class KeymapScreen(ModalScreen[None]):
    """Modal listing every TUI binding grouped by intent.

    Bound to F2 from the main app. Closes on Esc / F2 / q / Enter. Built
    from a static table so it stays correct even if a binding's `show=False`
    hides it from the Footer.
    """

    BINDINGS = [
        Binding("escape", "close", "close", show=True),
        Binding("f2",     "close", "close", show=False),
        Binding("q",      "close", "close", show=False),
        Binding("enter",  "close", "close", show=False),
    ]

    DEFAULT_CSS = """
    KeymapScreen {
        align: center middle;
        background: rgba(0,0,0,0.6);
    }
    KeymapScreen #keymap-card {
        width: 78;
        max-width: 90%;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        background: #050a06;
        border: heavy #ff00aa;
    }
    KeymapScreen #keymap-title {
        color: #00e5ff;
        text-style: bold;
        padding-bottom: 1;
    }
    KeymapScreen .keymap-group {
        color: #ff00aa;
        text-style: bold;
        padding-top: 1;
    }
    KeymapScreen .keymap-row {
        color: #00ff66;
    }
    KeymapScreen #keymap-hint {
        color: #5c8c70;
        padding-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="keymap-card"):
            yield Static("darkcat — keyboard shortcuts", id="keymap-title")
            for group_title, items in _KEYMAP_GROUPS:
                yield Static(group_title, classes="keymap-group")
                for keys, desc in items:
                    yield Static(
                        f"  [#00e5ff]{keys:<32}[/]  [#00ff66]{desc}[/]",
                        markup=True, classes="keymap-row",
                    )
            yield Static(
                "Press Esc / F2 / q / Enter to close.", id="keymap-hint",
            )

    def action_close(self) -> None:
        self.dismiss(None)


class AboutScreen(ModalScreen[None]):
    """Modal "About darkcat" — half-block logo + version + license + URL.

    Bound to F1 from the main app. Closes on Esc / F1 / q. The panel is
    rendered once at compose time; logo cell width is fixed so the modal
    keeps the same shape on a 80-col or 200-col terminal.
    """

    BINDINGS = [
        Binding("escape", "close", "close", show=True),
        Binding("f1",     "close", "close", show=False),
        Binding("q",      "close", "close", show=False),
        Binding("enter",  "close", "close", show=False),
    ]

    DEFAULT_CSS = """
    AboutScreen {
        align: center middle;
        background: rgba(0,0,0,0.6);
    }
    AboutScreen #about-card {
        width: auto;
        max-width: 90%;
        height: auto;
        padding: 0;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="about-card"):
            yield Static(
                about_panel(
                    __version__, url=__url__, license_str=__license__, logo_cols=28,
                ),
            )

    def action_close(self) -> None:
        self.dismiss(None)


def _needs_first_run() -> bool:
    """True when ``~/.darkcat`` is missing — the wizard pops up only on a
    truly first run, never on a re-launch where the user has clearly already
    chosen to skip init."""
    from darkcat.personas import default_dir as _persona_dir
    return not _persona_dir().exists()


class WelcomeScreen(ModalScreen[bool]):
    """First-run wizard. Shown once when ``~/.darkcat`` doesn't exist yet.

    Returns True if the user picked "Run init", False if they chose "Skip".
    The caller is responsible for actually running ``cmd_init`` — keeping the
    screen pure means the same modal works for any consumer.
    """

    BINDINGS = [
        Binding("escape", "skip",   "skip",   show=True),
        Binding("enter",  "accept", "init",   show=True),
        Binding("y",      "accept", "init",   show=False),
        Binding("n",      "skip",   "skip",   show=False),
    ]

    DEFAULT_CSS = """
    WelcomeScreen {
        align: center middle;
        background: rgba(0,0,0,0.6);
    }
    WelcomeScreen #welcome-card {
        width: 72;
        max-width: 90%;
        height: auto;
        padding: 1 2;
        background: #050a06;
        border: heavy #ff00aa;
    }
    WelcomeScreen #welcome-title {
        color: #00e5ff;
        text-style: bold;
        padding-bottom: 1;
    }
    WelcomeScreen .welcome-line {
        color: #00ff66;
    }
    WelcomeScreen .welcome-step {
        color: #5c8c70;
        padding-left: 2;
    }
    WelcomeScreen #welcome-buttons {
        height: 3;
        padding-top: 1;
        align-horizontal: center;
    }
    WelcomeScreen Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        from darkcat.personas import default_dir as _persona_dir
        home = _persona_dir()
        with Vertical(id="welcome-card"):
            yield Static("Welcome to darkcat", id="welcome-title")
            yield Static(
                f"It looks like this is your first run — [#00e5ff]{home}[/] "
                "doesn't exist yet.", classes="welcome-line", markup=True,
            )
            yield Static(
                "\n[bold #ff00aa]Run init now?[/] It will:",
                classes="welcome-line", markup=True,
            )
            yield Static("• create the home directory (mode 0700)",
                         classes="welcome-step")
            yield Static("• set up the SQLite database for crawled pages",
                         classes="welcome-step")
            yield Static("• probe transport reachability (Tor, I2P, …)",
                         classes="welcome-step")
            yield Static(
                "\n[#5c8c70]Press[/] [#00e5ff]Enter[/] / [#00e5ff]Y[/] "
                "[#5c8c70]to run init, or[/] [#00e5ff]Esc[/] / "
                "[#00e5ff]N[/] [#5c8c70]to skip.[/]",
                classes="welcome-line", markup=True,
            )
            with Horizontal(id="welcome-buttons"):
                yield Button("Run init", id="welcome-accept", variant="success")
                yield Button("Skip",     id="welcome-skip",   variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "welcome-accept":
            self.action_accept()
        else:
            self.action_skip()

    def action_accept(self) -> None:
        self.dismiss(True)

    def action_skip(self) -> None:
        self.dismiss(False)


class ResultScreen(ModalScreen[None]):
    """Generic scrollable text dump — used wherever we want to render the
    captured stdout from `invoke_cli_capturing` without truncating it
    into a notify. The body is fixed-width so tables align."""

    BINDINGS = [
        Binding("escape", "close", "close", show=True),
        Binding("q",      "close", "close", show=False),
    ]

    DEFAULT_CSS = """
    ResultScreen { align: center middle; background: rgba(0,0,0,0.7); }
    ResultScreen #card {
        width: 100; max-width: 95%; height: auto; max-height: 90%;
        padding: 1 2; background: #050a06; border: heavy #ff00aa;
    }
    ResultScreen #title { color: #00e5ff; text-style: bold; padding-bottom: 1; }
    ResultScreen RichLog { background: #0a1108; color: #00ff66;
        border: solid #5c8c70; height: auto; max-height: 32; }
    ResultScreen #close-row { height: 3; padding-top: 1; align-horizontal: right; }
    """

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="card"):
            yield Static(self._title, id="title")
            log = RichLog(highlight=False, markup=False, wrap=False)
            yield log
            with Horizontal(id="close-row"):
                yield Button("Close", id="close", variant="default")

    def on_mount(self) -> None:
        log = self.query_one(RichLog)
        for line in self._body.splitlines() or ["(no output)"]:
            log.write(line)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class LinkScreen(ModalScreen[Optional[dict]]):
    """Sub-modal: pick parent + child personas for `identity link`.

    Returns ``{'parent','child'}`` on submit, ``None`` on cancel. The
    parent is the recovery account (e.g. ProtonMail used to confirm a
    Reddit signup); the child is the protected one.
    """

    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=True),
        Binding("enter",  "submit", "submit", show=True),
    ]

    DEFAULT_CSS = """
    LinkScreen { align: center middle; background: rgba(0,0,0,0.7); }
    LinkScreen #card {
        width: 64; max-width: 90%; height: auto;
        padding: 1 2; background: #050a06; border: heavy #ff00aa;
    }
    LinkScreen #title { color: #00e5ff; text-style: bold; padding-bottom: 1; }
    LinkScreen Label { color: #5c8c70; padding-top: 1; }
    LinkScreen Select { background: #0a1108; color: #00ff66; border: solid #5c8c70; }
    LinkScreen #buttons { height: 3; padding-top: 1; align-horizontal: center; }
    """

    def __init__(self, names: list[str], default_child: Optional[str] = None,
                 verb: str = "Link") -> None:
        super().__init__()
        self._names = names
        self._default_child = default_child
        self._verb = verb

    def compose(self) -> ComposeResult:
        options = [(n, n) for n in self._names]
        with Vertical(id="card"):
            yield Static(f"{self._verb} identities", id="title")
            yield Static(
                "Parent = the recovery account (e.g. ProtonMail). "
                "Child = the protected one (e.g. Reddit).",
                id="hint",
            )
            yield Label("Parent")
            yield Select(options, id="parent",
                         value=options[0][1] if options else "",
                         allow_blank=False)
            yield Label("Child")
            yield Select(
                options, id="child",
                value=self._default_child or (options[0][1] if options else ""),
                allow_blank=False,
            )
            with Horizontal(id="buttons"):
                yield Button(self._verb, id="submit", variant="success")
                yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit()
        else:
            self.action_cancel()

    def action_submit(self) -> None:
        parent = self.query_one("#parent", Select).value
        child = self.query_one("#child", Select).value
        if not parent or not child or parent == child:
            return
        self.dismiss({"parent": parent, "child": child})

    def action_cancel(self) -> None:
        self.dismiss(None)


class PassphraseScreen(ModalScreen[Optional[str]]):
    """Single-shot passphrase prompt for an encrypted vault. Returns the
    typed string on submit or ``None`` on cancel."""

    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=True),
        Binding("enter",  "submit", "submit", show=True),
    ]

    DEFAULT_CSS = """
    PassphraseScreen { align: center middle; background: rgba(0,0,0,0.8); }
    PassphraseScreen #card {
        width: 56; height: auto;
        padding: 1 2; background: #050a06; border: heavy #ff00aa;
    }
    PassphraseScreen #title { color: #00e5ff; text-style: bold; padding-bottom: 1; }
    PassphraseScreen Label { color: #5c8c70; padding-top: 1; }
    PassphraseScreen Input { background: #0a1108; color: #00ff66; border: solid #5c8c70; }
    PassphraseScreen #buttons { height: 3; padding-top: 1; align-horizontal: center; }
    """

    def __init__(self, prompt: str = "Vault passphrase") -> None:
        super().__init__()
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="card"):
            yield Static(self._prompt, id="title")
            yield Label("Passphrase")
            yield Input(password=True, id="passphrase")
            with Horizontal(id="buttons"):
                yield Button("Unlock", id="submit", variant="success")
                yield Button("Cancel", id="cancel", variant="default")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit()
        else:
            self.action_cancel()

    def action_submit(self) -> None:
        pw = self.query_one(Input).value
        if not pw:
            return
        self.dismiss(pw)

    def action_cancel(self) -> None:
        self.dismiss(None)


class IdentityNewScreen(ModalScreen[Optional[dict]]):
    """Sub-modal: collect provider / purpose / transport for a new identity.

    Returns a dict ``{'provider', 'purpose', 'transport'}`` on submit, or
    ``None`` on cancel. The parent screen does the actual vault work so
    error handling stays in one place.
    """

    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=True),
        Binding("enter",  "submit", "submit", show=True),
    ]

    DEFAULT_CSS = """
    IdentityNewScreen { align: center middle; background: rgba(0,0,0,0.7); }
    IdentityNewScreen #card {
        width: 60; max-width: 90%; height: auto;
        padding: 1 2; background: #050a06; border: heavy #ff00aa;
    }
    IdentityNewScreen #title {
        color: #00e5ff; text-style: bold; padding-bottom: 1;
    }
    IdentityNewScreen Label { color: #5c8c70; padding-top: 1; }
    IdentityNewScreen Input, IdentityNewScreen Select {
        background: #0a1108; color: #00ff66; border: solid #5c8c70;
    }
    IdentityNewScreen #buttons {
        height: 3; padding-top: 1; align-horizontal: center;
    }
    """

    def compose(self) -> ComposeResult:
        from darkcat.identity import providers as provreg
        provreg.load_all()
        provider_options = [
            (f"{p.display_name} ({p.category})", p.slug)
            for p in sorted(provreg.registered(), key=lambda x: x.slug)
        ]
        with Vertical(id="card"):
            yield Static("New identity", id="title")
            yield Label("Provider")
            yield Select(provider_options, id="provider", allow_blank=False)
            yield Label("Instance (host)")
            yield Select(
                [("(default / N/A)", "")],
                id="instance", value="", allow_blank=False,
            )
            yield Label("Transport")
            yield Select(
                [("Tor", "tor"), ("I2P", "i2p"), ("Proxy", "proxy")],
                id="transport", value="tor", allow_blank=False,
            )
            yield Label("Purpose tag (optional)")
            yield Input(placeholder="e.g. research-forum-X", id="purpose")
            with Horizontal(id="buttons"):
                yield Button("Create", id="submit", variant="success")
                yield Button("Cancel", id="cancel", variant="default")

    def on_mount(self) -> None:
        # Populate the instance picker for whichever provider is selected
        # by default so users see the choices without first re-picking the
        # provider.
        provider = self.query_one("#provider", Select).value
        if provider:
            self._refresh_instances(str(provider))

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "provider" and event.value:
            self._refresh_instances(str(event.value))

    def _refresh_instances(self, provider_slug: str) -> None:
        from darkcat.identity import providers as provreg
        prof = provreg.get(provider_slug)
        sel = self.query_one("#instance", Select)
        if prof is None or not prof.instances:
            sel.set_options([("(default / N/A)", "")])
            sel.value = ""
            return
        opts: list[tuple[str, str]] = [("(provider default)", "")]
        for suffix, _url, note in prof.instances:
            label = f"{suffix} — {note}" if note else suffix
            opts.append((label, suffix))
        sel.set_options(opts)
        sel.value = ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit()
        else:
            self.action_cancel()

    def action_submit(self) -> None:
        provider = self.query_one("#provider", Select).value
        transport = self.query_one("#transport", Select).value
        purpose = self.query_one("#purpose", Input).value.strip() or None
        instance = self.query_one("#instance", Select).value or None
        if not provider or not transport:
            return
        self.dismiss({
            "provider": provider, "transport": transport,
            "purpose": purpose, "instance": instance,
        })

    def action_cancel(self) -> None:
        self.dismiss(None)


class IdentityEditScreen(ModalScreen[Optional[dict]]):
    """Sub-modal: edit credential fields on an existing identity.

    Returns ``None`` on cancel, otherwise a dict whose keys map 1:1 onto
    the ``identity edit`` CLI flags. Only keys whose values were changed
    are included so the dispatcher can decide what to forward.
    """

    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=True),
        Binding("enter",  "submit", "submit", show=True),
    ]

    DEFAULT_CSS = """
    IdentityEditScreen { align: center middle; background: rgba(0,0,0,0.7); }
    IdentityEditScreen #card {
        width: 72; max-width: 95%; height: auto;
        padding: 1 2; background: #050a06; border: heavy #ff00aa;
    }
    IdentityEditScreen #title {
        color: #00e5ff; text-style: bold; padding-bottom: 1;
    }
    IdentityEditScreen Label { color: #5c8c70; padding-top: 1; }
    IdentityEditScreen Input {
        background: #0a1108; color: #00ff66; border: solid #5c8c70;
    }
    IdentityEditScreen #buttons {
        height: 3; padding-top: 1; align-horizontal: center;
    }
    IdentityEditScreen #note {
        color: #5c8c70; padding-bottom: 1;
    }
    """

    def __init__(self, persona) -> None:
        super().__init__()
        self.persona = persona

    def compose(self) -> ComposeResult:
        p = self.persona
        with Vertical(id="card"):
            yield Static(f"Edit credentials — {p.name}", id="title")
            yield Static(
                "Leave a field unchanged to keep the current value. "
                "Empty strings on optional fields clear them. New "
                "recovery codes are appended (comma-separated).",
                id="note",
            )
            yield Label("Handle / username")
            yield Input(value=p.handle or "", id="handle")
            yield Label("Email")
            yield Input(value=p.email or "", id="email")
            yield Label("Recovery email")
            yield Input(value=p.recovery_email or "", id="recovery_email")
            yield Label("Display name")
            yield Input(value=p.display_name or "", id="display_name")
            yield Label("Recovery phrase / BIP-39")
            yield Input(value=p.recovery or "", id="recovery", password=True)
            yield Label(
                f"Add recovery codes (current: {len(p.recovery_codes)})"
            )
            yield Input(placeholder="aaa-bbb, ccc-ddd", id="recovery_codes")
            yield Label("Notes")
            yield Input(value=p.notes or "", id="notes")
            with Horizontal(id="buttons"):
                yield Button("Save", id="submit", variant="success")
                yield Button("Rotate password", id="rotate", variant="warning")
                yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit()
        elif event.button.id == "rotate":
            self.dismiss({"_action": "rotate-password"})
        else:
            self.action_cancel()

    def action_submit(self) -> None:
        p = self.persona
        payload: dict[str, object] = {"_action": "edit"}

        def _changed(field_id: str, current: Optional[str]) -> Optional[str]:
            new = self.query_one(f"#{field_id}", Input).value
            cur = current or ""
            if new == cur:
                return None
            return new

        for fid, cur in (
            ("handle",         p.handle),
            ("email",          p.email),
            ("recovery_email", p.recovery_email),
            ("display_name",   p.display_name),
            ("recovery",       p.recovery),
            ("notes",          p.notes),
        ):
            v = _changed(fid, cur)
            if v is not None:
                payload[fid] = v

        codes_raw = self.query_one("#recovery_codes", Input).value.strip()
        if codes_raw:
            payload["recovery_codes"] = [
                c.strip() for c in codes_raw.split(",") if c.strip()
            ]

        if len(payload) == 1:  # nothing besides the _action marker
            self.dismiss(None)
            return
        self.dismiss(payload)

    def action_cancel(self) -> None:
        self.dismiss(None)


# Sentinel Select value used by ChatScreen / MailScreen while the
# vault is still locked. ``_persona()`` maps it back to empty so the
# CLI dispatcher reports "persona is required" rather than seeing the
# placeholder leak through. Mounted on encrypted vaults; replaced by
# real persona names once ``_refresh_personas`` runs post-unlock.
_PERSONA_PENDING = "__persona_pending__"


class _VaultUnlockMixin:
    """Shared passphrase-prompt + env-var-threading machinery.

    Originally a private helper on ``IdentityScreen``. Mail and chat
    consoles need the same trick (prompt for the passphrase once,
    cache it for the modal's lifetime, expose it to the CLI handler
    via ``DARKCAT_VAULT_PASSPHRASE``) so encrypted vaults work in
    every console — without that, ``cmd_mail`` / ``cmd_chat`` fall
    through to ``getpass.getpass()`` which blocks under Textual.

    Contract for subclasses:

    * set ``self._passphrase: Optional[str] = None`` in ``__init__``
    * inherit (also) from a Textual ``Screen`` so ``self.app`` and
      ``self.notify`` are wired up
    * call ``self._unlock_then(...)`` before any work that opens the
      vault; call ``self._run_with_passphrase(ns)`` to dispatch the
      CLI with the env var in scope
    """

    _passphrase: Optional[str]

    def _vault_is_encrypted(self) -> bool:
        from darkcat import personas as pv
        path = pv.vault_path()
        return path.exists() and path.suffix == ".gpg"

    def _open_inner_or_notify(self):
        """Best-effort vault open using the cached passphrase. Returns
        the inner Vault on success, or None after pushing a notify."""
        from darkcat import personas as pv
        try:
            return pv.Vault(path=pv.vault_path(),
                            passphrase=self._passphrase)
        except RuntimeError as e:
            self.notify(f"could not open vault: {e}",
                        severity="error", timeout=6)
            return None

    def _unlock_then(self, callback) -> None:
        """If the vault is encrypted and we don't yet have a passphrase,
        push the PassphraseScreen and invoke ``callback`` once the user
        provides one that decrypts. Otherwise call ``callback`` directly.
        Wrong-passphrase loops re-prompt until cancel."""
        if not self._vault_is_encrypted() or self._passphrase is not None:
            callback()
            return

        def _on_pw(pw: Optional[str]) -> None:
            if pw is None:
                self.notify("vault locked — close and reopen to retry",
                            severity="warning", timeout=4)
                return
            from darkcat import personas as pv
            try:
                pv.Vault(path=pv.vault_path(), passphrase=pw)
            except RuntimeError as e:
                self.notify(f"wrong passphrase: {e}",
                            severity="error", timeout=4)
                self._unlock_then(callback)
                return
            self._passphrase = pw
            callback()

        self.app.push_screen(PassphraseScreen("Vault is encrypted"), _on_pw)

    def _run_with_passphrase(self, ns) -> tuple[int, str, str]:
        """Invoke ``invoke_cli_capturing`` with the cached passphrase in
        scope via ``DARKCAT_VAULT_PASSPHRASE``. Restores the env var on
        exit so it doesn't leak to unrelated callers."""
        import os as _os
        from darkcat.identity import invoke_cli_capturing
        saved = _os.environ.get("DARKCAT_VAULT_PASSPHRASE")
        if self._passphrase is not None:
            _os.environ["DARKCAT_VAULT_PASSPHRASE"] = self._passphrase
        try:
            return invoke_cli_capturing(self.cfg, ns)
        except SystemExit as e:
            return (int(e.code) if isinstance(e.code, int) else 2, "", "")
        except Exception as e:
            return (2, "", f"{type(e).__name__}: {e}")
        finally:
            if self._passphrase is not None:
                if saved is None:
                    _os.environ.pop("DARKCAT_VAULT_PASSPHRASE", None)
                else:
                    _os.environ["DARKCAT_VAULT_PASSPHRASE"] = saved


class IdentityScreen(_VaultUnlockMixin, ModalScreen[None]):
    """Identity vault browser — list / new / confirm / burn.

    Reads the persona vault. Encrypted vaults trigger a PassphraseScreen
    on first access; the verified passphrase is cached on the screen
    instance and threaded into each CLI dispatch via the mixin so the
    operator types it once per session. Highlights the selected row;
    n/c/b act on it.
    """

    BINDINGS = [
        Binding("escape", "close",   "close",   show=True),
        Binding("q",      "close",   "close",   show=False),
        Binding("n",      "new",     "new",     show=True),
        Binding("l",      "launch",  "launch",  show=True),
        Binding("c",      "confirm", "confirm", show=True),
        Binding("s",      "show",    "show",    show=True),
        Binding("e",      "edit",    "edit",    show=True),
        Binding("i",      "link",    "link",    show=True),
        Binding("u",      "unlink",  "unlink",  show=True),
        Binding("b",      "burn",    "burn",    show=True),
        Binding("r",      "refresh", "refresh", show=True),
    ]

    DEFAULT_CSS = """
    IdentityScreen { align: center middle; background: rgba(0,0,0,0.7); }
    IdentityScreen #card {
        width: 100; max-width: 95%; height: auto; max-height: 90%;
        padding: 1 2; background: #050a06; border: heavy #ff00aa;
    }
    IdentityScreen #title {
        color: #00e5ff; text-style: bold; padding-bottom: 1;
    }
    IdentityScreen #hint {
        color: #5c8c70; padding-top: 1;
    }
    IdentityScreen DataTable {
        background: #0a1108; color: #00ff66;
        border: solid #5c8c70;
    }
    """

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        # Cached vault passphrase for the duration of the screen — set
        # lazily by the PassphraseScreen the first time we encounter an
        # encrypted vault. Cleared on dismiss.
        self._passphrase: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Vertical(id="card"):
            yield Static("Identities", id="title")
            yield DataTable(id="id-table", cursor_type="row")
            yield Static(
                "[#00e5ff]N[/]ew  [#00e5ff]L[/]aunch  [#00e5ff]C[/]onfirm  "
                "[#00e5ff]S[/]how  [#00e5ff]E[/]dit  "
                "L[#00e5ff]i[/]nk  [#00e5ff]U[/]nlink  "
                "[#00e5ff]B[/]urn  [#00e5ff]R[/]efresh  [#00e5ff]Esc[/] close",
                id="hint", markup=True,
            )

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns("NAME", "PROVIDER", "STATUS", "PURPOSE", "CREATED")
        self._unlock_then(self._refresh)

    # ---- vault helpers ---------------------------------------------------
    # ``_vault_is_encrypted``, ``_open_inner_or_notify``, and
    # ``_unlock_then`` live on ``_VaultUnlockMixin`` so MailScreen /
    # ChatScreen can reuse the same passphrase-prompt + cache machinery.

    def _refresh(self) -> None:
        from darkcat.identity import IdentityVault
        inner = self._open_inner_or_notify()
        if inner is None:
            return
        vault = IdentityVault(inner)
        rows = vault.all_identities()
        t = self.query_one(DataTable)
        t.clear()
        if not rows:
            return
        for p in rows:
            created = time.strftime("%Y-%m-%d", time.localtime(p.created_at))
            t.add_row(
                p.name, p.provider or "-", p.status,
                p.purpose_tag or "-", created,
                key=p.name,
            )

    def _selected_name(self) -> Optional[str]:
        t = self.query_one(DataTable)
        if t.row_count == 0:
            return None
        try:
            row_key = t.coordinate_to_cell_key(t.cursor_coordinate).row_key
        except Exception:
            return None
        return str(row_key.value) if row_key.value else None

    def action_close(self) -> None:
        self.dismiss(None)

    def action_refresh(self) -> None:
        self._refresh()

    def action_new(self) -> None:
        def _on_done(payload: Optional[dict]) -> None:
            if not payload:
                return
            self._create_identity(**payload)
        self.app.push_screen(IdentityNewScreen(), _on_done)

    def _run(self, ns) -> tuple[int, str, str]:
        return self._run_with_passphrase(ns)

    @staticmethod
    def _last_error_line(stderr: str) -> str:
        for line in reversed(stderr.splitlines()):
            line = line.strip()
            if line:
                return line
        return "operation failed"

    def _create_identity(
        self,
        *,
        provider: str,
        transport: str,
        purpose: Optional[str],
        instance: Optional[str] = None,
    ) -> None:
        import argparse as _argparse
        ns = _argparse.Namespace(
            cmd="identity", action="new",
            provider=provider, transport=transport, purpose=purpose,
            name=None, instance=instance, recovery_email=None,
            cap=None, force=False, password_length=24,
            proxy_url=None, pin_to=None,
            launch=False, json=False,
        )
        rc, _out, err = self._run(ns)
        if rc == 0:
            label = f"{provider} ({instance})" if instance else provider
            self.notify(f"created identity for {label}", timeout=3)
        else:
            self.notify(self._last_error_line(err),
                        severity="error", timeout=6)
        self._refresh()

    def action_confirm(self) -> None:
        name = self._selected_name()
        if not name:
            self.notify("select a row first", severity="warning", timeout=3)
            return
        import argparse as _argparse
        ns = _argparse.Namespace(cmd="identity", action="confirm", name=name)
        rc, _out, err = self._run(ns)
        if rc == 0:
            self.notify(f"confirmed {name}", timeout=3)
        else:
            self.notify(self._last_error_line(err),
                        severity="error", timeout=6)
        self._refresh()

    def action_burn(self) -> None:
        name = self._selected_name()
        if not name:
            self.notify("select a row first", severity="warning", timeout=3)
            return
        import argparse as _argparse
        ns = _argparse.Namespace(
            cmd="identity", action="burn", name=name, note=None,
        )
        rc, _out, err = self._run(ns)
        if rc == 0:
            self.notify(f"burned {name}", timeout=3, severity="warning")
        else:
            self.notify(self._last_error_line(err),
                        severity="error", timeout=6)
        self._refresh()

    def action_edit(self) -> None:
        name = self._selected_name()
        if not name:
            self.notify("select a row first", severity="warning", timeout=3)
            return

        def _go() -> None:
            inner = self._open_inner_or_notify()
            if inner is None:
                return
            p = inner.get(name)
            if p is None:
                self.notify(f"{name!r} no longer in vault",
                            severity="error", timeout=5)
                self._refresh()
                return

            def _on_done(payload: Optional[dict]) -> None:
                if not payload:
                    return
                self._apply_edit(name, payload)

            self.app.push_screen(IdentityEditScreen(p), _on_done)

        self._unlock_then(_go)

    def _apply_edit(self, name: str, payload: dict) -> None:
        import argparse as _argparse
        action = payload.pop("_action", "edit")
        if action == "rotate-password":
            ns = _argparse.Namespace(
                cmd="identity", action="rotate-password",
                name=name, length=24, print_new=False,
            )
            rc, _out, err = self._run(ns)
            if rc == 0:
                self.notify(f"rotated password for {name}", timeout=3)
            else:
                self.notify(self._last_error_line(err),
                            severity="error", timeout=6)
            self._refresh()
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
        rc, _out, err = self._run(ns)
        if rc == 0:
            self.notify(f"updated {name}", timeout=3)
        else:
            self.notify(self._last_error_line(err),
                        severity="error", timeout=6)
        self._refresh()

    def action_launch(self) -> None:
        name = self._selected_name()
        if not name:
            self.notify("select a row first", severity="warning", timeout=3)
            return
        import argparse as _argparse
        # capture=False here — the CLI capture path is interactive
        # readline, which doesn't compose with Textual. We push the
        # IdentityEditScreen below instead so the operator can fill in
        # the real handle / recovery codes via the same TUI surface.
        ns = _argparse.Namespace(
            cmd="identity", action="launch", name=name,
            no_spawn=False, capture=False,
        )
        rc, out, err = self._run(ns)
        if rc != 0:
            self.notify(self._last_error_line(err),
                        severity="error", timeout=6)
            return

        # First: dump the launch block so the operator can read the
        # signup-flow checklist while completing the form.
        self.app.push_screen(ResultScreen(
            f"Signup launched — {name}", out or "(launched)",
        ))

        # Then: open the edit form for the same persona so the values
        # the provider just showed once (handle, recovery codes,
        # recovery email) can be captured before they're lost.
        def _go() -> None:
            inner = self._open_inner_or_notify()
            if inner is None:
                return
            p = inner.get(name)
            if p is None:
                return

            def _on_done(payload: Optional[dict]) -> None:
                if not payload:
                    return
                self._apply_edit(name, payload)

            self.app.push_screen(IdentityEditScreen(p), _on_done)

        # call_later so the ResultScreen is on top first; the edit
        # screen pops up underneath, ready when the operator dismisses
        # the launch block with Escape.
        self.call_later(self._unlock_then, _go)

    def action_show(self) -> None:
        name = self._selected_name()
        if not name:
            self.notify("select a row first", severity="warning", timeout=3)
            return

        def _go(reveal: bool) -> None:
            import argparse as _argparse
            ns = _argparse.Namespace(
                cmd="identity", action="show", name=name,
                reveal=reveal, json=False,
            )
            rc, out, err = self._run(ns)
            if rc != 0:
                self.notify(self._last_error_line(err),
                            severity="error", timeout=6)
                return
            title = (f"{name} (revealed — handle with care)"
                     if reveal else f"{name} (masked — press R to reveal)")
            self.app.push_screen(ResultScreen(title, out or "(no data)"))

        def _on_confirm(yes: bool) -> None:
            _go(reveal=yes)

        # Two-step: first ask whether to reveal secrets. Plain show is
        # always safe; reveal needs an explicit yes since the password
        # and recovery codes hit the screen.
        self.app.push_screen(
            ConfirmRevealScreen(name),
            _on_confirm,
        )

    def action_link(self) -> None:
        self._link_or_unlink(verb="link")

    def action_unlink(self) -> None:
        self._link_or_unlink(verb="unlink")

    def _link_or_unlink(self, *, verb: str) -> None:
        def _go() -> None:
            inner = self._open_inner_or_notify()
            if inner is None:
                return
            names = [
                p.name for p in inner.personas
                if p.provider  # only identity rows
            ]
            if len(names) < 2:
                self.notify(
                    "need at least two identities to link",
                    severity="warning", timeout=4,
                )
                return
            default_child = self._selected_name()

            def _on_picked(payload: Optional[dict]) -> None:
                if not payload:
                    return
                import argparse as _argparse
                ns = _argparse.Namespace(
                    cmd="identity", action=verb,
                    parent=payload["parent"], child=payload["child"],
                )
                rc, _out, err = self._run(ns)
                if rc == 0:
                    self.notify(
                        f"{verb}ed {payload['parent']} → {payload['child']}",
                        timeout=3,
                    )
                else:
                    self.notify(self._last_error_line(err),
                                severity="error", timeout=6)

            self.app.push_screen(
                LinkScreen(names, default_child=default_child,
                           verb=verb.capitalize()),
                _on_picked,
            )

        self._unlock_then(_go)


class ConfirmRevealScreen(ModalScreen[bool]):
    """Two-button modal: reveal secrets or just show masked view.

    Returns ``True`` to reveal (password + recovery codes in plaintext),
    ``False`` for the masked view. Dismissing with Escape is treated as
    "masked" — never accidentally reveal.
    """

    BINDINGS = [
        Binding("escape", "no",  "masked",  show=True),
        Binding("y",      "yes", "reveal",  show=True),
        Binding("n",      "no",  "masked",  show=True),
    ]

    DEFAULT_CSS = """
    ConfirmRevealScreen { align: center middle; background: rgba(0,0,0,0.7); }
    ConfirmRevealScreen #card {
        width: 60; height: auto;
        padding: 1 2; background: #050a06; border: heavy #ff00aa;
    }
    ConfirmRevealScreen #title { color: #00e5ff; text-style: bold; padding-bottom: 1; }
    ConfirmRevealScreen #body { color: #5c8c70; padding-bottom: 1; }
    ConfirmRevealScreen #buttons { height: 3; padding-top: 1; align-horizontal: center; }
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    def compose(self) -> ComposeResult:
        with Vertical(id="card"):
            yield Static(f"Show {self._name}", id="title")
            yield Static(
                "Reveal password and recovery codes in plaintext on screen? "
                "Choose 'Masked' if anyone is shoulder-surfing.",
                id="body",
            )
            with Horizontal(id="buttons"):
                yield Button("Masked", id="masked", variant="default")
                yield Button("Reveal", id="reveal", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "reveal")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class ChatScreen(_VaultUnlockMixin, ModalScreen[None]):
    """Chat console — pick persona, action, fields → invoke ``cmd_chat``.

    Covers every action the CLI exposes: backends, login, list, read,
    send, ingest, join (Telegram), leave (Telegram), connect (SimpleX),
    addcontact (Session). Output is rendered in a RichLog at the bottom
    so multi-line tables and error blocks survive intact.
    """

    BINDINGS = [
        Binding("escape", "close", "close", show=True),
        Binding("ctrl+enter", "run", "run", show=True),
    ]

    DEFAULT_CSS = """
    ChatScreen { align: center middle; background: rgba(0,0,0,0.7); }
    ChatScreen #card {
        width: 110; max-width: 96%; height: auto; max-height: 92%;
        padding: 1 2; background: #050a06; border: heavy #ff00aa;
    }
    ChatScreen #title { color: #00e5ff; text-style: bold; padding-bottom: 1; }
    ChatScreen Label { color: #5c8c70; padding-top: 1; }
    ChatScreen Input, ChatScreen Select {
        background: #0a1108; color: #00ff66; border: solid #5c8c70;
    }
    ChatScreen RichLog {
        height: 14; background: #0a1108; color: #00ff66;
        border: solid #5c8c70; margin-top: 1;
    }
    ChatScreen #buttons { height: 3; padding-top: 1; align-horizontal: center; }
    ChatScreen #presets { height: 3; padding-top: 1; align-horizontal: center; }
    ChatScreen #presets Button { margin: 0 1; }
    """

    # Quick-action presets — one click sets network + action so the
    # operator doesn't have to navigate two dropdowns for the common
    # verbs. Tuple shape: (button_label, button_id, network, action).
    _PRESETS = (
        ("Telegram Join",   "preset-tg-join",      "telegram", "join"),
        ("Telegram Leave",  "preset-tg-leave",     "telegram", "leave"),
        ("Add Session",     "preset-session-add",  "session",  "addcontact"),
        ("Accept SimpleX",  "preset-simplex-conn", "simplex",  "connect"),
        ("Login",           "preset-login",        "",         "login"),
        ("List",            "preset-list",         "",         "list"),
        ("Backends",        "preset-backends",     "",         "backends"),
    )

    _ACTIONS = (
        ("backends — list installed chat backends", "backends"),
        ("login — authenticate this persona", "login"),
        ("list — channels / DMs / groups", "list"),
        ("read — last N messages from a channel", "read"),
        ("send — post a message to a channel", "send"),
        ("ingest — store channel history in DB", "ingest"),
        ("join — Telegram public/private join", "join"),
        ("leave — Telegram leave by id", "leave"),
        ("connect — SimpleX accept invite link", "connect"),
        ("addcontact — Session add peer ID", "addcontact"),
    )

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self._passphrase: Optional[str] = None

    def compose(self) -> ComposeResult:
        from darkcat import personas as pv
        # Plain vaults populate the Select directly. Encrypted vaults
        # yield a placeholder Select; ``on_mount`` then prompts for the
        # passphrase and calls ``set_options`` once the vault opens, so
        # the operator sees the real persona list instead of a free-form
        # Input. Empty / missing vaults still drop to the Input fallback.
        persona_options: list[tuple[str, str]] = []
        encrypted = False
        try:
            path = pv.vault_path()
            encrypted = path.exists() and path.suffix == ".gpg"
            if path.exists() and not encrypted:
                v = pv.Vault(path=path)
                for p in v.personas:
                    persona_options.append((f"{p.name} ({p.network or '-'})", p.name))
        except Exception:
            pass

        with Vertical(id="card"):
            yield Static("Chat console", id="title")
            yield Label("Quick actions")
            with Horizontal(id="presets"):
                for label, btn_id, _net, _act in self._PRESETS:
                    yield Button(label, id=btn_id, variant="primary")
            yield Label("Persona")
            if encrypted:
                yield Select(
                    [("(unlock to load personas)", _PERSONA_PENDING)],
                    id="persona", allow_blank=False, value=_PERSONA_PENDING,
                )
            elif persona_options:
                yield Select(persona_options, id="persona", allow_blank=False)
            else:
                yield Input(placeholder="persona name", id="persona-text")
            yield Label("Network (overrides persona)")
            yield Select(
                [("(persona default)", ""),
                 ("telegram", "telegram"),
                 ("matrix", "matrix"),
                 ("xmpp", "xmpp"),
                 ("simplex", "simplex"),
                 ("session", "session")],
                value="", id="network", allow_blank=False,
            )
            yield Label("Action")
            yield Select(list(self._ACTIONS), id="action",
                         value="list", allow_blank=False)
            yield Label("Target / channel id / invite link / peer id")
            yield Input(placeholder="@channel | -100… | direct:42 | 05<hex> | https://t.me/+…",
                        id="target")
            yield Label("Message body (for `send`) — or limit/N for read/ingest")
            yield Input(placeholder="hello", id="body")
            yield RichLog(id="chat-log", highlight=True, markup=True, wrap=True)
            with Horizontal(id="buttons"):
                yield Button("Run", id="submit", variant="success")
                yield Button("Close", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "submit":
            self.action_run()
            return
        if bid == "cancel":
            self.action_close()
            return
        if bid.startswith("preset-"):
            for _label, preset_id, net, act in self._PRESETS:
                if preset_id == bid:
                    self._apply_preset(net, act)
                    return

    def _apply_preset(self, network: str, action: str) -> None:
        """Pre-fill the network + action dropdowns from one click."""
        try:
            self.query_one("#network", Select).value = network
        except Exception:
            pass
        try:
            self.query_one("#action", Select).value = action
        except Exception:
            pass
        try:
            log = self.query_one("#chat-log", RichLog)
            hint = {
                "join":       "expects @channel | https://t.me/+invite | numeric id",
                "leave":      "expects numeric channel id",
                "addcontact": "expects 66-hex Session ID; body = optional nickname",
                "connect":    "expects https://simplex.chat/contact#... or simplex:/...",
                "login":      "no target needed; press Run",
                "list":       "no target needed; press Run",
                "backends":   "no target needed; press Run",
            }.get(action, "")
            if hint:
                log.write(f"[#00e5ff]hint:[/] {hint}")
        except Exception:
            pass
        try:
            if action in ("login", "list", "backends"):
                self.query_one("#submit", Button).focus()
            else:
                self.query_one("#target", Input).focus()
        except Exception:
            pass

    def on_mount(self) -> None:
        # Encrypted vaults need a passphrase before we can list personas;
        # unlock now so the Select carries real names by the time the
        # operator interacts with it, instead of waiting until Run.
        if self._vault_is_encrypted():
            self._unlock_then(self._refresh_personas)

    def _refresh_personas(self) -> None:
        """Re-populate the persona Select after a successful unlock. Done
        in-place via ``set_options`` so the layout doesn't reflow."""
        inner = self._open_inner_or_notify()
        if inner is None:
            return
        options = [(f"{p.name} ({p.network or '-'})", p.name)
                   for p in inner.personas]
        if not options:
            self.notify("vault has no personas yet", severity="warning",
                        timeout=4)
            return
        try:
            sel = self.query_one("#persona", Select)
            sel.set_options(options)
            sel.value = options[0][1]
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss(None)

    def _persona(self) -> str:
        try:
            v = self.query_one("#persona", Select).value
            if v == _PERSONA_PENDING:
                return ""
            return v or ""
        except Exception:
            try:
                return self.query_one("#persona-text", Input).value.strip()
            except Exception:
                return ""

    def action_run(self) -> None:
        import argparse as _argparse

        persona = self._persona()
        action = self.query_one("#action", Select).value or "list"
        network = self.query_one("#network", Select).value or None
        target = self.query_one("#target", Input).value.strip()
        body = self.query_one("#body", Input).value.strip()

        log = self.query_one("#chat-log", RichLog)
        if not persona and action != "backends":
            log.write("[red]error:[/] persona is required")
            return

        ns_kwargs: dict = {"cmd": "chat", "action": action, "persona": persona,
                           "network": network, "json": False}
        if action == "backends":
            pass
        elif action == "login":
            pass
        elif action == "list":
            ns_kwargs["limit"] = 100
        elif action == "read":
            try:
                ns_kwargs["limit"] = int(body) if body else 30
            except ValueError:
                ns_kwargs["limit"] = 30
            ns_kwargs["channel_id"] = target
        elif action == "send":
            ns_kwargs["channel_id"] = target
            ns_kwargs["message"] = body
        elif action == "ingest":
            try:
                ns_kwargs["limit"] = int(body) if body else 200
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
            ns_kwargs["name"] = body or None

        ns = _argparse.Namespace(**ns_kwargs)

        def _go() -> None:
            rc, out, err = self._run_with_passphrase(ns)
            if out:
                log.write(out.rstrip())
            if err:
                log.write(f"[red]{err.rstrip()}[/]")
            log.write(f"[#5c8c70]-- exit {rc} --[/]")

        # If the vault is encrypted we need the passphrase before the
        # CLI hits ``_load_persona_or_die``; that helper falls back to
        # ``getpass.getpass()`` which would block under Textual. Unlock
        # first, then dispatch.
        self._unlock_then(_go)


class MailScreen(_VaultUnlockMixin, ModalScreen[None]):
    """Mail console — send and check email via persona SMTP/IMAP."""

    BINDINGS = [
        Binding("escape", "close", "close", show=True),
        Binding("ctrl+enter", "run", "run", show=True),
    ]

    DEFAULT_CSS = """
    MailScreen { align: center middle; background: rgba(0,0,0,0.7); }
    MailScreen #card {
        width: 110; max-width: 96%; height: auto; max-height: 92%;
        padding: 1 2; background: #050a06; border: heavy #ff00aa;
    }
    MailScreen #title { color: #00e5ff; text-style: bold; padding-bottom: 1; }
    MailScreen Label { color: #5c8c70; padding-top: 1; }
    MailScreen Input, MailScreen Select {
        background: #0a1108; color: #00ff66; border: solid #5c8c70;
    }
    MailScreen RichLog {
        height: 14; background: #0a1108; color: #00ff66;
        border: solid #5c8c70; margin-top: 1;
    }
    MailScreen #buttons { height: 3; padding-top: 1; align-horizontal: center; }
    """

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self._passphrase: Optional[str] = None

    def compose(self) -> ComposeResult:
        from darkcat import personas as pv
        # Same pre-populate pattern as ChatScreen: plain vault populates
        # the Select; encrypted vault gets a placeholder and ``on_mount``
        # fills the real list after the operator unlocks.
        persona_options: list[tuple[str, str]] = []
        encrypted = False
        try:
            path = pv.vault_path()
            encrypted = path.exists() and path.suffix == ".gpg"
            if path.exists() and not encrypted:
                v = pv.Vault(path=path)
                persona_options = [(f"{p.name} ({p.site or '-'})", p.name)
                                   for p in v.personas]
        except Exception:
            pass

        with Vertical(id="card"):
            yield Static("Mail console", id="title")
            yield Label("Persona")
            if encrypted:
                yield Select(
                    [("(unlock to load personas)", _PERSONA_PENDING)],
                    id="persona", allow_blank=False, value=_PERSONA_PENDING,
                )
            elif persona_options:
                yield Select(persona_options, id="persona", allow_blank=False)
            else:
                yield Input(placeholder="persona name", id="persona-text")
            yield Label("Action")
            yield Select(
                [("send — compose and send", "send"),
                 ("check — recent INBOX headers", "check")],
                value="send", id="action", allow_blank=False,
            )
            yield Label("To (comma-separated)")
            yield Input(placeholder="alice@example.com, bob@example.com", id="to")
            yield Label("CC (comma-separated, send only)")
            yield Input(placeholder="optional", id="cc")
            yield Label("BCC (comma-separated, send only)")
            yield Input(placeholder="optional", id="bcc")
            yield Label("Reply-To (send only)")
            yield Input(placeholder="optional", id="reply-to")
            yield Label("Subject (send) / folder (check)")
            yield Input(placeholder="hello / INBOX", id="subject")
            yield Label("Body (send) / limit (check, default 25)")
            yield Input(placeholder="message text or 25", id="body")
            yield RichLog(id="mail-log", highlight=True, markup=True, wrap=True)
            with Horizontal(id="buttons"):
                yield Button("Run", id="submit", variant="success")
                yield Button("Close", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_run()
        else:
            self.action_close()

    def on_mount(self) -> None:
        # Mirror ChatScreen: unlock encrypted vaults on open so the persona
        # Select carries real names before the operator hits Run.
        if self._vault_is_encrypted():
            self._unlock_then(self._refresh_personas)

    def _refresh_personas(self) -> None:
        """Re-populate the persona Select after unlock. Mail personas
        carry a ``site`` field (mail provider slug) rather than
        ``network`` — that's the only difference from ChatScreen."""
        inner = self._open_inner_or_notify()
        if inner is None:
            return
        options = [(f"{p.name} ({p.site or '-'})", p.name)
                   for p in inner.personas]
        if not options:
            self.notify("vault has no personas yet", severity="warning",
                        timeout=4)
            return
        try:
            sel = self.query_one("#persona", Select)
            sel.set_options(options)
            sel.value = options[0][1]
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss(None)

    def _persona(self) -> str:
        try:
            v = self.query_one("#persona", Select).value
            if v == _PERSONA_PENDING:
                return ""
            return v or ""
        except Exception:
            try:
                return self.query_one("#persona-text", Input).value.strip()
            except Exception:
                return ""

    def action_run(self) -> None:
        import argparse as _argparse

        persona = self._persona()
        action = self.query_one("#action", Select).value or "send"
        to_raw = self.query_one("#to", Input).value.strip()
        subj = self.query_one("#subject", Input).value.strip()
        body = self.query_one("#body", Input).value.strip()
        log = self.query_one("#mail-log", RichLog)

        if not persona:
            log.write("[red]error:[/] persona is required")
            return

        if action == "send":
            recipients = [s.strip() for s in to_raw.split(",") if s.strip()]
            if not recipients or not subj or not body:
                log.write("[red]error:[/] need to, subject, body")
                return
            cc_raw = self.query_one("#cc", Input).value.strip()
            bcc_raw = self.query_one("#bcc", Input).value.strip()
            reply_to = self.query_one("#reply-to", Input).value.strip() or None
            cc = [s.strip() for s in cc_raw.split(",") if s.strip()] or None
            bcc = [s.strip() for s in bcc_raw.split(",") if s.strip()] or None
            ns = _argparse.Namespace(
                cmd="mail", action="send", persona=persona,
                to=recipients, cc=cc, bcc=bcc, reply_to=reply_to,
                subject=subj, body=body, body_file=None, timeout=30.0,
            )
        else:
            try:
                limit = int(body) if body else 25
            except ValueError:
                limit = 25
            ns = _argparse.Namespace(
                cmd="mail", action="check", persona=persona,
                folder=subj or "INBOX", limit=limit, timeout=30.0,
                json=False,
            )

        def _go() -> None:
            rc, out, err = self._run_with_passphrase(ns)
            if out:
                log.write(out.rstrip())
            if err:
                log.write(f"[red]{err.rstrip()}[/]")
            log.write(f"[#5c8c70]-- exit {rc} --[/]")

        # Encrypted vault → prompt once via PassphraseScreen and cache,
        # then dispatch. ``cmd_mail`` reads the persona's SMTP/IMAP
        # creds from the vault, so without this it would fall through
        # to ``getpass.getpass()`` and hang under Textual.
        self._unlock_then(_go)


class PersonaAddScreen(ModalScreen[None]):
    """Add a mail-flavoured persona with a mail-provider preset picker.

    Mirrors ``personas add NAME --mail-provider SLUG`` so SMTP/IMAP
    host:port + TLS defaults land without manual typing. Operator
    overrides (network / site / notes) still win over the preset, same
    as the CLI handler.
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("ctrl+enter", "submit", "Add", show=True),
    ]

    DEFAULT_CSS = """
    PersonaAddScreen { align: center middle; background: rgba(0,0,0,0.7); }
    PersonaAddScreen #card {
        width: 80; max-width: 92%; height: auto; max-height: 92%;
        padding: 1 2; background: #050a06; border: heavy #ff00aa;
    }
    PersonaAddScreen #title { color: #00e5ff; text-style: bold; padding-bottom: 1; }
    PersonaAddScreen #hint  { color: #5c8c70; padding-bottom: 1; }
    PersonaAddScreen Label { color: #5c8c70; padding-top: 1; }
    PersonaAddScreen Input, PersonaAddScreen Select {
        background: #0a1108; color: #00ff66; border: solid #5c8c70;
    }
    PersonaAddScreen RichLog {
        height: 8; background: #0a1108; color: #00ff66;
        border: solid #5c8c70; margin-top: 1;
    }
    PersonaAddScreen #buttons { height: 3; padding-top: 1; align-horizontal: center; }
    """

    def __init__(self, cfg) -> None:
        super().__init__()
        self.cfg = cfg

    def compose(self) -> ComposeResult:
        from darkcat import mail_providers as _mp
        preset_options = [("(none — fill manually)", "")]
        for preset in _mp.all_presets():
            label = f"{preset.slug} — {preset.description.split(';')[0]}"
            preset_options.append((label, preset.slug))

        with Vertical(id="card"):
            yield Static("Add mail persona", id="title")
            yield Static(
                "Pick a mail-provider preset and SMTP/IMAP host, port, "
                "and TLS mode are filled in for you. Any field you "
                "override still wins over the preset.",
                id="hint",
            )
            yield Label("Name (unique persona id)")
            yield Input(id="name", placeholder="e.g. me-disroot")
            yield Label("Mail provider")
            yield Select(preset_options, id="preset", value="",
                         allow_blank=False)
            yield Label("Handle (e.g. alice@disroot.org)")
            yield Input(id="handle")
            yield Label("Email (optional)")
            yield Input(id="email")
            yield Label("Password (blank = autogenerate when --gen)")
            yield Input(id="password", password=True)
            yield Label("Network override (optional)")
            yield Input(id="network")
            yield Label("Site override (optional — e.g. host:port)")
            yield Input(id="site")
            yield Label("Notes override (optional)")
            yield Input(id="notes")
            yield Static("Auto-generate handle/password if blank: yes",
                         id="gen-hint")
            log = RichLog(highlight=False, markup=True, wrap=False)
            yield log
            with Horizontal(id="buttons"):
                yield Button("Add", id="submit", variant="success")
                yield Button("Close", id="close", variant="default")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.action_submit()
        else:
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        import argparse as _argparse
        from darkcat.identity import invoke_cli_capturing

        name = self.query_one("#name", Input).value.strip()
        if not name:
            self.notify("name is required", severity="warning", timeout=3)
            return
        preset_slug = self.query_one("#preset", Select).value or None
        ns = _argparse.Namespace(
            cmd="personas", action="add", name=name,
            network=self.query_one("#network", Input).value or "",
            site=self.query_one("#site", Input).value or "",
            handle=self.query_one("#handle", Input).value or None,
            password=self.query_one("#password", Input).value or None,
            email=self.query_one("#email", Input).value or None,
            pgp_key_id=None,
            recovery=None,
            notes=self.query_one("#notes", Input).value or None,
            user_agent=None,
            proxy=None,
            tags=[],
            gen=True,
            replace=False,
            mail_provider=preset_slug,
        )
        try:
            rc, out, err = invoke_cli_capturing(self.cfg, ns)
        except SystemExit as e:
            rc = int(e.code) if isinstance(e.code, int) else 2
            out, err = "", ""
        except Exception as e:
            rc, out, err = 2, "", f"{type(e).__name__}: {e}"

        log = self.query_one(RichLog)
        if out:
            log.write(out.rstrip())
        if err:
            log.write(f"[red]{err.rstrip()}[/]")
        log.write(f"[#5c8c70]-- exit {rc} --[/]")
        if rc == 0:
            self.notify(f"persona {name} added", timeout=3)


class DarkcatApp(App):
    CSS = """
    /* ----- darknet phosphor theme ------------------------------------ */

    Screen {
        layout: vertical;
        background: #050a06;
        color: #00ff66;
    }

    Header {
        background: #050a06;
        color: #ff00aa;
    }

    Footer {
        background: #050a06;
        color: #00e5ff;
    }
    Footer > .footer--key {
        background: #050a06;
        color: #ff00aa;
        text-style: bold;
    }
    Footer > .footer--description {
        background: #050a06;
        color: #00ff66;
    }

    #banner {
        height: 1;
        padding: 0 1;
        background: #050a06;
        color: #00ff66;
        border-bottom: heavy #ff00aa;
    }

    #status {
        height: 3;
        padding: 1;
        background: #080d09;
        color: #00ff66;
        border-bottom: heavy #ff00aa;
    }

    #form {
        height: auto;
        padding: 1;
        margin: 1 1 0 1;
        border: heavy #ff00aa;
        background: #050a06;
    }

    #form Input {
        width: 1fr;
        background: #080d09;
        color: #00ff66;
        border: tall #3a6b4c;
    }
    #form Input:focus { border: tall #00e5ff; }

    #form Select {
        width: 18;
        background: #080d09;
        color: #00ff66;
    }
    #form Select > SelectCurrent {
        background: #080d09;
        color: #00ff66;
        border: tall #3a6b4c;
    }
    #form Select:focus > SelectCurrent { border: tall #00e5ff; }

    #row1, #row2, #row3 { height: 3; margin-bottom: 1; }

    .lbl {
        content-align: left middle;
        padding: 0 1;
        width: auto;
        color: #00e5ff;
        text-style: bold;
    }

    Button {
        margin: 0 1;
        min-width: 14;
        background: #050a06;
        color: #00ff66;
        border: heavy #3a6b4c;
        text-style: bold;
    }
    Button:focus {
        border: heavy #00e5ff;
        color: #00e5ff;
        background: #080d09;
    }
    Button:hover  { background: #0a3320; color: #00e5ff; }
    Button.-primary {
        color: #ff00aa;
        border: heavy #ff00aa;
        text-style: bold;
    }
    Button.-primary:hover {
        background: #1a0033;
        color: #ff00aa;
    }
    Button.-error {
        color: #ff1a4b;
        border: heavy #ff1a4b;
    }
    Button.-error:hover { background: #330011; }

    #score-help {
        height: 1;
        padding: 0 1;
        margin: 0 1;
        background: #080d09;
        color: #5c8c70;
        border-top: heavy #ff00aa;
        border-bottom: heavy #ff00aa;
    }

    #content {
        height: 1fr;
        margin: 0 1 1 1;
    }

    #log {
        width: 1fr;
        border: heavy #ff00aa;
        background: #050a06;
        color: #00ff66;
    }

    #results {
        width: 1fr;
        border: heavy #ff00aa;
        background: #050a06;
        color: #00ff66;
    }

    DataTable {
        background: #050a06;
        color: #00ff66;
    }
    DataTable > .datatable--header {
        background: #050a06;
        color: #ff00aa;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: #1a0033;
        color: #ff00aa;
    }
    DataTable > .datatable--odd-row { background: #050a06; }
    DataTable > .datatable--even-row { background: #080d09; }
    """

    # Avoid ctrl+h / ctrl+i / ctrl+m — those share byte codes with Backspace,
    # Tab, and Enter in a TTY, so binding them would steal basic navigation
    # keys. Function keys are unambiguous on every modern terminal.
    #
    # F-keys are the canonical surface for top-level actions (F1..F12).
    # Letter keys remain as aliases for muscle memory but hidden from the
    # Footer to keep it readable.
    BINDINGS = [
        Binding("f1",            "show_about",       "About"),
        Binding("f2",            "show_keymap",      "Keys"),
        Binding("f3",            "show_chat_hub",    "ChatHub"),
        Binding("f4",            "show_mail",        "Mail"),
        Binding("f5",            "show_identity",    "Identity"),
        Binding("f6",            "show_persona_add", "Persona"),
        Binding("f7",            "show_doctor",      "Doctor"),
        Binding("f8",            "show_stats",       "Stats"),
        Binding("f9",            "mirrors_of_row",   "Mirrors"),
        Binding("f10",           "history_of_row",   "History"),
        Binding("f11",           "show_examples",    "Examples"),
        Binding("f12",           "quit",             "Quit"),
        Binding("r",             "refresh_results",  "Refresh"),
        Binding("ctrl+r",        "refresh_status",   "Rescan"),
        Binding("ctrl+e",        "export_results",   "Export"),
        Binding("ctrl+c",        "cancel_crawl",     "Abort"),
        Binding("ctrl+y",        "copy_url",         "Copy URL"),
        Binding("question_mark", "show_score_help",  "Score?"),
        # Letter aliases — hidden from Footer (F-keys are canonical).
        Binding("i", "show_identity",    "Identity", show=False),
        Binding("c", "show_chat",        "Chat",     show=False),
        Binding("m", "show_mail",        "Mail",     show=False),
        Binding("p", "show_persona_add", "Persona",  show=False),
        Binding("d", "show_doctor",      "Doctor",   show=False),
        Binding("q", "quit",             "Quit",     show=False),
    ]

    crawling: reactive[bool] = reactive(False)

    # Same bounds the GUI uses — keeps both surfaces in lockstep.
    _PAGES_RANGE = (1, 100_000)
    _DEPTH_RANGE = (0, 25)
    _THRESHOLD_RANGE = (0.0, 1_000.0)
    _LOG_MAX_LINES = 5000

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.fetcher = Fetcher(cfg)
        self.storage = Storage(cfg.db_path)
        self.control = TransportControl(cfg)
        self.control.set_password_provider(self._ask_sudo_password)
        self._active_crawler: Optional[Crawler] = None
        self._toggling: set[Protocol] = set()
        # Per-operation busy flags — disable the relevant button while the
        # worker is running so users can't double-fire long DB queries.
        self._busy: dict[str, bool] = {
            "search": False, "results": False, "fetch": False,
            "export": False, "stats": False, "mirrors": False, "history": False,
        }
        # Quit confirmation flag — first Q during a crawl asks, second quits.
        self._quit_armed: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield BannerBar(id="banner")
        yield StatusBar(self.fetcher, id="status")
        with Container(id="form"):
            with Horizontal(id="row1"):
                yield Label("Topics:", classes="lbl")
                yield Input(placeholder="whistleblower leak securedrop …", id="topics")
            with Horizontal(id="row2"):
                yield Label("Protocol:", classes="lbl")
                yield Select(
                    [(p, p) for p in (list(SEEDS_BY_PROTOCOL.keys()) + ["all"])],
                    value="tor",
                    id="protocol",
                    allow_blank=False,
                )
                yield Label("Max pages:", classes="lbl")
                yield Input(value="50", id="max_pages")
                yield Label("Max depth:", classes="lbl")
                yield Input(value="2", id="max_depth")
                yield Label("Threshold:", classes="lbl")
                yield Input(value="0", id="threshold")
            with Horizontal(id="row3"):
                crawl_btn = Button(BTN_CRAWL, variant="primary", id="crawl-btn")
                crawl_btn.tooltip = (
                    "Start a BFS crawl with the form values above. "
                    "Press Enter in any form field to fire this too."
                )
                yield crawl_btn
                stop_btn = Button(BTN_STOP, variant="error", id="stop-btn", disabled=True)
                stop_btn.tooltip = "Abort the active crawl (also Ctrl+C)."
                yield stop_btn
                search_in = Input(placeholder="search FTS5 …", id="search")
                search_in.tooltip = "FTS5 search across crawled pages. Enter to run."
                yield search_in
                search_btn = Button(BTN_SEARCH, id="search-btn")
                search_btn.tooltip = "Run the FTS5 search to the left."
                yield search_btn
                fetch_in = Input(placeholder="fetch URL …", id="fetch_url")
                fetch_in.tooltip = (
                    "Fetch one URL through the right transport (Tor/I2P/Gemini/…)."
                )
                yield fetch_in
                fetch_btn = Button(BTN_FETCH, id="fetch-btn")
                fetch_btn.tooltip = "Fetch the URL to the left through its transport."
                yield fetch_btn
        yield ScoreHelp(id="score-help")
        with Horizontal(id="content"):
            yield RichLog(
                highlight=True, markup=True, wrap=True,
                max_lines=self._LOG_MAX_LINES, id="log",
            )
            yield DataTable(id="results", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "darkcat"
        self.sub_title = "// multi-protocol darknet crawler"
        table = self.query_one("#results", DataTable)
        table.add_columns("score", "category", "proto", "title", "url")
        table.cursor_type = "row"
        # Cache of currently displayed rows for export (kept in display order).
        self._last_rows: list = []
        self.query_one(StatusBar).refresh_status()
        self.refresh_results()
        # Re-probe transports every 30 seconds so the pills stay live.
        self.set_interval(30.0, lambda: self.query_one(StatusBar).refresh_status())
        self._log(
            "[bold #ff00aa]▓▒░[/] [bold #00ff66]darkcat TUI online[/] "
            "[bold #ff00aa]░▒▓[/]  "
            "[#5c8c70]pick a protocol, set topics, hit[/] "
            f"[bold #ff00aa]{BTN_CRAWL}[/][#5c8c70].[/]"
        )
        self._log(
            "[#5c8c70]legend:[/]  "
            "[bold #00ff66]●[/] [#00ff66]reachable[/]   "
            "[bold #ff1a4b]○[/] [#ff1a4b]offline / not configured[/]"
        )
        if _needs_first_run():
            self.push_screen(WelcomeScreen(), self._on_welcome_done)

    def _on_welcome_done(self, accepted: Optional[bool]) -> None:
        """Wizard callback — run ``darkcat init`` synchronously when the user
        accepts. Errors are logged but never crash the TUI; the user can still
        invoke ``darkcat init`` from the CLI if anything goes sideways."""
        if not accepted:
            self._log("[#5c8c70]first-run init skipped — "
                      "use[/] [bold #00e5ff]darkcat init[/] [#5c8c70]later.[/]")
            return
        try:
            import argparse as _argparse
            from darkcat import cli as _cli
            ns = _argparse.Namespace(no_probe=False)
            _cli.cmd_init(self.cfg, ns)
            self._log("[bold #00ff66]✔ init complete — "
                      "[/][#00ff66]home directory ready.[/]")
            self.query_one(StatusBar).refresh_status()
        except Exception as exc:  # noqa: BLE001 — never crash the TUI
            self._log(f"[bold #ff1a4b]init failed:[/] [#ff1a4b]{exc}[/]")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.do_search()
        elif event.input.id == "fetch_url":
            self.do_fetch()
        elif event.input.id in ("topics", "max_pages", "max_depth", "threshold"):
            if not self.crawling:
                self.start_crawl()

    # --- actions -------------------------------------------------------------

    def action_refresh_status(self) -> None:
        self.query_one(StatusBar).refresh_status()

    def action_refresh_results(self) -> None:
        self.refresh_results()

    def action_cancel_crawl(self) -> None:
        if self._active_crawler:
            self._active_crawler.stop()
            self._log("[bold #ffb000]▣ stop requested[/]")

    def action_show_about(self) -> None:
        """Open the About modal — F1. Closes on Esc / F1 / q / Enter."""
        self.push_screen(AboutScreen())

    def action_show_keymap(self) -> None:
        """Open the Keymap modal — F2. Closes on Esc / F2 / q / Enter."""
        self.push_screen(KeymapScreen())

    def action_show_identity(self) -> None:
        """Open the Identity vault modal — i. List/new/confirm/burn."""
        self.push_screen(IdentityScreen(self.cfg))

    def action_show_chat(self) -> None:
        """Open the Chat console modal — c. Per-persona chat actions."""
        self.push_screen(ChatScreen(self.cfg))

    def action_show_mail(self) -> None:
        """Open the Mail console modal — m. Per-persona SMTP/IMAP."""
        self.push_screen(MailScreen(self.cfg))

    def action_show_persona_add(self) -> None:
        """Open the Add-mail-persona modal — p. Wraps `personas add`."""
        self.push_screen(PersonaAddScreen(self.cfg))

    def action_show_doctor(self) -> None:
        """Run the same self-checks as ``darkcat doctor`` and render them in
        a ResultScreen — F7 / d. CLI / REPL / GUI all have a doctor surface;
        this is the TUI's. Output is plain-text aligned (no markup) because
        ResultScreen renders verbatim — color parity with the CLI is a
        follow-up if it ever matters."""
        from darkcat.cli import doctor_run
        rows = doctor_run(self.cfg)
        glyphs = {"ok": "[OK]  ", "warn": "[WARN]", "fail": "[FAIL]"}
        lines: list[str] = []
        for level, label, detail, fix in rows:
            lines.append(f"{glyphs.get(level, '[?]')}  {label}")
            lines.append(f"           {detail}")
            if fix and level != "ok":
                lines.append(f"           fix: {fix}")
            lines.append("")
        body = "\n".join(lines) if lines else "(no checks ran)"
        self.push_screen(ResultScreen("darkcat doctor", body))

    def action_show_chat_hub(self) -> None:
        """Open the multi-protocol Chat hub — F3. Aggregates conversations
        from every logged-in chat backend (telegram, matrix, xmpp, simplex,
        session, tox, briar, ricochet) into one tree view.

        Phase 2 will replace this stub with the real ChatHubScreen. The
        binding is wired now so users discover the F3 slot from day one."""
        body = (
            "Multi-protocol chat hub — coming in Phase 2.\n\n"
            "The hub will aggregate conversations from every logged-in\n"
            "chat backend into one tree view, grouped by protocol and\n"
            "tagged by transport network (tor / i2p / clearnet).\n\n"
            "Until then, press 'c' to open the per-persona chat console\n"
            "(login / list / read / send / join / leave / connect)."
        )
        self.push_screen(ResultScreen("Chat hub", body))

    def action_show_examples(self) -> None:
        """Open the examples cheatsheet — F11. Curated worked examples for
        common workflows (signup, login, send-message, fetch-peer, enable
        transport, etc.) rendered with Rich markup.

        Phase 3 will replace this stub with the real ExamplesScreen. The
        binding is wired now so the F11 slot is reserved from day one."""
        body = (
            "Examples cheatsheet — coming in Phase 3.\n\n"
            "Will surface curated, copy-pasteable examples for:\n"
            "  - Create a persona / encrypt the vault\n"
            "  - Login to Telegram / Matrix / XMPP / Simplex / Session\n"
            "  - Send a message through Simplex / Session\n"
            "  - Login to ProtonMail / Tutanota / Disroot SMTP+IMAP\n"
            "  - Fetch a Tor / I2P / Gemini page\n"
            "  - Walk Tor / I2P peer lists\n"
            "  - Enable / re-probe transports\n"
            "Each entry shows the exact CLI / REPL / TUI / GUI path."
        )
        self.push_screen(ResultScreen("Examples", body))

    def action_show_score_help(self) -> None:
        """Dump the score / category formula into the log on `?`. Renders as
        a single multi-line block so RichLog wraps it cleanly without blank
        lines breaking the visual rhythm."""
        body = "\n".join(
            f"  [#5c8c70]{ln}[/]" if ln.strip() else "  "
            for ln in SCORE_HELP.splitlines()
        )
        self._log(
            "[bold #ff00aa]▓▒░ score / category help ░▒▓[/]\n" + body
        )

    def action_show_stats(self) -> None:
        """Kick off the stats query off the UI thread. Aggregate queries scan
        the whole pages/findings tables and stall the Textual event loop on
        a large DB — punt to a worker, render via call_from_thread."""
        if self._busy.get("stats"):
            return  # already computing — ignore double-press of F3
        self._busy["stats"] = True
        self._log("[#5c8c70]· computing stats…[/]")
        self.run_worker(self._stats_worker(), thread=True)

    def _stats_worker(self) -> None:
        try:
            page_stats = self.storage.stats()
            find_stats = self.storage.findings_stats()
        except Exception as e:
            self.call_from_thread(
                self._log,
                f"[bold #ff1a4b]✗ stats failed:[/] "
                f"[#ffb000]{type(e).__name__}: {self._esc(e)}[/]",
            )
            self.call_from_thread(self._busy.__setitem__, "stats", False)
            return
        self.call_from_thread(self._render_stats, page_stats, find_stats)
        self.call_from_thread(self._busy.__setitem__, "stats", False)

    def _render_stats(self, page_stats: dict, find_stats: dict) -> None:
        # Counts get thousands separators so six-digit page counts stay
        # legible — matches the CLI cmd_stats / GUI _render_stats output.
        per_proto = page_stats.get("by_protocol") or {}
        proto_block = "  ".join(
            f"[bold]{self._esc(k)}[/]=[#00ff66]{v:,}[/]"
            for k, v in sorted(per_proto.items(), key=lambda kv: -kv[1])
        ) or "[#5c8c70](none)[/]"
        per_cat = find_stats.get("by_category") or {}
        cat_block = "  ".join(
            f"[bold]{self._esc(k)}[/]=[#00ff66]{v:,}[/]"
            for k, v in sorted(per_cat.items(), key=lambda kv: -kv[1])
        ) or "[#5c8c70](none)[/]"
        self._log(
            "[bold #ff00aa]▓▒░ darkcat stats ░▒▓[/]\n"
            f"  [#5c8c70]pages:[/] [bold #00e5ff]{page_stats.get('total_pages', 0):,}[/]"
            f"   [#5c8c70]links:[/] [bold #00e5ff]{page_stats.get('links', 0):,}[/]"
            f"   [#5c8c70]findings:[/] [bold #00e5ff]{find_stats.get('total', 0):,}[/]\n"
            f"  [#5c8c70]by protocol:[/] {proto_block}\n"
            f"  [#5c8c70]by finding:[/]  {cat_block}"
        )

    def action_copy_url(self) -> None:
        """Copy the URL of the currently-selected results row to the system
        clipboard. Uses Textual's App.copy_to_clipboard so it works over SSH
        + OSC52 as well as on a local terminal."""
        url = self._selected_url()
        if not url:
            self._log("[#ffb000]⚠ no row selected — move the cursor first[/]")
            return
        try:
            self.copy_to_clipboard(url)
        except Exception as e:
            self._log(
                f"[bold #ff1a4b]✗ clipboard failed:[/] "
                f"[#ffb000]{type(e).__name__}: {self._esc(e)}[/]"
            )
            return
        self._log(
            f"[bold #00ff66]✓[/] [#5c8c70]copied →[/] "
            f"[underline #00e5ff]{self._esc(url)}[/]"
        )

    def action_mirrors_of_row(self) -> None:
        """Kick off a SimHash near-dup lookup off the UI thread."""
        if self._busy.get("mirrors"):
            return
        url = self._selected_url()
        if not url:
            self._log("[#ffb000]⚠ no row selected — move the cursor first[/]")
            return
        self._busy["mirrors"] = True
        self._log(f"[#5c8c70]· searching mirrors of[/] [underline #00e5ff]{self._esc(url)}[/]")
        self.run_worker(self._mirrors_worker(url), thread=True)

    def _mirrors_worker(self, url: str) -> None:
        try:
            rows = self.storage.near_duplicates_of(url, distance=3, limit=20)
        except Exception as e:
            self.call_from_thread(
                self._log,
                f"[bold #ff1a4b]✗ mirrors lookup failed:[/] "
                f"[#ffb000]{type(e).__name__}: {self._esc(e)}[/]",
            )
            self.call_from_thread(self._busy.__setitem__, "mirrors", False)
            return
        self.call_from_thread(self._render_mirrors, url, list(rows))
        self.call_from_thread(self._busy.__setitem__, "mirrors", False)

    def _render_mirrors(self, url: str, rows: list) -> None:
        head = (
            f"[bold #ff00aa]▓▒░ mirrors of[/] "
            f"[underline #00e5ff]{self._esc(url)}[/] "
            f"[bold #ff00aa]░▒▓[/]"
        )
        if not rows:
            self._log(
                head + "\n  [#5c8c70](none within Hamming distance ≤ 3 — "
                "try `mirrors --rebuild` from the CLI if you've never built "
                "the SimHash index)[/]"
            )
            return
        body = "\n".join(
            f"  [#5c8c70]d=[/][bold]{r['distance']:>2}[/]  "
            f"[underline #00e5ff]{self._esc(r['url'])}[/]"
            for r in rows
        )
        self._log(head + "\n" + body)

    def action_history_of_row(self) -> None:
        """Kick off a page-history lookup off the UI thread."""
        if self._busy.get("history"):
            return
        url = self._selected_url()
        if not url:
            self._log("[#ffb000]⚠ no row selected — move the cursor first[/]")
            return
        self._busy["history"] = True
        self._log(f"[#5c8c70]· loading history of[/] [underline #00e5ff]{self._esc(url)}[/]")
        self.run_worker(self._history_worker(url), thread=True)

    def _history_worker(self, url: str) -> None:
        try:
            rows = self.storage.page_history_for(url, limit=10)
        except Exception as e:
            self.call_from_thread(
                self._log,
                f"[bold #ff1a4b]✗ history lookup failed:[/] "
                f"[#ffb000]{type(e).__name__}: {self._esc(e)}[/]",
            )
            self.call_from_thread(self._busy.__setitem__, "history", False)
            return
        self.call_from_thread(self._render_history, url, list(rows))
        self.call_from_thread(self._busy.__setitem__, "history", False)

    def _render_history(self, url: str, rows: list) -> None:
        head = (
            f"[bold #ff00aa]▓▒░ history of[/] "
            f"[underline #00e5ff]{self._esc(url)}[/] "
            f"[bold #ff00aa]░▒▓[/]"
        )
        if not rows:
            self._log(head + "\n  [#5c8c70](no snapshots recorded)[/]")
            return
        body = "\n".join(
            f"  [bold]{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['captured_at']))}[/]  "
            f"[#5c8c70]score=[/][#00ff66]{(r['score'] or 0):>5.2f}[/]  "
            f"[#5c8c70]bytes=[/][#00ff66]{r['bytes'] or 0:>7}[/]  "
            f"[#5c8c70]hash=[/]{r['content_hash'][:12]}…"
            for r in rows
        )
        self._log(head + "\n" + body)

    def _selected_url(self) -> Optional[str]:
        """Return the URL of the currently-highlighted DataTable row, or
        None if no row is selected / the table is showing the placeholder."""
        try:
            table = self.query_one("#results", DataTable)
            cursor = table.cursor_row
        except Exception:
            return None
        rows = self._last_rows or []
        if cursor is None or cursor < 0 or cursor >= len(rows):
            return None
        try:
            url = rows[cursor]["url"]
        except (IndexError, KeyError, TypeError):
            return None
        return url or None

    def action_export_results(self) -> None:
        """Write the currently displayed rows to a timestamped .txt file.
        Tries CWD first; falls back to ~/ if CWD is read-only."""
        if self._busy.get("export"):
            return
        rows = getattr(self, "_last_rows", None) or []
        if not rows:
            self._log(
                "[#ffb000]✗ nothing to export — run a crawl or hit "
                "F5 to refresh first[/]"
            )
            return
        # Pre-compute categories on the UI thread (cheap regex scan), pass a
        # plain-dict snapshot to the worker so we don't share sqlite Rows.
        snapshot = [
            {
                "score": r["score"], "protocol": r["protocol"],
                "title": r["title"], "url": r["url"],
                "category": self._row_category(r),
            }
            for r in rows
        ]
        fname = time.strftime("darkcat-results-%Y%m%d-%H%M%S.txt")
        self._busy["export"] = True
        self._log(
            f"[bold #ff00aa]▶[/] [bold #00e5ff]export[/]  "
            f"[#5c8c70]{len(snapshot)} row(s) → [/][bold]{fname}[/]"
            f"  [#5c8c70]· writing…[/]"
        )
        self.run_worker(self._export_worker(fname, snapshot), thread=True)

    def _export_worker(self, fname: str, snapshot: list[dict]) -> None:
        candidates = [Path.cwd(), Path.home()]
        last_err: Optional[str] = None
        for base in candidates:
            target = (base / fname).resolve()
            try:
                self._write_export(target, snapshot)
            except OSError as e:
                last_err = f"{base}: {e}"
                continue
            self.call_from_thread(self._on_export_done, True, target, len(snapshot), None)
            return
        self.call_from_thread(
            self._on_export_done, False, Path(fname), len(snapshot),
            last_err or "unknown error",
        )

    def _on_export_done(
        self, ok: bool, path: Path, n: int, err: Optional[str],
    ) -> None:
        self._busy["export"] = False
        if not ok:
            self._log(
                f"[bold #ff1a4b]✗ export failed:[/] [#ffb000]{err}[/]"
            )
            return
        self._log(
            f"[bold #00ff66]✓ exported[/] [bold]{n}[/] "
            f"[#5c8c70]row(s) →[/] [underline #00e5ff]{path}[/]"
        )

    @staticmethod
    def _write_export(path: Path, snapshot: list[dict]) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with path.open("w", encoding="utf-8") as fh:
            fh.write(
                f"# darkcat export — {ts}\n"
                f"# {len(snapshot)} result(s)\n"
                f"# columns: score  category  protocol  title  url\n"
                "# " + "-" * 76 + "\n"
            )
            for s in snapshot:
                title = (s.get("title") or "").replace("\n", " ").replace("\t", " ")
                try:
                    score = float(s.get("score") or 0.0)
                except (TypeError, ValueError):
                    score = 0.0
                fh.write(
                    f"{score:>6.2f}\t{(s.get('category') or '—'):<24}\t"
                    f"{(s.get('protocol') or '?'):<10}\t"
                    f"{title}\t{s.get('url') or ''}\n"
                )

    # --- quit guard ----------------------------------------------------------

    def action_quit(self) -> None:  # type: ignore[override]
        """Confirm-on-quit while a crawl is running. First Q arms the warning;
        second Q within the same session actually quits."""
        if self._active_crawler is not None and not self._quit_armed:
            self._quit_armed = True
            self._log(
                "[bold #ffb000]⚠ a crawl is running.[/]  "
                "[#ffb000]press[/] [bold #ff00aa]Q[/] [#ffb000]again to "
                "stop it and quit, or[/] [bold #ff00aa]Ctrl+C[/] "
                "[#ffb000]to abort the crawl first.[/]"
            )
            return
        self._shutdown()
        self.exit()

    def _shutdown(self) -> None:
        """Best-effort teardown: signal any running crawler, close fetcher
        sessions, close the storage connection. Idempotent and tolerant of
        partially-initialised state (so we can call it from on_unmount too)."""
        crawler = self._active_crawler
        if crawler is not None:
            try:
                crawler.stop()
            except Exception:
                pass
        fetcher = getattr(self, "fetcher", None)
        if fetcher is not None:
            close = getattr(fetcher, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        storage = getattr(self, "storage", None)
        if storage is not None:
            try:
                storage.close()
            except Exception:
                pass

    def on_unmount(self) -> None:
        # Belt-and-braces: even if the user kills the process via the
        # window manager, Textual fires on_unmount before the loop dies.
        self._shutdown()

    @staticmethod
    def _row_category(row) -> str:
        def _g(name: str) -> str:
            try:
                return row[name] or ""
            except (IndexError, KeyError):
                return ""
        return categorize_str(
            _g("title"), _g("snippet"), _g("topic_hits"), _g("url"),
        )

    # --- input validation ---------------------------------------------------

    @staticmethod
    def _looks_like_url(s: str) -> bool:
        """Heuristic: must contain a scheme or a dotted host, no spaces."""
        s = (s or "").strip()
        if not s or " " in s:
            return False
        if "://" in s:
            return True
        lower = s.lower()
        if any(lower.startswith(p) for p in ("http", "ftp", "gopher", "freenet:")):
            return True
        # bare host like ``example.onion`` or ``site.i2p``
        return "." in s and not s.startswith(".") and not s.endswith(".")

    def _read_int_clamped(
        self, widget_id: str, default: int, lo: int, hi: int, label: str,
    ) -> int:
        """Read an int from an Input, clamp to [lo,hi], log + write back on edit.

        Returns the clamped value. Empty input falls back to ``default``.
        """
        inp = self.query_one(f"#{widget_id}", Input)
        raw = (inp.value or "").strip()
        if not raw:
            return default
        try:
            v = int(float(raw))  # tolerate "50.0"
        except ValueError:
            self._log(
                f"[#ffb000]⚠ {label}: '{raw}' is not a number, "
                f"using {default}[/]"
            )
            inp.value = str(default)
            return default
        clamped = max(lo, min(hi, v))
        if clamped != v:
            self._log(
                f"[#ffb000]⚠ {label}: {v} out of range [{lo},{hi}], "
                f"clamped to {clamped}[/]"
            )
            inp.value = str(clamped)
        return clamped

    def _read_float_clamped(
        self, widget_id: str, default: float, lo: float, hi: float, label: str,
    ) -> float:
        inp = self.query_one(f"#{widget_id}", Input)
        raw = (inp.value or "").strip()
        if not raw:
            return default
        try:
            v = float(raw)
        except ValueError:
            self._log(
                f"[#ffb000]⚠ {label}: '{raw}' is not a number, "
                f"using {default}[/]"
            )
            inp.value = str(default)
            return default
        clamped = max(lo, min(hi, v))
        if clamped != v:
            self._log(
                f"[#ffb000]⚠ {label}: {v} out of range [{lo},{hi}], "
                f"clamped to {clamped}[/]"
            )
            inp.value = str(clamped)
        return clamped

    def _set_busy(self, op: str, value: bool, button_id: Optional[str] = None) -> None:
        """Toggle a busy flag and optionally disable/enable the matching button."""
        self._busy[op] = value
        if button_id is not None:
            try:
                self.query_one(f"#{button_id}", Button).disabled = value
            except Exception:
                pass

    # --- buttons -------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "crawl-btn":
            self.start_crawl()
        elif bid == "stop-btn":
            self.action_cancel_crawl()
        elif bid == "search-btn":
            self.do_search()
        elif bid == "fetch-btn":
            self.do_fetch()

    def watch_crawling(self, value: bool) -> None:
        self.query_one("#crawl-btn", Button).disabled = value
        self.query_one("#stop-btn", Button).disabled = not value

    # --- transport toggle ---------------------------------------------------

    # control.py event level → Rich style for the log panel.
    _CTRL_STYLE = {
        "cmd":    "bold #ff00aa",
        "stdout": "#5c8c70",
        "stderr": "#ffb000",
        "info":   "bold #00e5ff",
        "ok":     "bold #00ff66",
        "warn":   "#ffb000",
        "err":    "bold #ff1a4b",
        "muted":  "#5c8c70",
    }

    def toggle_transport(self, proto: Protocol) -> None:
        """Pill click handler: probe → start (if down) or stop (if up) → re-probe."""
        if proto in self._toggling:
            return
        if not self.control.has_profile(proto):
            self._log(
                f"[#ffb000]·[/] [bold]{proto.value}[/] [#5c8c70]has no daemon "
                f"profile (stateless / system DNS)[/]"
            )
            return
        self._toggling.add(proto)
        self.run_worker(self._toggle_worker(proto), thread=True)

    def _toggle_worker(self, proto: Protocol) -> None:
        try:
            self.call_from_thread(
                self._log,
                f"[bold #ff00aa]▓▒░ {proto.value.upper()} ░▒▓[/]",
            )
            running = self.control.is_running(proto)
            for ev in self.control.probe(proto):
                self.call_from_thread(self._log_control_event, *ev)
            gen = self.control.down(proto) if running else self.control.up(proto)
            for ev in gen:
                self.call_from_thread(self._log_control_event, *ev)
            self.call_from_thread(self._log, "[#5c8c70]  · re-probing transports…[/]")
        finally:
            self._toggling.discard(proto)
            self.call_from_thread(self.action_refresh_status)

    def _log_control_event(self, level: str, text: str) -> None:
        style = self._CTRL_STYLE.get(level, "#00ff66")
        # Escape Rich markup brackets that occur in raw daemon output.
        safe = text.replace("[", "\\[")
        self._log(f"[{style}]{safe}[/]")

    # --- sudo prompt ---------------------------------------------------------
    #
    # Called from a worker thread by darkcat.elevation.run_elevated. Textual
    # screens are UI-thread only, so we hop to the loop with
    # ``call_from_thread`` and block the worker on a threading.Event until
    # ``SudoPasswordScreen`` dismisses itself.

    def _ask_sudo_password(self, prompt: str) -> Optional[str]:
        done = threading.Event()
        result: list[Optional[str]] = [None]

        def _on_dismiss(value: Optional[str]) -> None:
            result[0] = value
            done.set()

        def _open() -> None:
            try:
                self.push_screen(SudoPasswordScreen(prompt), _on_dismiss)
            except Exception:
                done.set()  # don't deadlock the worker if push fails

        try:
            self.call_from_thread(_open)
        except Exception:
            return None
        done.wait()
        return result[0]

    # --- crawl ---------------------------------------------------------------

    def start_crawl(self) -> None:
        if self._active_crawler is not None:
            self._log("[#ffb000]⚠ a crawl is already running — stop it first[/]")
            return
        topics = self.query_one("#topics", Input).value.split()
        protocol = self.query_one("#protocol", Select).value
        max_pages = self._read_int_clamped(
            "max_pages", 50, *self._PAGES_RANGE, "max pages",
        )
        max_depth = self._read_int_clamped(
            "max_depth", 2, *self._DEPTH_RANGE, "max depth",
        )
        threshold = self._read_float_clamped(
            "threshold", 0.0, *self._THRESHOLD_RANGE, "threshold",
        )
        seeds = all_seeds() if protocol == "all" else SEEDS_BY_PROTOCOL.get(protocol, [])
        if not seeds:
            self._log(f"[#ffb000]No built-in seeds for[/] [bold]{protocol}[/]")
            return
        self._log(
            f"[bold #ff00aa]▶[/] [bold #00e5ff]crawl starting[/]  "
            f"[#5c8c70]proto=[/][bold]{protocol}[/]  "
            f"[#5c8c70]seeds=[/][#00ff66]{len(seeds)}[/]  "
            f"[#5c8c70]pages=[/][#00ff66]{max_pages}[/]  "
            f"[#5c8c70]depth=[/][#00ff66]{max_depth}[/]  "
            f"[#5c8c70]topics=[/][#00ff66]{' '.join(topics) or '(none)'}[/]"
        )
        self.crawling = True
        self.run_worker(
            self._crawl_worker(seeds, topics, max_pages, max_depth, threshold),
            exclusive=True,
            thread=True,
        )

    def _crawl_worker(self, seeds, topics, max_pages, max_depth, threshold):
        tf = TopicFilter(topics)
        policy = CrawlPolicy(
            max_pages=max_pages,
            max_depth=max_depth,
            score_threshold=threshold,
        )
        crawler = Crawler(self.cfg, self.storage, tf, policy)
        self._active_crawler = crawler

        def on_event(kind: str, payload: dict) -> None:
            self.call_from_thread(self._handle_crawl_event, kind, payload)

        try:
            stats = crawler.crawl(seeds, on_event=on_event)
            self.call_from_thread(
                self._log,
                f"[bold #ff00aa]▓▒░[/] [bold #00ff66]done[/]  "
                f"[#5c8c70]fetched=[/][#00ff66]{stats.fetched}[/]  "
                f"[#5c8c70]errors=[/][#ff1a4b]{stats.errors}[/]  "
                f"[#5c8c70]skipped=[/][#5c8c70]{stats.skipped}[/]",
            )
        except Exception as e:
            self.call_from_thread(
                self._log,
                f"[bold #ff1a4b]✗ crawl crashed:[/] [#ffb000]{e}[/]",
            )
        finally:
            self._active_crawler = None
            self.call_from_thread(self._set_crawling, False)
            self.call_from_thread(self.refresh_results)

    def _set_crawling(self, value: bool) -> None:
        self.crawling = value

    @staticmethod
    def _esc(s) -> str:
        """Escape Rich-markup brackets in arbitrary user/network content.

        URLs, titles, and error strings can contain ``[`` (e.g. IPv6 hosts,
        bracketed prefixes in HTML titles), which Rich treats as the start
        of a markup tag — left unescaped, an unbalanced ``[`` will eat the
        rest of the line. ``str()`` covers None/non-str payloads too.
        """
        return str(s if s is not None else "").replace("[", r"\[")

    def _handle_crawl_event(self, kind: str, payload: dict) -> None:
        if kind == "fetch":
            try:
                score = float(payload.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            score_color = (
                "#00ff66" if score >= 1.0
                else "#ffb000" if score >= 0.3
                else "#5c8c70"
            )
            self._log(
                f"[bold #00ff66]▶[/] "
                f"[bold #00e5ff]\\[{self._esc(payload.get('protocol','?')):<10}][/] "
                f"[{score_color}]{score:>5.2f}[/] "
                f"[#5c8c70]d={int(payload.get('depth', 0))}[/]  "
                f"[bold]{self._esc(payload.get('title') or '(no title)')}[/]  "
                f"[underline #00e5ff]{self._esc(payload.get('url', ''))}[/]"
            )
        elif kind == "error":
            err = self._esc(payload.get("error", ""))[:140]
            self._log(
                f"[bold #ff1a4b]✗[/] "
                f"[bold #00e5ff]\\[{self._esc(payload.get('protocol', '?'))}][/] "
                f"[#ffb000]{err}[/]  "
                f"[underline #00e5ff]{self._esc(payload.get('url', ''))}[/]"
            )
        elif kind == "skip":
            self._log(
                f"[#5c8c70]·[/] [#5c8c70]skip "
                f"{self._esc(payload.get('reason', ''))}: "
                f"{self._esc(payload.get('url', ''))}[/]"
            )
        elif kind == "newnym":
            self._log(
                f"[bold #ff00aa]↻ NEWNYM[/] "
                f"[#5c8c70]rotating Tor circuit after repeated failures on[/] "
                f"[bold]{self._esc(payload.get('host', ''))}[/]"
            )

    # --- search / fetch -------------------------------------------------------

    # Cap search queries — anything longer is almost certainly a paste-bomb
    # and FTS5 will choke on it long before it finds anything useful.
    _MAX_QUERY_LEN = 256
    _MAX_FETCH_URL_LEN = 2048

    def do_search(self) -> None:
        if self._busy.get("search"):
            self._log("[#ffb000]⚠ search already running — please wait…[/]")
            return
        q = self.query_one("#search", Input).value.strip()
        if not q:
            return
        if len(q) > self._MAX_QUERY_LEN:
            self._log(
                f"[#ffb000]⚠ query too long ({len(q)} chars) — "
                f"truncated to {self._MAX_QUERY_LEN}[/]"
            )
            q = q[: self._MAX_QUERY_LEN]
        self._set_busy("search", True, "search-btn")
        self._log(
            f"[bold #ff00aa]▶[/] [bold #00e5ff]search[/] "
            f"[bold]{self._esc(q)}[/]  [#5c8c70]· querying…[/]"
        )
        self.run_worker(self._search_worker(q), thread=True)

    def _search_worker(self, q: str) -> None:
        try:
            rows = self.storage.search(q, limit=200)
        except Exception as e:
            self.call_from_thread(self._on_search_done, q, [], f"{type(e).__name__}: {e}")
            return
        self.call_from_thread(self._on_search_done, q, list(rows), None)

    def _on_search_done(self, q: str, rows: list, err: Optional[str]) -> None:
        self._set_busy("search", False, "search-btn")
        if err is not None:
            self._log(
                f"[bold #ff1a4b]✗ search failed:[/] [#ffb000]{self._esc(err)}[/]"
            )
            return
        self._populate_results(rows)
        self._log(
            f"[#5c8c70]  ↳[/] [bold]{self._esc(q)}[/] [#5c8c70]→[/] "
            f"[#00ff66]{len(rows)}[/] [#5c8c70]hit(s)[/]"
        )

    def do_fetch(self) -> None:
        if self._busy.get("fetch"):
            self._log("[#ffb000]⚠ fetch already running — please wait…[/]")
            return
        url = self.query_one("#fetch_url", Input).value.strip()
        if not url:
            return
        if len(url) > self._MAX_FETCH_URL_LEN:
            self._log(
                f"[bold #ff1a4b]✗ URL too long[/] "
                f"[#ffb000]({len(url)} > {self._MAX_FETCH_URL_LEN})[/]"
            )
            return
        if not self._looks_like_url(url):
            self._log(
                f"[bold #ff1a4b]✗ not a URL:[/] [#ffb000]{self._esc(url)}[/]  "
                f"[#5c8c70](need scheme:// or a dotted host, no spaces)[/]"
            )
            return
        self._set_busy("fetch", True, "fetch-btn")
        self._log(
            f"[bold #ff00aa]▶[/] [bold #00e5ff]fetch[/] "
            f"[underline #00e5ff]{self._esc(url)}[/]  "
            f"[#5c8c70]· connecting…[/]"
        )
        self.run_worker(self._fetch_worker(url), thread=True)

    def _fetch_worker(self, url: str) -> None:
        try:
            result = self.fetcher.fetch(url)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            self.call_from_thread(
                self._on_fetch_done, None, f"{type(e).__name__}: {e}",
            )
            return
        self.call_from_thread(self._on_fetch_done, result, None)

    def _on_fetch_done(self, result, err: Optional[str]) -> None:
        self._set_busy("fetch", False, "fetch-btn")
        if err is not None or result is None:
            self._log(
                f"[bold #ff1a4b]✗ fetch failed:[/] [#ffb000]{self._esc(err)}[/]"
            )
            return
        try:
            body_len = len(result.body or b"")
        except TypeError:
            body_len = 0
        self._log(
            f"[bold #00ff66]✓[/]  "
            f"[#5c8c70]status=[/][#00ff66]{int(result.status or 0)}[/]  "
            f"[#5c8c70]bytes=[/][#00ff66]{body_len}[/]  "
            f"[#5c8c70]ct=[/][#00ff66]{self._esc(result.content_type)}[/]  "
            f"[#5c8c70]→[/]  [underline #00e5ff]{self._esc(result.final_url)}[/]"
        )

    def refresh_results(self) -> None:
        if self._busy.get("results"):
            return
        self._set_busy("results", True)
        self.run_worker(self._results_worker(), thread=True)

    def _results_worker(self) -> None:
        try:
            rows = self.storage.top(limit=200)
        except Exception as e:
            self.call_from_thread(self._on_results_done, [], f"{type(e).__name__}: {e}")
            return
        self.call_from_thread(self._on_results_done, list(rows), None)

    def _on_results_done(self, rows: list, err: Optional[str]) -> None:
        self._set_busy("results", False)
        if err is not None:
            self._log(
                f"[bold #ff1a4b]✗ results refresh failed:[/] "
                f"[#ffb000]{self._esc(err)}[/]"
            )
            return
        self._populate_results(rows)

    def _populate_results(self, rows) -> None:
        """Render rows into the DataTable and cache them for export.

        Empty result sets render as a single dim placeholder row so the
        table never looks broken / blank.
        """
        table = self.query_one("#results", DataTable)
        table.clear()
        self._last_rows = list(rows)
        if not self._last_rows:
            table.add_row(
                "—", "—", "—",
                "no results yet — run a crawl or hit F5 to refresh",
                "—",
            )
            return
        for r in self._last_rows:
            try:
                score_val = float(r["score"])
                score_str = f"{score_val:.2f}"
            except (TypeError, KeyError, ValueError):
                score_val = None
                score_str = "—"
            if score_val is None:
                score_cell = Text(score_str, style="#5c8c70")
            elif score_val >= 1.0:
                score_cell = Text(score_str, style="bold #00ff66")
            elif score_val >= 0.3:
                score_cell = Text(score_str, style="#ffb000")
            else:
                score_cell = Text(score_str, style="#5c8c70")
            table.add_row(
                score_cell,
                self._row_category(r),
                r["protocol"] if "protocol" in r.keys() else "?",
                (r["title"] or "")[:60] if "title" in r.keys() else "",
                (r["url"] or "")[:80] if "url" in r.keys() else "",
            )

    def _log(self, msg: str) -> None:
        try:
            self.query_one("#log", RichLog).write(msg)
        except Exception:
            # Log widget might not be mounted yet (very early init) or the
            # app may be tearing down — drop the message rather than crash.
            pass


def run_tui(cfg: Config) -> int:
    DarkcatApp(cfg).run()
    return 0
