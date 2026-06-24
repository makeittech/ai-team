"""Software adapter -- webhooks for GitHub / Jira / Trello etc.

Abstracts software work items and services behind the same Entity / action
surface as physical devices. Inbound webhooks are normalized to SystemEvents
via :meth:`Adapter.ingest_external`.
"""

from __future__ import annotations

from typing import Any, Callable

from ..event_bus import EventBus
from .base import Adapter, Entity, EntityKind


class SoftwareAdapter(Adapter):
    source = "software"

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
            Entity(entity_id="github.repo.main", kind=EntityKind.SERVICE, adapter=self.source,
                   actions=["protect_branch", "delete_branch", "merge_pr"],
                   attributes={"default_branch": "main"}),
            Entity(entity_id="github.pr.42", kind=EntityKind.TASK, adapter=self.source,
                   actions=["close", "reopen", "merge", "comment"], attributes={"status": "open"}),
            Entity(entity_id="trello.card.123", kind=EntityKind.TASK, adapter=self.source,
                   actions=["move", "close", "comment"], attributes={"status": "todo"}),
            Entity(entity_id="jira.issue.PROJ-7", kind=EntityKind.TASK, adapter=self.source,
                   actions=["transition", "assign", "comment"], attributes={"status": "open"}),
        ]

    def register(self, entity: Entity) -> None:
        entity.adapter = self.source
        self._registry[entity.entity_id] = entity
        self.set_state(entity.entity_id, **entity.attributes)

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

        if self._transport is not None:  # pragma: no cover - real API path
            return self._transport(entity_id, action_type, payload)

        # Simulated software state machine.
        if action_type == "close":
            self.set_state(entity_id, status="closed")
        elif action_type in {"reopen", "open"}:
            self.set_state(entity_id, status="open")
        elif action_type == "merge":
            self.set_state(entity_id, status="merged")
        elif action_type == "move":
            self.set_state(entity_id, status=payload.get("to", "doing"))
        elif action_type == "transition":
            self.set_state(entity_id, status=payload.get("to", "in_progress"))
        return {"ok": True, "entity_id": entity_id, "action_type": action_type, "state": self.get_state(entity_id)}
