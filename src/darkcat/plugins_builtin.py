"""Built-in site plugins shipped with darkcat.

Currently ships:

* :class:`DreadPlugin` — Dread forum (``dread*.onion``). Pulls post bodies
  out of ``.preview`` / ``.post-content`` divs and surfaces ``/post/<id>``
  links the generic parser tends to drown in nav chrome.
* :class:`TelegramSPlugin` — ``t.me/s/<channel>`` web mirror. Channel
  messages live inside ``.tgme_widget_message_text``; the generic parser
  picks up reaction emoji and trailing nav links instead. The dedicated
  :mod:`darkcat.telegram` scraper is still the high-fidelity path; this
  plugin just makes drive-by crawls extract something useful.
* :class:`PastebinishPlugin` — sites with a single ``<pre>`` of dumped
  text (deepweb pastebins, doxbins, breach mirrors). The generic parser
  collapses whitespace and loses the dump structure; this preserves it.

Each plugin is intentionally small. When a host needs more — e.g.,
parsing 200 posts spread across 10 paginated URLs — write a dedicated
plugin and drop it in ``~/.darkcat/plugins/``.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin, urldefrag, urlparse

from bs4 import BeautifulSoup

from darkcat.extractor import Page, _decode


class DreadPlugin:
    name = "dread"

    def matches(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        # Dread cycles addresses; match generously on the prefix.
        return host.startswith("dread") and host.endswith(".onion")

    def parse(self, url: str, body: bytes, content_type: str) -> Optional[Page]:
        if not body:
            return None
        html = _decode(body, content_type)
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()

        title = ""
        # Dread thread titles are in <h1.title>; subforum index uses <h2>.
        h = soup.find(["h1", "h2"], class_=["title", "subtitle"])
        if h and h.text:
            title = h.text.strip()
        elif soup.title and soup.title.string:
            title = soup.title.string.strip()

        chunks: list[str] = []
        # Posts / comments — both forum threads and user pages.
        for sel in (".preview", ".post-content", ".post", ".comment"):
            for el in soup.select(sel):
                t = el.get_text(" ", strip=True)
                if t:
                    chunks.append(t)
        text = " ".join(chunks) if chunks else " ".join(soup.get_text(" ").split())

        seen: set[str] = set()
        links: list[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("javascript:", "mailto:", "#")):
                continue
            absolute, _ = urldefrag(urljoin(url, href))
            if absolute in seen:
                continue
            seen.add(absolute)
            links.append(absolute)
        return Page(url=url, title=title, text=text, links=links)


class TelegramSPlugin:
    name = "telegram-s"

    def matches(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        path = urlparse(url).path
        return host in ("t.me", "telegram.me") and path.startswith("/s/")

    def parse(self, url: str, body: bytes, content_type: str) -> Optional[Page]:
        if not body:
            return None
        html = _decode(body, content_type)
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        # Channel name is in og:title or <a.tgme_channel_info_header_title>.
        title = ""
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()
        msgs = []
        for el in soup.select(".tgme_widget_message_text"):
            t = el.get_text(" ", strip=True)
            if t:
                msgs.append(t)
        text = "\n".join(msgs) if msgs else " ".join(soup.get_text(" ").split())
        seen: set[str] = set()
        links: list[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("javascript:", "mailto:")):
                continue
            absolute, _ = urldefrag(urljoin(url, href))
            if absolute in seen:
                continue
            seen.add(absolute)
            links.append(absolute)
        return Page(url=url, title=title, text=text, links=links)


class PastebinishPlugin:
    """Generic catch-all for pastebin-style pages: a single dominant ``<pre>``
    block with the dumped text. The plugin matches by *content shape* rather
    than host, so it handles drop-bin clones we haven't seen before.

    Specifically: fires when a page has at least one ``<pre>`` whose text is
    longer than the rest of the page's textual content. Conservative on
    purpose — false positives just mean we keep raw text we'd otherwise lose
    to whitespace collapsing."""
    name = "pastebinish"
    is_catch_all = True  # body-shape decision, not host-based

    def matches(self, url: str) -> bool:
        # We can't decide without the body; return True and let parse() bail.
        return True

    def parse(self, url: str, body: bytes, content_type: str) -> Optional[Page]:
        if not body:
            return None
        ct = (content_type or "").lower()
        if "html" not in ct and b"<html" not in body[:512].lower():
            return None
        html = _decode(body, content_type)
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        pre_blocks = soup.find_all("pre")
        if not pre_blocks:
            return None
        # Find the largest <pre> and the rest of the page text.
        largest = max(pre_blocks, key=lambda el: len(el.get_text() or ""))
        pre_text = largest.get_text() or ""
        if len(pre_text) < 400:
            return None
        # Strip the <pre> blocks and check that what's left is "small" — i.e.
        # the page is dominated by the dump.
        for el in pre_blocks:
            el.decompose()
        rest = " ".join(soup.get_text(" ").split())
        if len(pre_text) < 2 * max(1, len(rest)):
            return None  # not actually pastebin-shaped
        title = (soup.title.string.strip()
                 if soup.title and soup.title.string else "")
        # Preserve newlines in the dump but stay under the page-text cap.
        text = pre_text[:200_000]
        return Page(url=url, title=title, text=text, links=[])


PLUGINS: list = [
    DreadPlugin(),
    TelegramSPlugin(),
    PastebinishPlugin(),
]


__all__ = [
    "DreadPlugin", "TelegramSPlugin", "PastebinishPlugin", "PLUGINS",
]
