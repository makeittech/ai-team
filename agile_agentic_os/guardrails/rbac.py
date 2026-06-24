"""Rule 1 -- Role Based Access Control.

Checks whether ``Agent_A`` is permitted to change the state of ``Entity_B``.
"""

from __future__ import annotations

from .models import ActionRequest, GuardrailViolation, Permission


class RBAC:
    def __init__(self) -> None:
        self._grants: dict[str, list[Permission]] = {}

    def grant(self, actor: str, permission: Permission) -> None:
        self._grants.setdefault(actor, []).append(permission)

    def grant_many(self, actor: str, permissions: list[Permission]) -> None:
        for p in permissions:
            self.grant(actor, p)

    def set_actor(self, actor: str, permissions: list[Permission]) -> None:
        """Replace an actor's permission set (used on hot-reload)."""
        self._grants[actor] = list(permissions)

    def remove_actor(self, actor: str) -> None:
        self._grants.pop(actor, None)

    def is_allowed(self, req: ActionRequest) -> bool:
        for perm in self._grants.get(req.actor, []):
            if perm.allows(req.entity_id, req.action_type):
                return True
        return False

    def check(self, req: ActionRequest) -> None:
        if not self.is_allowed(req):
            raise GuardrailViolation(
                rule="rbac",
                message=(
                    f"actor '{req.actor}' is not permitted to perform "
                    f"'{req.action_type}' on '{req.entity_id}'"
                ),
                detail={"actor": req.actor, "entity_id": req.entity_id, "action_type": req.action_type},
            )
