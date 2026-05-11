# Identity Generator — frontend parity

The Identity Generator is reachable from all four darkcat surfaces. The
CLI is the source of truth (every action lives in `cmd_identity`); the
other three frontends construct an `argparse.Namespace` and call the
same function, so behaviour stays identical.

## CLI

```sh
darkcat identity providers
darkcat identity new --provider protonmail --purpose research-foo
darkcat identity list --status pending
darkcat identity show <name> --reveal
darkcat identity confirm <name>
darkcat identity burn <name> --note "rate-limited"
darkcat identity launch <name>
darkcat identity launch <name> --capture       # 0.4: capture recovery codes
darkcat identity link <parent> <child>
darkcat identity unlink <parent> <child>
```

See `02-cli-reference.md` for full flags.

## REPL (`darkcat shell`)

Every CLI action has the same name in the REPL:

```
darkcat ▸ identity providers
darkcat ▸ identity new --provider tutanota --purpose foo
darkcat ▸ identity list
darkcat ▸ identity confirm tutanota-quiet_river_4821
```

Tab-completion hooks via `complete_identity` know the action verbs
(`providers`, `new`, `list`, `show`, `confirm`, `burn`, `rotate`,
`link`, `unlink`, `launch`, `delete`). The REPL forwards the tokenised
line through `cli._build_parser()` so flag handling is byte-identical
to a fresh shell invocation.

A note on output: the REPL uses the same Rich console as the CLI, so
colour and table layout match. `--json` output is plain-printed (so
piping inside the REPL still works for inspectors who like to parse).

## TUI (`darkcat tui`)

Press **`i`** at the top level to open the identity vault browser, or
**`p`** to open the mail-provider preset picker (`personas add`)
directly. The vault browser is a modal
`IdentityScreen(ModalScreen[None])` — a `DataTable` with NAME /
PROVIDER / STATUS / PURPOSE / CREATED columns.

| Key       | Action                                                                  |
|-----------|-------------------------------------------------------------------------|
| `n`       | New identity → opens `IdentityNewScreen` (provider / transport / purpose) |
| `l`       | Launch the highlighted row (transport-aware browser spawn)              |
| `s`       | Show the highlighted row, with masked-or-reveal confirmation prompt     |
| `e`       | Edit recovery / handle / email / recovery-codes for the highlighted row |
| `i`       | Link the highlighted row to another persona                             |
| `u`       | Unlink the highlighted row from another persona                         |
| `c`       | Confirm the highlighted row                                             |
| `b`       | Burn the highlighted row                                                |
| `r`       | Refresh                                                                 |
| `Esc`/`q` | Close                                                                   |

Encrypted vaults prompt for the passphrase through `PassphraseScreen`
(a modal `Input(password=True)`). The TUI caches the passphrase for
the rest of the session and threads it through to the CLI handler via
the `DARKCAT_VAULT_PASSPHRASE` env var; the env var is unset again on
modal close. Reveal flows go through `ConfirmRevealScreen` so secrets
are never shown without a deliberate `y` press.

The `Launch` action also chains into an `IdentityEditScreen` after the
result block, so any recovery codes the provider showed during signup
can be captured back into the vault in the same flow as the CLI's
`--capture`.

## GUI (`darkcat gui`)

Menubar:

* **Identity → Open vault…** (accelerator `Ctrl+Shift+I`) — opens the
  vault dialog (`ttk.Treeview` with the same columns as the TUI).
* **Mail → Add mail persona…** — opens the preset-picker dialog (a
  `ttk.Combobox` populated from `mail_providers.all_presets()` plus a
  free-form name entry).

Buttons inside the vault dialog:

* **New** — opens a sub-dialog (provider Combobox, transport Combobox
  [`tor` / `i2p` / `proxy`], purpose Entry).
* **Show** — opens a masked detail dialog with a "Reveal" confirmation
  step before secrets are unmasked.
* **Launch** — runs the same launch flow as the CLI, then opens an
  edit dialog so recovery codes can be captured back.
* **Link** / **Unlink** — opens a target-picker dialog and acts on
  the selected row.
* **Confirm** — acts on the selected row.
* **Burn** — asks for confirmation, then acts on the selected row.
* **Refresh** — re-reads the vault.
* **Close** — dismiss.

Encrypted vaults prompt for the passphrase the first time the dialog
loads (continuation-passing-style: every button funnels through
`_unlock_then(callback)`). The passphrase is cached in a closure-state
dict for the lifetime of the dialog and threaded into
`invoke_cli_capturing` via `DARKCAT_VAULT_PASSPHRASE` (restored to its
prior value with try/finally so the env var doesn't leak).

## Cross-frontend design rules

1. **One driver, four shells.** `cmd_identity` does the vault work;
   REPL/TUI/GUI build a `Namespace` and call it. No business logic
   leaks into the UI layers.
2. **Same defaults everywhere.** `--password-length=24`,
   `--transport=tor`, `--cap=5` apply uniformly.
3. **No silent divergence.** If the TUI/GUI can't expose a flag, it
   stays out — never simulated by a different code path.
4. **Encrypted vaults are first-class in every frontend.** As of 0.4,
   TUI and GUI both prompt for the passphrase through a modal and
   thread it through to the CLI handler via
   `DARKCAT_VAULT_PASSPHRASE`. The CLI is still the only surface that
   accepts the passphrase non-interactively (env var or stdin).
