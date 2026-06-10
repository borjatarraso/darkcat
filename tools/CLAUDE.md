# tools/ — maintainer-only helpers

Out-of-band scripts the maintainer runs by hand. Not shipped with the
package, not part of any user-facing flow, not on the import path.
Each script is self-contained — it pulls its own deps and is invoked
directly via `python tools/<name>.py`.

## Contents

- **`render_instructions_pdf.py`** — render `instructions.txt` to
  `instructions.pdf` using `fpdf2`. A4 portrait, 9pt monospaced,
  Unicode-capable TTF auto-picked from common system fonts (DejaVu Sans
  Mono, JetBrains Mono, Cascadia Mono, …). The text file is the source
  of truth; the PDF is committed for read-only distribution and
  regenerated whenever the txt changes.

  Usage:
  ```sh
  python tools/render_instructions_pdf.py
  python tools/render_instructions_pdf.py path/in.txt path/out.pdf
  ```

  Deps: `pip install fpdf2`. Not in `pyproject.toml` — this is a
  maintainer-only tool.

## Public interface

None. These scripts are not importable as a module and have no
backwards-compatibility guarantees — they can be edited freely as the
maintenance workflow evolves.

## Module-local conventions

- **SPDX header is `BSD-3-Clause`**, not `GPL-3.0-or-later`, matching
  the existing pattern. These are maintenance utilities, intentionally
  permissively-licensed so others can lift them.
- **Scripts are self-contained.** Each one declares the deps it needs
  inline (or in a comment at the top), so the maintainer can run it
  without polluting the runtime virtualenv.
- **No imports from `darkcat.*`.** These scripts must work even when
  the package is not installed — they're tooling around the source
  tree, not consumers of the engine.
- **Output paths default to repo-root-relative.** Most scripts accept
  positional `in / out` overrides; the no-arg form should target the
  canonical paths (`./instructions.txt` → `./instructions.pdf`).
