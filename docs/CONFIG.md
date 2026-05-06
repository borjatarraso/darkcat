# Darkcat configuration reference

Every setting darkcat exposes — what defaults to what, where it comes
from, and how to override it. Three sources, in increasing priority:

1. **Hard-coded defaults** in `src/darkcat/config.py`.
2. **Environment variables** read inline by individual modules.
3. **Command-line flags** that win over both.

There is no `config.toml`. The intent is for power users to wrap
darkcat in a shell script that exports env vars + passes flags — easier
to audit than YAML you forgot you wrote.

---

## 1. The `Config` dataclass

`src/darkcat/config.py:Config` holds the in-memory configuration for a
single CLI invocation. Built once in `_build_config()` from `argparse`
namespace + defaults.

| Field | Default | CLI flag | Purpose |
|-------|---------|----------|---------|
| `tor_socks_host` | `127.0.0.1` | — | Tor SOCKS5 host |
| `tor_socks_port` | `9050` | `--tor-port N` | Tor SOCKS5 port |
| `tor_control_port` | `9051` | `--tor-control-port N` | Tor control protocol port |
| `tor_control_password` | `None` | `--tor-control-password STR` | Plain password for control auth |
| `tor_control_cookie_path` | `None` (auto-discovered) | `--tor-control-cookie PATH` | Cookie file for control auth |
| `tor_stream_isolation` | `True` | `--no-tor-isolation` | Per-host SOCKS auth → fresh circuit per onion |
| `i2p_http_host` | `127.0.0.1` | — | I2P HTTP-proxy host |
| `i2p_http_port` | `4444` | `--i2p-port N` | I2P HTTP-proxy port |
| `i2p_jump_services` | notbob.i2p, stats.i2p | — | Fallback jump-service URLs when host isn't in addressbook |
| `ipfs_gateway_host` | `127.0.0.1` | — | IPFS HTTP gateway host |
| `ipfs_gateway_port` | `8080` | `--ipfs-port N` | IPFS HTTP gateway port |
| `ipfs_public_gateway` | `https://ipfs.io` | — | Public-gateway fallback |
| `use_public_ipfs_gateway` | `False` | `--public-ipfs` | Allow public-gateway fallback (leaks request) |
| `freenet_fproxy_host` | `127.0.0.1` | — | Freenet FProxy host |
| `freenet_fproxy_port` | `8888` | — | Freenet FProxy port |
| `zeronet_host` | `127.0.0.1` | — | ZeroNet UI host |
| `zeronet_port` | `43110` | — | ZeroNet UI port |
| `ens_gateway` | `eth.limo` | — | ENS HTTPS gateway domain |
| `handshake_gateway` | `hns.is` | — | Handshake HTTPS gateway domain |
| `hyper_gateway` | `hyper.fyi` | — | Hyperdrive HTTPS gateway domain |
| `hyper_local_gateway` | `127.0.0.1:4501` | — | Local hyperdrive gateway, tried first |
| `user_agent` | Firefox 115 ESR | — | HTTP User-Agent for clearnet & Tor fetches |
| `request_timeout` | `45.0` | — | Per-request HTTP timeout (s) |
| `politeness_delay` | `1.5` | — | Min delay between same-host requests (s) |
| `max_response_bytes` | `4 * 1024 * 1024` | — | 4 MiB cap on body read |
| `db_path` | `~/.darkcat/crawl.db` | `--db PATH` | SQLite DB path |
| `cookie_jar_path` | `None` | `--cookie-jar PATH` | Persistent Netscape cookie jar |

### Computed properties

| Property | Returns |
|----------|---------|
| `cfg.tor_proxies` | `{"http": "socks5h://...", "https": "..."}` for `requests` |
| `cfg.tor_proxies_for(host)` | Same, but with per-host SOCKS auth for stream isolation |
| `cfg.i2p_proxies` | `{"http": "...", "https": "..."}` pointing at I2P proxy |

---

## 2. Top-level CLI flags

These appear on `darkcat --help` and apply globally. Most just set
`Config` fields above.

```
darkcat [-h] [-V] [--about] [-l PROTOCOL] [-la]
        [--db DB]
        [--tor-port PORT]
        [--tor-control-port PORT]
        [--tor-control-password STR]
        [--tor-control-cookie PATH]
        [--no-tor-isolation]
        [--i2p-port PORT]
        [--ipfs-port PORT] [--public-ipfs]
        [--cookie-jar PATH]
        [-v] [-q]
        COMMAND ...
```

| Flag | What it does |
|------|--------------|
| `-V`, `--version` | Print version and exit |
| `--about` | Print maintainer / license / one-liner and exit |
| `-l, --list PROTO` | Print curated entry points for `PROTO` and exit (`all` for every protocol) |
| `-la, --list-all` | Shorthand for `-l all` |
| `--db PATH` | Override SQLite DB path |
| `--tor-port N` | Tor SOCKS5 port |
| `--tor-control-port N` | Tor control port |
| `--tor-control-password STR` | Plain password for control auth |
| `--tor-control-cookie PATH` | Cookie-file path (auto-discovered if omitted) |
| `--no-tor-isolation` | Disable per-host SOCKS auth (single circuit shared across hosts) |
| `--i2p-port N` | I2P HTTP-proxy port |
| `--ipfs-port N` | IPFS gateway port |
| `--public-ipfs` | Allow public-gateway fallback (leaks request to ipfs.io) |
| `--cookie-jar PATH` | Persistent Netscape cookie jar (used by every HTTP-family transport) |
| `-v` | Verbose logging (`logging.INFO`) |
| `-q` | Quiet — suppress per-page progress in `crawl` |

---

## 3. Environment variables

Modules read these directly. Setting them in your shell is enough — no
flag wires them up.

| Env var | Default | Read by | Purpose |
|---------|---------|---------|---------|
| `DARKCAT_HOME` | `~/.darkcat` | `personas.default_dir()` | Override the home directory (DB, vault, cookies, sessions) |
| `DARKCAT_VAULT_PASSPHRASE` | unset | `cli._vault_passphrase()` | Skip the GPG passphrase prompt for unattended runs |
| `DARKCAT_TG_API_ID` | unset | `chat.telegram._resolve_api_pair()` | Telegram API ID from <https://my.telegram.org> |
| `DARKCAT_TG_API_HASH` | unset | `chat.telegram._resolve_api_pair()` | Telegram API hash matching the ID above |
| `DARKCAT_SMTP_HOST` | unset | `watch._sink_email()` | SMTP host for `email:` watchlist sink |
| `DARKCAT_SMTP_PORT` | `587` | `watch._sink_email()` | SMTP port |
| `DARKCAT_SMTP_USER` | empty | `watch._sink_email()` | SMTP auth username |
| `DARKCAT_SMTP_PASS` | empty | `watch._sink_email()` | SMTP auth password |
| `DARKCAT_SMTP_FROM` | falls back to user | `watch._sink_email()` | `From:` header for outbound mail |
| `DARKCAT_SMTP_TLS` | `1` | `watch._sink_email()` | `0` disables STARTTLS |

Reading priority for **Telegram credentials** is: env vars → persona
notes (`tg_api_id=… tg_api_hash=…`) → public test pair (rate-limited;
useful only to verify import path).

---

## 4. Per-command flags worth knowing

A few subcommands have flags that materially change behavior:

### `darkcat crawl`

| Flag | Default | Notes |
|------|---------|-------|
| `-p, --protocol PROTO` | `tor` | Built-in seed set / context for `-epfl` |
| `-ep, --entry-point URL` | none | One explicit URL as the only seed |
| `-epfl, --entry-point-from-list N` | none | Use entry #N from the curated list (`a` = all) |
| `--seeds URL...` | none | Explicit seed list (overrides built-ins) |
| `--seed-file PATH` | none | One URL per line; `#` for comments |
| `-t, --topics WORD...` | `[]` | Topic keywords / quoted phrases |
| `--threshold N` | `0.0` | Min score required to expand a page's links |
| `-n, --max-pages N` | `100` | Stop after N pages |
| `-d, --max-depth N` | `2` | BFS depth from seeds |
| `--per-host N` | `25` | Cap pages per host |
| `--follow-clearnet` | off | Follow clearnet links from inside darknet pages |
| `--no-cross-protocol` | off | Stay within the seed's protocol |
| `--blocklist FILE` | none | Skip URLs / hosts / hashes; audit to `blocklist_audit` |
| `--render` | off | Render via headless Chromium (Playwright) |
| `--render-timeout SEC` | `45` | Per-page render timeout |
| `--newnym-after N` | `3` | Tor SIGNAL NEWNYM after N consecutive same-host failures |
| `--no-newnym` | off | Disable reactive circuit rotation |
| `--backoff-max SEC` | `60` | Cap on per-host exponential backoff |

### `darkcat scan`

| Flag | Default | Notes |
|------|---------|-------|
| `--url URL` | none | Scan one live URL (fetch + scan, do not store body) |
| `--category CAT...` | all 27 | Limit to these categories |
| `--target STR` | none | Restrict findings to ones whose target matches |
| `--salt HEX` | empty | Salt for finding digests (non-portable across installs) |
| `-n, --limit N` | `0` | Cap results |

### `darkcat chat`

| Subaction | Required | Notes |
|-----------|----------|-------|
| `backends` | — | Lists install state and hints |
| `login NETWORK` | `--persona NAME` | Interactive login flow |
| `list` | `--persona NAME` | Channels / rooms / DMs |
| `read CHANNEL_ID` | `--persona NAME` | Last N messages |
| `send CHANNEL_ID` | `--persona NAME -m TEXT` | One-shot message |
| `ingest CHANNEL_ID` | `--persona NAME` | Store messages as searchable pages |

`--network NETWORK` overrides the persona's `network` field for one
invocation (useful when a persona spans multiple backends).

### `darkcat personas`

| Subaction | Required | Notes |
|-----------|----------|-------|
| `add NAME` | — | `--gen` auto-generates handle + password |
| `list` | — | `--network`, `--site`, `--tag` filters |
| `show NAME` | — | `--reveal` to print password / recovery |
| `remove NAME` | — | Deletes vault entry; cookie jar untouched |
| `gen` | — | Roll a name + password; doesn't save |
| `use NAME` | — | Print the persona's cookie-jar path |
| `path` | — | Print vault file path |
| `encrypt` | — | Convert plain → AES-256 .gpg (shreds plain) |
| `decrypt` | — | `--keep` keeps the .gpg after decryption |

---

## 5. File locations

All under `$DARKCAT_HOME` (default `~/.darkcat/`):

```
crawl.db                     # main SQLite DB (pages, findings, alerts, …)
crawl.db-wal                 # WAL journal (auto-rotated)
crawl.db-shm                 # WAL shared memory
cookies.txt                  # default Netscape cookie jar (mode 0600)
cookies.<persona>.txt        # per-persona Netscape cookie jar
personas.json                # plaintext vault (mode 0600)
personas.json.gpg            # encrypted vault (preferred over plain)
chat-sessions/<persona>/     # per-persona chat session caches (mode 0700)
plugins/*.py                 # user extractor plugins (auto-loaded)
```

Override the root with `DARKCAT_HOME=/some/path darkcat …`. Override
just the DB path with `--db /some/path/foo.db`.

---

## 6. Worked example: an unattended scheduled run

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. Vault passphrase, never visible in `ps`:
export DARKCAT_VAULT_PASSPHRASE="$(< /etc/darkcat/vault.pass)"

# 2. Telegram credentials in the env, not on the CLI:
export DARKCAT_TG_API_ID=12345
export DARKCAT_TG_API_HASH=abcdef0123...

# 3. Email-sink credentials for watchlist alerts:
export DARKCAT_SMTP_HOST=smtp.example.org
export DARKCAT_SMTP_PORT=587
export DARKCAT_SMTP_USER=alerts@example.org
export DARKCAT_SMTP_PASS="$(< /etc/darkcat/smtp.pass)"
export DARKCAT_SMTP_FROM=alerts@example.org

# 4. Pin the home dir:
export DARKCAT_HOME=/var/lib/darkcat

# 5. Run the schedule and ingest a watched chat channel:
darkcat schedule run-due
darkcat chat ingest --persona alerts-tg some_channel -n 200
darkcat scan
```

Wrap that in a systemd timer or a cron line and you have darkcat
running fully unattended — nothing on argv that would leak via `ps -ef`.

---

## 7. What's intentionally not configurable

* **Dispatch order of transports.** Each URL is classified once; there's
  no fallback chain you can reorder.
* **The scanner's regexes.** They live in `scanner.py`; modifying them
  is a code change, not a config change. Use `--category` to *filter*,
  not to *redefine*.
* **The schema.** Schema migrations are in `storage.py`; bumping
  versions is the project's job, not the operator's.
* **Per-protocol UA / headers.** The `user_agent` field is global on
  purpose. If you need per-host headers, write a plugin.

When in doubt, read the source. `darkcat` is small (~6 kLOC of Python)
and every config knob has exactly one read site you can grep for.
