"""Proactive Event Triggers -- the "generator of life" (Task 5.1).

Watches the normalized event stream and matches it against the
``proactive_triggers`` produced by the Meta-Agent (e.g. "grumble when power
consumption > 5kW" binds to ``sensor.power_total`` state changes). When a
trigger fires the owning agent emits an in-character message onto the bus.
"""

from __future__ import annotations

import operator as _op
import time
from typing import Awaitable, Callable

from ..bridge.event_bus import EventBus
from ..bridge.events import EventKind, SystemEvent
from ..meta.schema import ProactiveTrigger

_OPS: dict[str, Callable[[float, float], bool]] = {
    ">": _op.gt,
    "<": _op.lt,
    ">=": _op.ge,
    "<=": _op.le,
    "==": _op.eq,
    "!=": _op.ne,
}

# emit(agent_id, trigger, event) -> message text
EmitFn = Callable[[str, ProactiveTrigger, SystemEvent], "Awaitable[str] | str"]


class ProactiveTriggerEngine:
    def __init__(self, bus: EventBus, emit_fn: EmitFn | None = None) -> None:
        self.bus = bus
        self.emit_fn = emit_fn
        self._triggers: list[tuple[str, ProactiveTrigger]] = []
        self._last_fired: dict[str, float] = {}
        self.fired: list[dict] = []
        bus.subscribe(self._on_event, EventKind.STATE_CHANGED.value)

    def register(self, agent_id: str, trigger: ProactiveTrigger) -> None:
        self._triggers.append((agent_id, trigger))

    def clear(self) -> None:
        self._triggers.clear()
        self._last_fired.clear()

    def _matches(self, trigger: ProactiveTrigger, event: SystemEvent) -> bool:
        if event.entity_id != trigger.entity_id:
            return False
        if (event.attribute or "state") != trigger.attribute:
            return False
        if trigger.operator == "changed":
            return True
        op = _OPS.get(trigger.operator)
        if op is None:
            return False
        try:
            return op(float(event.value), float(trigger.threshold))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return str(event.value) == str(trigger.threshold) and trigger.operator == "=="

    async def _on_event(self, event: SystemEvent) -> None:
        now = time.monotonic()
        for agent_id, trigger in list(self._triggers):
            if not self._matches(trigger, event):
                continue
            last = self._last_fired.get(trigger.id, 0.0)
            if trigger.cooldown and (now - last) < trigger.cooldown:
                continue
            self._last_fired[trigger.id] = now
            if self.emit_fn is not None:
                res = self.emit_fn(agent_id, trigger, event)
                text = await res if hasattr(res, "__await__") else res
            else:
                text = trigger.reaction
            self.fired.append({"agent": agent_id, "trigger": trigger.id, "text": text})
            await self.bus.publish(SystemEvent(
                kind=EventKind.MESSAGE, source="proactive", actor=agent_id,
                entity_id=event.entity_id, value=text,
            ))
