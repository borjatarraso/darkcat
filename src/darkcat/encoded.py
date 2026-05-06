"""Find URLs hidden inside JS strings, base64 blobs, or ROT13.

Markets and forums routinely encode their mirror lists. The standard HTML
extractor only sees `<a href="...">`; this module rescues URLs from:

  - inline JS / JSON / data attributes (literal strings)
  - base64 chunks that decode to URL-bearing text
  - ROT13'd hostnames or URLs (`uggc://...`, `.bavba`)

It is intentionally noisy — callers should dedup against the parser's own
link list.
"""
from __future__ import annotations

import base64
import codecs
import re


_URL_RX = re.compile(
    r"\b((?:https?|gemini|gopher|gophers|spartan|nex|ipfs|ipns|hyper|"
    r"freenet|hyphanet|zero|ssb|dat)://"
    r"[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]{4,300})",
    re.I,
)
_ROT13_HINT_RX = re.compile(
    r"\buggcf?://[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]{4,300}", re.I
)
_B64_RX = re.compile(r"[A-Za-z0-9+/]{32,}={0,2}")


def _scan(text: str, into: set) -> None:
    for m in _URL_RX.finditer(text):
        into.add(m.group(1).rstrip(".,;:)"))


def _try_b64(chunk: str, into: set) -> None:
    pad = "=" * ((4 - len(chunk) % 4) % 4)
    try:
        decoded = base64.b64decode(chunk + pad, validate=False)
    except Exception:
        return
    try:
        s = decoded.decode("utf-8", "replace")
    except Exception:
        return
    _scan(s, into)


def extract_encoded_links(text: str) -> list[str]:
    """Return a sorted list of URLs found via JS/base64/ROT13 scanning."""
    if not text:
        return []
    out: set[str] = set()
    _scan(text, out)
    for m in _ROT13_HINT_RX.finditer(text):
        decoded = codecs.decode(m.group(0), "rot_13")
        _scan(decoded, out)
    for m in _B64_RX.finditer(text):
        _try_b64(m.group(0), out)
    return sorted(out)
