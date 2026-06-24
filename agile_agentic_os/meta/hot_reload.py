"""Hot-Reloading (Task 4.3).

Applies a freshly generated :class:`OSConfig` to a *running* OS without
restarting the process / Docker container:

* old sub-agent instances are shut down and discarded,
* new agents are instantiated with their new personas,
* the guardrail RBAC matrix (from ``execute_entities``) and limit rules are
  swapped in place,
* natural-language ``proactive_triggers`` are compiled (against the live entity
  list) and re-bound, and slow-track interests are rebuilt.

All mutations happen on shared, live structures, so the main session daemon loop
keeps running uninterrupted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..agents.agent import Agent
from ..guardrails.middleware import GuardrailMiddleware
from ..guardrails.models import Permission
from ..routing.llm_router import LLMRouter
from .schema import OSConfig

if TYPE_CHECKING:
    from ..bridge.adapters.base import Entity
    from ..orchestration.proactive import ProactiveTriggerEngine
    from ..orchestration.triggers import TriggerParser
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
        self.compiled_triggers: list = []

    def apply(self, config: OSConfig, entities: "list[Entity] | None" = None) -> dict:
        killed = list(self.agents.keys())

        # 1. kill old instances
        for agent in self.agents.values():
            agent.shutdown()
        self.agents.clear()

        # 2. instantiate new agents
        for spec in config.agents:
            self.agents[spec.id] = Agent(spec, router=self.router)

        # 3. swap guardrail RBAC permissions (from execute_entities) + limits
        perm_matrix: dict[str, list[Permission]] = {}
        for spec in config.agents:
            perm_matrix[spec.id] = [
                Permission(entity_glob=eid, actions=["*"])
                for eid in spec.permissions.execute_entities
            ]
        self.guardrail.apply_permissions(perm_matrix)
        for old in killed:
            if old not in self.agents:
                self.guardrail.rbac.remove_actor(old)
        self.guardrail.apply_limits(config.limits)

        # 4. compile NL triggers against the live entity list & rebind
        self.compiled_triggers = []
        if self.proactive is not None:
            self.proactive.clear()
            parser = self._make_parser(entities)
            if parser is not None:
                for spec in config.agents:
                    for trig in parser.parse_many(spec.id, spec.proactive_triggers):
                        self.proactive.register(spec.id, trig)
                        self.compiled_triggers.append(trig)

        # 5. rebuild slow-track interests over every owned entity
        if self.slow_track is not None:
            self.slow_track._interests.clear()
            for spec in config.agents:
                for eid in spec.permissions.all_entities():
                    self.slow_track.register_interest(spec.id, eid)

        self.generation += 1
        return {
            "generation": self.generation,
            "killed": killed,
            "spawned": list(self.agents.keys()),
            "agent_count": len(self.agents),
            "compiled_triggers": len(self.compiled_triggers),
        }

    @staticmethod
    def _make_parser(entities) -> "TriggerParser | None":
        if not entities:
            return None
        from ..orchestration.triggers import TriggerParser

        return TriggerParser(entities)
