"""Discord channel.

Inbound uses **discord.py** (gateway bot, requires the message-content intent).
Outbound can use the same bot or a dependency-light **webhook** (httpx). Both
sit behind a small :class:`DiscordTransport` protocol so a fake can be injected
for tests.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol

from .base import Channel
from .message import ChatMessage

Dispatch = Callable[[ChatMessage], "Awaitable[None]"]


class DiscordTransport(Protocol):
    async def send_message(self, channel_id: str | None, text: str) -> None: ...
    async def start(self, dispatch: Dispatch) -> None: ...
    async def stop(self) -> None: ...


class DiscordPyTransport:
    """Transport backed by discord.py (full gateway bot)."""

    def __init__(self, token: str) -> None:
        import discord  # lazy import

        self._discord = discord
        self._token = token
        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        self._dispatch: Dispatch | None = None
        self._task = None

    async def start(self, dispatch: Dispatch) -> None:
        import asyncio

        self._dispatch = dispatch

        @self._client.event
        async def on_message(message):  # noqa: ANN001
            if message.author == self._client.user:
                return
            if self._dispatch is None:
                return
            await self._dispatch(ChatMessage(
                platform="discord", chat_id=str(message.channel.id),
                user=str(message.author), text=message.content,
                user_id=str(message.author.id), message_id=str(message.id),
            ))

        self._task = asyncio.create_task(self._client.start(self._token))

    async def send_message(self, channel_id: str | None, text: str) -> None:
        if channel_id is None:
            return
        channel = self._client.get_channel(int(channel_id))
        if channel is not None:
            await channel.send(text)

    async def stop(self) -> None:
        await self._client.close()


class WebhookDiscordTransport:
    """Outbound-only transport using a Discord webhook URL (no library needed)."""

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    async def start(self, dispatch: Dispatch) -> None:  # no inbound
        return None

    async def send_message(self, channel_id: str | None, text: str) -> None:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(self.webhook_url, json={"content": text})

    async def stop(self) -> None:
        return None


def _default_transport(token: str | None, webhook_url: str | None) -> DiscordTransport:
    if token:
        try:
            import discord  # noqa: F401

            return DiscordPyTransport(token)
        except Exception:
            pass
    if webhook_url:
        return WebhookDiscordTransport(webhook_url)
    raise ValueError("DiscordChannel needs a bot token (discord.py) or a webhook_url, or a transport")


class DiscordChannel(Channel):
    platform = "discord"

    def __init__(
        self,
        token: str | None = None,
        webhook_url: str | None = None,
        default_chat_id: str | None = None,
        transport: DiscordTransport | None = None,
    ) -> None:
        super().__init__()
        self.transport = transport or _default_transport(token, webhook_url)
        self.default_chat_id = default_chat_id

    async def send(self, text: str, chat_id: str | None = None) -> None:
        target = chat_id or self.default_chat_id
        await self.transport.send_message(target, text)
        self.sent.append((target or "(webhook)", text))

    async def start(self) -> None:
        self.running = True
        await self.transport.start(self._dispatch)

    async def stop(self) -> None:
        self.running = False
        await self.transport.stop()
