# Darkcat internals

A guided tour of how darkcat is wired internally — what each module does,
how the pieces compose, and why the boundaries fall where they do. Read
this if you want to extend the tool or audit it.

> **Audience.** Operators, contributors, security reviewers. If you're
> here to use darkcat, start with `docs/USERGUIDE.md` instead.

---

## 1. Five-minute architecture

```
                                    ┌──────────┐
                                    │  CLI     │ argparse, src/darkcat/cli.py
                                    └────┬─────┘
        ┌─────────────────────┬──────────┴──────────┬──────────────────┐
        ▼                     ▼                     ▼                  ▼
   ┌─────────┐         ┌────────────┐         ┌──────────┐       ┌──────────┐
   │ Crawler │         │ Scanner    │         │ Watcher  │       │ Chat     │
   │ BFS     │         │ regex IOCs │         │ alerts   │       │ msg I/O  │
   └────┬────┘         └─────┬──────┘         └────┬─────┘       └────┬─────┘
        │                    │                     │                  │
        └─────────┬──────────┴─────────┬───────────┴──────────────────┘
                  ▼                    ▼
            ┌─────────┐           ┌──────────┐
            │ Fetcher │           │ Storage  │  SQLite + FTS5
            └────┬────┘           └────┬─────┘
                 ▼                     ▼
        ┌────────────────┐     pages, findings, watchlist,
        │  Transports    │     alerts, schedules, simhash,
        │  per-protocol  │     liveness_probes, page_history,
        └────────┬───────┘     blocklist_audit, links
                 ▼
            external daemons:
            tor, i2p, ipfs, freenet, lokinet,
            zeronet, hyper.fyi, name resolvers
```

Two design rules everything bends to:

1. **Single source of truth.** All persisted state lives in one SQLite
   file (default `~/.darkcat/crawl.db`). No cache directories, no
   side-channel files except cookie jars (`auth.py`) and the persona
   vault (`personas.py`) — both of which have explicit format docs.
2. **Optional dependencies stay optional.** Every heavy library
   (`telethon`, `matrix-nio`, `slixmpp`, `playwright`) is imported
   inside the function that needs it, never at module top. A user who
   installs `pip install darkcat` and never runs `chat` should not pay
   for `telethon` startup time.

---

## 2. Module map

| Path | Responsibility |
|------|----------------|
| `cli.py` | Argparse layer. Every subcommand has a `cmd_*` function. No business logic — just argument validation and orchestration. |
| `config.py` | `Config` dataclass: ports, paths, knobs. Built once per CLI invocation in `_build_config()`. |
| `protocols.py` | URL classification (`classify(url) -> Protocol`) and normalization. The single dispatch point for "which transport handles this URL?" |
| `transports.py` | One transport class per protocol family (HTTP/SOCKS5, raw socket, Gemini-TLS, etc.). Each exposes `fetch(url) -> Response`. |
| `fetcher.py` | Cross-cutting fetch concerns: cookie jar attachment, retry, timeouts, status-code mapping. Wraps `transports`. |
| `crawler.py` | BFS frontier, depth budget, per-host concurrency, topic scoring, link extraction from `extractor.py`. Calls `Fetcher` and `Storage`. |
| `extractor.py` | HTML/Gemini/text parsing. Output: `Page(url, title, text, links, score)`. Calls plugin chain via `parse_with_plugins()`. |
| `plugins.py` / `plugins_builtin.py` | Per-site extractor plugins (Dread, Telegram, Pastebin-shape). User plugins live under `~/.darkcat/plugins/`. |
| `topic_filter.py` | Substring + token-ratio scoring of a page text against a list of topic keywords. Returns float in [0, 1]. |
| `politeness.py` | `HostBackoff` (exponential, capped) and `TorRotator` (NEWNYM after N consecutive host failures). |
| `seeds.py` / `entries.py` | Built-in seed lists per protocol; curated entry-point catalog with descriptions. |
| `scanner.py` | Pattern-matching IoC extraction. 27 categories from `email_password` to `ricochet_id`. Stateless: input text → list[Finding]. |
| `watch.py` | Watchlist matching + alert sinks (log / notify / file / webhook / slack / discord / matrix / email). |
| `storage.py` | All SQL. Schema in a triple-quoted DDL block at the top; methods cluster around the table they touch. Concurrency is a single threading.Lock around `self.conn`. |
| `personas.py` | JSON-backed credential vault, optional GPG-symmetric encryption. |
| `auth.py` | Persistent Netscape cookie jar shared across HTTP transports. |
| `liveness.py` | One-shot URL probes (latency + content-hash) with drift detection. |
| `scheduler.py` | DB-backed cron-lite. Schedules are rows with `next_run_at`; `run_due()` fires anything past due. |
| `dashboard.py` | Stdlib-only HTTP dashboard (no Flask). Read-only. Optional bearer-token auth. |
| `server.py` | HIBP-style hash-prefix lookup server over the findings table. |
| `chat/` | Messenger backends (Telegram, Matrix, XMPP, SimpleX, Session, Tox, Briar, Ricochet). |
| `discovery.py` | Querying public dark-web search engines (Ahmia, Tor.taxi, etc.) for seed URLs. |
| `feeds.py` | Sitemap.xml / RSS / Atom / JSON-Feed probing for a host. |
| `encoded.py` / `decode-links` | Surface URLs hidden in JS, base64, ROT13. |
| `pgp.py` | Harvest PGP key blocks from crawled pages. |
| `ocr.py` | Tesseract integration for `<img>` text extraction. |
| `telegram.py` | Scraping public `t.me/s/<channel>` previews (no API key, no login — *separate* from `chat/telegram.py`). |
| `zeronet.py` | Walking ZeroNet `content.json` graphs via the local UI. |
| `torctl.py` | Tor control-port client (NEWNYM, GETINFO, descriptor fetch). |
| `blocklist.py` | URL block-rule matching + audit log. |
| `theme.py` | Rich console styles, banner. Cosmetic only. |
| `tui.py` / `gui.py` / `repl.py` | Alternative front-ends over the same core. |
| `export.py` | JSONL / STIX 2.1 / MISP event JSON serialization for findings. |

---

## 3. The fetch path, end to end

```
darkcat fetch tor://abc.onion/index.html
    │
    ▼
cli.cmd_fetch
    │
    ▼
Fetcher(cfg).fetch(url)            ← cookie jar attached, retries, timeouts
    │
    ▼
classify(url) → Protocol.TOR
    │
    ▼
TorTransport.fetch(url)            ← SOCKS5 to 127.0.0.1:9050
    │   isolation: per-host SOCKS auth string for fresh circuit
    ▼
requests.get(url, proxies=…, headers=…)
    │
    ▼
Response{status, headers, body, content_type, final_url}
    │
    ▼
extractor.parse(final_url, body, content_type)
    │
    ├── plugins.parse_with_plugins(...)  ← matched plugins win
    └── default HTML / Gemini / text / pdf / image branches
    │
    ▼
Page{url, title, text, links, score}
    │
    └── (in `crawl`) → enqueue links + Storage.record_page(...)
```

The whole call chain is synchronous. `requests` is used for HTTP-family
protocols; everything else (Gemini, Gopher, Spartan, Nex, Finger, NNTP)
uses raw sockets. Async I/O is intentionally avoided for the fetch
path — single-process tools are easier to reason about and Tor has its
own concurrency limits we don't want to amplify.

---

## 4. The scan path, end to end

```
scanner.scan_text(text, salt=b"...")  ← stateless, deterministic, fast
    │
    ├── _RX_EMAIL_PWD.finditer(text)          → email_password
    ├── for cat, rx, conf in _API_KEY_RXS:    → aws_*, github_token, ...
    ├── _RX_PEM, _RX_PGP_BLOCK                → private_key, pgp_block
    ├── _RX_CC + _luhn_ok()                   → credit_card
    ├── _RX_INSERT                            → sql_dump
    ├── _RX_MNEMONIC + uniqueness heuristic   → seed_phrase
    ├── _scan_crypto(text, salt)              → btc/ltc/eth/trx/xmr (validated)
    ├── _scan_contacts(text, salt)            → session/simplex/tox/xmpp/matrix/...
    └── _RX_BREACH                            → breach_marker
    │
    ▼
list[Finding]   each: category, sample (redacted), digest (sha256 salt||v),
                       target (searchable handle), confidence, line_no
    │
    ▼
Storage.record_findings(url, protocol, findings)
    │   dedupe by (url, category, digest)
    ▼
Watcher.apply(url, protocol, new_findings)
    │
    ├── for w in watches:
    │     if matches(w, finding):
    │       fire(w, finding, url, protocol)   ← log/notify/file/webhook/slack/...
    │       Storage.record_alert(w.id, url, finding.digest, status)
```

The scan path never touches the network. All inputs come from
`Storage.iter_pages_for_scan()`. The output digests are deterministic
within a salt: the same secret on two pages dedupes correctly, but
across two darkcat installs with different salts the same secret looks
different (so an aggregated DB doesn't leak a secret-membership oracle).

---

## 5. The watchlist firing model

A watch has up to three match fields — `target`, `category`, `sample` —
plus a sink. Matching rules:

* If the watch sets nothing, it never fires (a no-op safety net).
* If `target` is set, the finding's `target` must match the regex
  (default literal, regex if `is_regex=1`).
* If `category` is set, it must be exact-equal (or fullmatch in regex
  mode).
* If `sample` is set, the finding's redacted preview must match.

A watch is `AND` across the set fields. Use multiple watches for OR.

Sinks (one per watch):

| Sink | Format |
|------|--------|
| `log` | stdout line, audit-friendly |
| `notify` | `notify-send` desktop popup |
| `file:/path` | append one JSON object per alert |
| `webhook:URL` | HTTP POST `application/json` |
| `slack:URL` | Slack incoming webhook (`{"text": ...}`) |
| `discord:URL` | Discord webhook (`{"content": ...}`, 1900-char cap) |
| `matrix:HOMESERVER\|ROOM\|TOKEN` | Matrix m.room.message via PUT to /rooms/{room}/send |
| `email:to@host` | SMTP, configured via `DARKCAT_SMTP_*` env vars |

`record_alert` is the dedup gate: an `(watch_id, url, digest)` triple
is unique, so the same finding never alerts twice on the same URL.

---

## 6. Storage schema (abridged)

The full DDL lives at the top of `src/darkcat/storage.py`. Quick map:

| Table | Purpose | Key indexes |
|-------|---------|-------------|
| `pages` | One row per crawled URL with text body, score, status. | `url` PK; `protocol`, `score` |
| `pages_fts` | FTS5 virtual table mirroring `(url, title, text)`. | porter tokenizer |
| `page_history` | Append-only snapshots of `(url, content_hash, text)` for diff/history. | `url`, `captured_at` |
| `simhash` | 64-bit SimHash + 4×16-bit LSH bands per page, for `mirrors`. | bands |
| `links` | Edges from `src` page to `dst` URL, for graph queries. | `src`, `dst` |
| `findings` | One row per detected secret/IoC. Dedup `(url, category, digest)`. | `category`, `target`, `url` |
| `watchlist` | Active watch rules. Dedup `(target, category, sample, sink)`. | n/a |
| `alerts` | One row per fired alert. Dedup `(watch_id, url, digest)`. | `watch_id`, `fired_at` |
| `schedules` | Persistent re-crawl jobs with `next_run_at`. | `name` UNIQUE |
| `liveness_probes` | One row per URL probe (status + latency + content_hash). | `url`, `probed_at` |
| `blocklist_audit` | Log of every URL blocked by a rule. | `blocked_at` |
| `pgp_keys` | Harvested PGP public-key blocks. | `fingerprint` |

All writes go through `Storage.transaction()` which wraps a
`BEGIN IMMEDIATE … COMMIT` under a single `threading.Lock`. SQLite's
WAL mode is enabled (`PRAGMA journal_mode=WAL`) so reads never block
on writes.

---

## 7. The chat layer

Each backend implements the `Messenger` ABC in `chat/base.py`:

```python
class Messenger:
    network: str
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def list_channels(self, *, limit: int = 100) -> list[ChatChannel]: ...
    def read(self, channel_id: str, *, limit: int = 50) -> list[ChatMessage]: ...
    def send(self, channel_id: str, text: str) -> ChatMessage: ...
```

Persona binding: every Messenger receives a `Persona` and creates a
sandboxed `~/.darkcat/chat-sessions/<persona>/` directory. Cached
session files (Telethon `.session`, Matrix `store/`, Matrix
`matrix.token.json`) live there with `chmod 0700` on the dir, `0600`
on the files.

Async-vs-sync rule: backends that use async libraries
(`telethon`, `matrix-nio`, `slixmpp`) keep a private event loop in
`self._loop` and expose blocking methods. The CLI never touches
`asyncio` directly, which lets us mix backends in a single process.

`chat/__init__.py` is a registry. `availability_report()` walks every
known backend, imports its module, and returns a row for the
`chat backends` CLI command. A backend's optional dependency missing
shows up as `available=False` with a one-line install hint — never an
import-time crash.

### Telegram specifics

Telethon needs an API ID + hash from
<https://my.telegram.org>. Three resolution sources:

1. `DARKCAT_TG_API_ID` / `DARKCAT_TG_API_HASH` env vars.
2. Persona notes string `tg_api_id=12345 tg_api_hash=abcdef…`.
3. Public test pair (rate-limited; only used so `chat backends` can
   prove the import path works).

Login is interactive: phone code → optional 2FA password. After the
first login the Telethon `.session` file holds an opaque session key —
not the password — so re-runs are silent.

### Matrix specifics

Token-first login: if `persona.password` looks like a token (`syt_…`,
`mxat_…`, or 40+ chars no spaces), we set it directly and `whoami()`
to verify. Otherwise we treat it as the account password and call
`client.login()`. Either way the resulting token is cached in
`matrix.token.json`. E2EE requires `matrix-nio[e2e]` plus the system
`libolm`; without them encrypted rooms still list but `read()` returns
empty bodies (we silently skip non-`RoomMessageText` events).

### XMPP specifics

`slixmpp` is used in a one-shot pattern: connect, fetch roster,
listen ~3 s, disconnect. There's no long-running consumer because the
CLI is request/response. A real-time consumer would use the underlying
`slixmpp.ClientXMPP` directly.

### SimpleX specifics

We do not implement SMP. We assume `simplex-chat -p 5225` is running
locally and we drive its WebSocket REPL with REPL-syntax commands
(`/_get chats`, `/_send …`). This is the same surface the upstream
GUI talks to.

### Session specifics

Session has no Python SDK. We shell out to `session-cli` (community
project) with `--json` flags and parse stdout. The persona's `handle`
must match an account already imported into session-cli's local store.

### Tox / Briar / Ricochet

Stubs that document why no automation surface exists. `Briar` is
mobile-first by design; F2F messengers are uncrawlable as a feature.

---

## 8. The persona vault

Layout under `$DARKCAT_HOME` (default `~/.darkcat/`):

```
crawl.db                         # crawl + findings + alerts + ...
cookies.txt                      # default jar (used by `auth.py`)
cookies.<persona>.txt            # per-persona jar
personas.json                    # plaintext vault (mode 0600)
personas.json.gpg                # AES-256 symmetric (gpg -c) — wins over plain
chat-sessions/<persona>/         # per-persona chat session caches
plugins/*.py                     # user plugins (auto-loaded)
```

The `Vault` class loads exactly one of `personas.json.gpg` /
`personas.json` (encrypted preferred). On `save()`, the file is
written to a sibling `*.tmp` then `os.replace`d — atomic on POSIX.
GPG passphrases come from `$DARKCAT_VAULT_PASSPHRASE` for unattended
use, else stdin via `getpass`. The passphrase is not retained on the
Vault instance after decryption beyond the immediate save call.

`personas encrypt` does a "shred and rename" on the plain file:
overwrites with zeros, fsyncs, unlinks. Not bulletproof against
journaled filesystems with snapshots, but reasonable for the threat
model (a casual attacker reading the file).

---

## 9. Concurrency model

* **One process, one SQLite connection.** All access goes through
  `Storage._lock`. WAL mode allows concurrent reads, but darkcat is a
  CLI — there's never more than a small thread pool live at once.
* **Per-host concurrency in the crawler.** `Crawler` holds a
  `defaultdict(deque)` of in-flight URLs per host and limits the
  width via `policy.per_host`. Politeness backoff keys on host too.
* **No background services.** Schedules and liveness loops run as
  foreground processes the user explicitly starts (`schedule loop`,
  `liveness loop`). No daemon, no systemd integration. We assume the
  operator runs darkcat under `tmux` / `screen` / a service manager
  they already trust.

---

## 10. Threat model

What darkcat protects:

* **Findings dedup digest.** `sha256(salt || secret)` — set a non-empty
  salt on `--scan` to make digests non-portable. Without that,
  shipping a `crawl.db` to a peer leaks a membership oracle: "if
  you compute sha256(your_secret) and find a match, that secret is
  on this disk".
* **Cookie jars.** Mode 0600. Per-persona separation prevents
  accidentally riding persona A's session on persona B's URL.
* **Persona vault.** Optional AES-256 symmetric encryption via gpg.
  The plain-file fallback is mode 0600, never group/world-readable.
* **Tor stream isolation.** On by default — different hosts go down
  different circuits, so a colluding-relay attack can't link two
  onion fetches via shared relays.

What darkcat *doesn't* protect:

* **Process memory.** Anything you load gets read out by `ptrace`,
  `gcore`, or a kernel debugger. Don't run darkcat on a host you
  don't control.
* **Tor metadata.** A passive observer who can see *both* your guard
  and your destination can still correlate timing. Tor doesn't fix
  that and neither do we.
* **Server-side logs.** `darkcat watch` sinks (Slack, Discord, Matrix,
  SMTP) all send alert text to third parties. If the alert quotes a
  finding sample, that sample is now on someone else's server.
* **Forensics.** Findings sit on disk in plaintext (sample column).
  If your threat model includes physical seizure, run on encrypted
  storage.

---

## 11. Extending darkcat

Three common extension points:

* **A new transport.** Add a class to `transports.py`, register it in
  `protocols.py` (URL classification), and teach `entries.py` /
  `seeds.py` about its URL form. The Fetcher and Crawler don't need
  to change.
* **A new scanner category.** Add a `_RX_FOO` and a branch in
  `scan_text()`, append the name to `CATEGORIES`. If it's a contact ID,
  also add to `CONTACT_CATEGORIES` so `darkcat contacts` picks it up.
* **A new chat backend.** Drop a module under `src/darkcat/chat/`,
  expose a `<Network>Messenger(Messenger)` class, set `HAS_<DEP>`
  to a real availability check, and add a `(name, module, marker)`
  entry to `_BACKENDS` in `chat/__init__.py`.

A site-specific extractor plugin doesn't even need a code change —
drop a `.py` file under `~/.darkcat/plugins/` exposing a
module-level `PLUGINS = [MyPlugin()]` list and run any `darkcat
plugins --test-url URL` to verify it's picked up.

---

## 12. Performance characteristics

| Operation | Dominant cost | Notes |
|-----------|---------------|-------|
| `crawl` | Network latency | Tor circuits ~500–2000 ms, I2P 1–5 s, Freenet 5–60 s. Per-host width = `policy.per_host` (default 4). |
| `search` | FTS5 | Sub-100 ms for a million pages on consumer SSD. |
| `top` | One full table scan, sorted. | Indexed by `score`. |
| `scan` | Regex eval on stored bodies. | ~1–2 MB/s/core on plain Python `re`. Salt doesn't move the needle. |
| `mirrors` | LSH lookup + Hamming-distance refinement. | O(N) average, vs. O(N²) for naive. |
| `liveness` | Like `crawl` but no parsing. | ~3× faster than a real crawl, not 100×. |
| `watch fire` | One sink call. | Webhook ~50–500 ms; SMTP a few seconds. |
| `chat read` | One backend round-trip. | Telegram ~200 ms; Matrix ~300 ms; XMPP ~3 s (listen window). |

The full DB on a thoroughly crawled estate (≈2M pages, 3M findings)
fits in ~6 GB of SQLite + WAL. On a disk that can do 200 MB/s reads,
a full FTS scan rebuild takes ~40 s; you don't need to think about it.
