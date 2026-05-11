# Identity Generator — documentation

Compartmented account creation and management. One persona per project,
manual-assist signup, encrypted vault, no anti-abuse evasion.

## Read order

1. [`01-overview.md`](01-overview.md) — what it is, why, and what it deliberately is **not**.
2. [`02-cli-reference.md`](02-cli-reference.md) — every `darkcat identity` subcommand and flag.
3. [`03-providers.md`](03-providers.md) — the 15 shipped profiles, with an honest no-phone tracker.
4. [`04-transports.md`](04-transports.md) — Tor / I2P / proxy / VPN-pin semantics and tokens.
5. [`05-vault-and-status.md`](05-vault-and-status.md) — schema, status lifecycle, link graph, redaction.
6. [`06-frontend-parity.md`](06-frontend-parity.md) — CLI ↔ REPL ↔ TUI ↔ GUI parity rules.
7. [`07-protonmail-walkthrough.md`](07-protonmail-walkthrough.md) — concrete end-to-end example.

## Building txt / pdf / html

The markdown above is the canonical source. To produce additional
formats, install [pandoc](https://pandoc.org/) (Fedora:
`sudo dnf install pandoc texlive-scheme-medium`; Debian/Ubuntu:
`sudo apt install pandoc texlive-xetex`) and run:

```sh
make -C docs/identity
```

The Makefile writes outputs to `docs/identity/build/{txt,pdf,html}/`
and is idempotent — re-runs only rebuild changed files.

## License

The Identity Generator's source code is **BSD-3-Clause**. This
documentation inherits the project's GPL-3.0-or-later license.
