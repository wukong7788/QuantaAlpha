#!/bin/bash
# QuantaAlpha main experiment runner
#
# Usage:
#   ./run.sh "initial direction"                    # default experiment
#   ./run.sh "initial direction" "suffix"           # with factor library suffix
#   CONFIG=configs/experiment.yaml ./run.sh "direction"
#
# Examples:
#   ./run.sh "price-volume factor mining"
#   ./run.sh "momentum reversal factors" "exp_momentum"

# =============================================================================
# Locate project root
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# =============================================================================
# Load .env configuration
# =============================================================================
if [ -f "${SCRIPT_DIR}/.env" ]; then
    set -a
    source "${SCRIPT_DIR}/.env"
    set +a
else
    echo "Error: .env file not found"
    echo "Please run: cp configs/.env.example .env"
    exit 1
fi

# =============================================================================
# Resolve Python environment (prefer uv .venv, no conda dependency)
# =============================================================================
PYTHON_BIN=""
PIP_BIN=""
QA_BIN=""

if [ -x "${SCRIPT_DIR}/.venv/bin/python" ]; then
    PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"
    PIP_BIN="${SCRIPT_DIR}/.venv/bin/pip"
    QA_BIN="${SCRIPT_DIR}/.venv/bin/quantaalpha"
elif command -v uv >/dev/null 2>&1; then
    echo "Info: .venv not found, creating with uv (Python 3.12)..."
    uv venv --python 3.12 "${SCRIPT_DIR}/.venv" || {
        echo "Error: failed to create .venv via uv"
        exit 1
    }
    PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"
    PIP_BIN="${SCRIPT_DIR}/.venv/bin/pip"
    QA_BIN="${SCRIPT_DIR}/.venv/bin/quantaalpha"
else
    echo "Error: no .venv found and uv is not installed."
    echo "Please run: uv venv --python 3.12 .venv && uv pip install -e ."
    exit 1
fi

if [ ! -x "${QA_BIN}" ]; then
    echo "Info: quantaalpha not found in .venv, installing project..."
    "${PIP_BIN}" install -e . || {
        echo "Error: failed to install quantaalpha into .venv"
        exit 1
    }
fi

if [ ! -x "${QA_BIN}" ]; then
    echo "Error: quantaalpha command not found in .venv after install."
    exit 1
fi

echo "Python: $("${PYTHON_BIN}" --version)"
echo "QuantaAlpha: ${QA_BIN}"
echo ""

# =============================================================================
# Compatibility env vars for rdagent (still expects conda fields internally)
# =============================================================================
export CONDA_DEFAULT_ENV="${CONDA_DEFAULT_ENV:-quantaalpha}"
# Ensure factor code execution uses current .venv python instead of system python
export FACTOR_CoSTEER_PYTHON_BIN="${FACTOR_CoSTEER_PYTHON_BIN:-${PYTHON_BIN}}"

# =============================================================================
# Experiment isolation
# =============================================================================
CONFIG_PATH=${CONFIG_PATH:-"configs/experiment.yaml"}

if [ -z "${EXPERIMENT_ID}" ]; then
    EXPERIMENT_ID="exp_$(date +%Y%m%d_%H%M%S)"
fi
export EXPERIMENT_ID

RESULTS_BASE="${DATA_RESULTS_DIR:-./data/results}"

if [ "${EXPERIMENT_ID}" != "shared" ]; then
    export WORKSPACE_PATH="${RESULTS_BASE}/workspace_${EXPERIMENT_ID}"
    export PICKLE_CACHE_FOLDER_PATH_STR="${RESULTS_BASE}/pickle_cache_${EXPERIMENT_ID}"
    mkdir -p "${WORKSPACE_PATH}" "${PICKLE_CACHE_FOLDER_PATH_STR}"
    echo "Experiment ID: ${EXPERIMENT_ID}"
    echo "Workspace: ${WORKSPACE_PATH}"
fi

# =============================================================================
# Validate Qlib data
# =============================================================================
QLIB_DATA="${QLIB_DATA_DIR:-}"
if [ -z "${QLIB_DATA}" ]; then
    echo "Error: QLIB_DATA_DIR not set. Please set Qlib data path in .env"
    echo "Example: QLIB_DATA_DIR=/path/to/qlib/cn_data"
    exit 1
fi
if [ ! -d "${QLIB_DATA}" ]; then
    echo "Error: Qlib data directory does not exist: ${QLIB_DATA}"
    echo "Please check QLIB_DATA_DIR path in .env"
    exit 1
fi
# Validate required subdirectories
for subdir in calendars features instruments; do
    if [ ! -d "${QLIB_DATA}/${subdir}" ]; then
        echo "Error: Qlib data directory missing ${subdir}/: ${QLIB_DATA}"
        echo "Valid Qlib data dir must contain calendars/, features/, instruments/"
        exit 1
    fi
done
echo "Qlib data validated: ${QLIB_DATA}"

# Ensure Qlib data symlink
if [ -n "${QLIB_DATA}" ]; then
    QLIB_SYMLINK_DIR="$HOME/.qlib/qlib_data"
    if [ ! -L "${QLIB_SYMLINK_DIR}/cn_data" ] || [ "$(readlink -f ${QLIB_SYMLINK_DIR}/cn_data 2>/dev/null)" != "$(readlink -f ${QLIB_DATA})" ]; then
        mkdir -p "${QLIB_SYMLINK_DIR}"
        ln -sfn "${QLIB_DATA}" "${QLIB_SYMLINK_DIR}/cn_data"
    fi
fi

# =============================================================================
# Parse arguments and run
# =============================================================================
DIRECTION="$1"
LIBRARY_SUFFIX="$2"

if [ -n "${LIBRARY_SUFFIX}" ]; then
    export FACTOR_LIBRARY_SUFFIX="${LIBRARY_SUFFIX}"
fi

echo ""
echo "Starting experiment..."
echo "Config: ${CONFIG_PATH}"
echo "Data: ${QLIB_DATA}"
echo "Results: ${RESULTS_BASE}"
echo "----------------------------------------"

if [ -n "${STEP_N}" ]; then
    "${QA_BIN}" mine --direction "${DIRECTION}" --step_n "${STEP_N}" --config_path "${CONFIG_PATH}"
else
    "${QA_BIN}" mine --direction "${DIRECTION}" --config_path "${CONFIG_PATH}"
fi
