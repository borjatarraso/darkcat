# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Outbound + inbound mail for darkcat personas.

A "mail persona" is just a regular persona whose ``site`` field carries
the SMTP / IMAP host (and optional ``:port``) and whose ``handle`` /
``password`` carry the SASL credentials. For Proton Mail this means the
operator runs *Proton Mail Bridge* locally and points the persona at
``127.0.0.1:1025`` (SMTP) / ``127.0.0.1:1143`` (IMAP); the Bridge
performs the heavy crypto with Proton's servers and exposes a normal
SMTP / IMAP endpoint to local clients. Same shape works for Disroot,
Tutanota (with their own bridge), Mailfence — anything with SMTP.

Persona fields used
-------------------

* ``handle``                SMTP/IMAP username (full address for most providers)
* ``password``              SMTP/IMAP password / Bridge token
* ``email``                 ``From:`` header (falls back to ``handle``)
* ``site``                  ``host[:port]``; SMTP if missing port assumes 587, IMAP 993
* ``notes``                 free-form; may carry ``smtp_port=…``, ``imap_port=…``,
                            ``smtp_tls=starttls|ssl|none``, ``imap_tls=ssl|starttls|none``

Environment fallback
--------------------

If the persona doesn't carry SMTP coordinates, ``DARKCAT_SMTP_HOST`` /
``DARKCAT_SMTP_PORT`` / ``DARKCAT_SMTP_USER`` / ``DARKCAT_SMTP_PASS``
take over — same vars the ``watch`` ``email:`` sink uses.

Design choice
-------------

We deliberately do not implement an OAuth flow for Gmail / Outlook
modern auth. Personas-grade scripting wants username/password or app
passwords; if you need OAuth, run the provider's bridge / IMAP proxy
locally (e.g. ``mailctl``, ``davmail``) and point the persona at it.
"""
from __future__ import annotations

import email.header
import email.utils
import imaplib
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional


DEFAULT_SMTP_PORT = 587
DEFAULT_IMAP_PORT = 993


@dataclass
class MailCoords:
    """Resolved SMTP/IMAP coordinates for a persona."""

    smtp_host: str
    smtp_port: int
    smtp_tls: str          # "starttls" | "ssl" | "none"
    imap_host: str
    imap_port: int
    imap_tls: str          # "ssl" | "starttls" | "none"
    username: str
    password: str
    sender: str            # From: address


class MailError(RuntimeError):
    """Mail send/receive failures (auth, TLS, transport)."""


def _decode_header(raw: str) -> str:
    """Decode an RFC 2047 encoded header to a plain str.

    Real-world inboxes routinely carry ``=?utf-8?B?...?=`` (base64) or
    ``=?iso-8859-1?Q?...?=`` (quoted-printable) Subject and From values.
    Falls back to the raw string if decoding misfires."""
    if not raw:
        return ""
    try:
        parts = email.header.decode_header(raw)
    except Exception:
        return raw
    out: list[str] = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            try:
                out.append(chunk.decode(charset or "utf-8", "replace"))
            except (LookupError, UnicodeDecodeError):
                out.append(chunk.decode("utf-8", "replace"))
        else:
            out.append(chunk)
    return "".join(out)


def _parse_notes(notes: Optional[str]) -> dict:
    """Pull ``key=value`` pairs out of ``persona.notes``.

    Anything we don't recognize is ignored. Whitespace between pairs is
    fine; values stop at the next whitespace."""
    out: dict[str, str] = {}
    if not notes:
        return out
    for m in re.finditer(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(\S+)", notes):
        out[m.group(1).lower()] = m.group(2)
    return out


def coords_from_persona(persona) -> MailCoords:
    """Build :class:`MailCoords` from a persona, falling back to env."""
    import os

    notes = _parse_notes(getattr(persona, "notes", None))
    site = (getattr(persona, "site", "") or "").strip()
    host = ""
    port: Optional[int] = None
    if site:
        if ":" in site:
            host, _, p = site.partition(":")
            try:
                port = int(p)
            except ValueError:
                port = None
        else:
            host = site

    smtp_host = host or os.environ.get("DARKCAT_SMTP_HOST", "")
    if not smtp_host:
        raise MailError(
            "persona has no SMTP host (set persona.site=host[:port] or "
            "DARKCAT_SMTP_HOST in the environment)"
        )
    smtp_port = (
        int(notes.get("smtp_port", "0")) or port or DEFAULT_SMTP_PORT
    )
    smtp_tls = (notes.get("smtp_tls") or "starttls").lower()

    imap_host = notes.get("imap_host", smtp_host)
    imap_port = int(notes.get("imap_port", "0")) or DEFAULT_IMAP_PORT
    imap_tls = (notes.get("imap_tls") or "ssl").lower()

    username = (
        getattr(persona, "handle", None)
        or os.environ.get("DARKCAT_SMTP_USER", "")
    )
    password = (
        getattr(persona, "password", None)
        or os.environ.get("DARKCAT_SMTP_PASS", "")
    )
    sender = (
        getattr(persona, "email", None)
        or username
        or "darkcat@localhost"
    )
    if not username or not password:
        raise MailError(
            "persona has no SMTP credentials (set handle + password, or "
            "DARKCAT_SMTP_USER / DARKCAT_SMTP_PASS)"
        )
    return MailCoords(
        smtp_host=smtp_host, smtp_port=smtp_port, smtp_tls=smtp_tls,
        imap_host=imap_host, imap_port=imap_port, imap_tls=imap_tls,
        username=username, password=password, sender=sender,
    )


def send_via_persona(
    persona,
    *,
    to: list[str],
    subject: str,
    body: str,
    cc: Optional[list[str]] = None,
    bcc: Optional[list[str]] = None,
    reply_to: Optional[str] = None,
    timeout: float = 30.0,
) -> str:
    """Build and dispatch a plain-text email. Returns the Message-Id.

    No HTML body, no attachments — keep darkcat's mail surface minimal.
    Anyone needing those can drop down to :mod:`email` directly."""
    coords = coords_from_persona(persona)
    msg = EmailMessage()
    msg["From"] = coords.sender
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg_id = email.utils.make_msgid(domain=coords.smtp_host)
    msg["Message-Id"] = msg_id
    msg.set_content(body)

    recipients = list(to) + list(cc or []) + list(bcc or [])
    try:
        if coords.smtp_tls == "ssl":
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(coords.smtp_host, coords.smtp_port,
                                  context=ctx, timeout=timeout) as s:
                s.login(coords.username, coords.password)
                s.send_message(msg, from_addr=coords.sender,
                               to_addrs=recipients)
        else:
            with smtplib.SMTP(coords.smtp_host, coords.smtp_port,
                              timeout=timeout) as s:
                s.ehlo()
                if coords.smtp_tls == "starttls":
                    ctx = ssl.create_default_context()
                    s.starttls(context=ctx)
                    s.ehlo()
                s.login(coords.username, coords.password)
                s.send_message(msg, from_addr=coords.sender,
                               to_addrs=recipients)
    except (smtplib.SMTPException, ssl.SSLError, OSError) as e:
        raise MailError(f"SMTP send failed: {e}") from e
    return msg_id


@dataclass
class MailHeader:
    """Lightweight header summary for an INBOX listing."""

    uid: str
    from_: str
    subject: str
    date: str
    size: int


def check_inbox(
    persona,
    *,
    folder: str = "INBOX",
    limit: int = 25,
    timeout: float = 30.0,
) -> list[MailHeader]:
    """Fetch the most recent ``limit`` envelope headers from ``folder``.

    Read-only: we never call ``STORE`` and never flag messages as seen."""
    coords = coords_from_persona(persona)
    try:
        if coords.imap_tls == "ssl":
            ctx = ssl.create_default_context()
            imap = imaplib.IMAP4_SSL(
                coords.imap_host, coords.imap_port,
                ssl_context=ctx, timeout=timeout,
            )
        else:
            imap = imaplib.IMAP4(coords.imap_host, coords.imap_port,
                                 timeout=timeout)
            if coords.imap_tls == "starttls":
                imap.starttls()
        imap.login(coords.username, coords.password)
    except (imaplib.IMAP4.error, ssl.SSLError, OSError) as e:
        raise MailError(f"IMAP login failed: {e}") from e

    try:
        # readonly=True is critical — we don't want to clear unread flags.
        imap.select(folder, readonly=True)
        typ, data = imap.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return []
        ids = data[0].split()
        ids = ids[-limit:]
        out: list[MailHeader] = []
        for raw_id in reversed(ids):
            typ, mdata = imap.fetch(
                raw_id,
                "(UID RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])",
            )
            if typ != "OK" or not mdata:
                continue
            uid = ""
            size = 0
            header_bytes = b""
            for part in mdata:
                if not isinstance(part, tuple):
                    continue
                meta = part[0].decode("utf-8", "replace")
                m_uid = re.search(r"UID\s+(\d+)", meta)
                m_size = re.search(r"RFC822\.SIZE\s+(\d+)", meta)
                if m_uid:
                    uid = m_uid.group(1)
                if m_size:
                    size = int(m_size.group(1))
                header_bytes = part[1] or header_bytes
            from_ = subject = date = ""
            for line in header_bytes.decode("utf-8", "replace").splitlines():
                low = line.lower()
                if low.startswith("from:"):
                    from_ = line[5:].strip()
                elif low.startswith("subject:"):
                    subject = line[8:].strip()
                elif low.startswith("date:"):
                    date = line[5:].strip()
            out.append(MailHeader(
                uid=uid,
                from_=_decode_header(from_),
                subject=_decode_header(subject),
                date=date,
                size=size,
            ))
        return out
    finally:
        try:
            imap.logout()
        except Exception:
            pass


__all__ = [
    "DEFAULT_IMAP_PORT",
    "DEFAULT_SMTP_PORT",
    "MailCoords",
    "MailError",
    "MailHeader",
    "check_inbox",
    "coords_from_persona",
    "send_via_persona",
]
