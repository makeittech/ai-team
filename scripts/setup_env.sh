#!/usr/bin/env bash
# Reproducible environment setup for the Agile Agentic OS.
#
# Installs Python dependencies (core + optional channels/TUI) and, when npm is
# available, the opencode CLI used by the integration tests. Safe to re-run.
#
# Usage: bash scripts/setup_env.sh
set -euo pipefail

echo "==> Python: $(python3 --version)"

# pip on Debian/Ubuntu cloud images is often externally-managed; allow override.
PIP_FLAGS="${PIP_FLAGS:---break-system-packages}"

echo "==> Installing Python dependencies"
python3 -m pip install --quiet --upgrade pip ${PIP_FLAGS} || true
python3 -m pip install --quiet ${PIP_FLAGS} -r requirements.txt

echo "==> Installing the package (editable)"
python3 -m pip install --quiet ${PIP_FLAGS} -e . || true

# opencode CLI (optional) — enables the live integration test.
if command -v npm >/dev/null 2>&1; then
  if ! command -v opencode >/dev/null 2>&1; then
    echo "==> Installing opencode CLI (npm)"
    npm install -g opencode-ai@latest >/dev/null 2>&1 || \
      echo "   (opencode install skipped — integration e2e test will auto-skip)"
  else
    echo "==> opencode already installed: $(opencode --version 2>/dev/null | tail -1)"
  fi
else
  echo "==> npm not found — skipping opencode CLI (integration e2e test will auto-skip)"
fi

echo "==> Verifying imports"
python3 -c "import agile_agentic_os; from agile_agentic_os.orchestration import Orchestrator; print('agile_agentic_os', agile_agentic_os.__version__, 'OK')"

echo "==> Done. Run the tests with: python3 -m pytest -q"
