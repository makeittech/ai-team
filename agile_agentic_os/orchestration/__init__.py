"""Stage 5 -- Role orchestration: proactive life, A2A comms, orchestrator."""

from .proactive import ProactiveTriggerEngine
from .a2a import AgentToAgentRouter
from .triggers import TriggerParser
from .orchestrator import Orchestrator

__all__ = [
    "ProactiveTriggerEngine",
    "AgentToAgentRouter",
    "TriggerParser",
    "Orchestrator",
]
