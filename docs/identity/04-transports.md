# Identity Generator — transports

Every persona records a `transport_used` string of the form
`<kind>:<token>`. The kind is one of `tor`, `i2p`, `proxy`, `vpn-pin`.
The token's meaning depends on the kind:

| Kind       | Token                                  | Used for                                         |
|------------|----------------------------------------|--------------------------------------------------|
| `tor`      | 16-hex SHA-256 prefix of the seed      | SOCKS auth pair → Tor stream isolation           |
| `i2p`      | 16-hex SHA-256 prefix of the seed      | (Reserved — stream isolation hooks not implemented) |
| `proxy`    | the literal `proxy_url`                | Direct-pass to `requests` `proxies=`             |
| `vpn-pin`  | the literal pin target (advisory)      | Documents the expected egress; **not** enforced  |

The seed is always the persona's `name`, so identical names produce
identical isolation tokens — that's intentional: the same persona always
takes the same SOCKS auth pair, so Tor reliably reuses the circuit.

## Tor (`--transport tor`, default)

`pick_transport("tor", seed=name)` derives a token via
`hashlib.sha256(name.encode()).hexdigest()[:16]`. The fetcher then sends
that token as the SOCKS5 username/password, which Tor (with
`IsolateSOCKSAuth`, on by default) treats as a separate stream. Two
personas → two circuits.

If the operator launches the signup with `tor-browser`, the browser
ignores our SOCKS auth and uses its own — that's fine for the manual
signup step; once the account exists, `darkcat fetch <url>` (using the
persona's cookie jar) will reuse the SOCKS-authed circuit.

## I2P (`--transport i2p`)

The token is generated identically to Tor, but `proxies_for()` returns
a plain HTTP proxy pointing at I2P's outproxy (`127.0.0.1:4444` by
default). Per-persona stream isolation through I2P's i2cp tunnels is
not yet wired up — the token is reserved for future use.

## Proxy (`--transport proxy --proxy-url URL`)

```
darkcat identity new --provider mailfence \
                     --transport proxy \
                     --proxy-url socks5://10.9.0.1:1080
```

The URL is stored verbatim and re-used for every fetch on this persona.
URL must be one of:

* `socks5://host:port`
* `socks5h://host:port` (DNS-over-SOCKS)
* `http://host:port` / `https://host:port`

Authentication is allowed (`socks5://user:pass@host:port`), but be
aware: the credential lives in the vault as part of `transport_used`.
Treat the vault accordingly.

`pick_transport("proxy")` raises `ValueError` if `proxy_url` is missing
— there is no fallback.

## VPN pin (`--transport vpn-pin --pin-to TARGET`)

Pinning is **advisory**. Darkcat does not control the VPN client; it
just records that this persona expects to egress through `<TARGET>`.
The fetcher will not auto-route to the pinned target — calling
`choice.proxies_for(cfg)` raises `NotImplementedError` so it's
impossible to forget that no enforcement happens.

Use this kind when:

* You manage VPN routes externally (per-namespace `wg`, policy routing,
  PolicyKit, etc.).
* You want the vault to *remember* which exit was meant for this
  persona, even if darkcat itself can't enforce it.

`pick_transport("vpn-pin")` raises `ValueError` if `pin_to` is missing.

## Choosing per provider

The shipped profiles carry a `transport_recommendation`. `identity new`
respects whatever you pass on the command line — the recommendation is
a hint surfaced by `identity providers <slug>`, not a default-override
mechanism. If you don't pass `--transport`, the CLI uses `tor`.

## Determinism and rotation

Tokens are deterministic per-name. To rotate a persona's circuit
without changing identity, rename the persona (delete + recreate with
the same fields) — but that breaks the link graph. Better: leave the
token alone and rely on Tor's natural circuit churn.

## Implementation pointers

* `src/darkcat/identity/transport.py` — `pick_transport`,
  `transport_token`, `TransportChoice`.
* `src/darkcat/control.py` — fetcher hands `transport_used` to its
  SOCKS layer.
* `tests/test_identity.py::test_transport_token_is_deterministic` —
  asserts token stability and 16-hex length.
