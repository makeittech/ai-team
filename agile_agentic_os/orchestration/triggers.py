"""Natural-language trigger compiler (Slow Track wiring).

The Meta-Agent emits ``proactive_triggers`` as free text, e.g.:

    "коли температура падає нижче 18"
    "when power consumption exceeds 5 kW"
    "when the light turns on at night"

The orchestrator must bind those to real Home Assistant State-Changed events.
:class:`TriggerParser` turns each string into a structured
:class:`CompiledTrigger` (entity_id + operator + threshold) using only entity
ids that actually exist (no hallucinated bindings).
"""

from __future__ import annotations

import re

from ..bridge.adapters.base import Entity
from ..meta.schema import CompiledTrigger

_NUM_RE = re.compile(r"(-?\d+(?:[.,]\d+)?)")

# operator keyword -> canonical operator (EN + UA)
_LT = re.compile(r"\b(below|under|less than|lower than|drops?|falls?|нижче|менше|падає|опуска)\b", re.I)
_GT = re.compile(r"\b(above|over|more than|greater|higher|exceed\w*|вище|більше|перевищ\w*|зроста)\b", re.I)
_ON = re.compile(r"\b(turns? on|switch\w* on|вмика\w*|увімк\w*|включ\w*)\b", re.I)
_OFF = re.compile(r"\b(turns? off|switch\w* off|вимика\w*|вимкн\w*)\b", re.I)
_HIGH = re.compile(r"\b(high|peak|висок\w*)\b", re.I)
_LOW = re.compile(r"\b(low|низьк\w*)\b", re.I)

# semantic keyword -> entity_id substring
_SEMANTIC = {
    "temp": ["temperature", "температур", "темпер", "градус"],
    "power": ["power", "energy", "consumption", "kw", "квт", "енерг", "споживан", "потуж"],
    "light": ["light", "lamp", "світл", "лампа"],
    "motion": ["motion", "presence", "рух", "присутн"],
    "humid": ["humidity", "вологіст"],
    "co2": ["co2", "вуглекисл"],
    "door": ["door", "двер"],
}


class TriggerParser:
    def __init__(self, entities: list[Entity]) -> None:
        self.entities = entities
        self._index = self._build_index(entities)

    @staticmethod
    def _build_index(entities: list[Entity]) -> dict[str, list[str]]:
        index: dict[str, list[str]] = {}
        for e in entities:
            for tok in re.split(r"[._\- ]", e.entity_id.lower()):
                if len(tok) >= 3:
                    index.setdefault(tok, [])
                    if e.entity_id not in index[tok]:
                        index[tok].append(e.entity_id)
        return index

    def _resolve_entity(self, text: str) -> str | None:
        low = text.lower()
        # 1) direct entity-id mention.
        for e in self.entities:
            if e.entity_id.lower() in low:
                return e.entity_id
        # 2) token overlap with entity-id parts.
        best: str | None = None
        best_score = 0
        for tok, eids in self._index.items():
            if tok in low and len(eids) == 1:
                if len(tok) > best_score:
                    best, best_score = eids[0], len(tok)
        if best:
            return best
        # 3) semantic keyword -> substring of an entity id.
        for canon, words in _SEMANTIC.items():
            if any(w in low for w in words):
                for e in self.entities:
                    if canon in e.entity_id.lower():
                        return e.entity_id
        return None

    @staticmethod
    def _operator(text: str) -> str:
        if _OFF.search(text):
            return "off"
        if _ON.search(text):
            return "on"
        if _LT.search(text):
            return "<"
        if _GT.search(text):
            return ">"
        if _HIGH.search(text):
            return ">"
        if _LOW.search(text):
            return "<"
        return "changed"

    @staticmethod
    def _threshold(text: str) -> float | None:
        m = _NUM_RE.search(text)
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            return None

    def parse(self, agent_id: str, text: str, index: int = 0) -> CompiledTrigger | None:
        entity_id = self._resolve_entity(text)
        if entity_id is None:
            return None
        operator = self._operator(text)
        threshold = self._threshold(text)
        if operator in {"on", "off"}:
            threshold = operator
            operator = "=="
        elif operator in {"<", ">"} and threshold is None:
            operator = "changed"
        return CompiledTrigger(
            id=f"{agent_id}_trig_{index}",
            agent_id=agent_id,
            source_text=text,
            entity_id=entity_id,
            attribute="state",
            operator=operator,
            threshold=threshold,
            reaction=text,
        )

    def parse_many(self, agent_id: str, texts: list[str]) -> list[CompiledTrigger]:
        out: list[CompiledTrigger] = []
        for i, t in enumerate(texts):
            compiled = self.parse(agent_id, t, i)
            if compiled is not None:
                out.append(compiled)
        return out
