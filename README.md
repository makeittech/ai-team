# Agile Agentic OS

A continuous (infinite-session) multi-agent operating system that uses
**[opencode](https://github.com/anomalyco/opencode) as its agent backend**. Work
is split into a **Fast Track** (deterministic, LLM-free command execution) and a
**Slow Track** (generative, in-character agent behaviour). The OS talks to the
physical and software world through a Universal I/O Bridge exposed via the Model
Context Protocol (MCP), and enforces strict backend **Guardrails** (RBAC, payload
limits, rate limiting).

## opencode as the backend (the "context substitution" hack)

Instead of writing a tool-calling / sub-agent engine from scratch, we run
opencode and **swap its context**: instead of a filesystem + GitHub we hand it
**physical devices + software APIs** through MCP.

```
opencode (TS engine)  ──MCP stdio──▶  agile_agentic_os.integrations.opencode.mcp_stdio
   subagents/tools                        │  get_state · execute_action · recall_memory
   (.opencode/agent/*.md)                 ▼
                                    I/O Bridge + Guardrails ──▶ Home Assistant / GitHub / Jira / Trello
```

* `integrations/opencode/mcp_stdio.py` — a real MCP (JSON-RPC 2.0 over stdio)
  server opencode launches via its `mcp` config; exposes our bridge tools with
  per-agent RBAC enforced by Guardrails.
* `integrations/opencode/config_gen.py` — `OpencodeProjectGenerator` turns a
  Meta-Agent `OSConfig` into a runnable opencode project: `opencode.json`
  (`mcp` + cost-aware `model`/`small_model`) and `.opencode/agent/*.md` personas
  with per-agent tool gating.
* `integrations/opencode/runner.py` — drives `opencode run --agent ...` headless
  to power the Slow Track on real models.

Verified end-to-end against opencode v1.17.9: the real CLI loads the generated
project and reports every generated MCP server as `✓ connected`
(`tests/test_stage6_opencode_backend.py`).

```python
from agile_agentic_os.orchestration import Orchestrator
from agile_agentic_os.bridge import HardwareAdapter, SoftwareAdapter

orch = Orchestrator()
orch.add_adapter(HardwareAdapter()); orch.add_adapter(SoftwareAdapter())
orch.boot("серйозна веб-студія")
orch.export_opencode_project("./my-space")   # then: cd my-space && opencode
```

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
| opencode backend | MCP stdio bridge, project/agent generation, headless runner | `agile_agentic_os/integrations/opencode` | `tests/test_stage6_opencode_backend.py` |
| Channels | Telegram + Discord, ChannelManager routing | `agile_agentic_os/channels` | `tests/test_stage7_channels.py` |
| Onboarding | rich TUI wizard + CLI | `agile_agentic_os/onboarding`, `agile_agentic_os/cli.py` | `tests/test_stage8_onboarding.py` |

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

## Onboarding (TUI)

A guided wizard (built on **rich**) walks you from zero to a running space:

```bash
agile-os onboard          # or: python -m agile_agentic_os onboard
```

It: picks I/O adapters → auto-discovers entities → asks for your lore → runs the
Meta-Agent → shows the generated characters → exports a runnable opencode project
→ configures Telegram/Discord → writes a `.env`. The wizard is rendering-agnostic
(`onboarding/prompter.py`) so it is fully scriptable in tests.

Other CLI commands:

```bash
agile-os export-opencode "серйозна веб-студія" ./my-space   # generate opencode project
agile-os serve                                              # run daemon + chat channels (from .env)
agile-os mcp                                                # run the opencode MCP stdio backend
```

## Chat channels: Telegram & Discord

`channels/` connects chat platforms to the OS. Inbound messages go through the
Fast Track (instant commands) and to agents (chatter); agent / slow-track /
proactive messages are pushed back out to chat.

* **Telegram** (`channels/telegram_channel.py`) — uses **python-telegram-bot**
  (`telegram.Bot`) when installed, else a raw Bot-API transport over httpx.
* **Discord** (`channels/discord_channel.py`) — **discord.py** gateway bot for
  inbound, plus a webhook (httpx) transport for outbound.

Both use a pluggable transport, so they run against the real services with a
token, or against an injected fake in tests. Human chat users are treated as
operators (RBAC), while payload limits still apply.

```python
from agile_agentic_os.orchestration import Orchestrator
from agile_agentic_os.bridge import HardwareAdapter, SoftwareAdapter
from agile_agentic_os.channels import ChannelManager, TelegramChannel

orch = Orchestrator()
orch.add_adapter(HardwareAdapter()); orch.add_adapter(SoftwareAdapter())
orch.boot("серйозна веб-студія")

manager = ChannelManager(orch)
manager.add_channel(TelegramChannel(token="<BOT_TOKEN>", default_chat_id="<CHAT_ID>"))
# await manager.start(); await orch.start(); orch.slow_track.start()
```

## Library quick start

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
