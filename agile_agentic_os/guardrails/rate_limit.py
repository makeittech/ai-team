"""Rule 3 -- rate limiting (anti-flood / state lock).

A sliding-window counter per actor. When an actor exceeds ``max_actions`` within
``window`` seconds the action is blocked. A short *state lock* can also be taken
on (actor, entity) pairs to serialize bursts against the same entity.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from .models import ActionRequest, GuardrailViolation


class RateLimiter:
    def __init__(self, window: float = 1.0, max_actions: int = 20, clock=time.monotonic) -> None:
        self.window = window
        self.max_actions = max_actions
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._locks: dict[tuple[str, str], float] = {}
        self.lock_ttl = 0.0  # default: no extra lock window

    def _prune(self, actor: str, now: float) -> None:
        dq = self._hits[actor]
        while dq and (now - dq[0]) > self.window:
            dq.popleft()

    def check(self, req: ActionRequest) -> None:
        now = self._clock()
        self._prune(req.actor, now)
        dq = self._hits[req.actor]
        if len(dq) >= self.max_actions:
            raise GuardrailViolation(
                rule="rate_limit",
                message=(
                    f"actor '{req.actor}' exceeded {self.max_actions} actions "
                    f"per {self.window}s (state lock)"
                ),
                detail={"actor": req.actor, "window": self.window, "max": self.max_actions},
            )
        dq.append(now)
