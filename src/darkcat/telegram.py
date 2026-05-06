"""Scrape Telegram channels via the t.me/s/<channel> web preview.

t.me/s/<channel> serves rendered HTML of recent messages — no auth, no
API key, no tdlib. Each message has a permalink, ISO datetime, body text,
and any inline links. We optionally ingest each message into the pages
table so the leak scanner sees it like any other crawled page.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

from darkcat.fetcher import Fetcher


@dataclass(frozen=True)
class TgMessage:
    channel: str
    msg_id: str
    permalink: str
    datetime_iso: str
    text: str
    links: list[str]


def _parse_messages(channel: str, html: bytes) -> list[TgMessage]:
    soup = BeautifulSoup(html, "lxml")
    out: list[TgMessage] = []
    for box in soup.select("div.tgme_widget_message"):
        link_el = box.select_one("a.tgme_widget_message_date")
        permalink = (link_el.get("href") if link_el else "") or ""
        time_el = box.select_one("a.tgme_widget_message_date time")
        dt = (time_el.get("datetime") if time_el else "") or ""
        msg_id = ""
        if permalink:
            msg_id = permalink.rstrip("/").rsplit("/", 1)[-1]
        text_el = box.select_one("div.tgme_widget_message_text")
        text = text_el.get_text(" ", strip=True) if text_el else ""
        links: list[str] = []
        if text_el:
            for a in text_el.select("a[href]"):
                href = (a.get("href") or "").strip()
                if href:
                    links.append(href)
        out.append(TgMessage(
            channel=channel, msg_id=msg_id, permalink=permalink,
            datetime_iso=dt, text=text, links=links,
        ))
    return out


def fetch_channel(
    fetcher: Fetcher,
    channel: str,
    *,
    limit: Optional[int] = None,
    pages: int = 1,
) -> list[TgMessage]:
    """Fetch the latest messages from t.me/s/<channel>. With pages>1 follow
    the `?before=` pagination back into older messages."""
    channel = channel.lstrip("@/")
    url = f"https://t.me/s/{channel}"
    out: list[TgMessage] = []
    seen: set[str] = set()
    for _ in range(max(1, pages)):
        try:
            r = fetcher.fetch(url)
        except Exception:
            break
        if not r or not r.body:
            break
        body = r.body if isinstance(r.body, (bytes, bytearray)) else r.body.encode("utf-8")
        msgs = _parse_messages(channel, body)
        if not msgs:
            break
        new_msgs: list[TgMessage] = []
        for m in msgs:
            if m.msg_id and m.msg_id not in seen:
                seen.add(m.msg_id)
                new_msgs.append(m)
        out.extend(new_msgs)
        if limit and len(out) >= limit:
            return out[:limit]
        # next page: oldest numeric msg_id becomes ?before=
        numeric_ids = [int(m.msg_id) for m in new_msgs if m.msg_id.isdigit()]
        if not numeric_ids:
            break
        url = f"https://t.me/s/{channel}?before={min(numeric_ids)}"
    return out[:limit] if limit else out
