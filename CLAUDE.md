# darkcat — agent guidance

A multi-protocol darknet / overlay-network crawler. One engine, four
frontends — every user-facing feature must reach all four.

- **CLI** — `darkcat …` (argparse, `src/darkcat/cli.py`)
- **REPL** — `darkcat shell` (`cmd.Cmd`, `src/darkcat/repl.py`)
- **TUI** — `darkcat tui` (Textual, `src/darkcat/tui.py`)
- **GUI** — `darkcat gui` (Tkinter, `src/darkcat/gui.py`)

License: **GPL-3.0-or-later**. Maintainer: Borja Tarraso
&lt;borja.tarraso@member.fsf.org&gt;. Canonical remote:
<https://github.com/borjatarraso/darkcat>.

## Layout

```
src/darkcat/        the package (see src/CLAUDE.md)
tools/              maintainer-only helpers (see tools/CLAUDE.md)
tests/              pytest suite — flat layout, `test_*.py`
docs/               long-form user-facing docs
share/              FreeDesktop entry + hicolor icons
logos/              steg-encoded logo bundle (do not recolour)
README.md           user-facing overview + protocol matrix
pyproject.toml      build + optional-deps map
darkcat             shell launcher (no install required)
```

## Build / test commands

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e .              # core only
pip install -e '.[all]'       # all optional Python deps

python -m pytest -q           # full test suite
python -m pytest -x -q        # stop at first failure
python -m darkcat --about     # smoke check
python -m darkcat doctor      # transport / dep health probe
```

There is no separate lint / format step today.

## Conventions an agent must respect

- **Four-frontend parity.** A feature added to CLI must also land in REPL,
  TUI, and GUI before it's done. The hub (`chat hub`), examples cheatsheet
  (`examples`), and identity flows are the reference pattern.
- **No AI attribution anywhere.** No `Co-Authored-By: Claude` (or any other
  model) in commits, no AI mentions in code comments, docs, or release
  notes. This is enforced by the maintainer — any commit you draft must be
  authored solely by `Borja Tarraso <borja.tarraso@member.fsf.org>`.
- **No auto-commits.** Wait for explicit user approval before
  `git commit` / `git push` / `gh release create`. This includes "looks
  ready, want me to commit?" as a question, not an action.
- **Optional deps are lazily imported inside functions.** Top-level imports
  cover only what `pip install -e .` (core) provides. Textual, Tk, Telethon,
  matrix-nio, slixmpp, websocket-client, fpdf2 etc. are all behind a function-
  local `import` so the CLI works on a stripped install.
- **Don't recolour the steg-encoded logos under `logos/` or `src/darkcat/assets/logos/`.**
  They carry steganographic payloads — a colour shift breaks the bundle.
- **License headers follow the neighbour file.** Where an SPDX header
  is present, `src/darkcat/` uses `GPL-3.0-or-later`; `tests/` and
  `tools/` use `BSD-3-Clause`. Many older runtime modules carry only a
  docstring — don't retrofit headers on existing files unless asked.
- **Comments are terse.** Default to none; only add when the *why* is
  non-obvious. Never narrate what the code does.

## Where the engine lives

`src/darkcat/` has a flat module layout — each module owns one concern
(`crawler.py`, `fetcher.py`, `extractor.py`, `storage.py`, etc.). The
two subpackages are `chat/` (per-protocol messenger backends + the
multi-protocol hub aggregator) and `identity/` (persona vault, signup
generator, transport-routed launcher). See `src/CLAUDE.md` for the full
module map.

<!-- LYNX-EP-NOTE:BEGIN -->

## Entry-point card — keep it current

This project carries `index.ep.md` (and `index.ep.html`), the standard card
that answers what this is, where to look first, and how to run it. Every
project in `~/claude/` has one in the same shape, so jumping between them
does not mean re-learning where to look.

**When work here changes any of the following, refresh the card:**

- what the project is or does (title, one-line purpose, description)
- the file someone should open first
- the command that starts it
- the top-level layout or where the documentation lives

Refresh it with:

```bash
python3 ~/claude/lynx_factory/web/tools/gen_ep_index.py --only <this-project>
```

That regenerates from this repo's own README/CLAUDE.md plus the Lynx Factory
ledger — it does not invent anything, so fixing the card usually means fixing
the README first. The README's ownership footer is refreshed by the same
command.

To hand-write a card and stop it being regenerated, set `ep_locked: true` in
its front matter.

<!-- LYNX-EP-NOTE:END -->
