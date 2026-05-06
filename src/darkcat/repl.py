"""Interactive REPL for darkcat — wraps the CLI subcommands as a shell."""
from __future__ import annotations

import argparse
import cmd
import shlex
import sys
from typing import Optional

from darkcat import __version__
from darkcat.cli import (
    PROTOCOL_TABLE,
    _build_about_text,
    cmd_alerts,
    cmd_blocklist,
    cmd_clusters,
    cmd_crawl,
    cmd_decode_links,
    cmd_diff,
    cmd_discover,
    cmd_doctor,
    cmd_down,
    cmd_export,
    cmd_feeds,
    cmd_fetch,
    cmd_findings,
    cmd_history,
    cmd_keys,
    cmd_list,
    cmd_mirrors,
    cmd_ocr,
    cmd_probe,
    cmd_scan,
    cmd_schedule,
    cmd_search,
    cmd_seeds,
    cmd_serve,
    cmd_stats,
    cmd_status,
    cmd_telegram,
    cmd_top,
    cmd_tor,
    cmd_up,
    cmd_watch,
    cmd_zeronet,
    print_about,
)
from darkcat.config import Config
from darkcat.theme import LOGO_MINI, banner, get_console, panel, rule


_console = get_console()
_err_console = get_console(stderr=True)


# REPL-only command index. Keep the groups close to `cli.COMMAND_GROUPS` so the
# CLI and shell tell the same story; differences: REPL adds `version`/`help`/
# `quit`/`exit`, and drops the frontend launchers (`tui`/`shell`/`gui`) — the
# shell can't reasonably re-launch itself.
_REPL_COMMAND_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Getting started", [
        ("about",   "Maintainer, license, and a one-line summary."),
        ("version", "Print darkcat version."),
        ("status",  "Report which protocol daemons are reachable."),
        ("doctor",  "Health check: home dir, DB, daemons, optional deps."),
        ("stats",   "SQLite database statistics."),
        ("seeds",   "Print built-in seed URLs (one protocol or 'all')."),
        ("list",    "Print curated entry points (one protocol or 'all')."),
    ]),
    ("Fetch & crawl", [
        ("fetch",     "Fetch a single URL through the right transport."),
        ("crawl",     "BFS-crawl from seeds with optional topic scoring."),
        ("discover",  "Query darknet search engines for seed URLs."),
        ("feeds",     "Probe sitemap / RSS / Atom / JSON-Feed for a host."),
        ("schedule",  "Persistent re-crawls: add/list/remove/run-due."),
    ]),
    ("Search & analyze", [
        ("search",       "FTS5 search of previously crawled pages."),
        ("top",          "Show highest-scoring crawled pages."),
        ("history",      "List historical text snapshots for one URL."),
        ("diff",         "Pages whose text changed; or unified diff for one URL."),
        ("clusters",     "Group pages by identical text (mirror detection)."),
        ("mirrors",      "Cluster near-duplicate pages via SimHash."),
        ("decode-links", "Surface URLs hidden in JS / base64 / ROT13 in a page."),
        ("ocr",          "Fetch a page and OCR every <img> via Tesseract."),
    ]),
    ("Monitoring & alerts", [
        ("scan",     "Scan crawled pages for credential / leak indicators."),
        ("findings", "List leak findings recorded in the DB."),
        ("watch",    "Manage finding watchlist (add/list/remove/test)."),
        ("alerts",   "Show alerts fired by the watchlist."),
        ("export",   "Export findings as JSONL / STIX 2.1 / MISP event JSON."),
        ("serve",    "Run a HIBP-style hash-prefix server over the findings DB."),
    ]),
    ("Networks & transports", [
        ("up",            "Start a transport daemon (tor, i2p, ipfs, …)."),
        ("down",          "Stop a transport daemon."),
        ("probe",         "Probe one (or every) transport for reachability."),
        ("tor",           "Tor control: newnym / info / circuits / bridges."),
        ("blocklist",     "Test rules against URLs / view blocklist audit log."),
        ("zeronet-walk",  "Walk a ZeroNet site's content.json graph."),
    ]),
    ("Identity & comms", [
        ("telegram", "Scrape t.me/s/<channel> messages."),
        ("keys",     "Harvest / list / show PGP public keys from crawled pages."),
    ]),
    ("Shell", [
        ("help",  "List all commands, or `help <command>` for details."),
        ("?",     "Alias for `help`."),
        ("quit",  "Exit the shell (also `exit` or Ctrl-D)."),
    ]),
]

_PROTOCOL_NAMES: tuple[str, ...] = tuple(name for name, _form, _t in PROTOCOL_TABLE)
_PROTOCOL_ARG_NAMES: tuple[str, ...] = (*_PROTOCOL_NAMES, "all")


# Subaction sets — each command's first positional. Only commands the REPL
# actually exposes as ``do_<name>`` belong here; CLI-only commands like
# ``cookies`` / ``personas`` aren't reachable from inside the shell, so a
# completer for them would be misleading. Tests guard the linkage.
_SUBACTIONS: dict[str, tuple[str, ...]] = {
    "watch":     ("add", "list", "remove", "test"),
    "tor":       ("newnym", "info", "circuits", "descriptor",
                  "bridges", "bridges-add", "bridges-clear"),
    "blocklist": ("test", "log"),
    "keys":      ("harvest", "list", "show"),
    "schedule":  ("add", "list", "remove", "enable", "disable",
                  "run", "run-due", "loop"),
}


# Persistent history file — readline writes / reads here so up-arrow survives
# across REPL sessions. Lives next to the DB (~/.darkcat/history) so a single
# `rm -rf ~/.darkcat` resets every persistent piece of state at once.
_HISTORY_FILE: Optional[Path] = None


def _history_file_path() -> Path:
    """``~/.darkcat/history`` — created lazily on first save."""
    from darkcat.personas import default_dir as _persona_dir
    return _persona_dir() / "history"


def _install_history() -> None:
    """Wire up readline history persistence. No-op if readline is missing."""
    if not _HAS_READLINE:
        return
    import atexit
    import readline as _rl

    path = _history_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            _rl.read_history_file(str(path))
    except OSError:
        # Read errors are non-fatal — start fresh, write on exit.
        pass
    _rl.set_history_length(2000)

    def _save_history() -> None:
        try:
            _rl.write_history_file(str(path))
        except OSError:
            pass

    atexit.register(_save_history)


try:
    import readline  # noqa: F401
    _HAS_READLINE = True
except ImportError:
    _HAS_READLINE = False


def _build_prompt() -> str:
    """Color the prompt only when stdout is a TTY *and* readline is around to
    correctly account for the non-printing ANSI bytes (\001/\002 markers)."""
    if not (sys.stdout.isatty() and _HAS_READLINE):
        return "darkcat> "
    return (
        "\001\033[1;38;2;255;0;170m\002▓"
        "\001\033[1;38;2;0;255;102m\002darkcat"
        "\001\033[1;38;2;255;0;170m\002▓ ❯ \001\033[0m\002"
    )


class DarkcatShell(cmd.Cmd):
    prompt = _build_prompt()

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        # Set True after preloop runs once so re-entering cmdloop after a
        # Ctrl+C at the prompt doesn't re-print the banner each time.
        self._banner_shown: bool = False

    def preloop(self) -> None:
        if self._banner_shown:
            return
        self._banner_shown = True
        banner(_console, version=__version__)
        _console.print(
            panel(
                "shell",
                "[muted]Type[/] [key]help[/] [muted]or[/] [key]?[/] "
                "[muted]to list commands.[/]\n"
                "[muted]Use[/] [key]quit[/][muted],[/] [key]exit[/][muted], or "
                "Ctrl-D to leave the shell.[/]",
            )
        )

    def emptyline(self) -> bool:
        return False

    def precmd(self, line: str) -> str:
        # Allow REPL users to type hyphenated commands like `decode-links URL`.
        head, sep, tail = line.partition(" ")
        if "-" in head:
            head = head.replace("-", "_")
        return head + sep + tail

    def onecmd(self, line: str):
        # Make Ctrl+C abort just the current command instead of falling out
        # of cmdloop. Long-running commands (crawl, scan, search-with-LIKE
        # on a huge DB) are the obvious targets, but `default()` is reached
        # for any unknown command — keep the same envelope.
        try:
            return super().onecmd(line)
        except KeyboardInterrupt:
            _err_console.print(
                "\n[warn]^C[/] [muted]aborted — back at prompt[/]"
            )
            return False  # don't exit cmdloop

    def default(self, line: str) -> None:
        token = line.split()[0] if line else ""
        _err_console.print(
            f"[fail]unknown command:[/] [warn]{token}[/]  "
            f"[muted]— type[/] [key]?[/] [muted]for help.[/]"
        )

    # ---- help & tab-completion ------------------------------------------

    def do_help(self, arg: str) -> None:
        """List all commands grouped by task, or `help <command>` for a
        single command's docstring."""
        if arg:
            # Translate hyphenated names so `help decode-links` works.
            super().do_help(arg.replace("-", "_"))
            return
        rule(_console, "darkcat shell — commands")
        for group_title, items in _REPL_COMMAND_GROUPS:
            _console.print(f"\n[tag]{group_title}[/]")
            for name, desc in items:
                _console.print(
                    f"  [key]{name:<14}[/] [muted]{desc}[/]"
                )
        _console.print(
            "\n[muted]Type[/] [key]help <command>[/] [muted]for that command's "
            "usage and options. Tab-completion works for command names and "
            "for the [/][key]up[/] [muted]/[/] [key]down[/] [muted]/[/] "
            "[key]probe[/] [muted]/[/] [key]list[/] [muted]/[/] [key]seeds[/] "
            "[muted]/[/] [key]discover[/] [muted]/[/] [key]feeds[/] [muted]"
            "protocol arg.[/]"
        )

    def do_shortcuts(self, _arg: str) -> None:
        """Alias of `help` — list all commands grouped by task."""
        self.do_help("")

    # cmd.Cmd's stock completer uses self.completenames(text), which only
    # surfaces method names matching `do_<text>`. Add the hyphenated alias
    # so users typing `decode-l<TAB>` see `decode-links`.
    def completenames(self, text: str, *ignored) -> list[str]:  # type: ignore[override]
        names = super().completenames(text, *ignored)
        if "decode-links".startswith(text):
            names.append("decode-links")
        if "zeronet-walk".startswith(text):
            names.append("zeronet-walk")
        return names

    # Protocol-name completion for commands whose first arg is a protocol.
    @staticmethod
    def _complete_protocol(text: str) -> list[str]:
        return [p for p in _PROTOCOL_ARG_NAMES if p.startswith(text)]

    def complete_up(self, text, line, begidx, endidx):
        return self._complete_protocol(text)

    def complete_down(self, text, line, begidx, endidx):
        return self._complete_protocol(text)

    def complete_probe(self, text, line, begidx, endidx):
        return self._complete_protocol(text)

    def complete_list(self, text, line, begidx, endidx):
        return self._complete_protocol(text)

    def complete_seeds(self, text, line, begidx, endidx):
        return self._complete_protocol(text)

    def complete_discover(self, text, line, begidx, endidx):
        return self._complete_protocol(text)

    def complete_feeds(self, text, line, begidx, endidx):
        return self._complete_protocol(text)

    # Subaction completion — ``watch <TAB>`` → add/list/remove/test, etc.
    # Only completes the *first* token after the command; later positionals
    # are command-specific and not worth a generic completer.
    def _complete_subaction(self, cmd_name: str, text: str, line: str) -> list[str]:
        # Strip leading command from the line, count remaining tokens to
        # decide whether the cursor is on the subaction slot.
        remainder = line[len(cmd_name):].lstrip()
        already = remainder.split()
        if len(already) > 1 or (len(already) == 1 and not text):
            return []  # past the subaction position
        return [a for a in _SUBACTIONS.get(cmd_name, ()) if a.startswith(text)]

    def complete_watch(self, text, line, begidx, endidx):
        return self._complete_subaction("watch", text, line)

    def complete_tor(self, text, line, begidx, endidx):
        return self._complete_subaction("tor", text, line)

    def complete_blocklist(self, text, line, begidx, endidx):
        return self._complete_subaction("blocklist", text, line)

    def complete_keys(self, text, line, begidx, endidx):
        return self._complete_subaction("keys", text, line)

    def complete_schedule(self, text, line, begidx, endidx):
        return self._complete_subaction("schedule", text, line)

    @staticmethod
    def _split(line: str) -> Optional[list[str]]:
        try:
            return shlex.split(line)
        except ValueError as e:
            _err_console.print(f"[fail]parse error:[/] {e}")
            return None

    @staticmethod
    def _parse_int_in_range(
        raw: str, lo: int, hi: int, label: str,
    ) -> Optional[int]:
        """Parse ``raw`` as int and require lo <= n <= hi. Print a helpful
        error and return None if invalid; the caller should then return
        without invoking the underlying command. Centralizes the bounds check
        so commands like search/top/scan/crawl don't accept 0, negatives, or
        absurdly-large counts that just stall the DB."""
        try:
            n = int(raw)
        except ValueError:
            _err_console.print(
                f"[fail]{label} must be an integer[/] [muted](got {raw!r})[/]"
            )
            return None
        if n < lo or n > hi:
            _err_console.print(
                f"[fail]{label} out of range[/] [muted]"
                f"(got {n}; expected {lo}..{hi})[/]"
            )
            return None
        return n

    # ---- info -----------------------------------------------------------

    def do_about(self, _arg: str) -> None:
        """Maintainer, license, and a one-line summary."""
        print_about()

    def do_version(self, _arg: str) -> None:
        """Print darkcat version."""
        _console.print(f"[tag]{LOGO_MINI}[/]  [value]{__version__}[/]")

    # ---- read-only commands --------------------------------------------

    def do_status(self, _arg: str) -> None:
        """Report which protocol daemons are reachable."""
        cmd_status(self.cfg)

    def do_stats(self, _arg: str) -> None:
        """SQLite database statistics."""
        cmd_stats(self.cfg)

    def do_doctor(self, _arg: str) -> None:
        """Health check: home dir, DB, daemons, optional deps. Prints fix hints."""
        cmd_doctor(self.cfg)

    # ---- transport control ---------------------------------------------

    def do_up(self, arg: str) -> None:
        """up PROTO   Start the daemon for a transport (tor | i2p | ipfs | …)."""
        toks = self._split(arg)
        if toks is None or not toks:
            print("usage: up PROTO")
            return
        cmd_up(self.cfg, toks[0])

    def do_down(self, arg: str) -> None:
        """down PROTO   Stop the daemon for a transport."""
        toks = self._split(arg)
        if toks is None or not toks:
            print("usage: down PROTO")
            return
        cmd_down(self.cfg, toks[0])

    def do_probe(self, arg: str) -> None:
        """probe [PROTO|all]   Probe one (or every) transport for reachability."""
        toks = self._split(arg)
        if toks is None:
            return
        cmd_probe(self.cfg, toks[0] if toks else "all")

    def do_seeds(self, arg: str) -> None:
        """seeds [PROTO|all]   Print built-in seed URLs."""
        toks = self._split(arg)
        if toks is None:
            return
        cmd_seeds(toks[0] if toks else "all")

    def do_list(self, arg: str) -> None:
        """list [PROTO|all]   Print curated entry points."""
        toks = self._split(arg)
        if toks is None:
            return
        cmd_list(toks[0] if toks else "all")

    # ---- search / top ---------------------------------------------------

    def do_search(self, arg: str) -> None:
        """search QUERY [-n N] [--strict]   Broad multi-strategy search of crawled pages."""
        toks = self._split(arg)
        if toks is None:
            return
        if not toks:
            print("usage: search QUERY [-n N] [--strict]")
            return
        limit = 50
        strict = False
        query_parts: list[str] = []
        i = 0
        while i < len(toks):
            t = toks[i]
            if t in ("-n", "--limit") and i + 1 < len(toks):
                n = self._parse_int_in_range(toks[i + 1], 1, 10_000, "limit")
                if n is None:
                    return
                limit = n
                i += 2
            elif t == "--strict":
                strict = True
                i += 1
            else:
                query_parts.append(t)
                i += 1
        if not query_parts:
            print("usage: search QUERY [-n N] [--strict]")
            return
        cmd_search(self.cfg, " ".join(query_parts), limit, strict=strict)

    def do_top(self, arg: str) -> None:
        """top [-n N] [-p PROTO]   Highest-scoring crawled pages."""
        toks = self._split(arg)
        if toks is None:
            return
        limit = 20
        protocol: Optional[str] = None
        i = 0
        while i < len(toks):
            t = toks[i]
            if t in ("-n", "--limit") and i + 1 < len(toks):
                n = self._parse_int_in_range(toks[i + 1], 1, 10_000, "limit")
                if n is None:
                    return
                limit = n
                i += 2
            elif t in ("-p", "--protocol") and i + 1 < len(toks):
                protocol = toks[i + 1]
                i += 2
            else:
                print(f"unknown option: {t}")
                return
        cmd_top(self.cfg, limit, protocol)

    # ---- fetch ----------------------------------------------------------

    def do_fetch(self, arg: str) -> None:
        """fetch URL [--show]   Fetch one URL through its transport."""
        toks = self._split(arg)
        if toks is None:
            return
        url: Optional[str] = None
        show = False
        for t in toks:
            if t == "--show":
                show = True
            elif url is None:
                url = t
            else:
                print(f"unexpected argument: {t}")
                return
        if not url:
            print("usage: fetch URL [--show]")
            return
        cmd_fetch(self.cfg, url, show)

    # ---- crawl ----------------------------------------------------------

    def do_crawl(self, arg: str) -> None:
        """crawl [-p PROTO] [-t WORD ...] [-n N] [-d N] [--threshold F]
                 [--per-host N] [--seeds URL ...] [-ep URL] [-epfl N|a]
                 [--follow-clearnet] [--no-cross-protocol]"""
        toks = self._split(arg)
        if toks is None:
            return
        ns = argparse.Namespace(
            protocol="tor",
            topics=[],
            max_pages=100,
            max_depth=2,
            per_host=25,
            threshold=0.0,
            seeds=None,
            seed_file=None,
            entry_point=None,
            entry_point_from_list=None,
            follow_clearnet=False,
            no_cross_protocol=False,
            quiet=False,
        )
        i = 0
        while i < len(toks):
            t = toks[i]
            try:
                if t in ("-p", "--protocol"):
                    ns.protocol = toks[i + 1]; i += 2
                elif t in ("-t", "--topics"):
                    i += 1
                    while i < len(toks) and not toks[i].startswith("-"):
                        ns.topics.append(toks[i]); i += 1
                elif t in ("-n", "--max-pages"):
                    n = self._parse_int_in_range(toks[i + 1], 1, 100_000, "max-pages")
                    if n is None:
                        return
                    ns.max_pages = n; i += 2
                elif t in ("-d", "--max-depth"):
                    n = self._parse_int_in_range(toks[i + 1], 0, 50, "max-depth")
                    if n is None:
                        return
                    ns.max_depth = n; i += 2
                elif t == "--per-host":
                    n = self._parse_int_in_range(toks[i + 1], 1, 10_000, "per-host")
                    if n is None:
                        return
                    ns.per_host = n; i += 2
                elif t == "--threshold":
                    try:
                        f = float(toks[i + 1])
                    except ValueError:
                        print("threshold must be a number"); return
                    if f < 0.0 or f > 100.0:
                        print(f"threshold out of range (got {f}; expected 0..100)")
                        return
                    ns.threshold = f; i += 2
                elif t == "--seeds":
                    ns.seeds = []
                    i += 1
                    while i < len(toks) and not toks[i].startswith("-"):
                        ns.seeds.append(toks[i]); i += 1
                elif t in ("-ep", "--entry-point"):
                    ns.entry_point = toks[i + 1]; i += 2
                elif t in ("-epfl", "--entry-point-from-list"):
                    ns.entry_point_from_list = toks[i + 1]; i += 2
                elif t == "--follow-clearnet":
                    ns.follow_clearnet = True; i += 1
                elif t == "--no-cross-protocol":
                    ns.no_cross_protocol = True; i += 1
                else:
                    print(f"unknown crawl option: {t}")
                    return
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        cmd_crawl(self.cfg, ns)

    # ---- scan / findings ------------------------------------------------

    def do_scan(self, arg: str) -> None:
        """scan [--url URL] [-p PROTO] [--category CAT ...] [--target STR]
                [-n N] [--salt S]   Scan crawled pages for credential leaks."""
        toks = self._split(arg)
        if toks is None:
            return
        ns = argparse.Namespace(
            url=None, category=None, protocol=None, target=None,
            limit=None, salt="",
        )
        i = 0
        while i < len(toks):
            t = toks[i]
            try:
                if t == "--url":
                    ns.url = toks[i + 1]; i += 2
                elif t == "--category":
                    ns.category = []
                    i += 1
                    while i < len(toks) and not toks[i].startswith("-"):
                        ns.category.append(toks[i]); i += 1
                elif t in ("-p", "--protocol"):
                    ns.protocol = toks[i + 1]; i += 2
                elif t == "--target":
                    ns.target = toks[i + 1]; i += 2
                elif t in ("-n", "--limit"):
                    n = self._parse_int_in_range(toks[i + 1], 1, 1_000_000, "limit")
                    if n is None:
                        return
                    ns.limit = n; i += 2
                elif t == "--salt":
                    ns.salt = toks[i + 1]; i += 2
                else:
                    print(f"unknown scan option: {t}")
                    return
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        cmd_scan(self.cfg, ns)

    def do_findings(self, arg: str) -> None:
        """findings [--category CAT] [-p PROTO] [--target STR] [-n N]
                    List leak findings recorded in the DB."""
        toks = self._split(arg)
        if toks is None:
            return
        ns = argparse.Namespace(category=None, protocol=None, target=None, limit=50)
        i = 0
        while i < len(toks):
            t = toks[i]
            try:
                if t == "--category":
                    ns.category = toks[i + 1]; i += 2
                elif t in ("-p", "--protocol"):
                    ns.protocol = toks[i + 1]; i += 2
                elif t == "--target":
                    ns.target = toks[i + 1]; i += 2
                elif t in ("-n", "--limit"):
                    n = self._parse_int_in_range(toks[i + 1], 1, 100_000, "limit")
                    if n is None:
                        return
                    ns.limit = n; i += 2
                else:
                    print(f"unknown findings option: {t}")
                    return
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        cmd_findings(self.cfg, ns)

    # ---- watch / alerts -------------------------------------------------

    def do_watch(self, arg: str) -> None:
        """watch ACTION [opts]   Manage finding watchlist.

        ACTION = add | list | remove ID | test ID
        Options for add:
          --target STR  --category CAT  --sample STR  --regex
          --sink (log | notify | file:PATH | webhook:URL)  --note STR"""
        toks = self._split(arg)
        if toks is None or not toks:
            print(self.do_watch.__doc__)
            return
        action = toks[0]
        rest = toks[1:]
        ns = argparse.Namespace(
            action=action, target=None, category=None, sample=None,
            regex=False, sink=None, note=None, id=None,
        )
        i = 0
        while i < len(rest):
            t = rest[i]
            try:
                if t == "--target":   ns.target = rest[i + 1]; i += 2
                elif t == "--category": ns.category = rest[i + 1]; i += 2
                elif t == "--sample": ns.sample = rest[i + 1]; i += 2
                elif t == "--regex":  ns.regex = True; i += 1
                elif t == "--sink":   ns.sink = rest[i + 1]; i += 2
                elif t == "--note":   ns.note = rest[i + 1]; i += 2
                elif action in ("remove", "test") and ns.id is None:
                    ns.id = int(t); i += 1
                else:
                    print(f"unknown watch arg: {t}")
                    return
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        cmd_watch(self.cfg, ns)

    def do_alerts(self, arg: str) -> None:
        """alerts [-n N]   Show recent alerts."""
        toks = self._split(arg)
        if toks is None:
            return
        ns = argparse.Namespace(limit=50)
        i = 0
        while i < len(toks):
            t = toks[i]
            try:
                if t in ("-n", "--limit"):
                    n = self._parse_int_in_range(toks[i + 1], 1, 10_000, "limit")
                    if n is None:
                        return
                    ns.limit = n; i += 2
                else:
                    print(f"unknown alerts option: {t}")
                    return
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        cmd_alerts(self.cfg, ns)

    # ---- diff / history -------------------------------------------------

    def do_diff(self, arg: str) -> None:
        """diff [--since DUR] [--url URL] [--vs ID] [-p PROTO] [-n N]
                Pages whose text changed; or unified diff for one URL."""
        toks = self._split(arg)
        if toks is None:
            return
        ns = argparse.Namespace(
            since="24h", url=None, vs=None, protocol=None, limit=50,
        )
        i = 0
        while i < len(toks):
            t = toks[i]
            try:
                if t == "--since": ns.since = toks[i + 1]; i += 2
                elif t == "--url": ns.url = toks[i + 1]; i += 2
                elif t == "--vs":
                    v = self._parse_int_in_range(toks[i + 1], 1, 10**12, "vs")
                    if v is None: return
                    ns.vs = v; i += 2
                elif t in ("-p", "--protocol"): ns.protocol = toks[i + 1]; i += 2
                elif t in ("-n", "--limit"):
                    n = self._parse_int_in_range(toks[i + 1], 1, 100_000, "limit")
                    if n is None: return
                    ns.limit = n; i += 2
                else:
                    print(f"unknown diff option: {t}")
                    return
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        cmd_diff(self.cfg, ns)

    def do_history(self, arg: str) -> None:
        """history --url URL [-n N]   List historical snapshots for a URL."""
        toks = self._split(arg)
        if toks is None or not toks:
            print("usage: history --url URL [-n N]")
            return
        ns = argparse.Namespace(url=None, limit=20)
        i = 0
        while i < len(toks):
            t = toks[i]
            try:
                if t == "--url": ns.url = toks[i + 1]; i += 2
                elif t in ("-n", "--limit"):
                    n = self._parse_int_in_range(toks[i + 1], 1, 10_000, "limit")
                    if n is None: return
                    ns.limit = n; i += 2
                else:
                    print(f"unknown history option: {t}")
                    return
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        if not ns.url:
            print("usage: history --url URL [-n N]")
            return
        cmd_history(self.cfg, ns)

    # ---- export / serve -------------------------------------------------

    def do_export(self, arg: str) -> None:
        """export [--format jsonl|stix|misp] [--category C] [-p P] [--target T]
                  [--since DUR] [-n N] [-o PATH]   Export findings."""
        toks = self._split(arg)
        if toks is None:
            return
        ns = argparse.Namespace(
            format="jsonl", category=None, protocol=None, target=None,
            since=None, limit=None, output=None,
        )
        valid_formats = ("jsonl", "stix", "misp")
        i = 0
        while i < len(toks):
            t = toks[i]
            try:
                if t == "--format":
                    fmt = toks[i + 1]
                    # Validate at parse time so users see the error before any
                    # downstream work (DB query, file open) is attempted.
                    if fmt not in valid_formats:
                        print(f"format must be jsonl|stix|misp (got {fmt!r})")
                        return
                    ns.format = fmt; i += 2
                elif t == "--category": ns.category = toks[i + 1]; i += 2
                elif t in ("-p", "--protocol"): ns.protocol = toks[i + 1]; i += 2
                elif t == "--target": ns.target = toks[i + 1]; i += 2
                elif t == "--since":  ns.since = toks[i + 1]; i += 2
                elif t in ("-n", "--limit"):
                    n = int(toks[i + 1])
                    if n <= 0 or n > 1_000_000:
                        print(f"limit must be 1..1_000_000 (got {n})")
                        return
                    ns.limit = n; i += 2
                elif t in ("-o", "--output"): ns.output = toks[i + 1]; i += 2
                else:
                    print(f"unknown export option: {t}")
                    return
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        cmd_export(self.cfg, ns)

    def do_serve(self, arg: str) -> None:
        """serve [--bind HOST:PORT]   Run HIBP-style hash-prefix server.
        Blocks until Ctrl-C, then returns to the prompt."""
        toks = self._split(arg)
        if toks is None:
            return
        ns = argparse.Namespace(bind="127.0.0.1:7531")
        i = 0
        while i < len(toks):
            t = toks[i]
            try:
                if t == "--bind":
                    ns.bind = toks[i + 1]; i += 2
                else:
                    print(f"unknown serve option: {t}")
                    return
            except IndexError:
                print(f"missing value for {t}")
                return
        cmd_serve(self.cfg, ns)

    # ---- discover / feeds / decode-links / ocr / clusters ---------------

    def do_discover(self, arg: str) -> None:
        """discover QUERY [--engines E ...] [--max-per-engine N]
                   [--include-clearnet] [--list-engines]
                   Query darknet search engines for seed URLs."""
        toks = self._split(arg)
        if toks is None:
            return
        ns = argparse.Namespace(
            query=None, engines=None, max_per_engine=50,
            include_clearnet=False, list_engines=False,
        )
        i = 0
        positional: list[str] = []
        while i < len(toks):
            t = toks[i]
            try:
                if t == "--list-engines":
                    ns.list_engines = True; i += 1
                elif t == "--include-clearnet":
                    ns.include_clearnet = True; i += 1
                elif t == "--max-per-engine":
                    ns.max_per_engine = int(toks[i + 1]); i += 2
                elif t == "--engines":
                    ns.engines = []
                    i += 1
                    while i < len(toks) and not toks[i].startswith("-"):
                        ns.engines.append(toks[i]); i += 1
                else:
                    positional.append(t); i += 1
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        if positional:
            ns.query = " ".join(positional)
        cmd_discover(self.cfg, ns)

    def do_feeds(self, arg: str) -> None:
        """feeds URL [--quiet]   Probe sitemap/RSS/Atom/JSON-Feed at URL's host."""
        toks = self._split(arg)
        if toks is None or not toks:
            print("usage: feeds URL [--quiet]")
            return
        ns = argparse.Namespace(url=None, quiet=False)
        for t in toks:
            if t == "--quiet":
                ns.quiet = True
            elif ns.url is None:
                ns.url = t
            else:
                print(f"unexpected arg: {t}")
                return
        if not ns.url:
            print("usage: feeds URL [--quiet]")
            return
        cmd_feeds(self.cfg, ns)

    def do_decode_links(self, arg: str) -> None:
        """decode_links URL [--diff]   Surface URLs hidden in JS/base64/ROT13."""
        toks = self._split(arg)
        if toks is None or not toks:
            print("usage: decode_links URL [--diff]")
            return
        ns = argparse.Namespace(url=None, diff=False)
        for t in toks:
            if t == "--diff":
                ns.diff = True
            elif ns.url is None:
                ns.url = t
            else:
                print(f"unexpected arg: {t}")
                return
        if not ns.url:
            print("usage: decode_links URL [--diff]")
            return
        cmd_decode_links(self.cfg, ns)

    def do_ocr(self, arg: str) -> None:
        """ocr URL [--lang L] [--max-images N]   Fetch + OCR every <img>."""
        toks = self._split(arg)
        if toks is None or not toks:
            print("usage: ocr URL [--lang L] [--max-images N]")
            return
        ns = argparse.Namespace(url=None, lang="eng", max_images=20)
        i = 0
        while i < len(toks):
            t = toks[i]
            try:
                if t == "--lang":
                    ns.lang = toks[i + 1]; i += 2
                elif t == "--max-images":
                    ns.max_images = int(toks[i + 1]); i += 2
                elif ns.url is None:
                    ns.url = t; i += 1
                else:
                    print(f"unexpected arg: {t}")
                    return
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        if not ns.url:
            print("usage: ocr URL [--lang L] [--max-images N]")
            return
        cmd_ocr(self.cfg, ns)

    def do_clusters(self, arg: str) -> None:
        """clusters [--min N] [-n N]   Group pages by identical text content."""
        toks = self._split(arg)
        if toks is None:
            return
        ns = argparse.Namespace(min=2, limit=50)
        i = 0
        while i < len(toks):
            t = toks[i]
            try:
                if t == "--min":
                    ns.min = int(toks[i + 1]); i += 2
                elif t in ("-n", "--limit"):
                    ns.limit = int(toks[i + 1]); i += 2
                else:
                    print(f"unknown clusters option: {t}")
                    return
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        cmd_clusters(self.cfg, ns)

    def do_mirrors(self, arg: str) -> None:
        """mirrors [--rebuild] [--url URL] [--distance D] [--min N] [-n N]
        SimHash near-duplicate clusters or mirrors-of one URL."""
        toks = self._split(arg)
        if toks is None:
            return
        ns = argparse.Namespace(
            rebuild=False, url=None, distance=3, min=2, limit=50,
        )
        i = 0
        while i < len(toks):
            t = toks[i]
            try:
                if t == "--rebuild":
                    ns.rebuild = True; i += 1
                elif t == "--url":
                    ns.url = toks[i + 1]; i += 2
                elif t in ("-d", "--distance"):
                    ns.distance = int(toks[i + 1]); i += 2
                elif t == "--min":
                    ns.min = int(toks[i + 1]); i += 2
                elif t in ("-n", "--limit"):
                    ns.limit = int(toks[i + 1]); i += 2
                else:
                    print(f"unknown mirrors option: {t}")
                    return
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        cmd_mirrors(self.cfg, ns)

    def do_schedule(self, arg: str) -> None:
        """schedule ACTION [args]   list | run-due | run NAME |
        enable NAME | disable NAME | remove NAME"""
        toks = self._split(arg)
        if toks is None or not toks:
            # Default to listing — that's the harmless / informational path.
            cmd_schedule(self.cfg, argparse.Namespace(action="list", json=False))
            return
        action = toks[0]
        rest = toks[1:]
        if action == "list":
            ns = argparse.Namespace(action="list", json=False)
            if rest and rest[0] == "--json":
                ns.json = True
            cmd_schedule(self.cfg, ns)
            return
        if action == "run-due":
            cmd_schedule(self.cfg, argparse.Namespace(action="run-due"))
            return
        if action in ("run", "enable", "disable", "remove"):
            if not rest:
                print(f"usage: schedule {action} NAME")
                return
            cmd_schedule(
                self.cfg, argparse.Namespace(action=action, name=rest[0]),
            )
            return
        print(f"unknown schedule action: {action!r}")

    # ---- tor / blocklist ------------------------------------------------

    def do_tor(self, arg: str) -> None:
        """tor ACTION [args]   newnym | info | circuits | descriptor ONION |
                              bridges | bridges-add LINE | bridges-clear"""
        toks = self._split(arg)
        if toks is None or not toks:
            print(self.do_tor.__doc__)
            return
        action = toks[0]
        if action.startswith("bridges"):
            action = action.replace("_", "-")
        ns = argparse.Namespace(action=action, line=None, onion=None)
        if action == "bridges-add":
            if len(toks) < 2:
                print('usage: tor bridges-add "<bridge line>"')
                return
            ns.line = " ".join(toks[1:])
        elif action == "descriptor":
            if len(toks) < 2:
                print("usage: tor descriptor ONION")
                return
            ns.onion = toks[1]
        cmd_tor(self.cfg, ns)

    def do_blocklist(self, arg: str) -> None:
        """blocklist ACTION [args]   test --file FILE URL... | log [-n N]"""
        toks = self._split(arg)
        if toks is None or not toks:
            print(self.do_blocklist.__doc__)
            return
        action = toks[0]
        rest = toks[1:]
        if action == "test":
            from pathlib import Path
            ns = argparse.Namespace(action="test", file=None, urls=[])
            i = 0
            while i < len(rest):
                t = rest[i]
                if t == "--file":
                    if i + 1 >= len(rest):
                        print("missing FILE")
                        return
                    ns.file = Path(rest[i + 1]); i += 2
                else:
                    ns.urls.append(t); i += 1
            if not ns.file or not ns.urls:
                print("usage: blocklist test --file FILE URL [URL ...]")
                return
            cmd_blocklist(self.cfg, ns)
            return
        if action == "log":
            ns = argparse.Namespace(action="log", limit=50)
            i = 0
            while i < len(rest):
                t = rest[i]
                try:
                    if t in ("-n", "--limit"):
                        ns.limit = int(rest[i + 1]); i += 2
                    else:
                        print(f"unknown blocklist log option: {t}")
                        return
                except (IndexError, ValueError) as e:
                    print(f"bad value for {t}: {e}")
                    return
            cmd_blocklist(self.cfg, ns)
            return
        print(f"unknown blocklist action: {action!r}")

    # ---- telegram / keys / zeronet --------------------------------------

    def do_telegram(self, arg: str) -> None:
        """telegram CHANNEL [--limit N] [--pages N] [--ingest]"""
        toks = self._split(arg)
        if toks is None or not toks:
            print("usage: telegram CHANNEL [--limit N] [--pages N] [--ingest]")
            return
        ns = argparse.Namespace(
            channel=None, limit=20, pages=1, ingest=False,
        )
        i = 0
        while i < len(toks):
            t = toks[i]
            try:
                if t == "--limit":
                    ns.limit = int(toks[i + 1]); i += 2
                elif t == "--pages":
                    ns.pages = int(toks[i + 1]); i += 2
                elif t == "--ingest":
                    ns.ingest = True; i += 1
                elif ns.channel is None:
                    ns.channel = t; i += 1
                else:
                    print(f"unexpected arg: {t}")
                    return
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        if not ns.channel:
            print("usage: telegram CHANNEL [--limit N] [--pages N] [--ingest]")
            return
        cmd_telegram(self.cfg, ns)

    def do_keys(self, arg: str) -> None:
        """keys ACTION   harvest [-p P] [-n N] | list [--fpr FPR] [-n N] | show FPR"""
        toks = self._split(arg)
        if toks is None or not toks:
            print(self.do_keys.__doc__)
            return
        action = toks[0]
        rest = toks[1:]
        ns = argparse.Namespace(
            action=action, protocol=None, fpr=None, fingerprint=None, limit=50,
        )
        if action == "harvest":
            ns.limit = None
            i = 0
            while i < len(rest):
                t = rest[i]
                try:
                    if t in ("-p", "--protocol"):
                        ns.protocol = rest[i + 1]; i += 2
                    elif t in ("-n", "--limit"):
                        ns.limit = int(rest[i + 1]); i += 2
                    else:
                        print(f"unknown harvest option: {t}")
                        return
                except (IndexError, ValueError) as e:
                    print(f"bad value for {t}: {e}")
                    return
            cmd_keys(self.cfg, ns)
            return
        if action == "list":
            i = 0
            while i < len(rest):
                t = rest[i]
                try:
                    if t == "--fpr":
                        ns.fpr = rest[i + 1]; i += 2
                    elif t in ("-n", "--limit"):
                        ns.limit = int(rest[i + 1]); i += 2
                    else:
                        print(f"unknown list option: {t}")
                        return
                except (IndexError, ValueError) as e:
                    print(f"bad value for {t}: {e}")
                    return
            cmd_keys(self.cfg, ns)
            return
        if action == "show":
            if not rest:
                print("usage: keys show FPR")
                return
            ns.fingerprint = rest[0]
            cmd_keys(self.cfg, ns)
            return
        print(f"unknown keys action: {action!r}")

    def do_zeronet_walk(self, arg: str) -> None:
        """zeronet_walk SITE [--limit N] [--ingest]   Walk content.json graph."""
        toks = self._split(arg)
        if toks is None or not toks:
            print("usage: zeronet-walk SITE [--limit N] [--ingest]")
            return
        ns = argparse.Namespace(site=None, limit=100, ingest=False)
        i = 0
        while i < len(toks):
            t = toks[i]
            try:
                if t == "--limit":
                    ns.limit = int(toks[i + 1]); i += 2
                elif t == "--ingest":
                    ns.ingest = True; i += 1
                elif ns.site is None:
                    ns.site = t; i += 1
                else:
                    print(f"unexpected arg: {t}")
                    return
            except (IndexError, ValueError) as e:
                print(f"bad value for {t}: {e}")
                return
        if not ns.site:
            print("usage: zeronet-walk SITE [--limit N] [--ingest]")
            return
        cmd_zeronet(self.cfg, ns)

    # ---- exit -----------------------------------------------------------

    def do_quit(self, _arg: str) -> bool:
        """Exit the shell."""
        print("bye")
        return True

    def do_exit(self, _arg: str) -> bool:
        """Exit the shell."""
        return self.do_quit(_arg)

    def do_EOF(self, _arg: str) -> bool:
        """Exit on Ctrl-D."""
        print()
        return True


def run_shell(cfg: Config) -> int:
    _install_history()
    shell = DarkcatShell(cfg)
    intro: Optional[str] = None
    while True:
        try:
            shell.cmdloop(intro=intro)
            break  # clean exit (do_quit / do_EOF)
        except KeyboardInterrupt:
            # Ctrl+C at the input prompt — keep the REPL alive. Suppress
            # the intro on re-entry so the banner only renders once.
            intro = ""
            print()
            continue
    return 0
