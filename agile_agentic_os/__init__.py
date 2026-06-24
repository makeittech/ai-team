"""Agile Agentic OS.

A continuous (infinite-session) multi-agent operating system inspired by the
``opencode`` philosophy. It splits work into a *Fast Track* (deterministic,
LLM-free command execution) and a *Slow Track* (generative, reflective agent
behaviour), connects to the physical and software world through a Universal I/O
Bridge exposed via the Model Context Protocol (MCP), and enforces strict
backend Guardrails (RBAC, payload limits, rate limiting).

The package is organised by the five engineering stages of the specification:

* :mod:`agile_agentic_os.core`          -- Stage 1: infinite session & memory
* :mod:`agile_agentic_os.bridge`        -- Stage 2: I/O bridge & MCP
* :mod:`agile_agentic_os.guardrails`    -- Stage 3: guardrails
* :mod:`agile_agentic_os.routing`       -- Stage 3/5: dual-track & LLM routing
* :mod:`agile_agentic_os.meta`          -- Stage 4: meta-agent / onboarding
* :mod:`agile_agentic_os.orchestration` -- Stage 5: role orchestration
"""

from .config import Settings, get_settings

__all__ = ["Settings", "get_settings", "__version__"]

__version__ = "0.1.0"
