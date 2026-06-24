"""Adapter contract for the Universal I/O Bridge.

An *adapter* abstracts a family of devices/services behind a uniform interface:

* it knows which ``entities`` it owns (for Auto-Discovery, Stage 4),
* it can report ``get_state(entity_id)``,
* it can ``execute_action(entity_id, action_type, payload)``,
* it emits normalized :class:`SystemEvent` objects onto the bus.

Concrete adapters (hardware / software) subclass :class:`Adapter`.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..event_bus import EventBus
from ..events import EventKind, SystemEvent


class EntityKind(str, Enum):
    SENSOR = "sensor"          # read-only telemetry
    ACTUATOR = "actuator"      # switch/relay/light/thermostat
    TASK = "task"              # software work item (Jira/Trello/GitHub)
    SERVICE = "service"        # software service / repo / pipeline
    PERSON = "person"          # presence / HR


class Entity(BaseModel):
    """A discoverable, addressable thing the OS can read or act on."""

    entity_id: str = Field(description="Domain-qualified id, e.g. 'light.kitchen' or 'github.repo'.")
    kind: EntityKind
    name: str = ""
    adapter: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    actions: list[str] = Field(default_factory=list, description="Supported action_types.")

    def model_post_init(self, __context) -> None:  # pydantic v2 hook
        if not self.name:
            self.name = self.entity_id


class Adapter(ABC):
    """Base adapter."""

    source: str = "adapter"

    def __init__(self, bus: EventBus | None = None) -> None:
        self.bus = bus
        self._states: dict[str, dict[str, Any]] = {}

    # --- discovery -----------------------------------------------------
    @abstractmethod
    def discover(self) -> list[Entity]:  # pragma: no cover - interface
        ...

    def owns(self, entity_id: str) -> bool:
        return any(e.entity_id == entity_id for e in self.discover())

    # --- state ---------------------------------------------------------
    def get_state(self, entity_id: str) -> dict[str, Any]:
        return dict(self._states.get(entity_id, {}))

    def set_state(self, entity_id: str, **attrs: Any) -> None:
        self._states.setdefault(entity_id, {}).update(attrs)

    # --- actions -------------------------------------------------------
    @abstractmethod
    def execute_action(self, entity_id: str, action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute an action against an entity and return a result dict."""
        ...

    # --- inbound events ------------------------------------------------
    async def emit(self, event: SystemEvent) -> None:
        if self.bus is not None:
            await self.bus.publish(event)

    async def ingest_external(self, raw: dict[str, Any]) -> SystemEvent:
        """Feed a raw external signal (webhook/MQTT msg) into the bus."""
        from ..events import normalize

        event = normalize(self.source, raw)
        if event.kind == EventKind.STATE_CHANGED and event.entity_id and event.attribute:
            self.set_state(event.entity_id, **{event.attribute: event.value})
        await self.emit(event)
        return event

    def make_state_event(self, entity_id: str, attribute: str, value: Any, actor: str | None = None) -> SystemEvent:
        return SystemEvent(
            kind=EventKind.STATE_CHANGED,
            source=self.source,
            entity_id=entity_id,
            attribute=attribute,
            value=value,
            actor=actor,
            ts=time.time(),
        )
