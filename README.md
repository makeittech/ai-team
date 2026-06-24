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

## Dual-Track architecture

The OS runs physical actions and agent chatter on two independent lanes:

* **Fast Track** (`routing/fast_track.py`): a lightweight, local intent classifier
  — regex *or* embedding/vector-search (`VectorIntentClassifier`) — pulls the
  entity + action out of an utterance, runs it through Guardrails and actuates in
  ~100 ms, bypassing the main LLM. If the LLM lane dies, the AC still turns off.
* **Slow Track** (`routing/slow_track.py`): the orchestrator drops the completed
  action onto an **async agent queue**; the relevant character wakes up a couple
  of seconds later and posts an in-character reaction to the chat.

## Meta-Agent (creative freedom inside a rigid schema)

`meta/wizard.py` exposes `META_AGENT_SYSTEM_PROMPT` (a Hallucination-Jail +
Strict-JSON contract for Claude 3.5 Sonnet / GPT-4o) and produces this exact,
directly-`json.loads`-able shape:

```json
{
  "system_domain": {"name": "...", "background_lore": "..."},
  "agents": [
    {
      "id": "petrovych", "name": "Petrovych", "role": "Facilities & Comfort",
      "tone_of_voice": "Grumbly, thrifty engineer... 'Давно пора, він жере кіловат на годину.'",
      "permissions": {"read_only_entities": ["sensor.power_total"],
                       "execute_entities": ["climate.living_room"]},
      "proactive_triggers": ["when sensor.power_total exceeds 5"]
    }
  ]
}
```

Natural-language `proactive_triggers` are compiled by
`orchestration/triggers.py` into structured conditions bound to State-Changed
events. A deterministic, offline planner is used when no LLM is configured; both
paths run through `MetaAgent.validate()` which drops any non-existent entity_id.

## Quick start

```python
from agile_agentic_os.orchestration import Orchestrator
from agile_agentic_os.bridge import HardwareAdapter, SoftwareAdapter

orch = Orchestrator()
orch.add_adapter(HardwareAdapter())   # Home Assistant / MQTT abstraction
orch.add_adapter(SoftwareAdapter())   # GitHub / Jira / Trello webhooks

# Meta-Agent auto-discovers entities and generates the character org chart.
config = orch.boot("серйозна веб-студія")
print(config.system_domain.name, [a.name for a in config.agents])

# Hot-reload a different lore at runtime (no process restart).
orch.boot("космічний корабель")
```

## Install & test

```bash
pip install -r requirements.txt          # or: pip install -e ".[dev]"
pytest -q
```

Core requirements are only `pydantic` and `numpy`. See `requirements.txt` for the
optional extras (`server`, `redis`, `vector`, `llm`).
