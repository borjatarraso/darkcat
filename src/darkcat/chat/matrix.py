"""Matrix backend for darkcat — matrix-nio (sync HTTPS, optional E2EE).

Matrix is a federated chat protocol: every account lives on a
homeserver (matrix.org, mozilla.org, kde.org, your-self-hosted.tld) and
homeservers gossip events to each other. A user ID is
``@localpart:server.tld``; a room ID is ``!opaque:server.tld``; a room
alias is the human-friendly ``#name:server.tld`` form.

Authentication
--------------

Three auth modes, in priority order:

1. **Access token** — set ``persona.password`` to a token (string with
   no spaces). Recommended for unattended use; tokens are easier to
   revoke than passwords.
2. **Username + password** — handle is the bare localpart or full
   ``@user:server``, password is the persona password. Requires the
   homeserver to have password auth enabled.
3. **SSO** — out of scope for the CLI; use a token from your client.

Persona shape
-------------

We expect the persona to look like::

    network        = "matrix"
    site           = "matrix.org"   # or your homeserver
    handle         = "@alice:matrix.org"
    password       = "syt_…access_token… or your password"
    pgp_key_id     = optional Olm device id for E2EE re-use

End-to-end encryption (Olm/Megolm) only works if matrix-nio was
installed with the ``e2e`` extra (``pip install matrix-nio[e2e]``)
and ``libolm`` is on the system. Without it, encrypted rooms still
appear in ``list_channels()`` but ``read()`` returns ciphertext-as-text
which is useless. The CLI surfaces this gracefully.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

from darkcat.chat.base import (
    AuthError,
    BackendUnavailable,
    ChatChannel,
    ChatMessage,
    Messenger,
)


DEP_NAME = "matrix-nio"
INSTALL_HINT = (
    "pip install matrix-nio[e2e]  (E2EE optional; needs libolm system pkg)"
)


try:
    from nio import (
        AsyncClient,
        AsyncClientConfig,
        LoginResponse,
        MatrixRoom,
        RoomMessageText,
        SyncResponse,
    )
    HAS_NIO = True
except ImportError:  # pragma: no cover
    HAS_NIO = False


def _resolve_homeserver(persona) -> str:
    """The site field is ``"matrix.org"`` (no scheme); we promote it
    to a URL. Operators sometimes self-host on a port, so we accept
    explicit ``https://...:8448`` too."""
    site = (persona.site or "").strip()
    if not site:
        raise AuthError(
            "matrix persona must set --site to the homeserver "
            "(e.g. 'matrix.org' or 'https://matrix.example.tld')"
        )
    if site.startswith(("http://", "https://")):
        return site.rstrip("/")
    return f"https://{site}"


class MatrixMessenger(Messenger):
    """matrix-nio async client wrapped as a sync Messenger.

    Each call drives one ``client.sync(...)`` to refresh state plus the
    actual operation. We deliberately don't keep a persistent sync loop
    running in the background: the CLI is one-shot, so a fire-and-forget
    pattern keeps the implementation small. Use the underlying
    ``self.client`` for long-running real-time consumers."""

    network = "matrix"

    def __init__(self, persona, *, sessions_dir=None) -> None:
        super().__init__(persona, sessions_dir=sessions_dir)
        if not HAS_NIO:
            raise BackendUnavailable(
                "matrix-nio not installed — " + INSTALL_HINT
            )
        self._loop = asyncio.new_event_loop()
        self.client: Optional["AsyncClient"] = None
        self._token_path = self.sessions_dir / "matrix.token.json"

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    # ---- token store ----------------------------------------------

    def _save_token(self, user_id: str, device_id: str, access_token: str) -> None:
        self._token_path.write_text(json.dumps({
            "user_id": user_id,
            "device_id": device_id,
            "access_token": access_token,
        }))
        try:
            self._token_path.chmod(0o600)
        except OSError:
            pass

    def _load_token(self) -> Optional[dict]:
        if not self._token_path.exists():
            return None
        try:
            return json.loads(self._token_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    # ---- lifecycle ------------------------------------------------

    def connect(self) -> None:
        if self._connected:
            return
        homeserver = _resolve_homeserver(self.persona)
        store_dir = self.sessions_dir / "store"
        store_dir.mkdir(parents=True, exist_ok=True)

        cfg = AsyncClientConfig(
            store_sync_tokens=True,
            encryption_enabled=True,
        )
        token = self._load_token()
        user_id = self.persona.handle or token.get("user_id") if token else self.persona.handle
        if not user_id:
            raise AuthError(
                "matrix persona must set --handle to your full "
                "@localpart:server.tld id"
            )

        client = AsyncClient(
            homeserver=homeserver,
            user=user_id,
            device_id=(token or {}).get("device_id"),
            store_path=str(store_dir),
            config=cfg,
        )
        self.client = client

        async def _login():
            # Try restoring a cached access token first.
            if token and token.get("access_token"):
                client.restore_login(
                    user_id=token["user_id"],
                    device_id=token["device_id"],
                    access_token=token["access_token"],
                )
                # Quick whoami to verify.
                whoami = await client.whoami()
                if not getattr(whoami, "user_id", None):
                    raise AuthError("matrix cached token is invalid; re-login")
                return

            pw = self.persona.password
            if not pw:
                raise AuthError(
                    "matrix persona has no password / token; "
                    "set one via `darkcat personas add … --password …`"
                )
            # Heuristic: tokens issued by Synapse start "syt_", "mxat_"
            # or are >40 chars no spaces; treat those as access tokens.
            looks_token = (
                pw.startswith(("syt_", "mxat_"))
                or (len(pw) >= 40 and " " not in pw and pw.isascii())
            )
            if looks_token:
                client.access_token = pw
                client.user_id = user_id
                client.device_id = client.device_id or "darkcat"
                whoami = await client.whoami()
                if not getattr(whoami, "user_id", None):
                    raise AuthError("matrix access token rejected")
                self._save_token(whoami.user_id, client.device_id, pw)
                return

            resp = await client.login(pw, device_name="darkcat")
            if not isinstance(resp, LoginResponse):
                raise AuthError(f"matrix login failed: {resp}")
            self._save_token(resp.user_id, resp.device_id, resp.access_token)

        try:
            self._run(_login())
            # First sync populates room state.
            self._run(client.sync(timeout=10000))
        except (AuthError, BackendUnavailable):
            raise
        except Exception as e:
            raise AuthError(f"matrix connect failed: {e}") from e
        self._connected = True

    def disconnect(self) -> None:
        if not self.client:
            return
        try:
            self._run(self.client.close())
        except Exception:
            pass
        try:
            self._loop.close()
        except Exception:
            pass
        self.client = None
        self._connected = False

    # ---- queries --------------------------------------------------

    def list_channels(self, *, limit: int = 100) -> list[ChatChannel]:
        if not self.client:
            raise AuthError("not connected")
        out: list[ChatChannel] = []
        for room_id, room in list(self.client.rooms.items())[:limit]:
            assert isinstance(room, MatrixRoom)
            kind = "dm" if room.is_group else (
                "channel" if room.canonical_alias else "group"
            )
            out.append(ChatChannel(
                id=room_id,
                name=room.display_name or room.canonical_alias or room_id,
                kind=kind,
                participants=len(room.users),
                unread=getattr(room, "unread_notifications", 0) or 0,
                extra={"encrypted": bool(room.encrypted)},
            ))
        return out

    def read(self, channel_id: str, *, limit: int = 50) -> list[ChatMessage]:
        if not self.client:
            raise AuthError("not connected")

        async def _go():
            resp = await self.client.room_messages(
                channel_id, start=self.client.next_batch, limit=limit,
            )
            out: list[ChatMessage] = []
            for ev in getattr(resp, "chunk", []):
                if isinstance(ev, RoomMessageText):
                    out.append(ChatMessage(
                        channel_id=channel_id,
                        msg_id=ev.event_id,
                        sender=ev.sender,
                        text=ev.body or "",
                        ts=ev.server_timestamp / 1000.0,
                        raw=ev,
                    ))
            return list(reversed(out))

        return self._run(_go())

    def send(self, channel_id: str, text: str) -> ChatMessage:
        if not self.client:
            raise AuthError("not connected")

        async def _go():
            resp = await self.client.room_send(
                room_id=channel_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": text},
            )
            event_id = getattr(resp, "event_id", "") or ""
            return ChatMessage(
                channel_id=channel_id,
                msg_id=event_id,
                sender=self.client.user_id or "",
                text=text,
                ts=time.time(),
                raw=resp,
            )

        return self._run(_go())


__all__ = ["MatrixMessenger", "HAS_NIO", "DEP_NAME", "INSTALL_HINT"]
