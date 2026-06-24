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

    # Valid JSON round-trip.
    payload = config.model_dump()
    text = json.dumps(payload)
    reparsed = OSConfig(**json.loads(text))
    assert reparsed.domain == "Production studio"

    # >= 3 agents.
    assert len(config.agents) >= 3

    # No hallucinated entity_ids anywhere.
    for agent in config.agents:
        for tool in agent.assigned_tools:
            assert tool in valid_ids, f"hallucinated tool {tool}"
        for trig in agent.proactive_triggers:
            assert trig.entity_id in valid_ids
        for perm in agent.permissions:
            # permission globs are exact entity ids in the deterministic planner
            assert perm.entity_glob in valid_ids

    # Logical distribution: tools are partitioned (no entity owned by 2 agents),
    # and every entity is assigned to exactly one agent.
    owners: dict[str, int] = {}
    for agent in config.agents:
        for tool in agent.assigned_tools:
            owners[tool] = owners.get(tool, 0) + 1
    assert all(count == 1 for count in owners.values())
    assert set(owners) == valid_ids

    # Read-only sensors got no write permissions.
    sensor_ids = {e.entity_id for e in entities if e.kind == EntityKind.SENSOR}
    granted = {p.entity_glob for a in config.agents for p in a.permissions}
    assert sensor_ids.isdisjoint(granted)


def test_meta_agent_strips_hallucinated_entities_from_llm_output():
    entities = _fifty_mixed_entities()
    valid_ids = {e.entity_id for e in entities}

    fake_llm_json = json.dumps({
        "domain": "Production studio",
        "agents": [
            {"id": "a1", "role": "x", "assigned_tools": ["sensor.0", "ghost.does_not_exist"],
             "permissions": [], "proactive_triggers": [
                 {"id": "t1", "entity_id": "ghost.does_not_exist", "reaction": "boo"}]},
            {"id": "a2", "role": "y", "assigned_tools": ["light.1"], "permissions": [],
             "proactive_triggers": []},
            {"id": "a3", "role": "z", "assigned_tools": ["trello.card.3"], "permissions": [],
             "proactive_triggers": []},
        ],
        "limits": [],
    })

    meta = MetaAgent(llm_fn=lambda sys, usr: fake_llm_json)
    config = meta.generate(entities, "Production studio")

    all_tools = {t for a in config.agents for t in a.assigned_tools}
    assert "ghost.does_not_exist" not in all_tools
    assert all(t in valid_ids for t in all_tools)
    assert all(trig.entity_id in valid_ids for a in config.agents for trig in a.proactive_triggers)


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
    assert len(agents_v1) >= 3
    assert all(a.alive for a in instances_v1)

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
