"""Hot-Reloading (Task 4.3).

Applies a freshly generated :class:`OSConfig` to a *running* OS without
restarting the process / Docker container:

* old sub-agent instances are shut down and discarded,
* new agents are instantiated with their new system prompts,
* the guardrail permission matrix and limit rules are swapped in place,
* proactive triggers and slow-track interests are rebuilt.

All mutations happen on shared, live structures, so the main session daemon
loop keeps running uninterrupted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..agents.agent import Agent
from ..guardrails.middleware import GuardrailMiddleware
from ..routing.llm_router import LLMRouter
from .schema import OSConfig

if TYPE_CHECKING:
    from ..orchestration.proactive import ProactiveTriggerEngine
    from ..routing.slow_track import SlowTrackSpawner


class HotReloader:
    def __init__(
        self,
        agents: dict[str, Agent],
        guardrail: GuardrailMiddleware,
        router: LLMRouter | None = None,
        proactive: "ProactiveTriggerEngine | None" = None,
        slow_track: "SlowTrackSpawner | None" = None,
    ) -> None:
        self.agents = agents
        self.guardrail = guardrail
        self.router = router or LLMRouter()
        self.proactive = proactive
        self.slow_track = slow_track
        self.generation = 0

    def apply(self, config: OSConfig) -> dict:
        killed = list(self.agents.keys())

        # 1. kill old instances
        for agent in self.agents.values():
            agent.shutdown()
        self.agents.clear()

        # 2. instantiate new agents
        for spec in config.agents:
            self.agents[spec.id] = Agent(spec, router=self.router)

        # 3. swap guardrail permissions + limits
        self.guardrail.apply_permissions({s.id: s.permissions for s in config.agents})
        # remove permissions for agents that no longer exist
        for old in killed:
            if old not in self.agents:
                self.guardrail.rbac.remove_actor(old)
        self.guardrail.apply_limits(config.limits)

        # 4. rebuild proactive triggers
        if self.proactive is not None:
            self.proactive.clear()
            for spec in config.agents:
                for trig in spec.proactive_triggers:
                    self.proactive.register(spec.id, trig)

        # 5. rebuild slow-track interests
        if self.slow_track is not None:
            self.slow_track._interests.clear()
            for spec in config.agents:
                for tool in spec.assigned_tools:
                    self.slow_track.register_interest(spec.id, tool)

        self.generation += 1
        return {
            "generation": self.generation,
            "killed": killed,
            "spawned": list(self.agents.keys()),
            "agent_count": len(self.agents),
        }
