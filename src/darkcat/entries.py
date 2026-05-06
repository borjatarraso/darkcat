"""Curated entry points per protocol.

For each protocol Darkcat tracks a small list of well-known starting points
with a human-readable name and one-line description. The CLI uses this both
for ``--list`` / ``--list-all`` and as the source of ``--entry-point-from-list``.

Many darknet addresses change. Verify before relying on them.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    name: str
    url: str
    description: str


ENTRY_POINTS: dict[str, list[Entry]] = {
    # ----- Anonymous overlays --------------------------------------------------
    "tor": [
        Entry("tor.taxi", "https://tor.taxi/",
              "Curated darknet directory with verified onion mirrors and uptime"),
        Entry("dark.fail", "https://dark.fail/",
              "Real-time uptime tracker for major hidden services"),
        Entry("Ahmia", "https://ahmia.fi/",
              "Open onion search engine (filtered for legality)"),
        Entry("Hidden Wiki", "https://thehiddenwiki.com/",
              "Classic Tor link directory — many entries are stale, verify"),
        Entry("onion.live", "https://onion.live/",
              "Aggregator and uptime monitor"),
        Entry("DuckDuckGo (onion)",
              "https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/",
              "DuckDuckGo's official onion service"),
        Entry("ProPublica",
              "https://p53lf57qovyuvwsc6xnrppyply3vtqm7l6pcobkmyqsiofyeznfu5uqd.onion/",
              "ProPublica investigative journalism mirror"),
        Entry("BBC News (onion)",
              "https://bbcnewsd73hkzno2ini43t4gblxvycyac5aw4gnv7t2rccijh7745uqd.onion/",
              "BBC News onion mirror"),
    ],
    "i2p": [
        Entry("notbob", "http://notbob.i2p/",
              "Best-curated I2P directory and link tracker"),
        Entry("identiguy", "http://identiguy.i2p/",
              "Long-running I2P link directory"),
        Entry("reg.i2p", "http://reg.i2p/",
              "Address registry for human-readable .i2p hostnames"),
        Entry("stats.i2p", "http://stats.i2p/",
              "I2P network statistics"),
        Entry("legwork", "http://legwork.i2p/",
              "Eepsite search engine"),
        Entry("i2p-projekt", "http://i2p-projekt.i2p/",
              "Official I2P project site (mirror inside I2P)"),
    ],
    "lokinet": [
        Entry("Oxen Foundation",
              "https://oxen.io/",
              "Lokinet's parent project — has the canonical SNApp directory"),
    ],
    "freenet": [
        Entry("Enzo's Index",
              "freenet:USK@XJZAi25dd5y7lrxE3cHMmM-xZ-c-hlPpKLYeLC0YG5I,8XTbR1bd9RBXlX6j-OZNednsJ8Cl6EAeBBebC3jtMFU,AQACAAE/index/-1/",
              "Long-running Freenet/Hyphanet link index"),
        Entry("Linkageddon",
              "freenet:USK@7H7sH5lEeFD80sigMb35GaCD03N5OCUKgi9D0iuxn7E,3SBfWf-DvMCwFmIfVx3lxYDEJpRobrcYZ4DbtUq3MbA,AQACAAE/linkageddon/-1/",
              "Alternative Freenet link aggregator"),
    ],
    "gnunet": [],
    "zeronet": [
        Entry("ZeroHello",
              "zero://1HelloAddr8MZUPYMtj9CSJj3wfGRjEHr",
              "ZeroNet's default landing zite (project largely abandoned)"),
    ],
    "yggdrasil": [
        Entry("Yggdrasil project", "https://yggdrasil-network.github.io/",
              "Project home — contains live peer list and stats"),
    ],
    "cjdns": [
        Entry("Hyperboria wiki", "https://wiki.hyperboria.net/",
              "cjdns / Hyperboria documentation hub (clearnet)"),
    ],
    "reticulum": [
        Entry("Reticulum project", "https://reticulum.network/",
              "Reticulum/LXMF project home (clearnet)"),
    ],
    "veilid": [
        Entry("Veilid", "https://veilid.com/",
              "cDc anonymous P2P framework — DHT-based, no addressable hosts"),
    ],
    "nym": [
        Entry("Nym Technologies", "https://nymtech.net/",
              "Sphinx mixnet / Loopix-based traffic-level anonymity"),
    ],

    # ----- Distributed / content-addressed web --------------------------------
    "ipfs": [
        Entry("IPFS docs", "ipns://docs.ipfs.tech",
              "Official IPFS documentation"),
        Entry("Wikipedia on IPFS", "ipns://en.wikipedia-on-ipfs.org",
              "Static Wikipedia mirror pinned on IPFS"),
        Entry("IPFS blog", "ipns://blog.ipfs.tech",
              "IPFS project blog"),
        Entry("Awesome IPFS", "ipns://awesome.ipfs.io",
              "Curated index of IPFS apps and gateways"),
        Entry("Protocol Labs", "ipns://protocol.ai",
              "Protocol Labs (IPFS authors) site"),
    ],
    "ipns": [
        Entry("IPFS docs", "ipns://docs.ipfs.tech",
              "Official IPFS documentation (IPNS-pinned)"),
        Entry("Wikipedia on IPFS", "ipns://en.wikipedia-on-ipfs.org",
              "Static Wikipedia mirror"),
    ],
    "hyper": [
        Entry("Mauve's blog", "hyper://blog.mauve.moe/",
              "Personal blog on Hypercore — one of the few live hyper:// sites"),
    ],
    "dat": [],
    "ssb": [],
    "earthstar": [],
    "cabal": [],
    "arweave": [
        Entry("Arweave docs",
              "ar://YzAJC8tFLW7oCRDnWwVPN8eKj5d4jdkJ2-kRzJmvMsk/",
              "Arweave network introduction — fetched via the public gateway"),
    ],

    # ----- Small-web / text protocols -----------------------------------------
    "gemini": [
        Entry("Gemini Project", "gemini://geminiprotocol.net/",
              "Official Gemini protocol site"),
        Entry("Geminispace.info", "gemini://geminispace.info/",
              "Statistics and search for Geminispace"),
        Entry("Kennedy", "gemini://kennedy.gemi.dev/",
              "Full-text search engine for Gemini"),
        Entry("Antenna", "gemini://warmedal.se/~antenna/",
              "Gemini blog/post aggregator"),
        Entry("Medusae", "gemini://medusae.space/",
              "Curated Gemini directory"),
        Entry("CAPCOM", "gemini://gemini.circumlunar.space/capcom/",
              "Capsule of capsules — Gemini ring directory"),
        Entry("Station", "gemini://station.martinrue.com/",
              "Gemini-based microblogging platform"),
    ],
    "spartan": [
        Entry("mozz.us", "spartan://mozz.us/",
              "Reference Spartan capsule (protocol author)"),
        Entry("0x47.io", "spartan://0x47.io/",
              "Active Spartan host"),
    ],
    "nex": [
        Entry("Nightfall City", "nex://nightfall.city/",
              "Reference NEX server with the protocol spec and a directory"),
    ],
    "gopher": [
        Entry("Floodgap", "gopher://gopher.floodgap.com/",
              "The classic Gopher hub — Veronica-2 search included"),
        Entry("SDF", "gopher://sdf.org/",
              "SDF Public Access Unix's Gopher hole"),
        Entry("gopher.club", "gopher://gopher.club/",
              "User-driven Gopher community"),
        Entry("Quux", "gopher://gopher.quux.org/",
              "Long-running Gopher server"),
        Entry("Bongusta", "gopher://i-logout.cz/1/bongusta/",
              "Aggregator of Gopher 'phlogs' (gopher blogs)"),
    ],
    "gophers": [
        Entry("Floodgap (TLS)", "gophers://gopher.floodgap.com/",
              "Floodgap with TLS"),
    ],
    "finger": [
        Entry("HappyNetBox", "finger://happynetbox.com/",
              "Public Finger host with user feeds"),
        Entry("graph.no", "finger://graph.no/",
              "Live ASCII graphs returned over Finger (weather, etc.)"),
    ],
    "nntp": [
        Entry("Eternal-September", "news://news.eternal-september.org/",
              "Free public NNTP server with most Big-8 hierarchies"),
        Entry("NetFront", "news://freenews.netfront.net/",
              "Free public Usenet server"),
        Entry("Gmane", "news://news.gmane.io/",
              "Mailing-list-to-Usenet gateway"),
    ],
    "webfinger": [
        Entry("Mastodon (Eugen Rochko)", "acct:Gargron@mastodon.social",
              "Webfinger for the Mastodon founder's account"),
    ],

    # ----- Alt-naming systems --------------------------------------------------
    "namecoin": [
        Entry("nx.bit", "http://nx.bit/",
              "Namecoin namespace explorer (requires .bit DNS configured)"),
    ],
    "emercoin": [
        Entry("emercoin.lib", "http://emercoin.lib/",
              "EmerCoin NVS demo (requires emcDNS configured)"),
    ],
    "ens": [
        Entry("vitalik.eth", "https://vitalik.eth/",
              "Vitalik Buterin's ENS domain"),
        Entry("brantly.eth", "https://brantly.eth/",
              "Brantly Millegan's ENS demo"),
        Entry("nick.eth", "https://nick.eth/",
              "ENS lead developer's domain"),
    ],
    "handshake": [
        Entry("welcome", "http://welcome.nb/",
              "Handshake welcome page"),
        Entry("proofofconcept", "http://proofofconcept/",
              "Handshake proof-of-concept page"),
    ],
    "unstoppable": [
        Entry("brad.crypto", "http://brad.crypto/",
              "Brad Kam (Unstoppable Domains co-founder)"),
    ],
    "solana": [
        Entry("bonfida.sol", "https://bonfida.sol/",
              "Bonfida — SNS founders' domain"),
    ],
    "opennic": [
        Entry("opennic.geek", "http://opennic.geek/",
              "OpenNIC's main info page"),
        Entry("wiki.opennic.geek", "http://wiki.opennic.geek/",
              "OpenNIC wiki"),
        Entry("grep.geek", "http://grep.geek/",
              "OpenNIC search engine"),
        Entry("search.fur", "http://search.fur/",
              "OpenNIC fur-TLD search"),
    ],

    # ----- Messaging / F2F (no usable HTTP entry points) ----------------------
    "briar": [],
    "tox": [],
    "retroshare": [],
    "bitchat": [
        Entry("bitchat project", "https://bitchat.free/",
              "Bluetooth-LE proximity mesh chat — peers within radio range only"),
    ],
    "simplex": [
        Entry("SimpleX Chat", "https://simplex.chat/",
              "SimpleX SMP — queue-based messaging with no user identifiers"),
    ],
    "session": [
        Entry("Session", "https://getsession.org/",
              "Oxen-routed anonymous messenger — no phone, no email"),
    ],
    "berty": [
        Entry("Berty", "https://berty.tech/",
              "Offline-first P2P chat over BLE / Wi-Fi-Direct / Tor"),
    ],
    "jami": [
        Entry("Jami (GNU)", "https://jami.net/",
              "Distributed SIP/chat — no central server, no account ID lookup"),
    ],
    "nostr": [
        Entry("Nostr protocol", "https://nostr.com/",
              "Notes & Other Stuff Transmitted by Relays — censorship-resistant social"),
        Entry("nostr.band", "https://nostr.band/",
              "Cross-relay search and discovery for the Nostr network"),
    ],

    # ----- File-sharing identifiers (illustrative) ----------------------------
    "magnet": [
        Entry("Arch Linux ISO",
              "magnet:?xt=urn:btih:88594aaacbde40ef3e2510c47374ec0aa396c08e&dn=archlinux-2024.04.01-x86_64.iso",
              "Arch Linux 2024.04 install media"),
    ],
    "ed2k": [],
}


def for_protocol(protocol: str) -> list[Entry]:
    return ENTRY_POINTS.get(protocol, [])


def all_protocols_with_entries() -> list[str]:
    return [p for p, entries in ENTRY_POINTS.items() if entries]


def render_protocol(protocol: str) -> str:
    """Pretty-print the entry list for one protocol (ANSI-free, terminal-safe)."""
    entries = for_protocol(protocol)
    if not entries:
        return f"# {protocol}\n  (no curated entry points)\n"
    lines = [f"# {protocol}"]
    for i, e in enumerate(entries, 1):
        lines.append(f"  [{i:>2}] {e.name}")
        lines.append(f"        {e.url}")
        lines.append(f"        {e.description}")
    return "\n".join(lines) + "\n"


def render_all() -> str:
    return "\n".join(render_protocol(p) for p in ENTRY_POINTS.keys())
