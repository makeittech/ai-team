# Agile Agentic OS

A continuous (infinite-session) multi-agent operating system inspired by the
`opencode` philosophy. Work is split into a **Fast Track** (deterministic,
LLM-free command execution) and a **Slow Track** (generative, in-character agent
behaviour). The OS talks to the physical and software world through a Universal
I/O Bridge exposed via the Model Context Protocol (MCP), and enforces strict
backend **Guardrails** (RBAC, payload limits, rate limiting).

Everything runs with **zero external infrastructure** by default (in-process
event bus, in-memory vector store, mock LLM router). Optional integrations
(Redis, ChromaDB, LiteLLM, FastAPI) are picked up automatically when installed.

## Architecture (spec stage -> module -> DoD test)

| Stage | What | Module | DoD test |
|------|------|--------|----------|
| 1 | Infinite session, sliding-window context, vector long-term memory + `recall_memory` | `agile_agentic_os/core` | `tests/test_stage1_session_memory.py` |
| 2 | Universal Event Bus, HW/SW adapters, `SystemEvent` normalization, MCP server (`get_state` / `execute_action`) | `agile_agentic_os/bridge` | `tests/test_stage2_bridge_mcp.py` |
| 3 | Guardrails middleware (RBAC, limits, rate limit), Fast Track interceptor, Slow Track spawning | `agile_agentic_os/guardrails`, `agile_agentic_os/routing` | `tests/test_stage3_guardrails_dualtrack.py` |
| 4 | Meta-Agent: auto-discovery, config wizard, hot-reload | `agile_agentic_os/meta` | `tests/test_stage4_meta_agent.py` |
| 5 | Proactive triggers, agent-to-agent comms, dynamic LLM routing | `agile_agentic_os/orchestration`, `agile_agentic_os/routing` | `tests/test_stage5_orchestration_routing.py` |

## Quick start

```python
from agile_agentic_os.orchestration import Orchestrator
from agile_agentic_os.bridge import HardwareAdapter, SoftwareAdapter

orch = Orchestrator()
orch.add_adapter(HardwareAdapter())   # Home Assistant / MQTT abstraction
orch.add_adapter(SoftwareAdapter())   # GitHub / Jira / Trello webhooks

# Meta-Agent auto-discovers entities and generates the agent org chart.
config = orch.boot("Smart Home for a family")
print([a.id for a in config.agents])

# Hot-reload a different domain at runtime (no process restart).
orch.boot("Production studio")
```

## Install & test

```bash
pip install -r requirements.txt          # or: pip install -e ".[dev]"
pytest -q
```

Core requirements are only `pydantic` and `numpy`. See `requirements.txt` for the
optional extras (`server`, `redis`, `vector`, `llm`).
