"""Leak / credential / secret scanner for darkcat.

Pattern-based detection of credential-dump indicators in already-crawled
pages. The goal is *detection* (where do leaks surface? which targets are
mentioned?) — not collection. Findings store a salted SHA-256 of each
secret plus a redacted preview, never the full secret in plaintext.

Designed for defensive use: monitoring darknet markets, paste mirrors,
forum mirrors, ransomware leak sites, and Telegram-mirror onion services
to surface mentions of a domain or a known indicator of compromise.

Categories produced:
    email_password    user@x.com:hu****r2  (combo-list rows)
    aws_access_key    AKIA…
    aws_secret_key    40-char base64 paired with an AKIA on the same page
    github_token      ghp_… / github_pat_…
    slack_token       xox[abpros]-…
    stripe_key        sk_live_… / pk_live_… / rk_live_…
    google_api_key    AIza…
    discord_token     M…/N… two-dot bot tokens
    jwt               eyJ…three-segment JWTs
    private_key       PEM-armored private keys
    pgp_block         BEGIN PGP PRIVATE KEY BLOCK / BEGIN PGP MESSAGE
    credit_card       Luhn-valid 13-19 digit numbers (BIN+last4 stored)
    seed_phrase       BIP-39 mnemonic (12 / 24 word, heuristic)
    sql_dump          INSERT INTO ... VALUES (... bulk-insert sentinel
    breach_marker     "combolist", "stealer log", "fullz", "leak", …
    btc_address       Bitcoin Base58Check (1.../3...) or bech32 (bc1...)
    ltc_address       Litecoin Base58Check (L../M../3..) or bech32 (ltc1...)
    eth_address       Ethereum 0x… (40-hex; EIP-55 case-checked when mixed)
    trx_address       TRON Base58Check (T...)
    xmr_address       Monero standard / integrated (4../8.., 95-106 chars)
    session_id        Oxen Session 66-hex starting "05" (Curve25519 + version)
    simplex_id        simplex.chat invite link or simplex: URI
    tox_id            Tox 76-hex (32B pubkey + 4B nospam + 2B checksum)
    xmpp_jid          xmpp:user@host or "user@host" with mention context
    matrix_id         @user:server.tld
    briar_link        briar://… invite link
    ricochet_id       ricochet:onion-address
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    category: str
    sample: str        # redacted preview safe to display
    digest: str        # sha256(salt || raw secret) — for dedup / IOC matching
    target: str        # email domain, BIN, or "" if N/A
    confidence: float  # 0.0–1.0
    line_no: int       # 1-based line within the source text


# --- redaction / hashing -------------------------------------------------

def _redact(value: str, keep_start: int = 2, keep_end: int = 2) -> str:
    n = len(value)
    if n <= keep_start + keep_end:
        return "*" * n
    suffix = value[-keep_end:] if keep_end > 0 else ""
    return value[:keep_start] + "*" * (n - keep_start - keep_end) + suffix


def _digest(value: str, salt: bytes) -> str:
    return hashlib.sha256(salt + value.encode("utf-8", "replace")).hexdigest()


def _email_domain(email: str) -> str:
    return email.split("@", 1)[1].lower() if "@" in email else ""


def _line_no(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


# --- crypto address validators -------------------------------------------
# Stdlib-only. Base58Check + bech32 polymod are tiny; we skip Keccak (not in
# stdlib) and do length-only checks for XMR; EIP-55 falls back to "all-lower
# / all-upper accepted, mixed-case unverified" when keccak isn't available.

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58_ALPHABET)}


def _b58decode(s: str) -> bytes | None:
    n = 0
    for ch in s:
        v = _B58_INDEX.get(ch)
        if v is None:
            return None
        n = n * 58 + v
    pad = 0
    for ch in s:
        if ch == "1":
            pad += 1
        else:
            break
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * pad + raw


def _b58check_ok(s: str, *, expected_versions: tuple[int, ...] | None = None) -> bool:
    raw = _b58decode(s)
    if raw is None or len(raw) < 5:
        return False
    payload, checksum = raw[:-4], raw[-4:]
    h = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if h != checksum:
        return False
    if expected_versions is not None and (not payload or payload[0] not in expected_versions):
        return False
    return True


_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values) -> int:
    GEN = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            chk ^= GEN[i] if (b >> i) & 1 else 0
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_ok(addr: str, *, expected_hrp: str) -> bool:
    if any(ord(c) < 33 or ord(c) > 126 for c in addr):
        return False
    if addr.lower() != addr and addr.upper() != addr:
        return False
    addr_l = addr.lower()
    pos = addr_l.rfind("1")
    if pos < 1 or pos + 7 > len(addr_l) or len(addr_l) > 90:
        return False
    hrp = addr_l[:pos]
    if hrp != expected_hrp:
        return False
    data = []
    for c in addr_l[pos + 1:]:
        idx = _BECH32_CHARSET.find(c)
        if idx == -1:
            return False
        data.append(idx)
    polymod = _bech32_polymod(_bech32_hrp_expand(hrp) + data)
    # 1 = bech32 (segwit v0), 0x2bc830a3 = bech32m (segwit v1+ / Taproot)
    return polymod in (1, 0x2bc830a3)


# Keccak-256 — not in stdlib. Try pycryptodome / pysha3, else None.
def _keccak256(data: bytes):
    try:
        from Crypto.Hash import keccak  # pycryptodome
        h = keccak.new(digest_bits=256)
        h.update(data)
        return h.digest()
    except Exception:
        pass
    try:
        import sha3  # pysha3
        h = sha3.keccak_256()
        h.update(data)
        return h.digest()
    except Exception:
        return None


def _eip55_ok(addr: str) -> bool:
    """EIP-55 mixed-case checksum for Ethereum. ``True`` when verifiable and
    valid, or when the address is all-lower / all-upper (no checksum to
    verify). Returns ``False`` only on demonstrable mismatch."""
    if not addr.startswith("0x") or len(addr) != 42:
        return False
    body = addr[2:]
    if body.lower() == body or body.upper() == body:
        return True  # no case info to check
    digest = _keccak256(body.lower().encode("ascii"))
    if digest is None:
        return True  # can't verify, accept at lower confidence
    h = digest.hex()
    for i, c in enumerate(body):
        if c.isalpha() and ((int(h[i], 16) >= 8) != c.isupper()):
            return False
    return True


def _luhn_ok(digits: str) -> bool:
    if not (13 <= len(digits) <= 19) or not digits.isdigit():
        return False
    s = 0
    parity = len(digits) % 2
    for i, c in enumerate(digits):
        d = int(c)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        s += d
    return s % 10 == 0


# --- patterns ------------------------------------------------------------

_EMAIL = r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"

_RX_EMAIL_PWD = re.compile(rf"({_EMAIL})[:|]([^\s,;|<>]{{4,72}})")

_RX_AWS_AKID   = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_RX_AWS_SECRET = re.compile(r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])")
_RX_GH_TOKEN   = re.compile(r"\bghp_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{82}\b")
_RX_SLACK      = re.compile(r"\bxox[abpros]-[A-Za-z0-9-]{10,}\b")
_RX_STRIPE     = re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{24,}\b")
_RX_GOOGLE     = re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")
_RX_DISCORD    = re.compile(r"\b[MN][A-Za-z0-9_\-]{23,28}\.[A-Za-z0-9_\-]{6,7}\.[A-Za-z0-9_\-]{27,}\b")
_RX_JWT        = re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")
_RX_PEM        = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |ENCRYPTED |)PRIVATE KEY-----"
)
_RX_PGP_BLOCK  = re.compile(r"-----BEGIN PGP (?:PRIVATE KEY BLOCK|MESSAGE)-----")
_RX_CC         = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")
_RX_INSERT     = re.compile(
    r"INSERT\s+INTO\s+`?[A-Za-z0-9_]+`?\s*\([^)]*\)\s*VALUES\s*\(", re.I,
)
_RX_MNEMONIC   = re.compile(
    r"\b((?:[a-z]{3,8}\s){11}[a-z]{3,8}|(?:[a-z]{3,8}\s){23}[a-z]{3,8})\b"
)
_RX_BTC_B58    = re.compile(r"(?<![A-Za-z0-9])[13][1-9A-HJ-NP-Za-km-z]{25,34}(?![A-Za-z0-9])")
_RX_BTC_BECH32 = re.compile(r"(?<![A-Za-z0-9])bc1[ac-hj-np-z02-9]{6,87}(?![A-Za-z0-9])", re.I)
_RX_LTC_B58    = re.compile(r"(?<![A-Za-z0-9])[LM3][1-9A-HJ-NP-Za-km-z]{25,34}(?![A-Za-z0-9])")
_RX_LTC_BECH32 = re.compile(r"(?<![A-Za-z0-9])ltc1[ac-hj-np-z02-9]{6,87}(?![A-Za-z0-9])", re.I)
_RX_ETH        = re.compile(r"(?<![A-Za-z0-9])0x[a-fA-F0-9]{40}(?![A-Za-z0-9])")
_RX_TRX        = re.compile(r"(?<![A-Za-z0-9])T[1-9A-HJ-NP-Za-km-z]{33}(?![A-Za-z0-9])")
_RX_XMR        = re.compile(r"(?<![A-Za-z0-9])[48][0-9AB][1-9A-HJ-NP-Za-km-z]{93}(?![A-Za-z0-9])")

# --- messaging-network contact identifiers ------------------------------
# These are *contact IDs* — public handles you'd hand out to start a chat.
# We treat them as findings so the watchlist and `darkcat contacts` can
# surface where they appear, not as secrets to redact. The full ID lands
# in Finding.target so it's searchable; sample is a short preview.

# Session: 66-char hex, starts with "05" (account-id version byte) +
# 32-byte X25519 pubkey. Some clients also use "15" (group) and "25"
# (blinded). We accept all three.
_RX_SESSION = re.compile(r"(?<![0-9a-fA-F])(?:05|15|25)[0-9a-fA-F]{64}(?![0-9a-fA-F])")

# SimpleX:
#   simplex:/<base64url>                   queue / contact URI
#   https://simplex.chat/contact#/?...     web invite redirect
#   https://simplex.chat/invitation#/?...  one-time invite link
_RX_SIMPLEX_URI = re.compile(r"\bsimplex:[A-Za-z0-9\-_+/=?&%#.,:!$@~*\[\]]+", re.I)
_RX_SIMPLEX_WEB = re.compile(
    r"https?://(?:www\.)?simplex\.chat/(?:contact|invitation|a)#?/?\?[^\s\"<>]+",
    re.I,
)

# Tox: 76 hex characters (case-insensitive). Uppercase is the canonical
# rendering but plenty of forums lowercase them.
_RX_TOX = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{76}(?![0-9a-fA-F])")

# XMPP / Jabber: "xmpp:user@host" URI form, or bare "user@host" inside
# explicit XMPP/Jabber context (we look for the surrounding word
# boundary at scan time to avoid matching every email).
_RX_XMPP_URI = re.compile(r"\bxmpp:([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b", re.I)
_RX_XMPP_HINT = re.compile(
    r"\b(?:xmpp|jabber|jid)\s*[:=]?\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b",
    re.I,
)

# Matrix: @localpart:server.tld — server must contain a dot, localpart
# is restricted to the spec's allowed chars (a-z 0-9 . _ = - / +).
_RX_MATRIX = re.compile(
    r"@([A-Za-z0-9._=\-/+]{1,64}):([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b"
)

# Briar invite: briar://<base32-padded-blob>. We just check the prefix
# and a reasonable length window.
_RX_BRIAR = re.compile(r"\bbriar://[A-Za-z0-9+/=_\-]{40,}\b", re.I)

# Ricochet (legacy onion): ricochet:<v2 onion address>. v2 is 16 chars
# of base32 ([a-z2-7]); v3 is 56 chars but Ricochet Refresh hasn't
# shipped widely, so we accept both.
_RX_RICOCHET = re.compile(
    r"\bricochet:([a-z2-7]{16}|[a-z2-7]{56})\b", re.I,
)

# Note: we don't match Telegram @handles or Discord #user-ids here —
# those collide too eagerly with markdown / page anchors. The
# `darkcat telegram` command surfaces real Telegram channel content.

_RX_BREACH = re.compile(
    r"\b(combolist|combo list|stealer log|redline log|raccoon log|vidar log|"
    r"lumma log|credential dump|database dump|leak(?:ed)? data|fullz|"
    r"UHQ combo|breach forum|ransomware leak|data4sale)\b",
    re.I,
)

_API_KEY_RXS = [
    ("aws_access_key", _RX_AWS_AKID, 0.95),
    ("github_token",   _RX_GH_TOKEN, 0.95),
    ("slack_token",    _RX_SLACK,    0.9),
    ("stripe_key",     _RX_STRIPE,   0.9),
    ("google_api_key", _RX_GOOGLE,   0.85),
    ("discord_token",  _RX_DISCORD,  0.7),
    ("jwt",            _RX_JWT,      0.6),
]


# --- main scan -----------------------------------------------------------

def scan_text(text: str, *, salt: bytes = b"") -> list[Finding]:
    """Return all findings in the given text. Safe to call on empty input."""
    out: list[Finding] = []
    if not text:
        return out

    # email:password combo lists
    for m in _RX_EMAIL_PWD.finditer(text):
        email, pwd = m.group(1), m.group(2)
        if "<" in pwd or ">" in pwd:
            continue  # HTML fragment, not a credential
        out.append(Finding(
            category="email_password",
            sample=f"{email}:{_redact(pwd, 1, 1)}",
            digest=_digest(f"{email}:{pwd}", salt),
            target=_email_domain(email),
            confidence=0.85,
            line_no=_line_no(text, m.start()),
        ))

    # API keys / tokens with strong prefixes
    for cat, rx, conf in _API_KEY_RXS:
        for m in rx.finditer(text):
            tok = m.group(0)
            out.append(Finding(
                category=cat,
                sample=_redact(tok, 4, 2),
                digest=_digest(tok, salt),
                target="",
                confidence=conf,
                line_no=_line_no(text, m.start()),
            ))

    # AWS secret keys are noisy; only flag when an AKIA appears on the page.
    if _RX_AWS_AKID.search(text):
        for m in _RX_AWS_SECRET.finditer(text):
            tok = m.group(0)
            if tok.startswith((
                "AKIA", "ghp_", "github_pat_", "xox", "sk_", "pk_", "rk_",
                "AIza", "eyJ",
            )):
                continue
            out.append(Finding(
                category="aws_secret_key",
                sample=_redact(tok, 4, 2),
                digest=_digest(tok, salt),
                target="",
                confidence=0.55,
                line_no=_line_no(text, m.start()),
            ))

    # PEM private keys
    for m in _RX_PEM.finditer(text):
        out.append(Finding(
            category="private_key",
            sample=m.group(0),
            digest=_digest(m.group(0) + str(m.start()), salt),
            target="",
            confidence=0.95,
            line_no=_line_no(text, m.start()),
        ))
    for m in _RX_PGP_BLOCK.finditer(text):
        out.append(Finding(
            category="pgp_block",
            sample=m.group(0),
            digest=_digest(m.group(0) + str(m.start()), salt),
            target="",
            confidence=0.7,
            line_no=_line_no(text, m.start()),
        ))

    # credit cards (Luhn-valid only; preserve BIN + last 4 for triage)
    for m in _RX_CC.finditer(text):
        digits = "".join(c for c in m.group(0) if c.isdigit())
        if not _luhn_ok(digits):
            continue
        sample = digits[:6] + "*" * (len(digits) - 10) + digits[-4:]
        out.append(Finding(
            category="credit_card",
            sample=sample,
            digest=_digest(digits, salt),
            target=digits[:6],
            confidence=0.7,
            line_no=_line_no(text, m.start()),
        ))

    # SQL dumps
    for m in _RX_INSERT.finditer(text):
        snippet = text[m.start(): m.start() + 80].replace("\n", " ")
        out.append(Finding(
            category="sql_dump",
            sample=snippet,
            digest=_digest(text[m.start(): m.start() + 200], salt),
            target="",
            confidence=0.5,
            line_no=_line_no(text, m.start()),
        ))

    # BIP-39 mnemonic — heuristic, never confident.
    for m in _RX_MNEMONIC.finditer(text):
        words = m.group(0).split()
        if len(set(words)) < len(words) * 0.6:
            continue
        out.append(Finding(
            category="seed_phrase",
            sample=" ".join(_redact(w, 1, 0) for w in words),
            digest=_digest(m.group(0), salt),
            target=str(len(words)),
            confidence=0.4,
            line_no=_line_no(text, m.start()),
        ))

    # Crypto wallet addresses — Base58Check / bech32 / EIP-55 validated.
    out.extend(_scan_crypto(text, salt))

    # Messaging-network contact IDs (Session, SimpleX, Tox, XMPP, ...).
    out.extend(_scan_contacts(text, salt))

    # Breach-context keywords (page-level signal, low confidence).
    for m in _RX_BREACH.finditer(text):
        kw = m.group(0).lower()
        out.append(Finding(
            category="breach_marker",
            sample=kw,
            digest=_digest(kw + str(m.start()), salt),
            target="",
            confidence=0.3,
            line_no=_line_no(text, m.start()),
        ))

    return out


def _crypto_finding(category: str, addr: str, text: str, idx: int,
                    salt: bytes, conf: float) -> Finding:
    """Build a Finding for a wallet address. Stores full address as both target
    and digest input (digest is irreversible; target is the searchable handle)."""
    sample = addr if len(addr) <= 14 else f"{addr[:6]}…{addr[-4:]}"
    return Finding(
        category=category,
        sample=sample,
        digest=_digest(addr.lower(), salt),
        target=addr,
        confidence=conf,
        line_no=_line_no(text, idx),
    )


def _scan_crypto(text: str, salt: bytes) -> list[Finding]:
    out: list[Finding] = []

    for m in _RX_BTC_B58.finditer(text):
        addr = m.group(0)
        # P2PKH (0x00) → "1...", P2SH (0x05) → "3..."
        if _b58check_ok(addr, expected_versions=(0x00, 0x05)):
            out.append(_crypto_finding("btc_address", addr, text, m.start(), salt, 0.95))
    for m in _RX_BTC_BECH32.finditer(text):
        addr = m.group(0)
        if _bech32_ok(addr, expected_hrp="bc"):
            out.append(_crypto_finding("btc_address", addr, text, m.start(), salt, 0.95))

    for m in _RX_LTC_B58.finditer(text):
        addr = m.group(0)
        # LTC P2PKH (0x30 → "L"), P2SH new (0x32 → "M") and legacy (0x05 → "3").
        if _b58check_ok(addr, expected_versions=(0x30, 0x32, 0x05)):
            out.append(_crypto_finding("ltc_address", addr, text, m.start(), salt, 0.9))
    for m in _RX_LTC_BECH32.finditer(text):
        addr = m.group(0)
        if _bech32_ok(addr, expected_hrp="ltc"):
            out.append(_crypto_finding("ltc_address", addr, text, m.start(), salt, 0.95))

    for m in _RX_ETH.finditer(text):
        addr = m.group(0)
        body = addr[2:]
        is_mixed = body.lower() != body and body.upper() != body
        if not _eip55_ok(addr):
            continue
        # Mixed-case verified by Keccak (when available) → high confidence;
        # uniform case → no checksum, lower confidence.
        conf = 0.9 if is_mixed and _keccak256(b"") is not None else 0.55
        out.append(_crypto_finding("eth_address", addr, text, m.start(), salt, conf))

    for m in _RX_TRX.finditer(text):
        addr = m.group(0)
        # TRON mainnet version byte is 0x41.
        if _b58check_ok(addr, expected_versions=(0x41,)):
            out.append(_crypto_finding("trx_address", addr, text, m.start(), salt, 0.95))

    for m in _RX_XMR.finditer(text):
        addr = m.group(0)
        n = len(addr)
        # 95 = standard / subaddress; 106 = integrated (extra payment id).
        # No checksum verified (Keccak required); regex + length is the gate.
        if n in (95, 106) and all(c in _B58_INDEX for c in addr):
            out.append(_crypto_finding("xmr_address", addr, text, m.start(), salt, 0.5))

    return out


def _contact_finding(category: str, contact: str, text: str, idx: int,
                     salt: bytes, conf: float) -> Finding:
    """Build a Finding for a messaging-network contact ID. Stores the
    contact in ``target`` (searchable) and a short preview in ``sample``.
    digest is sha256(salt || lowered contact) so the same handle from
    different pages dedupes."""
    sample = contact if len(contact) <= 40 else f"{contact[:18]}…{contact[-12:]}"
    return Finding(
        category=category,
        sample=sample,
        digest=_digest(contact.lower(), salt),
        target=contact,
        confidence=conf,
        line_no=_line_no(text, idx),
    )


def _scan_contacts(text: str, salt: bytes) -> list[Finding]:
    """Surface messaging-network handles. We intentionally err toward
    *recall* — false positives are harmless because they land on the
    `contacts` view, but missing a Session ID means the user has to
    grep page bodies manually."""
    out: list[Finding] = []
    seen_tox: set[str] = set()
    seen_session: set[str] = set()
    seen_simplex: set[str] = set()
    seen_matrix: set[str] = set()
    seen_briar: set[str] = set()
    seen_ricochet: set[str] = set()

    for m in _RX_SESSION.finditer(text):
        sid = m.group(0).lower()
        if sid in seen_session:
            continue
        seen_session.add(sid)
        out.append(_contact_finding("session_id", sid, text, m.start(), salt, 0.9))

    for m in _RX_SIMPLEX_URI.finditer(text):
        link = m.group(0).rstrip(".,);")  # forums often pin punctuation onto URIs
        if link in seen_simplex:
            continue
        seen_simplex.add(link)
        out.append(_contact_finding("simplex_id", link, text, m.start(), salt, 0.95))
    for m in _RX_SIMPLEX_WEB.finditer(text):
        link = m.group(0).rstrip(".,);")
        if link in seen_simplex:
            continue
        seen_simplex.add(link)
        out.append(_contact_finding("simplex_id", link, text, m.start(), salt, 0.9))

    # Tox 76-hex collides with arbitrary hex blobs (sha256 = 64, sha512 =
    # 128, but 76 is uncommon). We require the surrounding text to look
    # like a contact handover — the word "tox", "tox id", or a clear
    # pubkey label within ~80 chars before the match. Without that, a
    # 76-hex blob is too ambiguous.
    tox_ctx = re.compile(r"\b(tox(?:\s*id)?|pubkey|public[\s_-]?key|chat[\s_-]?id)\b", re.I)
    for m in _RX_TOX.finditer(text):
        tid = m.group(0).upper()
        if tid in seen_tox:
            continue
        window_start = max(0, m.start() - 80)
        if not tox_ctx.search(text[window_start: m.start()]):
            continue
        seen_tox.add(tid)
        out.append(_contact_finding("tox_id", tid, text, m.start(), salt, 0.7))

    # XMPP: explicit URI form is high confidence; the "jabber: user@host"
    # hint is medium; bare addresses are not surfaced (too many emails).
    # Dedupe: the same JID often hits both URI and hint regexes.
    seen_xmpp: set[str] = set()
    for m in _RX_XMPP_URI.finditer(text):
        jid = f"{m.group(1)}@{m.group(2)}"
        key = jid.lower()
        if key in seen_xmpp:
            continue
        seen_xmpp.add(key)
        out.append(_contact_finding("xmpp_jid", jid, text, m.start(), salt, 0.95))
    for m in _RX_XMPP_HINT.finditer(text):
        jid = m.group(1)
        key = jid.lower()
        if key in seen_xmpp:
            continue
        seen_xmpp.add(key)
        out.append(_contact_finding("xmpp_jid", jid, text, m.start(), salt, 0.6))

    for m in _RX_MATRIX.finditer(text):
        mid = f"@{m.group(1)}:{m.group(2)}"
        key = mid.lower()
        if key in seen_matrix:
            continue
        seen_matrix.add(key)
        out.append(_contact_finding("matrix_id", mid, text, m.start(), salt, 0.85))

    for m in _RX_BRIAR.finditer(text):
        link = m.group(0)
        if link in seen_briar:
            continue
        seen_briar.add(link)
        out.append(_contact_finding("briar_link", link, text, m.start(), salt, 0.9))

    for m in _RX_RICOCHET.finditer(text):
        rid = m.group(0)
        if rid in seen_ricochet:
            continue
        seen_ricochet.add(rid)
        out.append(_contact_finding("ricochet_id", rid, text, m.start(), salt, 0.8))

    return out


CATEGORIES = (
    "email_password", "aws_access_key", "aws_secret_key", "github_token",
    "slack_token", "stripe_key", "google_api_key", "discord_token", "jwt",
    "private_key", "pgp_block", "credit_card", "sql_dump", "seed_phrase",
    "breach_marker",
    "btc_address", "ltc_address", "eth_address", "trx_address", "xmr_address",
    "session_id", "simplex_id", "tox_id", "xmpp_jid", "matrix_id",
    "briar_link", "ricochet_id",
)


CONTACT_CATEGORIES = (
    "session_id", "simplex_id", "tox_id", "xmpp_jid", "matrix_id",
    "briar_link", "ricochet_id",
)
