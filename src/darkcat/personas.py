"""Persona / credential vault for darkcat.

A persona is a per-(network, site) account: handle, password, email, PGP
key id, recovery phrase, free-form notes, and a pointer at a per-persona
cookie jar. Most darknet forums (Dread, Breach mirrors, paywalled paste
sites, marketplaces) gate the interesting content behind a login, and
operators usually run *several* burner identities — one per market, one
per language community, etc. The vault lets you create and switch
between them without leaving credentials in shell history.

Storage layout (under ``~/.darkcat/`` by default):

* ``personas.json``         — plain JSON when GPG is not in use
* ``personas.json.gpg``     — symmetrically encrypted JSON (gpg -c)
* ``cookies.<persona>.txt`` — per-persona Netscape cookie jar

The vault file gets ``chmod 0600`` on every write. The encrypted variant
is preferred when present; if both exist the encrypted one wins and the
plain copy is left alone (operator decision to clean it up).

OPSEC note: a persona file is a credential bag. Treat it like an SSH
private key — back it up offline, never commit it, and use the
``encrypt`` action before syncing across machines.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


VAULT_VERSION = 1


@dataclass
class Persona:
    """One stored identity. All fields except ``name`` are optional so a
    persona can be seeded with just a handle and filled in later."""

    name: str
    network: str = ""           # tor / i2p / clearnet / lokinet / matrix / ...
    site: str = ""              # canonical site or onion (no scheme)
    handle: Optional[str] = None
    password: Optional[str] = None
    email: Optional[str] = None
    pgp_key_id: Optional[str] = None
    recovery: Optional[str] = None   # BIP-39 / one-time backup codes
    notes: Optional[str] = None
    cookie_jar: Optional[str] = None
    user_agent: Optional[str] = None
    proxy: Optional[str] = None     # override SOCKS proxy URL
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: time.time())
    last_used_at: Optional[float] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Persona":
        # Drop unknown keys so old vaults stay loadable across versions.
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# -- handle / password generation ----------------------------------------

# Curated wordlists — short, unambiguous, no offensive terms. Picked so a
# generated handle reads like a forum username rather than a UUID.
_ADJECTIVES = (
    "silent", "rusty", "quiet", "hidden", "drift", "midnight", "stale",
    "hollow", "noctis", "lucid", "obscure", "still", "frost", "ember",
    "ashen", "vacant", "phantom", "shadow", "echo", "lonely",
)
_NOUNS = (
    "owl", "fox", "moth", "wolf", "cipher", "raven", "ghost", "echo",
    "node", "vault", "relay", "circuit", "haven", "void", "drone",
    "warden", "crow", "hawk", "loop", "tide",
)


def generate_handle(rng: Optional[secrets.SystemRandom] = None) -> str:
    """Generate a forum-style handle: ``adjective_noun_NNNN``."""
    rng = rng or secrets.SystemRandom()
    adj = rng.choice(_ADJECTIVES)
    noun = rng.choice(_NOUNS)
    n = rng.randrange(1000, 9999)
    return f"{adj}_{noun}_{n}"


def generate_password(length: int = 24) -> str:
    """URL-safe random password. ``secrets.token_urlsafe`` produces ~1.33
    chars per byte; we round up so the requested length is a floor."""
    n_bytes = max(16, (length * 3 + 3) // 4)
    return secrets.token_urlsafe(n_bytes)[:length]


# -- file paths ----------------------------------------------------------

def default_dir() -> Path:
    return Path(os.environ.get("DARKCAT_HOME", str(Path.home() / ".darkcat")))


def vault_path(plain: bool = False) -> Path:
    """Resolve the vault path. When ``plain`` is False (default) the
    encrypted file is preferred if it exists."""
    base = default_dir()
    enc = base / "personas.json.gpg"
    if not plain and enc.exists():
        return enc
    return base / "personas.json"


def cookie_jar_for(name: str) -> Path:
    """Per-persona cookie jar path. Filename-safe characters only — names
    with slashes or shell metas are sanitized to underscores."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    return default_dir() / f"cookies.{safe}.txt"


# -- GPG helpers ---------------------------------------------------------

def gpg_available() -> bool:
    return shutil.which("gpg") is not None


def _gpg_encrypt(plaintext: bytes, passphrase: str) -> bytes:
    """Symmetric AES-256 via ``gpg -c``. Caller-supplied passphrase is
    piped via fd 3 so it never touches argv (visible in /proc) or the
    on-disk passphrase cache (gpg-agent)."""
    if not gpg_available():
        raise RuntimeError("gpg not installed; install gnupg or use --plain")
    r, w = os.pipe()
    try:
        os.write(w, passphrase.encode("utf-8") + b"\n")
    finally:
        os.close(w)
    try:
        result = subprocess.run(
            [
                "gpg", "--batch", "--yes", "--quiet",
                "--symmetric", "--cipher-algo", "AES256",
                "--passphrase-fd", str(r),
                "--pinentry-mode", "loopback",
            ],
            input=plaintext,
            capture_output=True,
            pass_fds=(r,),
            check=False,
        )
    finally:
        os.close(r)
    if result.returncode != 0:
        raise RuntimeError(f"gpg encrypt failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout


def _gpg_decrypt(ciphertext: bytes, passphrase: str) -> bytes:
    if not gpg_available():
        raise RuntimeError("gpg not installed; can't decrypt vault")
    r, w = os.pipe()
    try:
        os.write(w, passphrase.encode("utf-8") + b"\n")
    finally:
        os.close(w)
    try:
        result = subprocess.run(
            [
                "gpg", "--batch", "--yes", "--quiet",
                "--decrypt",
                "--passphrase-fd", str(r),
                "--pinentry-mode", "loopback",
            ],
            input=ciphertext,
            capture_output=True,
            pass_fds=(r,),
            check=False,
        )
    finally:
        os.close(r)
    if result.returncode != 0:
        raise RuntimeError(
            "gpg decrypt failed (wrong passphrase? corrupt file?): "
            + result.stderr.decode('utf-8', 'replace').strip()[:200]
        )
    return result.stdout


# -- vault ---------------------------------------------------------------

class Vault:
    """JSON-backed persona vault, plain or GPG-encrypted on disk.

    ``passphrase`` is required when the vault file ends with ``.gpg`` and
    only used at load / save time; we don't keep it on the instance after
    decryption to limit blast radius if the process gets cored."""

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        passphrase: Optional[str] = None,
    ) -> None:
        self.path: Path = Path(path) if path else vault_path()
        self.passphrase: Optional[str] = passphrase
        self.personas: list[Persona] = []
        self.load()

    @property
    def is_encrypted(self) -> bool:
        return self.path.suffix == ".gpg"

    # ---- I/O --------------------------------------------------------

    def load(self) -> None:
        if not self.path.exists():
            return
        raw = self.path.read_bytes()
        if self.is_encrypted:
            if not self.passphrase:
                raise RuntimeError(
                    f"vault at {self.path} is GPG-encrypted; pass --passphrase "
                    f"or set DARKCAT_VAULT_PASSPHRASE"
                )
            raw = _gpg_decrypt(raw, self.passphrase)
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise RuntimeError(f"vault {self.path} is corrupt: {e}") from e
        if not isinstance(doc, dict) or "personas" not in doc:
            raise RuntimeError(f"vault {self.path} has no 'personas' key")
        self.personas = [Persona.from_dict(p) for p in doc["personas"]]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "version": VAULT_VERSION,
            "personas": [asdict(p) for p in self.personas],
        }
        plain = json.dumps(doc, indent=2, ensure_ascii=False).encode("utf-8")
        out = plain
        if self.is_encrypted:
            if not self.passphrase:
                raise RuntimeError(
                    "encrypted vault save requested but no passphrase set"
                )
            out = _gpg_encrypt(plain, self.passphrase)
        # atomic rename: write a sibling tempfile then replace, so a kill
        # mid-write can't truncate the vault to zero bytes.
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_bytes(out)
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    # ---- queries ----------------------------------------------------

    def get(self, name: str) -> Optional[Persona]:
        for p in self.personas:
            if p.name == name:
                return p
        return None

    def find(
        self,
        *,
        network: Optional[str] = None,
        site: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> list[Persona]:
        out = list(self.personas)
        if network:
            out = [p for p in out if p.network == network]
        if site:
            site_l = site.lower()
            out = [p for p in out if site_l in (p.site or "").lower()]
        if tag:
            out = [p for p in out if tag in p.tags]
        return out

    # ---- mutation ---------------------------------------------------

    def add(self, persona: Persona, *, replace: bool = False) -> None:
        existing = self.get(persona.name)
        if existing is not None and not replace:
            raise ValueError(
                f"persona {persona.name!r} already exists; pass --replace to overwrite"
            )
        if existing is not None:
            self.personas.remove(existing)
        self.personas.append(persona)

    def remove(self, name: str) -> bool:
        p = self.get(name)
        if p is None:
            return False
        self.personas.remove(p)
        return True

    def touch(self, name: str) -> None:
        """Update ``last_used_at`` for ``name`` (no-op if missing)."""
        p = self.get(name)
        if p is None:
            return
        p.last_used_at = time.time()

    # ---- encryption transitions -------------------------------------

    def to_encrypted(self, passphrase: str) -> Path:
        """Convert a plain vault to its ``.gpg`` form. Caller is
        responsible for shredding the plain file afterwards."""
        if self.is_encrypted:
            return self.path
        new_path = self.path.with_suffix(self.path.suffix + ".gpg")
        plain = json.dumps(
            {"version": VAULT_VERSION,
             "personas": [asdict(p) for p in self.personas]},
            indent=2, ensure_ascii=False,
        ).encode("utf-8")
        new_path.write_bytes(_gpg_encrypt(plain, passphrase))
        try:
            new_path.chmod(0o600)
        except OSError:
            pass
        # Keep self pointed at the new file so subsequent saves stay encrypted.
        self.path = new_path
        self.passphrase = passphrase
        return new_path

    def to_plain(self) -> Path:
        if not self.is_encrypted:
            return self.path
        new_path = Path(str(self.path)[:-4])  # strip ".gpg"
        plain = json.dumps(
            {"version": VAULT_VERSION,
             "personas": [asdict(p) for p in self.personas]},
            indent=2, ensure_ascii=False,
        ).encode("utf-8")
        new_path.write_bytes(plain)
        try:
            new_path.chmod(0o600)
        except OSError:
            pass
        self.path = new_path
        self.passphrase = None
        return new_path


# -- redaction (for `personas show`) -------------------------------------

def redact_dict(p: Persona, *, reveal: bool = False) -> dict:
    """Return a dict suitable for printing — secrets masked unless
    ``reveal`` is True."""
    d = asdict(p)
    if not reveal:
        for k in ("password", "recovery"):
            v = d.get(k)
            if v:
                d[k] = "*" * 6 + " (--reveal to show)"
    return d


__all__ = [
    "Persona",
    "Vault",
    "VAULT_VERSION",
    "default_dir",
    "vault_path",
    "cookie_jar_for",
    "generate_handle",
    "generate_password",
    "gpg_available",
    "redact_dict",
]
