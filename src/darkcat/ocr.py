"""Image OCR via Tesseract.

Many onion sites image-encode text to dodge crawlers. OCR'd text feeds
back into the topic filter and the leak scanner with no other changes —
the only requirement is `tesseract` on $PATH.
"""
from __future__ import annotations

import shutil
import subprocess
import urllib.parse
from typing import Iterable

from bs4 import BeautifulSoup

from darkcat.fetcher import Fetcher


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def extract_image_text(
    image_bytes: bytes, *, lang: str = "eng", timeout: float = 30.0,
) -> str:
    """Run tesseract over `image_bytes` and return the recognized text."""
    if not image_bytes or not ocr_available():
        return ""
    try:
        p = subprocess.run(
            ["tesseract", "-l", lang, "stdin", "stdout"],
            input=image_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return (p.stdout or b"").decode("utf-8", "replace")


def image_urls(html: bytes, base_url: str) -> list[str]:
    """Extract <img src> / data-src URLs (absolute) from an HTML body."""
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        absu = urllib.parse.urljoin(base_url, src.strip())
        if absu in seen:
            continue
        seen.add(absu)
        out.append(absu)
    return out


def ocr_page(
    fetcher: Fetcher,
    page_url: str,
    *,
    lang: str = "eng",
    max_images: int = 20,
    on_event=None,
) -> list[tuple[str, str]]:
    """Fetch page_url, OCR every <img>, return [(image_url, text)]."""
    if not ocr_available():
        if on_event:
            on_event("warn", {"msg": "tesseract not installed"})
        return []
    try:
        r = fetcher.fetch(page_url)
    except Exception as e:
        if on_event:
            on_event("error", {"url": page_url, "error": str(e)})
        return []
    body = r.body if isinstance(r.body, (bytes, bytearray)) else (r.body or "").encode("utf-8")
    urls = image_urls(body, r.final_url)[:max_images]
    out: list[tuple[str, str]] = []
    for iu in urls:
        if on_event:
            on_event("image", {"url": iu})
        try:
            ir = fetcher.fetch(iu)
        except Exception as e:
            if on_event:
                on_event("error", {"url": iu, "error": str(e)})
            continue
        if not ir or not ir.body:
            continue
        ib = ir.body if isinstance(ir.body, (bytes, bytearray)) else ir.body.encode("utf-8")
        text = extract_image_text(ib, lang=lang).strip()
        if text:
            out.append((iu, text))
            if on_event:
                on_event("ocr", {"url": iu, "chars": len(text)})
    return out
