# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Curated worked examples for the darkcat four-frontend story.

This is the data source for ``darkcat help examples`` (CLI), ``help
examples`` (REPL), the TUI ``ExamplesScreen`` (F11), and the GUI
``ExamplesWindow``. One central catalog so every frontend renders the
same canonical recipe text.

Each entry is a small dataclass — id, title, category, description,
plus one :class:`ExampleStep` per frontend (cli / repl / tui / gui).
The rendering layer turns this into Rich markup with category headers,
colour-coded frontend tags, and copyable command snippets.

The catalog stays terse on purpose. Long-form walkthroughs belong in
``docs/USERGUIDE.md``; this is the "I forgot how to fire X" cheatsheet
that fits on one screen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ExampleStep:
    """One frontend's path to perform an example. ``command`` is a
    copy-pasteable string (shell line, REPL line, menu path, or key
    sequence). ``note`` is an optional one-liner clarifier."""

    frontend: str  # "cli" / "repl" / "tui" / "gui"
    command: str
    note: str = ""


@dataclass(frozen=True)
class Example:
    """One worked example. ``id`` is a stable slug used to look it up
    from ``darkcat help examples <id>``."""

    id: str
    title: str
    category: str
    description: str
    steps: list[ExampleStep] = field(default_factory=list)
    tags: tuple[str, ...] = ()


# Stable ordering matters for the UI sidebar. Categories appear in the
# order they're first seen here. Entries within a category appear in
# the order they're listed.
EXAMPLES: list[Example] = [
    # ---- Personas + vault ------------------------------------------
    Example(
        id="persona-add-mail",
        title="Create a mail persona from a provider preset",
        category="Personas",
        description=(
            "Seed a persona with one of the curated mail-provider presets "
            "(protonmail, tutanota, disroot, mailfence, riseup, …). The "
            "host/port + transport defaults are pre-filled."
        ),
        steps=[
            ExampleStep("cli",
                "darkcat personas add alice-mail --preset protonmail.bridge "
                "--handle alice --gen"),
            ExampleStep("repl",
                "personas add alice-mail --preset protonmail.bridge --handle alice --gen"),
            ExampleStep("tui",
                "Press F6 → pick provider → fill handle → Submit"),
            ExampleStep("gui",
                "Mail → Add mail persona… → pick provider → Submit"),
        ],
        tags=("persona", "mail", "preset", "signup"),
    ),
    Example(
        id="persona-add-chat",
        title="Create a chat persona for Matrix / Telegram / Simplex",
        category="Personas",
        description=(
            "Chat personas carry the same fields as mail ones; the "
            "`provider` field is what the chat hub keys off when "
            "deciding which backend to drive."),
        steps=[
            ExampleStep("cli",
                "darkcat personas add alice-mx --provider matrix "
                "--site matrix.tchncs.de --handle alice --gen"),
            ExampleStep("repl",
                "personas add alice-mx --provider matrix --site matrix.tchncs.de --handle alice --gen"),
            ExampleStep("tui", "Press F6 → pick provider matrix → fill site/handle → Submit"),
            ExampleStep("gui", "Identity → Add persona… → provider=matrix → Submit"),
        ],
        tags=("persona", "chat", "matrix", "telegram", "simplex"),
    ),
    Example(
        id="vault-encrypt",
        title="Encrypt the persona vault with a passphrase",
        category="Personas",
        description=(
            "Wraps ``~/.darkcat/personas.json`` with GPG symmetric "
            "encryption. Every frontend then prompts (or reads "
            "``DARKCAT_VAULT_PASSPHRASE``) on first use."
        ),
        steps=[
            ExampleStep("cli", "darkcat personas encrypt"),
            ExampleStep("repl", "personas encrypt"),
            ExampleStep("tui", "F5 (Identity) → e to edit → menu → encrypt"),
            ExampleStep("gui", "Identity → Encrypt vault…"),
        ],
        tags=("persona", "vault", "encryption", "gpg"),
    ),

    # ---- Chat -------------------------------------------------------
    Example(
        id="chat-backends",
        title="See which chat backends are installed",
        category="Chat",
        description=(
            "Lists every messaging backend darkcat knows about and "
            "whether its optional dependency is installed."),
        steps=[
            ExampleStep("cli", "darkcat chat backends"),
            ExampleStep("repl", "chat backends"),
            ExampleStep("tui", "Press c → Backends"),
            ExampleStep("gui", "Chat → Chat console… → Backends"),
        ],
        tags=("chat", "doctor", "dependencies"),
    ),
    Example(
        id="chat-login-matrix",
        title="Login to Matrix (or any chat backend) for the first time",
        category="Chat",
        description=(
            "First-time login caches a session under "
            "``~/.darkcat/chat-sessions/<persona>/`` so subsequent calls "
            "don't re-prompt for credentials."),
        steps=[
            ExampleStep("cli", "darkcat chat login matrix --persona alice-mx"),
            ExampleStep("repl", "chat login matrix --persona alice-mx"),
            ExampleStep("tui", "c → action=login → persona=alice-mx → Run"),
            ExampleStep("gui", "Chat → Chat console… → action=login → Run"),
        ],
        tags=("chat", "login", "matrix"),
    ),
    Example(
        id="chat-hub",
        title="Open the multi-protocol chat hub (F3)",
        category="Chat",
        description=(
            "Aggregates every chat-capable persona into one table — "
            "channels, unread, status, transport tag. Auto-refreshes on "
            "the cadence persisted in ``~/.darkcat/hub.json`` "
            "(default 30s; manual ``r``)."
        ),
        steps=[
            ExampleStep("cli", "darkcat chat hub"),
            ExampleStep("repl", "chat hub"),
            ExampleStep("tui", "Press F3"),
            ExampleStep("gui", "Press F3 (or Chat → Chat hub)"),
        ],
        tags=("chat", "hub", "aggregator"),
    ),
    Example(
        id="chat-hub-interval",
        title="Change the chat-hub auto-refresh interval",
        category="Chat",
        description=(
            "Presets: 10s / 30s / 1m / 10m / 30m / 1h / off. Persists "
            "to ``~/.darkcat/hub.json``."
        ),
        steps=[
            ExampleStep("cli", "darkcat chat hub --interval 10s"),
            ExampleStep("repl", "chat hub --interval 10s"),
            ExampleStep("tui", "In F3 → +/- to cycle presets, 0 for manual-only"),
            ExampleStep("gui", "In Chat hub window → Combobox top-right"),
        ],
        tags=("chat", "hub", "config"),
    ),
    Example(
        id="chat-send-simplex",
        title="Send a SimpleX message",
        category="Chat",
        description=(
            "SimpleX targets a running ``simplex-chat`` daemon. The "
            "persona's session-dir holds the queue secrets."),
        steps=[
            ExampleStep("cli",
                "darkcat chat send <CHANNEL_ID> --persona alice-sx -m 'hello from darkcat'"),
            ExampleStep("repl",
                "chat send <CHANNEL_ID> --persona alice-sx -m 'hello'"),
            ExampleStep("tui", "c → action=send → channel + message → Run"),
            ExampleStep("gui", "Chat → Chat console… → action=send"),
        ],
        tags=("chat", "send", "simplex"),
    ),

    # ---- Mail -------------------------------------------------------
    Example(
        id="mail-send-protonmail",
        title="Send mail via ProtonMail Bridge",
        category="Mail",
        description=(
            "The persona's ``site`` field carries ``host:port`` for both "
            "SMTP and IMAP. ProtonMail Bridge serves loopback 1025/1143."),
        steps=[
            ExampleStep("cli",
                "darkcat mail send --persona alice-pm --to bob@x.com "
                "--subject 'hi' --body 'one-liner'"),
            ExampleStep("repl",
                "mail send --persona alice-pm --to bob@x.com --subject hi --body one-liner"),
            ExampleStep("tui", "Press F4 → Send → fill fields → Run"),
            ExampleStep("gui", "Mail → Send mail… → fill fields → Send"),
        ],
        tags=("mail", "smtp", "protonmail"),
    ),
    Example(
        id="mail-check",
        title="Check an IMAP inbox",
        category="Mail",
        description="Lists the most recent N messages on the persona's IMAP host.",
        steps=[
            ExampleStep("cli", "darkcat mail check --persona alice-pm -n 20"),
            ExampleStep("repl", "mail check --persona alice-pm -n 20"),
            ExampleStep("tui", "Press F4 → Check → persona → Run"),
            ExampleStep("gui", "Mail → Check mail…"),
        ],
        tags=("mail", "imap"),
    ),

    # ---- Transports + crawl ----------------------------------------
    Example(
        id="doctor",
        title="Run the transport doctor",
        category="Transports",
        description=(
            "Probes Tor SOCKS, I2P HTTP, IPFS gateway, Freenet FProxy, "
            "ZeroNet UI, mail-host reachability, and DB integrity. "
            "Surfaces fix hints when something's broken."),
        steps=[
            ExampleStep("cli", "darkcat doctor"),
            ExampleStep("repl", "doctor"),
            ExampleStep("tui", "Press F7 (or d)"),
            ExampleStep("gui", "Press F7 (or Tools → Doctor)"),
        ],
        tags=("doctor", "transports", "diagnose"),
    ),
    Example(
        id="tor-newnym",
        title="Force a new Tor circuit (NEWNYM)",
        category="Transports",
        description=(
            "Cycles Tor's identity by sending NEWNYM on the control "
            "port — the next request uses a fresh circuit."),
        steps=[
            ExampleStep("cli", "darkcat tor newnym"),
            ExampleStep("repl", "tor newnym"),
            ExampleStep("tui", "(via shell) tor newnym"),
            ExampleStep("gui", "(via shell) tor newnym"),
        ],
        tags=("tor", "circuit", "opsec"),
    ),
    Example(
        id="tor-bridges-add",
        title="Add a Tor bridge line and re-probe",
        category="Transports",
        description=(
            "Useful when raw Tor is blocked and you have obfs4 / "
            "snowflake / meek bridge lines."),
        steps=[
            ExampleStep("cli",
                "darkcat tor bridges-add 'obfs4 1.2.3.4:443 FINGERPRINT cert=...'"),
            ExampleStep("repl",
                "tor bridges-add 'obfs4 1.2.3.4:443 FINGERPRINT cert=...'"),
            ExampleStep("tui", "(via shell) tor bridges-add ..."),
            ExampleStep("gui", "(via shell) tor bridges-add ..."),
        ],
        tags=("tor", "bridges", "censorship"),
    ),
    Example(
        id="fetch-page",
        title="Fetch a single onion / I2P / Gemini page",
        category="Crawl",
        description=(
            "Bypasses the crawler — pulls one URL via the right "
            "transport and dumps title/score/body to stdout."),
        steps=[
            ExampleStep("cli",
                "darkcat fetch http://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/"),
            ExampleStep("repl",
                "fetch http://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/"),
            ExampleStep("tui", "URL bar → paste → press Enter (Fetch button)"),
            ExampleStep("gui", "URL bar → paste → Fetch"),
        ],
        tags=("fetch", "tor", "i2p"),
    ),
    Example(
        id="crawl-tor",
        title="Start a Tor crawl from the curated seeds",
        category="Crawl",
        description="Walks the built-in tor seed set, respecting politeness + max depth.",
        steps=[
            ExampleStep("cli", "darkcat crawl --protocol tor --depth 2"),
            ExampleStep("repl", "crawl --protocol tor --depth 2"),
            ExampleStep("tui", "Pick protocol=tor → press Crawl button"),
            ExampleStep("gui", "Pick protocol=tor → click Crawl"),
        ],
        tags=("crawl", "tor"),
    ),
    Example(
        id="peers-tor",
        title="List Tor peers harvested from crawled pages",
        category="Crawl",
        description="Surfaces onion addresses found while crawling, with their first-seen page.",
        steps=[
            ExampleStep("cli", "darkcat keys harvest --protocol tor"),
            ExampleStep("repl", "keys harvest --protocol tor"),
            ExampleStep("tui", "Results panel → filter by protocol=tor"),
            ExampleStep("gui", "Results panel → filter by protocol=tor"),
        ],
        tags=("tor", "peers", "harvest"),
    ),
    Example(
        id="i2p-enable",
        title="Check / enable the I2P transport",
        category="Transports",
        description=(
            "Pings the I2P HTTP proxy on 127.0.0.1:4444 and reports "
            "whether it's reachable. The doctor walks the same probe."),
        steps=[
            ExampleStep("cli", "darkcat doctor  # look for i2p row"),
            ExampleStep("repl", "doctor"),
            ExampleStep("tui", "Press F7"),
            ExampleStep("gui", "Press F7"),
        ],
        tags=("i2p", "transport"),
    ),

    # ---- Identity Generator ----------------------------------------
    Example(
        id="identity-launch",
        title="Launch the signup browser for a pending persona",
        category="Identity",
        description=(
            "Opens a transport-routed browser, prefills the persona's "
            "fields, and (with --capture) chains an edit dialog to "
            "store the recovery codes shown after signup."),
        steps=[
            ExampleStep("cli", "darkcat identity launch alice-mx --capture"),
            ExampleStep("repl", "identity launch alice-mx --capture"),
            ExampleStep("tui", "F5 (Identity) → highlight persona → l (Launch)"),
            ExampleStep("gui", "Identity → Open vault → Launch"),
        ],
        tags=("identity", "signup", "browser"),
    ),
    Example(
        id="identity-show",
        title="Reveal a stored credential (masked → confirm → reveal)",
        category="Identity",
        description=(
            "Two-step reveal: masked dump first, then `--reveal` (or `y` "
            "in the TUI) to print the real values."),
        steps=[
            ExampleStep("cli", "darkcat identity show alice-mx --reveal"),
            ExampleStep("repl", "identity show alice-mx --reveal"),
            ExampleStep("tui", "F5 → s on persona → y to reveal"),
            ExampleStep("gui", "Identity → Open vault → Show → Reveal"),
        ],
        tags=("identity", "reveal", "secrets"),
    ),
]


def categories() -> list[str]:
    """Stable category list in declaration order — used by the UI sidebar."""
    seen: list[str] = []
    for ex in EXAMPLES:
        if ex.category not in seen:
            seen.append(ex.category)
    return seen


def by_category(name: str) -> list[Example]:
    return [ex for ex in EXAMPLES if ex.category == name]


def find(example_id: str) -> Optional[Example]:
    for ex in EXAMPLES:
        if ex.id == example_id:
            return ex
    return None


def search(query: str) -> list[Example]:
    """Case-insensitive substring match across id/title/description/tags."""
    q = query.strip().lower()
    if not q:
        return list(EXAMPLES)
    out: list[Example] = []
    for ex in EXAMPLES:
        haystack = " ".join((
            ex.id, ex.title, ex.description, " ".join(ex.tags),
        )).lower()
        if q in haystack:
            out.append(ex)
    return out


# Per-frontend label + colour for Rich rendering. Centralised so every
# frontend uses the same colour for "this is the CLI line", "this is
# the TUI key sequence", etc.
FRONTEND_STYLES: dict[str, tuple[str, str]] = {
    "cli":  ("CLI",  "#00e5ff"),
    "repl": ("REPL", "#ff00aa"),
    "tui":  ("TUI",  "#00ff66"),
    "gui":  ("GUI",  "#ffb000"),
}


def render_one(example: Example) -> str:
    """Render a single example as Rich markup. Used by CLI / REPL /
    TUI / GUI alike so the colour scheme stays consistent."""
    lines = [
        f"[bold #00e5ff]{example.title}[/]",
        f"[#5c8c70]{example.category} · {example.id}[/]",
        "",
        example.description,
        "",
    ]
    for step in example.steps:
        label, colour = FRONTEND_STYLES.get(
            step.frontend, (step.frontend.upper(), "#888888"))
        lines.append(f"  [{colour}]{label:>4}[/]  [#00ff66]{step.command}[/]")
        if step.note:
            lines.append(f"        [#5c8c70]{step.note}[/]")
    if example.tags:
        lines.append("")
        lines.append("  [#5c8c70]tags:[/] " + ", ".join(
            f"[#888888]{t}[/]" for t in example.tags))
    return "\n".join(lines)


def render_index() -> str:
    """Render the catalog as a category-grouped index, one short line
    per example. Used by ``darkcat help examples`` (no arg)."""
    lines: list[str] = []
    for cat in categories():
        lines.append(f"[bold #ff00aa]{cat}[/]")
        for ex in by_category(cat):
            lines.append(f"  [#00ff66]{ex.id:<28}[/] [#5c8c70]{ex.title}[/]")
        lines.append("")
    lines.append(
        "[#5c8c70]Show one with[/] [#00e5ff]darkcat help examples <id>[/]"
    )
    return "\n".join(lines).rstrip()


__all__ = [
    "EXAMPLES",
    "Example",
    "ExampleStep",
    "FRONTEND_STYLES",
    "by_category",
    "categories",
    "find",
    "render_index",
    "render_one",
    "search",
]
