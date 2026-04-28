# Darkcat

**Maintainer:** Overdrive (Borja Tarraso) &lt;borja.tarraso@member.fsf.org&gt;
**License:** GPL-3.0-or-later

A command-line crawler for darknets and obscure overlay networks. It
classifies every URL by protocol, routes it through the right transport,
crawls BFS from seed lists with topic-keyword scoring, and stores everything
in SQLite (FTS5). Ships with both a CLI (`darkcat …`) and a Textual TUI
(`darkcat tui`).

Run `darkcat --about` for a one-line summary, `darkcat -h` for the full
reference, or `darkcat -la` to discover curated entry points across every
supported protocol.

> Use this for security research, journalism, OSINT, accessing
> censorship-resistant content, or interop testing. You are responsible
> for what you fetch and where you point it. Don't use it to break laws.

## Supported protocols

| Family | URL form | Transport / requirement |
| --- | --- | --- |
| **Tor** onion services | `*.onion` (v2 16ch / v3 56ch) | Local Tor SOCKS5, default `127.0.0.1:9050` |
| **I2P** eepsites | `*.i2p`, `*.b32.i2p` | Local I2P HTTP proxy, default `127.0.0.1:4444` |
| **IPFS / IPNS** | `ipfs://CID`, `ipns://name`, `*/ipfs/CID` | Local IPFS gateway `127.0.0.1:8080` (Kubo), optional public fallback |
| **Hyphanet / Freenet** | `freenet:CHK@…`, `USK@…`, `SSK@…`, `KSK@…` | Local FProxy `127.0.0.1:8888` |
| **Lokinet (Oxen)** | `*.loki` | System routing — the lokinet TUN |
| **GNUnet / GNS** | `*.gnu`, `*.zkey` | System GNS resolver |
| **ZeroNet** | `zero://<address>` | Local ZeroNet UI `127.0.0.1:43110` |
| **Gemini** (small web) | `gemini://host[:1965]/path` | Native TLS+TOFU client (no daemon needed) |
| **Gopher** | `gopher://host[:70]/<sel>` | Native socket client (no daemon needed) |
| **Hyper / Hypercore** | `hyper://<key>/path` | `hyper.fyi` gateway (best-effort; ideally local Beaker / hyperdrive node) |
| **Yggdrasil** mesh | IPv6 in `200::/7` | System TUN (yggdrasil daemon) |
| **cjdns / Hyperboria** | IPv6 in `fc00::/8` | System TUN (cjdroute) |
| **Namecoin** | `*.bit` | `ncdns` running, or OpenNIC DNS that mirrors `.bit` |
| **ENS** | `*.eth` | `eth.limo` gateway fallback (or local ENS resolver) |
| **Handshake (HNS)** | `*.hns`, `.c`, `.p`, `.forever`, `.welcome`, `.decentralized` | `hsd`/`hnsd` running, else `hns.is` gateway |
| **OpenNIC** peering TLDs | `.geek` `.free` `.indy` `.pirate` `.libre` `.neo` `.bbs` `.o` `.oss` `.oz` `.parody` `.dyn` `.epic` `.fur` `.null` `.chan` `.micro` | OpenNIC DNS server in `/etc/resolv.conf` |
| **Clearnet** (any other URL) | `https://…` | Tunneled through Tor when Tor is up; direct otherwise |

`darkcat status` reports which transports are reachable on this machine.

## Install

```sh
cd tor-search
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

Or, without installing:

```sh
pip install -r requirements.txt
python -m darkcat status
```

## Daemons (Linux examples)

```sh
# Tor
sudo dnf install tor          # or: apt install tor
sudo systemctl start tor

# I2P (i2pd — lightweight C++ router)
sudo dnf install i2pd
sudo systemctl start i2pd

# IPFS (Kubo)
# https://docs.ipfs.tech/install/
ipfs init && ipfs daemon &

# OpenNIC DNS (also resolves .bit, .geek, .free, …)
# Pick from https://servers.opennic.org and add to /etc/resolv.conf

# Hyphanet (Freenet) — Java installer at https://www.hyphanet.org
# Lokinet — https://lokinet.org
# Yggdrasil — https://yggdrasil-network.github.io
# cjdns — https://github.com/cjdelisle/cjdns
# Handshake (hsd or hnsd) — https://hsd-dev.org / https://github.com/handshake-org/hnsd
# ZeroNet — https://github.com/ZeroNetX/ZeroNet (largely abandoned)
```

Gemini and Gopher need no daemon — Darkcat speaks them natively over a socket.

## Usage

`darkcat -h` shows a clean help screen with the full protocol table, every
subcommand, and example invocations. Highlights:

```sh
darkcat status                       # which daemons are reachable
darkcat seeds all                    # built-in seed list

# Fetch one URL through the right transport.
darkcat fetch gemini://geminiprotocol.net/ --show
darkcat fetch http://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/ --show
darkcat fetch ipns://docs.ipfs.tech --show

# Crawl Tor seeds for whistleblower content, 200 pages, 3 hops deep.
darkcat crawl \
    --protocol tor \
    --topics whistleblower leak securedrop \
    --max-pages 200 --max-depth 3 \
    --threshold 0.5

# Crawl Gemini space (no daemon required).
darkcat crawl --protocol gemini --topics privacy --max-depth 3

# Stay inside one network — don't follow cross-protocol links.
darkcat crawl --protocol i2p --no-cross-protocol --max-pages 50

# Custom seeds.
darkcat crawl --seed-file my_seeds.txt --topics journalism censorship

# Query the local DB.
darkcat search "secure drop"
darkcat top --limit 30 --protocol tor
darkcat stats
```

## TUI

```sh
darkcat tui
```

Opens a Textual app:

- A status bar with green/red dots for every protocol's reachability.
- A form for topics, protocol selector, max-pages/depth/threshold.
- Live RichLog of every fetched/skipped/errored URL during a crawl.
- Sortable results table backed by the SQLite store.
- An FTS5 search box and a single-URL fetch box.

Key bindings: `q` quit · `Ctrl+R` refresh status · `Ctrl+C` stop crawl ·
`F5` refresh results table.

## How crawling works

1. Seed URLs are normalized and classified by protocol
   (`darkcat/protocols.py`). The classifier recognizes URL schemes
   (`gemini://`, `ipfs://`, `freenet:`, …), TLDs (`*.onion`, `*.i2p`,
   `*.eth`, `*.bit`, OpenNIC TLDs, …), and IPv6 ranges (Yggdrasil's
   `200::/7`, cjdns's `fc00::/8`).
2. Each URL is dispatched to its transport (`darkcat/transports.py`):
   - HTTP-based (Tor SOCKS5h, I2P HTTP proxy, IPFS/Freenet/ZeroNet
     gateways) is built on `requests`.
   - **Gemini** uses a native TLS+TOFU socket client on port 1965.
   - **Gopher** uses a native socket client on port 70 with menu parsing.
   - System-routed transports (Lokinet, GNUnet, Yggdrasil, cjdns,
     Namecoin, OpenNIC, Handshake) just `requests.get` and rely on the
     daemon's TUN/DNS.
   - **ENS / Handshake / Hyper** fall back to public gateways
     (`eth.limo`, `hns.is`, `hyper.fyi`) when no local resolver works.
3. Pages are parsed (`darkcat/extractor.py`): HTML → BeautifulSoup;
   Gemini → gemtext (`=> URL [label]`); Gopher → menu lines
   (`<type>display\tselector\thost\tport`).
4. Topic scorer (`darkcat/topic_filter.py`) gives each page a score:
   `(body_hits + 5×title_hits + phrase_hits) / log(body_tokens + 10)`.
5. BFS frontier expands links, gated by max-depth, max-pages, per-host cap,
   score threshold, and cross-protocol/clearnet rules
   (`darkcat/crawler.py`).
6. Results land in SQLite + FTS5 (`darkcat/storage.py`).

## Privacy notes

- Tor SOCKS uses `socks5h://` so DNS is resolved by the exit / hidden
  service, not your machine.
- User-agent mimics Tor Browser by default to reduce fingerprinting.
- Clearnet links found inside darknet pages are tunneled through Tor too
  whenever Tor is reachable.
- Gemini's TOFU model means we don't validate against the public CA store
  (matches reference clients). Cert pinning isn't implemented yet.
- `--public-ipfs` is off by default because public gateways leak the
  request to a third party.
- `--follow-clearnet` is off by default — you opt in to leaving the darknet.
- ENS / Handshake gateway fallbacks (`eth.limo`, `hns.is`) similarly leak
  the request; a local resolver avoids that.

## Layout

```
darkcat/
  cli.py            argparse entry point with rich --help
  tui.py            Textual UI (status bar, crawl form, log, results table)
  config.py         defaults, ports, paths, gateway hosts
  protocols.py      URL → Protocol classifier (18 protocols)
  transports.py     per-protocol fetchers
  fetcher.py        protocol → transport dispatch
  extractor.py      HTML / Gemini / Gopher → title/text/links
  topic_filter.py   keyword + phrase scoring
  crawler.py        BFS crawler with stop-event and event callbacks
  storage.py        SQLite + FTS5 (pages, links, full-text)
  seeds.py          default seed lists per protocol
```

## Limitations

- Onion / I2P / IPFS / Freenet addresses churn fast. Built-in seeds use
  long-lived clearnet directories (tor.taxi, dark.fail, ahmia, notbob.i2p,
  …) so you discover current addresses rather than stale ones.
- No JavaScript execution — sites that need JS will look empty.
- Hyper:// rarely works without a local hyperdrive node; the gateway is
  best-effort.
- For Lokinet, GNUnet, Yggdrasil, and cjdns we can't probe daemon state
  without root, so `status` shows them as reachable and a fetch failure
  is reported as `unavailable: <reason>`.
