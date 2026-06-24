"""Telegram channel.

Default transport uses **python-telegram-bot** (``telegram.Bot``) when it is
installed; otherwise it falls back to the raw Telegram Bot API over ``httpx``.
Both implement the same small :class:`TelegramTransport` protocol, and a fake
transport can be injected for tests.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from .base import Channel
from .message import ChatMessage


class TelegramTransport(Protocol):
    async def send_message(self, chat_id: str, text: str) -> None: ...
    async def poll(self, offset: int, timeout: int = 30) -> tuple[list[ChatMessage], int]: ...


class PTBTransport:
    """Transport backed by python-telegram-bot's low-level ``Bot``."""

    def __init__(self, token: str) -> None:
        from telegram import Bot  # imported lazily

        self._bot = Bot(token)

    async def send_message(self, chat_id: str, text: str) -> None:
        await self._bot.send_message(chat_id=chat_id, text=text)

    async def poll(self, offset: int, timeout: int = 30) -> tuple[list[ChatMessage], int]:
        updates = await self._bot.get_updates(offset=offset, timeout=timeout)
        messages: list[ChatMessage] = []
        next_offset = offset
        for upd in updates:
            next_offset = upd.update_id + 1
            msg = upd.message
            if msg is None or not msg.text:
                continue
            user = msg.from_user.username or msg.from_user.full_name if msg.from_user else "user"
            messages.append(ChatMessage(
                platform="telegram", chat_id=str(msg.chat_id), user=user,
                text=msg.text, user_id=str(msg.from_user.id) if msg.from_user else None,
                message_id=str(msg.message_id),
            ))
        return messages, next_offset


class HttpxTelegramTransport:
    """Dependency-light transport using the raw Bot API over httpx."""

    def __init__(self, token: str) -> None:
        self.base = f"https://api.telegram.org/bot{token}"

    async def send_message(self, chat_id: str, text: str) -> None:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(f"{self.base}/sendMessage", json={"chat_id": chat_id, "text": text})

    async def poll(self, offset: int, timeout: int = 30) -> tuple[list[ChatMessage], int]:
        import httpx

        async with httpx.AsyncClient(timeout=timeout + 5) as client:
            resp = await client.get(f"{self.base}/getUpdates",
                                    params={"offset": offset, "timeout": timeout})
            data = resp.json()
        messages: list[ChatMessage] = []
        next_offset = offset
        for upd in data.get("result", []):
            next_offset = upd["update_id"] + 1
            msg = upd.get("message")
            if not msg or "text" not in msg:
                continue
            frm = msg.get("from", {})
            user = frm.get("username") or frm.get("first_name") or "user"
            messages.append(ChatMessage(
                platform="telegram", chat_id=str(msg["chat"]["id"]), user=user,
                text=msg["text"], user_id=str(frm.get("id")) if frm.get("id") else None,
                message_id=str(msg.get("message_id")),
            ))
        return messages, next_offset


def _default_transport(token: str) -> TelegramTransport:
    try:
        import telegram  # noqa: F401

        return PTBTransport(token)
    except Exception:
        return HttpxTelegramTransport(token)


class TelegramChannel(Channel):
    platform = "telegram"

    def __init__(
        self,
        token: str | None = None,
        default_chat_id: str | None = None,
        transport: TelegramTransport | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        super().__init__()
        if transport is None:
            if not token:
                raise ValueError("TelegramChannel needs a token or an explicit transport")
            transport = _default_transport(token)
        self.transport = transport
        self.default_chat_id = default_chat_id
        self.poll_interval = poll_interval
        self._offset = 0
        self._task: asyncio.Task | None = None

    async def send(self, text: str, chat_id: str | None = None) -> None:
        target = chat_id or self.default_chat_id
        if target is None:
            return
        await self.transport.send_message(target, text)
        self.sent.append((target, text))

    async def poll_once(self, timeout: int = 0) -> int:
        """Fetch and dispatch one batch of updates; returns count dispatched."""
        messages, self._offset = await self.transport.poll(self._offset, timeout=timeout)
        for m in messages:
            await self._dispatch(m)
        return len(messages)

    async def _loop(self) -> None:
        self.running = True
        while self.running:
            try:
                await self.poll_once(timeout=30)
            except Exception:  # pragma: no cover - network resilience
                await asyncio.sleep(self.poll_interval)
            else:
                await asyncio.sleep(self.poll_interval)

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.running = False
        if self._task is not None:
            self._task.cancel()
