"""The normalized ``SystemEvent`` format (Task 2.1).

Every signal in the OS -- a temperature reading, a GitHub PR merge, a Jira
status change, a relay toggle -- is normalized into a single ``SystemEvent``
JSON shape so downstream consumers (agents, triggers, guardrails) never care
where it came from.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventKind(str, Enum):
    STATE_CHANGED = "state_changed"        # an entity's state changed
    ACTION_REQUESTED = "action_requested"  # someone asked for an action
    ACTION_COMPLETED = "action_completed"  # Fast Track / executor finished
    ACTION_BLOCKED = "action_blocked"      # guardrails rejected an action
    MESSAGE = "message"                    # free-form chat/agent message
    SYSTEM = "system"                      # lifecycle (reload, boot, ...)


class SystemEvent(BaseModel):
    """The one event format to rule them all."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    kind: EventKind
    source: str = Field(description="Adapter / origin id, e.g. 'home_assistant', 'github'.")
    entity_id: str | None = Field(default=None, description="Domain-qualified entity, e.g. 'sensor.temp'.")
    attribute: str | None = None
    value: Any = None
    payload: dict[str, Any] = Field(default_factory=dict)
    actor: str | None = Field(default=None, description="Agent/user that triggered the event.")
    ts: float = Field(default_factory=time.time)

    def to_context_text(self) -> str:
        """Render the event as a human/agent-readable context line."""
        if self.kind == EventKind.STATE_CHANGED:
            return f"[event:{self.source}] {self.entity_id}.{self.attribute or 'state'} = {self.value!r}"
        if self.kind == EventKind.ACTION_COMPLETED:
            act = self.payload.get("action_type", "action")
            return f"[event:{self.source}] {self.entity_id} {act} completed by {self.actor or 'system'}"
        if self.kind == EventKind.ACTION_BLOCKED:
            return f"[event:{self.source}] action on {self.entity_id} BLOCKED: {self.payload.get('reason')}"
        if self.kind == EventKind.MESSAGE:
            return f"[{self.actor or self.source}] {self.value}"
        return f"[event:{self.source}] {self.kind.value} {self.entity_id or ''} {self.value if self.value is not None else ''}".strip()


def normalize(source: str, raw: dict[str, Any]) -> SystemEvent:
    """Best-effort normalization of an arbitrary raw payload into SystemEvent.

    Adapters usually build ``SystemEvent`` directly, but this helper handles
    loosely-typed inbound webhooks/messages.
    """

    kind = raw.get("kind")
    if isinstance(kind, str):
        try:
            kind = EventKind(kind)
        except ValueError:
            kind = EventKind.STATE_CHANGED
    if not isinstance(kind, EventKind):
        kind = EventKind.STATE_CHANGED
    return SystemEvent(
        kind=kind,
        source=source,
        entity_id=raw.get("entity_id"),
        attribute=raw.get("attribute"),
        value=raw.get("value"),
        payload=raw.get("payload", {}) or {},
        actor=raw.get("actor"),
    )
