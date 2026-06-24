"""Slow Track spawning (Task 3.3).

The orchestrator reacts to ``ACTION_COMPLETED`` / ``ACTION_BLOCKED`` events that
the Fast Track produced. Affected agents learn about the action *post factum*
and generate a textual, in-character reaction into the log/chat.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from ..bridge.events import EventKind, SystemEvent
from ..bridge.event_bus import EventBus

ReactionFn = Callable[[str, SystemEvent], Awaitable[str] | str]


class SlowTrackSpawner:
    """Subscribes to action events and spawns agent reactions."""

    def __init__(self, bus: EventBus, reaction_fn: ReactionFn | None = None) -> None:
        self.bus = bus
        self.reaction_fn = reaction_fn
        self.reactions: list[dict] = []
        # which agents care about which entity globs
        self._interests: list[tuple[str, str]] = []  # (agent_id, entity_glob)
        bus.subscribe(self._on_event, EventKind.ACTION_COMPLETED.value)
        bus.subscribe(self._on_event, EventKind.ACTION_BLOCKED.value)

    def register_interest(self, agent_id: str, entity_glob: str = "*") -> None:
        self._interests.append((agent_id, entity_glob))

    def _interested_agents(self, entity_id: str | None) -> list[str]:
        import fnmatch

        if entity_id is None:
            return [a for a, _ in self._interests]
        return [a for a, glob in self._interests if fnmatch.fnmatch(entity_id, glob)]

    async def _on_event(self, event: SystemEvent) -> None:
        for agent_id in self._interested_agents(event.entity_id):
            text = None
            if self.reaction_fn is not None:
                res = self.reaction_fn(agent_id, event)
                text = await res if hasattr(res, "__await__") else res
            else:
                text = self._default_reaction(agent_id, event)
            self.reactions.append({"agent": agent_id, "event_id": event.id, "text": text})
            # echo the reaction back onto the bus as a MESSAGE event
            await self.bus.publish(SystemEvent(
                kind=EventKind.MESSAGE, source="slow_track", actor=agent_id,
                entity_id=event.entity_id, value=text,
            ))

    @staticmethod
    def _default_reaction(agent_id: str, event: SystemEvent) -> str:
        if event.kind == EventKind.ACTION_BLOCKED:
            return f"{agent_id}: heads up -- an action on {event.entity_id} was blocked ({event.payload.get('reason')})."
        act = event.payload.get("action_type", "an action")
        return f"{agent_id}: noted, {act} on {event.entity_id} completed."
