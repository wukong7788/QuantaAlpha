#!/bin/bash
# Minimal smoke run for QuantaAlpha.
# - Uses lightweight config (configs/experiment_smoke.yaml)
# - Runs only first 3 workflow steps (up to factor_calculate)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

send_telegram() {
  local text="$1"
  local bot_token="${TG_BOT_TOKEN:-}"
  local chat_id="${TG_CHAT_ID:-}"

  # Fallback to ~/.zshrc exports when variables are not in current shell.
  if [ -z "${bot_token}" ] && [ -f "${HOME}/.zshrc" ]; then
    bot_token="$(sed -n 's/^export TG_BOT_TOKEN="\([^"]*\)"/\1/p' "${HOME}/.zshrc" | tail -n 1)"
  fi
  if [ -z "${chat_id}" ] && [ -f "${HOME}/.zshrc" ]; then
    chat_id="$(sed -n 's/^export TG_CHAT_ID="\([^"]*\)"/\1/p' "${HOME}/.zshrc" | tail -n 1)"
  fi

  if [ -n "${bot_token}" ] && [ -n "${chat_id}" ]; then
    curl -sS -X POST "https://api.telegram.org/bot${bot_token}/sendMessage" \
      -d "chat_id=${chat_id}" \
      --data-urlencode "text=${text}" >/dev/null || true
  fi
}

if [ ! -f ".env" ]; then
  echo "Error: .env not found in project root."
  echo "Please prepare it first (cp configs/.env.example .env and edit)."
  exit 1
fi

set -a
source ".env"
set +a

if [ ! -x ".venv/bin/python" ] || [ ! -x ".venv/bin/quantaalpha" ]; then
  echo "Error: .venv is not ready."
  echo "Please run: uv venv --python 3.12 .venv && uv pip install -e ."
  exit 1
fi

if [ ! -d "${QLIB_DATA_DIR:-}" ]; then
  echo "Error: QLIB_DATA_DIR is missing or invalid: ${QLIB_DATA_DIR:-<empty>}"
  exit 1
fi

MAIN_DATA_DIR="${FACTOR_CoSTEER_DATA_FOLDER:-}"
DEBUG_DATA_DIR="${FACTOR_CoSTEER_DATA_FOLDER_DEBUG:-}"
if [ -z "${MAIN_DATA_DIR}" ] || [ ! -f "${MAIN_DATA_DIR}/daily_pv.h5" ]; then
  echo "Error: main factor data not found: ${MAIN_DATA_DIR}/daily_pv.h5"
  exit 1
fi
if [ -z "${DEBUG_DATA_DIR}" ] || [ ! -f "${DEBUG_DATA_DIR}/daily_pv.h5" ]; then
  echo "Error: debug factor data not found: ${DEBUG_DATA_DIR}/daily_pv.h5"
  exit 1
fi

DIRECTION="${1:-价量因子挖掘}"
STEP_N_VALUE="${STEP_N:-3}"
CONFIG_FILE="${CONFIG_PATH:-configs/experiment_smoke.yaml}"

echo "Mini smoke run"
echo "Direction: ${DIRECTION}"
echo "Config: ${CONFIG_FILE}"
echo "STEP_N: ${STEP_N_VALUE}"
echo "Qlib: ${QLIB_DATA_DIR}"
echo "Main h5: ${MAIN_DATA_DIR}/daily_pv.h5"
echo "Debug h5: ${DEBUG_DATA_DIR}/daily_pv.h5"
echo "----------------------------------------"

START_TS="$(date +%s)"
set +e
CONFIG_PATH="${CONFIG_FILE}" STEP_N="${STEP_N_VALUE}" bash ./run.sh "${DIRECTION}"
RC=$?
set -e
END_TS="$(date +%s || true)"
if [ -z "${END_TS:-}" ]; then
  END_TS="${START_TS}"
fi
DURATION="$(( ${END_TS:-0} - ${START_TS:-0} ))"

if [ "${RC}" -eq 0 ]; then
  send_telegram "✅ QuantaAlpha minirun finished
dir: ${DIRECTION}
step_n: ${STEP_N_VALUE}
time: ${DURATION}s"
else
  send_telegram "❌ QuantaAlpha minirun failed
dir: ${DIRECTION}
step_n: ${STEP_N_VALUE}
code: ${RC}
time: ${DURATION}s"
fi

exit "${RC}"
