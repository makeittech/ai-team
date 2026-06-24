"""Pydantic models for the Guardrails layer (Task 3.1)."""

from __future__ import annotations

import fnmatch
from typing import Any

from pydantic import BaseModel, Field


class GuardrailViolation(Exception):
    """Raised when an action is rejected. Carries a structured, agent-readable detail."""

    def __init__(self, rule: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message
        self.detail = detail or {}

    def to_detail(self) -> dict[str, Any]:
        return {"rule": self.rule, "reason": self.message, **self.detail}


class ActionRequest(BaseModel):
    """Validated representation of a proposed action."""

    actor: str
    entity_id: str
    action_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class Permission(BaseModel):
    """An RBAC grant: an actor may run ``actions`` against entities matching a glob."""

    entity_glob: str = "*"
    actions: list[str] = Field(default_factory=lambda: ["*"])

    def allows(self, entity_id: str, action_type: str) -> bool:
        if not fnmatch.fnmatch(entity_id, self.entity_glob):
            return False
        return any(fnmatch.fnmatch(action_type, a) for a in self.actions)


class LimitRule(BaseModel):
    """A payload/parameter validation rule (Rule 2).

    Targets an entity glob + optional action; enforces numeric bounds on a
    payload field, or forbids an action outright.
    """

    entity_glob: str = "*"
    action_type: str | None = None  # None == any action
    field: str | None = None        # payload field to bound; None for action-level rules
    min_value: float | None = None
    max_value: float | None = None
    forbid: bool = False
    message: str | None = None

    def applies(self, entity_id: str, action_type: str) -> bool:
        if not fnmatch.fnmatch(entity_id, self.entity_glob):
            return False
        if self.action_type is not None and not fnmatch.fnmatch(action_type, self.action_type):
            return False
        return True
