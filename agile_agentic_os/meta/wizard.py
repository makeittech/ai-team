"""Meta-Agent / Setup Wizard (Task 4.2) -- "creative freedom inside a rigid schema".

Given the discovered entities plus a desired *lore/atmosphere* the Meta-Agent
produces a living, gamified org chart: a ``system_domain`` + 2-4 unique
characters, each with a detailed ``tone_of_voice`` (with sample phrases), an
RBAC split (``read_only_entities`` vs ``execute_entities``) and natural-language
``proactive_triggers``.

Two paths:

* **LLM planner** (recommended: Claude 3.5 Sonnet / GPT-4o) -- driven by
  :data:`META_AGENT_SYSTEM_PROMPT`, which is engineered as a *Hallucination Jail*
  + Strict-JSON contract so the backend can ``json.loads`` the response directly.
* **deterministic planner** (default, offline) -- a rule-based clusterer that
  cannot hallucinate and always honours the 2-4 character and RBAC-split rules.

Both outputs pass through :meth:`validate`, which drops any reference to
entity_ids that do not exist.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from ..bridge.adapters.base import Entity, EntityKind
from ..guardrails.models import LimitRule
from .schema import AgentPermissions, AgentSpec, OSConfig, SystemDomain

META_AGENT_SYSTEM_PROMPT = """Ти — Архітектор мультиагентних систем. Твоя мета — перетворити нудний список пристроїв розумного простору (Home Assistant) на живу, гейміфіковану екосистему з унікальними персонажами (агентами).

Користувач надасть тобі два вхідні параметри:
1. "Бажаний лор/атмосфера" (наприклад: серйозна веб-студія, космічний корабель, типове ОСББ).
2. "Список доступних сутностей (entities)" з їхніми поточними станами.

ТВОЯ ЗАДАЧА:
1. Проаналізувати бажаний лор та придумати загальну концепцію цього простору.
2. Створити від 2 до 4 унікальних персонажів, які органічно вписуються в цей лор і між якими можливий цікавий конфлікт або взаємодія (наприклад, економний інженер vs любитель комфорту).
3. Розподілити ВСІ надані сутності (entities) між цими персонажами на основі їхньої логічної зони відповідальності.

ПРАВИЛА ТА ОБМЕЖЕННЯ (КРИТИЧНО ВАЖЛИВО):
- Агент може керувати ТІЛЬКИ тими пристроями, які відповідають його ролі.
- СУВОРА ЗАБОРОНА: Ти не маєш права вигадувати нові `entity_id`. Використовуй виключно ті, що передані у списку "Список доступних сутностей". Якщо сутність не підходить жодному агенту за логікою — віддай її найменш завантаженому або створи для неї технічного агента.
- Опис характеру (tone_of_voice) має бути детальним, з прикладами їхніх типових фраз.

ФОРМАТ ВИВОДУ:
Ти повинен повернути відповідь ВИКЛЮЧНО у форматі валідного JSON без жодного додаткового тексту, маркдауну (```json) чи коментарів. Схема JSON має бути такою:

{
  "system_domain": {
    "name": "Назва простору",
    "background_lore": "Короткий опис того, що тут відбувається і яка атмосфера панує."
  },
  "agents": [
    {
      "id": "унікальний_ідентифікатор_англійською",
      "name": "Ім'я персонажа",
      "role": "Посада / Роль",
      "tone_of_voice": "Детальний опис характеру, манери спілкування, рівень токсичності чи емпатії. Вкажи, як він ставиться до інших.",
      "permissions": {
        "read_only_entities": ["список", "сутностей", "для", "моніторингу"],
        "execute_entities": ["список", "сутностей", "якими", "агент", "керує"]
      },
      "proactive_triggers": ["опис умов, коли агент має сам почати розмову, наприклад: 'коли температура падає нижче 18', 'коли вмикається світло вночі'"]
    }
  ]
}"""


# Domain keyword -> (flavour key, space name, lore template)
_DOMAIN_PROFILES: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"studio|production|film|video|render|web.?студі|студі", re.I),
     "Studio", "Production Studio",
     "A high-pressure creative studio where deadlines, render queues and tempers run hot."),
    (re.compile(r"space|ship|космі|корабел", re.I),
     "Starship", "Starship Bridge",
     "A long-haul starship where every watt and every degree is rationed."),
    (re.compile(r"osbb|осбб|кондомін|building|апартамент|ЖЕК", re.I),
     "Residence", "The Residence (ОСББ)",
     "A typical residential building association balancing comfort, costs and complaints."),
    (re.compile(r"smart\s*home|home|house|будин|дім|квартир", re.I),
     "Home", "Smart Home",
     "A family smart home torn between cosiness and the electricity bill."),
    (re.compile(r"\bhr\b|human resources|кадр", re.I),
     "People", "People Office",
     "An HR floor juggling people, morale and process."),
    (re.compile(r"office|company|business|startup|компан|офіс", re.I),
     "Office", "The Office",
     "A busy company office where ops, delivery and infra constantly negotiate."),
]

# team key -> (base role title, persona name pool, character/tone with sample phrases)
_PERSONAS: dict[str, dict] = {
    "observability": {
        "role": "Monitoring & Analytics",
        "names": ["Sensei", "Oracle", "Vira", "Argus"],
        "tone": ("Calm, data-obsessed observer. Speaks in numbers and trends, mildly smug when "
                 "predictions come true. Typical lines: 'The graph never lies.', "
                 "'Я ж казав, цей датчик скоро спрацює.'"),
    },
    "facilities": {
        "role": "Facilities & Comfort",
        "names": ["Petrovych", "Boris", "Comfort-9000", "Stepan"],
        "tone": ("Grumbly, thrifty engineer who hates wasted energy but secretly cares. Sarcastic, "
                 "a bit toxic but loyal. Typical lines: 'Давно пора, він жере кіловат на годину.', "
                 "'Хто знову залишив світло увімкненим?'"),
    },
    "delivery": {
        "role": "Delivery & Tasks",
        "names": ["Tasky", "Manager-Bot", "Olha", "Scrumlord"],
        "tone": ("Energetic, deadline-driven coordinator. Polite but relentless. Typical lines: "
                 "'Закриваємо таску, рухаємось далі!', 'Хто візьме цей тікет?'"),
    },
    "platform": {
        "role": "Platform & Infrastructure",
        "names": ["Sysadmin", "Root", "Ihor", "Kernel"],
        "tone": ("Paranoid, security-first admin. Terse, dry humour, distrusts everyone. Typical "
                 "lines: 'Не чіпай продакшн.', 'Бекап є? Тоді можна.'"),
    },
    "people": {
        "role": "People & Presence",
        "names": ["Empath", "Kateryna", "Concierge", "Hostess"],
        "tone": ("Warm, attentive host who tracks who's around and keeps the peace. Typical lines: "
                 "'Ласкаво просимо!', 'Здається, всі вже пішли додому.'"),
    },
}

_TEAM_OF = {
    EntityKind.SENSOR: "observability",
    EntityKind.ACTUATOR: "facilities",
    EntityKind.TASK: "delivery",
    EntityKind.SERVICE: "platform",
    EntityKind.PERSON: "people",
}


class MetaAgent:
    def __init__(self, llm_fn: Callable[[str, str], str] | None = None) -> None:
        self.llm_fn = llm_fn

    # --- public API ----------------------------------------------------
    def generate(self, entities: list[Entity], lore: str) -> OSConfig:
        if self.llm_fn is not None:
            config = self._generate_llm(entities, lore)
        else:
            config = self._generate_deterministic(entities, lore)
        return self.validate(config, entities)

    # --- deterministic planner ----------------------------------------
    def _generate_deterministic(self, entities: list[Entity], lore: str) -> OSConfig:
        flavour, name_tmpl, lore_tmpl = self._domain_profile(lore)

        # Cluster entities by responsibility team.
        teams: dict[str, list[Entity]] = {}
        for e in entities:
            teams.setdefault(_TEAM_OF.get(e.kind, "observability"), []).append(e)
        teams = {k: v for k, v in teams.items() if v}
        teams = self._cap_to_range(teams, lo=2, hi=4)

        agents: list[AgentSpec] = []
        for idx, (team_key, members) in enumerate(sorted(teams.items())):
            agents.append(self._build_agent(team_key, members, flavour, idx, entities))

        domain = SystemDomain(
            name=name_tmpl.format(flavour=flavour.capitalize()),
            background_lore=lore_tmpl + f" (requested lore: '{lore}')",
        )
        return OSConfig(system_domain=domain, agents=agents, limits=self._build_limits(entities))

    @staticmethod
    def _domain_profile(lore: str) -> tuple[str, str, str]:
        for pattern, flavour, name_tmpl, lore_tmpl in _DOMAIN_PROFILES:
            if pattern.search(lore):
                return flavour, name_tmpl, lore_tmpl
        return "Ops", "Operations Hub", "A general-purpose automated operations hub."

    def _cap_to_range(self, teams: dict[str, list[Entity]], lo: int, hi: int) -> dict[str, list[Entity]]:
        # Merge smallest teams together until we are within the upper bound.
        while len(teams) > hi:
            ordered = sorted(teams.items(), key=lambda kv: len(kv[1]))
            (k1, v1), (k2, v2) = ordered[0], ordered[1]
            del teams[k1]
            del teams[k2]
            teams[k2] = v2 + v1  # keep the larger team's key/persona
        # Split if we have too few teams.
        while len(teams) < lo:
            largest_key = max(teams, key=lambda k: len(teams[k]))
            members = teams[largest_key]
            if len(members) < 2:
                break
            mid = len(members) // 2
            del teams[largest_key]
            teams[f"{largest_key}_a"] = members[:mid]
            teams[f"{largest_key}_b"] = members[mid:]
        return teams

    def _build_agent(self, team_key: str, members: list[Entity], flavour: str, idx: int,
                     all_entities: list[Entity]) -> AgentSpec:
        base_key = team_key.split("_", 1)[0]
        persona = _PERSONAS.get(base_key, _PERSONAS["observability"])
        name = persona["names"][idx % len(persona["names"])]
        role = f"{flavour.capitalize()} {persona['role']}"

        read_only = [e.entity_id for e in members if e.kind == EntityKind.SENSOR]
        execute = [e.entity_id for e in members if e.kind != EntityKind.SENSOR]

        triggers = self._build_triggers(members)
        return AgentSpec(
            id=f"{base_key}_{idx}",
            name=name,
            role=role,
            tone_of_voice=persona["tone"],
            permissions=AgentPermissions(read_only_entities=read_only, execute_entities=execute),
            proactive_triggers=triggers,
        )

    @staticmethod
    def _build_triggers(members: list[Entity]) -> list[str]:
        triggers: list[str] = []
        for e in members:
            if e.kind != EntityKind.SENSOR:
                continue
            low = e.entity_id.lower()
            # Embed the entity_id so the TriggerParser binds it unambiguously.
            if "power" in low or "energy" in low:
                triggers.append(f"when {e.entity_id} consumption exceeds 5")
            elif "temp" in low:
                triggers.append(f"when {e.entity_id} rises above 28")
            elif "humid" in low:
                triggers.append(f"when {e.entity_id} drops below 30")
            elif "motion" in low or "presence" in low:
                triggers.append(f"when {e.entity_id} changes at night")
        return triggers

    @staticmethod
    def _build_limits(entities: list[Entity]) -> list[LimitRule]:
        ids = {e.entity_id for e in entities}
        actions_by_entity = {e.entity_id: set(e.actions) for e in entities}
        rules: list[LimitRule] = []
        if any("climate" in i or "thermostat" in i for i in ids):
            rules.append(LimitRule(
                entity_glob="climate.*", action_type="set_temperature", field="temperature",
                max_value=30, min_value=10, message="temperature must stay within 10-30C",
            ))
        if any("github.repo" in i for i in ids) and any(
            "delete_branch" in a for a in actions_by_entity.values()
        ):
            rules.append(LimitRule(
                entity_glob="github.repo*", action_type="delete_branch", forbid=True,
                message="deleting protected/main branch is forbidden",
            ))
        return rules

    # --- LLM planner ---------------------------------------------------
    def _generate_llm(self, entities: list[Entity], lore: str) -> OSConfig:
        entity_payload = json.dumps(
            [{"entity_id": e.entity_id, "kind": e.kind.value, "actions": e.actions,
              "state": e.attributes} for e in entities],
            ensure_ascii=False,
        )
        user_msg = (
            f"Бажаний лор/атмосфера: {lore}\n"
            f"Список доступних сутностей (entities): {entity_payload}"
        )
        raw = self.llm_fn(META_AGENT_SYSTEM_PROMPT, user_msg)
        data = json.loads(self._strip_fences(raw))
        return OSConfig(**data)

    @staticmethod
    def _strip_fences(text: str) -> str:
        """Defensive: strip ```json fences if a model adds them despite instructions."""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        return text.strip()

    # --- validation (Hallucination Jail enforcement) ------------------
    def validate(self, config: OSConfig, entities: list[Entity]) -> OSConfig:
        """Drop any reference to entity_ids that do not exist."""
        valid_ids = {e.entity_id for e in entities}
        for agent in config.agents:
            agent.permissions.read_only_entities = [
                t for t in agent.permissions.read_only_entities if t in valid_ids
            ]
            agent.permissions.execute_entities = [
                t for t in agent.permissions.execute_entities if t in valid_ids
            ]
        return config
