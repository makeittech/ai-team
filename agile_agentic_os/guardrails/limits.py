"""Rule 2 -- payload / parameter limits.

Examples enforced here:
* "temperature must not exceed 30"
* "deleting the master/main branch is forbidden"
"""

from __future__ import annotations

from .models import ActionRequest, GuardrailViolation, LimitRule


class LimitChecker:
    def __init__(self, rules: list[LimitRule] | None = None) -> None:
        self.rules: list[LimitRule] = list(rules or [])

    def add_rule(self, rule: LimitRule) -> None:
        self.rules.append(rule)

    def set_rules(self, rules: list[LimitRule]) -> None:
        self.rules = list(rules)

    def check(self, req: ActionRequest) -> None:
        for rule in self.rules:
            if not rule.applies(req.entity_id, req.action_type):
                continue
            if rule.forbid:
                raise GuardrailViolation(
                    rule="limits",
                    message=rule.message or f"action '{req.action_type}' on '{req.entity_id}' is forbidden",
                    detail={"entity_id": req.entity_id, "action_type": req.action_type},
                )
            if rule.field is not None:
                if rule.field not in req.payload:
                    continue
                value = req.payload[rule.field]
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                if rule.max_value is not None and numeric > rule.max_value:
                    raise GuardrailViolation(
                        rule="limits",
                        message=(
                            rule.message
                            or f"{rule.field}={numeric} exceeds max {rule.max_value} for {req.entity_id}"
                        ),
                        detail={"field": rule.field, "value": numeric, "max": rule.max_value},
                    )
                if rule.min_value is not None and numeric < rule.min_value:
                    raise GuardrailViolation(
                        rule="limits",
                        message=(
                            rule.message
                            or f"{rule.field}={numeric} below min {rule.min_value} for {req.entity_id}"
                        ),
                        detail={"field": rule.field, "value": numeric, "min": rule.min_value},
                    )
