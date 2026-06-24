"""opencode as the real backend.

These tests prove the integration surface opencode actually uses:

* the MCP (JSON-RPC 2.0 over stdio) server opencode launches, exercised both
  in-process and as a real subprocess (`python -m ...mcp_stdio`);
* Guardrails (RBAC) enforced on MCP tool calls per opencode-agent actor;
* generation of a runnable opencode project (opencode.json mcp+models +
  .opencode/agent/*.md personas with correct tool gating and no hallucinations);
* driving opencode headless for the Slow Track (dry-run when binary absent).
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

from agile_agentic_os.bridge import HardwareAdapter, SoftwareAdapter
from agile_agentic_os.guardrails.models import Permission
from agile_agentic_os.integrations.opencode import (
    OpencodeProjectGenerator,
    OpencodeRunner,
    OpencodeSlowTrack,
)
from agile_agentic_os.integrations.opencode.mcp_stdio import (
    OpencodeMCPStdioServer,
    build_backend,
)
from agile_agentic_os.meta.schema import (
    AgentPermissions,
    AgentSpec,
    OSConfig,
    SystemDomain,
)
from agile_agentic_os.orchestration import Orchestrator


# ----------------------------- MCP stdio ----------------------------------
def test_mcp_stdio_in_process_handshake_and_tool_call():
    orch, actor = build_backend(adapters="hardware,software", actor="system")
    srv = OpencodeMCPStdioServer(orch, actor)

    init = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init["result"]["serverInfo"]["name"] == "agile-agentic-os"
    assert "protocolVersion" in init["result"]

    tools = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"get_state", "execute_action", "recall_memory"} <= names

    call = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "execute_action",
                                  "arguments": {"entity_id": "light.kitchen", "action_type": "turn_on"}}})
    assert call["result"]["isError"] is False
    payload = json.loads(call["result"]["content"][0]["text"])
    assert payload["ok"] is True

    # Notifications get no response.
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_mcp_stdio_enforces_rbac_per_actor(tmp_path):
    # An opencode agent "lights" may only touch lights.
    config = OSConfig(
        system_domain=SystemDomain(name="Test Home"),
        agents=[AgentSpec(id="lights", name="Lumen", role="Lighting",
                          permissions=AgentPermissions(execute_entities=["light.kitchen"]))],
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config.model_dump()), encoding="utf-8")

    orch, actor = build_backend(config_path=str(config_path), actor="lights")
    srv = OpencodeMCPStdioServer(orch, actor="lights")

    ok = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": "execute_action",
                                "arguments": {"entity_id": "light.kitchen", "action_type": "turn_on"}}})
    assert ok["result"]["isError"] is False

    blocked = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                          "params": {"name": "execute_action",
                                     "arguments": {"entity_id": "switch.server_rack", "action_type": "turn_off"}}})
    assert blocked["result"]["isError"] is True
    detail = json.loads(blocked["result"]["content"][0]["text"])
    assert detail["ok"] is False and "not permitted" in detail["error"]


def test_mcp_stdio_real_subprocess_transport():
    """Spawn the server exactly as opencode would and speak newline-JSON-RPC."""
    env = dict(os.environ)
    env["AAOS_ACTOR"] = "system"
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.Popen(
        [sys.executable, "-m", "agile_agentic_os.integrations.opencode.mcp_stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, cwd=os.getcwd(),
    )
    requests = "\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "get_state", "arguments": {"entity_id": "light.kitchen"}}},
    ]) + "\n"
    out, err = proc.communicate(requests, timeout=60)
    lines = [json.loads(l) for l in out.splitlines() if l.strip()]
    by_id = {m["id"]: m for m in lines}
    assert by_id[1]["result"]["serverInfo"]["name"] == "agile-agentic-os", err
    assert any(t["name"] == "execute_action" for t in by_id[2]["result"]["tools"])
    state = json.loads(by_id[3]["result"]["content"][0]["text"])
    assert state["ok"] is True


# --------------------------- project generation ---------------------------
def _studio_config() -> OSConfig:
    orch = Orchestrator()
    orch.add_adapter(HardwareAdapter())
    orch.add_adapter(SoftwareAdapter())
    return orch.boot("серйозна веб-студія")


def test_generate_runnable_opencode_project(tmp_path):
    config = _studio_config()
    valid_ids = config.entity_ids()
    gen = OpencodeProjectGenerator()
    res = gen.generate(config, str(tmp_path))

    # opencode.json: mcp block + cost-aware default models.
    oc = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert oc["$schema"].startswith("https://opencode.ai")
    assert oc["model"] and oc["small_model"]
    assert len(oc["mcp"]) == len(config.agents)
    for spec in config.agents:
        server = oc["mcp"][gen.mcp_server_name(spec)]
        assert server["type"] == "local"
        assert server["command"][-1].endswith("mcp_stdio")
        assert server["environment"]["AAOS_ACTOR"] == spec.id

    # Persisted config has no hallucinated entities.
    persisted = OSConfig(**json.loads((tmp_path / ".opencode" / "agile_os" / "config.json").read_text("utf-8")))
    for spec in persisted.agents:
        assert set(spec.permissions.all_entities()) <= valid_ids

    # One persona md per agent, with correct tool gating.
    assert len(res["agent_files"]) == len(config.agents)
    for spec in config.agents:
        md = (tmp_path / ".opencode" / "agent" / f"{spec.id}.md").read_text(encoding="utf-8")
        assert "subagent" in md
        assert spec.name in md
        names = gen.tool_names(spec)
        # read-only observers must NOT be granted execute_action.
        can_exec = bool(spec.permissions.execute_entities)
        assert f'"{names["execute_action"]}": {str(can_exec).lower()}' in md


def test_model_routing_premium_for_actuators_cheap_for_observers():
    gen = OpencodeProjectGenerator()
    actuator = AgentSpec(id="a", role="Ops",
                         permissions=AgentPermissions(execute_entities=["light.kitchen"]))
    observer = AgentSpec(id="o", role="Watch",
                         permissions=AgentPermissions(read_only_entities=["sensor.power_total"]))
    assert gen.model_for(actuator) == gen.settings.premium_model
    assert gen.model_for(observer) == gen.settings.local_model


# ------------------------------- runner -----------------------------------
def test_opencode_runner_dry_run_when_binary_absent():
    runner = OpencodeRunner(binary="definitely-not-a-real-binary-xyz")
    assert runner.dry_run is True
    result = runner.run("petrovych", "the AC was turned off")
    assert result.ok and result.dry_run
    assert "petrovych" in result.text


@pytest.mark.skipif(shutil.which("opencode") is None, reason="opencode binary not installed")
def test_real_opencode_loads_project_and_connects_to_mcp(tmp_path):
    """End-to-end: the actual opencode engine launches our MCP servers."""
    config = _studio_config()
    OpencodeProjectGenerator().generate(config, str(tmp_path))

    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        ["opencode", "mcp", "list"], cwd=str(tmp_path), env=env,
        capture_output=True, text=True, timeout=120,
    )
    out = proc.stdout + proc.stderr
    # Every generated MCP server should be reported as connected.
    assert "connected" in out, out
    for spec in config.agents:
        assert f"agile_os_{spec.id}" in out


@pytest.mark.asyncio
async def test_opencode_slow_track_uses_runner_for_reflection():
    from agile_agentic_os.bridge import EventBus, MCPServer

    bus = EventBus()
    mcp = MCPServer(bus=bus)
    mcp.register_adapter(HardwareAdapter(bus=bus))

    slow = OpencodeSlowTrack(bus, runner=OpencodeRunner(binary="definitely-not-real"))
    slow.register_interest("petrovych", "climate.*")

    await mcp.execute_action("climate.living_room", "turn_off", {}, actor="user")
    processed = await slow.drain()
    assert processed == 1
    assert slow.reactions and "petrovych" in slow.reactions[0]["text"]
