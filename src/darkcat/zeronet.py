"""Walk a ZeroNet site via the local UI, fetching every file under content.json.

ZeroNet sites expose a JSON manifest at `<site>/content.json` listing every
file in the site (`files` key) and any nested manifests (`includes` key).
We fetch each one through the regular fetcher (which routes `zero://` URLs
to the local ZeroNet UI). Useful when an entry page only links the root.
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Callable, Iterator, Optional

from darkcat.fetcher import Fetcher


def walk_site(
    fetcher: Fetcher,
    site_address: str,
    *,
    limit: int = 100,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> Iterator[tuple[str, bytes, str]]:
    """Yield (url, body, content_type) for each file referenced from
    <site>/content.json (recursing into includes)."""
    site_address = site_address.strip("/")
    base = f"zero://{site_address}/"
    seen: set[str] = set()
    queue: list[str] = ["content.json"]
    n = 0

    def emit(kind: str, **kw) -> None:
        if on_event:
            try:
                on_event(kind, kw)
            except Exception:
                pass

    while queue and n < limit:
        rel = queue.pop(0)
        if rel in seen:
            continue
        seen.add(rel)
        full = urllib.parse.urljoin(base, rel)
        emit("fetch", url=full)
        try:
            r = fetcher.fetch(full)
        except Exception as e:
            emit("error", url=full, error=str(e))
            continue
        if not r or not r.body:
            continue
        body = r.body if isinstance(r.body, (bytes, bytearray)) else r.body.encode("utf-8")
        ct = r.content_type or ""
        yield (full, body, ct)
        n += 1
        if rel.endswith("content.json"):
            try:
                d = json.loads(body)
            except Exception:
                continue
            for f in (d.get("files") or {}):
                if isinstance(f, str):
                    queue.append(f)
            for inc in (d.get("includes") or {}):
                if isinstance(inc, str):
                    queue.append(inc)
