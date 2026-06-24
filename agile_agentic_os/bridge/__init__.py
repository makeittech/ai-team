"""Stage 2 -- Universal I/O Bridge & Model Context Protocol (MCP)."""

from .events import SystemEvent, EventKind, normalize
from .event_bus import EventBus
from .mcp_server import MCPServer, ToolResult, ToolError
from .adapters.base import Adapter, Entity, EntityKind
from .adapters.hardware import HardwareAdapter
from .adapters.software import SoftwareAdapter

__all__ = [
    "SystemEvent",
    "EventKind",
    "normalize",
    "EventBus",
    "MCPServer",
    "ToolResult",
    "ToolError",
    "Adapter",
    "Entity",
    "EntityKind",
    "HardwareAdapter",
    "SoftwareAdapter",
]
