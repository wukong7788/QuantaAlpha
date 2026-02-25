#!/usr/bin/env bash
set -euo pipefail

# Safe standalone backtest runner for QuantaAlpha.
# - Runs backtest without frontend
# - Writes full logs to file
# - Limits thread count to reduce crash risk
# - Checks factor cache completeness (h5_cached + md5_cached)
# - Optionally warms MD5 cache from result.h5 before backtest

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/run_backtest_safe.sh --library <factor_json>
  ./scripts/run_backtest_safe.sh --interactive

Options:
  --library <name-or-path>      Factor library JSON filename or path (required)
  --mode <performance|limited>  Run mode (default: limited)
                                performance = higher threads, faster but heavier
                                limited = fewer threads, safer on laptop
  --factor-source <custom|combined>
                                Factor source for backtest (default: custom)
  --config <path>               Backtest config path (default: configs/backtest.yaml)
  --threads <N>                 Override thread count manually (optional)
  --max-factors <N|all|default> Override custom max factors in config:
                                N = use top N custom factors
                                all = no limit (null)
                                default = keep config value
  --min-free-gb <N>             Minimum free disk GB required (default: 15)
  --warm-cache                  Sync available result.h5 into MD5 cache before run
  --log-file <path>             Custom log file path (default: log/backtest_manual/<timestamp>.log)
  --interactive                 Interactive wizard mode
  -h, --help                    Show this help

Examples:
  ./scripts/run_backtest_safe.sh --library all_factors_library_paper_reproduction.json
  ./scripts/run_backtest_safe.sh --library data/factorlib/all_factors_library_x.json --threads 6 --warm-cache
USAGE
}

LIBRARY=""
MODE="limited"
FACTOR_SOURCE="custom"
CONFIG_PATH="configs/backtest.yaml"
CONFIG_SET="false"
THREADS="8"
THREADS_SET="false"
MAX_FACTORS_OVERRIDE="default"
MAX_FACTORS_SET="false"
MIN_FREE_GB="15"
WARM_CACHE="false"
SKIP_UNCACHED="true"  # fixed by design
CUSTOM_LOG_FILE=""
INTERACTIVE="false"
ORIGINAL_ARGC="$#"

prompt_default() {
  local label="$1"
  local default_val="$2"
  local val
  read -r -p "$label [$default_val]: " val
  if [[ -z "$val" ]]; then
    echo "$default_val"
  else
    echo "$val"
  fi
}

prompt_yn() {
  local label="$1"
  local default_val="$2"  # y or n
  local ans
  local ans_norm
  while true; do
    if [[ "$default_val" == "y" ]]; then
      read -r -p "$label [Y/n]: " ans
      ans="${ans:-y}"
    else
      read -r -p "$label [y/N]: " ans
      ans="${ans:-n}"
    fi
    ans_norm="$(printf '%s' "$ans" | tr '[:upper:]' '[:lower:]')"
    case "$ans_norm" in
      y|yes) echo "true"; return 0 ;;
      n|no)  echo "false"; return 0 ;;
      *) echo "Please answer y or n." ;;
    esac
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --library)
      LIBRARY="${2:-}"
      shift 2
      ;;
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --factor-source)
      FACTOR_SOURCE="${2:-}"
      shift 2
      ;;
    --config)
      CONFIG_PATH="${2:-}"
      CONFIG_SET="true"
      shift 2
      ;;
    --threads)
      THREADS="${2:-}"
      THREADS_SET="true"
      shift 2
      ;;
    --max-factors)
      MAX_FACTORS_OVERRIDE="${2:-}"
      MAX_FACTORS_SET="true"
      shift 2
      ;;
    --min-free-gb)
      MIN_FREE_GB="${2:-}"
      shift 2
      ;;
    --warm-cache)
      WARM_CACHE="true"
      shift
      ;;
    --log-file)
      CUSTOM_LOG_FILE="${2:-}"
      shift 2
      ;;
    --interactive)
      INTERACTIVE="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ "$ORIGINAL_ARGC" -eq 0 ]]; then
  INTERACTIVE="true"
fi

if [[ "$MODE" != "performance" && "$MODE" != "limited" ]]; then
  echo "Error: --mode must be performance or limited"
  exit 1
fi

if [[ "$CONFIG_SET" != "true" ]]; then
  if [[ "$MODE" == "limited" ]]; then
    CONFIG_PATH="configs/backtest_limited.yaml"
  else
    CONFIG_PATH="configs/backtest.yaml"
  fi
fi

if [[ "$THREADS_SET" != "true" ]]; then
  if [[ "$MODE" == "performance" ]]; then
    THREADS="12"
  else
    THREADS="6"
  fi
fi

normalize_lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

validate_max_factors() {
  local raw="$1"
  local v
  v="$(normalize_lower "$raw")"
  if [[ "$v" == "all" || "$v" == "default" ]]; then
    return 0
  fi
  if [[ "$v" =~ ^[0-9]+$ ]] && [[ "$v" -gt 0 ]]; then
    return 0
  fi
  return 1
}

if [[ "$INTERACTIVE" == "true" ]]; then
  echo "== QuantaAlpha Backtest Wizard =="
  echo

  if [[ -z "$LIBRARY" ]]; then
    shopt -s nullglob
    LIB_PATHS=( "$PROJECT_ROOT"/data/factorlib/*.json )
    shopt -u nullglob
    LIBS=()
    for p in "${LIB_PATHS[@]}"; do
      LIBS+=( "$(basename "$p")" )
    done
    if [[ "${#LIBS[@]}" -gt 0 ]]; then
      echo "Available factor libraries:"
      i=1
      for lib in "${LIBS[@]}"; do
        echo "  $i) $lib"
        ((i++))
      done
      read -r -p "Select library number (or type custom path): " pick
      if [[ "$pick" =~ ^[0-9]+$ ]] && [[ "$pick" -ge 1 ]] && [[ "$pick" -le "${#LIBS[@]}" ]]; then
        LIBRARY="${LIBS[$((pick-1))]}"
      else
        LIBRARY="$pick"
      fi
    else
      LIBRARY="$(prompt_default "Factor library filename/path" "data/factorlib/all_factors_library.json")"
    fi
  fi

  if [[ "$FACTOR_SOURCE" != "custom" && "$FACTOR_SOURCE" != "combined" ]]; then
    FACTOR_SOURCE="custom"
  fi
  MODE="$(prompt_default "Run mode (performance/limited)" "$MODE")"
  if [[ "$MODE" != "performance" && "$MODE" != "limited" ]]; then
    echo "Invalid mode, fallback to limited"
    MODE="limited"
  fi
  if [[ "$THREADS_SET" != "true" ]]; then
    if [[ "$MODE" == "performance" ]]; then
      THREADS="12"
    else
      THREADS="6"
    fi
  fi
  echo "Thread count is set by mode: $THREADS"

  if [[ "$WARM_CACHE" != "true" ]]; then
    WARM_CACHE="$(prompt_yn "Warm cache before run?" "y")"
  fi

  if [[ "$MAX_FACTORS_SET" != "true" ]]; then
    MAX_FACTORS_OVERRIDE="$(prompt_default "Max custom factors (N/all/default)" "$MAX_FACTORS_OVERRIDE")"
  fi
  if ! validate_max_factors "$MAX_FACTORS_OVERRIDE"; then
    echo "Invalid max-factors, fallback to default"
    MAX_FACTORS_OVERRIDE="default"
  fi

  echo
  echo "Wizard summary:"
  echo "  library=$LIBRARY"
  echo "  mode=$MODE"
  echo "  factor_source=$FACTOR_SOURCE"
  echo "  config=$CONFIG_PATH"
  echo "  threads=$THREADS"
  echo "  max_factors=$MAX_FACTORS_OVERRIDE"
  echo "  warm_cache=$WARM_CACHE"
  echo "  skip_uncached=$SKIP_UNCACHED"
  echo "  log_file=<default>"
  if [[ "$(prompt_yn "Proceed?" "y")" != "true" ]]; then
    echo "Cancelled."
    exit 0
  fi
fi

if [[ -z "$LIBRARY" ]]; then
  echo "Error: --library is required (or run with --interactive)"
  usage
  exit 1
fi

if [[ "$FACTOR_SOURCE" != "custom" && "$FACTOR_SOURCE" != "combined" ]]; then
  echo "Error: --factor-source must be custom or combined"
  exit 1
fi

if ! [[ "$THREADS" =~ ^[0-9]+$ ]] || [[ "$THREADS" -le 0 ]]; then
  echo "Error: --threads must be a positive integer"
  exit 1
fi

if ! validate_max_factors "$MAX_FACTORS_OVERRIDE"; then
  echo "Error: --max-factors must be a positive integer, all, or default"
  exit 1
fi

if ! [[ "$MIN_FREE_GB" =~ ^[0-9]+$ ]] || [[ "$MIN_FREE_GB" -lt 1 ]]; then
  echo "Error: --min-free-gb must be an integer >= 1"
  exit 1
fi

if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Error: Python not found. Create .venv first or install python3."
  exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "Error: config file not found: $CONFIG_PATH"
  exit 1
fi

RUN_CONFIG_PATH="$CONFIG_PATH"
TMP_CONFIG_PATH=""
MAX_FACTORS_EFFECTIVE="$(normalize_lower "$MAX_FACTORS_OVERRIDE")"
if [[ "$MAX_FACTORS_EFFECTIVE" != "default" ]]; then
  TMP_CONFIG_PATH="$(mktemp "/tmp/quantaalpha_backtest_cfg_XXXX.yaml")"
  "$PYTHON_BIN" - "$CONFIG_PATH" "$TMP_CONFIG_PATH" "$MAX_FACTORS_EFFECTIVE" <<'PY'
import sys
from pathlib import Path
import yaml

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
raw = sys.argv[3].strip().lower()

with src.open("r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}

factor_source = cfg.setdefault("factor_source", {})
custom = factor_source.setdefault("custom", {})
if raw == "all":
    custom["max_factors"] = None
else:
    custom["max_factors"] = int(raw)

with dst.open("w", encoding="utf-8") as f:
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
PY
  RUN_CONFIG_PATH="$TMP_CONFIG_PATH"
fi

resolve_library_path() {
  local input="$1"
  if [[ -f "$input" ]]; then
    echo "$input"
    return 0
  fi
  if [[ -f "$PROJECT_ROOT/data/factorlib/$input" ]]; then
    echo "$PROJECT_ROOT/data/factorlib/$input"
    return 0
  fi
  if [[ -f "$PROJECT_ROOT/$input" ]]; then
    echo "$PROJECT_ROOT/$input"
    return 0
  fi
  return 1
}

LIB_PATH="$(resolve_library_path "$LIBRARY" || true)"
if [[ -z "$LIB_PATH" ]]; then
  echo "Error: factor library not found: $LIBRARY"
  echo "Checked: <input>, data/factorlib/<input>, project-root/<input>"
  exit 1
fi

FREE_KB="$(df -Pk "$PROJECT_ROOT" | awk 'NR==2 {print $4}')"
FREE_GB="$((FREE_KB / 1024 / 1024))"
if [[ "$FREE_GB" -lt "$MIN_FREE_GB" ]]; then
  echo "Error: low disk space: ${FREE_GB}GB available (< ${MIN_FREE_GB}GB required)"
  echo "Tip: clear space first, otherwise cache warm/backtest may fail."
  exit 1
fi

CACHE_JSON="$("$PYTHON_BIN" -c "import json; from quantaalpha.factors.library import FactorLibraryManager as F; r=F.check_cache_status('$LIB_PATH'); print(json.dumps(r, ensure_ascii=False))")"
TOTAL="$(echo "$CACHE_JSON" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d['total'])")"
H5="$(echo "$CACHE_JSON" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d['h5_cached'])")"
MD5="$(echo "$CACHE_JSON" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d['md5_cached'])")"
NEED="$(echo "$CACHE_JSON" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d['need_compute'])")"
READY="$((H5 + MD5))"

echo "[Cache] total=${TOTAL}, h5_cached=${H5}, md5_cached=${MD5}, need_compute=${NEED}, ready=${READY}"

if [[ "$WARM_CACHE" == "true" ]]; then
  echo "[Cache] warm-cache enabled: syncing available result.h5 -> MD5 cache..."
  "$PYTHON_BIN" -c "from quantaalpha.factors.library import FactorLibraryManager as F; import json; print(json.dumps(F.warm_cache_from_json('$LIB_PATH'), ensure_ascii=False))"
  CACHE_JSON="$("$PYTHON_BIN" -c "import json; from quantaalpha.factors.library import FactorLibraryManager as F; r=F.check_cache_status('$LIB_PATH'); print(json.dumps(r, ensure_ascii=False))")"
  TOTAL="$(echo "$CACHE_JSON" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d['total'])")"
  H5="$(echo "$CACHE_JSON" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d['h5_cached'])")"
  MD5="$(echo "$CACHE_JSON" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d['md5_cached'])")"
  NEED="$(echo "$CACHE_JSON" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d['need_compute'])")"
  READY="$((H5 + MD5))"
  echo "[Cache] after warm: total=${TOTAL}, h5_cached=${H5}, md5_cached=${MD5}, need_compute=${NEED}, ready=${READY}"
fi

if [[ "$SKIP_UNCACHED" == "true" && "$NEED" -gt 0 ]]; then
  echo "[Cache] incomplete: missing=${NEED}. Continue with cached factors only (skip uncached enabled)."
fi

export OMP_NUM_THREADS="$THREADS"
export MKL_NUM_THREADS="$THREADS"
export OPENBLAS_NUM_THREADS="$THREADS"
export NUMEXPR_NUM_THREADS="$THREADS"
export VECLIB_MAXIMUM_THREADS="$THREADS"

LOG_DIR="$PROJECT_ROOT/log/backtest_manual"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${CUSTOM_LOG_FILE:-$LOG_DIR/backtest_${TS}.log}"
PID_DIR="$LOG_DIR/pids"
mkdir -p "$PID_DIR"
PID_FILE="$PID_DIR/backtest_${TS}.pid"

CMD_PID=""
TEE_PID=""
LOG_PIPE=""

log_msg() {
  local msg="$1"
  local now
  now="$(date '+%F %T')"
  echo "[$now] $msg" | tee -a "$LOG_FILE"
}

on_signal() {
  local sig="$1"
  log_msg "[Signal] script_pid=$$ received $sig"
  {
    echo "last_signal=$sig"
    echo "last_signal_at=$(date '+%F %T')"
  } >> "$PID_FILE"

  if [[ -n "$CMD_PID" ]] && kill -0 "$CMD_PID" 2>/dev/null; then
    log_msg "[Signal] forwarding $sig to cmd_pid=$CMD_PID"
    kill -s "$sig" "$CMD_PID" 2>/dev/null || true
  fi
}

cleanup_runtime() {
  trap - TERM INT HUP EXIT
  if [[ -n "$TMP_CONFIG_PATH" && -f "$TMP_CONFIG_PATH" ]]; then
    rm -f "$TMP_CONFIG_PATH" 2>/dev/null || true
  fi
  if [[ -n "$LOG_PIPE" && -p "$LOG_PIPE" ]]; then
    rm -f "$LOG_PIPE" 2>/dev/null || true
  fi
  if [[ -n "$TEE_PID" ]] && kill -0 "$TEE_PID" 2>/dev/null; then
    kill "$TEE_PID" 2>/dev/null || true
  fi
}

trap 'on_signal TERM' TERM
trap 'on_signal INT' INT
trap 'on_signal HUP' HUP
trap cleanup_runtime EXIT

echo "[Run] library=$LIB_PATH"
echo "[Run] mode=$MODE"
echo "[Run] factor_source=$FACTOR_SOURCE config=$RUN_CONFIG_PATH (base=$CONFIG_PATH)"
echo "[Run] threads=$THREADS skip_uncached=$SKIP_UNCACHED"
echo "[Run] max_factors=$MAX_FACTORS_EFFECTIVE"
echo "[Run] free_disk=${FREE_GB}GB log=$LOG_FILE"

CMD=(
  "$PYTHON_BIN" -m quantaalpha.backtest.run_backtest
  -c "$RUN_CONFIG_PATH"
  --factor-source "$FACTOR_SOURCE"
  --factor-json "$LIB_PATH"
  -v
)

if [[ "$SKIP_UNCACHED" == "true" ]]; then
  CMD+=(--skip-uncached)
fi

LOG_PIPE="$(mktemp -u "/tmp/quantaalpha_backtest_${TS}_XXXX.pipe")"
mkfifo "$LOG_PIPE"

tee "$LOG_FILE" < "$LOG_PIPE" &
TEE_PID=$!

"${CMD[@]}" > "$LOG_PIPE" 2>&1 &
CMD_PID=$!

cat > "$PID_FILE" <<EOF
script_pid=$$
cmd_pid=$CMD_PID
tee_pid=$TEE_PID
started_at=$(date '+%F %T')
log_file=$LOG_FILE
library=$LIB_PATH
mode=$MODE
factor_source=$FACTOR_SOURCE
config=$RUN_CONFIG_PATH
config_base=$CONFIG_PATH
threads=$THREADS
max_factors=$MAX_FACTORS_EFFECTIVE
EOF

log_msg "[Run] pid_file=$PID_FILE"
log_msg "[Run] cmd_pid=$CMD_PID tee_pid=$TEE_PID"

set +e
wait "$CMD_PID"
EXIT_CODE=$?
wait "$TEE_PID" 2>/dev/null
set -e

{
  echo "finished_at=$(date '+%F %T')"
  echo "exit_code=$EXIT_CODE"
} >> "$PID_FILE"

echo "[Done] exit_code=$EXIT_CODE"
echo "[Done] log_file=$LOG_FILE"
echo "[Done] pid_file=$PID_FILE"

exit "$EXIT_CODE"
