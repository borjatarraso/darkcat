# Identity Generator — provider catalogue

15 profiles ship in `darkcat.identity.providers`. They are loaded the
first time `identity providers` runs (`pkgutil.iter_modules` over the
package, then `register()` per module). Each profile records:

* `slug` (lowercase identifier, used everywhere — e.g. `protonmail`),
* `display_name`, `category` (`email`, `webmail`, `vpn`, `social`),
* `signup_url` and `network_or_domain`,
* `fields` (what the operator must supply, what the generator supplies),
* `no_phone_path` (honest description of whether/how to skip phone),
* `transport_recommendation` (`tor`, `i2p`, `proxy`, `vpn-pin`),
* `instances` (Mastodon-style federated lists where relevant),
* `tos_warning` (one sentence — read it before agreeing),
* `notes` (free-form caveats).

## Email — privacy-leaning

| Slug         | Network    | Phone? | Transport | Notes                                                         |
|--------------|------------|--------|-----------|---------------------------------------------------------------|
| `protonmail` | mail.proton.me | optional through Tor onion (`protonmailrmez3lotccipshtkleegetolb73fuirgj7r4o4vfu7ozyd.onion`) | `tor` | Sometimes asks for human-verification (CAPTCHA / email / phone). Use the onion for least friction. |
| `tutanota`   | tuta.com   | not required | `tor` | Cleartext-CAPTCHA-only at signup as of writing. ToS forbids automated/mass account creation — abide. |
| `mailfence`  | mailfence.com | optional | `tor` | Belgian provider; signup is HTML-only, captcha-driven, EUR-priced for paid tiers. |
| `disroot`    | disroot.org | not required | `tor` | Activist co-op; manual approval flow — expect 24–48h delay. Read their TOS, they take it seriously. |

## Webmail — mainstream

These three demand phone numbers in many regions. Darkcat does **not**
help bypass that. The profile records what we know; the operator
decides whether to proceed.

| Slug      | Phone?                                | Transport          | Notes |
|-----------|---------------------------------------|--------------------|-------|
| `gmail`   | almost always required                | `vpn-pin` recommended; Tor often blocked | Google fingerprints heavily. Account creation through Tor exit IPs is usually rejected outright. |
| `outlook` | usually required, sometimes skippable on a residential IP | `vpn-pin` | Microsoft accepts more transports than Google but still blocks Tor exits frequently. |
| `yahoo`   | required in most regions               | `vpn-pin`          | Aol/Yahoo Mail paths converge on the same form. |

## VPN

| Slug          | Free tier? | No-phone path | Notes |
|---------------|------------|---------------|-------|
| `protonvpn`   | yes        | email only    | Works with the onion. Free tier is unlimited but bandwidth-throttled. |
| `tunnelbear`  | yes (500MB/mo) | email only | Account creation is straightforward; payment flows are more aggressive. |
| `windscribe`  | yes (10GB/mo) | email only | Supports voucher codes. CLI client is open-source. |

## Social

| Slug       | Phone?     | Transport recommendation | Notes |
|------------|------------|--------------------------|-------|
| `reddit`   | optional in most regions | `tor` | New accounts via Tor exit are rate-limited. Old.reddit signup is plainer. |
| `twitter`  | almost always required | `vpn-pin` | X aggressively phone-gates. Existing accounts sometimes survive Tor; new ones rarely. |
| `telegram` | **required** (number is the account) | `vpn-pin` | The phone number *is* your identity. There is no no-phone path. |
| `discord`  | optional at signup; required after first flag | `vpn-pin` | Account is unusable until email-verified; phone challenges hit fast. |
| `mastodon` | not required (depends on instance policy) | `tor` | Federated — pick an instance that fits your project. Profile carries `instances` list. |

### Mastodon instances shipped

| Suffix              | Instance URL              | Note |
|---------------------|---------------------------|------|
| `mastodon-social`   | https://mastodon.social   | Default, large, English-leaning. |
| `fosstodon`         | https://fosstodon.org     | FOSS-focused, manual approval. |
| `chaos-social`      | https://chaos.social      | Hacker / CCC-leaning. |
| `infosec-exchange`  | https://infosec.exchange  | Security researchers. |
| `mastodon-art`      | https://mastodon.art      | Artists; strict CW culture. |

Pick with `--instance fosstodon` (or `chaos-social`, etc.).

## Honest no-phone tracker

The `no_phone_path` field on each profile is the source of truth.
Snapshot summary (verify before relying — providers change policies):

* **Always works:** ProtonMail (onion), Tutanota, Mailfence, Disroot,
  ProtonVPN, TunnelBear, Windscribe, Mastodon.
* **Usually works:** Reddit, Discord (at signup only), Outlook (lucky
  IP), Mailfence with EU IP.
* **Rarely works:** Gmail, Yahoo, Twitter/X, paid Telegram.
* **Never works:** Telegram (phone *is* the account).

If a provider you need isn't here, the `ProviderProfile` dataclass is
small — drop a new file in `src/darkcat/identity/providers/` and
`register()` it. The registry deduplicates by slug, so reloading an
existing module replaces the entry instead of appending.
