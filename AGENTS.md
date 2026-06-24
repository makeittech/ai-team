# AGENTS.md

## Cursor Cloud specific instructions

Agile Agentic OS is a **pure-Python library / CLI** (package `agile_agentic_os`,
Python 3.12 here, requires >=3.10). There is **no GUI or web frontend**, so
demonstrate behavior with `pytest` and small Python driver scripts, not a browser.

### Environment notes (already handled by the startup update script)
- Dependencies are installed into the **user site** (`pip install --user
  --break-system-packages`) rather than a virtualenv, because the base image does
  **not** ship `python3-venv`. Use `python3 -m pytest` / `python3 -m pip`; the
  `~/.local/bin` scripts (incl. the `agile-os` console script) are not on `PATH`.
- The canonical dev/test install is the **core + dev** set:
  `pip install -e ".[dev]"` → `pydantic`, `numpy`, `pytest`, `pytest-asyncio`,
  `rich`. This alone makes the **entire** suite pass. Optional extras
  (`server`, `redis`, `vector`, `llm`, `tui`, `channels`/`telegram`/`discord`)
  live in `requirements.txt`/`pyproject.toml` and are auto-detected at runtime;
  the channel/onboarding tests use graceful fallbacks, so those libs are not
  required for tests.
- The repo also ships `scripts/setup_env.sh`, which installs the **full**
  `requirements.txt` (heavy: `chromadb`, `litellm`, channel libs) plus the
  `opencode` CLI via npm. Use it only if you need those optional integrations;
  the lean `.[dev]` install above is preferred for the default dev loop.

### Test / lint / run
- Tests: `python3 -m pytest -q` (suite is the project's Definition-of-Done).
- No linter/formatter is configured; a syntax sanity check is
  `python3 -m compileall agile_agentic_os tests`.
- Run via the CLI: `python3 -m agile_agentic_os <cmd>` (or `agile-os <cmd>` if
  `~/.local/bin` is on PATH). Subcommands: `export-opencode <lore> <out_dir>`,
  `serve` (daemon + chat channels; loops forever), `onboard` (TUI), `mcp`.
  Hello-world: `python3 -m agile_agentic_os export-opencode "Smart Home" /tmp/space`.

### Non-obvious gotchas
- **LiteLLM is opt-in.** Live provider routing in
  `agile_agentic_os/routing/llm_router.py` only activates when
  `AAOS_USE_LITELLM` is set (and `litellm` is installed); otherwise an offline
  mock backend is used, so the suite stays green with no API keys. Set
  `AAOS_USE_LITELLM` **and** `ANTHROPIC_API_KEY` only if you intentionally want
  real LLM calls.
- `tests/test_stage6_opencode_backend.py` contains 1 test that **skips** unless
  the external `opencode` CLI binary is installed; this is expected.
