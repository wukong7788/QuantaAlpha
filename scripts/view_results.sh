#!/usr/bin/env bash
set -euo pipefail

# Shell entry for backtest result comparison.
# - No args: interactive quick selector.
# - With args: forwarded to scripts/view_results.py.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_SCRIPT="${PROJECT_ROOT}/scripts/view_results.py"

if [[ ! -f "${PY_SCRIPT}" ]]; then
  echo "Error: ${PY_SCRIPT} not found."
  exit 1
fi

PYTHON_BIN=""
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
  PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "Error: python interpreter not found."
  exit 1
fi

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/view_results.sh
  ./scripts/view_results.sh --interactive
  ./scripts/view_results.sh --pick 1,2,3
  ./scripts/view_results.sh --result-dir data/results/backtest_v2_results --pick all

Notes:
  - Compares existing *_backtest_metrics.json files directly (no recompute).
  - Includes overwrite-risk check based on filename scheme.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  echo
  exec "${PYTHON_BIN}" "${PY_SCRIPT}" --help
fi

cd "${PROJECT_ROOT}"

if [[ "$#" -eq 0 ]]; then
  exec "${PYTHON_BIN}" "${PY_SCRIPT}" --interactive
fi

exec "${PYTHON_BIN}" "${PY_SCRIPT}" "$@"

