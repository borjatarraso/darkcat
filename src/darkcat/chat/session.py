"""Session backend for darkcat — drives ``session-cli`` / Oxen tooling.

Session has no Python SDK. The viable paths to programmatic control:

1. **session-cli** (community) — wraps the Session protocol in a CLI
   that can list contacts and send messages. Status: works, but
   maintained by a small group of contributors. Repo:
   https://github.com/VityaSchel/session-cli
2. **session-desktop** with ``--enable-cli`` — partial, not all
   builds expose it.
3. Re-implementing the Session protocol (Oxen onion routing + libsodium
   sealed-sender + Loki service-node selection) in Python is a
   multi-month effort and out of scope.

What this backend does
----------------------

It shells out to ``session-cli`` if present and parses its JSON output.
Subcommands we use:

* ``session-cli accounts list``
* ``session-cli contacts list --account <id> --json``
* ``session-cli messages get --account <id> --conversation <id> --limit N --json``
* ``session-cli messages send --account <id> --to <id> --text <body>``

Persona shape::

    handle      = your Session Account ID (66-hex starting 05)
    password    = your Session profile password (if you set one)
    recovery    = optional 13-word seed (used for migration only)

The backend doesn't generate accounts (``session-cli accounts new``
needs interactive RNG); operators should create the account with the
upstream tooling, then point a darkcat persona at it.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from typing import Optional

from darkcat.chat.base import (
    AuthError,
    BackendUnavailable,
    ChatChannel,
    ChatMessage,
    Messenger,
)


DEP_NAME = "session-cli"
INSTALL_HINT = (
    "Install session-cli from https://github.com/VityaSchel/session-cli "
    "(npm i -g session-cli or download a release binary) and ensure it's "
    "on your $PATH."
)

HAS_SESSION_CLI = shutil.which("session-cli") is not None


_SESSION_ID_RX = re.compile(r"^(?:05|15|25)[0-9a-fA-F]{64}$")


def _run(args: list[str], *, timeout: float = 30.0) -> dict:
    """Run a session-cli command, return its parsed JSON. Captures
    stderr to surface diagnostics in error messages — Session's CLI
    uses stderr for prompts and stdout for JSON when ``--json`` is on."""
    try:
        proc = subprocess.run(
            args, capture_output=True, timeout=timeout, check=False,
        )
    except FileNotFoundError as e:
        raise BackendUnavailable(f"session-cli missing: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise AuthError(f"session-cli timed out: {e}") from e
    if proc.returncode != 0:
        raise AuthError(
            f"session-cli exit {proc.returncode}: "
            + proc.stderr.decode("utf-8", "replace").strip()[:300]
        )
    raw = proc.stdout.decode("utf-8", "replace").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise AuthError(f"session-cli returned non-JSON: {e}") from e


class SessionMessenger(Messenger):
    network = "session"

    def __init__(self, persona, *, sessions_dir=None) -> None:
        super().__init__(persona, sessions_dir=sessions_dir)
        if not HAS_SESSION_CLI:
            raise BackendUnavailable(
                "session-cli not on $PATH — " + INSTALL_HINT
            )

    @property
    def _account_id(self) -> str:
        h = (self.persona.handle or "").strip()
        if not _SESSION_ID_RX.match(h):
            raise AuthError(
                "session persona's handle must be a 66-hex Account ID "
                "starting with 05/15/25 — generate one in the Session "
                "GUI or via `session-cli accounts new`"
            )
        return h.lower()

    # ---- lifecycle ------------------------------------------------

    def connect(self) -> None:
        if self._connected:
            return
        # Verify the account exists in session-cli's local store.
        accounts = _run(["session-cli", "accounts", "list", "--json"])
        ids = {a.get("accountId", "").lower() for a in accounts.get("accounts", [])}
        if self._account_id not in ids:
            raise AuthError(
                f"account {self._account_id[:10]}… not in session-cli's store; "
                "run `session-cli accounts import …` or `accounts new` first"
            )
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    # ---- queries --------------------------------------------------

    def list_channels(self, *, limit: int = 100) -> list[ChatChannel]:
        if not self._connected:
            raise AuthError("not connected")
        resp = _run([
            "session-cli", "contacts", "list",
            "--account", self._account_id, "--json",
        ])
        out: list[ChatChannel] = []
        for c in resp.get("contacts", [])[:limit]:
            out.append(ChatChannel(
                id=c.get("accountId", ""),
                name=c.get("displayName") or c.get("accountId", "")[:12],
                kind="dm",
                participants=2,
            ))
        # Closed groups also show up if session-cli supports them.
        for g in resp.get("closedGroups", [])[:limit]:
            out.append(ChatChannel(
                id="group:" + g.get("groupId", ""),
                name=g.get("name") or g.get("groupId", "")[:12],
                kind="group",
                participants=g.get("memberCount", 0) or 0,
            ))
        return out

    def read(self, channel_id: str, *, limit: int = 50) -> list[ChatMessage]:
        if not self._connected:
            raise AuthError("not connected")
        resp = _run([
            "session-cli", "messages", "get",
            "--account", self._account_id,
            "--conversation", channel_id,
            "--limit", str(limit), "--json",
        ])
        out: list[ChatMessage] = []
        for m in resp.get("messages", []):
            out.append(ChatMessage(
                channel_id=channel_id,
                msg_id=str(m.get("id", "")),
                sender=m.get("from", ""),
                text=m.get("body", ""),
                ts=float(m.get("timestamp", time.time() * 1000)) / 1000.0,
                raw=m,
            ))
        return out

    def add_contact(self, peer_session_id: str,
                    name: Optional[str] = None) -> str:
        """Add a peer Session ID to this account's contacts.

        Returns the peer's Session ID (echoed back, lower-cased).
        ``name`` is an optional local nickname for display."""
        if not self._connected:
            raise AuthError("not connected")
        peer = peer_session_id.strip().lower()
        if not _SESSION_ID_RX.match(peer):
            raise AuthError(
                "peer Session ID must be 66-hex starting 05/15/25"
            )
        args = [
            "session-cli", "contacts", "add",
            "--account", self._account_id,
            "--to", peer, "--json",
        ]
        if name:
            args.extend(["--name", name])
        _run(args)
        return peer

    def send(self, channel_id: str, text: str) -> ChatMessage:
        if not self._connected:
            raise AuthError("not connected")
        resp = _run([
            "session-cli", "messages", "send",
            "--account", self._account_id,
            "--to", channel_id, "--text", text, "--json",
        ])
        m = resp.get("message", {})
        return ChatMessage(
            channel_id=channel_id,
            msg_id=str(m.get("id", "")),
            sender=self._account_id,
            text=text,
            ts=time.time(),
            raw=m,
        )


__all__ = [
    "SessionMessenger", "HAS_SESSION_CLI",
    "DEP_NAME", "INSTALL_HINT",
]
