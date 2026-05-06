# Darkcat quickstart — from zero to first crawl

This is a **start-from-scratch** walk-through for someone who has just
installed darkcat and never used a darknet crawler before. By the end you
will have:

* installed darkcat and verified the daemons it depends on,
* run your first crawl over the Tor network and searched the result,
* extracted contact IDs from the crawled pages,
* created a burner persona and pointed darkcat at a logged-in URL,
* logged into a chat backend (Telegram or XMPP) and ingested messages.

If you already know what `.onion` is and just want the cheat-sheet, jump
to **§9 — Cheat-sheet**.

---

## 1. What darkcat is, in one paragraph

Darkcat is a **command-line crawler** that speaks ~30 darkweb / overlay /
small-web protocols (Tor, I2P, Freenet, Lokinet, IPFS, Gemini, Gopher,
Hyper, Yggdrasil, ENS, Handshake, …) plus eight chat networks (Telegram,
Matrix, XMPP, SimpleX, Session, Tox, Briar, Ricochet) and a credential /
leak scanner over everything it stores. Output goes into a single SQLite
file under `~/.darkcat/crawl.db` so you can search, diff, alert, and
export later.

The mental model:

```
   you  →  darkcat  →  the right transport for each URL  →  external daemons
                                                            (tor, i2p, ipfs …)
                                                                  ↓
                                                            ~/.darkcat/crawl.db
                                                            (pages, findings,
                                                             alerts, history)
```

Darkcat does **not** ship a Tor daemon, an I2P router, an IPFS node, etc.
It expects them on the loopback interface — and tells you which ones are
up.

---

## 2. Install

### Python package

```bash
pip install darkcat
# or, from a checkout:
pip install -e .
```

Python ≥ 3.9 is required. The base install pulls only `requests`,
`PySocks`, `beautifulsoup4`, `lxml`, `rich`, `textual` — under 30 MB.

### Optional extras

Install only what you need:

| Extra            | What it adds                                       |
|------------------|----------------------------------------------------|
| `[render]`       | Headless Chromium via Playwright, for JS-heavy sites |
| `[crypto]`       | Strict EIP-55 Ethereum address validation         |
| `[chat-telegram]`| Telethon, real Telegram user-account login        |
| `[chat-matrix]`  | matrix-nio (federated Matrix client)              |
| `[chat-xmpp]`    | slixmpp (Jabber/XMPP)                             |
| `[chat-simplex]` | websocket-client driver for `simplex-chat` daemon |
| `[chat]`         | All four chat backends in one go                  |
| `[all]`          | Everything                                         |

```bash
pip install 'darkcat[chat]'
pip install 'darkcat[render]' && playwright install chromium
```

### External daemons (pick what you need)

| Network        | Install (Debian/Fedora terms)                  | Listens on              |
|----------------|------------------------------------------------|-------------------------|
| Tor            | `apt install tor` / `dnf install tor`          | 127.0.0.1:9050 (SOCKS), 9051 (control) |
| I2P            | i2pd or i2p-router from upstream                | 127.0.0.1:4444 (HTTP proxy) |
| IPFS (Kubo)    | install from <https://docs.ipfs.tech>           | 127.0.0.1:8080 (gateway), 5001 (API) |
| Freenet/Hyphanet | install from <https://www.hyphanet.org>       | 127.0.0.1:8888 (FProxy) |
| ZeroNet        | install from upstream                           | 127.0.0.1:43110 (UI) |
| Lokinet        | install from <https://lokinet.org>              | system TUN (no port) |
| Yggdrasil      | `apt install yggdrasil`                         | system TUN (no port) |
| GNUnet         | `apt install gnunet` + run `gnunet-arm`         | system resolver |

**Minimum viable setup:** just Tor. You can ignore the others until
you actually need them.

### First-run bootstrap

```bash
darkcat init
```

This creates `~/.darkcat/` (mode 0700), probes the daemons, and prints a
guided next-step list. Re-runnable any time — never overwrites.

---

## 3. Verify your environment

```bash
darkcat status
```

You should see at least Tor as `●` (green dot, reachable). If Tor is
red, check:

* `systemctl status tor` (Linux) or `brew services list | grep tor` (macOS).
* The control port: `darkcat tor info` should print Tor's own version.
* SOCKS port collision: another tool may already be on `:9050`.

If you only have Tor and want to silence the others, that's fine — every
command takes a `--protocol` flag and ignores the rest.

---

## 4. Your first crawl

### Crawl a curated Tor seed list

```bash
darkcat crawl -p tor -n 30
```

`-p tor` says "use the built-in Tor seed list". `-n 30` caps the run at
30 pages. You'll see live status as each fetch resolves:

```
[ok] 200 https://3g2upl4pq6kufc4m.onion/        (DuckDuckGo onion)
[ok] 200 https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/
[skip]    blocklist:host
…
```

Each fetched page is stored in `~/.darkcat/crawl.db` under the `pages`
table with full text, title, score, and timestamp.

### Crawl with a topic filter

```bash
darkcat crawl -p tor -t whistleblower leak -n 200
```

`-t` adds a topic-keyword filter. Pages that **don't** mention any
keyword get a low score and won't expand their outbound links — you stop
following the graph through irrelevant pages early.

### Crawl a single curated entry

```bash
darkcat -l tor                           # list curated Tor entry points
darkcat crawl -p tor -epfl 1 -d 2 -n 50  # entry #1, depth 2, 50 pages
```

`-epfl` means *entry-point-from-list*. Indexes are 1-based.

---

## 5. Searching what you crawled

```bash
darkcat search "secure drop"
darkcat top                  # top-scoring pages by topic match
darkcat top -p gemini -n 50  # top Gemini pages
darkcat stats                # page count per protocol
```

Search uses SQLite FTS5 with a porter tokenizer; `secure drop` matches
"securedrop" too. Combine with `-n` to cap results.

### Diff & history

```bash
darkcat history https://3g2upl4pq6kufc4m.onion/
darkcat diff https://3g2upl4pq6kufc4m.onion/
```

Every crawl appends a row to `page_history` *only if the body changed*,
so you can replay the evolution of a page over time without exploding
disk usage.

---

## 6. Scan for credentials and contact IDs

```bash
darkcat scan                 # scan all crawled pages (idempotent)
darkcat findings -n 50
darkcat findings --category email_password
darkcat findings --category session_id
```

Detected categories include API keys (AWS, GitHub, Slack, …), private
keys (PEM, PGP), credit cards (Luhn-validated), seed phrases (BIP-39),
crypto addresses (BTC/LTC/ETH/TRX/XMR), and **contact IDs** for the
messaging-only networks:

```bash
darkcat contacts list                 # group by network
darkcat contacts list --network session
darkcat contacts show 0512abc...
darkcat contacts export -o ids.csv
```

Each finding stores a salted SHA-256 of the secret plus a redacted
preview — never the raw secret. Set `--salt` on `darkcat scan` to make
the digests non-portable across installs.

### Watching for new findings

```bash
darkcat watch add --target 'mycompany.com' --sink notify
darkcat watch add --category aws_access_key --sink slack:https://hooks.slack…
darkcat scan                         # the watch fires inline
darkcat alerts -n 20
```

Sinks include `log`, `notify`, `file:/path`, `webhook:URL`, `slack:URL`,
`discord:URL`, `matrix:server|room|token`, and `email:to@host`.

---

## 7. Personas — logging in to gated forums

Many darkweb forums (Dread, KickAss, etc.) gate the content you came for
behind a login. Darkcat doesn't fill in HTML forms; it runs **off the
cookies you already have**.

### Create a burner identity

```bash
darkcat personas add bob \
    --network tor \
    --site dread.onion \
    --gen
```

`--gen` auto-generates a random handle and password. The vault lives at
`~/.darkcat/personas.json` (mode 0600).

### Import the cookies you obtained manually

Log in once via Tor Browser, export Netscape cookies (use a browser
extension), then:

```bash
darkcat --cookie-jar $(darkcat personas use bob) \
    cookies import dread-tor-export.txt
```

`darkcat personas use bob` prints the per-persona cookie-jar path.

### Run a logged-in crawl

```bash
darkcat --cookie-jar $(darkcat personas use bob) \
    crawl -p tor -ep https://dread.onion/d/somesub -n 50
```

### Encrypt the vault at rest

```bash
darkcat personas encrypt
# prompts for a passphrase; writes ~/.darkcat/personas.json.gpg (AES-256)
# and shreds the plain file
```

Once encrypted, future runs prompt for the passphrase or read it from
`$DARKCAT_VAULT_PASSPHRASE`.

---

## 8. Chat — login, list, read, send, ingest

```bash
darkcat chat backends                    # what's installed and ready
```

### Telegram (real account, not a bot)

You need an API ID + hash from <https://my.telegram.org>. Either
export them as env vars:

```bash
export DARKCAT_TG_API_ID=12345
export DARKCAT_TG_API_HASH=abcdef...
```

…or stash them in a persona's notes (`tg_api_id=… tg_api_hash=…`).

```bash
darkcat personas add alice-tg --network telegram --handle '+15551234567'
darkcat chat login telegram --persona alice-tg
# prompts for SMS code, then optional 2FA password
darkcat chat list   --persona alice-tg
darkcat chat read   --persona alice-tg <chat_id> -n 30
darkcat chat send   --persona alice-tg <chat_id> -m 'hello'
darkcat chat ingest --persona alice-tg <chat_id> -n 200
# stores messages as searchable pages in crawl.db
```

### Matrix

```bash
darkcat personas add alice-matrix \
    --network matrix \
    --site matrix.org \
    --handle '@alice:matrix.org' \
    --password 'syt_abc...'   # access token, OR your account password
darkcat chat login matrix --persona alice-matrix
darkcat chat list  --persona alice-matrix
```

Tokens beat passwords (no MFA prompts, no rate limits). E2EE works if
you installed `matrix-nio[e2e]` and the system `libolm`.

### XMPP

```bash
darkcat personas add bob-xmpp \
    --network xmpp \
    --handle 'bob@xmpp.example.org' \
    --password 'hunter2'
darkcat chat login bob-xmpp
darkcat chat list  --persona bob-xmpp
darkcat chat read  --persona bob-xmpp 'alice@xmpp.example.org'
```

XMPP servers without `mod_mam` (Prosody) have no message archive — the
read window listens ~3 s for live traffic, no backlog.

### SimpleX

Run the upstream daemon first: `simplex-chat -p 5225` then:

```bash
darkcat chat list --persona my-simplex --network simplex
```

### Session

You need `session-cli` (community project, no Python SDK):

```bash
npm i -g session-cli
darkcat chat list --persona my-session --network session
```

---

## 9. Cheat-sheet

```bash
# bootstrap
darkcat init                                   # one-time setup
darkcat status                                 # what's reachable

# crawl
darkcat crawl -p tor -n 30                     # 30 Tor pages
darkcat crawl -p gemini -t privacy -n 100      # gemini, topic-filtered
darkcat crawl -ep https://example.com/         # one explicit URL

# search & analyze
darkcat search "leak"                          # FTS5 search
darkcat top -n 20                              # highest topic scores
darkcat stats                                  # per-protocol counts
darkcat scan                                   # find IOCs
darkcat findings --category email_password
darkcat contacts list                          # session/simplex/tox/...

# alerting
darkcat watch add --target mycompany.com --sink notify
darkcat alerts -n 20

# identity
darkcat personas add bob --gen
darkcat --cookie-jar $(darkcat personas use bob) crawl ...
darkcat personas encrypt                       # AES-256 at rest

# chat
darkcat chat backends
darkcat chat login telegram --persona alice-tg
darkcat chat list  --persona alice-tg
darkcat chat read  --persona alice-tg <id> -n 50
darkcat chat ingest --persona alice-tg <id>    # → crawl.db

# UIs
darkcat tui                                    # Textual TUI
darkcat shell                                  # interactive REPL
darkcat gui                                    # Tkinter desktop
darkcat dashboard                              # read-only HTTP dashboard
```

---

## 10. Where to read next

* **`docs/USERGUIDE.md`** — surface vs deep vs dark vs darknet, every
  network's purpose / strengths / weaknesses, opsec hygiene.
* **`docs/NETWORKS.md`** — per-network deep dives: how they route, who
  runs them, what their weaknesses are, how darkcat reaches them.
* **`docs/INTERNALS.md`** — architecture, fetch path, scan path, schema,
  threat model, how to extend it.
* **`docs/CONFIG.md`** — every Config field, env var, CLI flag.

Common follow-up reading **outside** this repo:

* The Tor Project Manual: <https://support.torproject.org/operators/>
* I2P Tech Intro: <https://geti2p.net/en/docs/how/intro>
* Hyphanet/Freenet whitepaper: <https://www.hyphanet.org/whitepapers.html>
* IPFS Concepts: <https://docs.ipfs.tech/concepts/>
* Gemini protocol spec: <https://geminiprotocol.net/docs/specification.gmi>

---

## 11. Common pitfalls

**"Tor is up but every fetch times out."** Your guard might be slow —
try `darkcat tor newnym` to rotate circuits, or wait 60 s. Real onions
can be 1–5 s per request.

**"`pip install darkcat[chat]` is huge."** Use only the slice you need:
`darkcat[chat-telegram]` is ~5 MB; the full chat extra pulls four
backends.

**"Where did my cookies go?"** Default jar path is
`~/.darkcat/cookies.txt`. Per-persona jars: `~/.darkcat/cookies.<persona>.txt`.
Both are Netscape format, mode 0600.

**"My findings DB has my secrets in plaintext."** Yes — by design. The
`sample` column stores a redacted preview; the real safety is the
**digest** (`sha256(salt || secret)`). If your threat model includes
disk seizure, run on encrypted storage and pass `--salt` to `scan`.

**"Why won't darkcat send messages on Tox/Briar/Ricochet?"** Those
networks have no maintained Python client (Briar is mobile-first by
design, Ricochet Refresh is GUI-only, Tox needs a libtoxcore wrapper
nobody maintains). Darkcat extracts their IDs from crawled pages but
won't drive a session.

---

You're done. `darkcat init && darkcat crawl -p tor -n 30 && darkcat search …`
is the loop. Everything else is variants on it.
