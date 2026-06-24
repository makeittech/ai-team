"""Guardrail middleware combining RBAC + limits + rate limiting (Task 3.1).

This is the single backend chokepoint every action must pass through. It is
plugged into :class:`~agile_agentic_os.bridge.mcp_server.MCPServer` as its
``guardrail`` callable. On violation it raises a :class:`ToolError` carrying a
detailed reason so the agent gets a precise, actionable error in its context.
"""

from __future__ import annotations

from ..bridge.mcp_server import ToolError
from ..config import Settings, get_settings
from .limits import LimitChecker
from .models import ActionRequest, GuardrailViolation, LimitRule, Permission
from .rate_limit import RateLimiter
from .rbac import RBAC


class GuardrailMiddleware:
    def __init__(
        self,
        rbac: RBAC | None = None,
        limits: LimitChecker | None = None,
        rate_limiter: RateLimiter | None = None,
        settings: Settings | None = None,
        enforce_rbac: bool = True,
    ) -> None:
        settings = settings or get_settings()
        self.rbac = rbac or RBAC()
        self.limits = limits or LimitChecker()
        self.rate_limiter = rate_limiter or RateLimiter(
            window=settings.rate_limit_window, max_actions=settings.rate_limit_max
        )
        self.enforce_rbac = enforce_rbac
        self.blocked_count = 0
        self.allowed_count = 0

    # --- the chokepoint ------------------------------------------------
    def validate(self, actor: str, entity_id: str, action_type: str, payload: dict) -> None:
        """Run all three rules in order. Raises ToolError on the first failure."""
        req = ActionRequest(actor=actor, entity_id=entity_id, action_type=action_type, payload=payload)
        try:
            # Rate limiting first -- cheapest, and floods should never reach RBAC.
            self.rate_limiter.check(req)
            if self.enforce_rbac:
                self.rbac.check(req)
            self.limits.check(req)
        except GuardrailViolation as exc:
            self.blocked_count += 1
            raise ToolError(exc.message, detail=exc.to_detail()) from exc
        self.allowed_count += 1

    # MCPServer expects a plain callable.
    def as_guardrail(self):
        return self.validate

    # --- hot-reload helpers -------------------------------------------
    def apply_permissions(self, matrix: dict[str, list[Permission]]) -> None:
        for actor, perms in matrix.items():
            self.rbac.set_actor(actor, perms)

    def apply_limits(self, rules: list[LimitRule]) -> None:
        self.limits.set_rules(rules)
