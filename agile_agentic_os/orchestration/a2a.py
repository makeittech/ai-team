"""Agent-to-Agent communication (Task 5.2).

Routes one agent's message to another so it becomes that agent's input prompt,
either because the agent was @-mentioned or because the event falls in the
agent's zone of responsibility. A hop counter prevents infinite ping-pong.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Awaitable, Callable

from ..agents.agent import Agent
from ..bridge.event_bus import EventBus
from ..bridge.events import EventKind, SystemEvent

_MENTION_RE = re.compile(r"@([A-Za-z0-9_\-]+)")

ReplyFn = Callable[[str, str], "Awaitable[str] | str"]


class AgentToAgentRouter:
    def __init__(
        self,
        bus: EventBus,
        agents: dict[str, Agent] | None = None,
        reply_fn: ReplyFn | None = None,
        max_hops: int = 8,
    ) -> None:
        self.bus = bus
        self.agents = agents if agents is not None else {}
        self.reply_fn = reply_fn
        self.max_hops = max_hops
        self._zones: dict[str, list[str]] = {}  # agent_id -> entity globs
        self.transcript: list[dict] = []
        bus.subscribe(self._on_message, EventKind.MESSAGE.value)

    def register_zone(self, agent_id: str, entity_glob: str) -> None:
        self._zones.setdefault(agent_id, []).append(entity_glob)

    # --- targeting -----------------------------------------------------
    def _targets(self, event: SystemEvent) -> list[str]:
        text = str(event.value or "")
        targets: set[str] = set()
        for m in _MENTION_RE.findall(text):
            if m in self.agents:
                targets.add(m)
        if event.entity_id:
            for agent_id, globs in self._zones.items():
                if any(fnmatch.fnmatch(event.entity_id, g) for g in globs):
                    targets.add(agent_id)
        targets.discard(event.actor or "")
        return sorted(targets)

    async def _reply(self, agent_id: str, text: str) -> str:
        if self.reply_fn is not None:
            res = self.reply_fn(agent_id, text)
            return await res if hasattr(res, "__await__") else res
        agent = self.agents.get(agent_id)
        if agent is None:
            return ""
        return agent.react(text)

    async def _on_message(self, event: SystemEvent) -> None:
        hops = int(event.payload.get("hops", 0))
        if hops >= self.max_hops:
            return
        if event.source == "a2a" and not _MENTION_RE.search(str(event.value or "")):
            # Avoid echo storms: only continue an a2a chain if explicitly mentioned.
            pass
        for target in self._targets(event):
            reply = await self._reply(target, str(event.value or ""))
            self.transcript.append({"from": target, "to": event.actor, "text": reply, "hops": hops + 1})
            await self.bus.publish(SystemEvent(
                kind=EventKind.MESSAGE, source="a2a", actor=target,
                entity_id=event.entity_id, value=reply, payload={"hops": hops + 1},
            ))

    # --- deterministic driver -----------------------------------------
    async def converse(self, a_id: str, b_id: str, opening: str, turns: int = 5) -> list[dict]:
        """Drive exactly ``turns`` alternating replies between two agents.

        Returns the transcript. No user involvement after the opening line.
        """
        transcript: list[dict] = []
        speaker, listener = a_id, b_id
        message = opening
        for i in range(turns):
            reply = await self._reply(listener, f"@{speaker} {message}")
            transcript.append({"turn": i + 1, "from": listener, "to": speaker, "text": reply})
            await self.bus.publish(SystemEvent(
                kind=EventKind.MESSAGE, source="a2a", actor=listener,
                value=reply, payload={"hops": i + 1, "driver": True},
            ))
            message = reply
            speaker, listener = listener, speaker
        return transcript
