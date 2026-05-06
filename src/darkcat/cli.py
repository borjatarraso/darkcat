"""darkcat CLI — multi-protocol darknet/overlay crawler."""
# PYTHON_ARGCOMPLETE_OK
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional

from darkcat import __author__, __email__, __license__, __url__, __version__
from darkcat.config import Config
from darkcat.crawler import Crawler, CrawlPolicy
from darkcat.entries import ENTRY_POINTS, render_all, render_protocol
from darkcat.fetcher import Fetcher
from darkcat.protocols import Protocol, classify, normalize
from darkcat.seeds import SEEDS_BY_PROTOCOL, all_seeds
from darkcat.storage import Storage
from darkcat.theme import (
    AMBER,
    DIM_FG,
    LOGO,
    LOGO_MINI,
    NEON_CYAN,
    NEON_GREEN,
    NEON_PINK,
    NEON_RED,
    TAGLINE,
    about_panel,
    banner,
    get_console,
    panel,
    rule,
    score_style,
    status_dot,
    table,
)
from darkcat.topic_filter import TopicFilter

# One module-level console — re-used by every command. Rich auto-detects when
# stdout is a pipe and drops styling there, so this is safe for `| grep` etc.
console = get_console()
err_console = get_console(stderr=True)


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

PROTOCOL_TABLE = [
    # Anonymous overlays
    ("tor",         "*.onion (v2/v3)",                "Tor SOCKS5      127.0.0.1:9050"),
    ("i2p",         "*.i2p, *.b32.i2p",               "I2P HTTP        127.0.0.1:4444"),
    ("lokinet",     "*.loki",                          "system TUN (lokinet)"),
    ("freenet",     "freenet:CHK@…/USK@…/…",          "FProxy          127.0.0.1:8888"),
    ("gnunet",      "*.gnu, *.zkey",                   "system GNS resolver"),
    ("zeronet",     "zero://<address>",                "ZeroNet UI      127.0.0.1:43110"),
    ("yggdrasil",   "IPv6 in 200::/7",                 "system TUN (yggdrasil)"),
    ("cjdns",       "IPv6 in fc00::/8",                "system TUN (cjdroute)"),
    ("reticulum",   "lxmf://, reticulum://",           "rnsd / LXMF app (stub)"),
    # Distributed web
    ("ipfs",        "ipfs://CID",                      "IPFS gw        127.0.0.1:8080"),
    ("ipns",        "ipns://name",                     "IPFS gw        127.0.0.1:8080"),
    ("hyper",       "hyper://<key>",                   "hyper.fyi gateway (best-effort)"),
    ("dat",         "dat://<key>",                     "stub — deprecated, use hyper"),
    ("ssb",         "ssb://%feed%.ed25519",            "stub — needs SSB pub"),
    ("earthstar",   "earthstar://<share>",             "stub — JS-only ecosystem"),
    ("cabal",       "cabal://<key>",                   "stub — needs cabal client"),
    # Small-web / text protocols
    ("gemini",      "gemini://host[:1965]/path",       "native TLS+TOFU client"),
    ("spartan",     "spartan://host[:300]/path",       "native socket client"),
    ("nex",         "nex://host[:1900]/path",          "native socket client"),
    ("gopher",      "gopher://host[:70]/<sel>",        "native socket client"),
    ("gophers",     "gophers://host[:70]/<sel>",       "native TLS socket"),
    ("finger",      "finger://user@host[:79]",         "native socket client"),
    ("nntp",        "news://server[/group[/article]]", "native NNTP client"),
    ("webfinger",   "acct:user@host",                  "/.well-known/webfinger over HTTPS"),
    # Alt-naming
    ("namecoin",    "*.bit",                           "ncdns or OpenNIC DNS"),
    ("emercoin",    "*.emc, *.lib, *.bazar, *.coin",   "emcDNS or OpenNIC DNS"),
    ("ens",         "*.eth",                           "eth.limo gateway fallback"),
    ("handshake",   "*.hns + .c .p .forever …",        "hsd/hnsd or hns.is fallback"),
    ("unstoppable", "*.crypto, *.nft, *.x, *.wallet …","Unstoppable / Cloudflare resolver"),
    ("solana",      "*.sol",                           "stub — needs SNS-aware client"),
    ("opennic",     ".geek .free .indy .pirate …",     "OpenNIC DNS"),
    # Messaging / F2F (stubs)
    ("briar",       "briar://",                        "stub — mobile mesh messenger"),
    ("tox",         "tox://<id>",                      "stub — Tox messaging"),
    ("retroshare",  "retroshare://",                   "stub — Retroshare client"),
    # File-sharing identifiers (parsed only)
    ("magnet",      "magnet:?xt=urn:btih:HASH&dn=…",   "decoded to text/plain"),
    ("ed2k",        "ed2k://|file|name|size|hash|/",   "decoded to text/plain"),
    # Fallback
    ("clearnet",    "https://anything",                "Tor SOCKS5 if up, else direct"),
]

# Commands grouped by user task. Order matches the typical workflow:
# bootstrap → fetch/crawl → search/analyze → monitor → comms → run frontends.
COMMAND_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Getting started", [
        ("init",    "First-run setup: create ~/.darkcat, probe daemons, print a tour."),
        ("status",  "Show which protocol daemons are reachable."),
        ("doctor",  "Health check: home dir, DB, daemons, optional deps. Prints fix hints."),
        ("about",   "Show the about panel (logo + version + license + source URL)."),
        ("seeds",   "Print built-in seed URLs (one protocol or 'all')."),
        ("list",    "Print curated entry points with descriptions."),
    ]),
    ("Fetch & crawl", [
        ("fetch",   "Fetch a single URL through the right transport."),
        ("crawl",   "BFS-crawl from seeds with optional topic scoring."),
        ("discover","Query darknet search engines for seed URLs."),
        ("feeds",   "Probe sitemap / RSS / Atom / JSON-Feed for a host."),
        ("schedule","Persistent re-crawls: add/list/remove/run-due, daemon loop."),
    ]),
    ("Search & analyze", [
        ("search",  "FTS5 search of previously crawled pages."),
        ("top",     "Show highest-scoring crawled pages."),
        ("stats",   "Database statistics."),
        ("history", "List historical text snapshots for one URL."),
        ("diff",    "Pages whose text changed; or unified diff for one URL."),
        ("clusters","Group pages by identical text (mirror / clone detection)."),
        ("mirrors", "Cluster near-duplicate pages via SimHash (fuzzy mirrors)."),
        ("decode-links","Surface URLs hidden in JS / base64 / ROT13 in a page."),
        ("ocr",     "Fetch a page and OCR every <img> via Tesseract."),
        ("plugins", "List per-site extractor plugins (built-ins + ~/.darkcat/plugins)."),
    ]),
    ("Monitoring & alerts", [
        ("scan",    "Scan crawled pages for credential / leak indicators."),
        ("findings","List leak findings recorded in the DB."),
        ("watch",   "Manage finding watchlist (add/list/remove/test)."),
        ("alerts",  "Show alerts fired by the watchlist."),
        ("liveness","Probe URLs for uptime / latency / content drift."),
        ("export",  "Export findings as JSONL / STIX 2.1 / MISP event JSON."),
        ("serve",   "Run a HIBP-style hash-prefix server over the findings DB."),
    ]),
    ("Networks & transports", [
        ("up",      "Start a transport daemon (tor, i2p, ipfs, …) — verbose."),
        ("down",    "Stop a transport daemon — verbose."),
        ("probe",   "Probe one transport for reachability and latency."),
        ("tor",     "Tor control: newnym / info / circuits / descriptor / bridges."),
        ("blocklist","Test rules against URLs / view blocklist audit log."),
        ("zeronet-walk","Walk a ZeroNet site's content.json graph."),
    ]),
    ("Identity & comms", [
        ("cookies", "Manage the persistent cookie jar for authenticated crawls."),
        ("personas","Burner identities per (network, site): handles, passwords, jars."),
        ("contacts","Surface Session/SimpleX/Tox/XMPP/Matrix IDs from crawled pages."),
        ("chat",    "Login + read + send over Telegram / Matrix / XMPP / SimpleX / Session."),
        ("telegram","Scrape t.me/s/<channel> messages (no auth, no API key)."),
        ("keys",    "Harvest / list / show PGP public keys from crawled pages."),
    ]),
    ("Frontends & dashboards", [
        ("tui",       "Launch the Textual TUI."),
        ("shell",     "Launch the interactive REPL."),
        ("gui",       "Launch the Tkinter desktop GUI."),
        ("dashboard", "Read-only HTTP dashboard over the crawl DB (stdlib server)."),
    ]),
]

COMMAND_TABLE = [item for _group, items in COMMAND_GROUPS for item in items]


def _build_help_description() -> str:
    return "\n".join([
        "Darkcat — multi-protocol darknet & overlay-network crawler.",
        "",
        "Routes URLs through the right transport for each address scheme,",
        "crawls from seed lists with topic-keyword scoring, and stores",
        "results in SQLite (FTS5). Ships a CLI and a Textual TUI.",
    ])


def _build_help_epilog() -> str:
    proto_lines = ["Supported protocols:", ""]
    for name, form, transport in PROTOCOL_TABLE:
        proto_lines.append(f"  {name:<12} {form:<36} {transport}")
    cmd_lines: list[str] = ["", "Commands (run `darkcat <command> -h` for details):"]
    for group_title, items in COMMAND_GROUPS:
        cmd_lines.append("")
        cmd_lines.append(f"  {group_title}:")
        for name, desc in items:
            cmd_lines.append(f"    {name:<14} {desc}")
    examples = [
        "",
        "First-time tour:",
        "",
        "  darkcat init                                # create ~/.darkcat, probe daemons",
        "  darkcat status                              # check which transports are up",
        "  darkcat -la                                 # curated entries for every protocol",
        "  darkcat fetch https://tor.taxi/             # fetch one page through Tor",
        "  darkcat crawl -ep https://tor.taxi/ -t whistleblower",
        "  darkcat search 'secure drop'                # search what you've crawled",
        "",
        "More examples:",
        "",
        "  darkcat -l tor                              # curated tor entry points",
        "  darkcat crawl -p tor   -epfl 1              # tor entry #1",
        "  darkcat crawl -p gemini -epfl a -d 3        # all gemini entries, depth 3",
        "  darkcat crawl -p tor -t whistleblower leak -n 200",
        "  darkcat scan --target example.com           # leaks mentioning your domain",
        "  darkcat scan --url https://pastebin.com/raw/xyz   # one URL on demand",
        "  darkcat findings --category email_password -n 100",
        "  darkcat tui                                 # terminal UI (Textual)",
        "  darkcat shell                               # interactive REPL",
        "  darkcat gui                                 # desktop GUI (Tkinter)",
        "",
        "Run `darkcat about` for maintainer / license info, or `darkcat <cmd> -h`",
        "for a single command's full options and usage.",
    ]
    return "\n".join(proto_lines + cmd_lines + examples)


def _build_about_text() -> str:
    """Plain-text about block — used by callers that want a string (REPL)."""
    proto_count = len(PROTOCOL_TABLE)
    return "\n".join([
        f"Darkcat {__version__}",
        "Multi-protocol darknet & overlay-network crawler with topic filtering.",
        "",
        f"Maintainer:  {__author__} <{__email__}>",
        f"License:     {__license__}",
        f"Protocols:   {proto_count} transports + {proto_count - 1} schemes recognized",
        "",
        "Run `darkcat -h` for the full reference, or `darkcat -la` to discover",
        "curated entry points across every supported protocol.",
    ])


def print_about() -> None:
    """Render the about block: logo + a key/value panel."""
    proto_count = len(PROTOCOL_TABLE)
    banner(console, version=__version__)
    body = (
        f"[key]maintainer[/]  [value]{__author__}[/] [muted]<{__email__}>[/]\n"
        f"[key]license[/]     [value]{__license__}[/]\n"
        f"[key]protocols[/]   [value]{proto_count} transports[/] "
        f"[muted]+ {proto_count - 1} URL schemes[/]\n\n"
        f"[muted]Run [/][key]darkcat -h[/][muted] for the full reference, or "
        f"[/][key]darkcat -la[/][muted] to discover curated entry points.[/]"
    )
    console.print(panel("identity", body))


# ---------------------------------------------------------------------------
# Custom argparse actions
# ---------------------------------------------------------------------------

class _AboutAction(argparse.Action):
    def __init__(self, option_strings, dest=argparse.SUPPRESS, **kw):
        super().__init__(option_strings, dest=dest, default=argparse.SUPPRESS, nargs=0, **kw)

    def __call__(self, parser, namespace, values, option_string=None):
        print_about()
        parser.exit(0)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="darkcat",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=_build_help_description(),
        epilog=_build_help_epilog(),
    )

    info = p.add_argument_group("information")
    info.add_argument("-V", "--version", action="version", version=f"darkcat {__version__}",
                      help="Print version and exit")
    info.add_argument("--about", action=_AboutAction,
                      help="Print maintainer, license, and a one-line summary, then exit")
    info.add_argument("-l", "--list", metavar="PROTOCOL", default=None,
                      help="Print curated entry points for PROTOCOL and exit "
                           "(use 'all' to print every protocol).")
    info.add_argument("-la", "--list-all", action="store_true",
                      help="Print curated entry points for every protocol and exit "
                           "(shorthand for `-l all`).")

    g = p.add_argument_group("daemon endpoints")
    g.add_argument("--db", type=Path, default=None,
                   help="SQLite DB path (default ~/.darkcat/crawl.db)")
    g.add_argument("--tor-port", type=int, default=9050, help="Tor SOCKS5 port (default 9050)")
    g.add_argument("--tor-control-port", type=int, default=9051,
                   help="Tor control port for NEWNYM / bridges (default 9051)")
    g.add_argument("--tor-control-password", default=None,
                   help="Password for Tor control auth (omit to use cookie/null auth).")
    g.add_argument("--tor-control-cookie", type=Path, default=None,
                   help="Path to Tor control cookie file (auto-discovered via PROTOCOLINFO if omitted).")
    g.add_argument("--no-tor-isolation", action="store_true",
                   help="Disable per-host SOCKS auth → single circuit for all Tor fetches.")
    g.add_argument("--i2p-port", type=int, default=4444, help="I2P HTTP proxy port (default 4444)")
    g.add_argument("--ipfs-port", type=int, default=8080, help="IPFS gateway port (default 8080)")
    g.add_argument("--public-ipfs", action="store_true",
                   help="Allow public IPFS gateway fallback (leaks request to a third party)")
    g.add_argument("--cookie-jar", type=Path, default=None, metavar="PATH",
                   help="Persistent Netscape-format cookie jar (default: none). "
                        "Enables authenticated crawls — see `darkcat cookies --help`.")

    output = p.add_argument_group("output")
    output.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    output.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress per-page progress during crawl (only print the summary)")

    sub = p.add_subparsers(dest="cmd", required=False, metavar="COMMAND")

    pinit = sub.add_parser(
        "init",
        help="First-run setup: create ~/.darkcat, probe daemons, print next steps.",
        description=(
            "Bootstrap a fresh darkcat install:\n"
            "  • create ~/.darkcat and chmod 0700 (DB, personas, cookies, sessions)\n"
            "  • probe Tor / I2P / IPFS daemons and report reachability\n"
            "  • create a placeholder cookie jar and persona vault\n"
            "  • print a curated first-crawl tour\n\n"
            "Idempotent — safe to re-run. Existing files are never overwritten."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pinit.add_argument("--no-probe", action="store_true",
                       help="Skip the daemon-reachability probe (faster, offline-friendly).")

    sub.add_parser("status", help="Show which protocol daemons are reachable.")

    sub.add_parser(
        "doctor",
        help="Health check: home dir, DB, daemons, optional deps. Prints fix hints.",
        description=(
            "Run a battery of self-checks against the darkcat install:\n"
            "  • ~/.darkcat exists and is mode 0700\n"
            "  • crawl.db opens and passes SQLite quick_check\n"
            "  • at least one transport daemon is reachable\n"
            "  • optional deps (Pillow, tesseract) are present\n"
            "  • cookie jar (if configured) exists\n\n"
            "Prints ✓ / ⚠ / ✗ for each, with a one-line fix hint where "
            "relevant. Exits 0 if every check is OK or just a warning, "
            "1 if any check failed (CI-friendly)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub.add_parser(
        "about",
        help="Show the about panel (logo + version + license + source URL).",
    )

    pup = sub.add_parser(
        "up",
        help="Start a transport daemon (tor, i2p, ipfs, …) — verbose.",
        description=(
            "Start the daemon that backs a transport, streaming every "
            "command darkcat runs (and the daemon's stdout) to your terminal "
            "so you can see exactly how the transport comes up.\n\n"
            "Strategy:\n"
            "  1. systemctl --user start <unit>    if a user unit exists\n"
            "  2. spawn the daemon binary directly (and remember the PID)\n"
            "  3. otherwise, print the suggested  sudo systemctl …  command"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pup.add_argument("protocol", help="Protocol name (tor, i2p, ipfs, freenet, zeronet, gnunet, …)")

    pdn = sub.add_parser(
        "down",
        help="Stop a transport daemon — verbose.",
        description=(
            "Stop the daemon that backs a transport. If darkcat spawned it, "
            "we send SIGTERM (then SIGKILL after 5s). Otherwise we attempt "
            "`systemctl --user stop` or surface the system command."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pdn.add_argument("protocol")

    ppr = sub.add_parser(
        "probe",
        help="Describe the reachability check for a transport and run it.",
        description=(
            "Print the exact probe darkcat runs (e.g. \"TCP connect to "
            "127.0.0.1:4444\") and report ● reachable or ○ not reachable. "
            "Pass 'all' to probe every transport."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ppr.add_argument("protocol", nargs="?", default="all")

    pf = sub.add_parser("fetch", help="Fetch a single URL through the right transport.")
    pf.add_argument("url")
    pf.add_argument("--show", action="store_true", help="Print decoded page text and links")
    pf.add_argument("--render", action="store_true",
                    help="Use headless Chromium (Playwright) for JS-heavy pages. "
                         "Routes via the same proxy as the regular transport.")
    pf.add_argument("--render-timeout", type=float, default=45.0,
                    help="Page-load timeout in seconds when --render is set (default 45).")

    pc = sub.add_parser(
        "crawl",
        help="BFS-crawl from seeds with optional topic scoring.",
        description=(
            "Crawl breadth-first from seed URLs. Pages are scored against --topics; "
            "only pages scoring above --threshold expand their links.\n\n"
            "Seed precedence (highest → lowest):\n"
            "  1. -ep / --entry-point URL              one explicit URL\n"
            "  2. -epfl / --entry-point-from-list N|a  curated entry #N (1-based) for -p\n"
            "  3. --seeds URL [URL ...]                explicit seeds list\n"
            "  4. --seed-file PATH                     one URL per line\n"
            "  5. -p / --protocol PROTO                built-in seeds for PROTO (or 'all')"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src = pc.add_argument_group("seed source (highest to lowest precedence)")
    src.add_argument("-ep", "--entry-point", metavar="URL", default=None,
                     help="Use a single URL as the only seed; protocol auto-detected.")
    src.add_argument("-epfl", "--entry-point-from-list", metavar="N|a", default=None,
                     help="Use entry #N (1-based) from the curated list for --protocol; "
                          "pass 'a' or 'all' to use every entry.")
    src.add_argument("--seeds", nargs="*", metavar="URL",
                     help="Explicit seed URLs (overrides built-ins)")
    src.add_argument("--seed-file", type=Path, metavar="PATH",
                     help="File with one seed URL per line (# for comments)")
    src.add_argument("-p", "--protocol",
                     choices=list(SEEDS_BY_PROTOCOL.keys()) + ["all"],
                     default="tor",
                     help="Built-in seed set / context for -epfl (default: tor)")

    topic = pc.add_argument_group("topic filter")
    topic.add_argument("-t", "--topics", nargs="*", default=[], metavar="WORD",
                       help="Topic keywords / quoted phrases (e.g. -t privacy 'secure drop')")
    topic.add_argument("--threshold", type=float, default=0.0, metavar="N",
                       help="Minimum topic score required to expand a page's links (default 0)")

    scope = pc.add_argument_group("crawl scope")
    scope.add_argument("-n", "--max-pages", type=int, default=100, metavar="N",
                       help="Stop after N pages (default 100)")
    scope.add_argument("-d", "--max-depth", type=int, default=2, metavar="N",
                       help="Max BFS depth from seeds (default 2)")
    scope.add_argument("--per-host", type=int, default=25, metavar="N",
                       help="Max pages per host (default 25)")

    net = pc.add_argument_group("network policy")
    net.add_argument("--follow-clearnet", action="store_true",
                     help="Follow clearnet links found inside darknet pages")
    net.add_argument("--no-cross-protocol", action="store_true",
                     help="Stay within the protocol of the seed (don't follow cross-network links)")
    net.add_argument("--blocklist", type=Path, default=None, metavar="FILE",
                     help="Skip URLs / hosts / hashes listed in FILE; audit to blocklist_audit.")
    net.add_argument("--render", action="store_true",
                     help="Render every fetched page with headless Chromium "
                          "(Playwright). Slower but unlocks JS-only content.")
    net.add_argument("--render-timeout", type=float, default=45.0,
                     help="Per-page render timeout in seconds (default 45).")
    net.add_argument("--newnym-after", type=int, default=3, metavar="N",
                     help="Fire Tor SIGNAL NEWNYM after N consecutive errors on "
                          "the same .onion host (default 3, 10s rate-limit-aware).")
    net.add_argument("--no-newnym", action="store_true",
                     help="Disable reactive Tor circuit rotation entirely.")
    net.add_argument("--backoff-max", type=float, default=60.0, metavar="SEC",
                     help="Cap on per-host exponential backoff (default 60s).")

    ps = sub.add_parser("search", help="FTS5 search of previously crawled pages.")
    ps.add_argument("query")
    ps.add_argument("-n", "--limit", type=int, default=50, metavar="N",
                    help="Max results (default 50)")
    ps.add_argument("--strict", action="store_true",
                    help="Require every word (AND of phrases) instead of broad prefix-OR matching.")

    pt = sub.add_parser("top", help="Show highest-scoring crawled pages.")
    pt.add_argument("-n", "--limit", type=int, default=20, metavar="N", help="Max results (default 20)")
    pt.add_argument("-p", "--protocol", default=None,
                    help="Filter to a single protocol (e.g. tor, gemini, i2p)")

    sub.add_parser("stats", help="Database statistics.")

    pseed = sub.add_parser("seeds", help="Print built-in seed URLs (one protocol or 'all').")
    pseed.add_argument("protocol", nargs="?", default="all",
                       choices=list(SEEDS_BY_PROTOCOL.keys()) + ["all"])

    pl = sub.add_parser("list", help="Print curated entry points (one protocol or 'all').")
    pl.add_argument("protocol", nargs="?", default="all",
                    choices=list(ENTRY_POINTS.keys()) + ["all"])

    psc = sub.add_parser(
        "scan",
        help="Scan crawled pages for credential / leak indicators.",
        description=(
            "Pattern-based detection of credential dumps, API keys, private keys, "
            "credit cards, BIP-39 mnemonics, SQL dumps, and breach-marker keywords "
            "in already-crawled pages. Findings store a salted SHA-256 of each "
            "secret plus a redacted preview — never the raw secret."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    psc.add_argument("--url", default=None,
                     help="Scan one live URL (fetch + scan, do not store body).")
    psc.add_argument("--category", nargs="*", default=None, metavar="CAT",
                     help="Restrict to these categories (run with no args to see them).")
    psc.add_argument("-p", "--protocol", default=None,
                     help="Restrict offline scan to pages from this protocol.")
    psc.add_argument("--target", default=None, metavar="STR",
                     help="Substring match on finding 'target' (e.g. your domain or BIN).")
    psc.add_argument("-n", "--limit", type=int, default=None,
                     help="Process at most N pages.")
    psc.add_argument("--salt", default="",
                     help="Salt for digest hashing (so digests aren't shareable).")

    pfd = sub.add_parser("findings", help="List leak findings recorded in the DB.")
    pfd.add_argument("--category", default=None,
                     help="Filter by category (e.g. email_password, github_token).")
    pfd.add_argument("-p", "--protocol", default=None, help="Filter by protocol.")
    pfd.add_argument("--target", default=None,
                     help="Substring match on target (domain / BIN / etc.).")
    pfd.add_argument("-n", "--limit", type=int, default=50, help="Max rows (default 50).")

    pw = sub.add_parser(
        "watch",
        help="Manage finding watchlist (add/list/remove/test).",
        description=(
            "Watchlist entries match against `target` / `category` / `sample` "
            "of a finding. When `scan` records a new finding that matches, the "
            "configured sink fires.\n\n"
            "Sinks:\n"
            "  log                              stdout audit line\n"
            "  notify                           libnotify desktop notification\n"
            "  file:/path                       append JSON-per-line\n"
            "  webhook:URL                      HTTP POST JSON payload\n"
            "  slack:WEBHOOK_URL                Slack incoming webhook (text)\n"
            "  discord:WEBHOOK_URL              Discord incoming webhook (text)\n"
            "  matrix:HOMESERVER|ROOM|TOKEN     Matrix m.room.message\n"
            "  email:to@host                    SMTP via DARKCAT_SMTP_* env vars"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    psw = pw.add_subparsers(dest="action", required=True, metavar="ACTION")
    pwa = psw.add_parser("add", help="Add a watch entry.")
    pwa.add_argument("--target", default=None,
                     help="Substring (or regex with --regex) on finding target.")
    pwa.add_argument("--category", default=None,
                     help="Exact category (or regex with --regex).")
    pwa.add_argument("--sample", default=None,
                     help="Substring (or regex with --regex) on finding sample.")
    pwa.add_argument("--regex", action="store_true",
                     help="Treat target/category/sample as regex patterns.")
    pwa.add_argument("--sink", required=True,
                     help="log | notify | file:PATH | webhook:URL | "
                          "slack:URL | discord:URL | "
                          "matrix:HOMESERVER|ROOM|TOKEN | email:to@host")
    pwa.add_argument("--note", default=None, help="Free-form note.")
    psw.add_parser("list", help="List all watch entries.")
    pwr = psw.add_parser("remove", help="Remove a watch entry by id.")
    pwr.add_argument("id", type=int)
    pwt = psw.add_parser("test", help="Synthesize a finding to verify the sink.")
    pwt.add_argument("id", type=int)

    pa = sub.add_parser("alerts", help="Show alerts fired by the watchlist.")
    pa.add_argument("-n", "--limit", type=int, default=50,
                    help="Max rows (default 50).")

    pdif = sub.add_parser(
        "diff",
        help="Pages whose text changed; or unified diff for one URL.",
        description=(
            "Without --url, lists URLs whose text snapshot has changed since "
            "DURATION ago (default 24h). With --url, prints a unified diff "
            "between the two newest snapshots (override the older side via --vs ID)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pdif.add_argument("--since", default="24h",
                      help="Duration (e.g. 24h, 7d, 30m, 30s), unix-ts, or ISO date "
                           "(default: 24h).")
    pdif.add_argument("--url", default=None,
                      help="If set, print a unified diff for this URL.")
    pdif.add_argument("--vs", type=int, default=None,
                      help="Diff against this history id (default: 2nd-newest).")
    pdif.add_argument("-p", "--protocol", default=None, help="Filter by protocol.")
    pdif.add_argument("-n", "--limit", type=int, default=50)

    phist = sub.add_parser("history", help="List historical text snapshots for a URL.")
    phist.add_argument("--url", required=True)
    phist.add_argument("-n", "--limit", type=int, default=20)

    pex = sub.add_parser(
        "export",
        help="Export findings as JSONL / STIX 2.1 / MISP event JSON.",
        description=(
            "Produce a SHA-256-hash-based IOC feed from the findings table. "
            "Safe to share — the digest column is what's emitted, never the "
            "raw secret."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pex.add_argument("--format", choices=["jsonl", "stix", "misp"], default="jsonl")
    pex.add_argument("--category", default=None, help="Filter by category.")
    pex.add_argument("-p", "--protocol", default=None, help="Filter by protocol.")
    pex.add_argument("--target", default=None,
                     help="Substring match on target (domain / BIN / etc.).")
    pex.add_argument("--since", default=None,
                     help="Only include findings newer than DURATION (e.g. 24h, 7d).")
    pex.add_argument("-n", "--limit", type=int, default=None,
                     help="Cap rows (default: all matching).")
    pex.add_argument("-o", "--output", default=None,
                     help="Write to PATH (default stdout).")

    psv = sub.add_parser(
        "serve",
        help="Run a HIBP-style hash-prefix server over the findings DB.",
        description=(
            "Read-only HTTP server. Endpoints:\n"
            "  GET /range/<3..8 hex>   match findings by digest prefix\n"
            "  GET /digest/<64 hex>    look up a full digest\n"
            "  GET /healthz            'ok'\n"
            "Localhost-only by default. Findings store hashes, never raw "
            "secrets, so this endpoint is safe to consume from other tooling."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    psv.add_argument("--bind", default="127.0.0.1:7531",
                     help="HOST:PORT (default 127.0.0.1:7531)")

    pdv = sub.add_parser(
        "discover",
        help="Query darknet search engines for seed URLs (Ahmia, Haystak, Torch, Phobos, …).",
        description=(
            "Submit `query` to each engine, parse the result page, harvest "
            "the result links (unwrapping any redirector wrappers), and "
            "print one URL per line on stdout. Pipe the output into a "
            "crawl: `darkcat discover whistleblower | tee seeds.txt && "
            "darkcat crawl --seed-file seeds.txt`."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pdv.add_argument("query", nargs="?", default=None,
                     help="Topic / keyword query.")
    pdv.add_argument("--engines", nargs="*", default=None,
                     help="Only these engines (default: all).")
    pdv.add_argument("--max-per-engine", type=int, default=50)
    pdv.add_argument("--include-clearnet", action="store_true",
                     help="Don't filter result links to darknet TLDs.")
    pdv.add_argument("--list-engines", action="store_true",
                     help="Print available engines and exit.")

    pfd2 = sub.add_parser(
        "feeds",
        help="Probe sitemap / RSS / Atom / JSON-Feed at a host's well-knowns.",
    )
    pfd2.add_argument("url",
                      help="Base URL — only the host part matters.")
    pfd2.add_argument("--quiet", action="store_true",
                      help="Suppress per-path progress on stderr.")

    pdec = sub.add_parser(
        "decode-links",
        help="Surface URLs hidden in JS strings / base64 / ROT13 inside a page.",
    )
    pdec.add_argument("url")
    pdec.add_argument("--diff", action="store_true",
                      help="Only print URLs the normal parser missed.")

    poc = sub.add_parser(
        "ocr",
        help="Fetch a URL and OCR every <img> via Tesseract.",
    )
    poc.add_argument("url")
    poc.add_argument("--lang", default="eng", help="Tesseract language (default eng).")
    poc.add_argument("--max-images", type=int, default=20)

    pcl = sub.add_parser(
        "clusters",
        help="Group pages by identical text content (mirror / clone detection).",
    )
    pcl.add_argument("--min", type=int, default=2,
                     help="Min cluster size (default 2).")
    pcl.add_argument("-n", "--limit", type=int, default=50,
                     help="Max clusters to print (default 50).")

    pck = sub.add_parser(
        "cookies",
        help="Manage the persistent cookie jar (login / session reuse).",
        description=(
            "Authenticated crawls need a logged-in session. The simplest "
            "workflow: log in via Tor Browser, export the cookies as a "
            "Netscape-format text file, then run:\n"
            "  darkcat --cookie-jar ~/.darkcat/cookies.txt cookies import EXPORT.txt\n\n"
            "After import, every fetch / crawl / render that uses the same "
            "--cookie-jar will ride that session. Cookies set by the server "
            "during fetches are saved back to the jar on shutdown."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pcks = pck.add_subparsers(dest="action", required=True, metavar="ACTION")
    pcka = pcks.add_parser("set",
                           help="Set a single cookie scoped to URL's host.")
    pcka.add_argument("url", help="URL whose host the cookie is scoped to.")
    pcka.add_argument("kv", nargs="+", metavar="NAME=VALUE",
                      help="One or more cookies, e.g. session=abc123 csrf=deadbeef")
    pckl = pcks.add_parser("list", help="List cookies (optionally per-host).")
    pckl.add_argument("--host", default=None,
                      help="Only cookies on this host (suffix match).")
    pcki = pcks.add_parser("import", help="Merge cookies from a Netscape-format file.")
    pcki.add_argument("path", type=Path)
    pcke = pcks.add_parser("export", help="Write the jar to a path (Netscape format).")
    pcke.add_argument("path", type=Path)
    pckc = pcks.add_parser("clear", help="Remove cookies (--host narrows; default = all).")
    pckc.add_argument("--host", default=None)
    pckp = pcks.add_parser("path", help="Print the current jar path.")

    pper = sub.add_parser(
        "personas",
        help="Manage per-(network, site) burner personas (handles, passwords, cookie jars).",
        description=(
            "A persona is one identity on one site: handle, password, email, "
            "PGP key id, recovery codes, plus a per-persona cookie jar. The "
            "vault is a JSON file under ~/.darkcat (chmod 0600) and can be "
            "GPG-encrypted symmetrically with `personas encrypt`.\n\n"
            "Workflow:\n"
            "  darkcat personas add bob --network tor --site dread.onion --gen\n"
            "  darkcat personas list\n"
            "  darkcat personas show bob --reveal\n"
            "  darkcat personas use bob          # prints cookie-jar path\n"
            "  darkcat --cookie-jar $(darkcat personas use bob) crawl ...\n"
            "  darkcat personas encrypt          # convert plain → AES-256 .gpg\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ppers = pper.add_subparsers(dest="action", required=True, metavar="ACTION")

    ppera = ppers.add_parser("add", help="Add a new persona.")
    ppera.add_argument("name", help="Persona name (unique, used as filename).")
    ppera.add_argument("--network", default="",
                       help="tor / i2p / clearnet / matrix / lokinet / ...")
    ppera.add_argument("--site", default="", help="Onion or domain (no scheme).")
    ppera.add_argument("--handle", default=None)
    ppera.add_argument("--password", default=None)
    ppera.add_argument("--email", default=None)
    ppera.add_argument("--pgp-key-id", default=None)
    ppera.add_argument("--recovery", default=None,
                       help="Recovery phrase or backup codes.")
    ppera.add_argument("--notes", default=None)
    ppera.add_argument("--user-agent", default=None)
    ppera.add_argument("--proxy", default=None,
                       help="Override SOCKS proxy URL for this persona.")
    ppera.add_argument("--tag", action="append", default=[],
                       dest="tags", metavar="TAG")
    ppera.add_argument("--gen", action="store_true",
                       help="Auto-generate handle and password if not given.")
    ppera.add_argument("--replace", action="store_true",
                       help="Overwrite an existing persona with the same name.")

    pperl = ppers.add_parser("list", help="List personas (filter optional).")
    pperl.add_argument("--network", default=None)
    pperl.add_argument("--site", default=None,
                       help="Substring match (case-insensitive).")
    pperl.add_argument("--tag", default=None)
    pperl.add_argument("--json", action="store_true")

    ppersh = ppers.add_parser("show", help="Print one persona's full record.")
    ppersh.add_argument("name")
    ppersh.add_argument("--reveal", action="store_true",
                        help="Show password / recovery in plaintext.")
    ppersh.add_argument("--json", action="store_true")

    pperrm = ppers.add_parser("remove", help="Delete a persona.")
    pperrm.add_argument("name")

    pperg = ppers.add_parser("gen",
                             help="Generate a handle + password (no save).")
    pperg.add_argument("--length", type=int, default=24,
                       help="Password length (default 24).")

    pperu = ppers.add_parser(
        "use",
        help="Print the cookie-jar path for a persona; touches last_used_at.",
    )
    pperu.add_argument("name")

    ppers.add_parser("path", help="Print the vault file path.")
    ppers.add_parser("encrypt",
                     help="Encrypt the plain vault with a passphrase (gpg -c).")
    pperdec = ppers.add_parser(
        "decrypt",
        help="Decrypt the .gpg vault back to plain JSON.",
    )
    pperdec.add_argument("--keep", action="store_true",
                         help="Keep the .gpg file after decryption (default removes it).")

    pchat = sub.add_parser(
        "chat",
        help="Login + read + send over Telegram / Matrix / XMPP / SimpleX / Session.",
        description=(
            "Two-way chat over messaging networks, using a darkcat persona "
            "as the identity. Backends are loaded lazily: the optional "
            "dependency for an unused backend is never imported.\n\n"
            "Available networks:\n"
            "  telegram   real user-account login (Telethon, MTProto)\n"
            "  matrix     federated client (matrix-nio; optional E2EE)\n"
            "  xmpp       slixmpp; plaintext + MUC; OMEMO TODO\n"
            "  simplex    drives a running simplex-chat WebSocket daemon\n"
            "  session    drives session-cli for Oxen Session Account IDs\n"
            "  tox/briar/ricochet  honest stubs (no maintained Python client)\n\n"
            "Workflow:\n"
            "  darkcat chat backends                           # what's installed\n"
            "  darkcat personas add alice-tg --network telegram --handle +1555... --gen\n"
            "  darkcat chat login telegram --persona alice-tg\n"
            "  darkcat chat list  --persona alice-tg\n"
            "  darkcat chat read  --persona alice-tg CHAT_ID -n 30\n"
            "  darkcat chat send  --persona alice-tg CHAT_ID -m 'hello'\n"
            "  darkcat chat ingest --persona alice-tg CHAT_ID  # store msgs as pages"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pchats = pchat.add_subparsers(dest="action", required=True, metavar="ACTION")
    pchats.add_parser("backends",
                      help="Show which chat backends are installed and ready.")

    pchatlog = pchats.add_parser("login",
                                 help="Authenticate (interactive — phone code, password, ...).")
    pchatlog.add_argument("network",
                          help="telegram / matrix / xmpp / simplex / session / ...")
    pchatlog.add_argument("--persona", required=True,
                          help="Persona name from `darkcat personas list`.")

    pchatlist = pchats.add_parser("list",
                                  help="List channels / rooms / DMs the persona is in.")
    pchatlist.add_argument("--persona", required=True)
    pchatlist.add_argument("--network", default=None,
                           help="Override persona's network field.")
    pchatlist.add_argument("-n", "--limit", type=int, default=100)
    pchatlist.add_argument("--json", action="store_true")

    pchatread = pchats.add_parser("read",
                                  help="Print the last N messages of a channel.")
    pchatread.add_argument("channel_id")
    pchatread.add_argument("--persona", required=True)
    pchatread.add_argument("--network", default=None)
    pchatread.add_argument("-n", "--limit", type=int, default=30)
    pchatread.add_argument("--json", action="store_true")

    pchatsend = pchats.add_parser("send",
                                  help="Post one message to a channel.")
    pchatsend.add_argument("channel_id")
    pchatsend.add_argument("--persona", required=True)
    pchatsend.add_argument("--network", default=None)
    pchatsend.add_argument("-m", "--message", required=True)

    pchating = pchats.add_parser(
        "ingest",
        help="Store messages from a channel as searchable pages in the crawl DB.",
    )
    pchating.add_argument("channel_id")
    pchating.add_argument("--persona", required=True)
    pchating.add_argument("--network", default=None)
    pchating.add_argument("-n", "--limit", type=int, default=200)

    pcon = sub.add_parser(
        "contacts",
        help="List messaging-network contact IDs (Session, SimpleX, Tox, XMPP, Matrix) extracted from crawled pages.",
        description=(
            "Walks crawled pages and surfaces every recognizable contact ID "
            "for messaging-only overlays:\n"
            "  Session    66-hex starting 05 (Oxen Session account)\n"
            "  SimpleX    https://simplex.chat/contact#... and simplex: URIs\n"
            "  Tox        76-hex Tox public-key+nospam+checksum\n"
            "  XMPP       xmpp:user@host or bare JIDs\n"
            "  Matrix     @user:server.tld\n"
            "  Briar      briar://... links\n"
            "  Ricochet   ricochet:onion-address\n\n"
            "Use `darkcat scan` first to populate findings, then this command "
            "summarizes them by network."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pcons = pcon.add_subparsers(dest="action", required=True, metavar="ACTION")
    pconl = pcons.add_parser("list", help="List contacts grouped by network.")
    pconl.add_argument("--network", default=None,
                       help="Filter to one network (session / simplex / tox / xmpp / matrix / briar / ricochet).")
    pconl.add_argument("-n", "--limit", type=int, default=200)
    pconl.add_argument("--json", action="store_true")

    pcons2 = pcons.add_parser("show",
                              help="Show every page that mentions one contact ID.")
    pcons2.add_argument("contact_id")

    pconex = pcons.add_parser("export",
                              help="Export contacts as JSONL or CSV.")
    pconex.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    pconex.add_argument("-o", "--output", default="-",
                        help="Output path; '-' = stdout (default).")

    psch = sub.add_parser(
        "schedule",
        help="Persistent re-crawls (add / list / remove / run-due / loop).",
        description=(
            "Schedule a crawl to re-run at a fixed interval. Schedules are "
            "stored in the same SQLite DB as crawled pages, so you can ship a "
            "darkcat.db between machines and the schedule rides along.\n\n"
            "Workflow:\n"
            "  darkcat schedule add NAME --interval 3600 --seeds URL ... \n"
            "  darkcat schedule list\n"
            "  darkcat schedule run-due          # one pass, fire anything due\n"
            "  darkcat schedule loop --tick 60   # daemon mode, runs forever\n"
            "  darkcat schedule remove NAME\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pschs = psch.add_subparsers(dest="action", required=True, metavar="ACTION")
    pscha = pschs.add_parser("add", help="Add a new schedule.")
    pscha.add_argument("name", help="Schedule name (unique).")
    pscha.add_argument("--interval", type=int, required=True, metavar="SECS",
                       help="Re-run every SECS seconds.")
    pscha.add_argument("--seeds", nargs="+", required=True, metavar="URL")
    pscha.add_argument("--topics", nargs="*", default=[], metavar="WORD")
    pscha.add_argument("--max-pages", type=int, default=None)
    pscha.add_argument("--max-depth", type=int, default=None)
    pscha.add_argument("--per-host", type=int, default=None)
    pscha.add_argument("--threshold", type=float, default=None)
    pscha.add_argument("--follow-clearnet", action="store_true")
    pscha.add_argument("--no-cross-protocol", action="store_true")
    pscha.add_argument("--newnym-after", type=int, default=None)
    pscha.add_argument("--no-newnym", action="store_true")
    pscha.add_argument("--start-in", type=float, default=0.0, metavar="SECS",
                       help="Delay first run by this many seconds (default 0).")

    pschl = pschs.add_parser("list", help="List all schedules.")
    pschl.add_argument("--json", action="store_true",
                       help="Emit JSON instead of a table.")

    pschr = pschs.add_parser("remove", help="Delete a schedule.")
    pschr.add_argument("name")

    pschen = pschs.add_parser("enable", help="Enable a paused schedule.")
    pschen.add_argument("name")

    pschdis = pschs.add_parser("disable", help="Pause a schedule (kept on disk).")
    pschdis.add_argument("name")

    pschrun = pschs.add_parser("run", help="Run one schedule by name now.")
    pschrun.add_argument("name")

    pschs.add_parser("run-due",
                     help="Run every schedule whose next_run_at has passed.")

    pschloop = pschs.add_parser("loop",
                                help="Daemon: poll every --tick seconds forever.")
    pschloop.add_argument("--tick", type=float, default=30.0,
                          help="Poll interval in seconds (default 30).")

    pliv = sub.add_parser(
        "liveness",
        help="Probe URLs for uptime / latency / content drift.",
        description=(
            "Sends a single GET through the right transport, records "
            "latency / status / content-hash, and surfaces drift across "
            "consecutive probes. Probes are stored in the liveness_probes "
            "table for trend analysis.\n\n"
            "Subcommands:\n"
            "  probe URL ...          one-shot probe of one or more URLs\n"
            "  probe --known          probe everything we've crawled before\n"
            "  loop --interval SECS   repeat probes every SECS forever\n"
            "  status                 latest result per URL (table)\n"
            "  history URL            full probe history for one URL\n"
            "  summary [--hours N]    aggregate uptime stats"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    plivs = pliv.add_subparsers(dest="action", required=True, metavar="ACTION")
    plivp = plivs.add_parser("probe", help="Probe one or more URLs once.")
    plivp.add_argument("urls", nargs="*", metavar="URL")
    plivp.add_argument("--known", action="store_true",
                       help="Probe all URLs we've previously crawled.")
    plivp.add_argument("--protocol", default=None,
                       help="With --known, narrow to one protocol.")
    plivp.add_argument("--limit", type=int, default=200,
                       help="With --known, cap at N URLs (default 200).")

    plivl = plivs.add_parser("loop", help="Repeat probes forever.")
    plivl.add_argument("urls", nargs="*", metavar="URL")
    plivl.add_argument("--known", action="store_true")
    plivl.add_argument("--protocol", default=None)
    plivl.add_argument("--limit", type=int, default=200)
    plivl.add_argument("--interval", type=int, default=900, metavar="SECS",
                       help="Pause between full passes (default 900s = 15min).")

    plivst = plivs.add_parser("status",
                              help="Show latest probe per URL.")
    plivst.add_argument("-n", "--limit", type=int, default=100)
    plivst.add_argument("--json", action="store_true")
    plivst.add_argument("--only-down", action="store_true",
                        help="Only show URLs whose latest probe failed.")

    plivh = plivs.add_parser("history", help="Probe history for one URL.")
    plivh.add_argument("url")
    plivh.add_argument("-n", "--limit", type=int, default=50)

    plivsu = plivs.add_parser("summary",
                              help="Aggregate uptime stats over a window.")
    plivsu.add_argument("--hours", type=float, default=24.0,
                        help="Window in hours (default 24).")

    pdash = sub.add_parser(
        "dashboard",
        help="Run the read-only web dashboard over the crawl DB.",
        description=(
            "Stdlib-only HTTP server (no Flask) that exposes pages, "
            "findings, alerts, schedules, and mirror clusters as HTML "
            "+ JSON endpoints. Bind 127.0.0.1 unless you've put "
            "auth in front of it.\n\n"
            "JSON: GET /api/stats, /api/findings, /api/alerts, /api/schedules.\n"
            "Health: GET /healthz."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pdash.add_argument("--bind", default="127.0.0.1:8765",
                       help="HOST:PORT to bind (default 127.0.0.1:8765).")
    pdash.add_argument("--auth-token", default=None, metavar="TOKEN",
                       help="If set, require X-Darkcat-Token header or "
                            "?token= query param to match TOKEN.")

    ppl = sub.add_parser(
        "plugins",
        help="List registered per-site extractor plugins.",
        description=(
            "Plugins override the generic HTML parser for sites whose markup "
            "the generic extractor handles poorly (Dread threads, Telegram /s/ "
            "mirrors, pastebin-style dumps).\n\n"
            "Drop your own plugin at ~/.darkcat/plugins/<name>.py — define a "
            "module-level PLUGINS list of objects with .name, .matches(url), "
            ".parse(url, body, content_type) -> Page|None."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ppl.add_argument("--test-url", default=None, metavar="URL",
                     help="Show which plugin would handle URL (no fetch).")

    pmr = sub.add_parser(
        "mirrors",
        help="Cluster near-duplicate pages via SimHash (fuzzy mirrors).",
        description=(
            "Like `clusters` but tolerant of small text differences. Uses a "
            "64-bit SimHash with 4×16-bit LSH banding so the candidate search "
            "is O(N) instead of O(N²). Use --rebuild after upgrading or to "
            "fingerprint pages crawled before this feature existed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pmr.add_argument("--distance", type=int, default=3,
                     help="Max Hamming distance to count as near-duplicate "
                          "(0 = exact, 3 = default, 8 = loose).")
    pmr.add_argument("--min", type=int, default=2,
                     help="Min cluster size (default 2).")
    pmr.add_argument("-n", "--limit", type=int, default=50,
                     help="Max clusters to print (default 50).")
    pmr.add_argument("--url", default=None,
                     help="If set, list pages near-duplicate to THIS URL "
                          "instead of clustering everything.")
    pmr.add_argument("--rebuild", action="store_true",
                     help="Compute SimHashes for any pages still missing one "
                          "and exit.")

    ptor = sub.add_parser(
        "tor",
        help="Tor control: newnym / info / bridges / bridges-add / bridges-clear.",
        description=(
            "Talk to the Tor control port (default 9051). Auth is auto-"
            "discovered via PROTOCOLINFO (NULL / cookie / password). Use "
            "`bridges-add` to swap pluggable-transport bridges at runtime "
            "(torrc still owns ClientTransportPlugin obfs4 / snowflake / "
            "meek-azure)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pts = ptor.add_subparsers(dest="action", required=True, metavar="ACTION")
    pts.add_parser("newnym", help="Request a new identity (rate-limited).")
    pts.add_parser("info", help="Print version / uptime / circuit status.")
    pts.add_parser("circuits", help="List current circuits via the control port.")
    ptd = pts.add_parser("descriptor", help="Query a v3 onion's descriptor from tor's cache.")
    ptd.add_argument("onion", help="Onion address (with or without .onion suffix).")
    pts.add_parser("bridges", help="List currently configured bridges.")
    pba = pts.add_parser("bridges-add", help="Append a bridge line via SETCONF.")
    pba.add_argument("line",
                     help='Full bridge line, e.g. '
                          '"obfs4 1.2.3.4:443 FINGERPRINT cert=... iat-mode=0"')
    pts.add_parser("bridges-clear", help="Clear all configured bridges.")

    pbl = sub.add_parser(
        "blocklist",
        help="Test rules against URLs / view blocklist audit log.",
        description=(
            "File format: one rule per line, # comments. Prefixes:\n"
            "    host:HOSTNAME           exact host match\n"
            "    .SUFFIX                 host suffix\n"
            "    urlcontains:SUBSTR      URL substring\n"
            "    hash:HEX                SHA-256 of decoded text\n"
            "    HOSTNAME                bare → exact host match\n"
            "Use the file with `darkcat crawl --blocklist FILE`."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pbs = pbl.add_subparsers(dest="action", required=True, metavar="ACTION")
    pbt = pbs.add_parser("test", help="Check whether URL(s) match rules in FILE.")
    pbt.add_argument("--file", required=True, type=Path)
    pbt.add_argument("urls", nargs="+")
    pbg = pbs.add_parser("log", help="Show audit log of blocked URLs.")
    pbg.add_argument("-n", "--limit", type=int, default=50)

    ptg = sub.add_parser(
        "telegram",
        help="Scrape t.me/s/<channel> messages (no auth, no API key).",
        description=(
            "Fetch the public web preview of a Telegram channel and print "
            "the most recent messages. With --ingest, store each message "
            "as a synthetic page so `scan` / `findings` see it like any "
            "other crawl target."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ptg.add_argument("channel", help='Channel name (with or without leading "@").')
    ptg.add_argument("--limit", type=int, default=20)
    ptg.add_argument("--pages", type=int, default=1,
                     help="Pagination depth — each page goes ~20 messages older.")
    ptg.add_argument("--ingest", action="store_true",
                     help="Store each message as a synthetic page.")

    pkey = sub.add_parser(
        "keys",
        help="Harvest / list / show PGP public keys from crawled pages.",
    )
    pks = pkey.add_subparsers(dest="action", required=True, metavar="ACTION")
    pkh = pks.add_parser("harvest", help="Scan crawled pages for PGP key blocks.")
    pkh.add_argument("-p", "--protocol", default=None, help="Filter pages by protocol.")
    pkh.add_argument("-n", "--limit", type=int, default=None)
    pkl = pks.add_parser("list", help="List harvested keys.")
    pkl.add_argument("--fpr", default=None, help="Substring match on fingerprint.")
    pkl.add_argument("-n", "--limit", type=int, default=50)
    pkshow = pks.add_parser("show", help="Print the full key block by fingerprint.")
    pkshow.add_argument("fingerprint")

    pzn = sub.add_parser(
        "zeronet-walk",
        help="Walk a ZeroNet site's content.json graph (requires local ZeroNet UI).",
    )
    pzn.add_argument("site", help='Site address (e.g. "1HelloAddress…").')
    pzn.add_argument("--limit", type=int, default=100,
                     help="Stop after N files (default 100).")
    pzn.add_argument("--ingest", action="store_true",
                     help="Store each file as a page so scan / findings see it.")

    sub.add_parser("tui", help="Launch the Textual TUI.")
    sub.add_parser("shell", help="Launch the interactive REPL.")
    sub.add_parser("gui", help="Launch the Tkinter desktop GUI.")

    return p


def _build_config(args: argparse.Namespace) -> Config:
    cfg = Config()
    if args.db:
        cfg.db_path = args.db
    cfg.tor_socks_port = args.tor_port
    cfg.tor_control_port = args.tor_control_port
    cfg.tor_control_password = args.tor_control_password
    cfg.tor_control_cookie_path = (
        str(args.tor_control_cookie) if args.tor_control_cookie else None
    )
    cfg.tor_stream_isolation = not args.no_tor_isolation
    cfg.i2p_http_port = args.i2p_port
    cfg.ipfs_gateway_port = args.ipfs_port
    cfg.use_public_ipfs_gateway = args.public_ipfs
    if getattr(args, "cookie_jar", None):
        cfg.cookie_jar_path = args.cookie_jar
    return cfg


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(protocol: str) -> int:
    if protocol == "all":
        protocols = list(ENTRY_POINTS.keys())
    elif protocol in ENTRY_POINTS:
        protocols = [protocol]
    else:
        err_console.print(f"[fail]Unknown protocol:[/] [warn]{protocol}[/]")
        err_console.print(f"[muted]Known:[/] {', '.join(ENTRY_POINTS.keys())}")
        return 2
    for proto in protocols:
        entries = ENTRY_POINTS.get(proto, [])
        rule(console, f"[title]{proto}[/]")
        if not entries:
            console.print("  [muted](no curated entry points)[/]\n")
            continue
        for i, e in enumerate(entries, 1):
            console.print(
                f"  [tag][{i:>2}][/] [bold]{e.name}[/]\n"
                f"        [url]{e.url}[/]\n"
                f"        [muted]{e.description}[/]"
            )
        console.print()
    return 0


def cmd_init(cfg: Config, args: argparse.Namespace) -> int:
    """First-run bootstrap. Creates ~/.darkcat (mode 0700), reports daemon
    reachability, and prints a tour. Idempotent — never overwrites."""
    import os as _os
    from darkcat.personas import default_dir as _persona_dir

    home = _persona_dir()
    home.mkdir(parents=True, exist_ok=True)
    try:
        _os.chmod(home, 0o700)
    except OSError:
        pass
    sessions = home / "chat-sessions"
    sessions.mkdir(exist_ok=True)
    try:
        _os.chmod(sessions, 0o700)
    except OSError:
        pass

    rule(console, "[title]darkcat init[/]")
    console.print(f"[ok]+[/] [key]home[/]      [value]{home}[/]")
    console.print(f"[ok]+[/] [key]sessions[/]  [value]{sessions}[/]")
    console.print(f"[ok]+[/] [key]database[/]  [value]{cfg.db_path}[/]")
    console.print()

    if not args.no_probe:
        console.print("[muted]probing daemons …[/]")
        fetcher = Fetcher(cfg)
        statuses = fetcher.status()
        up = sum(1 for ok in statuses.values() if ok)
        total = len(statuses)
        for proto, ok in list(statuses.items())[:6]:
            console.print(f"  {status_dot(ok)} {proto.value:<10} "
                          f"[muted]{_proto_endpoint(cfg, proto)}[/]")
        console.print(f"  [muted]({up}/{total} transports reachable — "
                      f"run [/][key]darkcat status[/][muted] for the full table)[/]")
        console.print()

    console.print("[title]next steps[/]")
    console.print(
        "  [key]darkcat status[/]                       check daemon reachability\n"
        "  [key]darkcat -la[/]                          curated entry points by protocol\n"
        "  [key]darkcat crawl -p tor -n 30[/]           first crawl (Tor seed list, 30 pages)\n"
        "  [key]darkcat search 'leak'[/]                full-text search of crawled corpus\n"
        "  [key]darkcat scan[/]                         credential / leak scan over crawled pages\n"
        "  [key]darkcat personas add bob --gen[/]       create a burner persona\n"
        "  [key]darkcat chat backends[/]                see which chat networks are wired up\n"
        "  [key]darkcat tui[/]                          launch the Textual TUI\n"
    )
    console.print(
        "[muted]docs:[/] [url]docs/QUICKSTART.md[/]  [url]docs/USERGUIDE.md[/]  "
        "[url]docs/NETWORKS.md[/]  [url]docs/INTERNALS.md[/]"
    )
    return 0


def cmd_about() -> int:
    """Print the About panel: logo + version + license + source URL."""
    console.print(about_panel(__version__, url=__url__, license_str=__license__))
    return 0


def cmd_status(cfg: Config) -> int:
    fetcher = Fetcher(cfg)
    statuses = fetcher.status()
    up = sum(1 for ok in statuses.values() if ok)
    total = len(statuses)
    t = table(
        " ", "PROTOCOL", "ENDPOINT",
        title=f"transport reachability  [muted]({up}/{total} up)[/]",
    )
    t.columns[0].justify = "center"
    t.columns[0].no_wrap = True
    t.columns[0].style = NEON_GREEN
    t.columns[1].style = f"bold {NEON_CYAN}"
    t.columns[1].no_wrap = True
    t.columns[2].style = "muted"
    for proto, ok in statuses.items():
        t.add_row(status_dot(ok), proto.value, _proto_endpoint(cfg, proto))
    console.print(t)
    return 0


# ---- darkcat doctor --------------------------------------------------------
#
# A single command that catches the common "darkcat doesn't work" failure
# modes and tells the user what to fix. Designed to be the first thing a
# new user runs after `darkcat init` (or when something later breaks). Each
# check returns one of: "ok" (✓), "warn" (⚠), "fail" (✗). Doctor exits 0
# only if every check is "ok" or "warn"; any "fail" → exit 1 so CI / shell
# scripts can rely on it.

def _doctor_check_home() -> tuple[str, str, str, str]:
    """~/.darkcat exists and is mode 0700 (private)."""
    import os as _os
    import stat as _stat
    from darkcat.personas import default_dir as _persona_dir

    home = _persona_dir()
    if not home.exists():
        return ("fail", "home directory",
                f"{home} is missing",
                "run `darkcat init` to create it")
    try:
        mode = _stat.S_IMODE(_os.stat(home).st_mode)
    except OSError as e:
        return ("warn", "home directory",
                f"{home} exists but stat() failed: {e}", "")
    if mode != 0o700:
        return ("warn", "home directory",
                f"{home} mode is {mode:#o} (expected 0o700)",
                f"run `chmod 0700 {home}`")
    return ("ok", "home directory", str(home), "")


def _doctor_check_db(cfg: Config) -> tuple[str, str, str, str]:
    """crawl.db exists, opens, and passes SQLite quick_check."""
    import sqlite3 as _sql

    db = cfg.db_path
    if not db.exists():
        return ("warn", "crawl database",
                f"{db} not yet created",
                "first crawl creates it; run `darkcat crawl -p tor -n 5` to seed")
    try:
        con = _sql.connect(str(db))
        try:
            row = con.execute("PRAGMA quick_check").fetchone()
            result = row[0] if row else "?"
        finally:
            con.close()
    except _sql.DatabaseError as e:
        return ("fail", "crawl database",
                f"{db} won't open: {e}",
                f"back up and remove {db}; rerun `darkcat init`")
    if result != "ok":
        return ("fail", "crawl database",
                f"{db} integrity check returned {result!r}",
                "back up the file and rebuild from scratch")
    return ("ok", "crawl database", f"{db} ({result})", "")


def _doctor_check_transports(cfg: Config) -> tuple[str, str, str, str]:
    """At least one transport is reachable."""
    fetcher = Fetcher(cfg)
    statuses = fetcher.status()
    up = sum(1 for ok in statuses.values() if ok)
    total = len(statuses)
    if up == 0:
        return ("fail", "transports",
                f"0/{total} transports reachable",
                "start at least one daemon: `darkcat up tor` (or i2p/ipfs/…)")
    if up < 2:
        return ("warn", "transports",
                f"{up}/{total} reachable — only one transport is up",
                "consider `darkcat up i2p` and `darkcat up ipfs` to widen coverage")
    return ("ok", "transports", f"{up}/{total} reachable", "")


def _doctor_check_pillow() -> tuple[str, str, str, str]:
    """Pillow is optional but unlocks the half-block logo and OCR fallbacks."""
    try:
        import PIL  # noqa: F401
    except ImportError:
        return ("warn", "Pillow (PIL)",
                "not installed",
                "pip install Pillow  (enables half-block About logo + OCR)")
    return ("ok", "Pillow (PIL)", PIL.__version__, "")


def _doctor_check_tesseract() -> tuple[str, str, str, str]:
    """`darkcat ocr` needs the tesseract CLI on $PATH."""
    import shutil as _sh
    if not _sh.which("tesseract"):
        return ("warn", "tesseract",
                "not on $PATH",
                "install tesseract-ocr if you want `darkcat ocr` to work")
    return ("ok", "tesseract", "found on $PATH", "")


def _doctor_check_cookies(cfg: Config) -> tuple[str, str, str, str]:
    """Cookie jar — only flagged if the user opted in via --cookie-jar."""
    jar = cfg.cookie_jar_path
    if jar is None:
        return ("ok", "cookie jar", "not configured (per-run cookies only)", "")
    if not jar.exists():
        return ("warn", "cookie jar",
                f"{jar} configured but missing",
                f"create with `touch {jar}` or omit --cookie-jar to disable")
    return ("ok", "cookie jar", str(jar), "")


_DOCTOR_GLYPH = {"ok": "✓", "warn": "⚠", "fail": "✗"}
_DOCTOR_STYLE = {
    "ok":   f"bold {NEON_GREEN}",
    "warn": AMBER,
    "fail": f"bold {NEON_RED}",
}


def doctor_run(cfg: Config) -> list[tuple[str, str, str, str]]:
    """Run every doctor check and return ``(level, label, detail, fix)`` rows.

    Lifted out of :func:`cmd_doctor` so the GUI / TUI can render the same
    matrix into a dialog without spawning a console.
    """
    return [
        _doctor_check_home(),
        _doctor_check_db(cfg),
        _doctor_check_transports(cfg),
        _doctor_check_pillow(),
        _doctor_check_tesseract(),
        _doctor_check_cookies(cfg),
    ]


def cmd_doctor(cfg: Config) -> int:
    """Run a battery of self-checks and report problems with fix hints.

    Useful when something breaks ("crawl says no transports", "search
    returns nothing") and you don't know whether the cause is config,
    daemons, or DB. Exit code 0 if every check is OK or just a warning;
    1 if any check failed.
    """
    rule(console, "[title]darkcat doctor[/]")
    checks = doctor_run(cfg)
    t = table(
        " ", "CHECK", "DETAIL", "FIX",
        title="health checks",
    )
    t.columns[0].justify = "center"
    t.columns[0].no_wrap = True
    t.columns[1].style = f"bold {NEON_CYAN}"
    t.columns[1].no_wrap = True
    t.columns[2].style = "value"
    t.columns[3].style = "muted"
    fails = 0
    warns = 0
    for level, label, detail, fix in checks:
        glyph = _DOCTOR_GLYPH[level]
        style = _DOCTOR_STYLE[level]
        t.add_row(f"[{style}]{glyph}[/]", label, detail, fix or "—")
        if level == "fail":
            fails += 1
        elif level == "warn":
            warns += 1
    console.print(t)
    if fails:
        console.print(
            f"[fail]✗ {fails} check(s) failed[/] — fix the items above and "
            f"re-run [key]darkcat doctor[/]."
        )
        return 1
    if warns:
        console.print(
            f"[warn]⚠ {warns} warning(s)[/] — darkcat works, but the items "
            f"above will limit features."
        )
    else:
        console.print("[ok]✓ all checks passed.[/]")
    return 0


_CTRL_STYLES = {
    "cmd":    f"bold {NEON_PINK}",
    "stdout": "muted",
    "stderr": AMBER,
    "info":   NEON_CYAN,
    "ok":     f"bold {NEON_GREEN}",
    "warn":   AMBER,
    "err":    f"bold {NEON_RED}",
    "muted":  DIM_FG,
}


def _emit_control(level: str, text: str) -> None:
    style = _CTRL_STYLES.get(level, "value")
    # Daemon output and our own [proto] tags contain square brackets — escape
    # so Rich treats them as literal text, not markup.
    safe = text.replace("[", r"\[")
    console.print(f"[{style}]{safe}[/]")


def _resolve_protocol_arg(name: str) -> Optional[Protocol]:
    """Map a CLI string to a Protocol enum, or None if unknown."""
    try:
        return Protocol(name.lower().strip())
    except ValueError:
        return None


def _truncate(s: Optional[str], n: int) -> str:
    """Return ``s`` clipped to ``n`` chars, with a trailing ``…`` if cut.

    None / empty → empty string. The ellipsis lives inside the budget so
    callers don't need to reason about column widths shifting by 1.
    """
    if not s:
        return ""
    if len(s) <= n:
        return s
    if n <= 1:
        return s[:n]
    return s[: n - 1] + "…"


def cmd_up(cfg: Config, name: str) -> int:
    proto = _resolve_protocol_arg(name)
    if proto is None:
        err_console.print(f"[fail]unknown protocol:[/] {name}")
        return 2
    from darkcat.control import TransportControl
    from darkcat.elevation import cli_password_provider
    ctrl = TransportControl(cfg)
    ctrl.set_password_provider(cli_password_provider)
    rule(console, f"{proto.value.upper()} up")
    for ev in ctrl.probe(proto):
        _emit_control(*ev)
    for ev in ctrl.up(proto):
        _emit_control(*ev)
    return 0


def cmd_down(cfg: Config, name: str) -> int:
    proto = _resolve_protocol_arg(name)
    if proto is None:
        err_console.print(f"[fail]unknown protocol:[/] {name}")
        return 2
    from darkcat.control import TransportControl
    from darkcat.elevation import cli_password_provider
    ctrl = TransportControl(cfg)
    ctrl.set_password_provider(cli_password_provider)
    rule(console, f"{proto.value.upper()} down")
    for ev in ctrl.down(proto):
        _emit_control(*ev)
    return 0


def cmd_probe(cfg: Config, name: str) -> int:
    from darkcat.control import TransportControl
    ctrl = TransportControl(cfg)
    if name in ("all", "*"):
        targets = list(Protocol)
    else:
        proto = _resolve_protocol_arg(name)
        if proto is None:
            err_console.print(f"[fail]unknown protocol:[/] {name}")
            return 2
        targets = [proto]
    for proto in targets:
        if not ctrl.has_profile(proto):
            continue
        rule(console, proto.value.upper())
        for ev in ctrl.probe(proto):
            _emit_control(*ev)
    return 0


def _proto_endpoint(cfg: Config, proto: Protocol) -> str:
    mapping = {
        Protocol.TOR: f"socks5://{cfg.tor_socks_host}:{cfg.tor_socks_port}",
        Protocol.I2P: f"http://{cfg.i2p_http_host}:{cfg.i2p_http_port}",
        Protocol.IPFS: f"http://{cfg.ipfs_gateway_host}:{cfg.ipfs_gateway_port}",
        Protocol.IPNS: f"http://{cfg.ipfs_gateway_host}:{cfg.ipfs_gateway_port}",
        Protocol.FREENET: f"http://{cfg.freenet_fproxy_host}:{cfg.freenet_fproxy_port}",
        Protocol.ZERONET: f"http://{cfg.zeronet_host}:{cfg.zeronet_port}",
        Protocol.GEMINI: "(native TLS+TOFU, port 1965)",
        Protocol.SPARTAN: "(native socket, port 300)",
        Protocol.NEX: "(native socket, port 1900)",
        Protocol.GOPHER: "(native socket, port 70)",
        Protocol.GOPHERS: "(native TLS socket, port 70)",
        Protocol.FINGER: "(native socket, port 79)",
        Protocol.NNTP: "(native NNTP client, port 119)",
        Protocol.WEBFINGER: "(.well-known/webfinger over HTTPS)",
        Protocol.HYPER: f"https://*.{cfg.hyper_gateway} (gateway)",
        Protocol.LOKINET: "(system TUN routing)",
        Protocol.GNUNET: "(system GNS resolver)",
        Protocol.YGGDRASIL: "(system TUN, 200::/7)",
        Protocol.CJDNS: "(system TUN, fc00::/8)",
        Protocol.NAMECOIN: "(ncdns / OpenNIC DNS)",
        Protocol.EMERCOIN: "(emcDNS / OpenNIC DNS)",
        Protocol.ENS: f"https://*.{cfg.ens_gateway} (gateway fallback)",
        Protocol.HANDSHAKE: f"https://*.{cfg.handshake_gateway} (gateway fallback)",
        Protocol.UNSTOPPABLE: "(Unstoppable / Cloudflare resolver)",
        Protocol.SOLANA: "(stub — SNS-aware client required)",
        Protocol.OPENNIC: "(OpenNIC DNS server in /etc/resolv.conf)",
        Protocol.DAT: "(stub — deprecated; use hyper)",
        Protocol.SSB: "(stub — needs SSB pub)",
        Protocol.BRIAR: "(stub — mobile mesh messenger)",
        Protocol.TOX: "(stub — Tox messaging)",
        Protocol.RETROSHARE: "(stub — Retroshare client)",
        Protocol.EARTHSTAR: "(stub — JS-only ecosystem)",
        Protocol.CABAL: "(stub — needs cabal client)",
        Protocol.RETICULUM: "(stub — needs rnsd / LXMF app)",
        Protocol.BITCHAT: "(stub — Bluetooth-LE proximity mesh, ~30m radio range)",
        Protocol.SIMPLEX: "(stub — SimpleX SMP queues, no user identifiers)",
        Protocol.SESSION: "(stub — Oxen / Lokinet-routed messaging client required)",
        Protocol.BERTY: "(stub — Berty offline-first P2P client required)",
        Protocol.JAMI: "(stub — Jami / Ring distributed SIP client required)",
        Protocol.NOSTR: "(stub — needs WebSocket relay subscription)",
        Protocol.VEILID: "(stub — needs veilid-server + VeilidChat / Veilid client)",
        Protocol.NYM: "(stub — needs nym-socks5-client mixnet proxy)",
        Protocol.ARWEAVE: f"{getattr(cfg, 'arweave_gateway', 'https://arweave.net')} (gateway)",
        Protocol.MAGNET: "(URI parser — outputs decoded fields)",
        Protocol.ED2K: "(URI parser — outputs decoded fields)",
        Protocol.CLEARNET: "(via Tor SOCKS if available)",
    }
    return mapping.get(proto, "")


def cmd_fetch(cfg: Config, url: str, show: bool, *,
              render: bool = False, render_timeout: float = 45.0) -> int:
    fetcher = Fetcher(cfg)
    proto = fetcher.protocol_for(url)
    console.print(f"[key]protocol[/]   [tag]{proto.value}[/]")
    try:
        if render:
            from darkcat.render import Renderer, RenderUnavailable, is_renderable
            if not is_renderable(proto):
                err_console.print(
                    f"[warn]--render[/] not supported for [tag]{proto.value}[/]; "
                    f"falling back to plain transport."
                )
                result = fetcher.fetch(url)
            else:
                console.print("[muted]rendering with headless Chromium…[/]")
                with Renderer(cfg, timeout=render_timeout,
                              cookie_store=fetcher.cookie_store) as r:
                    result = r.render(url)
        else:
            result = fetcher.fetch(url)
    except Exception as e:
        err_console.print(f"[fail]ERROR:[/] {e}")
        return 2
    finally:
        fetcher.save_cookies()
    if result is None:
        err_console.print("[fail]ERROR:[/] no result")
        return 2
    console.print(
        f"[key]status[/]     [value]{result.status}[/]   "
        f"[key]bytes[/] [value]{len(result.body)}[/]   "
        f"[key]ct[/] [muted]{result.content_type}[/]"
    )
    console.print(f"[key]final[/]      [url]{result.final_url}[/]")
    if show:
        from darkcat.extractor import parse as parse_page
        page = parse_page(result.final_url, result.body, result.content_type)
        if page.title:
            console.print(f"[key]title[/]      [title]{page.title}[/]")
        rule(console, "body")
        console.print(page.text[:8000], style="value", highlight=False, soft_wrap=True)
        if page.links:
            rule(console, f"links  [muted]({len(page.links)})[/]")
            for ln in page.links[:50]:
                console.print(f"  [url]{ln}[/]")
    return 0


def _resolve_seeds(args: argparse.Namespace) -> tuple[list[str], Optional[str]]:
    """Apply seed precedence rules. Return (seeds, protocol-override-or-None).

    -ep wins; the protocol is auto-detected from the URL.
    -epfl is next; uses --protocol (or 'tor' default) to pick a list.
    Then explicit --seeds / --seed-file / --protocol built-ins.
    """
    if args.entry_point:
        url = args.entry_point.strip()
        proto = classify(normalize(url)).value
        return [url], proto

    if args.entry_point_from_list:
        n = args.entry_point_from_list.strip().lower()
        proto = args.protocol
        if proto == "all":
            print("--entry-point-from-list requires a specific --protocol (not 'all').",
                  file=sys.stderr)
            return [], None
        entries = ENTRY_POINTS.get(proto, [])
        if not entries:
            print(f"No curated entries for protocol '{proto}'. "
                  f"Use --seeds or pick another protocol.", file=sys.stderr)
            return [], None
        if n in ("a", "all"):
            return [e.url for e in entries], proto
        try:
            idx = int(n)
        except ValueError:
            print(f"--entry-point-from-list expects a 1-based index or 'a' (got: {n!r})",
                  file=sys.stderr)
            return [], None
        if not (1 <= idx <= len(entries)):
            print(f"Index {idx} out of range for {proto} (1..{len(entries)}).",
                  file=sys.stderr)
            return [], None
        return [entries[idx - 1].url], proto

    seeds: list[str] = []
    if args.seeds:
        seeds.extend(args.seeds)
    if args.seed_file:
        seeds.extend(_read_seed_file(args.seed_file))
    if seeds:
        return seeds, None

    if args.protocol == "all":
        return all_seeds(), None
    return list(SEEDS_BY_PROTOCOL.get(args.protocol, [])), args.protocol


def cmd_crawl(cfg: Config, args: argparse.Namespace) -> int:
    seeds, proto_hint = _resolve_seeds(args)
    if not seeds:
        return 2

    storage = Storage(cfg.db_path)
    tf = TopicFilter(args.topics)
    policy = CrawlPolicy(
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        follow_clearnet=args.follow_clearnet,
        follow_cross_protocol=not args.no_cross_protocol,
        score_threshold=args.threshold,
        per_host_limit=args.per_host,
        backoff_max_delay=getattr(args, "backoff_max", 60.0),
        newnym_after=None if getattr(args, "no_newnym", False) else getattr(args, "newnym_after", 3),
    )
    blocklist = None
    if getattr(args, "blocklist", None):
        from darkcat.blocklist import Blocklist
        blocklist = Blocklist(args.blocklist)

    crawler = Crawler(cfg, storage, tf, policy, blocklist=blocklist)

    renderer = None
    render_cm = None
    if getattr(args, "render", False):
        try:
            from darkcat.render import Renderer
            render_cm = Renderer(
                cfg,
                timeout=getattr(args, "render_timeout", 45.0),
                cookie_store=crawler.fetcher.cookie_store,
            )
            renderer = render_cm.__enter__()
            crawler.renderer = renderer
            console.print("[ok]●[/] [tag]rendering with headless Chromium[/]")
        except Exception as e:
            err_console.print(f"[warn]--render unavailable[/] ({e}); continuing without it.")
            renderer = None

    where = (
        f"entry-point ({proto_hint})" if args.entry_point
        else f"entry-list {args.entry_point_from_list} ({proto_hint})" if args.entry_point_from_list
        else f"protocol={args.protocol}"
    )
    rule(console, "[title]initiating crawl[/]")
    console.print(
        f"  [key]seeds[/]      [value]{len(seeds)}[/]  [muted]({where})[/]\n"
        f"  [key]topics[/]     [value]{' '.join(args.topics) if args.topics else '(none)'}[/]\n"
        f"  [key]max-pages[/]  [value]{policy.max_pages}[/]   "
        f"[key]max-depth[/]  [value]{policy.max_depth}[/]   "
        f"[key]threshold[/]  [value]{policy.score_threshold}[/]"
    )
    rule(console)

    quiet = getattr(args, "quiet", False)

    def on_event(kind: str, payload: dict) -> None:
        if quiet:
            return
        if kind == "fetch":
            score = payload["score"]
            console.print(
                f"  [ok]▶[/] [tag][{payload['protocol']:<10}][/] "
                f"[{score_style(score)}]score={score:.2f}[/] "
                f"[muted]d={payload.get('depth', 0)}[/]  "
                f"[bold]{payload.get('title') or '(no title)'}[/]  "
                f"[url]{payload['url']}[/]"
            )
        elif kind == "error":
            err_console.print(
                f"  [fail]✗[/] [tag][{payload.get('protocol', '?')}][/] "
                f"[muted]{_truncate(payload.get('error', ''), 140)}[/]  [url]{payload['url']}[/]"
            )
        elif kind == "skip":
            console.print(
                f"  [muted]·[/] [muted]skip[/] {payload.get('reason', '')}: "
                f"[url]{payload['url']}[/]"
            )
        elif kind == "newnym":
            console.print(
                f"  [warn]↺[/] [tag]NEWNYM[/] [muted]new circuit for[/] "
                f"[url]{payload.get('host', '?')}[/]"
            )

    try:
        stats = crawler.crawl(seeds, on_event=on_event)
    finally:
        if render_cm is not None:
            try:
                render_cm.__exit__(None, None, None)
            except Exception:
                pass
        crawler.fetcher.save_cookies()
        crawler.close()
        storage.close()
    rule(console, "[title]crawl complete[/]")
    summary = (
        f"[key]fetched[/] [ok]{stats.fetched}[/]   "
        f"[key]errors[/] [fail]{stats.errors}[/]   "
        f"[key]skipped[/] [muted]{stats.skipped}[/]"
    )
    if stats.by_protocol:
        rows = "\n".join(
            f"  [tag]{proto:<11}[/]  [value]{n}[/]"
            for proto, n in stats.by_protocol.items()
        )
        body = f"{summary}\n\n[muted]by protocol:[/]\n{rows}"
    else:
        body = summary
    console.print(panel("summary", body))
    return 0


def cmd_search(cfg: Config, query: str, limit: int, *, strict: bool = False) -> int:
    from darkcat.categorize import categorize_str
    storage = Storage(cfg.db_path)
    try:
        rows = storage.search(query, limit=limit, strict=strict)
    finally:
        storage.close()
    if not rows:
        console.print("[muted]No matches.[/]")
        return 0
    rule(console, f"[title]search:[/] [tag]{query}[/]  [muted]({len(rows)} hit(s))[/]")
    for r in rows:
        keys = r.keys()
        snippet = r["snippet"] if "snippet" in keys else ""
        topic_hits = r["topic_hits"] if "topic_hits" in keys else ""
        category = categorize_str(r["title"], snippet, topic_hits, r["url"])
        console.print(
            f"[{score_style(r['score'])}]{r['score']:>5.2f}[/]  "
            f"[tag]{r['protocol']:<10}[/]  [bold]{r['title'] or '(no title)'}[/]"
            f"   [muted]{category}[/]"
        )
        console.print(f"        [url]{r['url']}[/]")
        if snippet:
            console.print(f"        [muted]…{snippet}…[/]")
        console.print()
    return 0


def cmd_top(cfg: Config, limit: int, protocol: Optional[str]) -> int:
    storage = Storage(cfg.db_path)
    try:
        rows = storage.top(limit=limit, protocol=protocol)
    finally:
        storage.close()
    if not rows:
        console.print("[muted]No pages stored yet — try a crawl first.[/]")
        return 0
    title = "top pages"
    if protocol:
        title += f" [muted]/[/] [tag]{protocol}[/]"
    t = table("SCORE", "PROTO", "TITLE", "URL", title=title)
    t.columns[0].justify = "right"
    t.columns[0].no_wrap = True
    t.columns[1].style = f"bold {NEON_CYAN}"
    t.columns[1].no_wrap = True
    t.columns[2].style = "bold"
    t.columns[3].style = "url"
    for r in rows:
        t.add_row(
            f"[{score_style(r['score'])}]{r['score']:.2f}[/]",
            r["protocol"],
            _truncate(r["title"] or "(no title)", 80),
            r["url"],
        )
    console.print(t)
    return 0


def cmd_stats(cfg: Config) -> int:
    storage = Storage(cfg.db_path)
    try:
        s = storage.stats()
    finally:
        storage.close()
    body = (
        f"[key]database[/]   [muted]{cfg.db_path}[/]\n"
        f"[key]pages[/]      [value]{s['total_pages']:,}[/]\n"
        f"[key]links[/]      [value]{s['links']:,}[/]"
    )
    console.print(panel("storage", body))
    if s["by_protocol"]:
        t = table("PROTOCOL", "PAGES", title="distribution by protocol")
        t.columns[0].style = f"bold {NEON_CYAN}"
        t.columns[1].justify = "right"
        for proto, n in s["by_protocol"].items():
            t.add_row(proto, f"{n:,}")
        console.print(t)
    return 0


def cmd_seeds(protocol: str) -> int:
    if protocol == "all":
        for proto, urls in SEEDS_BY_PROTOCOL.items():
            rule(console, f"[title]{proto}[/]")
            for u in urls:
                console.print(f"  [url]{u}[/]")
            console.print()
    else:
        for u in SEEDS_BY_PROTOCOL.get(protocol, []):
            console.print(f"[url]{u}[/]")
    return 0


def cmd_scan(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat.scanner import CATEGORIES, scan_text
    from darkcat.watch import Watcher

    salt = (args.salt or "").encode("utf-8")
    cats = set(args.category) if args.category else None
    if cats:
        unknown = cats - set(CATEGORIES)
        if unknown:
            print(f"Unknown categories: {', '.join(sorted(unknown))}", file=sys.stderr)
            print(f"Known: {', '.join(CATEGORIES)}", file=sys.stderr)
            return 2

    storage = Storage(cfg.db_path)
    watcher = Watcher(storage)
    fired = 0
    try:
        if args.url:
            from darkcat.extractor import parse as parse_page
            fetcher = Fetcher(cfg)
            try:
                r = fetcher.fetch(args.url)
            except Exception as e:
                print(f"fetch failed: {e}", file=sys.stderr)
                return 2
            page = parse_page(r.final_url, r.body, r.content_type)
            findings = scan_text(page.text, salt=salt)
            findings = _filter_findings(findings, cats, args.target)
            proto = fetcher.protocol_for(args.url).value
            new_findings = storage.record_findings(args.url, proto, findings)
            fired += watcher.apply(args.url, proto, new_findings)
            _print_findings_for(args.url, proto, findings)
            if fired:
                print(f"\n{fired} alert(s) fired.")
            return 0

        scanned = 0
        recorded = 0
        for row in storage.iter_pages_for_scan(protocol=args.protocol, limit=args.limit):
            findings = scan_text(row["text"] or "", salt=salt)
            findings = _filter_findings(findings, cats, args.target)
            scanned += 1
            if findings:
                new_findings = storage.record_findings(
                    row["url"], row["protocol"], findings,
                )
                recorded += len(new_findings)
                fired += watcher.apply(row["url"], row["protocol"], new_findings)
                _print_findings_for(row["url"], row["protocol"], findings, brief=True)
        print(f"\nScanned {scanned} page(s); recorded {recorded} new finding(s); "
              f"fired {fired} alert(s).")
        return 0
    finally:
        storage.close()


def _filter_findings(findings, cats, target):
    if cats:
        findings = [f for f in findings if f.category in cats]
    if target:
        t = target.lower()
        findings = [f for f in findings if t in (f.target or "").lower()]
    return findings


def _print_findings_for(url: str, protocol: str, findings, brief: bool = False) -> None:
    if not findings:
        return
    print(f"[{protocol:<10}] {url}: {len(findings)} finding(s)")
    show = findings[:5] if brief else findings
    for f in show:
        print(f"    [{f.category:<16}] target={f.target or '-':<28} "
              f"conf={f.confidence:.2f}  line={f.line_no}")
        print(f"        sample: {f.sample}")
        print(f"        digest: {f.digest}")
    if brief and len(findings) > len(show):
        print(f"    … and {len(findings) - len(show)} more")


def cmd_findings(cfg: Config, args: argparse.Namespace) -> int:
    storage = Storage(cfg.db_path)
    try:
        rows = storage.findings_query(
            category=args.category, target=args.target,
            protocol=args.protocol, limit=args.limit,
        )
        if not rows:
            print("No findings.")
            return 0
        for r in rows:
            print(f"[{r['category']:<16}] {r['protocol']:<10} "
                  f"target={(r['target'] or '-'):<28} conf={r['confidence']:.2f} "
                  f"line={r['line_no']}")
            print(f"    url:    {r['url']}")
            print(f"    sample: {r['sample']}")
            print(f"    digest: {r['digest']}")
        stats = storage.findings_stats()
        print(f"\nDB total: {stats['total']} finding(s) across "
              f"{len(stats['by_category'])} categor(y/ies).")
        return 0
    finally:
        storage.close()


def cmd_watch(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat.scanner import Finding
    from darkcat.watch import fire as watch_fire, from_row

    storage = Storage(cfg.db_path)
    try:
        if args.action == "add":
            if not (args.target or args.category or args.sample):
                print("watch add: need at least one of --target / --category / --sample",
                      file=sys.stderr)
                return 2
            if not _valid_sink(args.sink):
                print(f"watch add: invalid sink {args.sink!r}. "
                      "Use log | notify | file:PATH | webhook:URL", file=sys.stderr)
                return 2
            wid = storage.watchlist_add(
                target=args.target, category=args.category, sample=args.sample,
                is_regex=args.regex, sink=args.sink, note=args.note,
            )
            print(f"watch added (id={wid})")
            return 0
        if args.action == "list":
            rows = storage.watchlist_query()
            if not rows:
                print("(empty watchlist)")
                return 0
            for r in rows:
                fields = []
                if r["target"]:    fields.append(f"target={r['target']!r}")
                if r["category"]:  fields.append(f"category={r['category']!r}")
                if r["sample"]:    fields.append(f"sample={r['sample']!r}")
                if r["is_regex"]:  fields.append("regex=1")
                note = f"  ({r['note']})" if r["note"] else ""
                print(f"  [{r['id']:>3}] sink={r['sink']:<30} {' '.join(fields)}{note}")
            return 0
        if args.action == "remove":
            if storage.watchlist_remove(args.id):
                print(f"removed watch id={args.id}")
                return 0
            print(f"no watch with id={args.id}", file=sys.stderr)
            return 2
        if args.action == "test":
            row = storage.watchlist_get(args.id)
            if not row:
                print(f"no watch with id={args.id}", file=sys.stderr)
                return 2
            entry = from_row(row)
            f = Finding(
                category=entry.category or "test_category",
                sample=entry.sample or "synthetic-sample",
                digest="0" * 64,
                target=entry.target or "test.example",
                confidence=1.0,
                line_no=1,
            )
            status = watch_fire(entry, f, "darkcat://test", "tor")
            print(f"sink={entry.sink}  status={status}")
            return 0
        print(f"unknown action: {args.action}", file=sys.stderr)
        return 2
    finally:
        storage.close()


def _valid_sink(sink: str) -> bool:
    if sink in ("log", "notify"):
        return True
    return sink.startswith((
        "file:", "webhook:", "slack:", "discord:", "matrix:", "email:",
    ))


def cmd_alerts(cfg: Config, args: argparse.Namespace) -> int:
    storage = Storage(cfg.db_path)
    try:
        rows = storage.alerts_query(limit=args.limit)
        if not rows:
            print("(no alerts)")
            return 0
        for r in rows:
            who = []
            if r["w_target"]:   who.append(f"target={r['w_target']}")
            if r["w_category"]: who.append(f"category={r['w_category']}")
            if r["w_sample"]:   who.append(f"sample={r['w_sample']!r}")
            print(f"[watch={r['watch_id']}] sink={r['w_sink'] or '-'}  "
                  f"status={r['sink_status']}  {' '.join(who)}")
            print(f"    url:    {r['url']}")
            print(f"    digest: {r['digest']}")
        return 0
    finally:
        storage.close()


def _parse_since(s: str) -> float:
    """Parse a duration ('24h', '7d', '30m', '30s'), unix-ts, or ISO date.
    Return an absolute UNIX timestamp."""
    import time as _t
    s = (s or "").strip()
    if not s:
        return 0.0
    if s[-1] in "smhd":
        try:
            n = int(s[:-1])
            mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[s[-1]]
            return _t.time() - n * mult
        except (ValueError, KeyError):
            pass
    try:
        return float(s)
    except ValueError:
        pass
    try:
        from datetime import datetime
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


def cmd_diff(cfg: Config, args: argparse.Namespace) -> int:
    import time as _t
    from difflib import unified_diff

    storage = Storage(cfg.db_path)
    try:
        if args.url:
            hist = storage.page_history_for(args.url, limit=20)
            if len(hist) < 2:
                print(f"need at least 2 snapshots; got {len(hist)} for {args.url}")
                return 0
            new_full = storage.page_history_get(hist[0]["id"])
            if args.vs:
                old_full = storage.page_history_get(args.vs)
                if not old_full or old_full["url"] != args.url:
                    print(f"no snapshot id={args.vs} for {args.url}", file=sys.stderr)
                    return 2
            else:
                old_full = storage.page_history_get(hist[1]["id"])
            diff = unified_diff(
                (old_full["text"] or "").splitlines(),
                (new_full["text"] or "").splitlines(),
                fromfile=f"{args.url}@{int(old_full['captured_at'])}",
                tofile=f"{args.url}@{int(new_full['captured_at'])}",
                n=3,
                lineterm="",
            )
            for line in diff:
                print(line)
            return 0
        since_ts = _parse_since(args.since)
        rows = storage.page_changes_since(
            since_ts, protocol=args.protocol, limit=args.limit,
        )
        if not rows:
            print("(no changes)")
            return 0
        for r in rows:
            t = _t.strftime("%Y-%m-%d %H:%M", _t.localtime(r["latest_at"]))
            print(f"  [{(r['protocol'] or '-'):<10}] {t}  snaps={r['n']:>3}  {r['url']}")
        return 0
    finally:
        storage.close()


def cmd_history(cfg: Config, args: argparse.Namespace) -> int:
    import time as _t
    storage = Storage(cfg.db_path)
    try:
        rows = storage.page_history_for(args.url, limit=args.limit)
        if not rows:
            print(f"no snapshots for {args.url}")
            return 0
        for r in rows:
            t = _t.strftime("%Y-%m-%d %H:%M", _t.localtime(r["captured_at"]))
            print(f"  [{r['id']:>5}] {t}  hash={r['content_hash'][:12]}  "
                  f"bytes={r['bytes']:>8}  title={r['title'] or '-'}")
        return 0
    finally:
        storage.close()


def cmd_export(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat.export import to_jsonl, to_misp, to_stix

    storage = Storage(cfg.db_path)
    try:
        since_ts = _parse_since(args.since) if args.since else None
        rows = storage.findings_export(
            category=args.category, target=args.target,
            protocol=args.protocol, since_ts=since_ts, limit=args.limit,
        )
        out = open(args.output, "w", encoding="utf-8") if args.output else sys.stdout
        try:
            if args.format == "jsonl":
                for line in to_jsonl(rows):
                    out.write(line + "\n")
            elif args.format == "stix":
                out.write(to_stix(rows))
                out.write("\n")
            elif args.format == "misp":
                out.write(to_misp(rows))
                out.write("\n")
        finally:
            if args.output:
                out.close()
        if args.output:
            print(f"wrote {len(rows)} finding(s) → {args.output}")
        return 0
    finally:
        storage.close()


def cmd_serve(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat.server import serve
    return serve(str(cfg.db_path), args.bind)


def cmd_discover(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat.discovery import ENGINES, discover

    if args.list_engines:
        for e in ENGINES:
            mark = "(onion) " if e.only_onion else "        "
            note = f" — {e.note}" if e.note else ""
            print(f"  {e.name:<14} {mark}{note}")
        return 0
    if not args.query:
        print("usage: darkcat discover QUERY [--engines ...] [--list-engines]",
              file=sys.stderr)
        return 2
    fetcher = Fetcher(cfg)

    def on_event(kind: str, payload: dict) -> None:
        if kind == "query":
            print(f"[{payload['engine']}] querying {payload['url']}", file=sys.stderr)
        elif kind == "error":
            print(f"[{payload['engine']}] error: {payload['error']}", file=sys.stderr)
        elif kind == "done":
            print(f"[{payload['engine']}] {payload['found']} link(s)", file=sys.stderr)

    pairs = discover(
        fetcher, args.query, engines=args.engines,
        max_per_engine=args.max_per_engine,
        only_interesting=not args.include_clearnet,
        on_event=on_event,
    )
    for url, _ in pairs:
        print(url)
    return 0


def cmd_feeds(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat.feeds import discover_feeds
    fetcher = Fetcher(cfg)

    def on_event(kind: str, payload: dict) -> None:
        if args.quiet:
            return
        if kind == "try":
            print(f"trying {payload['url']}", file=sys.stderr)
        elif kind == "miss":
            err = payload.get("error") or f"status={payload.get('status', 0)}"
            print(f"  miss ({err})", file=sys.stderr)
        elif kind == "hit":
            print(f"  hit (+{payload['links']})", file=sys.stderr)

    urls = discover_feeds(fetcher, args.url, on_event=on_event)
    for u in urls:
        print(u)
    return 0


def cmd_decode_links(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat.encoded import extract_encoded_links
    from darkcat.extractor import parse as parse_page

    fetcher = Fetcher(cfg)
    try:
        r = fetcher.fetch(args.url)
    except Exception as e:
        print(f"fetch failed: {e}", file=sys.stderr)
        return 2
    body_bytes = r.body if isinstance(r.body, (bytes, bytearray)) else (r.body or "").encode("utf-8")
    text = body_bytes.decode("utf-8", "replace")
    encoded = set(extract_encoded_links(text))
    if args.diff:
        page = parse_page(r.final_url, body_bytes, r.content_type)
        encoded -= set(page.links)
    for u in sorted(encoded):
        print(u)
    return 0


def cmd_ocr(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat.ocr import ocr_available, ocr_page

    if not ocr_available():
        print(
            "tesseract not installed. Install via your package manager:\n"
            "  Fedora:        sudo dnf install tesseract\n"
            "  Debian/Ubuntu: sudo apt install tesseract-ocr",
            file=sys.stderr,
        )
        return 2
    fetcher = Fetcher(cfg)

    def on_event(kind: str, payload: dict) -> None:
        if kind == "image":
            print(f"# image: {payload['url']}", file=sys.stderr)
        elif kind == "ocr":
            print(f"#   chars: {payload['chars']}", file=sys.stderr)
        elif kind == "error":
            print(f"# error: {payload['error']}", file=sys.stderr)

    pairs = ocr_page(
        fetcher, args.url,
        lang=args.lang, max_images=args.max_images,
        on_event=on_event,
    )
    if not pairs:
        print("# (no text recognized)", file=sys.stderr)
        return 0
    for url, text in pairs:
        print(f"## {url}")
        print(text)
        print()
    return 0


def cmd_tor(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat.torctl import TorCtl, TorControlError
    try:
        with TorCtl(
            cfg.tor_socks_host, cfg.tor_control_port,
            password=cfg.tor_control_password,
            cookie_path=cfg.tor_control_cookie_path,
        ) as ctl:
            if args.action == "newnym":
                print(ctl.signal_newnym())
                return 0
            if args.action == "info":
                info = ctl.getinfo(
                    "version", "uptime", "status/circuit-established",
                    "network-liveness",
                )
                if not info:
                    print("(no info)")
                for k, v in info.items():
                    print(f"  {k}: {v}")
                return 0
            if args.action == "circuits":
                info = ctl.getinfo("circuit-status")
                val = info.get("circuit-status", "")
                if not val.strip():
                    print("(no circuits)")
                    return 0
                for line in val.splitlines():
                    if line.strip():
                        print(f"  {line.strip()}")
                return 0
            if args.action == "descriptor":
                onion = args.onion.strip().rstrip("/")
                if onion.endswith(".onion"):
                    onion = onion[:-len(".onion")]
                key = f"hs/v3/descriptor/{onion}"
                info = ctl.getinfo(key)
                val = info.get(key, "")
                if not val:
                    print(f"(no descriptor for {onion})", file=sys.stderr)
                    return 2
                print(val)
                return 0
            if args.action == "bridges":
                bridges = ctl.getconf("Bridge")
                if not bridges:
                    print("(no bridges configured)")
                    return 0
                for b in bridges:
                    print(b)
                return 0
            if args.action == "bridges-add":
                existing = ctl.getconf("Bridge")
                resp = ctl.setconf("Bridge", existing + [args.line])
                print(resp)
                return 0
            if args.action == "bridges-clear":
                resp = ctl.resetconf("Bridge")
                print(resp)
                return 0
    except (OSError, TorControlError) as e:
        print(f"tor control error: {e}", file=sys.stderr)
        return 2
    return 2


def cmd_blocklist(cfg: Config, args: argparse.Namespace) -> int:
    if args.action == "test":
        from darkcat.blocklist import Blocklist
        bl = Blocklist(args.file)
        if bl.is_empty:
            print(f"(blocklist {args.file} has no rules)")
            return 0
        any_blocked = False
        for url in args.urls:
            reason = bl.reason_for_url(url)
            if reason:
                any_blocked = True
                print(f"BLOCK  {url}  ({reason})")
            else:
                print(f"allow  {url}")
        return 0 if not any_blocked else 1
    if args.action == "log":
        storage = Storage(cfg.db_path)
        try:
            rows = storage.blocklist_audit(limit=args.limit)
            if not rows:
                print("(no blocked URLs in audit log)")
                return 0
            import time as _t
            for r in rows:
                t = _t.strftime("%Y-%m-%d %H:%M", _t.localtime(r["blocked_at"]))
                print(f"  [{t}] rule={r['rule']:<30}  {r['url']}")
            return 0
        finally:
            storage.close()
    return 2


def cmd_telegram(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat.telegram import fetch_channel
    fetcher = Fetcher(cfg)
    msgs = fetch_channel(fetcher, args.channel, limit=args.limit, pages=args.pages)
    if not msgs:
        print(f"(no messages for @{args.channel})")
        return 0
    if args.ingest:
        storage = Storage(cfg.db_path)
        try:
            for m in msgs:
                body = m.text + (("\n" + "\n".join(m.links)) if m.links else "")
                storage.record_page(
                    url=m.permalink, final_url=m.permalink,
                    protocol="telegram", status=200,
                    title=f"@{m.channel} #{m.msg_id}",
                    text=body, score=0.0, topic_hits="",
                )
            print(f"ingested {len(msgs)} message(s) from @{args.channel}")
        finally:
            storage.close()
        return 0
    for m in msgs:
        print(f"## @{m.channel} #{m.msg_id} {m.datetime_iso}")
        print(f"   {m.permalink}")
        if m.text:
            print(f"   {m.text}")
        if m.links:
            print(f"   links: {' '.join(m.links)}")
        print()
    return 0


def cmd_keys(cfg: Config, args: argparse.Namespace) -> int:
    storage = Storage(cfg.db_path)
    try:
        if args.action == "harvest":
            from darkcat.pgp import extract_keys, gpg_available
            if not gpg_available():
                print("note: gpg not on PATH — fingerprints/user_ids will be empty.",
                      file=sys.stderr)
            scanned = 0
            recorded = 0
            for row in storage.iter_pages_for_scan(
                protocol=args.protocol, limit=args.limit,
            ):
                scanned += 1
                keys = extract_keys(row["text"] or "")
                for k in keys:
                    if storage.record_pgp_key(
                        fingerprint=k.fingerprint,
                        user_ids="\n".join(k.user_ids),
                        block=k.block,
                        source_url=row["url"],
                    ):
                        recorded += 1
                if keys:
                    print(f"[{row['protocol']:<10}] {row['url']}: "
                          f"{len(keys)} key block(s)")
                    for k in keys:
                        print(f"    fpr={k.fingerprint or '(unknown)':<40} "
                              f"uids={k.user_ids[0] if k.user_ids else '-'}")
            print(f"\nScanned {scanned} page(s); recorded {recorded} new key(s).")
            return 0
        if args.action == "list":
            rows = storage.pgp_keys_query(fingerprint=args.fpr, limit=args.limit)
            if not rows:
                print("(no keys harvested yet — try `darkcat keys harvest`)")
                return 0
            for r in rows:
                fpr = r["fingerprint"] or "(unknown)"
                uids = (r["user_ids"] or "").splitlines()
                print(f"  {fpr}")
                for u in uids:
                    print(f"      uid: {u}")
                print(f"      src: {r['source_url']}")
            return 0
        if args.action == "show":
            rows = storage.pgp_keys_query(fingerprint=args.fingerprint, limit=1)
            if not rows:
                print(f"no key matching {args.fingerprint!r}", file=sys.stderr)
                return 2
            print(rows[0]["block"])
            return 0
        return 2
    finally:
        storage.close()


def cmd_zeronet(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat.extractor import parse as parse_page
    from darkcat.zeronet import walk_site

    fetcher = Fetcher(cfg)
    storage = Storage(cfg.db_path) if args.ingest else None

    def on_event(kind: str, payload: dict) -> None:
        if kind == "fetch":
            print(f"# fetch {payload['url']}", file=sys.stderr)
        elif kind == "error":
            print(f"# error {payload['url']}: {payload['error']}", file=sys.stderr)

    n = 0
    try:
        for url, body, ct in walk_site(
            fetcher, args.site, limit=args.limit, on_event=on_event,
        ):
            n += 1
            if storage:
                page = parse_page(url, body, ct)
                storage.record_page(
                    url=url, final_url=url, protocol="zeronet", status=200,
                    title=page.title, text=page.text,
                    score=0.0, topic_hits="",
                )
            else:
                print(f"# {url} ({len(body)} bytes, {ct or '?'})")
    finally:
        if storage:
            storage.close()
    print(f"\n{n} file(s) walked.", file=sys.stderr)
    return 0


def cmd_clusters(cfg: Config, args: argparse.Namespace) -> int:
    storage = Storage(cfg.db_path)
    try:
        rows = storage.page_clusters(min_size=args.min, limit=args.limit)
        if not rows:
            print("(no clusters; try crawling more pages first)")
            return 0
        for r in rows:
            print(f"== cluster ({r['n']} mirrors) hash={r['content_hash'][:16]} ==")
            for u in (r["urls"] or "").split("\n"):
                if u:
                    print(f"  {u}")
            print()
        return 0
    finally:
        storage.close()


def cmd_cookies(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat.auth import CookieStore
    if cfg.cookie_jar_path is None:
        cfg.cookie_jar_path = Path.home() / ".darkcat" / "cookies.txt"
        console.print(
            f"[muted](no --cookie-jar given; using default "
            f"[url]{cfg.cookie_jar_path}[/])[/]"
        )
    store = CookieStore(cfg.cookie_jar_path)

    if args.action == "path":
        print(cfg.cookie_jar_path)
        return 0

    if args.action == "list":
        cookies = store.list(host=args.host)
        if not cookies:
            print("(no cookies)")
            return 0
        for c in cookies:
            exp = ("session" if not c.expires
                   else time.strftime("%Y-%m-%d", time.localtime(c.expires)))
            sec = "S" if c.secure else "-"
            print(f"  [{sec}] {c.domain:<40} {c.path:<8} {c.name}={c.value[:40]}  exp={exp}")
        print(f"\n{len(cookies)} cookie(s).")
        return 0

    if args.action == "set":
        for kv in args.kv:
            if "=" not in kv:
                err_console.print(f"[fail]ERROR:[/] bad format {kv!r}; expected NAME=VALUE")
                return 2
            name, value = kv.split("=", 1)
            store.set(args.url, name, value)
        store.save()
        print(f"Set {len(args.kv)} cookie(s) on {args.url}.")
        return 0

    if args.action == "import":
        if not args.path.exists():
            err_console.print(f"[fail]ERROR:[/] {args.path} not found")
            return 2
        n = store.import_from(args.path)
        store.save()
        print(f"Imported {n} cookie(s) from {args.path} → {cfg.cookie_jar_path}")
        return 0

    if args.action == "export":
        # Build a fresh jar at the destination path and copy our cookies into it.
        out = CookieStore(args.path)
        for c in store.jar:
            out.jar.set_cookie(c)
        out.save()
        print(f"Exported {len(list(store.jar))} cookie(s) to {args.path}")
        return 0

    if args.action == "clear":
        n = store.clear(args.host)
        store.save()
        scope = f"on host suffix '{args.host}'" if args.host else "(all)"
        print(f"Cleared {n} cookie(s) {scope}.")
        return 0

    err_console.print(f"[fail]ERROR:[/] unknown cookies action {args.action!r}")
    return 2


def _vault_passphrase(prompt_label: str = "vault passphrase") -> str:
    """Read a passphrase: $DARKCAT_VAULT_PASSPHRASE if set, else getpass()."""
    import getpass
    import os as _os
    pw = _os.environ.get("DARKCAT_VAULT_PASSPHRASE")
    if pw:
        return pw
    return getpass.getpass(f"{prompt_label}: ")


def cmd_personas(cfg: Config, args: argparse.Namespace) -> int:
    import json as _json
    import os
    from darkcat import personas as pv

    base = pv.default_dir()
    base.mkdir(parents=True, exist_ok=True)

    # `gen` and `path` don't touch the vault, handle them up-front.
    if args.action == "gen":
        h = pv.generate_handle()
        p = pv.generate_password(args.length)
        console.print(f"[key]handle[/]   [value]{h}[/]")
        console.print(f"[key]password[/] [value]{p}[/]")
        return 0
    if args.action == "path":
        print(pv.vault_path())
        return 0

    # Resolve passphrase only if the vault is encrypted on disk.
    path = pv.vault_path()
    pw = None
    if path.exists() and path.suffix == ".gpg":
        pw = _vault_passphrase()
    try:
        vault = pv.Vault(path=path, passphrase=pw)
    except RuntimeError as e:
        err_console.print(f"[fail]ERROR:[/] {e}")
        return 2

    if args.action == "add":
        handle = args.handle
        password = args.password
        if args.gen:
            handle = handle or pv.generate_handle()
            password = password or pv.generate_password()
        persona = pv.Persona(
            name=args.name,
            network=args.network or "",
            site=args.site or "",
            handle=handle,
            password=password,
            email=args.email,
            pgp_key_id=args.pgp_key_id,
            recovery=args.recovery,
            notes=args.notes,
            user_agent=args.user_agent,
            proxy=args.proxy,
            tags=list(args.tags or []),
            cookie_jar=str(pv.cookie_jar_for(args.name)),
        )
        try:
            vault.add(persona, replace=args.replace)
        except ValueError as e:
            err_console.print(f"[fail]ERROR:[/] {e}")
            return 2
        vault.save()
        console.print(
            f"[ok]+[/] persona [value]{persona.name}[/] saved "
            f"([muted]{persona.network or '?'}/{persona.site or '?'}[/])"
        )
        if password and not args.replace:
            console.print(f"  [muted]password (only shown now): [/]"
                          f"[value]{password}[/]")
        return 0

    if args.action == "list":
        rows = vault.find(network=args.network, site=args.site, tag=args.tag)
        if args.json:
            print(_json.dumps([pv.redact_dict(p) for p in rows], indent=2))
            return 0
        if not rows:
            console.print("[muted](no personas)[/]")
            return 0
        t = table("NAME", "NETWORK", "SITE", "HANDLE", "TAGS", "LAST USED")
        for p in rows:
            last = (time.strftime("%Y-%m-%d", time.localtime(p.last_used_at))
                    if p.last_used_at else "-")
            t.add_row(
                p.name, p.network or "-", _truncate(p.site or "-", 40),
                p.handle or "-", ",".join(p.tags) or "-", last,
            )
        console.print(t)
        return 0

    if args.action == "show":
        p = vault.get(args.name)
        if p is None:
            err_console.print(f"[fail]ERROR:[/] no persona named {args.name!r}")
            return 2
        d = pv.redact_dict(p, reveal=args.reveal)
        if args.json:
            print(_json.dumps(d, indent=2))
            return 0
        for k, v in d.items():
            if v in (None, "", []):
                continue
            console.print(f"  [key]{k:<14}[/] [value]{v}[/]")
        return 0

    if args.action == "remove":
        if not vault.remove(args.name):
            err_console.print(f"[fail]ERROR:[/] no persona named {args.name!r}")
            return 2
        vault.save()
        console.print(f"[ok]-[/] removed [value]{args.name}[/]")
        return 0

    if args.action == "use":
        p = vault.get(args.name)
        if p is None:
            err_console.print(f"[fail]ERROR:[/] no persona named {args.name!r}")
            return 2
        vault.touch(args.name)
        vault.save()
        # Print exactly the path so it composes with `$(...)` substitution.
        print(p.cookie_jar or pv.cookie_jar_for(args.name))
        return 0

    if args.action == "encrypt":
        if vault.is_encrypted:
            console.print("[muted]vault is already encrypted[/]")
            return 0
        if not pv.gpg_available():
            err_console.print("[fail]ERROR:[/] gpg is not installed")
            return 2
        pw1 = _vault_passphrase("new vault passphrase")
        pw2 = _vault_passphrase("confirm passphrase")
        if pw1 != pw2:
            err_console.print("[fail]ERROR:[/] passphrases differ")
            return 2
        new_path = vault.to_encrypted(pw1)
        # Best-effort overwrite of the plain file with zeros before unlinking.
        plain_old = pv.vault_path(plain=True)
        try:
            if plain_old.exists():
                size = plain_old.stat().st_size
                with open(plain_old, "r+b") as fh:
                    fh.write(b"\0" * size)
                    fh.flush()
                    os.fsync(fh.fileno())
                plain_old.unlink()
        except OSError:
            pass
        console.print(f"[ok]+[/] encrypted vault → [url]{new_path}[/]")
        return 0

    if args.action == "decrypt":
        if not vault.is_encrypted:
            console.print("[muted]vault is already plaintext[/]")
            return 0
        old = vault.path
        new_path = vault.to_plain()
        if not args.keep:
            try:
                old.unlink()
            except OSError:
                pass
        console.print(f"[ok]+[/] decrypted vault → [url]{new_path}[/]")
        return 0

    err_console.print(f"[fail]ERROR:[/] unknown personas action {args.action!r}")
    return 2


def cmd_contacts(cfg: Config, args: argparse.Namespace) -> int:
    import json as _json
    from darkcat.scanner import CONTACT_CATEGORIES

    storage = Storage(cfg.db_path)
    try:
        if args.action == "list":
            cats = ([args.network] if args.network else list(CONTACT_CATEGORIES))
            cats = [c for c in cats if c in CONTACT_CATEGORIES]
            if not cats:
                err_console.print(
                    f"[fail]ERROR:[/] unknown network {args.network!r}; "
                    f"known: {', '.join(CONTACT_CATEGORIES)}"
                )
                return 2
            placeholders = ",".join("?" * len(cats))
            with storage._lock:
                rows = storage.conn.execute(
                    f"SELECT category, target, sample, COUNT(*) AS hits, "
                    f"  MAX(found_at) AS latest "
                    f"FROM findings "
                    f"WHERE category IN ({placeholders}) AND target != '' "
                    f"GROUP BY category, target "
                    f"ORDER BY hits DESC, latest DESC "
                    f"LIMIT ?",
                    (*cats, args.limit),
                ).fetchall()
            if args.json:
                print(_json.dumps(
                    [dict(r) for r in rows], indent=2, default=str))
                return 0
            if not rows:
                console.print("[muted](no contacts; run `darkcat scan` first)[/]")
                return 0
            t = table("NETWORK", "CONTACT", "HITS", "LAST SEEN")
            for r in rows:
                latest = (time.strftime("%Y-%m-%d", time.localtime(r["latest"]))
                          if r["latest"] else "-")
                t.add_row(
                    r["category"].replace("_id", ""),
                    _truncate(r["target"], 60),
                    str(r["hits"]),
                    latest,
                )
            console.print(t)
            return 0

        if args.action == "show":
            with storage._lock:
                rows = storage.conn.execute(
                    "SELECT f.category, f.target, f.sample, f.confidence, "
                    "  p.url, p.title, f.found_at "
                    "FROM findings f JOIN pages p ON f.url = p.url "
                    "WHERE f.target = ? "
                    "ORDER BY f.found_at DESC LIMIT 200",
                    (args.contact_id,),
                ).fetchall()
            if not rows:
                console.print("[muted](no pages mention that contact)[/]")
                return 0
            for r in rows:
                console.print(
                    f"[muted]{time.strftime('%Y-%m-%d', time.localtime(r['found_at']))}[/] "
                    f"[tag]{r['category']}[/] [url]{r['url']}[/]"
                )
                if r["title"]:
                    console.print(f"    [muted]{r['title'][:80]}[/]")
            return 0

        if args.action == "export":
            placeholders = ",".join("?" * len(CONTACT_CATEGORIES))
            with storage._lock:
                rows = storage.conn.execute(
                    f"SELECT category, target, sample, confidence, url, found_at "
                    f"FROM findings WHERE category IN ({placeholders}) "
                    f"AND target != '' ORDER BY found_at DESC",
                    tuple(CONTACT_CATEGORIES),
                ).fetchall()
            out_lines: list[str] = []
            if args.format == "jsonl":
                for r in rows:
                    out_lines.append(_json.dumps(dict(r), default=str))
            else:  # csv
                out_lines.append("category,target,sample,confidence,url,found_at")
                for r in rows:
                    def _esc(v) -> str:
                        s = "" if v is None else str(v)
                        if any(c in s for c in ',"\n'):
                            return '"' + s.replace('"', '""') + '"'
                        return s
                    out_lines.append(",".join(_esc(r[k]) for k in (
                        "category", "target", "sample",
                        "confidence", "url", "found_at",
                    )))
            blob = "\n".join(out_lines) + "\n"
            if args.output == "-":
                sys.stdout.write(blob)
            else:
                Path(args.output).write_text(blob)
                console.print(
                    f"[ok]+[/] wrote {len(rows)} contact(s) → "
                    f"[url]{args.output}[/]"
                )
            return 0

        err_console.print(f"[fail]ERROR:[/] unknown contacts action {args.action!r}")
        return 2
    finally:
        storage.close()


def _load_persona_or_die(name: str):
    """Look up a persona by name. Honors the encrypted-vault flow."""
    from darkcat import personas as pv
    path = pv.vault_path()
    pw = None
    if path.exists() and path.suffix == ".gpg":
        pw = _vault_passphrase()
    vault = pv.Vault(path=path, passphrase=pw)
    p = vault.get(name)
    if p is None:
        err_console.print(
            f"[fail]ERROR:[/] no persona named {name!r}; "
            f"`darkcat personas list` to see existing ones"
        )
        return None, None
    return vault, p


def cmd_chat(cfg: Config, args: argparse.Namespace) -> int:
    import json as _json
    from darkcat import chat as ch

    if args.action == "backends":
        rows = ch.availability_report()
        t = table("NETWORK", "READY", "DEPENDENCY")
        for r in rows:
            t.add_row(
                r["network"],
                "[ok]yes[/]" if r["available"] else "[muted]no[/]",
                r["dep"] or "?",
            )
        console.print(t)
        any_missing = any(not r["available"] for r in rows)
        if any_missing:
            console.print()
            console.print("[muted]install hints:[/]")
            for r in rows:
                if r["available"] or not r.get("hint"):
                    continue
                console.print(f"  [key]{r['network']:<9}[/] {r['hint']}")
        return 0

    vault, persona = _load_persona_or_die(args.persona)
    if persona is None:
        return 2
    network = (args.network or persona.network or "").strip()
    if not network:
        err_console.print(
            f"[fail]ERROR:[/] persona {persona.name!r} has no network; "
            f"pass --network or set it on the persona"
        )
        return 2

    try:
        m = ch.open_messenger(network, persona)
    except ch.BackendUnavailable as e:
        err_console.print(f"[fail]ERROR:[/] {e}")
        return 2

    try:
        m.connect()
    except ch.AuthError as e:
        err_console.print(f"[fail]auth:[/] {e}")
        return 2
    vault.touch(persona.name)
    vault.save()

    try:
        if args.action == "login":
            console.print(
                f"[ok]+[/] logged in as [value]{persona.name}[/] on "
                f"[value]{network}[/]; session cached at "
                f"[muted]{m.sessions_dir}[/]"
            )
            return 0

        if args.action == "list":
            channels = m.list_channels(limit=args.limit)
            if args.json:
                print(_json.dumps(
                    [vars(c) for c in channels], indent=2, default=str))
                return 0
            if not channels:
                console.print("[muted](no channels)[/]")
                return 0
            t = table("ID", "KIND", "NAME", "PEOPLE", "UNREAD")
            for c in channels:
                t.add_row(
                    str(c.id), c.kind, _truncate(c.name, 50),
                    str(c.participants), str(c.unread),
                )
            console.print(t)
            return 0

        if args.action == "read":
            if network == "xmpp":
                console.print(
                    "[muted](XMPP without MAM has no backlog — listening "
                    "~3s for live messages …)[/]"
                )
            messages = m.read(args.channel_id, limit=args.limit)
            if args.json:
                print(_json.dumps(
                    [{k: getattr(msg, k) for k in
                      ("channel_id", "msg_id", "sender", "text", "ts")}
                     for msg in messages], indent=2, default=str))
                return 0
            if not messages:
                console.print("[muted](no messages)[/]")
                return 0
            for msg in messages:
                ts = (time.strftime("%Y-%m-%d %H:%M",
                                    time.localtime(msg.ts))
                      if msg.ts else "-")
                console.print(
                    f"[muted]{ts}[/] [tag]{_truncate(msg.sender or '?', 24)}[/] "
                    f"{msg.text}"
                )
            return 0

        if args.action == "send":
            sent = m.send(args.channel_id, args.message)
            console.print(
                f"[ok]>[/] sent to [value]{args.channel_id}[/] "
                f"(msg_id={sent.msg_id or '?'})"
            )
            return 0

        if args.action == "ingest":
            from darkcat.scanner import scan_text
            messages = m.read(args.channel_id, limit=args.limit)
            storage = Storage(cfg.db_path)
            try:
                synthetic_proto = f"chat-{network}"
                n_pages = 0
                n_findings = 0
                for msg in messages:
                    url = (
                        f"chat://{network}/{persona.name}/"
                        f"{args.channel_id}/{msg.msg_id or msg.ts}"
                    )
                    title = (msg.text or "")[:80].replace("\n", " ")
                    storage.record_page(
                        url=url, final_url=url,
                        protocol=synthetic_proto, status=200,
                        title=title, text=msg.text or "",
                        score=0.0, topic_hits="",
                    )
                    findings = scan_text(msg.text or "", salt=b"")
                    storage.record_findings(url, synthetic_proto, findings)
                    n_pages += 1
                    n_findings += len(findings)
            finally:
                storage.close()
            console.print(
                f"[ok]+[/] ingested {n_pages} message(s), "
                f"{n_findings} finding(s) from "
                f"[value]{network}[/]/[value]{args.channel_id}[/]"
            )
            return 0

        err_console.print(f"[fail]ERROR:[/] unknown chat action {args.action!r}")
        return 2
    finally:
        try:
            m.disconnect()
        except Exception:
            pass


def cmd_liveness(cfg: Config, args: argparse.Namespace) -> int:
    import json as _json
    from darkcat import liveness as liv

    storage = Storage(cfg.db_path)
    try:
        if args.action == "probe" or args.action == "loop":
            urls: list[str] = list(getattr(args, "urls", []) or [])
            if getattr(args, "known", False):
                urls += liv.known_urls(
                    storage, protocol=args.protocol, limit=args.limit,
                )
            urls = list(dict.fromkeys(urls))  # de-dupe, preserve order
            if not urls:
                err_console.print(
                    "[fail]ERROR:[/] no URLs given. Pass URLs or --known."
                )
                return 2

            def _emit(res):
                if res["ok"]:
                    drift = " [warn]Δ drift[/]" if res.get("drift") else ""
                    console.print(
                        f"  [ok]●[/] [{res['protocol']:<10}] "
                        f"{res['status']} [muted]{res['latency_ms']}ms[/] "
                        f"[muted]{res['bytes']}B[/]{drift} "
                        f"[url]{res['url']}[/]"
                    )
                else:
                    console.print(
                        f"  [fail]●[/] [{res['protocol']:<10}] "
                        f"[muted]{res['latency_ms'] or 0}ms[/] "
                        f"[fail]{_truncate(res['error'] or '?', 80)}[/] "
                        f"[url]{res['url']}[/]"
                    )

            if args.action == "probe":
                liv.probe_many(cfg, storage, urls, on_result=_emit)
                return 0

            # loop
            console.print(
                f"[ok]●[/] liveness loop: {len(urls)} URL(s), "
                f"interval={args.interval}s, Ctrl-C to stop"
            )
            try:
                while True:
                    rule(console, "[title]liveness pass[/]")
                    liv.probe_many(cfg, storage, urls, on_result=_emit)
                    slept = 0
                    while slept < args.interval:
                        time.sleep(min(0.5, args.interval - slept))
                        slept += 0.5
            except KeyboardInterrupt:
                console.print("\n[muted]stopped[/]")
            return 0

        if args.action == "status":
            rows = liv.latest_per_url(storage, limit=args.limit)
            if args.only_down:
                rows = [r for r in rows if not r["ok"]]
            if args.json:
                print(_json.dumps([dict(r) for r in rows], indent=2,
                                  default=str, ensure_ascii=False))
                return 0
            if not rows:
                console.print("[muted](no probes)[/]")
                return 0
            try:
                for r in rows:
                    state = "[ok]●[/]" if r["ok"] else "[fail]●[/]"
                    lat = f"{r['latency_ms']}ms" if r["latency_ms"] is not None else "-"
                    stat = r["status"] if r["status"] is not None else "-"
                    console.print(
                        f"  {state} [{r['protocol'] or '?':<10}] "
                        f"[muted]{stat:<3}[/] [muted]{lat:<7}[/] "
                        f"[muted]{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['probed_at']))}[/] "
                        f"[url]{r['url']}[/]"
                        + (f"  [fail]{_truncate(r['error'], 80)}[/]" if not r["ok"] else "")
                    )
            except KeyboardInterrupt:
                console.print("\n[muted](interrupted)[/]")
            return 0

        if args.action == "history":
            rows = liv.history_for(storage, args.url, limit=args.limit)
            if not rows:
                print(f"(no probes for {args.url})")
                return 0
            try:
                for r in rows:
                    state = "[ok]●[/]" if r["ok"] else "[fail]●[/]"
                    console.print(
                        f"  {state} {time.strftime('%Y-%m-%d %H:%M', time.localtime(r['probed_at']))}  "
                        f"status={r['status']}  latency={r['latency_ms']}ms  "
                        f"hash={(r['content_hash'] or '')[:12]}  "
                        f"{_truncate(r['error'], 60)}"
                    )
            except KeyboardInterrupt:
                console.print("\n[muted](interrupted)[/]")
            return 0

        if args.action == "summary":
            s = liv.liveness_summary(storage, hours=args.hours)
            console.print(panel(
                f"liveness summary (last {s['since_hours']}h)",
                f"  [key]probes[/] [value]{s['total_probes']}[/]   "
                f"[key]ok[/] [ok]{s['ok_probes']}[/]   "
                f"[key]urls[/] [value]{s['unique_urls']}[/]   "
                f"[key]success[/] [value]{s['success_rate']*100:.1f}%[/]\n"
                "[muted]by protocol:[/]\n" +
                "\n".join(f"  [tag]{p:<10}[/] [value]{n}[/]"
                          for p, n in s["by_protocol"].items()),
            ))
            return 0

        err_console.print(f"[fail]ERROR:[/] unknown liveness action {args.action!r}")
        return 2
    finally:
        storage.close()


def cmd_dashboard(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat.dashboard import serve as serve_dashboard
    return serve_dashboard(
        str(cfg.db_path), args.bind,
        auth_token=getattr(args, "auth_token", None) or "",
    )


def cmd_plugins(cfg: Config, args: argparse.Namespace) -> int:
    from darkcat import plugins
    plugins.load_all()
    regs = plugins.registered()
    if args.test_url:
        m = plugins.find(args.test_url)
        if m is None:
            print(f"(no plugin matches {args.test_url})")
            return 1
        print(f"{getattr(m, 'name', type(m).__name__)} matches {args.test_url}")
        return 0
    if not regs:
        console.print("[muted](no plugins registered)[/]")
        return 0
    user_dir = Path.home() / ".darkcat" / "plugins"
    console.print(f"[muted]user plugin dir:[/] {user_dir} "
                  f"({'exists' if user_dir.is_dir() else 'not present'})")
    for p in regs:
        name = getattr(p, "name", type(p).__name__)
        cls = type(p).__name__
        mod = type(p).__module__
        console.print(f"  [tag]{name:<20}[/] [muted]{mod}.{cls}[/]")
    console.print(f"\n[ok]●[/] {len(regs)} plugin(s) registered.")
    return 0


def cmd_schedule(cfg: Config, args: argparse.Namespace) -> int:
    import json as _json
    from darkcat.crawler import CrawlPolicy
    from darkcat.scheduler import (
        encode_policy, run_schedule, run_due, loop_forever,
    )

    storage = Storage(cfg.db_path)
    try:
        if args.action == "add":
            policy_kw: dict = {}
            for src, dst in (
                ("max_pages", "max_pages"),
                ("max_depth", "max_depth"),
                ("per_host", "per_host_limit"),
                ("threshold", "score_threshold"),
                ("newnym_after", "newnym_after"),
            ):
                v = getattr(args, src, None)
                if v is not None:
                    policy_kw[dst] = v
            if getattr(args, "follow_clearnet", False):
                policy_kw["follow_clearnet"] = True
            if getattr(args, "no_cross_protocol", False):
                policy_kw["follow_cross_protocol"] = False
            if getattr(args, "no_newnym", False):
                policy_kw["newnym_after"] = None
            policy = CrawlPolicy(**policy_kw)
            sid = storage.add_schedule(
                name=args.name,
                seeds_json=_json.dumps(list(args.seeds), ensure_ascii=False),
                topics_json=_json.dumps(list(args.topics), ensure_ascii=False),
                policy_json=encode_policy(policy),
                interval_sec=args.interval,
                first_run_in=args.start_in,
            )
            console.print(
                f"[ok]●[/] schedule [bold]{args.name}[/] added "
                f"(id={sid}, interval={args.interval}s, "
                f"seeds={len(args.seeds)})"
            )
            return 0

        if args.action == "list":
            rows = storage.list_schedules()
            if getattr(args, "json", False):
                out = []
                for r in rows:
                    out.append({
                        "name": r["name"],
                        "enabled": bool(r["enabled"]),
                        "interval_sec": r["interval_sec"],
                        "next_run_at": r["next_run_at"],
                        "last_run_at": r["last_run_at"],
                        "last_status": r["last_status"],
                        "seeds": _json.loads(r["seeds_json"] or "[]"),
                        "topics": _json.loads(r["topics_json"] or "[]"),
                        "last_stats": _json.loads(r["last_stats"]) if r["last_stats"] else None,
                    })
                print(_json.dumps(out, indent=2, ensure_ascii=False))
                return 0
            if not rows:
                console.print("[muted](no schedules)[/]")
                return 0
            now = time.time()
            for r in rows:
                state = "[ok]on[/]" if r["enabled"] else "[muted]off[/]"
                nxt = r["next_run_at"] or 0
                eta = nxt - now
                if not r["enabled"]:
                    when = "[muted]paused[/]"
                elif eta <= 0:
                    when = "[warn]due now[/]"
                else:
                    when = f"in {int(eta)}s"
                last = r["last_status"] or "(never run)"
                seeds = _json.loads(r["seeds_json"] or "[]")
                console.print(
                    f"  {state} [bold]{r['name']:<24}[/] "
                    f"[muted]every[/] {r['interval_sec']:>6}s  "
                    f"[muted]next:[/] {when:<14}  "
                    f"[muted]last:[/] [value]{_truncate(last, 60)}[/]  "
                    f"[muted]seeds:[/] {len(seeds)}"
                )
            return 0

        if args.action == "remove":
            n = storage.remove_schedule(args.name)
            print(f"removed {n} schedule(s).")
            return 0 if n else 2

        if args.action in ("enable", "disable"):
            n = storage.set_schedule_enabled(args.name, args.action == "enable")
            print(f"{args.action}d {n} schedule(s).")
            return 0 if n else 2

        if args.action == "run":
            stats = run_schedule(cfg, storage, args.name, on_event=None)
            if stats is None:
                err_console.print(f"[fail]ERROR:[/] schedule {args.name!r} did not complete")
                return 2
            console.print(
                f"[ok]●[/] {args.name}: fetched={stats.fetched} "
                f"errors={stats.errors} skipped={stats.skipped}"
            )
            return 0

        if args.action == "run-due":
            n = run_due(cfg, storage)
            console.print(f"[ok]●[/] ran {n} due schedule(s).")
            return 0

        if args.action == "loop":
            console.print(
                f"[ok]●[/] scheduler loop started "
                f"(tick={args.tick}s, Ctrl-C to stop)"
            )

            def _start(name): console.print(f"  [tag]→[/] running [bold]{name}[/]")
            def _end(name, stats):
                if stats is None:
                    err_console.print(f"  [fail]✗[/] {name}: failed")
                else:
                    console.print(
                        f"  [ok]✓[/] {name}: "
                        f"fetched={stats.fetched} errors={stats.errors}"
                    )
            loop_forever(
                cfg, storage,
                tick_seconds=args.tick,
                on_schedule_start=_start,
                on_schedule_end=_end,
            )
            return 0

        err_console.print(f"[fail]ERROR:[/] unknown schedule action {args.action!r}")
        return 2
    finally:
        storage.close()


def cmd_mirrors(cfg: Config, args: argparse.Namespace) -> int:
    storage = Storage(cfg.db_path)
    try:
        if args.rebuild:
            n = storage.simhash_backfill()
            print(f"Backfilled SimHashes for {n} page(s).")
            return 0

        if args.url:
            rows = storage.near_duplicates_of(
                args.url, distance=args.distance, limit=args.limit,
            )
            if not rows:
                print(f"(no near-duplicates of {args.url} within "
                      f"distance {args.distance}; try `mirrors --rebuild` "
                      f"if you haven't yet)")
                return 0
            print(f"Near-duplicates of {args.url} (distance ≤ {args.distance}):")
            for r in rows:
                print(f"  d={r['distance']:>2}  {r['url']}")
            return 0

        clusters = storage.mirror_clusters(
            distance=args.distance, min_size=args.min, limit=args.limit,
        )
        if not clusters:
            print(f"(no near-duplicate clusters at distance ≤ {args.distance}; "
                  f"try `mirrors --rebuild` first, or raise --distance)")
            return 0
        for c in clusters:
            print(f"== cluster ({c['size']} mirrors) "
                  f"simhash={c['simhash']:016x} max_dist={c['max_distance']} ==")
            for u in c["urls"]:
                print(f"  {u}")
            print()
        return 0
    finally:
        storage.close()


def cmd_tui(cfg: Config) -> int:
    try:
        from darkcat.tui import run_tui
    except ImportError as e:
        print(f"TUI requires the 'textual' package. Install with: pip install textual\n({e})",
              file=sys.stderr)
        return 2
    return run_tui(cfg)


def cmd_shell(cfg: Config) -> int:
    from darkcat.repl import run_shell
    return run_shell(cfg)


def cmd_gui(cfg: Config) -> int:
    try:
        from darkcat.gui import run_gui
    except ImportError as e:
        print(
            "GUI requires Tkinter (Python stdlib). On Debian/Ubuntu install "
            "`python3-tk`, on Fedora `python3-tkinter`.\n"
            f"({e})",
            file=sys.stderr,
        )
        return 2
    return run_gui(cfg)


def print_no_args_banner() -> None:
    """Friendly landing page when ``darkcat`` is run with no arguments."""
    banner(console, version=__version__)
    first_run = (
        "[muted]New here? Try this in order:[/]\n"
        "  [key]darkcat init[/]      [muted]create ~/.darkcat, probe daemons[/]\n"
        "  [key]darkcat status[/]    [muted]see which transports are reachable[/]\n"
        "  [key]darkcat -la[/]       [muted]curated entry points for every protocol[/]\n"
        "  [key]darkcat fetch <url>[/]  [muted]fetch one page through the right transport[/]\n"
        "  [key]darkcat crawl -ep <url>[/]  [muted]start a small crawl[/]\n"
        "  [key]darkcat search <q>[/]  [muted]FTS5 search what you've crawled[/]"
    )
    frontends = (
        "[key]darkcat tui[/]    [muted]Textual terminal UI[/]\n"
        "[key]darkcat shell[/]  [muted]interactive REPL (tab-completes commands)[/]\n"
        "[key]darkcat gui[/]    [muted]desktop GUI (Tkinter)[/]"
    )
    info = (
        "[key]darkcat -h[/]        [muted]full help, grouped by task[/]\n"
        "[key]darkcat <cmd> -h[/]  [muted]help for a single command[/]\n"
        "[key]darkcat about[/]     [muted]about panel (logo + version + license + source)[/]"
    )
    console.print(panel("first-time tour", first_run))
    console.print(panel("pick a frontend", frontends))
    console.print(panel("get help", info))


def _read_seed_file(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    # Soft-import argcomplete so darkcat still works when it isn't installed.
    # When present, this populates the bash/zsh/fish completion machinery via
    # the magic `_ARGCOMPLETE` env var the shell sets up; on a regular run
    # autocomplete() just returns immediately.
    try:
        import argcomplete as _argcomplete  # type: ignore[import-not-found]
        _argcomplete.autocomplete(parser)
    except ImportError:
        pass
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Run-and-exit listing shortcuts.
    if args.list_all:
        return cmd_list("all")
    if args.list is not None:
        return cmd_list(args.list)

    # Friendly empty-invocation banner.
    if args.cmd is None:
        print_no_args_banner()
        return 0

    cfg = _build_config(args)

    dispatch = {
        "init":   lambda: cmd_init(cfg, args),
        "about":  lambda: cmd_about(),
        "status": lambda: cmd_status(cfg),
        "doctor": lambda: cmd_doctor(cfg),
        "up":     lambda: cmd_up(cfg, args.protocol),
        "down":   lambda: cmd_down(cfg, args.protocol),
        "probe":  lambda: cmd_probe(cfg, args.protocol),
        "fetch":  lambda: cmd_fetch(cfg, args.url, args.show,
                                    render=args.render,
                                    render_timeout=args.render_timeout),
        "crawl":  lambda: cmd_crawl(cfg, args),
        "search": lambda: cmd_search(cfg, args.query, args.limit, strict=getattr(args, "strict", False)),
        "top":    lambda: cmd_top(cfg, args.limit, args.protocol),
        "stats":  lambda: cmd_stats(cfg),
        "seeds":  lambda: cmd_seeds(args.protocol),
        "list":     lambda: cmd_list(args.protocol),
        "scan":     lambda: cmd_scan(cfg, args),
        "findings": lambda: cmd_findings(cfg, args),
        "watch":    lambda: cmd_watch(cfg, args),
        "alerts":   lambda: cmd_alerts(cfg, args),
        "diff":     lambda: cmd_diff(cfg, args),
        "history":  lambda: cmd_history(cfg, args),
        "export":   lambda: cmd_export(cfg, args),
        "serve":    lambda: cmd_serve(cfg, args),
        "discover": lambda: cmd_discover(cfg, args),
        "feeds":    lambda: cmd_feeds(cfg, args),
        "decode-links": lambda: cmd_decode_links(cfg, args),
        "ocr":      lambda: cmd_ocr(cfg, args),
        "clusters": lambda: cmd_clusters(cfg, args),
        "mirrors":  lambda: cmd_mirrors(cfg, args),
        "cookies":  lambda: cmd_cookies(cfg, args),
        "personas": lambda: cmd_personas(cfg, args),
        "contacts": lambda: cmd_contacts(cfg, args),
        "chat":     lambda: cmd_chat(cfg, args),
        "schedule": lambda: cmd_schedule(cfg, args),
        "plugins":  lambda: cmd_plugins(cfg, args),
        "dashboard": lambda: cmd_dashboard(cfg, args),
        "liveness":  lambda: cmd_liveness(cfg, args),
        "tor":      lambda: cmd_tor(cfg, args),
        "blocklist":lambda: cmd_blocklist(cfg, args),
        "telegram": lambda: cmd_telegram(cfg, args),
        "keys":     lambda: cmd_keys(cfg, args),
        "zeronet-walk": lambda: cmd_zeronet(cfg, args),
        "tui":      lambda: cmd_tui(cfg),
        "shell":    lambda: cmd_shell(cfg),
        "gui":      lambda: cmd_gui(cfg),
    }
    handler = dispatch.get(args.cmd)
    if not handler:
        parser.error(f"unknown command: {args.cmd}")
        return 2
    return handler()


if __name__ == "__main__":
    sys.exit(main())
