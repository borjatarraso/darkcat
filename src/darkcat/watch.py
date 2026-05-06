"""Watchlist + alerting for darkcat findings.

A watch entry has a match pattern (against `target` / `category` / `sample`
of a Finding) plus a sink. When `scan` records a *new* finding that
matches an active watch, the sink fires and the alert is appended to the
`alerts` table.

Sink syntax:
    log                              print to stdout (audit-friendly)
    notify                           libnotify desktop notification (notify-send)
    file:/path                       append one JSON object per alert
    webhook:URL                      HTTP POST a JSON payload to URL
    slack:WEBHOOK_URL                Slack incoming-webhook (formatted text)
    discord:WEBHOOK_URL              Discord incoming-webhook (formatted text)
    matrix:HOMESERVER|ROOM_ID|TOKEN  Matrix m.room.message (text body)
    email:to@host                    SMTP via DARKCAT_SMTP_* env vars

Pipe ``|`` is used as the separator inside ``matrix:`` because room IDs and
URLs both contain ``:``. The Matrix segment order is intentional — the
homeserver URL first so a misconfigured token doesn't leak as the apparent
host in error messages.

The ``email:`` sink reads SMTP config from the environment to keep secrets
out of the watchlist DB:

    DARKCAT_SMTP_HOST    required (e.g. smtp.gmail.com)
    DARKCAT_SMTP_PORT    default 587
    DARKCAT_SMTP_USER    SMTP username
    DARKCAT_SMTP_PASS    SMTP password
    DARKCAT_SMTP_FROM    From: header (defaults to user)
    DARKCAT_SMTP_TLS     "0" disables STARTTLS (default on)
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import smtplib
import ssl
import subprocess
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Iterable, Optional
from urllib.parse import quote

import requests


log = logging.getLogger("darkcat.watch")


@dataclass(frozen=True)
class WatchEntry:
    id: int
    target: Optional[str]
    category: Optional[str]
    sample: Optional[str]
    is_regex: bool
    sink: str
    note: Optional[str]


def from_row(row) -> WatchEntry:
    return WatchEntry(
        id=row["id"],
        target=row["target"],
        category=row["category"],
        sample=row["sample"],
        is_regex=bool(row["is_regex"]),
        sink=row["sink"],
        note=row["note"],
    )


def _rx(pattern: str, regex: bool) -> re.Pattern:
    return re.compile(pattern if regex else re.escape(pattern), re.I)


def matches(watch: WatchEntry, finding) -> bool:
    """Return True iff every set field on the watch matches the finding."""
    if not (watch.target or watch.category or watch.sample):
        return False  # never fire on a watch with nothing set
    if watch.target:
        if not _rx(watch.target, watch.is_regex).search(finding.target or ""):
            return False
    if watch.category:
        rx = _rx(watch.category, watch.is_regex)
        if watch.is_regex:
            if not rx.fullmatch(finding.category):
                return False
        elif finding.category != watch.category:
            return False
    if watch.sample:
        if not _rx(watch.sample, watch.is_regex).search(finding.sample or ""):
            return False
    return True


def _payload(watch: WatchEntry, finding, url: str, protocol: str) -> dict:
    return {
        "watch_id": watch.id,
        "fired_at": time.time(),
        "url": url,
        "protocol": protocol,
        "category": finding.category,
        "target": finding.target,
        "sample": finding.sample,
        "digest": finding.digest,
        "confidence": finding.confidence,
        "line_no": finding.line_no,
        "note": watch.note,
    }


def _format_text(payload: dict) -> str:
    """Human-readable single-string representation of an alert payload, used
    by sinks that don't accept structured JSON (Slack, Matrix, email)."""
    lines = [
        f"[darkcat] {payload['category']}",
        f"  target  : {payload.get('target') or '-'}",
        f"  url     : {payload['url']}",
        f"  proto   : {payload['protocol']}",
    ]
    if payload.get("sample"):
        s = payload["sample"]
        if len(s) > 200:
            s = s[:197] + "..."
        lines.append(f"  sample  : {s}")
    if payload.get("confidence"):
        lines.append(f"  conf    : {payload['confidence']:.2f}")
    if payload.get("note"):
        lines.append(f"  note    : {payload['note']}")
    return "\n".join(lines)


def _send_slack(webhook_url: str, payload: dict) -> str:
    """Slack incoming webhook — accepts ``{'text': '...'}``."""
    body = {"text": _format_text(payload)}
    r = requests.post(webhook_url, json=body, timeout=8)
    return f"ok:{r.status_code}" if r.ok else f"err:{r.status_code}"


def _send_discord(webhook_url: str, payload: dict) -> str:
    """Discord incoming webhook — accepts ``{'content': '...'}``. Discord
    enforces a 2000-char body cap so we truncate aggressively."""
    text = _format_text(payload)
    if len(text) > 1900:
        text = text[:1897] + "..."
    body = {"content": text}
    r = requests.post(webhook_url, json=body, timeout=8)
    return f"ok:{r.status_code}" if r.ok else f"err:{r.status_code}"


def _send_matrix(target: str, payload: dict) -> str:
    """Matrix m.room.message — ``HOMESERVER|ROOM_ID|TOKEN``.

    Uses the legacy ``r0`` API path which every Synapse build still serves.
    The transaction ID is timestamp-based; collisions on the same ms within
    a single room would deduplicate but for alerting that's fine."""
    parts = target.split("|", 2)
    if len(parts) != 3:
        return "err:matrix:bad-target"
    homeserver, room, token = parts
    if not homeserver.startswith(("http://", "https://")):
        return "err:matrix:homeserver-missing-scheme"
    txn = str(int(time.time() * 1000))
    url = (
        f"{homeserver.rstrip('/')}/_matrix/client/r0/rooms/"
        f"{quote(room, safe='')}/send/m.room.message/{txn}"
    )
    body = {"msgtype": "m.text", "body": _format_text(payload)}
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.put(url, json=body, headers=headers, timeout=8)
    return f"ok:{r.status_code}" if r.ok else f"err:{r.status_code}:{r.text[:80]}"


def _send_email(to_addr: str, payload: dict) -> str:
    """SMTP via DARKCAT_SMTP_* env vars. Returns ``skip:*`` when host is
    unconfigured rather than failing — keeps the sink safely no-op-able."""
    host = os.environ.get("DARKCAT_SMTP_HOST")
    if not host:
        return "skip:no-smtp-host"
    port = int(os.environ.get("DARKCAT_SMTP_PORT") or "587")
    user = os.environ.get("DARKCAT_SMTP_USER", "")
    pw = os.environ.get("DARKCAT_SMTP_PASS", "")
    sender = os.environ.get("DARKCAT_SMTP_FROM") or user or "darkcat@localhost"
    use_tls = os.environ.get("DARKCAT_SMTP_TLS", "1") != "0"

    msg = EmailMessage()
    msg["Subject"] = f"[darkcat] {payload['category']} — {payload.get('target') or payload['url']}"
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(_format_text(payload))

    with smtplib.SMTP(host, port, timeout=15) as s:
        s.ehlo()
        if use_tls:
            try:
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
            except Exception as e:
                return f"err:starttls:{e}"
        if user and pw:
            s.login(user, pw)
        s.send_message(msg)
    return "ok"


def fire(watch: WatchEntry, finding, url: str, protocol: str) -> str:
    """Dispatch to the watch's sink. Return a short status string."""
    sink = watch.sink
    payload = _payload(watch, finding, url, protocol)
    try:
        if sink == "log":
            note = f" note={watch.note}" if watch.note else ""
            print(
                f"[ALERT watch={watch.id}] {finding.category} "
                f"target={finding.target or '-'} url={url}{note}"
            )
            return "ok"
        if sink == "notify":
            if not shutil.which("notify-send"):
                return "skip:no notify-send"
            title = f"darkcat: {finding.category}"
            body = (
                f"target={finding.target or '-'}\n"
                f"{url}\n{finding.sample}"
            )
            # subprocess.run with a timeout so a stuck/non-responsive
            # notification daemon can't wedge the alert pipeline.
            try:
                subprocess.run(
                    ["notify-send", title, body],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return "err:notify-send timed out"
            return "ok"
        if sink.startswith("file:"):
            path = sink[len("file:") :]
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
            return "ok"
        if sink.startswith("webhook:"):
            url_target = sink[len("webhook:") :]
            r = requests.post(url_target, json=payload, timeout=5)
            return f"ok:{r.status_code}"
        if sink.startswith("slack:"):
            return _send_slack(sink[len("slack:"):], payload)
        if sink.startswith("discord:"):
            return _send_discord(sink[len("discord:"):], payload)
        if sink.startswith("matrix:"):
            return _send_matrix(sink[len("matrix:"):], payload)
        if sink.startswith("email:"):
            return _send_email(sink[len("email:"):], payload)
        return "skip:unknown-sink"
    except Exception as e:
        # The 200-char return string is what gets recorded next to the alert
        # row; that's fine for ops dashboards but useless for debugging an
        # auth failure or a malformed webhook body. Mirror the full traceback
        # to the logger so operators can grep `darkcat.watch` in journalctl.
        log.warning(
            "sink %r failed: %s: %s", sink, type(e).__name__, e, exc_info=True,
        )
        return f"err:{type(e).__name__}:{e}"[:200]


class Watcher:
    def __init__(self, storage) -> None:
        self.storage = storage
        self._watches: list[WatchEntry] = []
        self.reload()

    def reload(self) -> None:
        self._watches = [from_row(r) for r in self.storage.watchlist_query()]

    def apply(self, url: str, protocol: str, findings: Iterable) -> int:
        if not self._watches:
            return 0
        fired = 0
        for f in findings:
            for w in self._watches:
                if matches(w, f):
                    status = fire(w, f, url, protocol)
                    if self.storage.record_alert(w.id, url, f.digest, status):
                        fired += 1
        return fired
