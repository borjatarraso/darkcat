# Identity Generator — CLI reference

All commands sit under `darkcat identity`. The vault is `~/.darkcat/
personas.json` — encrypted variants (`.gpg`) prompt for a passphrase
once per command (or read it from `DARKCAT_VAULT_PASSPHRASE`).

## Global

```
darkcat identity <action> [options]
```

Actions:

| Action       | Purpose                                                  |
|--------------|----------------------------------------------------------|
| `providers`  | List or describe shipped provider profiles               |
| `new`        | Generate a new persona for a provider                    |
| `list`       | Filter / show personas (no secrets)                      |
| `show`       | Show one persona, with `--reveal` for secrets            |
| `confirm`    | Mark a persona as `confirmed` (account is live)          |
| `burn`       | Mark a persona as `burned` (slot frees)                  |
| `rotate`     | Rotate the password for an existing persona              |
| `link`       | Record that one persona depends on another (graph edge)  |
| `unlink`     | Remove a link edge                                       |
| `launch`     | Open signup URL through the persona's transport          |
| `delete`     | Remove a persona row entirely (use rarely; prefer burn)  |

## `identity providers`

```
darkcat identity providers [--category EMAIL|WEBMAIL|VPN|SOCIAL]
                           [SLUG] [--json]
```

* No arguments → table of all 15 profiles.
* `SLUG` → full detail page for one profile (signup URL, fields,
  no-phone path, ToS warning, available instances).
* `--json` → machine-readable dump.

## `identity new`

```
darkcat identity new --provider PROTONMAIL [options]
```

| Flag                       | Default          | Purpose                                              |
|----------------------------|------------------|------------------------------------------------------|
| `--provider SLUG`          | (required)       | Profile slug (`darkcat identity providers` lists them) |
| `--instance KEY`           | profile default  | For Mastodon/etc. — pick a documented instance       |
| `--name NAME`              | `<slug>-<handle>`| Persona key in the vault                             |
| `--purpose TEXT`           | `None`           | Free-form `purpose_tag`                              |
| `--transport tor\|i2p\|proxy\|vpn-pin` | `tor`  | Anonymising network for this persona                |
| `--proxy-url URL`          | `None`           | Required if `--transport proxy`                      |
| `--pin-to TARGET`          | `None`           | Required if `--transport vpn-pin` (advisory only — see Caveats) |
| `--password-length N`      | `24`             | URL-safe password length (min 16)                    |
| `--recovery-email ADDR`    | `None`           | Recorded for ProtonMail-style recovery flows         |
| `--cap N`                  | `5`              | Override per-provider cap for this command           |
| `--force`                  | off              | Bypass cap                                           |
| `--launch`                 | off              | Open signup URL after creating (see `identity launch`) |
| `--json`                   | off              | Emit a JSON record (password is **revealed once**)   |

The persona is generated **before** any network call; you can `--force`
the cap, change your mind, and `identity delete` without ever opening a
browser.

## `identity list`

```
darkcat identity list [--provider SLUG] [--category CAT]
                      [--status pending|confirmed|burned|locked]
                      [--purpose SUBSTRING] [--json]
```

Returns a table of NAME / PROVIDER / CATEGORY / STATUS / PURPOSE /
TRANSPORT / CREATED. Legacy persona rows without a provider stay
hidden.

## `identity show <name>`

```
darkcat identity show <name> [--reveal] [--json]
```

By default, secrets are masked (`password`, `recovery`, every entry of
`recovery_codes`). `--reveal` prompts interactively unless
`DARKCAT_VAULT_PASSPHRASE` is set, then dumps cleartext.

## `identity confirm <name>` / `identity burn <name> [--note TEXT]`

Status transitions. `confirm` is idempotent. `burn` records the
operator's note in `notes` and stamps `burned_at`. A burned slot is
free for the cap counter.

## `identity rotate <name>`

```
darkcat identity rotate <name> [--password STRING | --length N]
```

Overwrites `password`. Default length stays 24.

## `identity link <parent> <child>` / `identity unlink <parent> <child>`

Records a directed edge in `child.linked_identities`. Self-loops are
rejected. `unlink` returns 0 if the edge existed, 1 if it didn't.

## `identity launch <name>`

```
darkcat identity launch <name> [--no-spawn] [--capture]
```

Opens the persona's signup URL through the recorded transport. Strategy:

1. If `tor-browser-launcher` (or `tor-browser`) is on `$PATH` and
   transport is `tor`, spawn it.
2. Otherwise set `HTTPS_PROXY`/`HTTP_PROXY` env vars and call
   `xdg-open` (Linux) / `open` (macOS) / `start` (Windows).
3. If neither works, print the URL plus a copy-paste block (handle,
   password, display name, locale, transport string).

`--no-spawn` forces step 3 — useful when running on a remote / headless
host.

`--capture` (0.4+) prompts interactively for fields the provider showed
during signup that the persona doesn't yet record: real handle (if the
provider rewrote it), email address, recovery email, recovery secret,
and one-line recovery codes. Each prompt is skipped if the operator
hits Enter, so partial capture is fine. The prompts are gated on
`sys.stdin.isatty()` so non-interactive shells are a no-op; the TUI
and GUI launch flows chain the same edit dialog automatically after
the result block, regardless of `--capture`.

## Caveats

* **`vpn-pin` is advisory.** Darkcat does not bring up VPN tunnels;
  pinning records the target and trusts the operator to route through
  it. `proxies_for(cfg)` raises `NotImplementedError` for this kind so
  fetchers don't accidentally treat the pin as live SOCKS.
* **Encrypted vaults need a passphrase per command.** Use
  `DARKCAT_VAULT_PASSPHRASE=…` for batch flows; never store it on disk
  in cleartext.
* **`identity new` reveals the password once.** `redact_dict` masks it
  on every subsequent `show` unless `--reveal` is set.
