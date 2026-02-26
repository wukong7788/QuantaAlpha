#!/bin/bash
# QuantaAlpha main experiment runner
#
# Usage:
#   ./run.sh "initial direction"                    # default experiment (low-disk ON)
#   ./run.sh "initial direction" "suffix"           # with factor library suffix
#   ./run.sh --low-disk "initial direction" "suffix"# explicit low-disk ON
#   ./run.sh --no-low-disk "initial direction" "suffix" # disable low-disk mode
#   ./run.sh --relay "initial direction" "suffix"   # relay mode (auto chunk, true resume across restarts)
#   ./run.sh --resume "initial direction" "suffix"  # resume mode (continue to max_rounds)
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
# Parse arguments early (avoid side effects for --help)
# =============================================================================
LOW_DISK_MODE=true
RELAY_MODE=false
RESUME_MODE=false
POSITIONAL_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --low-disk)
            LOW_DISK_MODE=true
            shift
            ;;
        --no-low-disk)
            LOW_DISK_MODE=false
            shift
            ;;
        --relay)
            RELAY_MODE=true
            shift
            ;;
        --resume)
            RESUME_MODE=true
            shift
            ;;
        -h|--help)
            echo "Usage:"
            echo "  ./run.sh [--low-disk|--no-low-disk] [--relay|--resume] \"initial direction\" [library_suffix]"
            echo ""
            echo "Options:"
            echo "  --low-disk   Enable low-disk mode."
            echo "  --no-low-disk Disable low-disk mode (default is ON)."
            echo "               Low-disk mode disables pickle cache, compresses parquet,"
            echo "               and purges large temporary files after backtest/cache sync."
            echo "  --relay      Relay mode: run in planned chunks."
            echo "               Default chunk is 5 rounds; next run auto-completes remaining rounds"
            echo "               up to evolution.max_rounds (default 11)."
            echo "  --resume     Resume mode: continue from saved state directly to max_rounds."
            echo ""
            echo "Environment override:"
            echo "  QUANTA_RELAY_CHUNK_ROUNDS=5   first relay leg rounds (default 5)"
            exit 0
            ;;
        *)
            POSITIONAL_ARGS+=("$1")
            shift
            ;;
    esac
done
set -- "${POSITIONAL_ARGS[@]}"

if [ "${RELAY_MODE}" = true ] && [ "${RESUME_MODE}" = true ]; then
    echo "Error: --relay and --resume are mutually exclusive."
    exit 1
fi

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Error: invalid arguments."
    echo "Usage: ./run.sh [--low-disk|--no-low-disk] [--relay|--resume] \"initial direction\" [library_suffix]"
    exit 1
fi

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
    if [ "${RELAY_MODE}" = true ] || [ "${RESUME_MODE}" = true ]; then
        EXPERIMENT_ID="relay_shared"
    else
        EXPERIMENT_ID="exp_$(date +%Y%m%d_%H%M%S)"
    fi
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

if [ "${RELAY_MODE}" = true ] || [ "${RESUME_MODE}" = true ]; then
    export QUANTA_ENABLE_RELAY=1
    if [ "${RELAY_MODE}" = true ]; then
        export QUANTA_RELAY_MODE="relay"
        export QUANTA_RELAY_CHUNK_ROUNDS="${QUANTA_RELAY_CHUNK_ROUNDS:-5}"
        if ! [[ "${QUANTA_RELAY_CHUNK_ROUNDS}" =~ ^[1-9][0-9]*$ ]]; then
            echo "Error: QUANTA_RELAY_CHUNK_ROUNDS must be a positive integer (got '${QUANTA_RELAY_CHUNK_ROUNDS}')."
            exit 1
        fi
    else
        export QUANTA_RELAY_MODE="resume"
    fi
    if [ -z "${LOG_TRACE_PATH}" ]; then
        export LOG_TRACE_PATH="${SCRIPT_DIR}/log/relay_${EXPERIMENT_ID}"
    fi
    mkdir -p "${LOG_TRACE_PATH}"
    if [ "${RELAY_MODE}" = true ]; then
        echo "Relay mode: ON"
    else
        echo "Resume mode: ON"
    fi
    echo "  QUANTA_ENABLE_RELAY=${QUANTA_ENABLE_RELAY}"
    echo "  QUANTA_RELAY_MODE=${QUANTA_RELAY_MODE}"
    if [ "${RELAY_MODE}" = true ]; then
        echo "  QUANTA_RELAY_CHUNK_ROUNDS=${QUANTA_RELAY_CHUNK_ROUNDS}"
        echo "  Relay schedule: first leg uses chunk; later leg auto-finish to target"
    fi
    echo "  Relay target rounds: evolution.max_rounds from config (default 11)"
    echo "  LOG_TRACE_PATH=${LOG_TRACE_PATH}"
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
LIBRARY_SUFFIX="${2:-}"

if [ -n "${LIBRARY_SUFFIX}" ]; then
    export FACTOR_LIBRARY_SUFFIX="${LIBRARY_SUFFIX}"
fi

if [ "${LOW_DISK_MODE}" = true ]; then
    export QUANTA_LOW_DISK_MODE=1
    export CACHE_WITH_PICKLE=false
    export QUANTA_PARQUET_COMPRESSION="${QUANTA_PARQUET_COMPRESSION:-zstd}"
    export QUANTA_LOW_DISK_FLOAT32="${QUANTA_LOW_DISK_FLOAT32:-true}"
    export QUANTA_LOW_DISK_PURGE_PARQUET="${QUANTA_LOW_DISK_PURGE_PARQUET:-true}"
    export QUANTA_LOW_DISK_PURGE_H5="${QUANTA_LOW_DISK_PURGE_H5:-true}"
    echo "Low disk mode: ON"
    echo "  CACHE_WITH_PICKLE=${CACHE_WITH_PICKLE}"
    echo "  QUANTA_PARQUET_COMPRESSION=${QUANTA_PARQUET_COMPRESSION}"
    echo "  QUANTA_LOW_DISK_FLOAT32=${QUANTA_LOW_DISK_FLOAT32}"
    echo "  QUANTA_LOW_DISK_PURGE_PARQUET=${QUANTA_LOW_DISK_PURGE_PARQUET}"
    echo "  QUANTA_LOW_DISK_PURGE_H5=${QUANTA_LOW_DISK_PURGE_H5}"
    echo "----------------------------------------"
else
    export QUANTA_LOW_DISK_MODE=0
    : "${CACHE_WITH_PICKLE:=true}"
    export CACHE_WITH_PICKLE
    echo "Low disk mode: OFF"
    echo "  CACHE_WITH_PICKLE=${CACHE_WITH_PICKLE}"
    echo "----------------------------------------"
fi

echo ""
echo "Starting experiment..."
echo "Config: ${CONFIG_PATH}"
echo "Data: ${QLIB_DATA}"
echo "Results: ${RESULTS_BASE}"
echo "----------------------------------------"

if [ -f "${SCRIPT_DIR}/scripts/preflight_check.py" ]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/scripts/preflight_check.py" experiment --config "${CONFIG_PATH}" || true
    echo "----------------------------------------"
fi

if [ -n "${STEP_N}" ]; then
    "${QA_BIN}" mine --direction "${DIRECTION}" --step_n "${STEP_N}" --config_path "${CONFIG_PATH}"
else
    "${QA_BIN}" mine --direction "${DIRECTION}" --config_path "${CONFIG_PATH}"
fi
