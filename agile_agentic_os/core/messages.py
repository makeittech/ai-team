"""Message primitives shared across the OS."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Role(str, Enum):
    """Who produced a message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    AGENT = "agent"
    TOOL = "tool"
    EVENT = "event"  # normalized SystemEvent injected into context


class Message(BaseModel):
    """A single conversational/event item in a session timeline."""

    role: Role
    content: str
    author: str | None = Field(
        default=None, description="Agent id / entity id that authored this message."
    )
    ts: float = Field(default_factory=time.time)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def token_estimate(self) -> int:
        return estimate_tokens(self.content) + 4  # role/formatting overhead


def estimate_tokens(text: str) -> int:
    """Cheap, dependency-free token estimate.

    Uses the well-known ~4 chars/token heuristic with a word-count floor so
    that very long single "words" still count. This avoids a hard dependency
    on ``tiktoken`` while being good enough for windowing decisions.
    """

    if not text:
        return 0
    char_estimate = (len(text) + 3) // 4
    word_estimate = len(text.split())
    return max(char_estimate, word_estimate)
