"""PGP public-key harvest from crawled page text.

Many darknet vendors publish a PGP block. We extract the armored block
with regex, and (best-effort) get fingerprint + user IDs by piping it to
`gpg --with-colons --show-keys`. The block itself is always preserved;
fingerprint resolution requires `gpg` on PATH and is otherwise empty.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass


_KEY_BLOCK_RX = re.compile(
    r"-----BEGIN PGP PUBLIC KEY BLOCK-----"
    r".*?"
    r"-----END PGP PUBLIC KEY BLOCK-----",
    re.DOTALL,
)


def gpg_available() -> bool:
    return shutil.which("gpg") is not None


@dataclass(frozen=True)
class PgpKey:
    block: str
    fingerprint: str
    user_ids: tuple[str, ...]


def _show_keys(block: str) -> tuple[str, list[str]]:
    """Return (fingerprint, user_ids). Empty strings on failure."""
    if not gpg_available():
        return "", []
    try:
        p = subprocess.run(
            ["gpg", "--with-colons", "--show-keys"],
            input=block.encode("utf-8", "replace"),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return "", []
    fpr = ""
    uids: list[str] = []
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        cols = line.split(":")
        if not cols:
            continue
        if cols[0] == "fpr" and len(cols) >= 10 and not fpr:
            fpr = cols[9]
        elif cols[0] == "uid" and len(cols) >= 10:
            uids.append(cols[9])
    return fpr, uids


def extract_keys(text: str) -> list[PgpKey]:
    if not text:
        return []
    out: list[PgpKey] = []
    for m in _KEY_BLOCK_RX.finditer(text):
        block = m.group(0)
        fpr, uids = _show_keys(block)
        out.append(PgpKey(block=block, fingerprint=fpr, user_ids=tuple(uids)))
    return out
