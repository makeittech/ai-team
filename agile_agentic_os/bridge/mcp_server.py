"""MCP server (Task 2.2).

Turns normalized entities into MCP *tools* for opencode agents. The two base
tools are:

* ``get_state(entity_id)``
* ``execute_action(entity_id, action_type, payload)``

The server routes a call to whichever registered adapter owns the entity, so an
agent calls ``execute_action`` identically whether it ends up toggling a
physical lamp (HardwareAdapter) or moving a Trello card (SoftwareAdapter).

An optional ``guardrail`` callable (Stage 3) is invoked before every action; if
it raises, the action is hard-blocked and a structured error is returned (and,
when a bus is present, an ``ACTION_BLOCKED`` event is published).
"""

from __future__ import annotations

import time
from typing import Any, Callable

from pydantic import BaseModel

from .adapters.base import Adapter, Entity
from .event_bus import EventBus
from .events import EventKind, SystemEvent


class ToolError(Exception):
    """Raised to hard-block a tool call. Carries a structured detail dict."""

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


class ToolResult(BaseModel):
    ok: bool
    tool: str
    entity_id: str | None = None
    data: dict[str, Any] = {}
    error: str | None = None
    latency_ms: float | None = None


# A guardrail receives the proposed action and may raise ToolError to block it.
Guardrail = Callable[[str, str, str, dict], None]  # (actor, entity_id, action_type, payload)


class MCPServer:
    def __init__(self, bus: EventBus | None = None, guardrail: Guardrail | None = None) -> None:
        self.bus = bus
        self.guardrail = guardrail
        self.adapters: list[Adapter] = []

    # --- registration --------------------------------------------------
    def register_adapter(self, adapter: Adapter) -> None:
        adapter.bus = adapter.bus or self.bus
        self.adapters.append(adapter)

    def _find_adapter(self, entity_id: str) -> Adapter | None:
        for adapter in self.adapters:
            if adapter.owns(entity_id):
                return adapter
        return None

    def list_entities(self) -> list[Entity]:
        out: list[Entity] = []
        for adapter in self.adapters:
            out.extend(adapter.discover())
        return out

    def list_tools(self) -> list[dict[str, Any]]:
        """MCP-style tool manifest."""
        return [
            {
                "name": "get_state",
                "description": "Read the current state of an entity.",
                "input_schema": {"type": "object", "properties": {"entity_id": {"type": "string"}},
                                  "required": ["entity_id"]},
            },
            {
                "name": "execute_action",
                "description": "Perform an action on an entity (physical or software).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "action_type": {"type": "string"},
                        "payload": {"type": "object"},
                    },
                    "required": ["entity_id", "action_type"],
                },
            },
            {
                "name": "recall_memory",
                "description": "Retrieve relevant long-term facts from vector memory.",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                                  "required": ["query"]},
            },
        ]

    # --- tools ---------------------------------------------------------
    def get_state(self, entity_id: str) -> ToolResult:
        adapter = self._find_adapter(entity_id)
        if adapter is None:
            return ToolResult(ok=False, tool="get_state", entity_id=entity_id,
                              error=f"no adapter owns '{entity_id}'")
        return ToolResult(ok=True, tool="get_state", entity_id=entity_id,
                          data=adapter.get_state(entity_id))

    async def execute_action(
        self,
        entity_id: str,
        action_type: str,
        payload: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> ToolResult:
        payload = payload or {}
        start = time.perf_counter()

        adapter = self._find_adapter(entity_id)
        if adapter is None:
            return ToolResult(ok=False, tool="execute_action", entity_id=entity_id,
                              error=f"no adapter owns '{entity_id}'")

        # --- Guardrails (Stage 3) -------------------------------------
        if self.guardrail is not None:
            try:
                self.guardrail(actor, entity_id, action_type, payload)
            except ToolError as exc:
                detail = {"reason": str(exc), **exc.detail}
                if self.bus is not None:
                    await self.bus.publish(SystemEvent(
                        kind=EventKind.ACTION_BLOCKED, source="mcp", entity_id=entity_id,
                        actor=actor, payload={"action_type": action_type, **detail},
                    ))
                return ToolResult(ok=False, tool="execute_action", entity_id=entity_id,
                                  error=str(exc), data=detail,
                                  latency_ms=(time.perf_counter() - start) * 1000)

        result = adapter.execute_action(entity_id, action_type, payload)
        latency_ms = (time.perf_counter() - start) * 1000

        if self.bus is not None and result.get("ok", False):
            await self.bus.publish(SystemEvent(
                kind=EventKind.ACTION_COMPLETED, source="mcp", entity_id=entity_id, actor=actor,
                value=result.get("state"),
                payload={"action_type": action_type, "result": result},
            ))

        return ToolResult(ok=result.get("ok", False), tool="execute_action", entity_id=entity_id,
                          data=result, error=result.get("error"), latency_ms=latency_ms)
