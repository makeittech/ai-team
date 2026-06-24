"""Slow Track -- asynchronous reflection / role-play (Task 3.3).

The Fast Track has *already* performed the physical action in ~100 ms. The Slow
Track is a separate, parallel lane: the orchestrator drops the completed action
onto an **async agent queue** ("the user turned off the AC because they were
cold"), and the relevant agent wakes up a couple of seconds later and posts an
in-character reaction to the chat.

This decoupling is what gives the system its key properties:
* instant smart-home responsiveness (Fast Track), and
* gamified "life" + fault tolerance (if the LLM lane stalls or dies, the action
  still happened).
"""

from __future__ import annotations

import asyncio
import fnmatch
from typing import Awaitable, Callable

from ..bridge.event_bus import EventBus
from ..bridge.events import EventKind, SystemEvent

ReactionFn = Callable[[str, SystemEvent], Awaitable[str] | str]


class SlowTrackSpawner:
    """Subscribes to action events and spawns *asynchronous* agent reactions."""

    def __init__(
        self,
        bus: EventBus,
        reaction_fn: ReactionFn | None = None,
        reflection_delay: float = 0.0,
    ) -> None:
        self.bus = bus
        self.reaction_fn = reaction_fn
        self.reflection_delay = reflection_delay  # set 2-4s in production
        self.queue: asyncio.Queue[tuple[str, SystemEvent]] = asyncio.Queue()
        self.reactions: list[dict] = []
        self._interests: list[tuple[str, str]] = []  # (agent_id, entity_glob)
        self.running = False
        self._worker: asyncio.Task | None = None
        bus.subscribe(self._enqueue, EventKind.ACTION_COMPLETED.value)
        bus.subscribe(self._enqueue, EventKind.ACTION_BLOCKED.value)

    def register_interest(self, agent_id: str, entity_glob: str = "*") -> None:
        self._interests.append((agent_id, entity_glob))

    def _interested_agents(self, entity_id: str | None) -> list[str]:
        if entity_id is None:
            return [a for a, _ in self._interests]
        return [a for a, glob in self._interests if fnmatch.fnmatch(entity_id, glob)]

    # --- producer: enqueue, return immediately (non-blocking) ----------
    async def _enqueue(self, event: SystemEvent) -> None:
        for agent_id in self._interested_agents(event.entity_id):
            self.queue.put_nowait((agent_id, event))

    # --- consumer ------------------------------------------------------
    async def _react(self, agent_id: str, event: SystemEvent) -> str:
        if self.reaction_fn is not None:
            res = self.reaction_fn(agent_id, event)
            return await res if hasattr(res, "__await__") else res
        return self._default_reaction(agent_id, event)

    async def _handle(self, agent_id: str, event: SystemEvent) -> None:
        if self.reflection_delay:
            await asyncio.sleep(self.reflection_delay)
        text = await self._react(agent_id, event)
        self.reactions.append({"agent": agent_id, "event_id": event.id, "text": text})
        await self.bus.publish(SystemEvent(
            kind=EventKind.MESSAGE, source="slow_track", actor=agent_id,
            entity_id=event.entity_id, value=text,
        ))

    async def drain(self) -> int:
        """Process all currently-queued reflections (used in tests / on demand)."""
        count = 0
        while not self.queue.empty():
            agent_id, event = self.queue.get_nowait()
            await self._handle(agent_id, event)
            self.queue.task_done()
            count += 1
        return count

    async def _run(self) -> None:
        self.running = True
        while self.running:
            try:
                agent_id, event = await asyncio.wait_for(self.queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            await self._handle(agent_id, event)
            self.queue.task_done()

    def start(self) -> asyncio.Task:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())
        return self._worker

    async def stop(self) -> None:
        self.running = False
        if self._worker is not None:
            try:
                await asyncio.wait_for(self._worker, timeout=1.0)
            except asyncio.TimeoutError:  # pragma: no cover - defensive
                self._worker.cancel()

    @staticmethod
    def _default_reaction(agent_id: str, event: SystemEvent) -> str:
        if event.kind == EventKind.ACTION_BLOCKED:
            return f"{agent_id}: heads up -- an action on {event.entity_id} was blocked ({event.payload.get('reason')})."
        act = event.payload.get("action_type", "an action")
        return f"{agent_id}: noted, {act} on {event.entity_id} completed."
