"""Stage 5 Definition of Done.

* Two agents autonomously exchange 5 replies (no user intervention) off the back
  of a trigger event.
* LLM routing logs confirm pure-text generations spend no paid tokens while
  tool/action tasks are served by premium models.
"""

import pytest

from agile_agentic_os.agents.agent import Agent
from agile_agentic_os.bridge import EventBus, HardwareAdapter
from agile_agentic_os.bridge.events import EventKind, SystemEvent
from agile_agentic_os.config import Settings
from agile_agentic_os.meta.schema import AgentSpec, CompiledTrigger
from agile_agentic_os.orchestration import AgentToAgentRouter, ProactiveTriggerEngine
from agile_agentic_os.routing import LLMRouter, RouteTag


@pytest.mark.asyncio
async def test_two_agents_exchange_five_replies_from_trigger_event():
    bus = EventBus()
    router = LLMRouter(Settings())

    producer = Agent(AgentSpec(id="producer", role="Studio Producer"), router=router)
    director = Agent(AgentSpec(id="director", role="Technical Director"), router=router)
    agents = {a.id: a for a in (producer, director)}

    a2a = AgentToAgentRouter(bus, agents)
    proactive = ProactiveTriggerEngine(bus)
    proactive.register("producer", CompiledTrigger(
        id="power_high", agent_id="producer", entity_id="sensor.power_total",
        operator=">", threshold=5,
        reaction="@director power draw exceeded 5kW, what's our plan?",
    ))

    # A real-world trigger event enters the bus (no user typing anything).
    await bus.publish(SystemEvent(
        kind=EventKind.STATE_CHANGED, source="home_assistant",
        entity_id="sensor.power_total", attribute="state", value=7.3,
    ))
    assert proactive.fired, "trigger should have fired off the event"
    opening = proactive.fired[0]["text"]

    # The trigger kicks off an autonomous 5-reply volley between the two agents.
    transcript = await a2a.converse("producer", "director", opening, turns=5)

    assert len(transcript) == 5
    speakers = [t["from"] for t in transcript]
    # Strict alternation, both agents participate, no "user" anywhere.
    assert speakers == ["director", "producer", "director", "producer", "director"]
    assert "user" not in speakers
    assert all(t["text"] for t in transcript)


@pytest.mark.asyncio
async def test_mention_routing_makes_message_input_for_other_agent():
    bus = EventBus()
    a = Agent(AgentSpec(id="alice", role="A"))
    b = Agent(AgentSpec(id="bob", role="B"))
    a2a = AgentToAgentRouter(bus, {"alice": a, "bob": b}, max_hops=2)

    await bus.publish(SystemEvent(
        kind=EventKind.MESSAGE, source="chat", actor="alice", value="hey @bob can you check this?",
    ))
    assert any(t["from"] == "bob" for t in a2a.transcript)


def test_llm_routing_idle_chatter_is_free_actions_are_premium():
    settings = Settings(
        local_model="ollama/qwen2.5:0.5b",
        premium_model="anthropic/claude-3-5-sonnet",
    )
    router = LLMRouter(settings)

    for i in range(5):
        router.complete([{"role": "user", "content": f"idle musing {i}"}], tag=RouteTag.IDLE_CHATTER)
    for i in range(3):
        router.complete(
            [{"role": "user", "content": f"please toggle the light {i}"}],
            tag=RouteTag.ACTION_REQUIRED,
        )

    idle = router.decisions_for(RouteTag.IDLE_CHATTER)
    action = router.decisions_for(RouteTag.ACTION_REQUIRED)

    # Idle chatter: routed to local/free, never paid, zero cost.
    assert len(idle) == 5
    assert all(d.paid is False and d.cost == 0.0 for d in idle)
    assert all(d.model == settings.local_model and d.tier == "local" for d in idle)

    # Action work: routed to premium, paid, non-zero cost.
    assert len(action) == 3
    assert all(d.paid is True and d.cost > 0.0 for d in action)
    assert all(d.model == settings.premium_model for d in action)

    # The bill comes only from the action calls.
    assert router.total_paid_cost == round(sum(d.cost for d in action), 6)


def test_tool_use_forces_premium_even_when_untagged():
    router = LLMRouter(Settings())
    decision = router.complete([{"role": "user", "content": "do it"}], has_tools=True)
    assert decision.tag == RouteTag.ACTION_REQUIRED
    assert decision.paid is True
    assert decision.tier == "premium"


def test_trigger_parser_compiles_natural_language_to_state_conditions():
    from agile_agentic_os.bridge.adapters.base import Entity, EntityKind
    from agile_agentic_os.orchestration import TriggerParser

    entities = [
        Entity(entity_id="sensor.power_total", kind=EntityKind.SENSOR),
        Entity(entity_id="sensor.living_room_temp", kind=EntityKind.SENSOR),
        Entity(entity_id="light.kitchen", kind=EntityKind.ACTUATOR, actions=["turn_on", "turn_off"]),
    ]
    parser = TriggerParser(entities)

    # English: "exceeds 5" -> '>' 5 on the power sensor.
    t1 = parser.parse("eng_eng", "when power consumption exceeds 5 kW")
    assert t1 and t1.entity_id == "sensor.power_total" and t1.operator == ">" and t1.threshold == 5.0

    # Ukrainian: "падає нижче 18" -> '<' 18 on the temperature sensor.
    t2 = parser.parse("ua", "коли температура падає нижче 18")
    assert t2 and t2.entity_id == "sensor.living_room_temp" and t2.operator == "<" and t2.threshold == 18.0

    # "turns on" -> categorical == "on" on the light.
    t3 = parser.parse("ua2", "коли вмикається світло вночі")
    assert t3 and t3.entity_id == "light.kitchen" and t3.operator == "==" and t3.threshold == "on"

    # Unresolvable / no entity -> dropped (no hallucinated binding).
    assert parser.parse("x", "when the coffee machine is happy") is None


@pytest.mark.asyncio
async def test_proactive_fires_on_compiled_string_trigger_via_orchestrator():
    from agile_agentic_os.orchestration import Orchestrator
    from agile_agentic_os.bridge import HardwareAdapter

    orch = Orchestrator()
    orch.add_adapter(HardwareAdapter())
    orch.boot("Smart Home")

    # Drive the temperature sensor above the compiled threshold (28).
    await orch.bus.publish(SystemEvent(
        kind=EventKind.STATE_CHANGED, source="home_assistant",
        entity_id="sensor.living_room_temp", attribute="state", value=31,
    ))
    assert orch.proactive.fired, "a compiled NL trigger should have fired"
