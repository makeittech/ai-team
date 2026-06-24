"""Top-level orchestrator that wires all five stages together.

This is the convenience entry-point: it builds the event bus, I/O bridge + MCP,
guardrails, dual-track routing, memory-backed infinite session, the meta-agent
and the proactive / agent-to-agent subsystems, and supports booting an org
chart from a domain description with hot-reload.
"""

from __future__ import annotations

import asyncio

from ..agents.agent import Agent
from ..bridge.adapters.base import Adapter
from ..bridge.event_bus import EventBus
from ..bridge.events import EventKind, SystemEvent
from ..bridge.mcp_server import MCPServer
from ..config import Settings, get_settings
from ..core.memory import Summarizer, VectorMemory
from ..core.messages import Message, Role
from ..core.session import InfiniteSession
from ..guardrails.middleware import GuardrailMiddleware
from ..meta.discovery import AutoDiscoveryService
from ..meta.hot_reload import HotReloader
from ..meta.schema import OSConfig
from ..meta.wizard import MetaAgent
from ..routing.fast_track import FastTrackInterceptor
from ..routing.llm_router import LLMRouter
from ..routing.slow_track import SlowTrackSpawner
from .a2a import AgentToAgentRouter
from .proactive import ProactiveTriggerEngine


class Orchestrator:
    def __init__(self, settings: Settings | None = None, router: LLMRouter | None = None) -> None:
        self.settings = settings or get_settings()

        # Stage 2: bus + bridge
        self.bus = EventBus(self.settings)
        self.mcp = MCPServer(bus=self.bus)

        # Stage 3: guardrails -> wired into MCP as the action chokepoint
        self.guardrail = GuardrailMiddleware(settings=self.settings)
        self.mcp.guardrail = self.guardrail.as_guardrail()

        # Stage 5: LLM router shared by all agents
        self.router = router or LLMRouter(self.settings)

        # Stage 1: memory + infinite session
        self.memory = VectorMemory()
        self.session = InfiniteSession(
            settings=self.settings, memory=self.memory, summarizer=Summarizer(),
            on_message=None,
        )

        # Stage 3: dual track
        self.fast_track = FastTrackInterceptor(self.mcp)
        self.slow_track = SlowTrackSpawner(self.bus)

        # Stage 5: life + comms
        self.config: OSConfig | None = None
        self.agents: dict[str, Agent] = {}
        self.proactive = ProactiveTriggerEngine(self.bus)
        self.a2a = AgentToAgentRouter(self.bus, self.agents)

        # Stage 4: meta-agent + hot reload
        self.discovery = AutoDiscoveryService(mcp=self.mcp)
        self.meta = MetaAgent()
        self.hot_reloader = HotReloader(
            self.agents, self.guardrail, router=self.router,
            proactive=self.proactive, slow_track=self.slow_track,
        )

        # Bridge events into the session context.
        self.bus.subscribe(self._event_into_context)

    # --- bridge events into session context (Stage 2 DoD) -------------
    async def _event_into_context(self, event: SystemEvent) -> None:
        role = Role.EVENT if event.kind != EventKind.MESSAGE else Role.AGENT
        await self.session.submit(Message(
            role=role, content=event.to_context_text(), author=event.actor or event.source,
            tags=[event.kind.value],
        ))

    # --- adapters ------------------------------------------------------
    def add_adapter(self, adapter: Adapter) -> None:
        adapter.bus = adapter.bus or self.bus
        self.mcp.register_adapter(adapter)
        # Re-learn the full catalogue (works for regex or vector classifiers).
        self.fast_track.classifier.learn(self.mcp.list_entities())

    # --- boot an org chart (Stage 4) ----------------------------------
    def boot(self, lore: str) -> OSConfig:
        entities = self.discovery.discover()
        config = self.meta.generate(entities, lore)
        self.apply_config(config, entities)
        return config

    def apply_config(self, config: OSConfig, entities=None) -> dict:
        entities = entities if entities is not None else self.discovery.discover()
        self.config = config
        summary = self.hot_reloader.apply(config, entities)
        # register a2a zones over every entity each agent owns (read or execute)
        self.a2a._zones.clear()
        for spec in config.agents:
            for eid in spec.permissions.all_entities():
                self.a2a.register_zone(spec.id, eid)
        return summary

    # --- opencode backend integration ---------------------------------
    def export_opencode_project(self, out_dir: str, **kwargs) -> dict:
        """Materialise the current org chart as a runnable opencode project.

        Writes ``opencode.json`` (mcp + models) and ``.opencode/agent/*.md`` so
        the real opencode engine drives these agents against the I/O bridge.
        """
        if getattr(self, "config", None) is None:
            raise RuntimeError("no config booted yet; call boot() first")
        from ..integrations.opencode import OpencodeProjectGenerator

        generator = OpencodeProjectGenerator(settings=self.settings, router=self.router, **kwargs)
        return generator.generate(self.config, out_dir)

    # --- lifecycle -----------------------------------------------------
    def start(self) -> asyncio.Task:
        return self.session.start()

    async def stop(self) -> None:
        await self.session.stop()
