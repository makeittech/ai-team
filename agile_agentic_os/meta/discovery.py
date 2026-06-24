"""Auto-Discovery Service (Task 4.1).

Collects every available entity from all connected adapters (via the MCP
server / I/O Bridge) so the Meta-Agent can plan an org chart over real,
existing entity_ids only.
"""

from __future__ import annotations

from ..bridge.adapters.base import Adapter, Entity
from ..bridge.mcp_server import MCPServer


class AutoDiscoveryService:
    def __init__(self, mcp: MCPServer | None = None, adapters: list[Adapter] | None = None) -> None:
        self.mcp = mcp
        self.adapters = adapters or []

    def discover(self) -> list[Entity]:
        entities: list[Entity] = []
        seen: set[str] = set()
        sources: list[list[Entity]] = []
        if self.mcp is not None:
            sources.append(self.mcp.list_entities())
        for adapter in self.adapters:
            sources.append(adapter.discover())
        for group in sources:
            for e in group:
                if e.entity_id not in seen:
                    seen.add(e.entity_id)
                    entities.append(e)
        return entities

    def inventory(self) -> dict[str, list[str]]:
        """Group entity_ids by domain prefix for quick inspection."""
        out: dict[str, list[str]] = {}
        for e in self.discover():
            domain = e.entity_id.split(".", 1)[0]
            out.setdefault(domain, []).append(e.entity_id)
        return out
