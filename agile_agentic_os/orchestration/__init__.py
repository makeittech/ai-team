"""Stage 5 -- Role orchestration: proactive life, A2A comms, orchestrator."""

from .proactive import ProactiveTriggerEngine
from .a2a import AgentToAgentRouter
from .orchestrator import Orchestrator

__all__ = ["ProactiveTriggerEngine", "AgentToAgentRouter", "Orchestrator"]
