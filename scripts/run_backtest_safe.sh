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
  ./scripts/run_backtest_safe.sh --view-results

Options:
  --library <name-or-path>      Factor library JSON filename or path
                                (required unless --bob-libraries is provided in BOB mode)
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
  --corr-dedup                  Enable correlation-based de-dup + Top-N selection
                                (runs scripts/select_diverse_factors.py to produce a smaller
                                diverse library JSON before backtest).
  --dedup-topn <N>              Final Top-N after correlation de-dup
                                (default: inferred from config factor_source.custom.max_factors when possible)
  --dedup-per-cluster <K>       Keep K champions per cluster (default: 3; set 1 for strict diversity)
  --dedup-corr-threshold <T>    Cluster edge threshold on |Spearman corr| (default: 0.8)
  --dedup-sample-size <N>       Sample size for correlation computation (default: 8000)
  --dedup-compute-missing       Compute/cache factor values when missing (can be slow)
  --min-free-gb <N>             Minimum free disk GB required (default: 15)
  --warm-cache                  Sync available result.h5 into MD5 cache before run
  --bob                         Build Best-of-Best (BOB) library from multiple runs, then backtest
  --bob-libraries <spec>        BOB input libraries (comma/glob), e.g.
                                "all_factors_library_a.json,all_factors_library_b.json"
                                "data/factorlib/all_factors_library_*.json"
  --bob-top <N>                 Keep top N factors in BOB library (default: 50)
  --bob-metric <auto|information_ratio|rank_ic|ic|annualized_return>
                                Primary metric used for BOB ranking (default: auto)
  --bob-grade <s|sa|all>        Grade scope for BOB pool:
                                s = only S-grade factors
                                sa = S + A grades (default)
                                all = keep S/A/B/C
  --log-file <path>             Custom log file path (default: log/backtest_manual/<timestamp>.log)
  --interactive                 Interactive wizard mode
  --view-results                Open horizontal comparison of existing result files and exit
  --view-pick <spec>            View mode: compare selected indexes, e.g. 1,2,3 or all
  --view-latest <N>             View mode: show latest N candidates in selector list
  --view-result-dir <path>      View mode: metrics directory (default: data/results/backtest_v2_results)
  -h, --help                    Show this help

Examples:
  ./scripts/run_backtest_safe.sh --library all_factors_library_paper_reproduction.json
  ./scripts/run_backtest_safe.sh --library data/factorlib/all_factors_library_x.json --threads 6 --warm-cache
  ./scripts/run_backtest_safe.sh --library data/factorlib/all_factors_library_x.json --max-factors 80 --corr-dedup --dedup-per-cluster 1
  ./scripts/run_backtest_safe.sh --bob --bob-libraries "data/factorlib/all_factors_library_*.json" --bob-top 80
  ./scripts/run_backtest_safe.sh --bob --bob-libraries "data/factorlib/all_factors_library_*.json" --bob-grade s
  ./scripts/run_backtest_safe.sh --view-results
  ./scripts/run_backtest_safe.sh --view-results --view-pick 1,2,3
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
QUALITY_MIN_SOURCE="${BACKTEST_MIN_QUALITY:-auto}"  # auto => limited: high, performance: off
QUALITY_MIN="$QUALITY_MIN_SOURCE"
CORR_DEDUP="false"
DEDUP_TOPN=""
DEDUP_TOPN_EFFECTIVE=""
DEDUP_PER_CLUSTER="3"
DEDUP_CORR_THRESHOLD="0.8"
DEDUP_SAMPLE_SIZE="8000"
DEDUP_COMPUTE_MISSING="false"
BOB_ENABLED="false"
BOB_LIBRARIES=""
BOB_TOP="50"
BOB_METRIC="auto"
BOB_GRADE_MODE="sa"
CUSTOM_LOG_FILE=""
INTERACTIVE="false"
VIEW_RESULTS_ONLY="false"
VIEW_PICK=""
VIEW_LATEST=""
VIEW_RESULT_DIR=""
ORIGINAL_ARGC="$#"

run_view_results() {
  local py="$PROJECT_ROOT/.venv/bin/python"
  local script="$PROJECT_ROOT/scripts/view_results.py"
  local args=()
  if [[ ! -f "$script" ]]; then
    echo "Error: view script not found: $script"
    exit 1
  fi
  if [[ ! -x "$py" ]]; then
    py="$(command -v python3 || true)"
  fi
  if [[ -z "$py" ]]; then
    echo "Error: Python not found for view-results."
    exit 1
  fi

  if [[ -n "$VIEW_RESULT_DIR" ]]; then
    args+=(--result-dir "$VIEW_RESULT_DIR")
  fi
  if [[ -n "$VIEW_LATEST" ]]; then
    args+=(--latest "$VIEW_LATEST")
  fi
  if [[ -n "$VIEW_PICK" ]]; then
    args+=(--pick "$VIEW_PICK")
  fi

  if [[ ${#args[@]} -eq 0 && -t 0 && -t 1 ]]; then
    args+=(--interactive)
  fi

  if [[ ${#args[@]} -gt 0 ]]; then
    "$py" "$script" "${args[@]}"
  else
    "$py" "$script"
  fi
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
    --corr-dedup)
      CORR_DEDUP="true"
      shift
      ;;
    --dedup-topn)
      DEDUP_TOPN="${2:-}"
      shift 2
      ;;
    --dedup-per-cluster)
      DEDUP_PER_CLUSTER="${2:-}"
      shift 2
      ;;
    --dedup-corr-threshold)
      DEDUP_CORR_THRESHOLD="${2:-}"
      shift 2
      ;;
    --dedup-sample-size)
      DEDUP_SAMPLE_SIZE="${2:-}"
      shift 2
      ;;
    --dedup-compute-missing)
      DEDUP_COMPUTE_MISSING="true"
      shift
      ;;
    --min-free-gb)
      MIN_FREE_GB="${2:-}"
      shift 2
      ;;
    --warm-cache)
      WARM_CACHE="true"
      shift
      ;;
    --bob)
      BOB_ENABLED="true"
      shift
      ;;
    --bob-libraries)
      BOB_LIBRARIES="${2:-}"
      shift 2
      ;;
    --bob-top)
      BOB_TOP="${2:-}"
      shift 2
      ;;
    --bob-metric)
      BOB_METRIC="${2:-}"
      shift 2
      ;;
    --bob-grade)
      BOB_GRADE_MODE="${2:-}"
      shift 2
      ;;
    --log-file)
      CUSTOM_LOG_FILE="${2:-}"
      shift 2
      ;;
    --interactive)
      INTERACTIVE="true"
      shift
      ;;
    --view-results)
      VIEW_RESULTS_ONLY="true"
      shift
      ;;
    --view-pick)
      VIEW_PICK="${2:-}"
      shift 2
      ;;
    --view-latest)
      VIEW_LATEST="${2:-}"
      shift 2
      ;;
    --view-result-dir)
      VIEW_RESULT_DIR="${2:-}"
      shift 2
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

if [[ "$VIEW_RESULTS_ONLY" == "true" ]]; then
  run_view_results
  exit $?
fi

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

resolve_quality_min() {
  local raw="$1"
  local mode="$2"
  local v
  v="$(normalize_lower "$raw")"
  if [[ "$v" == "auto" ]]; then
    if [[ "$mode" == "limited" ]]; then
      echo "high"
    else
      echo "off"
    fi
    return 0
  fi
  echo "$v"
}

QUALITY_MIN="$(resolve_quality_min "$QUALITY_MIN_SOURCE" "$MODE")"

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

validate_positive_int() {
  local raw="$1"
  [[ "$raw" =~ ^[0-9]+$ ]] && [[ "$raw" -gt 0 ]]
}

validate_quality_min() {
  local raw="$1"
  local v
  v="$(normalize_lower "$raw")"
  case "$v" in
    off|low|medium|high|auto) return 0 ;;
    *) return 1 ;;
  esac
}

validate_bob_metric() {
  local raw="$1"
  local v
  v="$(normalize_lower "$raw")"
  case "$v" in
    auto|information_ratio|rank_ic|ic|annualized_return) return 0 ;;
    *) return 1 ;;
  esac
}

validate_bob_grade_mode() {
  local raw="$1"
  local v
  v="$(normalize_lower "$raw")"
  case "$v" in
    s|sa|all) return 0 ;;
    *) return 1 ;;
  esac
}

TARGET_MODE="single"
if [[ "$BOB_ENABLED" == "true" ]]; then
  TARGET_MODE="bob"
fi

if [[ "$INTERACTIVE" == "true" ]]; then
  echo "== QuantaAlpha Backtest Quick Start =="
  echo "Step 1/1: choose target (single experiment library or BOB)"
  echo

  shopt -s nullglob
  LIB_PATHS=( "$PROJECT_ROOT"/data/factorlib/*.json )
  shopt -u nullglob
  if [[ "${#LIB_PATHS[@]}" -gt 0 ]]; then
    SORTED_LIB_PATHS=()
    while IFS= read -r line; do
      SORTED_LIB_PATHS+=( "$line" )
    done < <(printf '%s\n' "${LIB_PATHS[@]}" | sort -r)
    LIB_PATHS=( "${SORTED_LIB_PATHS[@]}" )
  fi

  idx=1
  for p in "${LIB_PATHS[@]}"; do
    echo "  $idx) [EXP] $(basename "$p")"
    ((idx++))
  done

  bob_idx="$idx"
  echo "  $bob_idx) [BOB] aggregate libraries (defaults: grade=sa, top=50)"
  view_idx="$((bob_idx + 1))"
  echo "  $view_idx) [VIEW] horizontal compare existing result files"
  echo

  default_pick="$view_idx"
  if [[ "${#LIB_PATHS[@]}" -gt 0 ]]; then
    default_pick="1"
  fi

  read -r -p "Select target [${default_pick}]: " pick
  pick="${pick:-$default_pick}"
  pick_lc="$(normalize_lower "$pick")"

  if [[ "$pick_lc" == "view" || "$pick_lc" == "v" || "$pick_lc" == "compare" || "$pick" == "$view_idx" ]]; then
    run_view_results
    exit $?
  elif [[ "$pick_lc" == "bob" || "$pick_lc" == "b" || "$pick" == "$bob_idx" ]]; then
    TARGET_MODE="bob"
    BOB_ENABLED="true"
    LIBRARY=""
    if [[ -z "$BOB_LIBRARIES" ]]; then
      BOB_LIBRARIES="data/factorlib/all_factors_library*.json"
    fi
    if [[ -z "$BOB_GRADE_MODE" ]]; then
      BOB_GRADE_MODE="sa"
    fi
    if [[ -z "$BOB_TOP" ]]; then
      BOB_TOP="50"
    fi
  elif [[ "$pick" =~ ^[0-9]+$ ]] && [[ "$pick" -ge 1 ]] && [[ "$pick" -le "${#LIB_PATHS[@]}" ]]; then
    TARGET_MODE="single"
    BOB_ENABLED="false"
    LIBRARY="${LIB_PATHS[$((pick-1))]}"
  else
    TARGET_MODE="single"
    BOB_ENABLED="false"
    LIBRARY="$pick"
  fi

  # Keep everything else on defaults in interactive quick-start mode.
  if [[ "$FACTOR_SOURCE" != "custom" && "$FACTOR_SOURCE" != "combined" ]]; then
    FACTOR_SOURCE="custom"
  fi
  if [[ "$MODE" != "performance" && "$MODE" != "limited" ]]; then
    MODE="limited"
  fi
  QUALITY_MIN="$(resolve_quality_min "$QUALITY_MIN_SOURCE" "$MODE")"
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
  if ! validate_max_factors "$MAX_FACTORS_OVERRIDE"; then
    MAX_FACTORS_OVERRIDE="default"
  fi

  echo
  echo "Quick summary (auto-start, no confirm):"
  echo "  target=$TARGET_MODE"
  echo "  library=$LIBRARY"
  echo "  bob_libraries=$BOB_LIBRARIES"
  echo "  bob_grade=$BOB_GRADE_MODE"
  echo "  bob_top=$BOB_TOP"
  echo "  mode=$MODE"
  echo "  factor_source=$FACTOR_SOURCE"
  echo "  max_factors=$MAX_FACTORS_OVERRIDE"
  echo "  corr_dedup=$CORR_DEDUP dedup_topn_effective=${DEDUP_TOPN_EFFECTIVE:-${DEDUP_TOPN:-auto}} dedup_per_cluster=$DEDUP_PER_CLUSTER"
  echo "  warm_cache=$WARM_CACHE"
  echo "  quality_min=$QUALITY_MIN"
fi

if [[ "$BOB_ENABLED" != "true" && -z "$LIBRARY" ]]; then
  echo "Error: --library is required (or run with --interactive)"
  usage
  exit 1
fi
if [[ "$BOB_ENABLED" == "true" && -z "$LIBRARY" && -z "$BOB_LIBRARIES" ]]; then
  echo "Error: BOB requires --library or --bob-libraries"
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

if ! validate_quality_min "$QUALITY_MIN"; then
  echo "Error: BACKTEST_MIN_QUALITY must be one of auto/off/low/medium/high"
  exit 1
fi

if [[ "$CORR_DEDUP" == "true" ]]; then
  if [[ "$FACTOR_SOURCE" != "custom" ]]; then
    echo "Error: --corr-dedup currently supports --factor-source custom only (got '$FACTOR_SOURCE')"
    exit 1
  fi
  if [[ -n "$DEDUP_TOPN" ]] && ! validate_positive_int "$DEDUP_TOPN"; then
    echo "Error: --dedup-topn must be a positive integer"
    exit 1
  fi
  if ! validate_positive_int "$DEDUP_PER_CLUSTER"; then
    echo "Error: --dedup-per-cluster must be a positive integer"
    exit 1
  fi
  if ! validate_positive_int "$DEDUP_SAMPLE_SIZE"; then
    echo "Error: --dedup-sample-size must be a positive integer"
    exit 1
  fi
fi

if [[ "$BOB_ENABLED" == "true" ]]; then
  if ! [[ "$BOB_TOP" =~ ^[0-9]+$ ]] || [[ "$BOB_TOP" -le 0 ]]; then
    echo "Error: --bob-top must be a positive integer"
    exit 1
  fi
  BOB_METRIC="$(normalize_lower "$BOB_METRIC")"
  if ! validate_bob_metric "$BOB_METRIC"; then
    echo "Error: --bob-metric must be one of auto/information_ratio/rank_ic/ic/annualized_return"
    exit 1
  fi
  BOB_GRADE_MODE="$(normalize_lower "$BOB_GRADE_MODE")"
  if ! validate_bob_grade_mode "$BOB_GRADE_MODE"; then
    echo "Error: --bob-grade must be one of s/sa/all"
    exit 1
  fi
  if [[ "$FACTOR_SOURCE" != "custom" ]]; then
    echo "Error: BOB currently supports --factor-source custom only"
    exit 1
  fi
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
TMP_FILTERED_LIBRARY_PATH=""
TMP_DIVERSE_LIBRARY_PATH=""
TMP_DIVERSE_REPORT_PATH=""
TMP_BOB_LIBRARY_PATH=""
TMP_BOB_REPORT_PATH=""
CMD_PID=""
TEE_PID=""
LOG_PIPE=""
LOG_FILE=""
PID_FILE=""

cleanup_runtime() {
  trap - TERM INT HUP EXIT
  if [[ -n "$TMP_CONFIG_PATH" && -f "$TMP_CONFIG_PATH" ]]; then
    rm -f "$TMP_CONFIG_PATH" 2>/dev/null || true
  fi
  if [[ -n "$TMP_FILTERED_LIBRARY_PATH" && -f "$TMP_FILTERED_LIBRARY_PATH" ]]; then
    rm -f "$TMP_FILTERED_LIBRARY_PATH" 2>/dev/null || true
  fi
  if [[ -n "$TMP_DIVERSE_LIBRARY_PATH" && -f "$TMP_DIVERSE_LIBRARY_PATH" ]]; then
    rm -f "$TMP_DIVERSE_LIBRARY_PATH" 2>/dev/null || true
  fi
  if [[ -n "$TMP_DIVERSE_REPORT_PATH" && -f "$TMP_DIVERSE_REPORT_PATH" ]]; then
    rm -f "$TMP_DIVERSE_REPORT_PATH" 2>/dev/null || true
  fi
  if [[ -n "$TMP_BOB_LIBRARY_PATH" && -f "$TMP_BOB_LIBRARY_PATH" ]]; then
    rm -f "$TMP_BOB_LIBRARY_PATH" 2>/dev/null || true
  fi
  if [[ -n "$TMP_BOB_REPORT_PATH" && -f "$TMP_BOB_REPORT_PATH" ]]; then
    rm -f "$TMP_BOB_REPORT_PATH" 2>/dev/null || true
  fi
  if [[ -n "$LOG_PIPE" && -p "$LOG_PIPE" ]]; then
    rm -f "$LOG_PIPE" 2>/dev/null || true
  fi
  if [[ -n "$TEE_PID" ]] && kill -0 "$TEE_PID" 2>/dev/null; then
    kill "$TEE_PID" 2>/dev/null || true
  fi
}

trap cleanup_runtime EXIT

MAX_FACTORS_EFFECTIVE="$(normalize_lower "$MAX_FACTORS_OVERRIDE")"
if [[ "$MAX_FACTORS_EFFECTIVE" != "default" ]]; then
  TMP_CONFIG_PATH="$(mktemp "/tmp/quantaalpha_backtest_cfg_XXXXXX")"
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

if [[ -f "$PROJECT_ROOT/scripts/preflight_check.py" ]]; then
  "$PYTHON_BIN" "$PROJECT_ROOT/scripts/preflight_check.py" backtest \
    --config "$RUN_CONFIG_PATH" \
    --mode "$MODE" \
    --factor-source "$FACTOR_SOURCE" || true
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

LIB_PATH=""
if [[ "$BOB_ENABLED" == "true" ]]; then
  BOB_SPEC="$BOB_LIBRARIES"
  if [[ -z "$BOB_SPEC" ]]; then
    BOB_SPEC="$LIBRARY"
  fi
  if [[ -z "$BOB_SPEC" ]]; then
    echo "Error: empty BOB libraries spec"
    exit 1
  fi
  TMP_BOB_LIBRARY_PATH="$(mktemp "/tmp/quantaalpha_factorlib_bob_XXXXXX")"
  TMP_BOB_REPORT_PATH="$(mktemp "/tmp/quantaalpha_factorlib_bob_report_XXXXXX")"
  BOB_SUMMARY="$("$PYTHON_BIN" - "$PROJECT_ROOT" "$BOB_SPEC" "$TMP_BOB_LIBRARY_PATH" "$BOB_TOP" "$BOB_METRIC" "$BOB_GRADE_MODE" "$TMP_BOB_REPORT_PATH" <<'PY'
import copy
import glob
import hashlib
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(sys.argv[1]).resolve()
spec = str(sys.argv[2]).strip()
out_path = Path(sys.argv[3])
top_n = int(sys.argv[4])
metric = str(sys.argv[5]).strip().lower()
grade_mode = str(sys.argv[6]).strip().lower()
report_path = Path(sys.argv[7])

def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))

def pick_numeric(bt, keys_exact=(), key_contains=()):
    if not isinstance(bt, dict):
        return None
    for k in keys_exact:
        if k in bt and is_number(bt[k]):
            return float(bt[k])
    for k, v in bt.items():
        ks = str(k).lower()
        if any(token in ks for token in key_contains) and is_number(v):
            return float(v)
    return None

def get_metric(bt, name):
    if name == "information_ratio":
        return pick_numeric(
            bt,
            keys_exact=(
                "1day.excess_return_without_cost.information_ratio",
                "1day.excess_return_with_cost.information_ratio",
            ),
            key_contains=("information_ratio",),
        )
    if name == "rank_ic":
        if not isinstance(bt, dict):
            return None
        exact = {"rank ic", "rankic", "rank_ic"}
        for k, v in bt.items():
            ks = str(k).strip().lower()
            if ks in exact and is_number(v):
                return float(v)
        for k, v in bt.items():
            ks = str(k).strip().lower()
            if ("rank ic" in ks or "rank_ic" in ks) and "ir" not in ks and is_number(v):
                return float(v)
        return None
    if name == "ic":
        if not isinstance(bt, dict):
            return None
        for k, v in bt.items():
            ks = str(k).strip().lower()
            if ks in {"ic", "1day.ic"} and is_number(v):
                return float(v)
        for k, v in bt.items():
            ks = str(k).strip().lower()
            if ks.endswith(".ic") and "rank" not in ks and "ir" not in ks and is_number(v):
                return float(v)
        return None
    if name == "annualized_return":
        return pick_numeric(
            bt,
            keys_exact=(
                "1day.excess_return_without_cost.annualized_return",
                "1day.excess_return_with_cost.annualized_return",
                "annualized_return",
            ),
            key_contains=("annualized_return",),
        )
    return None

METRIC_PRIORITY = ("information_ratio", "rank_ic", "ic", "annualized_return")

def resolve_metric_name(name, metric_availability):
    if name != "auto":
        return name
    for n in METRIC_PRIORITY:
        if metric_availability.get(n, 0) > 0:
            return n
    return "information_ratio"

def classify_quality(bt):
    ir = get_metric(bt, "information_ratio")
    if ir is None:
        return "medium"
    if ir > 0.5:
        return "high"
    if ir > 0.1:
        return "medium"
    return "low"

def normalize_decision(feedback):
    if not isinstance(feedback, dict):
        return False
    v = feedback.get("decision")
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y", "pass", "accepted"}
    return False

def assign_grade(decision, ir, rank_ic, ic):
    grade = "C"
    if ir is not None:
        if ir >= 1.0:
            grade = "S"
        elif ir >= 0.5:
            grade = "A"
        elif ir >= 0.1:
            grade = "B"
        else:
            grade = "C"
    else:
        proxy = rank_ic if rank_ic is not None else ic
        if proxy is not None:
            if proxy >= 0.10:
                grade = "S"
            elif proxy >= 0.05:
                grade = "A"
            elif proxy >= 0.02:
                grade = "B"
            else:
                grade = "C"
        else:
            grade = "B"

    # Slightly reward factors that pass feedback gate.
    if decision and grade == "B":
        grade = "A"
    return grade

def resolve_token(token):
    token = token.strip()
    if not token:
        return []
    candidates = []
    p = Path(token)
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append(p)
        candidates.append(project_root / token)
        candidates.append(project_root / "data" / "factorlib" / token)
    out = []
    seen = set()
    for c in candidates:
        s = str(c)
        has_glob = any(ch in s for ch in "*?[]")
        matches = []
        if has_glob:
            matches = [Path(x) for x in glob.glob(s)]
        elif c.is_file():
            matches = [c]
        for m in matches:
            r = m.resolve()
            if r.is_file() and str(r) not in seen:
                seen.add(str(r))
                out.append(r)
    return out

tokens = [t.strip() for t in spec.split(",") if t.strip()]
resolved_paths = []
seen_paths = set()
for token in tokens:
    for p in resolve_token(token):
        ps = str(p)
        if ps not in seen_paths:
            seen_paths.add(ps)
            resolved_paths.append(p)

if not resolved_paths:
    raise SystemExit(f"No factor libraries resolved from spec: {spec}")

quality_rank = {"low": 0, "medium": 1, "high": 2}
grade_rank = {"C": 0, "B": 1, "A": 2, "S": 3}
grade_scope = {"s": {"S"}, "sa": {"S", "A"}, "all": {"S", "A", "B", "C"}}
allowed_grades = grade_scope.get(grade_mode, {"S", "A"})
candidates = {}
records = []
metric_availability = {k: 0 for k in METRIC_PRIORITY}
input_total = 0
decision_true = 0

for lib_path in resolved_paths:
    with lib_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    factors = data.get("factors", {}) or {}
    if not isinstance(factors, dict):
        continue
    for factor_id, finfo in factors.items():
        if not isinstance(finfo, dict):
            continue
        input_total += 1
        bt = finfo.get("backtest_results", {}) if isinstance(finfo.get("backtest_results"), dict) else {}
        feedback = finfo.get("feedback", {}) if isinstance(finfo.get("feedback"), dict) else {}
        decision = normalize_decision(feedback)
        if decision:
            decision_true += 1
        q = classify_quality(bt)
        ir = get_metric(bt, "information_ratio")
        rank_ic = get_metric(bt, "rank_ic")
        ic = get_metric(bt, "ic")
        ann = get_metric(bt, "annualized_return")
        metric_values = {
            "information_ratio": ir,
            "rank_ic": rank_ic,
            "ic": ic,
            "annualized_return": ann,
        }
        for metric_name, metric_value in metric_values.items():
            if metric_value is not None:
                metric_availability[metric_name] = metric_availability.get(metric_name, 0) + 1
        grade = assign_grade(decision, ir, rank_ic, ic)
        records.append(
            {
                "factor_id": factor_id,
                "factor_info": finfo,
                "source_library": str(lib_path),
                "decision": bool(decision),
                "quality": q,
                "grade": grade,
                "metrics": metric_values,
            }
        )

metric_resolved = resolve_metric_name(metric, metric_availability)

for rec in records:
    finfo = rec["factor_info"]
    decision = rec["decision"]
    q = rec["quality"]
    grade = rec["grade"]
    metrics = rec["metrics"]
    ir = metrics.get("information_ratio")
    rank_ic = metrics.get("rank_ic")
    ic = metrics.get("ic")
    ann = metrics.get("annualized_return")
    primary = metrics.get(metric_resolved)

    score = (
        1 if decision else 0,
        grade_rank.get(grade, 0),
        quality_rank.get(q, 0),
        primary if primary is not None else -1e18,
        ir if ir is not None else -1e18,
        rank_ic if rank_ic is not None else -1e18,
        ic if ic is not None else -1e18,
        ann if ann is not None else -1e18,
    )

    expr = str(finfo.get("factor_expression") or "").strip()
    if expr:
        dedup_key = hashlib.md5(expr.encode()).hexdigest()
    else:
        dedup_key = str(finfo.get("factor_id") or rec["factor_id"] or finfo.get("factor_name") or "")

    current = candidates.get(dedup_key)
    if current is None or score > current["score"]:
        item = copy.deepcopy(finfo)
        meta = item.get("metadata")
        if not isinstance(meta, dict):
            meta = {}
        meta["bob_source_library"] = rec["source_library"]
        meta["bob_score_metric"] = metric_resolved
        item["metadata"] = meta
        item["quality"] = q
        item["bob_grade"] = grade
        item["bob_score"] = {
            "decision": bool(decision),
            "grade": grade,
            "quality": q,
            "metric": metric_resolved,
            "metric_value": primary,
            "information_ratio": ir,
            "rank_ic": rank_ic,
            "ic": ic,
            "annualized_return": ann,
        }
        candidates[dedup_key] = {"score": score, "factor": item}

grade_counts_candidates = {"S": 0, "A": 0, "B": 0, "C": 0}
for row in candidates.values():
    finfo = row.get("factor", {})
    g = str(finfo.get("bob_grade", "C")).upper()
    if g not in grade_counts_candidates:
        g = "C"
    grade_counts_candidates[g] += 1

filtered_candidates = []
for row in candidates.values():
    finfo = row.get("factor", {})
    g = str(finfo.get("bob_grade", "C")).upper()
    if g in allowed_grades:
        filtered_candidates.append(row)

ranked = sorted(filtered_candidates, key=lambda x: x["score"], reverse=True)
selected = ranked[: max(0, top_n)]

out_factors = {}
used_ids = set()
selected_details = []
selected_grade_counts = {"S": 0, "A": 0, "B": 0, "C": 0}
for idx, row in enumerate(selected, start=1):
    finfo = row["factor"]
    fid = str(finfo.get("factor_id") or "").strip()
    if not fid:
        expr = str(finfo.get("factor_expression") or "")
        name = str(finfo.get("factor_name") or f"bob_factor_{idx}")
        fid = hashlib.md5(f"{name}_{expr}".encode()).hexdigest()[:16]
    base = fid
    suffix = 1
    while fid in used_ids:
        fid = f"{base}_{suffix}"
        suffix += 1
    used_ids.add(fid)
    finfo["factor_id"] = fid
    out_factors[fid] = finfo
    meta = finfo.get("metadata") if isinstance(finfo.get("metadata"), dict) else {}
    bob_score = finfo.get("bob_score") if isinstance(finfo.get("bob_score"), dict) else {}
    grade = str(bob_score.get("grade") or finfo.get("bob_grade") or "C").upper()
    if grade not in selected_grade_counts:
        grade = "C"
    selected_grade_counts[grade] += 1
    selected_details.append({
        "rank": idx,
        "factor_id": fid,
        "factor_name": finfo.get("factor_name", ""),
        "source_library": meta.get("bob_source_library", ""),
        "experiment_id": meta.get("experiment_id", ""),
        "round_number": meta.get("round_number"),
        "evolution_phase": meta.get("evolution_phase", ""),
        "trajectory_id": meta.get("trajectory_id", ""),
        "score_metric": bob_score.get("metric"),
        "score_value": bob_score.get("metric_value"),
        "grade": grade,
        "quality": bob_score.get("quality"),
        "decision": bob_score.get("decision"),
    })

now = datetime.now().isoformat()
out = {
    "metadata": {
        "created_at": now,
        "last_updated": now,
        "total_factors": len(out_factors),
        "version": "1.0",
        "bob": {
            "enabled": True,
            "top_n": top_n,
            "metric": metric_resolved,
            "metric_requested": metric,
            "metric_resolved": metric_resolved,
            "metric_availability": metric_availability,
            "grade_mode": grade_mode,
            "input_libraries": [str(p) for p in resolved_paths],
            "input_total_factors": input_total,
            "decision_true_count": decision_true,
            "unique_candidates": len(candidates),
            "grade_counts_candidates": grade_counts_candidates,
            "allowed_grades": sorted(list(allowed_grades), reverse=True),
            "candidates_after_grade_filter": len(filtered_candidates),
            "selected_factors": len(out_factors),
            "selected_grade_counts": selected_grade_counts,
        },
    },
    "factors": out_factors,
}

with out_path.open("w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

summary = {
    "input_libraries": [str(p) for p in resolved_paths],
    "input_total_factors": input_total,
    "decision_true_count": decision_true,
    "unique_candidates": len(candidates),
    "selected_factors": len(out_factors),
    "top_n": top_n,
    "metric": metric_resolved,
    "metric_requested": metric,
    "metric_resolved": metric_resolved,
    "metric_availability": metric_availability,
    "grade_mode": grade_mode,
    "grade_counts_candidates": grade_counts_candidates,
    "allowed_grades": sorted(list(allowed_grades), reverse=True),
    "candidates_after_grade_filter": len(filtered_candidates),
    "selected_grade_counts": selected_grade_counts,
    "output_path": str(out_path),
    "report_path": str(report_path),
}

with report_path.open("w", encoding="utf-8") as f:
    json.dump(
        {
            "summary": summary,
            "selected_details": selected_details,
        },
        f,
        ensure_ascii=False,
        indent=2,
    )

print(json.dumps(summary, ensure_ascii=False))
PY
)"
  LIB_PATH="$TMP_BOB_LIBRARY_PATH"
  echo "[BOB] enabled=true metric=$BOB_METRIC top=$BOB_TOP"
  echo "[BOB] summary=$BOB_SUMMARY"
  echo "[BOB] selected_details_report=$TMP_BOB_REPORT_PATH"
  "$PYTHON_BIN" - "$TMP_BOB_REPORT_PATH" <<'PY'
import json
import sys
from pathlib import Path

rp = Path(sys.argv[1])
if not rp.exists():
    print("[BOB] detail report not found")
    raise SystemExit(0)

with rp.open("r", encoding="utf-8") as f:
    data = json.load(f) or {}

rows = data.get("selected_details") or []
if not isinstance(rows, list) or not rows:
    print("[BOB] no selected factor details")
    raise SystemExit(0)

for row in rows:
    if not isinstance(row, dict):
        continue
    rank = row.get("rank")
    name = row.get("factor_name", "")
    fid = row.get("factor_id", "")
    exp_id = row.get("experiment_id", "")
    rnd = row.get("round_number")
    phase = row.get("evolution_phase", "")
    metric = row.get("score_metric", "")
    value = row.get("score_value")
    src = row.get("source_library", "")
    print(
        f"[BOB][Pick {rank}] grade={row.get('grade')} exp={exp_id} round={rnd} phase={phase} "
        f"factor={name} id={fid} metric={metric} value={value} src={src}"
    )
PY
else
  LIB_PATH="$(resolve_library_path "$LIBRARY" || true)"
  if [[ -z "$LIB_PATH" ]]; then
    echo "Error: factor library not found: $LIBRARY"
    echo "Checked: <input>, data/factorlib/<input>, project-root/<input>"
    exit 1
  fi
fi

if [[ "$FACTOR_SOURCE" == "custom" && "$QUALITY_MIN" != "off" ]]; then
  ORIGINAL_LIB_PATH="$LIB_PATH"
  TMP_FILTERED_LIBRARY_PATH="$(mktemp "/tmp/quantaalpha_factorlib_filtered_XXXXXX")"
  FILTER_SUMMARY="$("$PYTHON_BIN" - "$ORIGINAL_LIB_PATH" "$TMP_FILTERED_LIBRARY_PATH" "$QUALITY_MIN" <<'PY'
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
min_quality = str(sys.argv[3]).strip().lower()

quality_rank = {"low": 0, "medium": 1, "high": 2}
threshold = quality_rank.get(min_quality, 2)

with src.open("r", encoding="utf-8") as f:
    data = json.load(f)

factors = data.get("factors", {}) or {}
if not isinstance(factors, dict):
    factors = {}

def classify_quality(backtest_results):
    if not isinstance(backtest_results, dict) or not backtest_results:
        return "low"
    ir = None
    for key in (
        "1day.excess_return_without_cost.information_ratio",
        "1day.excess_return_with_cost.information_ratio",
    ):
        if key in backtest_results and isinstance(backtest_results[key], (int, float)):
            ir = float(backtest_results[key])
            break
    if ir is None:
        for k, v in backtest_results.items():
            if "information_ratio" in str(k).lower() and isinstance(v, (int, float)):
                ir = float(v)
                break
    if ir is None:
        return "medium"
    if ir > 0.5:
        return "high"
    if ir > 0.1:
        return "medium"
    return "low"

kept = {}
quality_counts = {"high": 0, "medium": 0, "low": 0}
kept_counts = {"high": 0, "medium": 0, "low": 0}

for factor_id, factor_info in factors.items():
    if not isinstance(factor_info, dict):
        continue
    q = classify_quality(factor_info.get("backtest_results", {}))
    quality_counts[q] += 1
    factor_info["quality"] = q
    if quality_rank[q] >= threshold:
        kept[factor_id] = factor_info
        kept_counts[q] += 1

meta = data.get("metadata", {})
if not isinstance(meta, dict):
    meta = {}
meta["quality_prefilter"] = {
    "enabled": True,
    "min_quality": min_quality,
    "input_total": len(factors),
    "kept_total": len(kept),
    "input_quality_counts": quality_counts,
    "kept_quality_counts": kept_counts,
}
meta["total_factors"] = len(kept)

out = {"metadata": meta, "factors": kept}
with dst.open("w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(json.dumps({
    "input_total": len(factors),
    "kept_total": len(kept),
    "min_quality": min_quality,
    "input_quality_counts": quality_counts,
    "kept_quality_counts": kept_counts,
}, ensure_ascii=False))
PY
)"

  FILTER_KEPT="$(echo "$FILTER_SUMMARY" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d.get('kept_total', 0))")"
  if [[ "$FILTER_KEPT" -gt 0 ]]; then
    LIB_PATH="$TMP_FILTERED_LIBRARY_PATH"
    echo "[Quality] min=${QUALITY_MIN}: $FILTER_SUMMARY"
    echo "[Quality] using prefiltered library: $LIB_PATH"
  else
    echo "[Quality] min=${QUALITY_MIN}: $FILTER_SUMMARY"
    echo "[Quality] prefilter kept 0 factors, fallback to original library: $ORIGINAL_LIB_PATH"
    rm -f "$TMP_FILTERED_LIBRARY_PATH" 2>/dev/null || true
    TMP_FILTERED_LIBRARY_PATH=""
    LIB_PATH="$ORIGINAL_LIB_PATH"
  fi
fi

if [[ "$CORR_DEDUP" == "true" ]]; then
  if [[ ! -f "$PROJECT_ROOT/scripts/select_diverse_factors.py" ]]; then
    echo "Error: dedup selector script not found: $PROJECT_ROOT/scripts/select_diverse_factors.py"
    exit 1
  fi

  TOPN_EFFECTIVE="$DEDUP_TOPN"
  if [[ -z "$TOPN_EFFECTIVE" ]]; then
    TOPN_EFFECTIVE="$("$PYTHON_BIN" - "$RUN_CONFIG_PATH" <<'PY'
import sys
from pathlib import Path
import yaml

cfg_path = Path(sys.argv[1])
with cfg_path.open("r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}
fs = cfg.get("factor_source") or {}
custom = fs.get("custom") or {}
mf = custom.get("max_factors")
if mf in (None, "", 0):
    print("")
else:
    try:
        print(int(mf))
    except Exception:
        print("")
PY
)"
  fi

  if [[ -z "$TOPN_EFFECTIVE" ]]; then
    echo "Error: --corr-dedup needs a target topn. Provide --dedup-topn <N> or set config factor_source.custom.max_factors."
    exit 1
  fi
  if ! validate_positive_int "$TOPN_EFFECTIVE"; then
    echo "Error: inferred dedup topn is not a positive integer: '$TOPN_EFFECTIVE'"
    exit 1
  fi
  DEDUP_TOPN_EFFECTIVE="$TOPN_EFFECTIVE"

  if ! "$PYTHON_BIN" - "$DEDUP_CORR_THRESHOLD" <<'PY' >/dev/null 2>&1; then
import sys
try:
    v = float(sys.argv[1])
    raise SystemExit(0 if (0.0 < v < 1.0) else 1)
except Exception:
    raise SystemExit(1)
PY
    echo "Error: --dedup-corr-threshold must be a float in (0,1) (got '$DEDUP_CORR_THRESHOLD')"
    exit 1
  fi

  TMP_DIVERSE_LIBRARY_PATH="$(mktemp "/tmp/quantaalpha_factorlib_diverse_XXXXXX.json")"
  TMP_DIVERSE_REPORT_PATH="$(mktemp "/tmp/quantaalpha_factorlib_diverse_report_XXXXXX.json")"

  DEDUP_ARGS=(
    --library "$LIB_PATH"
    --config "$RUN_CONFIG_PATH"
    --out "$TMP_DIVERSE_LIBRARY_PATH"
    --topn "$TOPN_EFFECTIVE"
    --per-cluster "$DEDUP_PER_CLUSTER"
    --corr-threshold "$DEDUP_CORR_THRESHOLD"
    --sample-size "$DEDUP_SAMPLE_SIZE"
    --report "$TMP_DIVERSE_REPORT_PATH"
  )
  if [[ "$DEDUP_COMPUTE_MISSING" == "true" ]]; then
    DEDUP_ARGS+=(--compute-missing)
  fi

  echo "[Diverse] enabled=true topn=$TOPN_EFFECTIVE per_cluster=$DEDUP_PER_CLUSTER corr_threshold=$DEDUP_CORR_THRESHOLD sample_size=$DEDUP_SAMPLE_SIZE compute_missing=$DEDUP_COMPUTE_MISSING"
  echo "[Diverse] input_library=$LIB_PATH"
  "$PYTHON_BIN" "$PROJECT_ROOT/scripts/select_diverse_factors.py" "${DEDUP_ARGS[@]}"
  echo "[Diverse] report=$TMP_DIVERSE_REPORT_PATH"
  echo "[Diverse] output_library=$TMP_DIVERSE_LIBRARY_PATH"
  LIB_PATH="$TMP_DIVERSE_LIBRARY_PATH"
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

  {
    echo "[Summary] interactive=$INTERACTIVE target=$TARGET_MODE auto_start=true"
    echo "[Summary] library=$LIB_PATH"
    echo "[Summary] mode=$MODE factor_source=$FACTOR_SOURCE quality_min=$QUALITY_MIN max_factors=$MAX_FACTORS_EFFECTIVE"
    echo "[Summary] corr_dedup=$CORR_DEDUP dedup_topn_effective=${DEDUP_TOPN_EFFECTIVE:-${DEDUP_TOPN:-auto}} dedup_per_cluster=$DEDUP_PER_CLUSTER dedup_corr_threshold=$DEDUP_CORR_THRESHOLD dedup_sample_size=$DEDUP_SAMPLE_SIZE"
    echo "[Summary] bob_enabled=$BOB_ENABLED bob_libraries=$BOB_LIBRARIES bob_metric=$BOB_METRIC bob_grade=$BOB_GRADE_MODE bob_top=$BOB_TOP"
    echo "[Summary] warm_cache=$WARM_CACHE skip_uncached=$SKIP_UNCACHED free_disk=${FREE_GB}GB"
  } | tee -a "$LOG_FILE"

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

trap 'on_signal TERM' TERM
trap 'on_signal INT' INT
trap 'on_signal HUP' HUP

echo "[Run] library=$LIB_PATH"
echo "[Run] mode=$MODE"
echo "[Run] factor_source=$FACTOR_SOURCE config=$RUN_CONFIG_PATH (base=$CONFIG_PATH)"
echo "[Run] threads=$THREADS skip_uncached=$SKIP_UNCACHED"
echo "[Run] quality_min=$QUALITY_MIN"
echo "[Run] max_factors=$MAX_FACTORS_EFFECTIVE"
echo "[Run] corr_dedup=$CORR_DEDUP dedup_topn_effective=${DEDUP_TOPN_EFFECTIVE:-${DEDUP_TOPN:-auto}} dedup_per_cluster=$DEDUP_PER_CLUSTER dedup_corr_threshold=$DEDUP_CORR_THRESHOLD dedup_sample_size=$DEDUP_SAMPLE_SIZE compute_missing=$DEDUP_COMPUTE_MISSING"
echo "[Run] bob_enabled=$BOB_ENABLED bob_metric=$BOB_METRIC bob_top=$BOB_TOP bob_grade=$BOB_GRADE_MODE"
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

LOG_PIPE="$(mktemp -u "/tmp/quantaalpha_backtest_${TS}_XXXXXX")"
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
quality_min=$QUALITY_MIN
max_factors=$MAX_FACTORS_EFFECTIVE
corr_dedup=$CORR_DEDUP
dedup_topn_effective=${DEDUP_TOPN_EFFECTIVE:-${DEDUP_TOPN:-}}
dedup_per_cluster=$DEDUP_PER_CLUSTER
dedup_corr_threshold=$DEDUP_CORR_THRESHOLD
dedup_sample_size=$DEDUP_SAMPLE_SIZE
dedup_compute_missing=$DEDUP_COMPUTE_MISSING
bob_enabled=$BOB_ENABLED
bob_libraries=$BOB_LIBRARIES
bob_metric=$BOB_METRIC
bob_top=$BOB_TOP
bob_grade=$BOB_GRADE_MODE
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
