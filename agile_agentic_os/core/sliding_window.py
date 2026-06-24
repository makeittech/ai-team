"""Sliding-window context manager (Task 1.2).

Keeps only the last ``N`` messages *and* enforces a hard token ceiling so the
active context never triggers a provider "context length exceeded" error,
regardless of how many messages flow through the session.

Evicted messages are handed to an optional callback so they can be summarized
and pushed to long-term vector memory before they leave the window.
"""

from __future__ import annotations

from collections import deque
from typing import Callable, Iterable

from .messages import Message


class SlidingWindow:
    def __init__(
        self,
        max_messages: int = 40,
        max_tokens: int = 8000,
        on_evict: Callable[[list[Message]], None] | None = None,
        pinned_system_prompt: Message | None = None,
    ) -> None:
        if max_messages < 1:
            raise ValueError("max_messages must be >= 1")
        self.max_messages = max_messages
        self.max_tokens = max_tokens
        self.on_evict = on_evict
        self.pinned = pinned_system_prompt
        self._buf: deque[Message] = deque()
        self._token_count = 0
        self.total_seen = 0
        self.total_evicted = 0

    @property
    def pinned_tokens(self) -> int:
        return self.pinned.token_estimate() if self.pinned else 0

    def set_system_prompt(self, message: Message) -> None:
        """Replace the always-pinned system prompt (used on hot-reload)."""
        self.pinned = message

    def append(self, message: Message) -> None:
        self._buf.append(message)
        self._token_count += message.token_estimate()
        self.total_seen += 1
        self._enforce()

    def extend(self, messages: Iterable[Message]) -> None:
        for m in messages:
            self.append(m)

    def _enforce(self) -> None:
        evicted: list[Message] = []
        # Enforce count ceiling.
        while len(self._buf) > self.max_messages:
            evicted.append(self._pop_left())
        # Enforce token ceiling (pinned prompt always counts).
        while self._buf and (self._token_count + self.pinned_tokens) > self.max_tokens:
            evicted.append(self._pop_left())
        if evicted:
            self.total_evicted += len(evicted)
            if self.on_evict:
                self.on_evict(evicted)

    def _pop_left(self) -> Message:
        m = self._buf.popleft()
        self._token_count -= m.token_estimate()
        return m

    # --- introspection -------------------------------------------------
    @property
    def token_count(self) -> int:
        """Total tokens in the rendered context (pinned prompt + window)."""
        return self._token_count + self.pinned_tokens

    def messages(self) -> list[Message]:
        return list(self._buf)

    def render(self) -> list[Message]:
        """Full context to send to an LLM (pinned prompt first)."""
        out: list[Message] = []
        if self.pinned:
            out.append(self.pinned)
        out.extend(self._buf)
        return out

    def __len__(self) -> int:
        return len(self._buf)
