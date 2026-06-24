"""Agent runtime.

An ``Agent`` is a thin, hot-swappable runtime around an :class:`AgentSpec`. It
holds a system prompt, the tools (entities) it may use, and produces textual
reactions via the :class:`LLMRouter` (so its idle chatter is cheap and its
action-bearing turns use premium models).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..routing.llm_router import LLMRouter, RouteTag

if TYPE_CHECKING:
    from ..meta.schema import AgentSpec
    from ..bridge.events import SystemEvent


class Agent:
    def __init__(self, spec: "AgentSpec", router: LLMRouter | None = None) -> None:
        self.spec = spec
        self.router = router or LLMRouter()
        self.alive = True

    @property
    def id(self) -> str:
        return self.spec.id

    def system_message(self) -> dict:
        prompt = self.spec.system_prompt or (
            f"You are '{self.spec.id}', role: {self.spec.role}. "
            f"Tone: {self.spec.tone_of_voice}. "
            f"You may operate: {', '.join(self.spec.assigned_tools) or 'nothing'}."
        )
        return {"role": "system", "content": prompt}

    def react(self, event_text: str, requires_action: bool = False) -> str:
        """Produce an in-character reaction. Routes to cheap/premium models."""
        messages = [self.system_message(), {"role": "user", "content": event_text}]
        decision = self.router.complete(
            messages,
            requires_action=requires_action,
            has_tools=requires_action,
        )
        return decision.text or ""

    def chatter(self, prompt: str) -> str:
        """Idle, tool-free chatter -- always routed to cheap models."""
        messages = [self.system_message(), {"role": "user", "content": prompt}]
        decision = self.router.complete(messages, tag=RouteTag.IDLE_CHATTER)
        return decision.text or ""

    def shutdown(self) -> None:
        self.alive = False
