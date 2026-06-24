"""Stage 1 Definition of Done.

* The session runs continuously under load (10,000 messages) with no
  "token limit exceeded" condition.
* The agent recalls a fact from vector memory that was evicted from the active
  text context.
"""

import pytest

from agile_agentic_os.config import Settings
from agile_agentic_os.core import (
    InfiniteSession,
    Message,
    Role,
    VectorMemory,
    recall_memory,
)


@pytest.mark.asyncio
async def test_infinite_session_survives_10k_messages_without_token_overflow():
    settings = Settings(max_context_messages=40, max_context_tokens=4000, summarize_every=50)
    session = InfiniteSession(settings=settings)

    for i in range(10_000):
        await session.submit(Message(role=Role.USER, content=f"event #{i} " + "lorem ipsum " * 5))
    processed = await session.drain()

    assert processed == 10_000
    assert session.processed == 10_000
    # The active context window never exceeds the hard token ceiling.
    assert session.context_tokens <= settings.max_context_tokens
    assert len(session.window) <= settings.max_context_messages
    # Old history was evicted (and summarized to long-term memory), not retained.
    assert session.window.total_evicted > 0


@pytest.mark.asyncio
async def test_agent_recalls_fact_evicted_from_active_context():
    settings = Settings(max_context_messages=10, max_context_tokens=2000, summarize_every=1000)
    session = InfiniteSession(settings=settings)

    # An important fact arrives early...
    await session.submit(Message(role=Role.USER, author="user",
                                 content="I love the temperature set to 22 degrees"))
    await session.submit(Message(role=Role.USER, author="user",
                                 content="The air conditioner broke yesterday"))
    # ...then gets buried under lots of unrelated chatter.
    for i in range(200):
        await session.submit(Message(role=Role.USER, content=f"unrelated chatter line {i}"))
    await session.drain()

    # The fact is gone from the active textual context.
    active_text = " ".join(m.content for m in session.context())
    assert "22 degrees" not in active_text
    assert "air conditioner" not in active_text

    # But it can be recalled from vector long-term memory via the tool.
    result = recall_memory(session.memory, "what temperature does the user like?")
    assert result["ok"] is True
    assert any("22" in r["text"] for r in result["results"]), result

    ac = recall_memory(session.memory, "is the air conditioner working?")
    assert any("air conditioner" in r["text"].lower() for r in ac["results"]), ac


def test_vector_memory_semantic_recall_direct():
    mem = VectorMemory()
    mem.add_fact("The AC broke")
    mem.add_fact("User likes temperature 22C")
    mem.add_fact("The kitchen light is green")

    hits = mem.query("air conditioning temperature preference", k=2)
    texts = [f.text for f, _ in hits]
    assert any("22C" in t or "AC" in t for t in texts)
