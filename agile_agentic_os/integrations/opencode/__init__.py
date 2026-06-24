"""opencode backend integration.

This package makes the *opencode* AI agent engine
(https://github.com/anomalyco/opencode) the real backend of the Agile Agentic
OS, using the "context substitution" hack: instead of giving opencode a
filesystem + GitHub, we give it **physical devices + software APIs** through the
Model Context Protocol.

Pieces:

* :mod:`mcp_stdio`  -- a real MCP (JSON-RPC 2.0 over stdio) server that opencode
  launches via its ``mcp`` config. It exposes ``get_state`` / ``execute_action``
  / ``recall_memory`` backed by our I/O Bridge + Guardrails. This is what an
  opencode agent calls instead of editing files.
* :mod:`config_gen` -- turns a Meta-Agent :class:`OSConfig` into a runnable
  opencode project: an ``opencode.json`` (with the ``mcp`` + ``agent`` blocks)
  and ``.opencode/agent/*.md`` persona files, with per-agent tool gating and
  cost-aware model routing.
* :mod:`runner`     -- drives opencode headless (``opencode run --agent ...``)
  to power the Slow Track (in-character reflection) on real models.
"""

from .config_gen import OpencodeProjectGenerator
from .runner import OpencodeRunner, OpencodeSlowTrack

__all__ = ["OpencodeProjectGenerator", "OpencodeRunner", "OpencodeSlowTrack"]
