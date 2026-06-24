"""Universal Event Bus (Task 2.1).

A single internal pub/sub spine. Defaults to an in-process asyncio fan-out so
the OS runs with zero infrastructure; if ``settings.redis_url`` is set (and the
``redis`` package is installed) it transparently mirrors events through Redis
pub/sub for multi-process deployments.
"""

from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

from ..config import Settings, get_settings
from .events import SystemEvent

Subscriber = Callable[[SystemEvent], Awaitable[None] | None]

WILDCARD = "*"


class EventBus:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        # topic -> list of subscribers. Topic is the EventKind value or "*".
        self._subscribers: dict[str, list[Subscriber]] = {}
        self.published = 0
        self._redis = None
        self._redis_task: asyncio.Task | None = None

    def subscribe(self, subscriber: Subscriber, topic: str = WILDCARD) -> Callable[[], None]:
        """Subscribe to a topic (an :class:`EventKind` value or ``*``).

        Returns an unsubscribe callable.
        """
        self._subscribers.setdefault(topic, []).append(subscriber)

        def _unsub() -> None:
            try:
                self._subscribers.get(topic, []).remove(subscriber)
            except ValueError:
                pass

        return _unsub

    async def publish(self, event: SystemEvent) -> None:
        self.published += 1
        await self._dispatch_local(event)
        if self._redis is not None:  # pragma: no cover - optional dependency
            await self._redis.publish("aaos.events", event.model_dump_json())

    def publish_nowait(self, event: SystemEvent) -> None:
        """Fire-and-forget publish usable from sync code/tests."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            asyncio.run(self.publish(event))

    async def _dispatch_local(self, event: SystemEvent) -> None:
        targets = list(self._subscribers.get(event.kind.value, []))
        targets += list(self._subscribers.get(WILDCARD, []))
        for sub in targets:
            res = sub(event)
            if asyncio.iscoroutine(res):
                await res

    # --- optional redis transport -------------------------------------
    async def connect_redis(self) -> bool:  # pragma: no cover - optional dependency
        if not self.settings.redis_url:
            return False
        try:
            import redis.asyncio as aioredis
        except Exception:
            return False
        self._redis = aioredis.from_url(self.settings.redis_url)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe("aaos.events")

        async def _reader() -> None:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                data = json.loads(msg["data"])
                await self._dispatch_local(SystemEvent(**data))

        self._redis_task = asyncio.create_task(_reader())
        return True
