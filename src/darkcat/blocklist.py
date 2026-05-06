"""Abuse blocklist — hard-skip URLs / hosts / content hashes we never want.

File format: one rule per line, comments with `#`. Rule prefixes:

    host:HOSTNAME           exact host match
    .SUFFIX                 host suffix (e.g. ".bad.onion")
    urlcontains:SUBSTR      URL substring match
    hash:HEX                exact SHA-256 of decoded page text
    HOSTNAME                bare line → exact host match

Blocked URLs are skipped before fetching (host/url rules) or after
fetching but before storing (hash rule), and audited in `blocklist_audit`.
Use this to keep CSAM, dox archives, or anything else off the local DB.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


class Blocklist:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.hosts: set[str] = set()
        self.host_suffixes: list[str] = []
        self.url_substrings: list[str] = []
        self.hashes: set[str] = set()
        self.path: Optional[Path] = Path(path) if path else None
        if self.path:
            self.load(self.path)

    def load(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8", errors="replace")
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            low = line.lower()
            if low.startswith("hash:"):
                self.hashes.add(low[5:].strip())
            elif low.startswith("host:"):
                self.hosts.add(low[5:].strip())
            elif low.startswith("urlcontains:"):
                self.url_substrings.append(line[len("urlcontains:"):].strip())
            elif low.startswith("."):
                self.host_suffixes.append(low)
            else:
                self.hosts.add(low)

    @property
    def is_empty(self) -> bool:
        return not (
            self.hosts
            or self.host_suffixes
            or self.url_substrings
            or self.hashes
        )

    def reason_for_url(self, url: str) -> Optional[str]:
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            host = ""
        if host and host in self.hosts:
            return f"host:{host}"
        for suffix in self.host_suffixes:
            if host and host.endswith(suffix):
                return f"host_suffix:{suffix}"
        for sub in self.url_substrings:
            if sub and sub in url:
                return f"url:{sub}"
        return None

    def reason_for_hash(self, content_hash: str) -> Optional[str]:
        h = (content_hash or "").lower()
        return f"hash:{h}" if h in self.hashes else None

    @staticmethod
    def hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
