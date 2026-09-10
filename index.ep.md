---
ep_version: 1
project: darkcat
title: Darkcat
status: PAUSED
last_touched: 2026-06-10
last_touched_text: 10 June 2026
section: top
category: security
generated: 2026-09-08
ep_locked: false   # set true and this file is never regenerated
---

# Darkcat

> Dark-web gateway tools

🟠 **PAUSED** · last touched **10 June 2026** (last commit to project files)

---

## What this is

**Maintainer:** Overdrive (Borja Tarraso) &lt;borja.tarraso@member.fsf.org&gt; **License:** GPL-3.0-or-later **Source:** <https://github.com/borjatarraso/darkcat>

A crawler for darknets and obscure overlay networks. It classifies every URL by protocol, routes it through the right transport, crawls BFS from seed lists with topic-keyword scoring, and stores everything in SQLite (FTS5). Ships in four flavours over the same engine:

- **CLI** — `darkcat …` (one-shot subcommands)
- **Shell / REPL** — `darkcat shell` (interactive line editor)
- **TUI** — `darkcat tui` (Textual full-screen terminal app)
- **GUI** — `darkcat gui` (Tkinter desktop window)

Run `darkcat --about` for a one-line summary, `darkcat -h` for the full reference, or `darkcat -la` to discover curated entry points across every supported protocol.

Use this for security research, journalism, OSINT, accessing censorship-resistant content, or interop testing. You are responsible for what you fetch and where you point it. Don't use it to break laws.

`darkcat status` reports which transports are reachable on this machine.

Or, without installing — use the bundled launcher (auto-detects `.venv/`, falls back to system `python3`):

A FreeDesktop entry and hicolor icons live under `share/`. Install them into your prefix to get a "Darkcat" launcher in the application menu and correct icons in the GUI's title bar / taskbar:

System-wide packagers can drop the same trees under `/usr/share/`.

Darkcat soft-imports [`argcomplete`](https://kislyuk.github.io/argcomplete/) to power tab-completion of subcommands and flags. Install it (it's a no-op for runtime if you never enable completion):

Then, for the current shell:

Add the line to your shell's rc file to make it permanent.

Gemini and Gopher need no daemon — Darkcat speaks them natively over a socket.

`darkcat -h` shows a clean help screen with the full protocol table, every subcommand, and example invocations. Highlights:

Pattern-based detection of credential dumps, API keys, private keys, credit cards, BIP-39 seed phrases, SQL dumps, and breach-marker keywords in already-crawled pages. Findings store a salted SHA-256 of each secret plus a redacted preview — never the raw secret.

Categories: `email_password`, `aws_access_key`, `aws_secret_key`, `github_token`, `slack_token`, `stripe_key`, `google_api_key`, `discord_token`, `jwt`, `private_key`, `pgp_block`, `credit_card`, `sql_dump`, `seed_phrase`, `breach_marker`.

The intent is detection — surfacing where leaks appear so defenders / threat-intel teams can monitor and respond. Storage is hashed + redacted by design; the digest column lets you correlate against IOC feeds without re-identifying anyone.

Register patterns; when a *new* finding matches, the configured sink fires and an `alerts` row is recorded.

Sinks: `log` (stdout) · `notify` (libnotify desktop notification via `notify-send`) · `file:PATH` (append one JSON object per alert) · `webhook:URL` (HTTP POST a JSON payload).

`record_page` snapshots `(url, content_hash, title, text, captured_at)` into a `page_history` table on every fetch where the text has changed. Use this to surface ransomware-leak-site updates, market re-listings, etc.

Emit findings as a hash-based IOC feed for SOC/TIP integration. Only the SHA-256 digest goes out — never the underlying secret.

## Start here

- [`README.md`](README.md) — what the project is, in its own words
- [`CLAUDE.md`](CLAUDE.md) — working agreement for a session in this repo

## Run it

```bash
cd ~/devel/darkcat
./run                                 # project runner
darkcat                               # console entry point
python3 -m darkcat                    # runnable package
```

## The rest of it

**Directories**

- `docs/` — 6 entries
- `logos/` — 5 entries
- `share/` — 2 entries
- `src/` — 3 entries
- `tests/` — 9 entries
- `tools/` — 2 entries

**Other documentation**

- [`CHANGELOG.md`](CHANGELOG.md)

**`docs/`** holds 14 files.

**Build / config**: `pyproject.toml`

---

## Ownership

<img src="https://www.cortex-university.com/static/brand/lince-logo.png" alt="Lince" width="96" height="96" align="left" style="margin-right:16px" />

**Darkcat is proudly part of Lince.**

| Company ID | Headquarters |
|---|---|
| 3015071-2 | Helsinki, Finland |

Part of the LINCE company · © All rights reserved


<sub>Standard entry-point card (`index.ep.md`, format v1) — generated 2026-09-08 by Lynx Factory. Regenerating overwrites this file unless `ep_locked: true`.</sub>
