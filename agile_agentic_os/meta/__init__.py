"""Stage 4 -- Meta-Agent: auto-discovery, config generation, hot-reload."""

from .schema import (
    AgentPermissions,
    AgentSpec,
    CompiledTrigger,
    OSConfig,
    SystemDomain,
)
from .discovery import AutoDiscoveryService
from .wizard import MetaAgent, META_AGENT_SYSTEM_PROMPT
from .hot_reload import HotReloader

__all__ = [
    "AgentPermissions",
    "AgentSpec",
    "CompiledTrigger",
    "OSConfig",
    "SystemDomain",
    "AutoDiscoveryService",
    "MetaAgent",
    "META_AGENT_SYSTEM_PROMPT",
    "HotReloader",
]
