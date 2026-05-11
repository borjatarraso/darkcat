"""SimpleX backend for darkcat — drives the ``simplex-chat`` binary.

SimpleX has no published Python SDK. The reference implementation is
the Haskell daemon ``simplex-chat`` (https://github.com/simplex-chat/simplex-chat),
which can run as a server exposing a JSON-over-WebSocket API on
``ws://127.0.0.1:5225/`` (configurable). Every operation a user can do
in the GUI is also a JSON command on that socket.

Protocol summary
----------------

The SimpleX chat daemon speaks a line-delimited request/response
protocol over WebSocket. Each request is JSON::

    {"corrId": "uuid", "cmd": "/_get chats"}

and each response is also JSON, correlated by ``corrId``. The
``cmd`` field is the same string a user would type in the
``simplex-chat`` REPL — that means we can talk to the daemon by
emitting REPL commands.

What this backend implements
----------------------------

* Connect to a running ``simplex-chat`` WebSocket on
  ``ws://127.0.0.1:<port>/``.
* List chats (`/_get chats`).
* Read messages (`/_get chat <id> count=<n>`).
* Send messages (`/_send <id> text <body>`).

What it doesn't
---------------

* It does not start the daemon for you. SimpleX wants you to know
  what's running where; we won't auto-launch a process that has
  cryptographic keys on it.
* It does not implement the SMP (queue) protocol natively. If you
  want a self-contained Python SimpleX client one day, that's the
  ~10k-LOC project in your future.

Persona shape
-------------

* ``persona.site``     ``ws://127.0.0.1:5225/``  (or wherever your daemon listens)
* ``persona.password`` optional ``Authorization: Bearer …`` token if your
                        daemon was started with ``-y`` and a basic auth wrapper
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from typing import Optional
from urllib.parse import urlparse

from darkcat.chat.base import (
    AuthError,
    BackendUnavailable,
    ChatChannel,
    ChatMessage,
    Messenger,
)


DEP_NAME = "websocket-client + simplex-chat daemon"
INSTALL_HINT = (
    "pip install websocket-client; "
    "install simplex-chat from https://simplex.chat/cli; "
    "run `simplex-chat -p 5225` to start the daemon."
)


try:
    import websocket  # websocket-client package
    HAS_WS = True
except ImportError:  # pragma: no cover
    HAS_WS = False


# Whether the simplex-chat binary is on PATH. We don't *require* it on
# this machine — the daemon could be running in a remote container —
# but its presence is a useful availability signal.
HAS_SIMPLEX_CLI = HAS_WS and shutil.which("simplex-chat") is not None


class _SimplexWS:
    """Tiny request/response wrapper around the simplex-chat WebSocket
    REPL. Synchronous because the operations the CLI cares about are
    short enough that an event loop is overkill."""

    def __init__(self, url: str, token: Optional[str] = None,
                 timeout: float = 8.0) -> None:
        self.url = url
        self.timeout = timeout
        headers = []
        if token:
            headers.append(f"Authorization: Bearer {token}")
        if not HAS_WS:
            raise BackendUnavailable("websocket-client not installed")
        self.ws = websocket.create_connection(
            url, header=headers, timeout=timeout,
        )

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass

    def cmd(self, repl_command: str) -> dict:
        corr = str(uuid.uuid4())
        self.ws.send(json.dumps({"corrId": corr, "cmd": repl_command}))
        # The daemon may push unsolicited events. Walk the inbound
        # stream until we see our corrId or hit the timeout.
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            try:
                raw = self.ws.recv()
            except Exception as e:
                raise AuthError(f"simplex-chat read failed: {e}") from e
            try:
                msg = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if msg.get("corrId") == corr:
                return msg
        raise AuthError(f"simplex-chat timed out waiting for {repl_command!r}")


class SimplexMessenger(Messenger):
    network = "simplex"

    def __init__(self, persona, *, sessions_dir=None) -> None:
        super().__init__(persona, sessions_dir=sessions_dir)
        if not HAS_WS:
            raise BackendUnavailable(
                "websocket-client not installed — " + INSTALL_HINT
            )
        self._ws: Optional[_SimplexWS] = None

    # ---- lifecycle ------------------------------------------------

    def connect(self) -> None:
        if self._connected:
            return
        url = (self.persona.site or "").strip() or "ws://127.0.0.1:5225/"
        # Accept "ws://host:port" as-is, or "host:port" promoted to ws.
        if "://" not in url:
            url = "ws://" + url
        parsed = urlparse(url)
        if parsed.scheme not in ("ws", "wss"):
            raise AuthError(
                f"simplex persona's site must be a ws:// URL, got {url!r}"
            )
        try:
            self._ws = _SimplexWS(url, token=self.persona.password)
            # Sanity probe: ask for the version of the running daemon.
            self._ws.cmd("/version")
        except Exception as e:
            raise AuthError(f"simplex-chat connect failed: {e}") from e
        self._connected = True

    def disconnect(self) -> None:
        if self._ws:
            self._ws.close()
        self._ws = None
        self._connected = False

    # ---- queries --------------------------------------------------

    def list_channels(self, *, limit: int = 100) -> list[ChatChannel]:
        if not self._ws:
            raise AuthError("not connected")
        resp = self._ws.cmd("/_get chats pcc=on")
        chats = (resp.get("resp", {})
                     .get("Right", {})
                     .get("chats", []))
        out: list[ChatChannel] = []
        for c in chats[:limit]:
            info = c.get("chatInfo") or {}
            kind_tag = info.get("type", "")
            kind = {"direct": "dm", "group": "group"}.get(kind_tag, "dm")
            ident = info.get("contact", {}).get("contactId") or info.get("groupInfo", {}).get("groupId")
            name = (info.get("contact", {}).get("localDisplayName")
                    or info.get("groupInfo", {}).get("localDisplayName")
                    or str(ident))
            out.append(ChatChannel(
                id=f"{kind_tag}:{ident}" if ident is not None else name,
                name=name,
                kind=kind,
                participants=info.get("groupInfo", {}).get("memberCount", 0) or 0,
            ))
        return out

    def read(self, channel_id: str, *, limit: int = 50) -> list[ChatMessage]:
        if not self._ws:
            raise AuthError("not connected")
        # channel_id is "direct:<id>" or "group:<id>"
        try:
            kind_tag, ident = channel_id.split(":", 1)
        except ValueError:
            raise AuthError(f"bad simplex channel id {channel_id!r}")
        cmd = f"/_get chat {kind_tag} {ident} count={limit}"
        resp = self._ws.cmd(cmd)
        items = (resp.get("resp", {})
                     .get("Right", {})
                     .get("chatItems", []))
        out: list[ChatMessage] = []
        for it in items:
            content = it.get("content", {}).get("msgContent", {})
            text = content.get("text") or content.get("filePath") or ""
            ts = it.get("meta", {}).get("itemTs")
            ts_f = 0.0
            if isinstance(ts, str):
                # ISO-8601 UTC like "2026-04-29T11:22:33Z"
                try:
                    import datetime
                    ts_f = datetime.datetime.fromisoformat(
                        ts.replace("Z", "+00:00")
                    ).timestamp()
                except Exception:
                    ts_f = 0.0
            sender = it.get("chatDir", {}).get("type", "")
            out.append(ChatMessage(
                channel_id=channel_id,
                msg_id=str(it.get("meta", {}).get("itemId", "")),
                sender=sender,
                text=text,
                ts=ts_f,
                raw=it,
            ))
        return out

    def connect_link(self, invite_link: str) -> str:
        """Accept a SimpleX contact invitation.

        Pass a ``https://simplex.chat/contact#...`` or ``simplex:/...``
        link from the peer. Returns the daemon's raw response (already
        decoded JSON) summarised as a one-line description."""
        if not self._ws:
            raise AuthError("not connected")
        invite_link = invite_link.strip()
        resp = self._ws.cmd(f"/connect {invite_link}")
        # SimpleX responses are nested under .resp; surface a short
        # readable summary the CLI can show without dumping JSON.
        right = resp.get("resp", {}).get("Right", {})
        if not right:
            err = resp.get("resp", {}).get("Left") or resp
            raise AuthError(f"simplex /connect failed: {err}")
        kind = next(iter(right.keys()), "ok")
        return f"{kind}: invitation accepted"

    def send(self, channel_id: str, text: str) -> ChatMessage:
        if not self._ws:
            raise AuthError("not connected")
        try:
            kind_tag, ident = channel_id.split(":", 1)
        except ValueError:
            raise AuthError(f"bad simplex channel id {channel_id!r}")
        # The SimpleX REPL spelling is `@<contact> <text>` for direct
        # and `#<group> <text>` for group; via _send we can be explicit.
        cmd = f"/_send {kind_tag} {ident} text {text}"
        resp = self._ws.cmd(cmd)
        item = (resp.get("resp", {})
                    .get("Right", {})
                    .get("chatItem", {}))
        return ChatMessage(
            channel_id=channel_id,
            msg_id=str(item.get("meta", {}).get("itemId", "")),
            sender="me",
            text=text,
            ts=time.time(),
            raw=resp,
        )


__all__ = [
    "SimplexMessenger", "HAS_WS", "HAS_SIMPLEX_CLI",
    "DEP_NAME", "INSTALL_HINT",
]
