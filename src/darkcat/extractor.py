"""HTML / Gemini / Gopher parsing — title, plain text, link extraction."""
from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin, urldefrag, urlparse, quote

from bs4 import BeautifulSoup


# urllib.parse only resolves relative refs for a known list of schemes.
# Register the obscure ones we care about so urljoin works correctly.
for _s in ("gemini", "gopher", "gophers", "hyper", "ipfs", "ipns", "freenet", "hyphanet", "zero"):
    if _s not in urllib.parse.uses_relative:
        urllib.parse.uses_relative.append(_s)
    if _s not in urllib.parse.uses_netloc:
        urllib.parse.uses_netloc.append(_s)


_BAD_SCHEMES = ("mailto:", "javascript:", "data:", "tel:", "magnet:", "irc:")
_GEMINI_LINK_RE = re.compile(r"^=>\s*(\S+)(?:\s+(.+))?\s*$")


@dataclass
class Page:
    url: str
    title: str
    text: str
    links: list[str]


def _decode(body: bytes, content_type: str) -> str:
    encoding = "utf-8"
    ct = (content_type or "").lower()
    if "charset=" in ct:
        encoding = ct.split("charset=", 1)[1].split(";")[0].strip()
    try:
        return body.decode(encoding, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return body.decode("utf-8", errors="replace")


def parse(url: str, body: bytes, content_type: str = "") -> Page:
    if not body:
        return Page(url=url, title="", text="", links=[])
    ct = (content_type or "").lower()

    # Per-site plugins get first crack. They can return None to defer to the
    # generic parsers below. Imported lazily so users without the plugin code
    # path (e.g. one-shot scripts importing parse() directly) don't pay the
    # plugin-discovery cost.
    try:
        from darkcat.plugins import parse_with_plugins
        page = parse_with_plugins(url, body, content_type)
        if page is not None:
            return page
    except Exception:
        pass

    if "gemini" in ct or url.startswith("gemini://"):
        return _parse_gemini(url, _decode(body, content_type))
    if "gopher-menu" in ct or url.startswith("gopher://"):
        return _parse_gopher(url, _decode(body, content_type))
    if _looks_like_html(ct, body):
        return _parse_html(url, _decode(body, content_type))
    return Page(url=url, title="", text=_decode(body, content_type)[:200_000], links=[])


def _looks_like_html(content_type: str, body: bytes) -> bool:
    if content_type and "html" in content_type:
        return True
    head = body[:512].lower()
    return b"<html" in head or b"<!doctype html" in head


def _parse_html(url: str, html: str) -> Page:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    title = (soup.title.string.strip() if soup.title and soup.title.string else "").strip()
    text = " ".join(soup.get_text(" ").split())
    links = list(_iter_html_links(soup, url))
    return Page(url=url, title=title, text=text, links=links)


def _iter_html_links(soup: BeautifulSoup, base_url: str) -> Iterable[str]:
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(_BAD_SCHEMES):
            continue
        absolute = urljoin(base_url, href)
        absolute, _ = urldefrag(absolute)
        if absolute in seen:
            continue
        seen.add(absolute)
        yield absolute


def _parse_gemini(url: str, text: str) -> Page:
    """Parse gemtext: '=> URL [label]' lines are links, '# title' is title."""
    title = ""
    body_lines: list[str] = []
    links: list[str] = []
    seen: set[str] = set()
    in_pre = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_pre = not in_pre
            continue
        if in_pre:
            body_lines.append(line)
            continue
        if not title and line.startswith("# "):
            title = line[2:].strip()
        m = _GEMINI_LINK_RE.match(line)
        if m:
            target = m.group(1)
            label = (m.group(2) or "").strip()
            absolute = urljoin(url, target)
            absolute, _ = urldefrag(absolute)
            if absolute not in seen:
                seen.add(absolute)
                links.append(absolute)
            if label:
                body_lines.append(label)
        else:
            stripped = line.strip()
            if stripped:
                body_lines.append(stripped)
    return Page(url=url, title=title, text=" ".join(body_lines), links=links)


def _parse_gopher(url: str, menu: str) -> Page:
    """Parse a Gopher menu: type|display TAB selector TAB host TAB port CRLF."""
    parsed = urlparse(url)
    title_candidates: list[str] = []
    body_lines: list[str] = []
    links: list[str] = []
    seen: set[str] = set()
    for raw in menu.splitlines():
        if raw == "." or not raw:
            continue
        type_char = raw[:1]
        rest = raw[1:]
        parts = rest.split("\t")
        display = parts[0] if parts else ""
        selector = parts[1] if len(parts) > 1 else ""
        host = parts[2] if len(parts) > 2 else parsed.hostname or ""
        port = parts[3] if len(parts) > 3 else str(parsed.port or 70)
        if type_char == "i":
            body_lines.append(display)
            if not title_candidates and display:
                title_candidates.append(display)
        elif type_char in "01gIhM+sT":
            if type_char == "h" and selector.startswith("URL:"):
                target = selector[4:]
            else:
                target = f"gopher://{host}:{port}/{type_char}{quote(selector)}"
            if target not in seen:
                seen.add(target)
                links.append(target)
            body_lines.append(display)
    title = title_candidates[0] if title_candidates else ""
    return Page(url=url, title=title, text=" ".join(body_lines), links=links)
