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
#   ./run.sh --blacklist-file data/factorlib/subtree_blacklist.json "initial direction" "suffix"
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
ZOO_DEDUP_MODE=false
RELAY_MODE=false
RESUME_MODE=false
BLACKLIST_FILE=""
ROUNDS_OVERRIDE=""
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
        --zoo-dedup)
            ZOO_DEDUP_MODE=true
            shift
            ;;
        --blacklist-file)
            if [ -z "${2:-}" ] || [[ "${2}" == --* ]]; then
                echo "Error: --blacklist-file requires a file path."
                exit 1
            fi
            BLACKLIST_FILE="$2"
            shift 2
            ;;
        --rounds)
            ROUNDS_OVERRIDE="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage:"
            echo "  ./run.sh [--low-disk|--no-low-disk] [--relay|--resume] [--zoo-dedup] [--blacklist-file PATH] [--rounds N] \"initial direction\" [library_suffix]"
            echo ""
            echo "Options:"
            echo "  --low-disk    Enable low-disk mode (default: ON)."
            echo "  --no-low-disk Disable low-disk mode."
            echo "                Low-disk mode disables pickle cache, compresses parquet,"
            echo "                and purges large temporary files after backtest/cache sync."
            echo "  --relay       Relay mode: run in planned chunks."
            echo "                Default chunk comes from config evolution.relay_chunk_rounds"
            echo "                (fallback: 5 when not configured), next run auto-completes"
            echo "                remaining rounds up to evolution.max_rounds from config."
            echo "  --resume      Resume mode: continue from saved state directly to max_rounds."
            echo "  --zoo-dedup   Zoo dedup mode: skip factor expressions already explored in any"
            echo "                previous run. Sets factor_zoo_path to data/factorlib/factor_zoo.csv"
            echo "                and auto-updates the zoo when the experiment finishes."
            echo "  --blacklist-file PATH"
            echo "                Subtree blacklist mode: reject expressions matching blacklisted"
            echo "                AST subtree patterns from a JSON file."
            echo "  --rounds N    Override evolution.max_rounds (e.g. --rounds 23 for full paper reproduction)."
            echo "                Creates a temporary config with max_rounds replaced; original config is unchanged."
            echo ""
            echo "Environment override:"
            echo "  QUANTA_RELAY_CHUNK_ROUNDS=N   first relay leg rounds (overrides config value)"
            echo "  QUANTA_FACTOR_ZOO_PATH=...    override zoo path (default: data/factorlib/factor_zoo.csv)"
            echo "  QUANTA_SUBTREE_BLACKLIST_PATH=... override blacklist file path"
            echo "  QUANTA_SUBTREE_BLACKLIST_MAX_PATTERNS=N"
            echo "  QUANTA_SUBTREE_BLACKLIST_MIN_NODES=N"
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
    echo "Usage: ./run.sh [--low-disk|--no-low-disk] [--relay|--resume] [--zoo-dedup] [--blacklist-file PATH] \"initial direction\" [library_suffix]"
    exit 1
fi

# =============================================================================
# Load .env configuration
# =============================================================================
# Preserve pre-set env overrides from caller (A/B harness, CI, etc.).
# NOTE: `.env` is sourced with `set -a`, which would otherwise overwrite these.
_HAS_CONFIG_PATH=0; _SAVED_CONFIG_PATH=""
_HAS_STEP_N=0; _SAVED_STEP_N=""
_HAS_EXPERIMENT_ID=0; _SAVED_EXPERIMENT_ID=""
_HAS_FACTOR_LIBRARY_SUFFIX=0; _SAVED_FACTOR_LIBRARY_SUFFIX=""
_HAS_DATA_RESULTS_DIR=0; _SAVED_DATA_RESULTS_DIR=""
_HAS_LOG_TRACE_PATH=0; _SAVED_LOG_TRACE_PATH=""

if [ "${CONFIG_PATH+x}" = "x" ]; then _HAS_CONFIG_PATH=1; _SAVED_CONFIG_PATH="${CONFIG_PATH}"; fi
if [ "${STEP_N+x}" = "x" ]; then _HAS_STEP_N=1; _SAVED_STEP_N="${STEP_N}"; fi
if [ "${EXPERIMENT_ID+x}" = "x" ]; then _HAS_EXPERIMENT_ID=1; _SAVED_EXPERIMENT_ID="${EXPERIMENT_ID}"; fi
if [ "${FACTOR_LIBRARY_SUFFIX+x}" = "x" ]; then _HAS_FACTOR_LIBRARY_SUFFIX=1; _SAVED_FACTOR_LIBRARY_SUFFIX="${FACTOR_LIBRARY_SUFFIX}"; fi
if [ "${DATA_RESULTS_DIR+x}" = "x" ]; then _HAS_DATA_RESULTS_DIR=1; _SAVED_DATA_RESULTS_DIR="${DATA_RESULTS_DIR}"; fi
if [ "${LOG_TRACE_PATH+x}" = "x" ]; then _HAS_LOG_TRACE_PATH=1; _SAVED_LOG_TRACE_PATH="${LOG_TRACE_PATH}"; fi

if [ -f "${SCRIPT_DIR}/.env" ]; then
    set -a
    source "${SCRIPT_DIR}/.env"
    set +a
else
    echo "Error: .env file not found"
    echo "Please run: cp configs/.env.example .env"
    exit 1
fi

# Restore preserved overrides.
if [ "${_HAS_CONFIG_PATH}" -eq 1 ]; then CONFIG_PATH="${_SAVED_CONFIG_PATH}"; export CONFIG_PATH; fi
if [ "${_HAS_STEP_N}" -eq 1 ]; then STEP_N="${_SAVED_STEP_N}"; export STEP_N; fi
if [ "${_HAS_EXPERIMENT_ID}" -eq 1 ]; then EXPERIMENT_ID="${_SAVED_EXPERIMENT_ID}"; export EXPERIMENT_ID; fi
if [ "${_HAS_FACTOR_LIBRARY_SUFFIX}" -eq 1 ]; then FACTOR_LIBRARY_SUFFIX="${_SAVED_FACTOR_LIBRARY_SUFFIX}"; export FACTOR_LIBRARY_SUFFIX; fi
if [ "${_HAS_DATA_RESULTS_DIR}" -eq 1 ]; then DATA_RESULTS_DIR="${_SAVED_DATA_RESULTS_DIR}"; export DATA_RESULTS_DIR; fi
if [ "${_HAS_LOG_TRACE_PATH}" -eq 1 ]; then LOG_TRACE_PATH="${_SAVED_LOG_TRACE_PATH}"; export LOG_TRACE_PATH; fi

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

validate_subtree_blacklist_or_die() {
    local blacklist_path="$1"
    local max_patterns="$2"
    local min_nodes="$3"
    local output=""
    if ! output="$("${PYTHON_BIN}" - "${blacklist_path}" "${max_patterns}" "${min_nodes}" <<'PY'
import json
import sys
from pathlib import Path

from quantaalpha.factors.regulator.subtree_blacklist import SubtreeBlacklist

path = Path(sys.argv[1])
max_patterns = int(sys.argv[2])
min_nodes = int(sys.argv[3])

if not path.exists():
    print(f"Error: subtree blacklist file not found: {path}", file=sys.stderr)
    raise SystemExit(2)

try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"Error: failed to parse subtree blacklist JSON: {path} ({exc})", file=sys.stderr)
    raise SystemExit(3)

if isinstance(payload, list):
    raw_count = len(payload)
elif isinstance(payload, dict) and isinstance(payload.get("patterns"), list):
    raw_count = len(payload["patterns"])
else:
    print(
        "Error: subtree blacklist JSON must be a list or an object with a 'patterns' list.",
        file=sys.stderr,
    )
    raise SystemExit(4)

if raw_count <= 0:
    print(f"Error: subtree blacklist JSON contains no raw patterns: {path}", file=sys.stderr)
    raise SystemExit(5)

blacklist = SubtreeBlacklist(str(path), max_patterns=max_patterns, min_nodes=min_nodes)
if blacklist.size <= 0:
    print(
        "Error: subtree blacklist produced 0 usable patterns after validation "
        f"(path={path}, raw={raw_count}, min_nodes={min_nodes}, max_patterns={max_patterns}).",
        file=sys.stderr,
    )
    raise SystemExit(6)

print(f"{raw_count}:{blacklist.size}")
PY
    )"; then
        return 1
    fi
    BLACKLIST_COUNT_RAW="${output%%:*}"
    BLACKLIST_COUNT_USABLE="${output##*:}"
    return 0
}

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

# If --rounds N is given, create a temp config with max_rounds overridden
_TEMP_CONFIG=""
if [ -n "${ROUNDS_OVERRIDE}" ]; then
    if ! [[ "${ROUNDS_OVERRIDE}" =~ ^[1-9][0-9]*$ ]]; then
        echo "Error: --rounds must be a positive integer (got '${ROUNDS_OVERRIDE}')."
        exit 1
    fi
    _TEMP_CONFIG="$(mktemp "${TMPDIR:-/tmp}/quanta_config_rounds_XXXXXX")"
    if [ -z "${_TEMP_CONFIG}" ] || [ ! -f "${_TEMP_CONFIG}" ]; then
        echo "Error: failed to allocate temporary config file for --rounds override."
        exit 1
    fi
    if ! "${PYTHON_BIN}" - "${CONFIG_PATH}" "${_TEMP_CONFIG}" "${ROUNDS_OVERRIDE}" <<'PY'
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
rounds = sys.argv[3]
text = src.read_text(encoding="utf-8")

pattern = re.compile(r"^(\s*max_rounds:\s*)\d+(\s*(?:#.*)?)$", flags=re.MULTILINE)
new_text, replaced = pattern.subn(rf"\g<1>{rounds}\g<2>", text, count=1)
if replaced == 0:
    raise RuntimeError("Could not locate 'max_rounds' in config.")

dst.write_text(new_text, encoding="utf-8")
PY
    then
        echo "Error: failed to create temp config for --rounds override."
        [ -f "${_TEMP_CONFIG}" ] && rm -f "${_TEMP_CONFIG}"
        exit 1
    fi
    echo "Rounds override: max_rounds=${ROUNDS_OVERRIDE} (temp config: ${_TEMP_CONFIG})"
    CONFIG_PATH="${_TEMP_CONFIG}"
fi

CONFIG_RELAY_CHUNK_ROUNDS="$("${PYTHON_BIN}" -c "
import yaml
try:
    with open('${CONFIG_PATH}', 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    val = cfg.get('evolution', {}).get('relay_chunk_rounds', 5)
    val = int(val)
    print(val if val > 0 else 5)
except Exception:
    print(5)
")"
if ! [[ "${CONFIG_RELAY_CHUNK_ROUNDS}" =~ ^[1-9][0-9]*$ ]]; then
    CONFIG_RELAY_CHUNK_ROUNDS=5
fi

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
        export QUANTA_RELAY_CHUNK_ROUNDS="${QUANTA_RELAY_CHUNK_ROUNDS:-${CONFIG_RELAY_CHUNK_ROUNDS}}"
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
    echo "  Relay target rounds: evolution.max_rounds from config"
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
    export QUANTA_LOW_DISK_FLOAT32="${QUANTA_LOW_DISK_FLOAT32:-false}"
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

# --- Paper Reproduction Parameter Check ---
"${PYTHON_BIN}" -c "
import os
import yaml
try:
    with open('${CONFIG_PATH}', 'r') as f:
        cfg = yaml.safe_load(f)
    rounds = cfg.get('evolution', {}).get('max_rounds', 0)
    factors = cfg.get('factor', {}).get('factors_per_hypothesis', 0)
    chunk = getattr(cfg.get('evolution'), 'get', lambda k, d: 0)('relay_chunk_rounds', 0) if isinstance(cfg.get('evolution'), dict) else 0
    low_disk_mode = os.getenv('QUANTA_LOW_DISK_MODE', '0')
    low_disk_float32 = os.getenv('QUANTA_LOW_DISK_FLOAT32', 'false')
    parquet_compression = os.getenv('QUANTA_PARQUET_COMPRESSION', '')
    purge_parquet = os.getenv('QUANTA_LOW_DISK_PURGE_PARQUET', '')
    purge_h5 = os.getenv('QUANTA_LOW_DISK_PURGE_H5', '')
    paper_factor_match = (factors == 3)

    if rounds == 23 and factors == 3 and chunk == 6:
        print('\n' + '='*60)
        print(' 🚀 [PAPER REPRODUCTION MODE] ✅ FULL CAPACITY ENABLED!')
        print('    - factor.factors_per_hypothesis: 3')
        print('    - evolution.max_rounds: 23')
        print('    - evolution.relay_chunk_rounds: 6')
        print('    - paper.factor_setting_match: YES (factors_per_hypothesis=3)')
        print('    - runtime.QUANTA_LOW_DISK_MODE: ' + str(low_disk_mode))
        print('    - runtime.QUANTA_LOW_DISK_FLOAT32: ' + str(low_disk_float32))
        print('    - runtime.QUANTA_PARQUET_COMPRESSION: ' + str(parquet_compression))
        print('    - runtime.QUANTA_LOW_DISK_PURGE_PARQUET: ' + str(purge_parquet))
        print('    - runtime.QUANTA_LOW_DISK_PURGE_H5: ' + str(purge_h5))
        print('='*60 + '\n')
    else:
        print('\n' + '-'*60)
        print(' ⚠️  [STANDARD MODE] Running with parameters:')
        print(f'    - factor.factors_per_hypothesis: {factors}')
        print(f'    - evolution.max_rounds: {rounds}')
        print(f'    - evolution.relay_chunk_rounds: {chunk}')
        print('    - paper.factor_setting_match: ' + ('YES' if paper_factor_match else 'NO'))
        print('    - runtime.QUANTA_LOW_DISK_MODE: ' + str(low_disk_mode))
        print('    - runtime.QUANTA_LOW_DISK_FLOAT32: ' + str(low_disk_float32))
        print('    - runtime.QUANTA_PARQUET_COMPRESSION: ' + str(parquet_compression))
        print('    - runtime.QUANTA_LOW_DISK_PURGE_PARQUET: ' + str(purge_parquet))
        print('    - runtime.QUANTA_LOW_DISK_PURGE_H5: ' + str(purge_h5))
        print('-'*60 + '\n')
except Exception as e:
    pass
"

if [ -f "${SCRIPT_DIR}/scripts/preflight_check.py" ]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/scripts/preflight_check.py" experiment --config "${CONFIG_PATH}" || true
    echo "----------------------------------------"
fi

if [ "${ZOO_DEDUP_MODE}" = true ]; then
    # factor_regulator.py reads zoo via pd.read_csv → point to CSV file
    # Env var matches FactorCoSTEERSettings(env_prefix="FACTOR_CoSTEER_") + field factor_zoo_path
    ZOO_CSV_PATH="${QUANTA_FACTOR_ZOO_PATH:-${SCRIPT_DIR}/data/factorlib/factor_zoo.csv}"
    export FACTOR_CoSTEER_FACTOR_ZOO_PATH="${ZOO_CSV_PATH}"
    echo "Zoo dedup mode: ON"
    echo "  Zoo CSV: ${ZOO_CSV_PATH}"
    if [ -f "${ZOO_CSV_PATH}" ]; then
        ZOO_COUNT=$(( $(wc -l < "${ZOO_CSV_PATH}") - 1 ))
        echo "  Zoo size: ${ZOO_COUNT} expressions (skip before calculate/backtest)"
    else
        echo "  Zoo CSV not found — will be created after first run. Run:"
        echo "    ${PYTHON_BIN} scripts/update_factor_zoo.py build"
    fi
    echo "----------------------------------------"
fi

if [ -n "${BLACKLIST_FILE}" ]; then
    export QUANTA_SUBTREE_BLACKLIST_ENABLED=1
    export QUANTA_SUBTREE_BLACKLIST_PATH="${BLACKLIST_FILE}"
    export QUANTA_SUBTREE_BLACKLIST_MAX_PATTERNS="${QUANTA_SUBTREE_BLACKLIST_MAX_PATTERNS:-200}"
    export QUANTA_SUBTREE_BLACKLIST_MIN_NODES="${QUANTA_SUBTREE_BLACKLIST_MIN_NODES:-1}"
    if ! validate_subtree_blacklist_or_die \
        "${QUANTA_SUBTREE_BLACKLIST_PATH}" \
        "${QUANTA_SUBTREE_BLACKLIST_MAX_PATTERNS}" \
        "${QUANTA_SUBTREE_BLACKLIST_MIN_NODES}"; then
        exit 1
    fi
fi

if [[ "${QUANTA_SUBTREE_BLACKLIST_ENABLED:-0}" =~ ^(1|true|yes|on)$ ]]; then
    BLACKLIST_PATH="${QUANTA_SUBTREE_BLACKLIST_PATH:-}"
    echo "Subtree blacklist mode: ON"
    echo "  Blacklist JSON: ${BLACKLIST_PATH}"
    echo "  QUANTA_SUBTREE_BLACKLIST_MAX_PATTERNS=${QUANTA_SUBTREE_BLACKLIST_MAX_PATTERNS:-200}"
    echo "  QUANTA_SUBTREE_BLACKLIST_MIN_NODES=${QUANTA_SUBTREE_BLACKLIST_MIN_NODES:-1}"
    if [ -n "${BLACKLIST_PATH}" ] && [ -f "${BLACKLIST_PATH}" ]; then
        if [ -n "${BLACKLIST_COUNT_RAW:-}" ]; then
            echo "  Blacklist entries (raw): ${BLACKLIST_COUNT_RAW}"
            echo "  Blacklist entries (usable): ${BLACKLIST_COUNT_USABLE}"
        else
            echo "  Blacklist file found via env override; validation deferred to runtime config."
        fi
    else
        echo "  Blacklist file not found yet; the run will continue without subtree matches."
    fi
    echo "----------------------------------------"
fi

if [ -n "${STEP_N}" ]; then
    "${QA_BIN}" mine --direction "${DIRECTION}" --step_n "${STEP_N}" --config_path "${CONFIG_PATH}"
else
    "${QA_BIN}" mine --direction "${DIRECTION}" --config_path "${CONFIG_PATH}"
fi
MINE_EXIT_CODE=$?

# Clean up temp config if --rounds was used
if [ -n "${_TEMP_CONFIG}" ] && [ -f "${_TEMP_CONFIG}" ]; then
    rm -f "${_TEMP_CONFIG}"
fi

# After experiment: auto-update factor zoo if --zoo-dedup is on
if [ "${ZOO_DEDUP_MODE}" = true ]; then
    echo ""
    echo "----------------------------------------"
    echo "[zoo-dedup] Updating factor zoo with new factors from this run..."
    ZOO_UPDATE_ARGS="update"
    if [ -n "${LIBRARY_SUFFIX}" ]; then
        ZOO_UPDATE_ARGS="update --lib ${LIBRARY_SUFFIX}"
    fi
    "${PYTHON_BIN}" "${SCRIPT_DIR}/scripts/update_factor_zoo.py" ${ZOO_UPDATE_ARGS} || \
        echo "[zoo-dedup] Warning: zoo update failed (non-fatal)"
    echo "[zoo-dedup] Zoo updated. Next run with --zoo-dedup will skip these factor expressions."
fi

exit ${MINE_EXIT_CODE}
