# Identity Generator — vault, schema, status lifecycle

## Storage

Identity rows live in the same persona vault as `darkcat personas`:

* Plain mode: `~/.darkcat/personas.json`.
* Encrypted mode: `~/.darkcat/personas.json.gpg` — symmetric AES256
  via `gpg --symmetric`, passphrase prompted at every command (or
  read from `DARKCAT_VAULT_PASSPHRASE`).

`VAULT_VERSION` is **2**: schema migrations leave older rows untouched
and just drop unknown keys at load time, so a 0.2-era vault opens
cleanly in 0.3 and 0.4.

## Persona schema (identity-relevant fields)

| Field                  | Type                | Notes                                                       |
|------------------------|---------------------|-------------------------------------------------------------|
| `name`                 | str (key)           | Unique per vault. Defaults to `<slug>-<handle>`.            |
| `provider`             | str?                | Profile slug (`protonmail`, `mastodon`, …). `None` = legacy persona. |
| `category`             | str?                | `email` / `webmail` / `vpn` / `social`.                     |
| `status`               | str                 | `pending`, `confirmed`, `burned`, `locked`.                 |
| `purpose_tag`          | str?                | Free-form, your choice.                                     |
| `network_or_domain`    | str?                | Mirrors the profile (or instance) for fast lookup.          |
| `transport_used`       | str?                | `kind:token`, see *transports*.                             |
| `handle`               | str                 | `<word>_<word>_<4-digits>`.                                 |
| `password`             | str                 | URL-safe, ≥ 16 chars (default 24). Masked unless `--reveal`. |
| `display_name`         | str?                | Two ASCII words.                                            |
| `birthdate`            | str?                | ISO `YYYY-MM-DD`. Default age range 22–55.                  |
| `locale`               | str?                | e.g. `en_US`, `fr_FR`.                                      |
| `timezone`             | str?                | IANA, paired with locale.                                   |
| `bio`                  | str?                | Three-segment bio with `•` / `\|` / `, ` / `—` connectors.    |
| `recovery_email`       | str?                | Recorded if you set `--recovery-email`.                     |
| `recovery_codes`       | list[str]           | Set with `identity show … --reveal` output, masked otherwise. |
| `linked_identities`    | list[str]           | Names this persona depends on (parent → child as a directed edge). |
| `confirmed_at`         | float?              | Unix timestamp set by `identity confirm`.                   |
| `burned_at`            | float?              | Unix timestamp set by `identity burn`.                      |
| `created_at`           | float               | Unix timestamp at `add()`.                                  |
| `notes`                | str?                | `identity burn --note` appends here.                        |

Legacy persona rows (created by 0.2's `darkcat personas add` and never
upgraded) have no `provider` field; `IdentityVault.all_identities()`
filters them out so they don't pollute the table or the cap counters.

## Status lifecycle

```
   identity new          identity confirm        identity burn
       │                        │                       │
       ▼                        ▼                       ▼
   pending  ─────────────►  confirmed  ─────────────►  burned
                                                        ▲
   identity new --force                                 │
       (over cap)                                       │
       │                                                │
       └────────────►  pending (over cap, allowed)  ────┘

   locked = manual / ops-side flag (rarely used)
```

Rules:

* `confirm()` is idempotent — calling it twice is a no-op.
* `confirm()` raises `ValueError` if the persona is already burned.
* `burn(name, note=None)` sets `status=burned`, stamps `burned_at`,
  and appends `note` to `notes`. The slot stops counting against the
  cap.
* `IdentityVault.per_provider_count(slug, active_only=True)` is the
  function the cap consults. `active_only=True` excludes `burned` and
  `locked`.

## Per-provider cap

`DEFAULT_PER_PROVIDER_CAP = 5`. Override with:

* `IdentityVault(inner, per_provider_cap=N)` programmatically,
* `darkcat identity new --cap N` for a single command,
* `darkcat identity new --force` to skip the cap entirely.

A cap breach raises `PerProviderCapExceeded`, which the CLI translates
to a human error and a non-zero exit. `--force` doesn't lower the cap
on subsequent commands; it just bypasses for that call.

## Link graph

`identity link <parent> <child>` adds `parent` to `child.linked_identities`.
The graph is **directed** (the edge is stored on the child only) and
self-loops are rejected. Use it to model:

* "this Mastodon persona uses this ProtonMail address for recovery"
  (`link protonmail-x mastodon-y`),
* "this Discord account is owned by this Reddit account"
  (`link reddit-x discord-y`),
* "this VPN account funds these social accounts"
  (`link protonvpn-x reddit-y; link protonvpn-x discord-y`).

`identity unlink` returns 1 if the edge didn't exist (callers can
script around it without try/except).

## Redaction

`personas.redact_dict(p, reveal=False)` replaces:

* `password` → `******<last 4 chars>`,
* `recovery` → same,
* every entry of `recovery_codes` → same.

`reveal=True` returns the cleartext fields. `identity show --reveal`
prompts interactively before flipping the flag, unless
`DARKCAT_VAULT_PASSPHRASE` is set (in which case the operator already
demonstrated they own the vault).

## Tests

`tests/test_identity.py` covers:

* legacy-persona invisibility,
* per-provider cap blocks at N+1, `--force` bypasses,
* burned slot frees a cap slot,
* status transitions (`pending → confirmed → burned`),
* `confirm` rejects burned,
* directional link graph + self-loop rejection (incl. CLI `link` /
  `unlink` round-trip and unknown-persona errors),
* password rotation overwrites,
* `recovery_codes` masked by default, revealed on `reveal=True`,
* `identity show` masked vs `--reveal`,
* `identity launch --no-spawn` and unknown-persona errors,
* `identity launch --capture` writes captured fields back to the vault
  (and is a no-op when stdin is not a tty),
* `personas add` preset routing through `invoke_cli_capturing`.
