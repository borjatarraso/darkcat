"""darkcat CLI — multi-protocol darknet/overlay crawler."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from darkcat import __author__, __email__, __license__, __version__
from darkcat.config import Config
from darkcat.crawler import Crawler, CrawlPolicy
from darkcat.entries import ENTRY_POINTS, render_all, render_protocol
from darkcat.fetcher import Fetcher
from darkcat.protocols import Protocol, classify, normalize
from darkcat.seeds import SEEDS_BY_PROTOCOL, all_seeds
from darkcat.storage import Storage
from darkcat.topic_filter import TopicFilter


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

COMMAND_TABLE = [
    ("status",  "Show which protocol daemons are reachable."),
    ("fetch",   "Fetch a single URL through the right transport."),
    ("crawl",   "BFS-crawl from seeds with optional topic scoring."),
    ("search",  "FTS5 search of previously crawled pages."),
    ("top",     "Show highest-scoring crawled pages."),
    ("stats",   "Database statistics."),
    ("seeds",   "Print built-in seed URLs (one protocol or 'all')."),
    ("list",    "Print curated entry points with descriptions."),
    ("tui",     "Launch the Textual TUI."),
]


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
    cmd_lines = ["", "Commands:", ""]
    for name, desc in COMMAND_TABLE:
        cmd_lines.append(f"  {name:<10} {desc}")
    examples = [
        "",
        "Examples:",
        "",
        "  darkcat -l tor                              # curated tor entry points",
        "  darkcat -la                                 # curated entries for every protocol",
        "  darkcat status",
        "  darkcat fetch gemini://geminiprotocol.net/ --show",
        "  darkcat crawl -ep https://tor.taxi/ -t whistleblower",
        "  darkcat crawl -p tor   -epfl 1              # tor entry #1",
        "  darkcat crawl -p gemini -epfl a -d 3        # all gemini entries, depth 3",
        "  darkcat crawl -p tor -t whistleblower leak -n 200",
        "  darkcat search 'secure drop'",
        "  darkcat tui",
        "",
        "Run `darkcat --about` for maintainer / license info.",
    ]
    return "\n".join(proto_lines + cmd_lines + examples)


def _build_about_text() -> str:
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


# ---------------------------------------------------------------------------
# Custom argparse actions
# ---------------------------------------------------------------------------

class _AboutAction(argparse.Action):
    def __init__(self, option_strings, dest=argparse.SUPPRESS, **kw):
        super().__init__(option_strings, dest=dest, default=argparse.SUPPRESS, nargs=0, **kw)

    def __call__(self, parser, namespace, values, option_string=None):
        print(_build_about_text())
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
    g.add_argument("--i2p-port", type=int, default=4444, help="I2P HTTP proxy port (default 4444)")
    g.add_argument("--ipfs-port", type=int, default=8080, help="IPFS gateway port (default 8080)")
    g.add_argument("--public-ipfs", action="store_true",
                   help="Allow public IPFS gateway fallback (leaks request to a third party)")

    output = p.add_argument_group("output")
    output.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    output.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress per-page progress during crawl (only print the summary)")

    sub = p.add_subparsers(dest="cmd", required=False, metavar="COMMAND")

    sub.add_parser("status", help="Show which protocol daemons are reachable.")

    pf = sub.add_parser("fetch", help="Fetch a single URL through the right transport.")
    pf.add_argument("url")
    pf.add_argument("--show", action="store_true", help="Print decoded page text and links")

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

    ps = sub.add_parser("search", help="FTS5 search of previously crawled pages.")
    ps.add_argument("query")
    ps.add_argument("-n", "--limit", type=int, default=20, metavar="N", help="Max results (default 20)")

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

    sub.add_parser("tui", help="Launch the Textual TUI.")

    return p


def _build_config(args: argparse.Namespace) -> Config:
    cfg = Config()
    if args.db:
        cfg.db_path = args.db
    cfg.tor_socks_port = args.tor_port
    cfg.i2p_http_port = args.i2p_port
    cfg.ipfs_gateway_port = args.ipfs_port
    cfg.use_public_ipfs_gateway = args.public_ipfs
    return cfg


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(protocol: str) -> int:
    if protocol == "all":
        sys.stdout.write(render_all())
    elif protocol in ENTRY_POINTS:
        sys.stdout.write(render_protocol(protocol))
    else:
        print(f"Unknown protocol: {protocol}", file=sys.stderr)
        print(f"Known: {', '.join(ENTRY_POINTS.keys())}", file=sys.stderr)
        return 2
    return 0


def cmd_status(cfg: Config) -> int:
    fetcher = Fetcher(cfg)
    print("Daemon reachability:")
    for proto, ok in fetcher.status().items():
        mark = "OK  " if ok else "DOWN"
        print(f"  [{mark}] {proto.value:<10} {_proto_endpoint(cfg, proto)}")
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
        Protocol.MAGNET: "(URI parser — outputs decoded fields)",
        Protocol.ED2K: "(URI parser — outputs decoded fields)",
        Protocol.CLEARNET: "(via Tor SOCKS if available)",
    }
    return mapping.get(proto, "")


def cmd_fetch(cfg: Config, url: str, show: bool) -> int:
    fetcher = Fetcher(cfg)
    proto = fetcher.protocol_for(url)
    print(f"Protocol: {proto.value}")
    try:
        result = fetcher.fetch(url)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if result is None:
        print("ERROR: no result", file=sys.stderr)
        return 2
    print(f"Status: {result.status}  final={result.final_url}  "
          f"bytes={len(result.body)}  ct={result.content_type}")
    if show:
        from darkcat.extractor import parse as parse_page
        page = parse_page(result.final_url, result.body, result.content_type)
        if page.title:
            print(f"Title: {page.title}")
        print()
        print(page.text[:8000])
        if page.links:
            print()
            print(f"Links ({len(page.links)}):")
            for ln in page.links[:50]:
                print(f"  {ln}")
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
    )
    crawler = Crawler(cfg, storage, tf, policy)

    where = (
        f"entry-point ({proto_hint})" if args.entry_point
        else f"entry-list {args.entry_point_from_list} ({proto_hint})" if args.entry_point_from_list
        else f"protocol={args.protocol}"
    )
    print(f"Crawling {len(seeds)} seed(s) [{where}]; topics={args.topics or '(none)'}; "
          f"max_pages={policy.max_pages}, max_depth={policy.max_depth}")

    quiet = getattr(args, "quiet", False)

    def on_event(kind: str, payload: dict) -> None:
        if quiet:
            return
        if kind == "fetch":
            print(f"  [{payload['protocol']:<10}] score={payload['score']:.2f} "
                  f"d={payload.get('depth', 0)} {payload.get('title') or '(no title)'} "
                  f"-- {payload['url']}")
        elif kind == "error":
            print(f"  ERROR [{payload.get('protocol', '?')}] {payload['url']}: "
                  f"{payload.get('error', '')[:160]}", file=sys.stderr)

    try:
        stats = crawler.crawl(seeds, on_event=on_event)
    finally:
        storage.close()
    print()
    print(f"Done. fetched={stats.fetched}  errors={stats.errors}  skipped={stats.skipped}")
    for proto, n in stats.by_protocol.items():
        print(f"  {proto:<10} {n}")
    return 0


def cmd_search(cfg: Config, query: str, limit: int) -> int:
    storage = Storage(cfg.db_path)
    try:
        rows = storage.search(query, limit=limit)
    finally:
        storage.close()
    if not rows:
        print("No matches.")
        return 0
    for r in rows:
        print(f"[{r['protocol']:<9} score={r['score']:.2f}] {r['title'] or '(no title)'}")
        print(f"  {r['url']}")
        print(f"  …{r['snippet']}…")
        print()
    return 0


def cmd_top(cfg: Config, limit: int, protocol: Optional[str]) -> int:
    storage = Storage(cfg.db_path)
    try:
        rows = storage.top(limit=limit, protocol=protocol)
    finally:
        storage.close()
    for r in rows:
        print(f"[{r['protocol']:<9} score={r['score']:.2f}] {r['title'] or '(no title)'}")
        print(f"  {r['url']}")
    return 0


def cmd_stats(cfg: Config) -> int:
    storage = Storage(cfg.db_path)
    try:
        s = storage.stats()
    finally:
        storage.close()
    print(f"DB: {cfg.db_path}")
    print(f"Total pages: {s['total_pages']}")
    print(f"Total links: {s['links']}")
    for proto, n in s["by_protocol"].items():
        print(f"  {proto:<10} {n}")
    return 0


def cmd_seeds(protocol: str) -> int:
    if protocol == "all":
        for proto, urls in SEEDS_BY_PROTOCOL.items():
            print(f"# {proto}")
            for u in urls:
                print(u)
            print()
    else:
        for u in SEEDS_BY_PROTOCOL.get(protocol, []):
            print(u)
    return 0


def cmd_tui(cfg: Config) -> int:
    try:
        from darkcat.tui import run_tui
    except ImportError as e:
        print(f"TUI requires the 'textual' package. Install with: pip install textual\n({e})",
              file=sys.stderr)
        return 2
    return run_tui(cfg)


def _no_args_banner() -> str:
    return "\n".join([
        f"Darkcat {__version__} — multi-protocol darknet & overlay crawler.",
        "",
        "Try one of:",
        "  darkcat -h            full help with the protocol table",
        "  darkcat --about       maintainer, license, version",
        "  darkcat -la           curated entry points for every protocol",
        "  darkcat status        check which transports are reachable",
        "  darkcat tui           launch the interactive Textual TUI",
        "",
    ])


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
        sys.stdout.write(_no_args_banner())
        return 0

    cfg = _build_config(args)

    dispatch = {
        "status": lambda: cmd_status(cfg),
        "fetch":  lambda: cmd_fetch(cfg, args.url, args.show),
        "crawl":  lambda: cmd_crawl(cfg, args),
        "search": lambda: cmd_search(cfg, args.query, args.limit),
        "top":    lambda: cmd_top(cfg, args.limit, args.protocol),
        "stats":  lambda: cmd_stats(cfg),
        "seeds":  lambda: cmd_seeds(args.protocol),
        "list":   lambda: cmd_list(args.protocol),
        "tui":    lambda: cmd_tui(cfg),
    }
    handler = dispatch.get(args.cmd)
    if not handler:
        parser.error(f"unknown command: {args.cmd}")
        return 2
    return handler()


if __name__ == "__main__":
    sys.exit(main())
