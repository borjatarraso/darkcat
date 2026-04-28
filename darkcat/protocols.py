"""Classify URLs into transport categories.

Recognized darknet / overlay / underground / obscure protocols (38 total):

  Anonymous overlays
    - Tor onion services      *.onion (v2 16ch / v3 56ch)
    - I2P eepsites            *.i2p, *.b32.i2p
    - Lokinet (Oxen)          *.loki
    - Hyphanet / Freenet      freenet:CHK@…, USK@…, SSK@…, KSK@…
    - GNUnet GNS              *.gnu, *.zkey
    - ZeroNet                 zero://<addr>
    - Yggdrasil mesh          IPv6 in 200::/7
    - cjdns / Hyperboria      IPv6 in fc00::/8
    - Reticulum / LXMF        lxmf://, reticulum://

  Distributed / content-addressed web
    - IPFS / IPNS             ipfs://CID, ipns://name, /ipfs/, /ipns/
    - Hyper / Hypercore       hyper://<key>
    - DAT (Beaker, deprecated) dat://<key>
    - Secure Scuttlebutt      ssb://%feed%.ed25519
    - Earthstar               earthstar://<share>
    - Cabal                   cabal://<key>

  Small-web / text protocols
    - Gemini (TLS+TOFU 1965)  gemini://host[:1965]/path
    - Spartan (300)           spartan://host[:300]/path
    - NEX (1900)              nex://host[:1900]/path
    - Gopher (70)             gopher://host[:70]/<type><selector>
    - Gophers (TLS Gopher)    gophers://host[:70]/<type><selector>
    - Finger (79)             finger://user@host
    - NNTP / Usenet (119)     news://server/group, nntp://server/group/article
    - WebFinger               acct:user@host

  Alt-naming systems (use system DNS / dedicated resolver / public gateway)
    - Namecoin                *.bit
    - EmerCoin NVS            *.emc, *.lib, *.bazar, *.coin
    - ENS                     *.eth
    - Handshake (HNS)         *.hns + .c .p .forever .welcome .decentralized
    - Unstoppable Domains     *.crypto, *.nft, *.x, *.wallet, *.bitcoin, *.dao,
                              *.888, *.zil, *.blockchain, *.polygon, *.klever,
                              *.hi, *.anime, *.manga
    - Solana SNS              *.sol
    - OpenNIC                 .geek .free .indy .pirate .libre .neo .bbs .o
                              .oss .oz .parody .dyn .epic .fur .null .chan .micro

  Messaging / F2F
    - Briar                   briar://
    - Tox                     tox://<id>
    - Retroshare              retroshare://

  File-sharing identifiers (parsed, not crawled)
    - Magnet (BitTorrent)     magnet:?xt=urn:btih:HASH&dn=…
    - eDonkey/eD2k            ed2k://|file|name|size|hash|/

  Fallback
    - Clearnet                anything else, tunneled via Tor when up
"""
from __future__ import annotations

import ipaddress
import re
from enum import Enum
from urllib.parse import urlparse


class Protocol(str, Enum):
    # Anonymous overlays
    TOR = "tor"
    I2P = "i2p"
    LOKINET = "lokinet"
    FREENET = "freenet"
    GNUNET = "gnunet"
    ZERONET = "zeronet"
    YGGDRASIL = "yggdrasil"
    CJDNS = "cjdns"
    RETICULUM = "reticulum"

    # Distributed web
    IPFS = "ipfs"
    IPNS = "ipns"
    HYPER = "hyper"
    DAT = "dat"
    SSB = "ssb"
    EARTHSTAR = "earthstar"
    CABAL = "cabal"

    # Small-web / text
    GEMINI = "gemini"
    SPARTAN = "spartan"
    NEX = "nex"
    GOPHER = "gopher"
    GOPHERS = "gophers"
    FINGER = "finger"
    NNTP = "nntp"
    WEBFINGER = "webfinger"

    # Alt-naming
    NAMECOIN = "namecoin"
    EMERCOIN = "emercoin"
    ENS = "ens"
    HANDSHAKE = "handshake"
    UNSTOPPABLE = "unstoppable"
    SOLANA = "solana"
    OPENNIC = "opennic"

    # Messaging / F2F
    BRIAR = "briar"
    TOX = "tox"
    RETROSHARE = "retroshare"

    # File-sharing identifiers
    MAGNET = "magnet"
    ED2K = "ed2k"

    # Fallback
    CLEARNET = "clearnet"
    UNKNOWN = "unknown"


_ONION_RE = re.compile(r"(^|\.)([a-z2-7]{16}|[a-z2-7]{56})\.onion$", re.IGNORECASE)

_OPENNIC_TLDS = {
    "geek", "free", "indy", "pirate", "libre", "neo",
    "bbs", "o", "oss", "oz", "parody", "dyn", "epic",
    "fur", "null", "chan", "micro",
}

_HANDSHAKE_TLDS = {"hns", "c", "p", "forever", "welcome", "decentralized"}

_EMERCOIN_TLDS = {"emc", "lib", "bazar", "coin"}

_UNSTOPPABLE_TLDS = {
    "crypto", "nft", "x", "wallet", "bitcoin", "dao",
    "888", "zil", "blockchain", "polygon", "klever",
    "hi", "anime", "manga", "kresus", "binanceus",
}

_YGG_NET = ipaddress.ip_network("200::/7")
_CJDNS_NET = ipaddress.ip_network("fc00::/8")

# Schemes that map directly to a Protocol (no host/TLD inspection needed).
_SCHEME_TO_PROTOCOL: dict[str, Protocol] = {
    "ipfs": Protocol.IPFS,
    "ipns": Protocol.IPNS,
    "freenet": Protocol.FREENET,
    "hyphanet": Protocol.FREENET,
    "zero": Protocol.ZERONET,
    "gemini": Protocol.GEMINI,
    "spartan": Protocol.SPARTAN,
    "nex": Protocol.NEX,
    "gopher": Protocol.GOPHER,
    "gophers": Protocol.GOPHERS,
    "finger": Protocol.FINGER,
    "news": Protocol.NNTP,
    "nntp": Protocol.NNTP,
    "snews": Protocol.NNTP,
    "nntps": Protocol.NNTP,
    "hyper": Protocol.HYPER,
    "dat": Protocol.DAT,
    "ssb": Protocol.SSB,
    "earthstar": Protocol.EARTHSTAR,
    "cabal": Protocol.CABAL,
    "briar": Protocol.BRIAR,
    "tox": Protocol.TOX,
    "retroshare": Protocol.RETROSHARE,
    "lxmf": Protocol.RETICULUM,
    "reticulum": Protocol.RETICULUM,
    "magnet": Protocol.MAGNET,
    "ed2k": Protocol.ED2K,
    "acct": Protocol.WEBFINGER,
}


def _ipv6_in(host: str, network: ipaddress.IPv6Network) -> bool:
    try:
        addr = ipaddress.IPv6Address(host)
    except (ipaddress.AddressValueError, ValueError):
        return False
    return addr in network


def classify(url: str) -> Protocol:
    if not url:
        return Protocol.UNKNOWN
    lowered = url.strip().lower()

    # Scheme-based protocols (URI-shaped)
    scheme = lowered.split(":", 1)[0] if ":" in lowered else ""
    if scheme in _SCHEME_TO_PROTOCOL:
        return _SCHEME_TO_PROTOCOL[scheme]

    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = (parsed.hostname or "").lower()
    if not host:
        return Protocol.UNKNOWN

    # TLD-based detection
    if _ONION_RE.search(host) or host.endswith(".onion"):
        return Protocol.TOR
    if host.endswith(".i2p"):
        return Protocol.I2P
    if host.endswith(".loki"):
        return Protocol.LOKINET
    if host.endswith(".gnu") or host.endswith(".zkey"):
        return Protocol.GNUNET
    if host.endswith(".bit"):
        return Protocol.NAMECOIN
    if host.endswith(".eth"):
        return Protocol.ENS
    if host.endswith(".sol"):
        return Protocol.SOLANA

    tld = host.rsplit(".", 1)[-1]
    if tld in _OPENNIC_TLDS:
        return Protocol.OPENNIC
    if tld in _EMERCOIN_TLDS:
        return Protocol.EMERCOIN
    if tld in _UNSTOPPABLE_TLDS:
        return Protocol.UNSTOPPABLE
    if tld in _HANDSHAKE_TLDS:
        return Protocol.HANDSHAKE

    # IPv6-overlay detection
    if _ipv6_in(host, _YGG_NET):
        return Protocol.YGGDRASIL
    if _ipv6_in(host, _CJDNS_NET):
        return Protocol.CJDNS

    # Path-based IPFS detection (clearnet gateway URLs)
    if "/ipfs/" in parsed.path:
        return Protocol.IPFS
    if "/ipns/" in parsed.path:
        return Protocol.IPNS

    return Protocol.CLEARNET


def normalize(url: str) -> str:
    if "://" in url or url.startswith(("magnet:", "acct:", "freenet:", "hyphanet:")):
        return url
    return f"http://{url}"
