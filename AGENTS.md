# AGENTS.md

## Cursor Cloud specific instructions

Agile Agentic OS is a **pure-Python library / CLI** (package `agile_agentic_os`,
Python 3.12 here, requires >=3.10). There is **no GUI or web frontend**, so
demonstrate behavior with `pytest` and small Python driver scripts, not a browser.

### Environment notes (already handled by the startup update script)
- Dependencies are installed into the **user site** (`pip install --user
  --break-system-packages`) rather than a virtualenv, because the base image does
  **not** ship `python3-venv`. Use `python3 -m pytest` / `python3 -m pip`; the
  `~/.local/bin` scripts are not on `PATH`.
- The canonical dev/test install is the **core + dev** set:
  `pip install -e ".[dev]"` → `pydantic`, `numpy`, `pytest`, `pytest-asyncio`.
  Optional extras (`server`, `redis`, `vector`, `llm`) live in `requirements.txt`
  and are auto-detected at runtime when present.

### Test / lint / run
- Tests: `python3 -m pytest -q` (suite is the project's Definition-of-Done).
- No linter/formatter is configured; a syntax sanity check is
  `python3 -m compileall agile_agentic_os tests`.
- Run / hello-world: boot the orchestrator and export an opencode project — see
  the "Quick start" in `README.md`
  (`Orchestrator().boot(...)` + `export_opencode_project(...)`).

### Non-obvious gotchas
- **Installing the optional `llm` extra (`litellm`) changes test behavior.**
  `agile_agentic_os/routing/llm_router.py` auto-detects `litellm`; when it is
  installed, `LLMRouter` makes **real** provider calls instead of the offline
  mock backend, so the 4 routing tests in
  `tests/test_stage5_orchestration_routing.py` fail with an Anthropic auth error
  unless `ANTHROPIC_API_KEY` is set. The default offline setup (no `litellm`)
  keeps the whole suite green. Set `ANTHROPIC_API_KEY` only if you intentionally
  want live LLM routing.
- `tests/test_stage6_opencode_backend.py` contains 1 test that **skips** unless
  the external `opencode` CLI binary is installed; this is expected.
