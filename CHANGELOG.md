# Changelog

All notable changes to **darkcat** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] — 2026-05-11

The 0.4 cycle finishes the four-frontend parity story for the Identity
Generator: TUI and GUI now match what the CLI can do, including
encrypted-vault unlock, recovery-code capture after signup, and the
mail-provider preset picker.

### Added

#### Identity Generator — frontend parity

- **TUI vault browser** (`darkcat tui` → `i`) gains the actions the CLI
  has had since 0.3: `s` show (with masked / reveal confirmation), `e`
  edit, `i` link, `u` unlink, `l` launch. The `n` (new), `c` (confirm),
  `b` (burn), `r` (refresh), `Esc`/`q` (close) bindings remain.
- **TUI passphrase prompt** (`PassphraseScreen`) opens automatically
  when the dialog hits an encrypted vault. The passphrase is cached
  for the session and threaded into the CLI handler via
  `DARKCAT_VAULT_PASSPHRASE`.
- **TUI reveal confirmation** (`ConfirmRevealScreen`) so secrets are
  never shown without an explicit `y` press.
- **Top-level `p` binding** in the TUI opens the mail-provider preset
  picker (`PersonaAddScreen`) directly, mirroring
  `Mail → Add mail persona…` in the GUI.
- **GUI parity surface** (`darkcat gui` → `Identity → Open vault…`):
  Show / Link / Unlink buttons, transport-aware Launch that chains an
  edit dialog for post-signup recovery-code capture, passphrase prompt
  on dialog open, and a mail-provider preset picker dialog under
  `Mail → Add mail persona…`.
- **`darkcat identity launch --capture`** prompts interactively for
  fields the provider revealed during signup (real handle, email,
  recovery email, recovery secret, recovery codes) and writes them
  back to the vault. The TUI and GUI launch flows chain the same
  edit dialog automatically. All prompts are skippable; the CLI form
  is gated on `sys.stdin.isatty()`.
- **`darkcat doctor` mail-host probe** walks the plaintext vault and
  opens a 2-second TCP connection to each persona's SMTP and IMAP
  host:port. Encrypted vaults are reported as `warn` with a decrypt
  hint; empty vaults show the available preset slugs as `info`. The
  loopback Bridge ports (1025) are skipped to avoid false positives
  when Proton Bridge isn't running.

#### Mail integration

- New `darkcat mail` console for outbound (SMTP) and inbound (IMAP) on
  any persona whose `site` field carries `host[:port]`. Proton Bridge,
  Disroot, Tutanota, Mailfence and any plain SMTP target all share the
  same code path.
- `darkcat personas add` accepts a `--preset` flag populated from
  `mail_providers.all_presets()` (so the picker dialogs in TUI/GUI and
  the CLI share one source of truth).

#### Chat additions

- Session, Simplex, and Telegram chat backends gain the per-persona
  isolation hooks the rest of the chat surface already had.

#### Tests

- 8 Pilot-driven TUI screen tests (`tests/test_tui_screens.py`)
  covering `ResultScreen`, `PassphraseScreen`, `ConfirmRevealScreen`,
  `LinkScreen`, `PersonaAddScreen`.
- Identity test count grows to 49 with coverage for `show` masked vs
  reveal, link / unlink round-trip, launch `--no-spawn` / unknown
  persona, `personas add` preset routing, and the `--capture` write-
  back loop (TTY and non-TTY paths).
- 4 mail-host doctor tests in `tests/test_ux_polish.py`: empty vault
  info row, SMTP + IMAP probes both fire, refused → warn, encrypted
  vault → warn-skip.
- Full test suite passes at 138 tests.

#### Tooling / docs

- `tools/render_instructions_pdf.py` regenerates `instructions.pdf`
  from `instructions.txt`.
- `docs/identity/` updated for the new TUI bindings and the
  encrypted-vault parity work; cross-frontend rule #4 is rewritten
  ("encrypted vaults are first-class in every frontend").
- `docs/identity/02-cli-reference.md` documents
  `identity launch --capture`.

### Changed

- `IdentityVault` rows opened by 0.2 still load cleanly in 0.4 — the
  schema-version-2 migration drops unknown keys at load time.
- `invoke_cli_capturing` now routes `cmd=personas` through
  `cmd_personas`, so the GUI / TUI preset picker can call the CLI
  with the same `Namespace` shape every other frontend uses.

### Fixed

- Initial Pilot tests for `PassphraseScreen` and `LinkScreen` fired
  `Enter` against focused widgets that swallowed the key event; tests
  now drive `pilot.click("#submit")` / `#cancel` to fire the screen-
  level binding deterministically.

### Notes

- The Identity Generator's source files (under `src/darkcat/identity/`)
  remain **BSD-3-Clause**; the rest of darkcat is **GPL-3.0-or-later**.
  Each module carries an SPDX header.
- No telemetry, no network calls outside the persona's transport.

## [0.3.0] — earlier in the 0.4 cycle

- Tkinter GUI (`darkcat gui`) mirroring the TUI surface.
- `cmd.Cmd` REPL (`darkcat shell`) wrapping the CLI commands.
- `darkcat doctor` first-run wizard.
- `src/` package layout.

## [0.2.0] — initial release

- Multi-protocol darknet & overlay crawler (Tor, I2P, IPFS, Freenet,
  Lokinet, GNUnet, ZeroNet, Gemini, Gopher, Hyper, Yggdrasil, cjdns,
  Namecoin, ENS, Handshake, OpenNIC).
- Topic-keyword scoring, BFS frontier, SQLite + FTS5 store.
- Textual TUI (`darkcat tui`) with status bar, crawl form, log pane,
  results table, search box.
- Leak / credential scanner, watchlist + alerting, IOC export
  (JSONL / STIX 2.1 / MISP), HIBP-style hash-prefix server.
- PGP key harvest, ZeroNet content.json walker, Tor control-port
  helper (`tor newnym` / `tor bridges` / `tor info`).
