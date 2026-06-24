"""Stage 3 Definition of Done.

* A direct command executes in < 200 ms via the Fast Track.
* An action outside an agent's permissions or physical limits is hard-blocked
  by the middleware, returning a detailed error into the agent context.
"""

import pytest

from agile_agentic_os.bridge import EventBus, HardwareAdapter, MCPServer, SoftwareAdapter
from agile_agentic_os.bridge.events import EventKind, SystemEvent
from agile_agentic_os.guardrails import GuardrailMiddleware
from agile_agentic_os.guardrails.models import LimitRule, Permission
from agile_agentic_os.routing import FastTrackInterceptor


def _build_mcp(guardrail=None):
    bus = EventBus()
    mcp = MCPServer(bus=bus, guardrail=guardrail)
    mcp.register_adapter(HardwareAdapter(bus=bus))
    mcp.register_adapter(SoftwareAdapter(bus=bus))
    return bus, mcp


@pytest.mark.asyncio
async def test_fast_track_executes_direct_command_under_200ms():
    _, mcp = _build_mcp()
    fast = FastTrackInterceptor(mcp)

    result = await fast.try_handle("turn off the switch.server_rack now", actor="user")
    assert result is not None, "command should be intercepted by Fast Track"
    assert result["ok"] is True
    assert result["latency_ms"] < 200.0, result["latency_ms"]
    # Verify it actually actuated, bypassing any LLM.
    assert mcp.get_state("switch.server_rack").data["state"] == "off"


@pytest.mark.asyncio
async def test_fast_track_ignores_non_commands():
    _, mcp = _build_mcp()
    fast = FastTrackInterceptor(mcp)
    # Pure chatter -> not a command -> falls through to Slow Track (None).
    assert await fast.try_handle("what do you think about the weather today?") is None


@pytest.mark.asyncio
async def test_rbac_blocks_unpermitted_action_with_detailed_error():
    guard = GuardrailMiddleware()
    guard.rbac.grant("agent_lights", Permission(entity_glob="light.*", actions=["*"]))
    bus, mcp = _build_mcp(guardrail=guard.as_guardrail())

    blocked_events: list[SystemEvent] = []
    bus.subscribe(lambda e: blocked_events.append(e), EventKind.ACTION_BLOCKED.value)

    # agent_lights may touch lights, but NOT the server rack.
    res = await mcp.execute_action("switch.server_rack", "turn_off", {}, actor="agent_lights")
    assert res.ok is False
    assert res.data["rule"] == "rbac"
    assert "not permitted" in res.error
    assert blocked_events and blocked_events[0].payload["rule"] == "rbac"
    assert guard.blocked_count == 1


@pytest.mark.asyncio
async def test_limit_blocks_out_of_range_temperature():
    guard = GuardrailMiddleware(enforce_rbac=False)
    guard.limits.add_rule(LimitRule(
        entity_glob="climate.*", action_type="set_temperature", field="temperature",
        max_value=30, message="temperature must not exceed 30",
    ))
    _, mcp = _build_mcp(guardrail=guard.as_guardrail())

    ok = await mcp.execute_action("climate.living_room", "set_temperature", {"temperature": 22})
    assert ok.ok is True

    bad = await mcp.execute_action("climate.living_room", "set_temperature", {"temperature": 35})
    assert bad.ok is False
    assert bad.data["rule"] == "limits"
    assert "30" in bad.error


@pytest.mark.asyncio
async def test_forbid_rule_blocks_master_branch_deletion():
    guard = GuardrailMiddleware(enforce_rbac=False)
    guard.limits.add_rule(LimitRule(
        entity_glob="github.repo*", action_type="delete_branch", forbid=True,
        message="deleting master branch is forbidden",
    ))
    _, mcp = _build_mcp(guardrail=guard.as_guardrail())

    res = await mcp.execute_action("github.repo.main", "delete_branch", {"branch": "main"})
    assert res.ok is False
    assert res.data["rule"] == "limits"


@pytest.mark.asyncio
async def test_rate_limiter_blocks_flood():
    from agile_agentic_os.guardrails.rate_limit import RateLimiter

    guard = GuardrailMiddleware(enforce_rbac=False, rate_limiter=RateLimiter(window=10, max_actions=3))
    _, mcp = _build_mcp(guardrail=guard.as_guardrail())

    outcomes = []
    for _ in range(5):
        r = await mcp.execute_action("light.kitchen", "turn_on", {}, actor="spammer")
        outcomes.append(r.ok)
    assert outcomes.count(True) == 3
    assert outcomes.count(False) == 2  # remaining 2 hit the state lock


@pytest.mark.asyncio
async def test_slow_track_reacts_to_completed_action():
    from agile_agentic_os.routing import SlowTrackSpawner

    bus, mcp = _build_mcp()
    slow = SlowTrackSpawner(bus)
    slow.register_interest("ops_agent", "switch.*")

    await mcp.execute_action("switch.server_rack", "turn_off", {}, actor="user")
    # Allow the subscriber coroutine(s) to run.
    assert slow.reactions, "slow track should have produced a reaction"
    assert slow.reactions[0]["agent"] == "ops_agent"
