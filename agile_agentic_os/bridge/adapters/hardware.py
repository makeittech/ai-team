"""Hardware adapter -- Home Assistant (WebSocket/MQTT) abstraction.

In production this adapter speaks the Home Assistant WebSocket API / MQTT. To
keep the OS runnable and testable offline, the transport is pluggable: by
default it maintains an in-memory device registry and simulates actuation,
while exposing the *exact same* ``get_state`` / ``execute_action`` surface a
real HA connection would.
"""

from __future__ import annotations

from typing import Any, Callable

from ..event_bus import EventBus
from .base import Adapter, Entity, EntityKind


class HardwareAdapter(Adapter):
    source = "home_assistant"

    def __init__(
        self,
        bus: EventBus | None = None,
        entities: list[Entity] | None = None,
        transport: Callable[[str, str, dict], dict] | None = None,
    ) -> None:
        super().__init__(bus)
        self._registry: dict[str, Entity] = {}
        self._transport = transport
        for e in entities or self._default_entities():
            self.register(e)

    def _default_entities(self) -> list[Entity]:
        return [
            Entity(entity_id="sensor.living_room_temp", kind=EntityKind.SENSOR, adapter=self.source,
                   attributes={"unit": "C"}),
            Entity(entity_id="sensor.power_total", kind=EntityKind.SENSOR, adapter=self.source,
                   attributes={"unit": "kW"}),
            Entity(entity_id="climate.living_room", kind=EntityKind.ACTUATOR, adapter=self.source,
                   actions=["set_temperature", "turn_on", "turn_off"]),
            Entity(entity_id="light.kitchen", kind=EntityKind.ACTUATOR, adapter=self.source,
                   actions=["turn_on", "turn_off", "set_brightness"]),
            Entity(entity_id="switch.server_rack", kind=EntityKind.ACTUATOR, adapter=self.source,
                   actions=["turn_on", "turn_off"]),
        ]

    def register(self, entity: Entity) -> None:
        entity.adapter = self.source
        self._registry[entity.entity_id] = entity
        # seed a default state
        if entity.kind == EntityKind.ACTUATOR:
            self.set_state(entity.entity_id, state="off")
        elif entity.kind == EntityKind.SENSOR:
            self.set_state(entity.entity_id, state=0)

    def discover(self) -> list[Entity]:
        return list(self._registry.values())

    def owns(self, entity_id: str) -> bool:
        return entity_id in self._registry

    def execute_action(self, entity_id: str, action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if entity_id not in self._registry:
            return {"ok": False, "error": f"unknown entity '{entity_id}'"}
        entity = self._registry[entity_id]
        if entity.actions and action_type not in entity.actions:
            return {"ok": False, "error": f"action '{action_type}' not supported by {entity_id}"}

        if self._transport is not None:  # pragma: no cover - real HA path
            return self._transport(entity_id, action_type, payload)

        # Simulated actuation -> updates local state.
        if action_type == "turn_on":
            self.set_state(entity_id, state="on")
        elif action_type == "turn_off":
            self.set_state(entity_id, state="off")
        elif action_type == "set_temperature":
            self.set_state(entity_id, state="on", temperature=payload.get("temperature"))
        elif action_type == "set_brightness":
            self.set_state(entity_id, state="on", brightness=payload.get("brightness"))
        return {"ok": True, "entity_id": entity_id, "action_type": action_type, "state": self.get_state(entity_id)}
