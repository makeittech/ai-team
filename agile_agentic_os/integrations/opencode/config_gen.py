"""Generate a runnable *opencode* project from a Meta-Agent :class:`OSConfig`.

Output layout (in ``out_dir``)::

    opencode.json                     # mcp servers + default models
    .opencode/agent/<id>.md           # one persona per character (native opencode form)
    .opencode/agile_os/config.json    # persisted OSConfig the MCP server loads

Each character becomes an opencode **subagent** whose tools are gated to a
dedicated per-agent MCP server (so the Guardrails enforce that agent's RBAC),
and whose model is chosen cost-aware: agents that can actuate get a premium
model, read-only/observer agents get the cheap local/free model.
"""

from __future__ import annotations

import json
import os
import sys

from ...config import Settings, get_settings
from ...meta.schema import AgentSpec, OSConfig
from ...routing.llm_router import LLMRouter, RouteTag

_SCHEMA_URL = "https://opencode.ai/config.json"
_PALETTE = ["#E67E22", "#3498DB", "#2ECC71", "#9B59B6", "#E74C3C", "#1ABC9C"]


def _sanitize(value: str) -> str:
    """Mirror opencode's MCP name sanitizer: [^a-zA-Z0-9_-] -> '_'."""
    return "".join(c if (c.isalnum() or c in "_-") else "_" for c in value)


class OpencodeProjectGenerator:
    def __init__(
        self,
        settings: Settings | None = None,
        python_executable: str | None = None,
        adapters: str = "hardware,software",
        router: LLMRouter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.python = python_executable or sys.executable
        self.adapters = adapters
        self.router = router or LLMRouter(self.settings)

    # --- model routing -------------------------------------------------
    def model_for(self, spec: AgentSpec) -> str:
        """Premium model if the agent can actuate, else the cheap model."""
        can_execute = bool(spec.permissions.execute_entities)
        tag = RouteTag.ACTION_REQUIRED if can_execute else RouteTag.IDLE_CHATTER
        model, _tier, _paid = self.router.route(tag, has_tools=can_execute)
        return model

    # --- naming --------------------------------------------------------
    @staticmethod
    def mcp_server_name(spec: AgentSpec) -> str:
        return _sanitize(f"agile_os_{spec.id}")

    def tool_names(self, spec: AgentSpec) -> dict[str, str]:
        srv = self.mcp_server_name(spec)
        return {
            "get_state": f"{srv}_get_state",
            "execute_action": f"{srv}_execute_action",
            "recall_memory": f"{srv}_recall_memory",
            "list_entities": f"{srv}_list_entities",
        }

    def tool_gating(self, spec: AgentSpec) -> dict[str, bool]:
        names = self.tool_names(spec)
        gating: dict[str, bool] = {"*": False}
        gating[names["get_state"]] = True
        gating[names["recall_memory"]] = True
        gating[names["list_entities"]] = True
        # Only agents that own execute_entities may actuate.
        gating[names["execute_action"]] = bool(spec.permissions.execute_entities)
        return gating

    # --- opencode.json -------------------------------------------------
    def mcp_block(self, config: OSConfig, config_path: str) -> dict:
        block: dict[str, dict] = {}
        for spec in config.agents:
            block[self.mcp_server_name(spec)] = {
                "type": "local",
                "command": [self.python, "-m", "agile_agentic_os.integrations.opencode.mcp_stdio"],
                "environment": {
                    "AAOS_ACTOR": spec.id,
                    "AAOS_CONFIG": config_path,
                    "AAOS_ADAPTERS": self.adapters,
                },
                "enabled": True,
            }
        return block

    def to_opencode_config(self, config: OSConfig, config_path: str) -> dict:
        return {
            "$schema": _SCHEMA_URL,
            "model": self.settings.premium_model,
            "small_model": self.settings.local_model,
            "mcp": self.mcp_block(config, config_path),
        }

    # --- agent markdown ------------------------------------------------
    def to_agent_markdown(self, config: OSConfig, spec: AgentSpec, idx: int) -> str:
        color = _PALETTE[idx % len(_PALETTE)]
        gating = self.tool_gating(spec)
        front = {
            "mode": "subagent",
            "description": spec.role or spec.name,
            "model": self.model_for(spec),
            "color": color,
            "tools": gating,
        }
        # Hand-roll YAML (only simple scalars/maps) to avoid a yaml dependency.
        # NB: string scalars are double-quoted so values like "#E67E22" are not
        # parsed as YAML comments, and descriptions with ':' stay valid.
        def _scalar(v) -> str:
            if isinstance(v, bool):
                return str(v).lower()
            if isinstance(v, (int, float)):
                return str(v)
            return '"' + str(v).replace('"', '\\"') + '"'

        lines = ["---"]
        for key, value in front.items():
            if isinstance(value, dict):
                lines.append(f"{key}:")
                for k, v in value.items():
                    lines.append(f'  "{k}": {_scalar(v)}')
            else:
                lines.append(f"{key}: {_scalar(value)}")
        lines.append("---")
        front_matter = "\n".join(lines)

        names = self.tool_names(spec)
        read = ", ".join(spec.permissions.read_only_entities) or "(none)"
        execute = ", ".join(spec.permissions.execute_entities) or "(none)"
        triggers = "\n".join(f"- {t}" for t in spec.proactive_triggers) or "- (none)"
        body = f"""
You are **{spec.name}** — {spec.role} aboard "{config.system_domain.name}".

Background lore: {config.system_domain.background_lore}

Character / tone of voice: {spec.tone_of_voice}

## Your tools (via MCP)
- `{names['get_state']}` — read an entity's state.
- `{names['execute_action']}` — actuate an entity (only your own; Guardrails enforce this).
- `{names['recall_memory']}` — recall long-term facts.
- `{names['list_entities']}` — list available entities.

## Your responsibility zones
- Monitor (read-only): {read}
- Actuate (execute): {execute}

## When to speak up (proactive triggers)
{triggers}

Stay strictly in character. Never attempt to actuate an entity outside your
execute list — the backend will hard-block it and you will look foolish.
"""
        return front_matter + "\n" + body.strip() + "\n"

    # --- write project -------------------------------------------------
    def generate(self, config: OSConfig, out_dir: str) -> dict:
        os.makedirs(out_dir, exist_ok=True)
        agile_dir = os.path.join(out_dir, ".opencode", "agile_os")
        agent_dir = os.path.join(out_dir, ".opencode", "agent")
        os.makedirs(agile_dir, exist_ok=True)
        os.makedirs(agent_dir, exist_ok=True)

        # 1. persist the OSConfig for the MCP server to load.
        config_path = os.path.join(agile_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump(config.model_dump(), fh, ensure_ascii=False, indent=2)

        # 2. opencode.json (mcp servers + default models).
        oc_config = self.to_opencode_config(config, config_path)
        oc_path = os.path.join(out_dir, "opencode.json")
        with open(oc_path, "w", encoding="utf-8") as fh:
            json.dump(oc_config, fh, ensure_ascii=False, indent=2)

        # 3. one persona markdown per character.
        agent_files: list[str] = []
        for idx, spec in enumerate(config.agents):
            md = self.to_agent_markdown(config, spec, idx)
            md_path = os.path.join(agent_dir, f"{_sanitize(spec.id)}.md")
            with open(md_path, "w", encoding="utf-8") as fh:
                fh.write(md)
            agent_files.append(md_path)

        return {
            "opencode_json": oc_path,
            "config_json": config_path,
            "agent_files": agent_files,
            "agents": [s.id for s in config.agents],
        }
