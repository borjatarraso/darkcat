"""XMPP backend for darkcat — slixmpp (pure Python, asyncio).

XMPP is the elder federated messenger: a JID is ``user@server.tld``,
servers gossip with each other over s2s, and the protocol is XML
streaming. Modern privacy-conscious deployments (calyx.net,
dismail.de, jabber.ccc.de, conversations.im) ship OMEMO E2EE by
default, but darkcat's first-cut backend stays plaintext-only — OMEMO
in slixmpp depends on ``slixmpp-omemo`` and ``python-omemo`` plus a
double-ratchet implementation, which is a significant install.

What works
----------

* Login with bare or full JID + password (``persona.handle`` /
  ``persona.password``).
* Roster listing (your contacts) and joined MUC rooms (group chats).
* Plain ``<message/>`` send and receive.

What doesn't (yet)
------------------

* OMEMO encryption — falls back to plaintext, which most secure-XMPP
  servers will reject for direct messages. Group MUCs without
  encryption work fine.
* Voice / video / file transfer — not exposed.
* Roster-add / subscribe handshake — use a normal client to befriend
  someone, then darkcat can talk to them.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from darkcat.chat.base import (
    AuthError,
    BackendUnavailable,
    ChatChannel,
    ChatMessage,
    Messenger,
)


DEP_NAME = "slixmpp"
INSTALL_HINT = "pip install slixmpp"


try:
    import slixmpp
    HAS_SLIXMPP = True
except ImportError:  # pragma: no cover
    HAS_SLIXMPP = False


class _CollectingClient(slixmpp.ClientXMPP if HAS_SLIXMPP else object):
    """One-shot slixmpp client: connect → fetch roster → wait for
    a small inbound burst → disconnect.

    We don't keep a long-running connection because the CLI is
    request/response. The trade-off: messages that arrive *while*
    darkcat isn't running are queued by the server (XEP-0313: MAM)
    and need to be pulled on next read."""

    def __init__(self, jid: str, password: str) -> None:
        super().__init__(jid, password)
        self.roster_ready = asyncio.Event()
        self.inbound: list[ChatMessage] = []
        self.add_event_handler("session_start", self._on_session_start)
        self.add_event_handler("message", self._on_message)

    async def _on_session_start(self, _event):
        try:
            await self.get_roster()
        except slixmpp.exceptions.IqError as e:  # pragma: no cover
            self.inbound.append(ChatMessage(
                channel_id="@error",
                msg_id="0",
                sender="server",
                text=f"roster fetch failed: {e}",
                ts=time.time(),
            ))
        self.send_presence()
        self.roster_ready.set()

    def _on_message(self, msg) -> None:
        if msg["type"] not in ("chat", "groupchat", "normal"):
            return
        self.inbound.append(ChatMessage(
            channel_id=str(msg["from"].bare),
            msg_id=msg["id"] or "",
            sender=str(msg["from"]),
            text=msg["body"] or "",
            ts=time.time(),
            raw=msg,
        ))


class XmppMessenger(Messenger):
    """slixmpp Messenger. Each call spins up a short-lived session,
    runs the operation, and shuts down."""

    network = "xmpp"

    def __init__(self, persona, *, sessions_dir=None) -> None:
        super().__init__(persona, sessions_dir=sessions_dir)
        if not HAS_SLIXMPP:
            raise BackendUnavailable(
                "slixmpp not installed — " + INSTALL_HINT
            )
        self._loop = asyncio.new_event_loop()
        self._jid: str = ""
        self._password: str = ""

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    async def _open(self) -> _CollectingClient:
        c = _CollectingClient(self._jid, self._password)
        c.connect(disable_starttls=False)
        await c.roster_ready.wait()
        return c

    @staticmethod
    async def _close(c) -> None:
        try:
            c.disconnect(wait=True)
        except Exception:  # pragma: no cover
            pass

    # ---- lifecycle ------------------------------------------------

    def connect(self) -> None:
        if self._connected:
            return
        jid = self.persona.handle or ""
        if "@" not in jid:
            raise AuthError(
                "xmpp persona's handle must be a JID (user@server.tld)"
            )
        if not self.persona.password:
            raise AuthError("xmpp persona has no password")
        self._jid = jid
        self._password = self.persona.password
        # Probe one connection so an unreachable server fails fast.
        try:
            c = self._run(self._open())
            self._run(self._close(c))
        except Exception as e:
            raise AuthError(f"xmpp login failed: {e}") from e
        self._connected = True

    def disconnect(self) -> None:
        try:
            self._loop.close()
        except Exception:
            pass
        self._connected = False

    # ---- queries --------------------------------------------------

    def list_channels(self, *, limit: int = 100) -> list[ChatChannel]:
        if not self._connected:
            raise AuthError("not connected")

        async def _go():
            c = await self._open()
            out: list[ChatChannel] = []
            for jid in list(c.client_roster.keys())[:limit]:
                if jid == c.boundjid.bare:
                    continue
                item = c.client_roster[jid]
                out.append(ChatChannel(
                    id=jid,
                    name=getattr(item, "name", None) or jid,
                    kind="dm",
                    participants=2,
                ))
            await self._close(c)
            return out

        return self._run(_go())

    def read(self, channel_id: str, *, limit: int = 50) -> list[ChatMessage]:
        """Return any messages that arrived during a brief listen
        window. Without MAM this is whatever the server pushes us in
        the first ~3 seconds after we present. For full backlog,
        configure your server with mod_mam (Prosody) or similar."""
        if not self._connected:
            raise AuthError("not connected")

        async def _go():
            c = await self._open()
            await asyncio.sleep(3.0)
            out = [m for m in c.inbound if m.channel_id == channel_id]
            await self._close(c)
            return out[-limit:]

        return self._run(_go())

    def send(self, channel_id: str, text: str) -> ChatMessage:
        if not self._connected:
            raise AuthError("not connected")

        async def _go():
            c = await self._open()
            mtype = "groupchat" if "/" in channel_id or channel_id.startswith("#") else "chat"
            msg = c.make_message(mto=channel_id, mbody=text, mtype=mtype)
            msg.send()
            await asyncio.sleep(0.5)
            await self._close(c)
            return ChatMessage(
                channel_id=channel_id,
                msg_id="",
                sender=self._jid,
                text=text,
                ts=time.time(),
            )

        return self._run(_go())


__all__ = ["XmppMessenger", "HAS_SLIXMPP", "DEP_NAME", "INSTALL_HINT"]
