"""Fast Track interceptor (Task 3.2).

A local, LLM-free intent classifier (regex / small-SLM-pluggable) that detects
direct imperative commands ("turn off the server", "close the task") and
executes them straight through the I/O Bridge, bypassing the main LLM. On
success it emits an ``ACTION_COMPLETED`` event so the Slow Track can react.

Latency budget: a Fast Track command must complete in < 200 ms.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from ..bridge.mcp_server import MCPServer
from ..bridge.adapters.base import Entity
from ..core.embeddings import Embedder, cosine, get_default_embedder


@dataclass
class Intent:
    is_command: bool
    action_type: str | None = None
    entity_hint: str | None = None
    entity_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    raw: str = ""


# (regex, action_type) pairs. Multilingual (EN + UA) imperative patterns.
_COMMAND_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(turn off|switch off|shut down|power off|вимкни|вимкнути|вирубай)\b", re.I), "turn_off"),
    (re.compile(r"\b(turn on|switch on|power on|увімкни|увiмкнути|включи)\b", re.I), "turn_on"),
    (re.compile(r"\b(close|закрий|закрити)\b", re.I), "close"),
    (re.compile(r"\b(merge|змерджи|злий)\b", re.I), "merge"),
    (re.compile(r"\b(set (?:the )?temperature|встанови температуру)\b", re.I), "set_temperature"),
    (re.compile(r"\b(set brightness|яскравість)\b", re.I), "set_brightness"),
]

_TEMP_RE = re.compile(r"(\d{1,3})\s*(?:°|degrees|градус)?", re.I)


class IntentClassifier:
    """Regex-first classifier with an optional pluggable SLM backend.

    ``slm`` may be any callable ``(text) -> Intent | None`` (e.g. a 0.5B local
    model). When provided it is consulted only if the regex layer is unsure.
    """

    def __init__(self, entity_index: dict[str, list[str]] | None = None,
                 slm: Callable[[str], Intent | None] | None = None) -> None:
        # entity_index maps keyword -> [entity_ids] for resolution
        self.entity_index = entity_index or {}
        self.slm = slm

    def index_entities(self, entity_ids: list[str]) -> None:
        for eid in entity_ids:
            # index by last path segment and by full id words
            words = re.split(r"[._\- ]", eid.lower())
            for w in words:
                if len(w) >= 3:
                    self.entity_index.setdefault(w, [])
                    if eid not in self.entity_index[w]:
                        self.entity_index[w].append(eid)

    def learn(self, entities: list[Entity]) -> None:
        """Unified entity-learning hook (matches VectorIntentClassifier)."""
        self.index_entities([e.entity_id for e in entities])

    def _resolve_entity(self, text: str) -> str | None:
        low = text.lower()
        best: str | None = None
        best_len = 0
        for keyword, eids in self.entity_index.items():
            if keyword in low and len(keyword) > best_len and len(eids) == 1:
                best = eids[0]
                best_len = len(keyword)
        return best

    def classify(self, text: str) -> Intent:
        for pattern, action in _COMMAND_PATTERNS:
            if pattern.search(text):
                payload: dict[str, Any] = {}
                if action == "set_temperature":
                    m = _TEMP_RE.search(text)
                    if m:
                        payload["temperature"] = int(m.group(1))
                if action == "set_brightness":
                    m = _TEMP_RE.search(text)
                    if m:
                        payload["brightness"] = int(m.group(1))
                entity_id = self._resolve_entity(text)
                return Intent(
                    is_command=True, action_type=action, entity_id=entity_id,
                    payload=payload, confidence=0.9 if entity_id else 0.6, raw=text,
                )
        if self.slm is not None:
            slm_intent = self.slm(text)
            if slm_intent is not None:
                return slm_intent
        return Intent(is_command=False, raw=text, confidence=0.0)


# Action synonyms (EN + UA) used to build the vector catalog.
_ACTION_SYNONYMS: dict[str, list[str]] = {
    "turn_off": ["turn off", "switch off", "shut down", "power off", "вимкни", "вимкнути", "вирубай"],
    "turn_on": ["turn on", "switch on", "power on", "увімкни", "увiмкнути", "включи"],
    "close": ["close", "закрий", "закрити"],
    "merge": ["merge", "змерджи", "злий"],
    "set_temperature": ["set temperature", "встанови температуру", "температура"],
    "set_brightness": ["set brightness", "яскравість", "brightness"],
    "move": ["move", "перемісти", "перенеси"],
    "transition": ["transition", "переведи статус"],
    "start": ["start", "запусти", "почни"],
    "stop": ["stop", "зупини", "стоп"],
}


class VectorIntentClassifier:
    """Embedding/vector-search based intent classifier (Fast Track option).

    Builds a catalog of ``(entity_id, action)`` phrases, embeds them, and matches
    an incoming utterance by nearest-neighbour cosine similarity. With the
    default :class:`HashingEmbedder` this behaves as robust lexical matching;
    swap in a sentence-transformer for full semantic matching.
    """

    def __init__(self, embedder: Embedder | None = None, min_score: float = 0.2) -> None:
        self.embedder = embedder or get_default_embedder()
        self.min_score = min_score
        self._phrases: list[str] = []
        self._meta: list[tuple[str, str]] = []  # (entity_id, action)
        self._matrix: np.ndarray | None = None

    def _entity_tokens(self, entity_id: str) -> str:
        return " ".join(t for t in re.split(r"[._\- ]", entity_id) if t)

    def learn(self, entities: list[Entity]) -> None:
        self._phrases.clear()
        self._meta.clear()
        for e in entities:
            etoks = self._entity_tokens(e.entity_id)
            actions = e.actions or ["turn_on", "turn_off"]
            for action in actions:
                syns = _ACTION_SYNONYMS.get(action, [action.replace("_", " ")])
                phrase = f"{' '.join(syns)} {etoks}"
                self._phrases.append(phrase)
                self._meta.append((e.entity_id, action))
        self._matrix = self.embedder.embed_many(self._phrases) if self._phrases else None

    # keep API parity with IntentClassifier
    def index_entities(self, entity_ids: list[str]) -> None:  # pragma: no cover - parity shim
        pass

    def classify(self, text: str) -> Intent:
        if self._matrix is None or not len(self._meta):
            return Intent(is_command=False, raw=text)
        q = self.embedder.embed(text)
        scores = self._matrix @ q  # vectors are L2-normalized -> dot == cosine
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        if best_score < self.min_score:
            return Intent(is_command=False, raw=text, confidence=best_score)
        entity_id, action = self._meta[best_idx]
        payload: dict[str, Any] = {}
        if action in {"set_temperature", "set_brightness"}:
            m = _TEMP_RE.search(text)
            if m:
                key = "temperature" if action == "set_temperature" else "brightness"
                payload[key] = int(m.group(1))
        return Intent(is_command=True, action_type=action, entity_id=entity_id,
                      payload=payload, confidence=best_score, raw=text)


class FastTrackInterceptor:
    def __init__(self, mcp: MCPServer, classifier=None) -> None:
        self.mcp = mcp
        self.classifier = classifier or IntentClassifier()
        # auto-learn from the MCP server's entities
        self.classifier.learn(mcp.list_entities())
        self.handled = 0

    async def try_handle(self, text: str, actor: str = "user") -> dict[str, Any] | None:
        """Attempt to handle ``text`` as a direct command.

        Returns a result dict (with measured latency) if intercepted, else
        ``None`` so the caller routes it to the Slow Track / main LLM.
        """
        start = time.perf_counter()
        intent = self.classifier.classify(text)
        if not intent.is_command or not intent.entity_id or not intent.action_type:
            return None

        result = await self.mcp.execute_action(
            entity_id=intent.entity_id,
            action_type=intent.action_type,
            payload=intent.payload,
            actor=actor,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        self.handled += 1
        return {
            "fast_track": True,
            "intent": intent.__dict__,
            "result": result.model_dump(),
            "ok": result.ok,
            "latency_ms": latency_ms,
        }
