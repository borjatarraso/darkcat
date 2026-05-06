"""Telegram backend for darkcat — Telethon-driven (MTProto, real client).

This backend logs in as a *user account*, not a bot. Bot accounts have
a much narrower API (no access to other people's groups, no read-history
in many channels) which defeats the point. The trade-off is that the
user has to satisfy Telegram's auth flow once: phone number, SMS code,
optional 2FA password.

After the first login Telethon writes a ``.session`` file containing a
session key (not the password); subsequent runs reuse it and never
prompt again. We store that session under
``~/.darkcat/chat-sessions/<persona>/telegram.session`` so each persona
has its own independent identity.

API credentials
---------------

Telegram requires every client to identify itself with an API ID +
API hash registered at https://my.telegram.org. There is **no shared
test pair** that works for production traffic. Two ways to provide it:

1. Persist them on the persona: ``darkcat personas add … --notes
   "tg_api_id=12345 tg_api_hash=abcdef…"``. The backend parses them out.
2. Set ``DARKCAT_TG_API_ID`` and ``DARKCAT_TG_API_HASH`` in the env.

If neither is set we fall back to Telethon's documented test-mode pair,
which is **rate-limited and not for real accounts** — only used for the
``backends`` self-check.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Optional

from darkcat.chat.base import (
    AuthError,
    BackendUnavailable,
    ChatChannel,
    ChatMessage,
    Messenger,
)


DEP_NAME = "telethon"
INSTALL_HINT = "pip install telethon  (https://docs.telethon.dev/)"


try:
    from telethon import TelegramClient
    from telethon.errors import (
        SessionPasswordNeededError,
        PhoneCodeInvalidError,
        FloodWaitError,
    )
    from telethon.tl.types import (
        Channel as TgChannel, Chat as TgChat, User as TgUser,
        Message as TgMessage,
    )
    HAS_TELETHON = True
except ImportError:  # pragma: no cover — optional dep
    HAS_TELETHON = False


# Public Telethon "developer test" credentials. Do not use these to log
# into a real account. The ID is documented at
# https://docs.telethon.dev/en/stable/basic/signing-in.html ; here we
# treat them as a placeholder for the availability self-check only.
_TG_TEST_API_ID = 17349
_TG_TEST_API_HASH = "344583e45741c457fe1862106095a5eb"


def _parse_persona_credentials(persona) -> tuple[Optional[int], Optional[str]]:
    """Pull tg_api_id / tg_api_hash from persona.notes if present."""
    notes = (persona.notes or "")
    m_id = re.search(r"tg_api_id\s*=\s*(\d+)", notes)
    m_hash = re.search(r"tg_api_hash\s*=\s*([0-9a-fA-F]{20,})", notes)
    api_id = int(m_id.group(1)) if m_id else None
    api_hash = m_hash.group(1) if m_hash else None
    return api_id, api_hash


def _resolve_credentials(persona) -> tuple[int, str]:
    """Resolve API credentials with this priority: env > persona notes
    > public test pair (for self-check only)."""
    env_id = os.environ.get("DARKCAT_TG_API_ID")
    env_hash = os.environ.get("DARKCAT_TG_API_HASH")
    if env_id and env_hash:
        return int(env_id), env_hash
    pid, phash = _parse_persona_credentials(persona)
    if pid and phash:
        return pid, phash
    return _TG_TEST_API_ID, _TG_TEST_API_HASH


class TelegramMessenger(Messenger):
    """Persona-bound Telegram user-client.

    Telethon is async-native; we wrap it with a private event loop so
    callers don't need to know. Every public method blocks until done."""

    network = "telegram"

    def __init__(self, persona, *, code_prompt=None, password_prompt=None,
                 sessions_dir=None) -> None:
        super().__init__(persona, sessions_dir=sessions_dir)
        if not HAS_TELETHON:
            raise BackendUnavailable(
                "telethon not installed — " + INSTALL_HINT
            )
        self._loop = asyncio.new_event_loop()
        self._client: Optional["TelegramClient"] = None
        # Allow CLI to inject custom prompts (e.g. read from stdin via
        # ``getpass``). Default is plain ``input`` and ``getpass``.
        self._code_prompt = code_prompt
        self._password_prompt = password_prompt

    # ---- helpers ----------------------------------------------------

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    @property
    def _session_path(self) -> str:
        return str(self.sessions_dir / "telegram.session")

    # ---- lifecycle --------------------------------------------------

    def connect(self) -> None:
        if self._connected:
            return
        api_id, api_hash = _resolve_credentials(self.persona)
        client = TelegramClient(self._session_path, api_id, api_hash,
                                loop=self._loop)
        self._client = client

        async def _login():
            await client.connect()
            if await client.is_user_authorized():
                return
            phone = self.persona.handle
            if not phone or not re.match(r"^\+?\d{6,15}$", phone):
                raise AuthError(
                    "telegram persona's handle must be a phone number "
                    "in international format (+15551234567); set it "
                    "with `darkcat personas add … --handle +…`"
                )
            try:
                await client.send_code_request(phone)
            except FloodWaitError as e:
                raise AuthError(
                    f"telegram rate-limited this login; retry in {e.seconds}s"
                ) from e
            code = self._read_code()
            try:
                await client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                pwd = self._read_password()
                await client.sign_in(password=pwd)
            except PhoneCodeInvalidError as e:
                raise AuthError("telegram code was invalid") from e

        try:
            self._run(_login())
        except (AuthError, BackendUnavailable):
            raise
        except Exception as e:
            raise AuthError(f"telegram login failed: {e}") from e
        self._connected = True

    def disconnect(self) -> None:
        if not self._client:
            return
        try:
            self._run(self._client.disconnect())
        except Exception:
            pass
        finally:
            try:
                self._loop.close()
            except Exception:
                pass
            self._client = None
            self._connected = False

    # ---- prompts (overridable for non-TTY CLI flows) ---------------

    def _read_code(self) -> str:
        if self._code_prompt is not None:
            return self._code_prompt()
        return input("Telegram login code (sent to your device): ").strip()

    def _read_password(self) -> str:
        if self._password_prompt is not None:
            return self._password_prompt()
        import getpass
        return getpass.getpass("Telegram 2FA password: ")

    # ---- queries ---------------------------------------------------

    def list_channels(self, *, limit: int = 100) -> list[ChatChannel]:
        if not self._client:
            raise AuthError("not connected; call connect() first")

        async def _go():
            out: list[ChatChannel] = []
            async for dialog in self._client.iter_dialogs(limit=limit):
                ent = dialog.entity
                kind = "dm"
                participants = 0
                if isinstance(ent, TgChannel):
                    kind = "channel" if ent.broadcast else "group"
                    participants = getattr(ent, "participants_count", 0) or 0
                elif isinstance(ent, TgChat):
                    kind = "group"
                    participants = getattr(ent, "participants_count", 0) or 0
                elif isinstance(ent, TgUser):
                    kind = "dm"
                out.append(ChatChannel(
                    id=str(dialog.id),
                    name=getattr(dialog, "name", "") or str(dialog.id),
                    kind=kind,
                    participants=participants,
                    unread=getattr(dialog, "unread_count", 0) or 0,
                ))
            return out

        return self._run(_go())

    def read(self, channel_id: str, *, limit: int = 50) -> list[ChatMessage]:
        if not self._client:
            raise AuthError("not connected; call connect() first")

        async def _go():
            ent = await self._client.get_entity(int(channel_id))
            out: list[ChatMessage] = []
            async for m in self._client.iter_messages(ent, limit=limit):
                if not isinstance(m, TgMessage):
                    continue
                sender_id = getattr(m, "sender_id", None)
                out.append(ChatMessage(
                    channel_id=channel_id,
                    msg_id=str(m.id),
                    sender=str(sender_id) if sender_id else "",
                    text=m.message or "",
                    ts=m.date.timestamp() if m.date else time.time(),
                    raw=m,
                ))
            # Telethon yields newest-first; flip to oldest-first.
            return list(reversed(out))

        return self._run(_go())

    def send(self, channel_id: str, text: str) -> ChatMessage:
        if not self._client:
            raise AuthError("not connected; call connect() first")

        async def _go():
            ent = await self._client.get_entity(int(channel_id))
            sent = await self._client.send_message(ent, text)
            return ChatMessage(
                channel_id=channel_id,
                msg_id=str(sent.id),
                sender=str(getattr(sent, "sender_id", "") or ""),
                text=sent.message or text,
                ts=sent.date.timestamp() if sent.date else time.time(),
                raw=sent,
            )

        return self._run(_go())


__all__ = ["TelegramMessenger", "HAS_TELETHON", "DEP_NAME", "INSTALL_HINT"]
