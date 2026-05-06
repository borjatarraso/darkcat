# Darkcat user guide

A field manual for the networks darkcat speaks. The goal is not to teach you
how to operate them safely — that is your responsibility — but to give the
mental model you need to understand what darkcat is doing on your behalf
and where it stops being helpful.

> **Authorization-first.** Darkcat is a defensive-research tool. Use it on
> infrastructure you own, on threat-intelligence engagements you have a
> contract for, in CTFs, or for academic study. Do not use it to find
> targets to harm. The networks below host both legitimate research
> communities and active criminal markets; treat URLs you discover as
> hazardous until you have read them in a sandboxed renderer.

---

## 1. Surface, deep, dark — what the words actually mean

| Term | What it really means | Reachable how |
|------|----------------------|---------------|
| **Surface web** | Pages a search engine has crawled and indexed. | A normal browser, no auth. |
| **Deep web** | Pages reachable on the public internet but **not indexed** — paywalls, login-gated forums, parameterized DB results, intranets, private GitHub repos, dynamically generated dashboards, your bank statement page. The deep web is *vastly* larger than the surface web. | A normal browser, but you need credentials, the right URL, or to be on a private network. |
| **Dark web** | A subset of the deep web reachable only through anonymity / overlay networks. Not Google-indexable for two reasons: (a) the hostname doesn't resolve over normal DNS, (b) reaching it requires running an overlay client. | A specialized client / proxy (Tor, I2P, Lokinet, Freenet, ZeroNet, Yggdrasil, …). |
| **Darknet** | The infrastructure layer — the overlay network itself, not the content on it. "The Tor darknet" = the Tor anonymity network; "Tor onion services" = the dark-web content hosted on it. You'll hear it used loosely as a synonym for "dark web" — it isn't. |

**Key distinction.** Your bank's account page is "deep web" but not "dark
web". A `.onion` site is *both* deep web and dark web. A Reddit thread is
neither.

Darkcat's job is to (1) speak as many of the dark-web protocols as
possible from one CLI, and (2) make crawled content searchable so you
can do post-hoc threat analysis without juggling six clients.

---

## 2. Quick reference: every network darkcat speaks

| Network | URL form | Anonymity model | Darkcat transport |
|---------|----------|-----------------|-------------------|
| **Tor** | `*.onion` (v3 = 56 chars) | Onion routing, 3-hop circuits | SOCKS5 → 127.0.0.1:9050 |
| **I2P** | `*.i2p`, `*.b32.i2p` | Garlic routing, unidirectional tunnels | HTTP proxy → 127.0.0.1:4444 |
| **Lokinet** | `*.loki` | Onion routing on top of Oxen service-node DHT | System TUN |
| **Freenet / Hyphanet** | `freenet:CHK@…/USK@…` | F2F datastore, content-addressed | FProxy → 127.0.0.1:8888 |
| **GNUnet** | `*.gnu`, `*.zkey` | F2F mesh, GNS naming | System resolver |
| **ZeroNet** | `zero://<address>` | BitTorrent-like, sites pinned by visitors | UI → 127.0.0.1:43110 |
| **Yggdrasil** | IPv6 `200::/7` | Mesh end-to-end IPv6, no onion-style anon | System TUN |
| **cjdns / Hyperboria** | IPv6 `fc00::/8` | Mesh, source-routed | System TUN |
| **Reticulum / LXMF** | `lxmf://`, `reticulum://` | Long-form mesh / RF / packet | rnsd (stub) |
| **IPFS / IPNS** | `ipfs://CID`, `ipns://name` | Content-addressed DHT, no anonymity | gateway → 127.0.0.1:8080 |
| **Hyper / Hypercore** | `hyper://<key>` | Append-only logs over Hyperswarm | hyper.fyi (best-effort) |
| **Dat** | `dat://<key>` | Predecessor of Hyper, deprecated | stub |
| **SSB (Scuttlebutt)** | `ssb://%feed%.ed25519` | Gossip, F2F replication | stub (needs SSB pub) |
| **Earthstar** | `earthstar://<share>` | Sharded sync over many transports | stub |
| **Cabal** | `cabal://<key>` | Decentralized chat / forums | stub |
| **Gemini** | `gemini://host[:1965]/path` | Small-web TLS protocol, TOFU | Native client |
| **Spartan** | `spartan://host[:300]/path` | Smaller-web sibling of Gemini | Native client |
| **Nex** | `nex://host[:1900]/path` | Even-smaller-web | Native client |
| **Gopher** | `gopher://host[:70]/<sel>` | 1991-era hierarchical browser | Native socket |
| **Gophers** | `gophers://host[:70]/<sel>` | Gopher over TLS | Native socket |
| **Finger** | `finger://user@host[:79]` | Per-user info protocol, RFC 1288 | Native socket |
| **NNTP / Usenet** | `news://server[/group[/article]]` | Decentralized newsgroups | Native NNTP |
| **WebFinger** | `acct:user@host` | Discovery for Fediverse / IndieWeb | HTTPS |
| **Namecoin** | `*.bit` | Blockchain-rooted DNS | ncdns / OpenNIC |
| **Emercoin** | `*.emc, *.lib, *.bazar, *.coin` | Blockchain-rooted DNS | emcDNS / OpenNIC |
| **ENS (Ethereum)** | `*.eth` | Smart-contract DNS | eth.limo gateway |
| **Handshake** | `*.hns + many TLDs` | Decentralized root zone | hsd / hns.is |
| **Unstoppable Domains** | `*.crypto, *.nft, *.x, *.wallet …` | Polygon-rooted DNS | Unstoppable / Cloudflare resolver |
| **OpenNIC** | `.geek .free .indy .pirate …` | Alternative DNS root | OpenNIC servers |
| **Solana SNS** | `*.sol` | Solana-rooted DNS | stub |
| **Briar** | `briar://` | Bluetooth + Tor mesh messenger | stub (mobile) |
| **Tox** | `tox://<id>` | Friend-to-friend P2P chat | stub |
| **Retroshare** | `retroshare://` | F2F with key-signed identity | stub |
| **Magnet / ed2k** | `magnet:?…`, `ed2k://…` | Torrent / eDonkey identifiers | Decoded to text/plain |
| **Session** | 66-hex Account ID | Onion-routed messaging on Oxen | extracted as contact ID |
| **SimpleX** | `simplex:` URI / `simplex.chat/contact` link | No durable identity, queue-based | extracted as contact ID |
| **XMPP** | `xmpp:user@host` | Federated chat, optional Tor | extracted as contact ID |
| **Matrix** | `@user:server.tld` | Federated chat | extracted as contact ID |
| **Ricochet** | `ricochet:onion-id` | Tor-only F2F messenger | extracted as contact ID |
| **Clearnet** | `https://anything` | None | Tor SOCKS5 if up, else direct |

---

## 3. Per-network deep dive

### Tor (The Onion Router)

The 800-pound gorilla of anonymity overlays. Three-hop circuits — guard,
middle, exit — encrypt traffic in three layers ("onion"); each relay
peels one layer and sees only the next hop. Onion services skip the exit
and rendezvous via introduction points, so neither side learns the
other's IP.

* **What's on it.** SecureDrop instances, journalist tip lines,
  privacy-respecting mirrors of mainstream sites (BBC, ProPublica, The
  Intercept), human-rights forums, *and* Russian / English-speaking
  drug markets, ransomware leak sites, breach forums, fraud bazaars.
  Most of "the dark web" in casual usage means Tor.
* **How darkcat reaches it.** Routes via `127.0.0.1:9050` SOCKS5. If you
  want tighter control (NEWNYM rotation, bridges, info), pair with the
  control port (default 9051) and `darkcat tor`.
* **Stream isolation.** Darkcat asks the Tor SOCKS proxy for a fresh
  circuit per host by default — different onions don't share circuits,
  so a compromised relay can't correlate your crawls.
* **Captchas / Cloudflare.** Many clearnet sites Tor-block at the edge.
  Pair `--render` with a persona's cookie jar to ride a session that
  passed the challenge once.

### I2P (Invisible Internet Project)

Garlic routing — multiple messages bundled per "garlic clove" — with
unidirectional tunnels (in and out, separate paths). Stronger against
some traffic-analysis attacks than Tor; weaker user base; no clearnet
exit nodes by default.

* **What's on it.** Eepsites (`*.i2p` and `*.b32.i2p`), torrents
  (i2psnark), an internal IRC, plus mirrors of forums that double-host
  on Tor. Smaller volume but a more technical / privacy-purist culture.
* **How darkcat reaches it.** HTTP proxy on `127.0.0.1:4444`. The I2P
  router itself runs as a daemon (Java I2P or i2pd).

### Lokinet

Onion routing over the Oxen blockchain's service-node set. The same
service nodes that power the Session messenger also relay Lokinet
traffic. SNApps end in `.loki`.

* **Why it matters.** SNApps don't suffer from Tor's HSDir-enumeration
  problem (everyone scrapes onion v2/v3 descriptors). The cost is a much
  smaller anonymity set.
* **How darkcat reaches it.** Lokinet runs as a daemon and exposes a
  TUN interface; darkcat just makes normal HTTP requests routed
  system-wide.

### Freenet / Hyphanet

A peer-to-peer datastore. You don't browse "sites"; you fetch
**content-addressed** keys (CHK = static blob, SSK = signed blob, USK =
updatable site). Once content is inserted, it can persist for years even
after the original poster is offline.

* **What's on it.** Long-form essays, Frost forums, freesites of
  whistleblowers and dissidents. Older / quieter than Tor; resistant to
  takedown.
* **Trade-off.** Latency is brutal (seconds to minutes) and content can
  be anywhere on the network. Plan for slow crawls.

### GNUnet

Friend-to-friend mesh with **GNS** (GNU Name System) replacing DNS. Less
content, more research focus.

### ZeroNet

BitTorrent-like distribution: every visitor of a site reseeds it. Sites
are signed with a Bitcoin private key (the "address"). Resilient, but
not anonymous unless you front it with Tor.

* **Darkcat hook.** `zeronet-walk SITE` traverses a site's
  `content.json` graph and optionally ingests every file as a page.

### Yggdrasil & cjdns / Hyperboria

End-to-end **encrypted IPv6 mesh**, not anonymity overlays — your
public-key-derived IPv6 address is pseudonymous but stable. Treat them
like a private internet that anyone can join: confidentiality good,
anonymity weak.

### Reticulum / LXMF

Mesh protocol designed to run over packet-radio, lora, serial links,
i.e. for situations with no "internet" at all. Darkcat ships a stub —
real ingest needs `rnsd` running locally.

### IPFS / IPNS

Content-addressed storage. CIDs are sha256-of-content; the same blob has
the same CID everywhere. No anonymity; treat IPFS like a public CDN
where pinning != hosting.

* **Darkcat hook.** Routes `ipfs://CID` and `ipns://name` through the
  local IPFS gateway (or a public gateway with `--public-ipfs`).

### Hyper, Dat, SSB, Earthstar, Cabal

The "Beaker browser ecosystem." All decentralized, all
content-addressed, all very small communities. Darkcat parses the URL
schemes; only Hyper has a working transport (best-effort via gateway).
The rest are stubs that mark the URL as recognized but can't fetch.

### Gemini, Spartan, Nex, Gopher, Gophers, Finger, NNTP, WebFinger

The "small-web" suite. Plain text and minimal markup, tiny servers, a
deliberate retreat from JavaScript-heavy advertising surfaces.

* **Gemini.** TLS-mandatory, TOFU certs, `text/gemini` markup. The
  largest of the small-web protocols by far. Real communities, real
  bloggers, no advertisers.
* **Gopher.** Pre-web hierarchical document protocol; small but
  enthusiastic community keeps it alive on phlogosphere.
* **NNTP.** Real Usenet still exists; useful for archival research.
* **WebFinger.** Discovery layer for Fediverse / IndieWeb identities.

### Alt-naming (Namecoin, Emercoin, ENS, Handshake, Unstoppable, OpenNIC, Solana)

These don't host content directly — they just provide alternative DNS
roots. Once a name resolves, it points to a normal HTTPS server (or
sometimes IPFS / Tor). Darkcat's job is to *resolve* the name through
the right resolver and then hand the response off to the appropriate
transport.

### Briar, Tox, Retroshare, Ricochet

**Friend-to-friend messengers.** No central server, no public directory.
You can't *crawl* them — there are no addressable pages. But forums on
Tor and I2P routinely advertise contact IDs for these networks, and
darkcat extracts them so you can see who is publishing what handles.

---

## 4. Messaging-only networks: Session, SimpleX, Tox, XMPP, Matrix

These are pure messaging protocols. They have no "websites" to crawl;
the unit of activity is a **conversation between contact IDs**. Darkcat
can't open a conversation for you, but it can:

1. Find the IDs that get advertised on crawled sites (`darkcat scan`).
2. Group them by network and surface the pages that mention them
   (`darkcat contacts list / show / export`).
3. Hold a persona for each one (`darkcat personas add …`) so the handle,
   recovery seed, and any account password you set on the messenger live
   in the same encrypted vault as your forum logins.

### Session

* **Identity.** A 66-hex-char Account ID — a Curve25519 pubkey prefixed
  with `05` (account), `15` (closed group), or `25` (blinded relay).
  No phone number, no email.
* **Routing.** Onion-routed via Oxen service nodes. Each message hops
  through three SNs.
* **Why it matters in dark-web ops.** Session is the de-facto successor
  to Wickr in a lot of forum cultures: no metadata trail, multi-device,
  ID-only friending. Darkcat's `session_id` finding is high-confidence:
  the prefix + length + hex match is unique enough that false positives
  are rare.
* **Implementing in darkcat.** No transport — Session has no HTTP API to
  read with. Extraction-only; pair with `darkcat personas add … --notes
  "session: 05abc…"` to track which IDs you've spoken to.

### SimpleX

* **Identity.** None durable. Each conversation is a fresh queue on a
  randomly chosen SMP server, identified by a one-time URI of the form
  `simplex:/<base64url>` or as an HTTPS redirect through
  `simplex.chat/contact`.
* **Routing.** SMP relays; you can self-host. Strong forward-secrecy /
  unlinkability story.
* **Implementing in darkcat.** Extraction-only — there is no scrapeable
  surface, only one-shot invite links. Findings include both the
  `simplex:` URI form and the web-redirect form.

### Tox

* **Identity.** A 38-byte tuple rendered as 76 hex chars: 32 B
  Curve25519 pubkey + 4 B "nospam" anti-flood + 2 B XOR checksum.
* **Routing.** Pure DHT; no relays, no central infra. Full P2P, which
  also means metadata leaks to peers.
* **Implementing in darkcat.** Extraction with a context guard — bare
  76-hex strings collide with too many things, so a Tox finding fires
  only when nearby text contains `tox`, `pubkey`, `chat id`, etc.

### XMPP / Jabber

* **Identity.** A JID — `localpart@server.tld` — not unlike an email.
  Tor-friendly servers (calyx.net, dismail.de, jabber.ccc.de) double as
  the de-facto "secure XMPP" set.
* **Routing.** Federated XML stanzas. End-to-end encryption needs an
  extension (OMEMO).
* **Implementing in darkcat.** We catch the explicit `xmpp:` URI plus
  any "JID:" / "Jabber:" hint near a bare address. Plain `user@host`
  without context is **not** flagged — too many false positives from
  email lists.

### Matrix

* **Identity.** `@localpart:server.tld`. Federated. Element / Cinny are
  the popular clients.
* **Routing.** Server-mediated; servers gossip events to each other.
* **Implementing in darkcat.** Pattern-matched directly. The watch /
  alert sinks include a Matrix sink (`matrix:HOMESERVER|ROOM_ID|TOKEN`)
  if you want to receive findings in a Matrix room.

### Briar

Bluetooth + Tor + LAN mesh, mobile-first. Invite is a `briar://` link.
Extraction-only.

### Ricochet (and Ricochet Refresh)

`ricochet:` URI containing a v2 (16-char) or v3 (56-char) onion address.
Tor-only F2F messaging. The legacy v2 client is unmaintained; Ricochet
Refresh is the current fork.

---

## 5. Personas: how to actually log in to anything

Forums on Tor / I2P routinely gate the content you came for behind a
login, sometimes with a small Monero or Bitcoin entry fee. Darkcat's
**persona vault** is where you keep one identity per (network, site).

### Lifecycle

```
darkcat personas add bob \
    --network tor \
    --site dread.onion \
    --gen
# → handle generated, password generated, cookie jar reserved at
#   ~/.darkcat/cookies.bob.txt

# Log in manually in Tor Browser, export Netscape cookies, import:
darkcat --cookie-jar $(darkcat personas use bob) \
    cookies import dread-tor-export.txt

# Now every crawl that uses bob rides bob's session:
darkcat --cookie-jar $(darkcat personas use bob) \
    crawl -p tor https://dread.onion/d/somesub

# When you're done, encrypt the vault for at-rest safety:
darkcat personas encrypt   # → ~/.darkcat/personas.json.gpg
```

### Threat model

* **Vault file.** Plain JSON at `~/.darkcat/personas.json` with mode
  `0600`. After `personas encrypt` it's `personas.json.gpg`, AES-256
  symmetric, passphrase prompted on every load (or read from
  `$DARKCAT_VAULT_PASSPHRASE` for unattended runs).
* **Cookies.** Stored separately in `~/.darkcat/cookies.<persona>.txt`
  (Netscape format). Cookies are also credentials — back them up the
  same way you'd back up an SSH key.
* **Recovery codes / mnemonics.** Stored in the vault but masked by
  default in `personas show`; pass `--reveal` to print plaintext.

### What darkcat **doesn't** do

* It does not register accounts for you. Most onion forums require
  hand-solved captchas and a small payment; you do that step in Tor
  Browser, then teach darkcat about the resulting session.
* It does not autosolve anti-bot challenges.
* It does not impersonate real people. Generated handles are
  obviously-synthetic strings (`silent_owl_4271`); the goal is "an
  identity that won't collide with someone real," not "a deepfake
  persona."

---

## 6. Operational hygiene

* **Run Tor inside Whonix or a dedicated VM** when crawling fraud /
  ransomware / abuse markets. Browser fingerprinting and link previews
  routinely leak your real IP.
* **Treat onion descriptors as toxic.** Descriptors and HSDir queries
  can fingerprint you against Tor relays. Darkcat fetches descriptors
  only when you explicitly ask (`darkcat tor descriptor …`).
* **Rotate circuits, not personas.** `darkcat tor newnym` (also
  available implicitly via `--newnym-after N` on `crawl`) gets you a
  fresh circuit for the same identity. Switching personas is a slower,
  more expensive operation — use it when the *identity* is burned, not
  when the *network path* is.
* **Don't mix personas in one circuit.** If you crawl two onions back
  to back without `newnym`, the same exit and middle relays see both
  requests. Stream isolation (on by default) keeps onion-to-onion
  isolation strong; cross-protocol (onion → clearnet) is where you have
  to be explicit.
* **Never crawl a clearnet site through Tor without disclosing the
  context.** Many sites view Tor traffic as adversarial. Darkcat tries
  Tor first for clearnet and falls back to direct only when Tor is
  unreachable, but you should be aware of the implication.
* **Watchlist alerts go through external services.** Slack / Discord /
  Matrix / SMTP sinks send alert text to third-party servers. If the
  finding contains bait (a target email, a leak BIN), assume those
  servers see it.

---

## 7. Where to learn more

* Tor Project — <https://www.torproject.org/>
* I2P / I2P+ — <https://geti2p.net/> / <https://i2pplus.github.io/>
* Oxen / Lokinet / Session — <https://oxen.io/>
* Hyphanet (Freenet) — <https://www.hyphanet.org/>
* GNUnet — <https://gnunet.org/>
* Yggdrasil — <https://yggdrasil-network.github.io/>
* Hyperboria / cjdns — <https://github.com/cjdelisle/cjdns>
* Reticulum — <https://reticulum.network/>
* IPFS — <https://ipfs.tech/>
* Hypercore Protocol — <https://hypercore-protocol.org/>
* Gemini — <https://geminiprotocol.net/>
* SimpleX — <https://simplex.chat/>
* Briar — <https://briarproject.org/>
* OpenNIC — <https://www.opennic.org/>
* Handshake — <https://handshake.org/>
* ENS — <https://ens.domains/>

If you find a network this guide doesn't cover, file an issue. The map
isn't the territory; the territory is moving faster than any one tool.
