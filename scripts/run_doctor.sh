#!/usr/bin/env bash
set -euo pipefail

# Terminal entry: one-shot markdown report (progress + doctor diagnostics).
# - default: adds --doctor --markdown
# - if --json is given: keeps json output
# - if --markdown is given explicitly: respects it

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_SCRIPT="${PROJECT_ROOT}/scripts/run_doctor.py"

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

cd "${PROJECT_ROOT}"

if [[ "$#" -eq 0 ]]; then
  exec "${PYTHON_BIN}" "${PY_SCRIPT}" --doctor --markdown
fi

has_doctor_flag=0
has_markdown_flag=0
has_json_flag=0
for arg in "$@"; do
  if [[ "${arg}" == "--doctor" ]]; then
    has_doctor_flag=1
  fi
  if [[ "${arg}" == "--markdown" ]]; then
    has_markdown_flag=1
  fi
  if [[ "${arg}" == "--json" ]]; then
    has_json_flag=1
  fi
done

args=("$@")
if [[ "${has_doctor_flag}" -eq 0 ]]; then
  args=(--doctor "${args[@]}")
fi

if [[ "${has_markdown_flag}" -eq 0 && "${has_json_flag}" -eq 0 ]]; then
  args=(--markdown "${args[@]}")
fi

exec "${PYTHON_BIN}" "${PY_SCRIPT}" "${args[@]}"
