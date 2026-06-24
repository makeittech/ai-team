"""Dynamic LLM routing (Task 5.3).

Routes requests to the cheapest capable provider:

* ``idle_chatter``  (pure text, no tool calls) -> local model (Ollama) or a
  free tier (Gemini Flash). Cost: 0.
* ``action_required`` (needs analysis / tool use) -> premium commercial models
  (Claude 3.5 Sonnet / GPT-4o).

Uses LiteLLM when installed & configured; otherwise a deterministic mock
backend is used so routing decisions (and the "no paid tokens for chatter"
guarantee) are fully testable offline. Every decision is logged.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ..config import Settings, get_settings


class RouteTag(str, Enum):
    IDLE_CHATTER = "idle_chatter"
    ACTION_REQUIRED = "action_required"


@dataclass
class RouteDecision:
    tag: RouteTag
    model: str
    tier: str          # "local" | "free" | "premium"
    paid: bool
    cost: float
    text: str | None = None
    ts: float = field(default_factory=time.time)


# A completion backend: (model, messages, **kw) -> response text
CompletionFn = Callable[[str, list[dict], dict], str]


class LLMRouter:
    def __init__(
        self,
        settings: Settings | None = None,
        completion_fn: CompletionFn | None = None,
        use_litellm: bool | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.completion_fn = completion_fn
        self.log: list[RouteDecision] = []
        if use_litellm is None:
            # Off by default (zero-infra, no surprise paid calls). Opt in
            # explicitly or via env so production can route through LiteLLM.
            use_litellm = (
                completion_fn is None
                and os.environ.get("AAOS_USE_LITELLM", "").lower() in {"1", "true", "yes"}
                and self._litellm_available()
            )
        self.use_litellm = use_litellm

    @staticmethod
    def _litellm_available() -> bool:
        try:
            import litellm  # noqa: F401

            return True
        except Exception:
            return False

    # --- routing policy ------------------------------------------------
    def route(self, tag: RouteTag, has_tools: bool = False) -> tuple[str, str, bool]:
        """Return (model, tier, paid) for a tag."""
        # Tool use forces premium regardless of tag.
        if tag == RouteTag.ACTION_REQUIRED or has_tools:
            return self.settings.premium_model, "premium", True
        # idle chatter -> prefer local, fall back to free tier; never paid.
        model = self.settings.local_model or self.settings.free_tier_model
        tier = "local" if self.settings.local_model else "free"
        return model, tier, False

    def classify_tag(self, has_tools: bool, requires_action: bool) -> RouteTag:
        if has_tools or requires_action:
            return RouteTag.ACTION_REQUIRED
        return RouteTag.IDLE_CHATTER

    # --- completion ----------------------------------------------------
    def complete(
        self,
        messages: list[dict],
        tag: RouteTag | None = None,
        has_tools: bool = False,
        requires_action: bool = False,
        **kwargs: Any,
    ) -> RouteDecision:
        if tag is None:
            tag = self.classify_tag(has_tools, requires_action)
        model, tier, paid = self.route(tag, has_tools=has_tools)

        text = self._invoke(model, messages, paid, kwargs)

        # Cost model: premium calls "cost" tokens, local/free cost 0.
        cost = self._estimate_cost(messages, text) if paid else 0.0
        decision = RouteDecision(tag=tag, model=model, tier=tier, paid=paid, cost=cost, text=text)
        self.log.append(decision)
        return decision

    def _invoke(self, model: str, messages: list[dict], paid: bool, kwargs: dict) -> str:
        if self.completion_fn is not None:
            return self.completion_fn(model, messages, kwargs)
        if self.use_litellm:  # pragma: no cover - optional dependency / network
            import litellm

            resp = litellm.completion(model=model, messages=messages, **kwargs)
            return resp["choices"][0]["message"]["content"]
        # Deterministic mock used in tests/offline.
        last = messages[-1]["content"] if messages else ""
        return f"[{model}] reply to: {last[:80]}"

    @staticmethod
    def _estimate_cost(messages: list[dict], text: str) -> float:
        tokens = sum(len(m.get("content", "")) for m in messages) + len(text)
        return round(tokens / 1000.0 * 0.003, 6)  # arbitrary premium $/1k

    # --- introspection -------------------------------------------------
    @property
    def total_paid_cost(self) -> float:
        return round(sum(d.cost for d in self.log if d.paid), 6)

    def decisions_for(self, tag: RouteTag) -> list[RouteDecision]:
        return [d for d in self.log if d.tag == tag]
