"""Infinite session daemon (Task 1.1).

Standard opencode sessions complete a task and close. The Agile Agentic OS
needs a session that runs *forever*: it never self-terminates on goal
completion, instead it parks in an idle loop that consumes an inbound event
queue. Memory is kept bounded by a :class:`SlidingWindow`; evicted history is
summarized to long-term :class:`VectorMemory` so nothing important is lost.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from ..config import Settings, get_settings
from .memory import Summarizer, VectorMemory
from .messages import Message, Role
from .sliding_window import SlidingWindow

Handler = Callable[[Message], Awaitable[None] | None]


class InfiniteSession:
    """A continuously-running session.

    Parameters
    ----------
    settings:
        OS settings (window sizes, summarize cadence, idle interval).
    memory:
        Long-term vector memory; evicted/periodic history is summarized here.
    summarizer:
        Converts raw messages into atomic facts.
    on_message:
        Optional async/sync handler invoked for every ingested message (this is
        where the orchestrator / agents react).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        memory: VectorMemory | None = None,
        summarizer: Summarizer | None = None,
        on_message: Handler | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.memory = memory or VectorMemory()
        self.summarizer = summarizer or Summarizer()
        self.on_message = on_message

        pinned = (
            Message(role=Role.SYSTEM, content=system_prompt) if system_prompt else None
        )
        self.window = SlidingWindow(
            max_messages=self.settings.max_context_messages,
            max_tokens=self.settings.max_context_tokens,
            on_evict=self._on_evict,
            pinned_system_prompt=pinned,
        )

        self.inbox: asyncio.Queue[Message] = asyncio.Queue()
        self.running = False
        self._since_summary = 0
        self.processed = 0
        self._task: asyncio.Task | None = None

    # --- memory plumbing ----------------------------------------------
    def _on_evict(self, evicted: list[Message]) -> None:
        """Before history leaves the window, distill it into long-term facts."""
        facts = self.summarizer.summarize(evicted)
        if facts:
            self.memory.add_facts(facts, source="evicted")

    def _maybe_periodic_summary(self) -> None:
        self._since_summary += 1
        if self._since_summary >= self.settings.summarize_every:
            self._since_summary = 0
            facts = self.summarizer.summarize(self.window.messages())
            if facts:
                # De-duplicate against the most recent additions cheaply by text.
                self.memory.add_facts(facts, source="periodic")

    # --- ingestion -----------------------------------------------------
    async def submit(self, message: Message) -> None:
        await self.inbox.put(message)

    def submit_nowait(self, message: Message) -> None:
        self.inbox.put_nowait(message)

    async def _ingest(self, message: Message) -> None:
        self.window.append(message)
        self.processed += 1
        self._maybe_periodic_summary()
        if self.on_message is not None:
            result = self.on_message(message)
            if asyncio.iscoroutine(result):
                await result

    async def process_one(self, timeout: float | None = None) -> Message | None:
        """Process a single inbound message; returns it or None on timeout."""
        try:
            if timeout is None:
                message = self.inbox.get_nowait()
            else:
                message = await asyncio.wait_for(self.inbox.get(), timeout)
        except (asyncio.TimeoutError, asyncio.QueueEmpty):
            return None
        await self._ingest(message)
        self.inbox.task_done()
        return message

    async def drain(self) -> int:
        """Process everything currently queued. Returns count processed."""
        count = 0
        while True:
            msg = await self.process_one(timeout=None)
            if msg is None:
                break
            count += 1
        return count

    # --- daemon idle loop (Task 1.1) ----------------------------------
    async def run_forever(self) -> None:
        """Idle loop: never terminates on its own, only on :meth:`stop`."""
        self.running = True
        while self.running:
            msg = await self.process_one(timeout=self.settings.idle_poll_interval)
            if msg is None:
                # Idle tick -- this is where proactive/background work can hook in.
                await asyncio.sleep(0)

    def start(self) -> asyncio.Task:
        """Start the daemon as a background task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever())
        return self._task

    async def stop(self) -> None:
        self.running = False
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=1.0)
            except asyncio.TimeoutError:  # pragma: no cover - defensive
                self._task.cancel()

    # --- introspection -------------------------------------------------
    @property
    def context_tokens(self) -> int:
        return self.window.token_count

    def context(self) -> list[Message]:
        return self.window.render()
