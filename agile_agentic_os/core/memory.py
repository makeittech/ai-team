"""Vector long-term memory + summarizer (Task 1.3).

A background-friendly memory subsystem:

* :class:`Summarizer` compresses raw message history into atomic *facts*
  (e.g. "The AC broke", "User likes 22C").
* :class:`VectorMemory` stores facts as embeddings and supports semantic recall.
  It uses an in-process numpy store by default and transparently upgrades to
  ChromaDB when available / requested.
* :func:`recall_memory` is the tool agents call to fetch relevant facts that
  may have already scrolled out of the active context window.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Callable

import numpy as np
from pydantic import BaseModel, Field

from .embeddings import Embedder, cosine, get_default_embedder
from .messages import Message


class MemoryFact(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    text: str
    source: str = "summary"
    ts: float = Field(default_factory=time.time)
    metadata: dict = Field(default_factory=dict)


class VectorMemory:
    """Semantic long-term store.

    Backend selection:
      * ``backend="numpy"`` (default) -- zero-dependency in-process store.
      * ``backend="chroma"``         -- persistent ChromaDB if installed.
      * ``backend="auto"``           -- chroma if importable else numpy.
    """

    def __init__(self, embedder: Embedder | None = None, backend: str = "numpy") -> None:
        self.embedder = embedder or get_default_embedder()
        self.backend = self._resolve_backend(backend)
        self._facts: list[MemoryFact] = []
        self._vectors: list[np.ndarray] = []
        self._chroma = None
        if self.backend == "chroma":
            self._init_chroma()

    @staticmethod
    def _resolve_backend(backend: str) -> str:
        if backend == "auto":
            try:
                import chromadb  # noqa: F401

                return "chroma"
            except Exception:
                return "numpy"
        return backend

    def _init_chroma(self) -> None:  # pragma: no cover - optional dependency
        import chromadb

        client = chromadb.Client()
        self._chroma = client.get_or_create_collection("aaos_memory")

    # --- write ---------------------------------------------------------
    def add_fact(self, fact: MemoryFact | str, **meta) -> MemoryFact:
        if isinstance(fact, str):
            fact = MemoryFact(text=fact, metadata=meta)
        vec = self.embedder.embed(fact.text)
        if self.backend == "chroma":  # pragma: no cover - optional dependency
            self._chroma.add(
                ids=[fact.id],
                embeddings=[vec.tolist()],
                documents=[fact.text],
                metadatas=[{"source": fact.source, "ts": fact.ts}],
            )
        self._facts.append(fact)
        self._vectors.append(vec)
        return fact

    def add_facts(self, texts: list[str], source: str = "summary") -> list[MemoryFact]:
        return [self.add_fact(MemoryFact(text=t, source=source)) for t in texts]

    # --- read ----------------------------------------------------------
    def query(self, text: str, k: int = 5, min_score: float = 0.0) -> list[tuple[MemoryFact, float]]:
        if not self._facts:
            return []
        q = self.embedder.embed(text)
        scored = [(fact, cosine(q, vec)) for fact, vec in zip(self._facts, self._vectors)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(f, s) for f, s in scored[:k] if s >= min_score]

    def __len__(self) -> int:
        return len(self._facts)


# --------------------------------------------------------------------------
# Summarizer
# --------------------------------------------------------------------------
SummaryFn = Callable[[list[Message]], list[str]]


class Summarizer:
    """Compresses messages into atomic facts.

    A pluggable :class:`LLMSummarizer` can be supplied for production. The
    default heuristic extractor is deterministic and offline: it captures
    preferences, failures and explicit state statements so that fact recall is
    testable without any model.
    """

    PREFERENCE_RE = re.compile(r"\b(like|love|prefer|want|hate|dislike|always|never)\b", re.I)
    FAILURE_RE = re.compile(r"\b(broke|broken|failed|error|down|crash|offline|overheat)\b", re.I)
    STATE_RE = re.compile(r"\b(is|=|set to|now|status)\b", re.I)

    def __init__(self, summary_fn: SummaryFn | None = None) -> None:
        self.summary_fn = summary_fn

    def summarize(self, messages: list[Message]) -> list[str]:
        if self.summary_fn is not None:
            return self.summary_fn(messages)
        return self._heuristic(messages)

    def _heuristic(self, messages: list[Message]) -> list[str]:
        facts: list[str] = []
        for m in messages:
            if m.role.value in {"system"}:
                continue
            text = m.content.strip()
            if not text:
                continue
            if (
                self.PREFERENCE_RE.search(text)
                or self.FAILURE_RE.search(text)
                or self.STATE_RE.search(text)
            ):
                author = m.author or m.role.value
                facts.append(f"[{author}] {text}")
        return facts


# --------------------------------------------------------------------------
# recall_memory tool
# --------------------------------------------------------------------------
def recall_memory(memory: VectorMemory, query: str, k: int = 3) -> dict:
    """Tool agents call to retrieve relevant long-term facts.

    Returns an MCP-style tool result.
    """

    hits = memory.query(query, k=k)
    return {
        "ok": True,
        "tool": "recall_memory",
        "query": query,
        "results": [
            {"text": f.text, "score": round(score, 4), "source": f.source, "id": f.id}
            for f, score in hits
        ],
    }
