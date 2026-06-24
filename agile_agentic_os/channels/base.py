"""Channel base class.

A :class:`Channel` is a bidirectional connector to a chat platform. It:

* receives inbound messages and forwards them to an ``on_message`` callback
  (wired by the :class:`~agile_agentic_os.channels.manager.ChannelManager`), and
* sends outbound text via :meth:`send`.

Concrete subclasses implement the platform specifics with a pluggable transport.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from .message import ChatMessage

OnMessage = Callable[[ChatMessage], "Awaitable[None] | None"]


class Channel(ABC):
    platform: str = "channel"

    def __init__(self) -> None:
        self.on_message: OnMessage | None = None
        self.default_chat_id: str | None = None
        self.running = False
        self.sent: list[tuple[str, str]] = []  # (chat_id, text) audit log

    def bind(self, on_message: OnMessage) -> None:
        self.on_message = on_message

    async def _dispatch(self, message: ChatMessage) -> None:
        if self.on_message is None:
            return
        res = self.on_message(message)
        if hasattr(res, "__await__"):
            await res

    @abstractmethod
    async def send(self, text: str, chat_id: str | None = None) -> None:
        ...

    @abstractmethod
    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        self.running = False
