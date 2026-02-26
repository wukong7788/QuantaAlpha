#!/bin/bash
# Minimal full-flow smoke run for QuantaAlpha.
# - Uses lightweight config (configs/experiment_smoke.yaml)
# - Runs one complete 5-step loop (propose/construct/calculate/backtest/feedback)
# - Tags artifacts for easy cleanup later

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

capture_log_dirs() {
  local out_file="$1"
  if [ -d "log" ]; then
    find "log" -mindepth 1 -maxdepth 1 -type d -print | sort > "${out_file}"
  else
    : > "${out_file}"
  fi
}

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
STEP_N_VALUE="${STEP_N:-5}"
CONFIG_FILE="${CONFIG_PATH:-configs/experiment_smoke.yaml}"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
MINIRUN_TAG="${MINIRUN_TAG:-minirun_${RUN_TS}}"

if [ -z "${EXPERIMENT_ID:-}" ]; then
  EXPERIMENT_ID="mini_${RUN_TS}"
fi
if [ -z "${FACTOR_LIBRARY_SUFFIX:-}" ]; then
  FACTOR_LIBRARY_SUFFIX="${MINIRUN_TAG}"
fi

if ! [[ "${STEP_N_VALUE}" =~ ^[0-9]+$ ]]; then
  echo "Error: STEP_N must be a positive integer."
  exit 1
fi
if [ "${STEP_N_VALUE}" -lt 5 ]; then
  echo "Info: STEP_N=${STEP_N_VALUE} does not cover full 5-step workflow, auto-upgrade to 5."
  STEP_N_VALUE=5
fi

RESULTS_BASE="${DATA_RESULTS_DIR:-./data/results}"
WORKSPACE_PATH="${RESULTS_BASE}/workspace_${EXPERIMENT_ID}"
PICKLE_CACHE_PATH="${RESULTS_BASE}/pickle_cache_${EXPERIMENT_ID}"
FACTORLIB_PATH="${SCRIPT_DIR}/data/factorlib/all_factors_library_${FACTOR_LIBRARY_SUFFIX}.json"
MANIFEST_DIR="${SCRIPT_DIR}/log/minirun_manifests"
mkdir -p "${MANIFEST_DIR}"
MANIFEST_FILE="${MANIFEST_DIR}/${MINIRUN_TAG}.txt"

BEFORE_LOGS="$(mktemp "/tmp/minirun_logs_before_XXXXXX")"
AFTER_LOGS="$(mktemp "/tmp/minirun_logs_after_XXXXXX")"
trap 'rm -f "${BEFORE_LOGS}" "${AFTER_LOGS}" 2>/dev/null || true' EXIT
capture_log_dirs "${BEFORE_LOGS}"

echo "Mini smoke run"
echo "Direction: ${DIRECTION}"
echo "Config: ${CONFIG_FILE}"
echo "STEP_N: ${STEP_N_VALUE}"
echo "Experiment ID: ${EXPERIMENT_ID}"
echo "Artifact Tag: ${MINIRUN_TAG}"
echo "Factor Library Suffix: ${FACTOR_LIBRARY_SUFFIX}"
echo "Qlib: ${QLIB_DATA_DIR}"
echo "Main h5: ${MAIN_DATA_DIR}/daily_pv.h5"
echo "Debug h5: ${DEBUG_DATA_DIR}/daily_pv.h5"
echo "----------------------------------------"

START_TS="$(date +%s)"
set +e
CONFIG_PATH="${CONFIG_FILE}" STEP_N="${STEP_N_VALUE}" EXPERIMENT_ID="${EXPERIMENT_ID}" FACTOR_LIBRARY_SUFFIX="${FACTOR_LIBRARY_SUFFIX}" bash ./run.sh "${DIRECTION}"
RC=$?
set -e
END_TS="$(date +%s || true)"
if [ -z "${END_TS:-}" ]; then
  END_TS="${START_TS}"
fi
DURATION="$(( ${END_TS:-0} - ${START_TS:-0} ))"

capture_log_dirs "${AFTER_LOGS}"
NEW_LOG_DIRS="$(comm -13 "${BEFORE_LOGS}" "${AFTER_LOGS}" || true)"
LATEST_LOG_DIR="$(printf '%s\n' "${NEW_LOG_DIRS}" | tail -n 1)"

{
  echo "# QuantaAlpha minirun artifact manifest"
  echo "tag=${MINIRUN_TAG}"
  echo "created_at=$(date '+%F %T')"
  echo "direction=${DIRECTION}"
  echo "config=${CONFIG_FILE}"
  echo "step_n=${STEP_N_VALUE}"
  echo "exit_code=${RC}"
  echo "duration_sec=${DURATION}"
  echo "experiment_id=${EXPERIMENT_ID}"
  echo "factor_library_suffix=${FACTOR_LIBRARY_SUFFIX}"
  echo "workspace_path=${WORKSPACE_PATH}"
  echo "pickle_cache_path=${PICKLE_CACHE_PATH}"
  echo "factor_library_path=${FACTORLIB_PATH}"
  if [ -n "${LATEST_LOG_DIR}" ]; then
    echo "latest_log_dir=${LATEST_LOG_DIR}"
  fi
  if [ -n "${NEW_LOG_DIRS}" ]; then
    echo "new_log_dirs_begin"
    printf '%s\n' "${NEW_LOG_DIRS}"
    echo "new_log_dirs_end"
  fi
  echo "cleanup_hint=rm -rf \"${WORKSPACE_PATH}\" \"${PICKLE_CACHE_PATH}\" \"${FACTORLIB_PATH}\""
} > "${MANIFEST_FILE}"

echo "Manifest: ${MANIFEST_FILE}"
if [ -n "${LATEST_LOG_DIR}" ]; then
  echo "Latest log dir: ${LATEST_LOG_DIR}"
fi

if [ "${RC}" -eq 0 ]; then
  send_telegram "✅ QuantaAlpha minirun finished
dir: ${DIRECTION}
step_n: ${STEP_N_VALUE}
tag: ${MINIRUN_TAG}
time: ${DURATION}s"
else
  send_telegram "❌ QuantaAlpha minirun failed
dir: ${DIRECTION}
step_n: ${STEP_N_VALUE}
tag: ${MINIRUN_TAG}
code: ${RC}
time: ${DURATION}s"
fi

exit "${RC}"
