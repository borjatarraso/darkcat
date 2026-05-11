# Identity Generator — ProtonMail walkthrough

End-to-end example. ProtonMail is the simplest path: fully no-phone via
the onion site, free tier, supports Tor egress without much friction.

Time budget: ~10 minutes from `darkcat identity new` to a verified
inbox you can reuse for the next 18 months.

## 0. Pre-flight

```sh
# Tor must be reachable (default 127.0.0.1:9050).
darkcat status | grep -i tor

# Check the provider profile so you know what to expect.
darkcat identity providers protonmail
```

That last command prints (abridged):

```
slug              protonmail
display_name      ProtonMail
category          email
signup_url        https://account.proton.me/signup
network_or_domain mail.proton.me
transport         tor
fields
  • handle       ← generated (required)
  • password     ← generated (required)
  • display_name ← generated (optional) — shown to recipients
no_phone_path
  Use the onion (protonmailrmez3lotccipshtkleegetolb73fuirgj7r4o4vfu7ozyd.onion)
  and select the email-only verification path. Phone is offered, never required.
tos_warning
  No automated/mass account creation. Read the ToS — Proton enforces.
```

## 1. Generate the persona

```sh
darkcat identity new \
        --provider protonmail \
        --transport tor \
        --purpose "research / forum-x"
```

Output:

```
+ identity protonmail-quiet_river_4821 created (protonmail/email)
  handle        quiet_river_4821
  password      8x2-fJW9_zT…vGqM   (shown once — store now)
  display_name  Mira Holt
  locale/tz     en_US / America/New_York
  birthdate     1991-07-14
  bio           security & privacy • EU-based, mostly evenings — no DMs
  transport     tor (auth=4f2a91e1c8b3d7a0)
  signup_url    https://account.proton.me/signup

No-phone path:
  Use the onion (protonmailrmez3lotccipshtkleegetolb73fuirgj7r4o4vfu7ozyd.onion)
  and select the email-only verification path. Phone is offered, never required.

ToS: No automated/mass account creation. Read the ToS — Proton enforces.

Status: pending — run `darkcat identity confirm protonmail-quiet_river_4821`
once the account is live.
```

**Save the password now.** It will be masked on every subsequent
`identity show` unless you pass `--reveal`.

## 2. Open the signup page

```sh
darkcat identity launch protonmail-quiet_river_4821
```

What happens, in order of preference:

1. If `tor-browser-launcher` is on `$PATH` → spawns Tor Browser
   pointed at the onion URL.
2. Otherwise → sets `HTTPS_PROXY=socks5h://127.0.0.1:9050`,
   `HTTP_PROXY=…`, calls `xdg-open` (Linux) / `open` (macOS) /
   `start` (Windows).
3. Otherwise → prints a copy-paste block:

   ```
   --- manual signup ---
   provider:    protonmail
   url:         https://protonmailrmez3lotccipshtkleegetolb73fuirgj7r4o4vfu7ozyd.onion/signup
   transport:   tor (auth=4f2a91e1c8b3d7a0)
   handle:      quiet_river_4821
   password:    8x2-fJW9_zT…vGqM
   display:     Mira Holt
   locale:      en_US (America/New_York)
   birthdate:   1991-07-14
   bio:         security & privacy • EU-based, mostly evenings — no DMs
   no-phone:    Use the onion … (full text from profile)
   tos:         …
   ```

Pass `--no-spawn` if you want to force step 3 (e.g. on a headless host).

## 3. Solve the captcha and verify

This is the manual part. In the browser:

1. Username: `quiet_river_4821`
2. Password: paste from the output
3. Verification: pick **email** (not phone). Use a throwaway address
   you control or a recovery email you've already burned for this
   project. Proton will send a 6-digit code.
4. Solve the human-verification CAPTCHA.
5. Display name: `Mira Holt` (or whatever the generator chose). Yes,
   it matters — recipients see this.
6. Sign in once to confirm.

## 4. Mark it confirmed

```sh
darkcat identity confirm protonmail-quiet_river_4821
```

This stamps `confirmed_at` and frees the cap counter from caring about
it (it still counts as one of the 5 active slots; only `burn` releases
the slot entirely).

## 5. Use it

The persona's cookie jar is already wired:

```sh
darkcat fetch https://protonmail.com/inbox \
        --persona protonmail-quiet_river_4821
```

`darkcat` uses the recorded transport and the persona's cookie jar so
all subsequent fetches stay on the same Tor circuit (per
`IsolateSOCKSAuth`).

## 6. Optional: link to a recovery account

If you also create a Tutanota persona for *out-of-band* recovery:

```sh
darkcat identity new --provider tutanota \
                     --purpose "recovery for protonmail-quiet_river_4821"
darkcat identity link tutanota-<...> protonmail-quiet_river_4821
```

Now `identity show protonmail-quiet_river_4821` shows the linked
recovery account in `linked_identities`.

## 7. Burn it when done

```sh
darkcat identity burn protonmail-quiet_river_4821 \
        --note "project closed 2027-02; last login 2027-01-30"
```

The slot is now free. The row stays in the vault for audit; nothing is
deleted. Use `identity delete` only if you're certain you want the row
gone permanently — there is no undo.

## Common errors

| Error                                    | Cause                                          | Fix                                              |
|------------------------------------------|------------------------------------------------|--------------------------------------------------|
| `ERROR: persona named '…' already exists`| `--name` collision                             | Pass a different `--name`, or remove the old row |
| `ERROR: per-provider cap exceeded`       | 5 active personas already on this provider     | `burn` an old one, or pass `--force`             |
| `tor-browser not found, falling back to xdg-open` | No Tor Browser on PATH                | Install it, or accept the system-browser route   |
| Proton says "this email could not be verified" | Tor exit on Proton's blocklist           | Retry — Tor circuit changes are free; or use the onion URL directly |
