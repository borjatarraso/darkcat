# Identity Generator — overview

The **Identity Generator** is darkcat's fourth working surface. The first
three (CLI, REPL, TUI, GUI) all crawl, fetch, and search content. This
one *creates and manages the accounts* you use to read or post on the
content side — one persona at a time, kept in the same encrypted vault
that backs `darkcat personas`.

## Why this exists

If you do research, journalism, or OSINT across forums, mailboxes, and
chat networks, you eventually want **one account per project**. Reusing
a single ProtonMail address across five unrelated investigations lets
the operator on the other side connect dots that should stay
unconnected. The Identity Generator builds compartmented accounts with:

* a fresh handle, password, display name, locale, timezone, birthdate,
  and bio per persona,
* a chosen anonymising **transport** (Tor / I2P / SOCKS proxy / pinned
  VPN egress) recorded next to the persona so future fetches reuse the
  same network path,
* a `purpose_tag` so the operator remembers *why* this identity exists,
* a `status` lifecycle (`pending → confirmed → burned`) and a soft
  per-provider cap so the vault never quietly grows into a spam farm.

## What it is *not*

This is a **manual-assist** workflow. Darkcat opens the signup page
through the chosen transport and pre-fills clipboard / form data; **you**
solve the captcha, accept the ToS, and confirm the email. The tool
deliberately ships none of:

* phone-verification bypass (no SMS receivers, no SIM-rental APIs),
* JA3 / TLS fingerprint rotation,
* mass-creation orchestration,
* any form of CAPTCHA solver, paid or otherwise.

Those features cross into anti-abuse evasion. Darkcat's job stops at
"open the signup page through Tor with a freshly generated identity in
hand."

## Scope: 15 shipped providers

| Family   | Providers                                            |
|----------|------------------------------------------------------|
| Email    | ProtonMail, Tutanota, Mailfence, Disroot             |
| Webmail  | Gmail, Outlook, Yahoo                                |
| VPN      | ProtonVPN, TunnelBear, Windscribe                    |
| Social   | Reddit, X/Twitter, Telegram, Discord, Mastodon       |

Each profile records the signup URL, recommended transport, the
documented **no-phone path** (where one exists — for some providers it
is "there is no path; phone is mandatory"), required fields, and a ToS
warning. Run `darkcat identity providers` to see the live list and
`darkcat identity providers <slug>` for details.

## Soft per-provider cap

The default cap is **5 active personas per provider** (`pending +
confirmed`). `burned` and `locked` slots do **not** count, so rotating
out a stale persona frees a slot. The cap is a guardrail, not a wall —
`identity new --force` bypasses it. Override with `identity new --cap N`
or accept the default.

## Where the data lives

* Vault: `~/.darkcat/personas.json` (or `.gpg` if encrypted) — the same
  file `darkcat personas` uses. Identity rows carry extra fields
  (`provider`, `category`, `status`, `purpose_tag`, `display_name`,
  `birthdate`, `locale`, `timezone`, `bio`, `transport_used`,
  `recovery_email`, `recovery_codes`, `linked_identities`, …). Old
  persona rows without a `provider` stay invisible to `identity list`
  and don't count against caps.
* Cookie jars: `~/.darkcat/cookies/<persona>.txt` (per-persona, isolated).
* No telemetry, no remote calls outside the chosen transport.

## License

The Identity Generator source files are **BSD-3-Clause**. See each
module's SPDX header.
