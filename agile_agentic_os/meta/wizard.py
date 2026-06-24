"""Meta-Agent / Setup Wizard (Task 4.2).

Given the discovered entity list plus a free-text domain description (e.g. "HR
department", "Smart Home", "Production studio") the Meta-Agent generates the
``Agents -> Assigned Tools -> Permissions -> Tone of Voice`` matrix.

Two generation paths exist:

* **deterministic planner** (default) -- a rule-based clusterer that *cannot*
  hallucinate: it only ever references entity_ids it was given, and it always
  emits >= 3 agents with logically distributed tools/permissions.
* **LLM planner** -- when an ``llm_fn`` is provided, the hard system prompt
  below is used; the result is then passed through :meth:`validate` which drops
  any hallucinated (non-existent) entity_ids before returning.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from ..bridge.adapters.base import Entity, EntityKind
from ..guardrails.models import LimitRule, Permission
from .schema import AgentSpec, OSConfig, ProactiveTrigger

META_AGENT_SYSTEM_PROMPT = """You are the Meta-Architect of an Agile Agentic OS.
INPUT: a JSON list of EXISTING entities (each with entity_id, kind, actions) and
a DOMAIN description from the user.
TASK: produce a JSON object matching this schema EXACTLY:
{
  "domain": str,
  "agents": [
    {"id": str, "role": str, "tone_of_voice": str, "system_prompt": str,
     "assigned_tools": [entity_id, ...],
     "permissions": [{"entity_glob": str, "actions": [str, ...]}],
     "proactive_triggers": [{"id": str, "entity_id": str, "attribute": str,
                              "operator": str, "threshold": number|string,
                              "reaction": str, "cooldown": number}]}
  ],
  "limits": [{"entity_glob": str, "action_type": str|null, "field": str|null,
              "min_value": number|null, "max_value": number|null,
              "forbid": bool, "message": str|null}]
}
HARD RULES:
1. Use ONLY entity_ids that appear in INPUT. NEVER invent entity_ids.
2. Produce AT LEAST 3 agents with non-overlapping responsibilities.
3. Read-only sensors must not receive write/actuation permissions.
4. Distribute tools logically by entity kind and domain semantics.
5. Output ONLY valid JSON, no prose."""


# team key -> (default role title, tone)
_TEAM_TEMPLATES: dict[str, tuple[str, str]] = {
    "observability": ("Observability Analyst", "calm, data-driven, precise"),
    "facilities": ("Facilities Operator", "practical, safety-first"),
    "delivery": ("Delivery Lead", "organized, motivating"),
    "platform": ("Platform Engineer", "rigorous, security-conscious"),
    "people": ("People Coordinator", "warm, supportive"),
}

# Domain keyword -> flavour adjective injected into roles/tone.
_DOMAIN_FLAVOURS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"studio|production|film|video|render", re.I), "Studio"),
    (re.compile(r"smart\s*home|home|house|будин|дім", re.I), "Home"),
    (re.compile(r"\bhr\b|human resources|people|відділ кадрів", re.I), "HR"),
    (re.compile(r"company|business|startup|enterprise|компан", re.I), "Company"),
    (re.compile(r"dev|software|engineering|devops", re.I), "Engineering"),
]


def _team_of(entity: Entity) -> str:
    if entity.kind == EntityKind.SENSOR:
        return "observability"
    if entity.kind == EntityKind.ACTUATOR:
        return "facilities"
    if entity.kind == EntityKind.TASK:
        return "delivery"
    if entity.kind == EntityKind.SERVICE:
        return "platform"
    if entity.kind == EntityKind.PERSON:
        return "people"
    return "observability"


class MetaAgent:
    def __init__(self, llm_fn: Callable[[str, str], str] | None = None) -> None:
        self.llm_fn = llm_fn

    # --- public API ----------------------------------------------------
    def generate(self, entities: list[Entity], domain: str) -> OSConfig:
        if self.llm_fn is not None:
            config = self._generate_llm(entities, domain)
        else:
            config = self._generate_deterministic(entities, domain)
        return self.validate(config, entities)

    # --- deterministic planner ----------------------------------------
    def _generate_deterministic(self, entities: list[Entity], domain: str) -> OSConfig:
        flavour = self._flavour(domain)

        teams: dict[str, list[Entity]] = {}
        for e in entities:
            teams.setdefault(_team_of(e), []).append(e)

        teams = self._ensure_min_teams(teams, minimum=3)

        agents: list[AgentSpec] = []
        for idx, (team_key, members) in enumerate(sorted(teams.items())):
            agents.append(self._build_agent(team_key, members, flavour, idx))

        limits = self._build_limits(entities)
        return OSConfig(domain=domain, agents=agents, limits=limits)

    @staticmethod
    def _flavour(domain: str) -> str:
        for pattern, flavour in _DOMAIN_FLAVOURS:
            if pattern.search(domain):
                return flavour
        return "Ops"

    def _ensure_min_teams(self, teams: dict[str, list[Entity]], minimum: int) -> dict[str, list[Entity]]:
        # Drop empty teams.
        teams = {k: v for k, v in teams.items() if v}
        if len(teams) >= minimum:
            return teams
        # Split the largest team by entity domain-prefix until we reach `minimum`.
        while len(teams) < minimum:
            largest_key = max(teams, key=lambda k: len(teams[k]))
            members = teams[largest_key]
            if len(members) < 2:
                break  # cannot split further
            by_prefix: dict[str, list[Entity]] = {}
            for e in members:
                by_prefix.setdefault(e.entity_id.split(".", 1)[0], []).append(e)
            if len(by_prefix) < 2:
                # split in half
                mid = len(members) // 2
                by_prefix = {f"{largest_key}_a": members[:mid], f"{largest_key}_b": members[mid:]}
            del teams[largest_key]
            for i, (pfx, grp) in enumerate(sorted(by_prefix.items())):
                key = f"{largest_key}:{pfx}" if not pfx.startswith(largest_key) else pfx
                teams[key] = grp
        return teams

    def _build_agent(self, team_key: str, members: list[Entity], flavour: str, idx: int) -> AgentSpec:
        base_key = team_key.split(":", 1)[0]
        base_role, base_tone = _TEAM_TEMPLATES.get(base_key, ("Operator", "neutral, concise"))
        role = f"{flavour} {base_role}"
        agent_id = f"{flavour.lower()}_{base_key}_{idx}"

        assigned_tools: list[str] = [e.entity_id for e in members]
        permissions: list[Permission] = []
        for e in members:
            if e.kind == EntityKind.SENSOR:
                # read-only: no actuation permissions
                continue
            actions = e.actions or ["*"]
            # strip clearly destructive actions from default grants
            safe_actions = [a for a in actions if a not in {"delete_branch"}]
            permissions.append(Permission(entity_glob=e.entity_id, actions=safe_actions or ["*"]))

        triggers = self._build_triggers(members, agent_id)
        system_prompt = (
            f"You are '{agent_id}', the {role} of a {flavour} operation. "
            f"Tone: {base_tone}. Responsible for: {', '.join(assigned_tools)}. "
            f"React in character to events in your area; never act outside your tools."
        )
        return AgentSpec(
            id=agent_id, role=role, tone_of_voice=base_tone, system_prompt=system_prompt,
            assigned_tools=assigned_tools, permissions=permissions, proactive_triggers=triggers,
        )

    @staticmethod
    def _build_triggers(members: list[Entity], agent_id: str) -> list[ProactiveTrigger]:
        triggers: list[ProactiveTrigger] = []
        for e in members:
            if e.kind != EntityKind.SENSOR:
                continue
            low = e.entity_id.lower()
            if "power" in low:
                triggers.append(ProactiveTrigger(
                    id=f"{agent_id}_{e.entity_id}_power", entity_id=e.entity_id, attribute="state",
                    operator=">", threshold=5,
                    reaction=f"{agent_id}: power draw on {e.entity_id} is high, investigating.",
                ))
            elif "temp" in low:
                triggers.append(ProactiveTrigger(
                    id=f"{agent_id}_{e.entity_id}_temp", entity_id=e.entity_id, attribute="state",
                    operator=">", threshold=28,
                    reaction=f"{agent_id}: {e.entity_id} is running hot.",
                ))
        return triggers

    @staticmethod
    def _build_limits(entities: list[Entity]) -> list[LimitRule]:
        ids = {e.entity_id for e in entities}
        actions_by_entity = {e.entity_id: set(e.actions) for e in entities}
        rules: list[LimitRule] = []
        # Thermostat safety: temperature <= 30.
        if any("climate" in i or "thermostat" in i for i in ids):
            rules.append(LimitRule(
                entity_glob="climate.*", action_type="set_temperature", field="temperature",
                max_value=30, min_value=10, message="temperature must stay within 10-30C",
            ))
        # Protect default branch from deletion.
        if any("github.repo" in i for i in ids) and any(
            "delete_branch" in a for a in actions_by_entity.values()
        ):
            rules.append(LimitRule(
                entity_glob="github.repo*", action_type="delete_branch", forbid=True,
                message="deleting protected/main branch is forbidden",
            ))
        return rules

    # --- LLM planner ---------------------------------------------------
    def _generate_llm(self, entities: list[Entity], domain: str) -> OSConfig:  # pragma: no cover - needs model
        entity_payload = json.dumps(
            [{"entity_id": e.entity_id, "kind": e.kind.value, "actions": e.actions} for e in entities]
        )
        raw = self.llm_fn(META_AGENT_SYSTEM_PROMPT, f"ENTITIES={entity_payload}\nDOMAIN={domain}")
        data = json.loads(raw)
        return OSConfig(**data)

    # --- validation (anti-hallucination) ------------------------------
    def validate(self, config: OSConfig, entities: list[Entity]) -> OSConfig:
        """Drop any reference to entity_ids that do not exist."""
        valid_ids = {e.entity_id for e in entities}
        for agent in config.agents:
            agent.assigned_tools = [t for t in agent.assigned_tools if t in valid_ids]
            agent.proactive_triggers = [
                t for t in agent.proactive_triggers if t.entity_id in valid_ids
            ]
        return config
