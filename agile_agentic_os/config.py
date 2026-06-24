"""Global configuration for the Agile Agentic OS.

Settings are intentionally simple (a frozen-ish pydantic model) so they can be
constructed in tests and overridden via environment variables in production.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Runtime settings.

    All values have safe defaults so the OS boots with zero external
    dependencies (in-process event bus, in-memory vector store, mock LLMs).
    """

    # --- Stage 1: session & memory -------------------------------------
    max_context_messages: int = Field(
        default=40, description="N: number of recent messages kept in the active window."
    )
    max_context_tokens: int = Field(
        default=8000, description="Hard ceiling for the active context window (token estimate)."
    )
    summarize_every: int = Field(
        default=20, description="M: run the summarizer after this many new messages."
    )
    idle_poll_interval: float = Field(
        default=0.05, description="Seconds the daemon idle loop waits between queue polls."
    )

    # --- Stage 2: bridge -----------------------------------------------
    redis_url: str | None = Field(default=None, description="If set, EventBus uses Redis pub/sub.")

    # --- Stage 3: guardrails / fast track ------------------------------
    rate_limit_window: float = Field(default=1.0, description="Rate-limit sliding window (seconds).")
    rate_limit_max: int = Field(default=20, description="Max actions per agent per window.")
    fast_track_max_latency_ms: float = Field(
        default=200.0, description="SLA budget for a Fast Track command."
    )

    # --- Stage 5: LLM routing ------------------------------------------
    local_model: str = Field(default="ollama/qwen2.5:0.5b")
    free_tier_model: str = Field(default="gemini/gemini-1.5-flash")
    premium_model: str = Field(default="anthropic/claude-3-5-sonnet")

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from environment variables (AAOS_* prefix)."""
        data: dict[str, object] = {}
        mapping = {
            "AAOS_MAX_CONTEXT_MESSAGES": ("max_context_messages", int),
            "AAOS_MAX_CONTEXT_TOKENS": ("max_context_tokens", int),
            "AAOS_SUMMARIZE_EVERY": ("summarize_every", int),
            "AAOS_REDIS_URL": ("redis_url", str),
            "AAOS_LOCAL_MODEL": ("local_model", str),
            "AAOS_FREE_TIER_MODEL": ("free_tier_model", str),
            "AAOS_PREMIUM_MODEL": ("premium_model", str),
        }
        for env_key, (field, caster) in mapping.items():
            raw = os.environ.get(env_key)
            if raw is not None:
                data[field] = caster(raw)
        return cls(**data)


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings."""
    return Settings.from_env()
