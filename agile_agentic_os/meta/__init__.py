"""Stage 4 -- Meta-Agent: auto-discovery, config generation, hot-reload."""

from .schema import AgentSpec, OSConfig, ProactiveTrigger
from .discovery import AutoDiscoveryService
from .wizard import MetaAgent, META_AGENT_SYSTEM_PROMPT
from .hot_reload import HotReloader

__all__ = [
    "AgentSpec",
    "OSConfig",
    "ProactiveTrigger",
    "AutoDiscoveryService",
    "MetaAgent",
    "META_AGENT_SYSTEM_PROMPT",
    "HotReloader",
]
