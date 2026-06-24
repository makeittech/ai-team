"""Configuration schema produced by the Meta-Agent (Stage 4) and consumed by
the orchestrator / hot-reloader.

This is the canonical ``Agents -> Assigned Tools -> Permissions -> Tone of
Voice`` matrix.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..guardrails.models import LimitRule, Permission


class ProactiveTrigger(BaseModel):
    """A condition that, when met by the event stream, makes an agent speak/act."""

    id: str
    entity_id: str               # must reference a real entity
    attribute: str = "state"
    operator: str = ">"          # one of >, <, >=, <=, ==, !=, changed
    threshold: float | str | None = None
    reaction: str = ""           # in-character text template
    cooldown: float = 0.0


class AgentSpec(BaseModel):
    id: str
    role: str
    tone_of_voice: str = "neutral, concise"
    system_prompt: str = ""
    assigned_tools: list[str] = Field(
        default_factory=list, description="entity_ids this agent may operate on."
    )
    permissions: list[Permission] = Field(default_factory=list)
    proactive_triggers: list[ProactiveTrigger] = Field(default_factory=list)


class OSConfig(BaseModel):
    domain: str
    agents: list[AgentSpec] = Field(default_factory=list)
    limits: list[LimitRule] = Field(default_factory=list)

    def entity_ids(self) -> set[str]:
        out: set[str] = set()
        for a in self.agents:
            out.update(a.assigned_tools)
        return out
