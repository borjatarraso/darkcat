"""Sitemap / RSS / Atom / JSON-Feed / WebFinger discovery helpers.

Probes well-known paths under a base URL and parses any responses as
sitemap, RSS, Atom, or JSON-Feed. Useful for surfacing pages a homepage
doesn't link to.
"""
from __future__ import annotations

import json
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Callable, Iterable, Optional

from darkcat.fetcher import Fetcher


WELL_KNOWN_PATHS: tuple[str, ...] = (
    "sitemap.xml",
    "sitemap_index.xml",
    "sitemap-index.xml",
    "feed",
    "feed/",
    "feed.xml",
    "feed/atom",
    "feed.json",
    "rss",
    "rss.xml",
    "atom.xml",
    "atom/",
    "index.xml",
    ".well-known/host-meta",
    ".well-known/security.txt",
)


def _xml_links(body: bytes) -> list[str]:
    out: list[str] = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return out
    for el in root.iter():
        tag = el.tag.split("}", 1)[-1].lower()
        if tag == "loc" and el.text:
            out.append(el.text.strip())
        elif tag == "link":
            href = el.get("href")
            if href:
                out.append(href.strip())
            elif el.text:
                out.append(el.text.strip())
    return out


def _json_links(body: bytes) -> list[str]:
    try:
        d = json.loads(body)
    except Exception:
        return []
    out: list[str] = []
    if isinstance(d, dict):
        for item in d.get("items", []) or []:
            if isinstance(item, dict):
                u = item.get("url") or item.get("external_url")
                if isinstance(u, str):
                    out.append(u)
    return out


def discover_feeds(
    fetcher: Fetcher,
    base_url: str,
    *,
    paths: Iterable[str] = WELL_KNOWN_PATHS,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> list[str]:
    """Try well-known feed/sitemap paths under `base_url`. Return all URLs."""
    parsed = urllib.parse.urlparse(base_url)
    if not parsed.scheme:
        base_url = "http://" + base_url
        parsed = urllib.parse.urlparse(base_url)
    base = f"{parsed.scheme}://{parsed.netloc}/"
    seen: set[str] = set()
    out: list[str] = []

    def emit(kind: str, **kw) -> None:
        if on_event:
            try:
                on_event(kind, kw)
            except Exception:
                pass

    def add(urls: Iterable[str]) -> int:
        added = 0
        for u in urls:
            absu = urllib.parse.urljoin(base, u.strip())
            if absu in seen:
                continue
            seen.add(absu)
            out.append(absu)
            added += 1
        return added

    for path in paths:
        url = urllib.parse.urljoin(base, path)
        emit("try", url=url)
        try:
            r = fetcher.fetch(url)
        except Exception as e:
            emit("miss", url=url, error=str(e))
            continue
        if not r or not r.body or (r.status and r.status >= 400):
            emit("miss", url=url, status=getattr(r, "status", 0))
            continue
        ct = (r.content_type or "").lower()
        if "json" in ct or path.endswith(".json"):
            added = add(_json_links(r.body))
        else:
            added = add(_xml_links(r.body))
        emit("hit", url=url, links=added)
    return out
