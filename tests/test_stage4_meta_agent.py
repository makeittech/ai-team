"""Stage 4 Definition of Done.

* 50 mixed entities + a "Production studio" domain prompt generates valid JSON
  with >= 3 agents, tools/permissions distributed logically and with no
  hallucinated (non-existent) entity_ids.
* The system can apply a new config (hot-reload) without restarting the process
  / container -- the running session daemon keeps ticking across reloads.
"""

import asyncio
import json

import pytest

from agile_agentic_os.bridge.adapters.base import Entity, EntityKind
from agile_agentic_os.bridge import HardwareAdapter, SoftwareAdapter
from agile_agentic_os.meta import MetaAgent, OSConfig
from agile_agentic_os.orchestration import Orchestrator


def _fifty_mixed_entities() -> list[Entity]:
    entities: list[Entity] = []
    kinds_cycle = [
        (EntityKind.SENSOR, "sensor", ["state"]),
        (EntityKind.ACTUATOR, "light", ["turn_on", "turn_off"]),
        (EntityKind.ACTUATOR, "camera", ["start", "stop"]),
        (EntityKind.TASK, "trello.card", ["move", "close"]),
        (EntityKind.SERVICE, "render.farm", ["enqueue", "cancel"]),
        (EntityKind.PERSON, "person", ["page"]),
    ]
    for i in range(50):
        kind, prefix, actions = kinds_cycle[i % len(kinds_cycle)]
        eid = f"{prefix}.{i}"
        entities.append(Entity(entity_id=eid, kind=kind, actions=list(actions)))
    assert len(entities) == 50
    return entities


def test_meta_agent_generates_valid_config_no_hallucination():
    entities = _fifty_mixed_entities()
    valid_ids = {e.entity_id for e in entities}

    meta = MetaAgent()
    config = meta.generate(entities, "Production studio")

    # Strict JSON round-trip (json.loads directly, as the backend does).
    payload = config.model_dump()
    text = json.dumps(payload, ensure_ascii=False)
    reparsed = OSConfig(**json.loads(text))
    assert reparsed.system_domain.name
    assert reparsed.system_domain.background_lore

    # 2 to 4 unique characters (per the Meta-Agent contract).
    assert 2 <= len(config.agents) <= 4
    # Each character is fleshed out: name + role + detailed tone with sample phrases.
    for agent in config.agents:
        assert agent.name and agent.role and len(agent.tone_of_voice) > 20

    # No hallucinated entity_ids anywhere (Hallucination Jail).
    for agent in config.agents:
        for eid in agent.permissions.all_entities():
            assert eid in valid_ids, f"hallucinated entity {eid}"

    # Logical distribution: every entity assigned to exactly one agent.
    owners: dict[str, int] = {}
    for agent in config.agents:
        for eid in agent.permissions.all_entities():
            owners[eid] = owners.get(eid, 0) + 1
    assert all(count == 1 for count in owners.values())
    assert set(owners) == valid_ids

    # RBAC split: read-only sensors never appear in any execute_entities list.
    sensor_ids = {e.entity_id for e in entities if e.kind == EntityKind.SENSOR}
    executable = {eid for a in config.agents for eid in a.permissions.execute_entities}
    assert sensor_ids.isdisjoint(executable)


def test_meta_agent_strips_hallucinated_entities_from_llm_output():
    entities = _fifty_mixed_entities()
    valid_ids = {e.entity_id for e in entities}

    # An LLM that ignores instructions: wraps JSON in a markdown fence and
    # invents a non-existent entity_id.
    fake_llm_json = """```json
{
  "system_domain": {"name": "Studio", "background_lore": "lore"},
  "agents": [
    {"id": "a1", "name": "Boris", "role": "Engineer", "tone_of_voice": "grumpy",
     "permissions": {"read_only_entities": ["sensor.0", "ghost.does_not_exist"],
                     "execute_entities": ["light.1", "switch.fake_relay"]},
     "proactive_triggers": ["when sensor.0 changes"]},
    {"id": "a2", "name": "Olha", "role": "Manager", "tone_of_voice": "bubbly",
     "permissions": {"read_only_entities": [], "execute_entities": ["trello.card.3"]},
     "proactive_triggers": []}
  ]
}
```"""

    meta = MetaAgent(llm_fn=lambda sys, usr: fake_llm_json)
    config = meta.generate(entities, "Production studio")

    all_entities = {eid for a in config.agents for eid in a.permissions.all_entities()}
    assert "ghost.does_not_exist" not in all_entities
    assert "switch.fake_relay" not in all_entities
    assert all(eid in valid_ids for eid in all_entities)


def test_meta_agent_system_prompt_enforces_strict_json_and_jail():
    from agile_agentic_os.meta import META_AGENT_SYSTEM_PROMPT

    # The prompt must encode the hard constraints we rely on downstream.
    assert "СУВОРА ЗАБОРОНА" in META_AGENT_SYSTEM_PROMPT
    assert "entity_id" in META_AGENT_SYSTEM_PROMPT
    assert "read_only_entities" in META_AGENT_SYSTEM_PROMPT
    assert "execute_entities" in META_AGENT_SYSTEM_PROMPT
    assert "ВИКЛЮЧНО у форматі валідного JSON" in META_AGENT_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_hot_reload_without_process_restart():
    orch = Orchestrator()
    orch.add_adapter(HardwareAdapter())
    orch.add_adapter(SoftwareAdapter())

    # Start the infinite session daemon -- it must survive across reloads.
    task = orch.start()
    await asyncio.sleep(0.01)
    assert not task.done()

    cfg1 = orch.boot("Smart Home")
    gen1 = orch.hot_reloader.generation
    agents_v1 = set(orch.agents.keys())
    instances_v1 = list(orch.agents.values())
    assert 2 <= len(agents_v1) <= 4
    assert all(a.alive for a in instances_v1)
    # NL proactive triggers were compiled and bound to real entities.
    assert all(t.entity_id in cfg1.entity_ids() for t in orch.hot_reloader.compiled_triggers)

    # Apply a brand-new domain config at runtime.
    cfg2 = orch.boot("Production studio")
    gen2 = orch.hot_reloader.generation
    agents_v2 = set(orch.agents.keys())

    assert gen2 == gen1 + 1
    # Old instances were killed...
    assert all(not a.alive for a in instances_v1)
    # ...and replaced by fresh ones.
    assert all(a.alive for a in orch.agents.values())
    # The daemon never stopped during the reloads.
    assert not task.done()
    assert orch.session.running is True

    await orch.stop()
    assert isinstance(cfg1, OSConfig) and isinstance(cfg2, OSConfig)
