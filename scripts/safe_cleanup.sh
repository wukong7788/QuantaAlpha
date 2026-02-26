#!/usr/bin/env bash
set -euo pipefail

# Shell entry for safe cleanup.
# - No args: launch interactive wizard.
# - With args: pass through to safe_cleanup.py.

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_SCRIPT="${PROJECT_ROOT}/scripts/safe_cleanup.py"

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
  ./scripts/safe_cleanup.sh
  ./scripts/safe_cleanup.sh --interactive
  ./scripts/safe_cleanup.sh --clean-logs --apply --yes
  ./scripts/safe_cleanup.sh --prune-factor-cache --apply --yes
  ./scripts/safe_cleanup.sh --clean-minirun-temp --apply --yes
  ./scripts/safe_cleanup.sh --clean-minirun-temp --minirun-tag minirun_20260225_180000 --apply --yes

Notes:
  - This is a shell wrapper around scripts/safe_cleanup.py.
  - No arguments => starts interactive wizard.
  - With arguments => forwarded to safe_cleanup.py unchanged.
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  echo
  "${PYTHON_BIN}" "${PY_SCRIPT}" --help
  exit 0
fi

cd "${PROJECT_ROOT}"

if [[ "$#" -eq 0 ]]; then
  if [[ -t 0 && -t 1 ]]; then
    exec "${PYTHON_BIN}" "${PY_SCRIPT}" --interactive
  fi
  exec "${PYTHON_BIN}" "${PY_SCRIPT}"
fi

exec "${PYTHON_BIN}" "${PY_SCRIPT}" "$@"
