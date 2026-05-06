# Network reference

A field card for every network darkcat speaks. For each: what it is,
why it exists, what it's good at, and where it falls down. Designed
to be skimmable — read the row you need and move on.

> **Pair with** `docs/USERGUIDE.md` for hands-on usage and `docs/INTERNALS.md`
> for how darkcat plumbs each transport.

---

## Quick legend

* **Anonymity model** — what the network protects against. "Onion" =
  client and server are both hidden; "Mesh-pseudonymous" = traffic is
  encrypted but identities are stable; "None" = it's just a CDN /
  naming layer.
* **Best for** — what the protocol is genuinely good at, where it's
  the right tool.
* **Weak against** — adversaries / failure modes the design *doesn't*
  defend.
* **Darkcat surface** — `transport` (full crawl), `extractor`-only
  (we recognize the URL but can't fetch), `chat` (messenger), or
  `stub`.

---

## Anonymity overlays

### Tor — onion routing, the gold standard

* **Anonymity model.** Three-hop circuits over public relays; onion
  services rendezvous via introduction points so neither side learns
  the other's IP.
* **Goals.** Censorship resistance, anonymous publication, anonymous
  reading. Originally a U.S. Naval Research Lab project; now a
  nonprofit with a decade of academic security analysis behind it.
* **Strengths.** Largest anonymity set of any overlay (~2M users,
  ~7000 relays). Battle-tested. Rich client (Tor Browser) with
  fingerprinting hardening. Onion v3 addresses don't leak via
  HSDir scraping the way v2 did.
* **Weaknesses.** Slow (multi-hop). Vulnerable to global passive
  adversaries who see traffic on both ends. Exit nodes can sniff
  unencrypted clearnet traffic. Many clearnet CDNs hard-block Tor exits.
  Quantum-vulnerable key exchange (NTor).
* **Darkcat surface.** `transport` — SOCKS5 to 127.0.0.1:9050 with
  per-host stream isolation. Control-port helpers (`darkcat tor …`)
  for NEWNYM, descriptor fetch, bridge lines.

### I2P — garlic routing, eepsite native

* **Anonymity model.** Multi-message "garlic" packets routed through
  unidirectional tunnels (separate in/out paths). Internal-by-default
  (no clearnet exits unless an outproxy is configured).
* **Goals.** Anonymous internal services. Less of a "Tor for clearnet
  via exits" mission, more of a "build everything inside the network".
* **Strengths.** Tunnels are per-application, so cross-application
  correlation is harder. P2P-friendly (i2psnark, IRC). Smaller but more
  technically aligned community.
* **Weaknesses.** Smaller anonymity set (~50k routers vs Tor's millions).
  Java reference implementation is heavy; i2pd is faster but less
  audited. Outproxies are a single point of trust.
* **Darkcat surface.** `transport` — HTTP proxy to 127.0.0.1:4444.

### Lokinet — onion routing on the Oxen DHT

* **Anonymity model.** Onion routing very similar to Tor's, but the
  relay set is the Oxen blockchain's service-node committee. SNApps
  end in `.loki`.
* **Goals.** Pay-to-play relay incentive (service nodes earn Oxen);
  no HSDir descriptor enumeration; integrated with Session messenger.
* **Strengths.** Service nodes have economic skin in the game (staked
  Oxen). Lokinet's `.loki` resolution is on-chain — no probabilistic
  rendezvous-point game.
* **Weaknesses.** Tiny anonymity set (~2k service nodes). Economic
  centralization: large stakers can dominate the relay set.
  Censorship-resistance depends on the Oxen blockchain not being
  attacked.
* **Darkcat surface.** `transport` — system TUN; darkcat just makes HTTP
  requests once Lokinet is up.

### Freenet / Hyphanet — distributed datastore

* **Anonymity model.** "Darknet" mode: connect only to manually-trusted
  friends ("F2F"). "Opennet" mode: connect to strangers. Content is
  content-addressed (CHK = static, SSK = signed-mutable, USK = updatable).
* **Goals.** Anonymous *publication* with persistence: once inserted,
  content survives the publisher disconnecting.
* **Strengths.** Strong publication anonymity (the inserter is hidden
  by routing through a chain of relays). Censorship-resistant by design
  — takedown means convincing every node to drop the content.
* **Weaknesses.** Latency is brutal (seconds to minutes per fetch).
  Content disappears if no one requests it for a long time. Small user
  base. Reading patterns are correlatable on Opennet.
* **Darkcat surface.** `transport` — FProxy to 127.0.0.1:8888.

### GNUnet — F2F mesh + GNS naming

* **Anonymity model.** F2F-only by design; GAP file-sharing protocol
  uses pre-image-resistant block routing.
* **Goals.** A general framework for secure, decentralized internet
  applications. GNS replaces DNS with a Petname-style system.
* **Strengths.** Academic rigor; lots of formal analysis. GNS doesn't
  have the trust-anchor problem of DNSSEC.
* **Weaknesses.** Tiny user base. Steep operator complexity. Most
  applications are research-grade, not production.
* **Darkcat surface.** `extractor` only.

### ZeroNet — BitTorrent-like, signed sites

* **Anonymity model.** None by default. Front it with Tor for client
  anonymity.
* **Goals.** Build websites that survive their author going offline:
  every visitor reseeds the site.
* **Strengths.** Resilient to takedown if anyone is still hosting.
  Site signed with a Bitcoin private key, so updates are
  cryptographically verifiable.
* **Weaknesses.** Visitors are exposed unless tunneled through Tor.
  Very small ecosystem; many sites unmaintained. Discovery is awkward.
* **Darkcat surface.** `transport` via the local UI; `darkcat zeronet-walk`
  traverses content.json.

### Yggdrasil — encrypted IPv6 mesh

* **Anonymity model.** Pseudonymous: your IPv6 address is the public
  key, stable across sessions. Confidentiality good; anonymity weak.
* **Goals.** A scalable end-to-end encrypted mesh — like a private
  internet that anyone can join.
* **Strengths.** Simple to operate. Real IPv6 reachability between
  nodes. Rapidly self-healing topology.
* **Weaknesses.** Not anonymous. Not private from your peers (they
  see who you talk to). DDoS-able like any IPv6 host.
* **Darkcat surface.** `transport` — system TUN.

### cjdns / Hyperboria — source-routed mesh

* **Anonymity model.** Same as Yggdrasil: pseudonymous IPv6.
* **Goals.** Predecessor philosophy to Yggdrasil. Hyperboria is the
  largest cjdns deployment.
* **Strengths.** Deep peer-to-peer routing with explicit path control.
* **Weaknesses.** Smaller, older codebase; less active maintenance
  than Yggdrasil.
* **Darkcat surface.** `transport` — system TUN.

### Reticulum / LXMF — long-form mesh, packet-radio friendly

* **Anonymity model.** Pseudonymous (Ed25519 destinations).
* **Goals.** Mesh protocol that runs over arbitrary links — Bluetooth,
  LoRa, packet radio, serial cable, TCP. Designed for situations
  *without* internet.
* **Strengths.** Transport-agnostic. Resilient to disconnection. LXMF
  (the messaging layer) is store-and-forward.
* **Weaknesses.** Tiny ecosystem. Mostly tinkerers and HAM radio.
* **Darkcat surface.** `stub` — needs `rnsd` running locally.

---

## Distributed-web protocols

### IPFS / IPNS — content-addressed storage

* **Anonymity model.** None.
* **Goals.** Decentralized content distribution. CIDs are sha256 of
  the content; the same blob has the same CID everywhere. IPNS adds
  mutable pointers signed by a key.
* **Strengths.** True content-addressing (verify what you received).
  Excellent for static-asset distribution. Pinning markets exist.
* **Weaknesses.** Pinning ≠ hosting (anyone can stop). Public gateways
  centralize trust. Privacy is approximately zero — your peers see
  every CID you fetch.
* **Darkcat surface.** `transport` — local gateway preferred,
  optional public-gateway fallback.

### Hyper / Hypercore — append-only logs

* **Anonymity model.** None directly.
* **Goals.** Reliable append-only log replication via Hyperswarm DHT.
  Powers Beaker browser.
* **Strengths.** Live updates, sparse replication, peer-to-peer.
* **Weaknesses.** Tiny user base. Beaker browser is dormant. Best as
  a building block.
* **Darkcat surface.** `transport` — best-effort via gateway.

### Dat — predecessor of Hyper

Deprecated in favor of Hyper. Stub.

### SSB (Secure Scuttlebutt) — gossip log

* **Anonymity model.** None — feeds are signed by a known key.
* **Goals.** Offline-first, gossip-replicated social network. Each
  participant has an append-only log; pubs gateway between LANs.
* **Strengths.** Genuinely offline-capable. Strong community in
  certain subcultures.
* **Weaknesses.** No DM (everything is broadcast). Joining requires
  knowing a "pub". Very specific design choices that aren't for
  everyone.
* **Darkcat surface.** `extractor` only.

### Earthstar — sharded sync

Niche. Stub.

### Cabal — decentralized chat

Niche. Stub.

---

## Small-web

### Gemini — TLS-mandatory, TOFU certs, text/gemini

* **Anonymity model.** None inherent. Tor-friendly because it's a
  small protocol.
* **Goals.** Deliberate retreat from JavaScript-heavy web. Spec fits on
  a few pages.
* **Strengths.** Privacy by simplicity (no cookies, no tracking, no
  WebRTC). Self-host trivially. Real bloggers, real essays, no ads.
* **Weaknesses.** Niche. Some content trapped behind Tor or VPN walls
  but most is public. Search is a community problem (geminispace.info,
  Kennedy).
* **Darkcat surface.** `transport` — native TLS+TOFU client.

### Spartan / Nex — simpler-than-Gemini

* **Goals.** Even smaller. Spartan removes input prompts; Nex removes
  TLS.
* **Strengths.** Minimalism. Easy to write a server in a shell script.
* **Weaknesses.** Tiny ecosystems.
* **Darkcat surface.** `transport` — native sockets.

### Gopher / Gophers — pre-web hypertext

* **Goals.** What you got before HTTP existed. Hierarchical menus,
  text files, no markup.
* **Strengths.** Tiny, fast. Active phlogosphere community.
* **Weaknesses.** Read-only practically; no search; tiny.
* **Darkcat surface.** `transport` — native socket; `gophers://` over TLS.

### Finger — per-user info

* **Goals.** RFC-1288 daemon: ask `finger user@host`, get a plan file.
* **Strengths.** Charming. Used by some Gemini operators as an "about"
  page.
* **Weaknesses.** Niche.
* **Darkcat surface.** `transport`.

### NNTP / Usenet

* **Goals.** Decentralized newsgroups. Articles flood-replicate
  through peering.
* **Strengths.** Long-running archives. Some old crypto / privacy /
  research discussion is *only* on Usenet.
* **Weaknesses.** Spam-heavy. Most public servers gone. Binary groups
  are mostly piracy.
* **Darkcat surface.** `transport` — native NNTP.

### WebFinger — discovery for Fediverse / IndieWeb

* **Goals.** "Who is `acct:user@example.com`?" → `.well-known/webfinger`
  on `example.com` returns links.
* **Strengths.** Glue for federated identity.
* **Weaknesses.** Not a content protocol; just discovery.
* **Darkcat surface.** `transport` — HTTPS to `.well-known/webfinger`.

---

## Alt-naming systems

These don't host content; they replace DNS. Once a name resolves, you
get a normal HTTPS / Tor / IPFS endpoint that darkcat then fetches via
the appropriate transport.

| Network | Resolution mechanism | Darkcat surface |
|---------|----------------------|-----------------|
| **Namecoin** (`.bit`) | Blockchain DNS, ncdns or OpenNIC | resolver |
| **Emercoin** (`.emc/.lib/.bazar/.coin`) | Blockchain DNS, emcDNS or OpenNIC | resolver |
| **ENS** (`.eth`) | Ethereum smart contract | eth.limo gateway |
| **Handshake** (`.hns` + many TLDs) | Decentralized root zone, hsd/hnsd | hns.is gateway |
| **Unstoppable Domains** (`.crypto`, `.nft`, `.x`, `.wallet` …) | Polygon contracts | Cloudflare resolver |
| **OpenNIC** (`.geek/.free/.indy/.pirate/.parody` …) | Alternative DNS root | OpenNIC servers |
| **Solana SNS** (`.sol`) | Solana name service | stub |

**Strengths overall.** Censorship-resistant naming. No registrar gatekeepers.

**Weaknesses overall.** Squatting markets dominate. Resolver
centralization is a frequent attack vector (eth.limo, hns.is, Cloudflare
Unstoppable). Browser-side support is patchy.

---

## Messaging-only networks

Not crawlable; surfaced through `darkcat scan` (find the IDs people
publish) and `darkcat chat` (talk over them with persona-bound logins).

### Telegram

* **Threat model.** Centralized servers, optional client-side E2EE
  (Secret Chats only). Channels and groups are server-readable.
* **Strengths.** Massive user base. Public channels are searchable.
  Bot API is rich. MTProto v2 is fast and well-analyzed.
* **Weaknesses.** Server trust required for normal chats. Telegram
  Inc. complies with various legal demands. Phone-number registration
  is a metadata leak.
* **Darkcat surface.** `chat` — full Telethon-driven user-account login.

### Matrix

* **Threat model.** Federated. Optional E2EE (Olm/Megolm). Server
  metadata (who talks to whom, when) is visible to participating
  homeservers.
* **Strengths.** Open standard, multiple servers and clients, real
  bridges to other protocols (IRC, Discord, Telegram).
* **Weaknesses.** E2EE key-management UX is rough. Metadata leakage
  across federated servers. Big rooms are painful.
* **Darkcat surface.** `chat` — matrix-nio-driven, optional E2EE.

### XMPP / Jabber

* **Threat model.** Federated. OMEMO E2EE optional. Standard XMPP is
  plaintext between server and client (unless you require TLS) and
  plaintext on the wire between federated servers.
* **Strengths.** Mature (since 1999). Many privacy-aware servers
  (calyx.net, dismail.de, jabber.ccc.de). Self-hostable.
* **Weaknesses.** Server admin sees metadata. OMEMO ecosystem is
  fractured. Plain `<message/>` is plaintext on disk somewhere.
* **Darkcat surface.** `chat` — slixmpp; plaintext + MUC; OMEMO TODO.

### Session

* **Threat model.** No phone number, no email. Onion-routed via Oxen
  service nodes. Account ID = Curve25519 pubkey + version byte.
* **Strengths.** No durable metadata trail. Multi-device. Clean GUI.
* **Weaknesses.** Smaller anonymity set than Tor. Closed-group
  rotation has had bugs historically. Service-node set is economic.
* **Darkcat surface.** `chat` — drives session-cli (community CLI).

### SimpleX

* **Threat model.** No durable identity. Each conversation is a
  fresh queue on a randomly-chosen SMP server (relay).
* **Strengths.** Forward-secrecy across conversations. Self-hostable
  SMP relays. No "who are you" identifier to leak.
* **Weaknesses.** UX is unfamiliar (no contact list in the usual
  sense). Smaller user base.
* **Darkcat surface.** `chat` — drives a running simplex-chat
  WebSocket daemon.

### Tox

* **Threat model.** Pure DHT — no relays. Friend-by-public-key.
* **Strengths.** No central infra. Voice/video.
* **Weaknesses.** DHT exposes who you talk to to your peers. Last
  full-time maintainer left years ago. Multiple forks.
* **Darkcat surface.** `extractor` only (Python ecosystem too
  fragmented for first-class support).

### Briar

* **Threat model.** F2F. Bluetooth + Wi-Fi + Tor. QR-bootstrap.
* **Strengths.** Genuinely uncrawlable, by design. Mobile-first.
  Strong story for activist coordination during internet outages.
* **Weaknesses.** Mobile-only practically. No desktop client.
* **Darkcat surface.** `extractor` only (`briar://` invite links).

### Ricochet

* **Threat model.** Tor-only F2F. Each user IS an onion service.
* **Strengths.** Beautiful design — both sides anonymous to each other
  except for the contact handover.
* **Weaknesses.** Original Ricochet unmaintained. Refresh fork has a
  GUI but no programmable surface.
* **Darkcat surface.** `extractor` only.

---

## Choosing a network

A rough operator's chart:

| If you want… | Pick |
|--------------|------|
| Maximum anonymity for browsing | Tor (with Tor Browser) |
| Anonymous publishing, content survives | Freenet/Hyphanet |
| Internal-services-by-default | I2P or Lokinet |
| End-to-end encrypted chat with no phone | Session, SimpleX, or Matrix+E2EE |
| Mesh that works without internet | Briar (mobile) or Reticulum (radio) |
| Censorship-resistant naming | Handshake, ENS, or Namecoin |
| Static content distribution (no anonymity) | IPFS |
| Encrypted private internet | Yggdrasil or cjdns |
| Small, slow, ad-free reading | Gemini or Gopher |

There is no single "best" anonymity tool — every one of the networks
above has a specific threat model. Picking the wrong one for your
situation gives you false confidence, which is worse than no
protection. When in doubt, *layer*: Tor inside Whonix inside a
dedicated VM is a much safer position than any one network alone.
