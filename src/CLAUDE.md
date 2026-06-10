# src/ — the darkcat package

Everything importable lives under `src/darkcat/`. Flat layout: one file
per concern, two subpackages (`chat/`, `identity/`). The package is
shipped to PyPI via `pyproject.toml`'s `setuptools.packages.find`
(`where = ["src"]`).

## Public interface

- `darkcat.cli:main` — the console-script entry point declared in
  `pyproject.toml [project.scripts]`. Every other frontend is reached
  by `darkcat <subcommand>`: `tui`, `gui`, `shell` (REPL).
- `python -m darkcat` — equivalent to `darkcat`; routed through
  `darkcat/__main__.py`.

There is no stable Python API for downstream importers — every module
may move or rename between releases. Treat the CLI as the contract.

## Module map (one-liners)

| Module | Concern |
|---|---|
| `cli.py` | argparse entry, grouped help index, every `cmd_<name>` handler |
| `repl.py` | `cmd.Cmd` shell — wraps the CLI commands with completion |
| `tui.py` | Textual fullscreen TUI — Screens, modals, key bindings |
| `gui.py` | Tkinter desktop GUI — mirrors the TUI in a window |
| `config.py` | defaults, ports, paths, transport gateways |
| `protocols.py` | URL → `Protocol` classifier (Tor / I2P / IPFS / …) |
| `transports.py` | per-protocol HTTP / socket fetchers |
| `fetcher.py` | `Protocol` → transport dispatch + retry policy |
| `extractor.py` | HTML / Gemini / Gopher → title / text / links |
| `crawler.py` | BFS crawler with stop-event + event callbacks |
| `topic_filter.py` | keyword + phrase scoring |
| `categorize.py` | category / score formula used by results table |
| `scanner.py` | regex / Luhn-based credential + leak detector |
| `watch.py` | watchlist matching + sink dispatch |
| `export.py` | findings → JSONL / STIX 2.1 / MISP |
| `server.py` | HIBP-style hash-prefix HTTP server |
| `discovery.py` | submit queries to onion search engines, harvest seeds |
| `feeds.py` | sitemap / RSS / Atom / JSON-Feed probing |
| `encoded.py` | rescue URLs from JS / base64 / ROT13 |
| `ocr.py` | Tesseract integration for image-encoded pages |
| `torctl.py` | minimal Tor control-port client |
| `probe.py` | active reachability probes for Yggdrasil / cjdns / Lokinet |
| `blocklist.py` | abuse blocklist (host / suffix / urlcontains / hash) |
| `telegram.py` | `t.me/s/<channel>` scraper (no auth) |
| `pgp.py` | PGP public-key block extractor |
| `zeronet.py` | `content.json` walker for ZeroNet sites |
| `storage.py` | SQLite + FTS5 — pages, links, FTS, findings, alerts |
| `seeds.py` | default seed lists per protocol |
| `personas.py` | persona vault (plain or GPG-symmetric encrypted) |
| `mail.py` | mail send / fetch (SMTP / IMAP) per persona |
| `mail_providers.py` | curated provider presets (ProtonMail, Tutanota, …) |
| `auth.py` | login flows shared by mail + chat backends |
| `theme.py` | shared colour palette + ASCII logo + glyphs |
| `help_examples.py` | curated catalog driving the cheatsheet on every frontend |
| `hub_config.py` | chat-hub refresh interval persisted to `~/.darkcat/hub.json` |
| `dashboard.py` | crawl-status dashboard for the TUI / GUI |
| `liveness.py` | per-page liveness signal aggregation |
| `entries.py` | curated entry-points discovered by `-la` |
| `render.py` | optional headless-Chromium render via Playwright |
| `scheduler.py` | scheduled-crawl runner |
| `plugins.py` / `plugins_builtin.py` | plugin loader + bundled plugins |
| `control.py` | sudo-gated transport start / stop (Linux services) |
| `elevation.py` | password-provider abstraction for sudo prompts |
| `__init__.py` | version, license, URL constants |
| `__main__.py` | `python -m darkcat` shim → `cli:main` |

## Subpackages

- **`chat/`** — one module per messenger backend (`telegram`, `matrix`,
  `xmpp`, `simplex`, `session`, `tox`, `briar`, `ricochet`), the shared
  `base.py` (Messenger ABC, `ChatChannel`, `ChatMessage`,
  `BackendUnavailable`, `AuthError`), and `hub.py` (cross-persona
  aggregator powering `chat hub`). Backends always export `HAS_<DEP>`
  module markers + `INSTALL_HINT` strings so the hub can report
  `unavailable` rows without a hard import.
- **`identity/`** — persona vault (`vault.py`), signup credential
  generator (`generator.py`), transport-routed launcher (`launcher.py`,
  `transport.py`), and provider-specific signup recipes under
  `providers/`.

## Module-local conventions

- Every module imports only the **core** runtime deps at top-level
  (`requests`, `PySocks`, `bs4`, `lxml`, `rich`, `textual`). Optional
  deps — `tkinter`, `telethon`, `matrix-nio`, `slixmpp`,
  `websocket-client`, `playwright`, `pycryptodome`, `argcomplete`,
  `fpdf2` — are imported **inside the function that needs them** so
  the CLI runs on a stripped install.
- New CLI subcommands must be registered in `COMMAND_GROUPS` (cli.py)
  **and** mirrored in the REPL command table, the TUI key map, and the
  GUI menu. The tests in `tests/test_help_index.py` enforce parity.
- Backends in `chat/` register themselves in `chat/hub.py:_BACKENDS`
  and expose `HAS_<DEP>` + `INSTALL_HINT`. The aggregator captures
  per-backend exceptions and reports them as status rows, never crashes
  the hub.
- Persona-dependent code paths must honour the
  `DARKCAT_VAULT_PASSPHRASE` env var for encrypted vaults — the TUI /
  GUI thread it through transparently via the `_VaultUnlockMixin`.
- Asset paths (`assets/`, `assets/logos/`) are packaged via
  `pyproject.toml [tool.setuptools.package-data]` — adding a new asset
  type needs that map updated too.

## Tests

Tests live in the sibling top-level `tests/` directory (flat,
`test_*.py`). Each module's behaviour is covered by at least one file:
`test_help_index.py` enforces CLI/REPL parity, `test_chat_hub.py`
covers the multi-protocol aggregator, `test_identity.py` exercises the
vault + launcher, `test_mail.py` covers send / fetch, `test_tui_screens.py`
mounts each TUI screen via the Textual `Pilot` harness.
