"""Stage 2 Definition of Done.

* ``execute_action`` routes to the correct abstract endpoint regardless of
  whether the entity is a physical lamp or a Trello/GitHub task.
* External events (triggers) successfully enter the agent context as inbound
  messages.
"""

import pytest

from agile_agentic_os.bridge import (
    EventBus,
    HardwareAdapter,
    MCPServer,
    SoftwareAdapter,
)
from agile_agentic_os.bridge.events import EventKind, SystemEvent


@pytest.mark.asyncio
async def test_execute_action_routes_uniformly_across_hardware_and_software():
    bus = EventBus()
    mcp = MCPServer(bus=bus)
    mcp.register_adapter(HardwareAdapter(bus=bus))
    mcp.register_adapter(SoftwareAdapter(bus=bus))

    # Physical lamp.
    lamp = await mcp.execute_action("light.kitchen", "turn_on", {}, actor="system")
    assert lamp.ok is True
    assert lamp.data["state"]["state"] == "on"

    # Software task (Trello card) -- identical call shape.
    card = await mcp.execute_action("trello.card.123", "move", {"to": "done"}, actor="system")
    assert card.ok is True
    assert card.data["state"]["status"] == "done"

    # Unknown entity -> clean error, no crash.
    nope = await mcp.execute_action("ghost.entity", "turn_on", {}, actor="system")
    assert nope.ok is False and "no adapter" in nope.error


@pytest.mark.asyncio
async def test_external_event_enters_agent_context():
    bus = EventBus()
    received: list[SystemEvent] = []
    bus.subscribe(lambda e: received.append(e), EventKind.STATE_CHANGED.value)

    hw = HardwareAdapter(bus=bus)
    # Simulate an inbound Home Assistant state update (e.g. via WS/MQTT).
    event = await hw.ingest_external({
        "kind": "state_changed",
        "entity_id": "sensor.living_room_temp",
        "attribute": "state",
        "value": 25,
    })

    assert event.kind == EventKind.STATE_CHANGED
    assert received and received[0].entity_id == "sensor.living_room_temp"
    # It renders as an agent-readable context line.
    assert "sensor.living_room_temp" in event.to_context_text()
    assert hw.get_state("sensor.living_room_temp")["state"] == 25


@pytest.mark.asyncio
async def test_action_completed_event_published_on_success():
    bus = EventBus()
    completed: list[SystemEvent] = []
    bus.subscribe(lambda e: completed.append(e), EventKind.ACTION_COMPLETED.value)
    mcp = MCPServer(bus=bus)
    mcp.register_adapter(HardwareAdapter(bus=bus))

    await mcp.execute_action("switch.server_rack", "turn_off", {}, actor="ops")
    assert completed and completed[0].entity_id == "switch.server_rack"
    assert completed[0].payload["action_type"] == "turn_off"
