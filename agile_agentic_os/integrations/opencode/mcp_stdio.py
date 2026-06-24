"""Real MCP server (JSON-RPC 2.0 over stdio) that opencode launches.

opencode connects to MCP servers declared in ``opencode.json`` under the ``mcp``
key with ``{"type": "local", "command": [...]}``. It then exposes that server's
tools to its agents as ``<server>_<tool>`` (e.g. ``agile_os_alice_execute_action``).

This module is that server. Run it as::

    python -m agile_agentic_os.integrations.opencode.mcp_stdio

Environment:
    AAOS_ACTOR     -- the agent id whose RBAC the Guardrails enforce (default "system").
    AAOS_CONFIG    -- path to a persisted OSConfig JSON (the Meta-Agent output).
    AAOS_ADAPTERS  -- comma list of adapters to load: "hardware,software" (default both).

It speaks the subset of MCP that opencode needs: ``initialize``, ``tools/list``,
``tools/call`` (+ ``ping`` and ``notifications/*``). Messages are newline-delimited
JSON, per the MCP stdio transport.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from ...bridge.adapters.hardware import HardwareAdapter
from ...bridge.adapters.software import SoftwareAdapter
from ...core.memory import recall_memory
from ...guardrails.models import Permission
from ...meta.schema import OSConfig
from ...orchestration.orchestrator import Orchestrator

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "agile-agentic-os"


def build_backend(
    config_path: str | None = None,
    adapters: str = "hardware,software",
    actor: str = "system",
) -> tuple[Orchestrator, str]:
    """Construct the Orchestrator + I/O Bridge that backs the MCP tools."""
    orch = Orchestrator()
    wanted = {a.strip() for a in adapters.split(",") if a.strip()}
    if "hardware" in wanted:
        orch.add_adapter(HardwareAdapter())
    if "software" in wanted:
        orch.add_adapter(SoftwareAdapter())

    entities = orch.discovery.discover()
    if config_path and os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as fh:
            config = OSConfig(**json.load(fh))
        orch.apply_config(config, entities)
    elif entities:
        # No persisted org chart -> generate a default one so RBAC is populated.
        orch.boot("Smart Home")

    # "system" actor (or an unknown actor) gets full access so direct/system
    # calls work; real agents are constrained by the applied config.
    if actor == "system" or actor not in orch.guardrail.rbac._grants:
        orch.guardrail.rbac.grant(actor, Permission(entity_glob="*", actions=["*"]))
    return orch, actor


class OpencodeMCPStdioServer:
    def __init__(self, orchestrator: Orchestrator, actor: str = "system") -> None:
        self.orch = orchestrator
        self.actor = actor
        self.loop = asyncio.new_event_loop()

    # --- MCP method handlers ------------------------------------------
    def tool_manifest(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "get_state",
                "description": "Read the current state of a physical or software entity.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"entity_id": {"type": "string"}},
                    "required": ["entity_id"],
                },
            },
            {
                "name": "execute_action",
                "description": (
                    "Perform an action on an entity (light, thermostat, relay, "
                    "GitHub/Jira/Trello task, ...). Guardrails (RBAC, limits, rate "
                    "limiting) are enforced; a blocked call returns a detailed reason."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "action_type": {"type": "string"},
                        "payload": {"type": "object"},
                    },
                    "required": ["entity_id", "action_type"],
                },
            },
            {
                "name": "recall_memory",
                "description": "Retrieve relevant long-term facts from vector memory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "list_entities",
                "description": "List all entities available across the I/O bridge.",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "get_state":
            res = self.orch.mcp.get_state(args["entity_id"]).model_dump()
        elif name == "execute_action":
            coro = self.orch.mcp.execute_action(
                entity_id=args["entity_id"],
                action_type=args["action_type"],
                payload=args.get("payload") or {},
                actor=self.actor,
            )
            res = self.loop.run_until_complete(coro).model_dump()
        elif name == "recall_memory":
            res = recall_memory(self.orch.memory, args["query"])
        elif name == "list_entities":
            res = {"entities": [e.model_dump() for e in self.orch.mcp.list_entities()]}
        else:
            raise KeyError(f"unknown tool '{name}'")
        return res

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        msg_id = msg.get("id")
        # Notifications (no id) get no response.
        if method and method.startswith("notifications/"):
            return None

        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.tool_manifest()}
            elif method == "tools/call":
                params = msg.get("params") or {}
                tool_res = self.call_tool(params.get("name", ""), params.get("arguments") or {})
                is_error = tool_res.get("ok") is False
                result = {
                    "content": [{"type": "text", "text": json.dumps(tool_res, ensure_ascii=False)}],
                    "isError": bool(is_error),
                }
            else:
                return self._error(msg_id, -32601, f"method not found: {method}")
        except Exception as exc:  # pragma: no cover - defensive
            return self._error(msg_id, -32603, f"internal error: {exc}")

        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    # --- stdio loop ----------------------------------------------------
    def serve(self, stdin=None, stdout=None) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            response = self.handle(msg)
            if response is not None:
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                stdout.flush()


def main() -> None:
    actor = os.environ.get("AAOS_ACTOR", "system")
    config_path = os.environ.get("AAOS_CONFIG")
    adapters = os.environ.get("AAOS_ADAPTERS", "hardware,software")
    orch, actor = build_backend(config_path=config_path, adapters=adapters, actor=actor)
    server = OpencodeMCPStdioServer(orch, actor=actor)
    server.serve()


if __name__ == "__main__":
    main()
