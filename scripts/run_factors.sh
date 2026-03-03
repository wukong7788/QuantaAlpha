#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Error: python3 not found."
  exit 1
fi

run_factor_library_inspector() {
  local action="$1"
  shift
  "$PYTHON_BIN" - "$PROJECT_ROOT" "$action" "$@" <<'PY'
import glob
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

project_root = Path(sys.argv[1]).resolve()
action = sys.argv[2].strip().lower()
patterns = sys.argv[3:]
ids_token = os.environ.get("RUN_FACTORS_IDS", "").strip() or os.environ.get("RUN_FACTORS_DELETE_IDS", "").strip()

paths = []
seen = set()
for pat in patterns:
    for p in glob.glob(pat):
        rp = str(Path(p).resolve())
        if rp not in seen and Path(rp).is_file():
            seen.add(rp)
            paths.append(Path(rp))

def parse_float(v):
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            x = float(v)
            if not math.isfinite(x):
                return None
            return x
        if isinstance(v, str) and v.strip():
            x = float(v)
            if not math.isfinite(x):
                return None
            return x
    except Exception:
        return None
    return None

def pick_metric(bt, keys_exact=(), contains=()):
    if not isinstance(bt, dict):
        return None
    for k in keys_exact:
        x = parse_float(bt.get(k))
        if x is not None:
            return x
    if contains:
        for k, v in bt.items():
            lk = str(k).lower()
            if any(t in lk for t in contains):
                x = parse_float(v)
                if x is not None:
                    return x
    return None

def get_ir(bt):
    return pick_metric(
        bt,
        keys_exact=(
            "1day.excess_return_without_cost.information_ratio",
            "1day.excess_return_with_cost.information_ratio",
        ),
        contains=("information_ratio",),
    )

def classify_quality(bt):
    if not isinstance(bt, dict) or not bt:
        return "low"
    ir = get_ir(bt)
    if ir is None:
        return "medium"
    if ir > 0.5:
        return "high"
    if ir > 0.1:
        return "medium"
    return "low"

def get_arr(bt):
    return pick_metric(
        bt,
        keys_exact=(
            "1day.excess_return_with_cost.annualized_return",
            "1day.excess_return_without_cost.annualized_return",
            "annualized_return",
        ),
        contains=("annualized_return",),
    )

def median(xs):
    xs = [x for x in xs if x is not None and math.isfinite(float(x))]
    if not xs:
        return None
    xs.sort()
    n = len(xs)
    mid = n // 2
    if n % 2 == 1:
        return float(xs[mid])
    return float((xs[mid - 1] + xs[mid]) / 2.0)

def parse_created_at(meta):
    if not isinstance(meta, dict):
        return None
    v = meta.get("created_at") or meta.get("createdAt") or meta.get("created")
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip()
    # Support Zulu time.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def fmt_dt(dt):
    if dt is None:
        return "-"
    try:
        local_dt = dt.astimezone()
    except Exception:
        local_dt = dt
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")

def parse_ids(token):
    token = (token or "").strip()
    if not token:
        return []
    if token.lower() in {"all", "*"}:
        return "__ALL__"
    out = []
    for part in token.split("+"):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except Exception:
            return None
    return out

rows = []
for path in paths:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        continue
    factors = data.get("factors") or {}
    if not isinstance(factors, dict):
        factors = {}
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    created_at_dt = parse_created_at(meta)

    total = len(factors)
    q_counts = {"high": 0, "medium": 0, "low": 0}
    arrs = []
    for finfo in factors.values():
        if not isinstance(finfo, dict):
            continue
        bt = finfo.get("backtest_results") if isinstance(finfo.get("backtest_results"), dict) else {}
        q = classify_quality(bt)
        q_counts[q] += 1
        arrs.append(get_arr(bt))

    arr_p50 = median(arrs)

    try:
        rel = path.resolve().relative_to(project_root)
        rel_str = str(rel)
    except Exception:
        rel_str = str(path)

    rows.append(
        {
            "path": rel_str,
            "mtime": path.stat().st_mtime,
            "created_at_dt": created_at_dt,
            "abs_path": str(path.resolve()),
            "total": total,
            "h": q_counts["high"],
            "m": q_counts["medium"],
            "l": q_counts["low"],
            "arr_p50": arr_p50,
        }
    )

rows.sort(key=lambda r: r["mtime"], reverse=True)

if not rows:
    print("No factor libraries found (all_factors_library*.json).")
    raise SystemExit(0)

def fmt_arr(x):
    if x is None:
        return "-"
    return f"{x:.6f}"

id_width = max(len("id"), len(str(len(rows))))
headers = ["id", "created_at", "file", "n", "H/M/L", "ARR(p50)"]
created_at_width = max(len(headers[1]), len("YYYY-MM-DD HH:MM:SS"))
file_width = max(len(headers[2]), max(len(r["path"]) for r in rows))
n_width = max(len(headers[3]), max(len(str(r["total"])) for r in rows))
hml_width = len(headers[4])
arr_width = len(headers[5])

def print_table(rows):
    print(
        f"{headers[0]:>{id_width}}  "
        f"{headers[1]:<{created_at_width}}  "
        f"{headers[2]:<{file_width}}  "
        f"{headers[3]:>{n_width}}  "
        f"{headers[4]:>7}  "
        f"{headers[5]:>10}"
    )
    print("-" * (id_width + created_at_width + file_width + n_width + 7 + 10 + 10))
    for i, r in enumerate(rows, start=1):
        hml = f"{r['h']}/{r['m']}/{r['l']}"
        created_at_out = fmt_dt(r.get("created_at_dt"))
        print(
            f"{i:>{id_width}}  "
            f"{created_at_out:<{created_at_width}}  "
            f"{r['path']:<{file_width}}  "
            f"{r['total']:>{n_width}}  "
            f"{hml:>7}  "
            f"{fmt_arr(r['arr_p50']):>10}"
        )

allowed_delete_dirs = {
    project_root,
    project_root / "data" / "factorlib",
    project_root / "data" / "factorlib" / "selected",
    project_root / "data" / "results" / "backtest_v2_results",
}

def is_allowed_delete_file(ap: Path) -> bool:
    name = ap.name
    if not name.startswith("all_factors_library"):
        return False
    if name.endswith(".json"):
        return True
    if name.endswith("_backtest_metrics.json"):
        return True
    if name.endswith("_cumulative_excess.csv"):
        return True
    return False

def validate_delete_paths(paths_to_delete):
    for ap in paths_to_delete:
        ap = Path(ap).resolve()
        parent = ap.parent.resolve()
        if parent not in allowed_delete_dirs:
            raise ValueError(f"Refuse to delete outside allowed dirs: {ap}")
        if not is_allowed_delete_file(ap):
            raise ValueError(f"Refuse to delete non-target file: {ap.name}")

def expand_bundle_for_library_file(ap: Path):
    ap = ap.resolve()
    name = ap.name
    if not name.endswith(".json") or not name.startswith("all_factors_library"):
        return []

    stem = name[:-5]
    if stem.endswith("_report"):
        base_stem = stem[: -len("_report")]
    else:
        base_stem = stem

    candidates = []

    def add_if_exists(p: Path):
        if p.is_file():
            candidates.append(p.resolve())

    # 1) Pair in the same directory: base + report
    add_if_exists(ap.parent / f"{base_stem}.json")
    add_if_exists(ap.parent / f"{base_stem}_report.json")

    # 2) Copies under selected/
    selected_dir = project_root / "data" / "factorlib" / "selected"
    add_if_exists(selected_dir / f"{base_stem}.json")
    add_if_exists(selected_dir / f"{base_stem}_report.json")

    # 3) Offline backtest results (both legacy and timestamped)
    bt_dir = project_root / "data" / "results" / "backtest_v2_results"
    for pat in (
        f"{base_stem}_backtest_metrics.json",
        f"{base_stem}_cumulative_excess.csv",
        f"{base_stem}_n*_backtest_metrics.json",
        f"{base_stem}_n*_cumulative_excess.csv",
    ):
        for m in bt_dir.glob(pat):
            if m.is_file():
                candidates.append(m.resolve())

    # Ensure deterministic order.
    uniq = []
    seen_p = set()
    for p in sorted(candidates, key=lambda x: str(x)):
        sp = str(p)
        if sp not in seen_p:
            seen_p.add(sp)
            uniq.append(p)
    return uniq

if action in {"list", "ls"}:
    print_table(rows)
    raise SystemExit(0)

ids = parse_ids(ids_token)
if ids is None:
    print("Error: invalid ids. Use `+` to join integers, e.g. 1+3+5.")
    raise SystemExit(2)
if ids == "__ALL__":
    if action in {"resolve", "paths"}:
        ids = list(range(1, len(rows) + 1))
    else:
        print("Error: 'all' is only supported for merge selection.")
        raise SystemExit(2)
if not ids:
    print("Error: empty ids.")
    raise SystemExit(2)

targets = []
max_id = len(rows)
bad = [i for i in ids if i < 1 or i > max_id]
if bad:
    print(f"Error: invalid ids: {bad}. Valid range: 1..{max_id}.")
    raise SystemExit(2)
for i in ids:
    targets.append(rows[i - 1])

if action in {"resolve", "paths"}:
    for r in targets:
        print(r["abs_path"])
    raise SystemExit(0)

bundle_paths = []
for r in targets:
    ap = Path(r["abs_path"]).resolve()
    # Always include the selected file itself, even if it's a weird corner case.
    if ap.is_file():
        bundle_paths.append(ap)
    bundle_paths.extend(expand_bundle_for_library_file(ap))

uniq_bundle = []
seen_bundle = set()
for p in bundle_paths:
    sp = str(Path(p).resolve())
    if sp not in seen_bundle:
        seen_bundle.add(sp)
        uniq_bundle.append(Path(sp))

validate_delete_paths(uniq_bundle)
uniq_bundle_sorted = sorted(uniq_bundle, key=lambda p: str(p))

if action in {"preview-delete", "preview"}:
    print("Will delete:")
    for p in uniq_bundle_sorted:
        try:
            rel = p.relative_to(project_root)
            print(f"  {rel}")
        except Exception:
            print(f"  {p}")
    raise SystemExit(0)

if action in {"delete", "rm"}:
    deleted = 0
    for p in uniq_bundle_sorted:
        try:
            p.unlink()
            deleted += 1
        except FileNotFoundError:
            try:
                rel = p.relative_to(project_root)
                print(f"Skip (missing): {rel}")
            except Exception:
                print(f"Skip (missing): {p}")
        except Exception as e:
            try:
                rel = p.relative_to(project_root)
                print(f"Error deleting {rel}: {e}")
            except Exception:
                print(f"Error deleting {p}: {e}")
            raise SystemExit(1)
    print(f"Deleted {deleted} file(s).")
    raise SystemExit(0)

print(f"Error: unknown action '{action}'.")
raise SystemExit(2)
PY
}

list_factor_libraries() {
  local patterns=(
    "$PROJECT_ROOT/data/factorlib/all_factors_library*.json"
    "$PROJECT_ROOT/all_factors_library*.json"
  )
  run_factor_library_inspector list "${patterns[@]}"
}

resolve_factor_library_paths_by_ids() {
  local ids="$1"
  local patterns=(
    "$PROJECT_ROOT/data/factorlib/all_factors_library*.json"
    "$PROJECT_ROOT/all_factors_library*.json"
  )
  RUN_FACTORS_IDS="$ids" run_factor_library_inspector resolve "${patterns[@]}"
}

delete_factor_libraries() {
  local patterns=(
    "$PROJECT_ROOT/data/factorlib/all_factors_library*.json"
    "$PROJECT_ROOT/all_factors_library*.json"
  )

  echo "Current libraries:"
  list_factor_libraries
  echo
  read -r -p "Enter ids to delete (use + to join, e.g. 1+3+5): " delete_ids
  delete_ids="$(echo "${delete_ids:-}" | tr -d '[:space:]')"
  if [[ -z "$delete_ids" ]]; then
    echo "Error: empty ids."
    return 2
  fi

  echo
  RUN_FACTORS_IDS="$delete_ids" run_factor_library_inspector preview-delete "${patterns[@]}"

  echo
  read -r -p "Confirm delete? [y/N]: " confirm
  confirm="$(echo "${confirm:-}" | tr '[:upper:]' '[:lower:]')"
  if [[ "$confirm" != "y" && "$confirm" != "yes" ]]; then
    echo "Canceled."
    return 0
  fi

  echo
  RUN_FACTORS_IDS="$delete_ids" run_factor_library_inspector delete "${patterns[@]}"
}

merge_factor_libraries_by_ids() {
  local patterns=(
    "$PROJECT_ROOT/data/factorlib/all_factors_library*.json"
    "$PROJECT_ROOT/all_factors_library*.json"
  )

  echo "Current libraries:"
  list_factor_libraries
  echo
  read -r -p "Enter ids to merge (use + to join, e.g. 1+2, or all): " merge_ids
  merge_ids="$(echo "${merge_ids:-}" | tr -d '[:space:]')"
  if [[ -z "$merge_ids" ]]; then
    echo "Error: empty ids."
    return 2
  fi

  local selected_paths=()
  local line
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    selected_paths+=("$line")
  done < <(resolve_factor_library_paths_by_ids "$merge_ids")
  if [[ "${#selected_paths[@]}" -eq 0 ]]; then
    echo "Error: no libraries resolved from ids: $merge_ids"
    return 2
  fi

  echo
  echo "Selected libraries (${#selected_paths[@]}):"
  local p rel
  for p in "${selected_paths[@]}"; do
    rel="$p"
    if [[ "$p" == "$PROJECT_ROOT/"* ]]; then
      rel="${p#"$PROJECT_ROOT"/}"
    fi
    echo "  - $rel"
  done

  local out_prefix
  read -r -p "Output name prefix [data/factorlib/merged/factor_pool_selected]: " out_prefix
  out_prefix="${out_prefix:-data/factorlib/merged/factor_pool_selected}"
  out_prefix="$(echo "$out_prefix" | xargs)"
  out_prefix="${out_prefix%.json}"

  local zoo_method
  read -r -p "Zoo method [ast|norm|both|none] (default: ast): " zoo_method
  zoo_method="$(echo "${zoo_method:-ast}" | tr '[:upper:]' '[:lower:]' | xargs)"
  case "$zoo_method" in
    ast|norm|both|none) ;;
    *)
      echo "Error: invalid zoo method '$zoo_method' (choose ast|norm|both|none)."
      return 2
      ;;
  esac

  local skip_unparsable="y"
  if [[ "$zoo_method" == "ast" || "$zoo_method" == "both" ]]; then
    read -r -p "Skip unparsable AST expressions? [Y/n]: " skip_unparsable
    skip_unparsable="$(echo "${skip_unparsable:-y}" | tr '[:upper:]' '[:lower:]' | xargs)"
  fi

  local merge_ts
  merge_ts="$(date "+%Y%m%d_%H%M%S")"

  local tmp_out_path="${out_prefix}_tmp_${merge_ts}.json"
  local tmp_out_abs="$tmp_out_path"
  if [[ "$tmp_out_abs" != /* ]]; then
    tmp_out_abs="$PROJECT_ROOT/$tmp_out_abs"
  fi

  local libraries_spec
  libraries_spec="$(IFS=,; echo "${selected_paths[*]}")"

  local cmd=(
    "$PYTHON_BIN" "scripts/factor_filtering/merge_factor_libraries.py"
    "--libraries" "$libraries_spec"
    "--out" "$tmp_out_path"
    "--zoo-method" "$zoo_method"
  )
  if [[ "$zoo_method" == "ast" || "$zoo_method" == "both" ]]; then
    if [[ "$skip_unparsable" != "n" && "$skip_unparsable" != "no" ]]; then
      cmd+=("--skip-unparsable")
    fi
  fi

  echo
  echo "Run merge command:"
  printf '  %q' "${cmd[@]}"
  echo
  echo
  read -r -p "Proceed? [Y/n]: " confirm
  confirm="$(echo "${confirm:-y}" | tr '[:upper:]' '[:lower:]' | xargs)"
  if [[ "$confirm" == "n" || "$confirm" == "no" ]]; then
    echo "Canceled."
    return 0
  fi

  echo
  "${cmd[@]}"

  local merged_n
  merged_n="$("$PYTHON_BIN" - "$tmp_out_abs" <<'PY'
import json, sys
p = sys.argv[1]
with open(p, "r", encoding="utf-8") as f:
    data = json.load(f) or {}
factors = data.get("factors") if isinstance(data, dict) else {}
print(len(factors) if isinstance(factors, dict) else 0)
PY
)"
  if [[ ! "$merged_n" =~ ^[0-9]+$ ]]; then
    echo "Error: failed to read merged factor count."
    return 1
  fi

  local final_out_path="${out_prefix}_n${merged_n}_${merge_ts}.json"
  local final_out_abs="$final_out_path"
  if [[ "$final_out_abs" != /* ]]; then
    final_out_abs="$PROJECT_ROOT/$final_out_abs"
  fi

  mv "$tmp_out_abs" "$final_out_abs"

  local final_ast_csv="" final_norm_csv=""
  if [[ "$zoo_method" == "ast" ]]; then
    local tmp_csv="${tmp_out_abs%.json}_zoo.csv"
    local tmp_json="${tmp_out_abs%.json}_zoo.json"
    final_ast_csv="${final_out_abs%.json}_zoo.csv"
    local final_json="${final_out_abs%.json}_zoo.json"
    [[ -f "$tmp_csv" ]] && mv "$tmp_csv" "$final_ast_csv"
    [[ -f "$tmp_json" ]] && mv "$tmp_json" "$final_json"
  elif [[ "$zoo_method" == "norm" ]]; then
    local tmp_csv="${tmp_out_abs%.json}_zoo.csv"
    local tmp_json="${tmp_out_abs%.json}_zoo.json"
    final_norm_csv="${final_out_abs%.json}_zoo.csv"
    local final_json="${final_out_abs%.json}_zoo.json"
    [[ -f "$tmp_csv" ]] && mv "$tmp_csv" "$final_norm_csv"
    [[ -f "$tmp_json" ]] && mv "$tmp_json" "$final_json"
  elif [[ "$zoo_method" == "both" ]]; then
    local tmp_norm_csv="${tmp_out_abs%.json}_zoo_norm.csv"
    local tmp_norm_json="${tmp_out_abs%.json}_zoo_norm.json"
    local tmp_ast_csv="${tmp_out_abs%.json}_zoo_ast.csv"
    local tmp_ast_json="${tmp_out_abs%.json}_zoo_ast.json"
    final_norm_csv="${final_out_abs%.json}_zoo_norm.csv"
    final_ast_csv="${final_out_abs%.json}_zoo_ast.csv"
    local final_norm_json="${final_out_abs%.json}_zoo_norm.json"
    local final_ast_json="${final_out_abs%.json}_zoo_ast.json"
    [[ -f "$tmp_norm_csv" ]] && mv "$tmp_norm_csv" "$final_norm_csv"
    [[ -f "$tmp_norm_json" ]] && mv "$tmp_norm_json" "$final_norm_json"
    [[ -f "$tmp_ast_csv" ]] && mv "$tmp_ast_csv" "$final_ast_csv"
    [[ -f "$tmp_ast_json" ]] && mv "$tmp_ast_json" "$final_ast_json"
  fi

  echo
  echo "Final merged file:"
  local final_rel="$final_out_abs"
  if [[ "$final_out_abs" == "$PROJECT_ROOT/"* ]]; then
    final_rel="${final_out_abs#"$PROJECT_ROOT"/}"
  fi
  echo "  $final_rel"

  echo
  echo "Merged output summary:"
  run_factor_library_inspector list "$final_out_abs"

  echo
  if [[ -n "$final_ast_csv" ]]; then
    local ast_rel="$final_ast_csv"
    if [[ "$final_ast_csv" == "$PROJECT_ROOT/"* ]]; then
      ast_rel="${final_ast_csv#"$PROJECT_ROOT"/}"
    fi
    echo "Use AST zoo in current shell:"
    echo "  export FACTOR_CoSTEER_FACTOR_ZOO_PATH=$ast_rel"
  fi
  if [[ -n "$final_norm_csv" ]]; then
    local norm_rel="$final_norm_csv"
    if [[ "$final_norm_csv" == "$PROJECT_ROOT/"* ]]; then
      norm_rel="${final_norm_csv#"$PROJECT_ROOT"/}"
    fi
    echo "Use norm zoo in current shell:"
    echo "  export FACTOR_CoSTEER_FACTOR_ZOO_PATH=$norm_rel"
  fi
}

repair_factor_cache_by_ids() {
  local patterns=(
    "$PROJECT_ROOT/data/factorlib/all_factors_library*.json"
    "$PROJECT_ROOT/all_factors_library*.json"
  )

  echo "Current libraries:"
  list_factor_libraries
  echo
  read -r -p "Enter library ids to repair (use + to join, e.g. 1+3): " repair_ids
  repair_ids="$(echo "${repair_ids:-}" | tr -d '[:space:]')"
  if [[ -z "$repair_ids" ]]; then
    echo "Error: empty ids."
    return 2
  fi

  local selected_paths=()
  local line
  while IFS= read -r line; do
    [[ -n "$line" ]] && selected_paths+=("$line")
  done < <(resolve_factor_library_paths_by_ids "$repair_ids")

  if [[ "${#selected_paths[@]}" -eq 0 ]]; then
    echo "Error: no libraries resolved from ids: $repair_ids"
    return 2
  fi

  local config_path cache_dir max_factors warm_cache delete_invalid recompute_missing recompute_invalid
  echo "Note:"
  echo "  - 这里的 backtest config 用于定义“校验/重算缓存”时的取数口径（时间区间/市场/股票池）。"
  echo "  - 若要与挖掘阶段（2021 验证集打分口径）一致，推荐：configs/backtest_2021_validate.yaml"
  echo "  - 若要服务于后续统一过滤/长期离线回测（长窗口复用缓存），推荐：configs/backtest.yaml"
  echo "  - 时间区间越短通常越快、占用磁盘更少，但可能不足以支撑后续阶段。"
  echo "  - Cache dir 是“自定义因子值（日期×标的）”的 MD5 缓存目录（不是 backtest_metrics 输出目录）。"
  echo "    - 常规默认：data/results/factor_cache"
  echo "    - 若你经常切不同口径（例如只算 2021 / 全量 2016-2025），建议分目录：data/results/factor_cache_2021、data/results/factor_cache_full"
  echo "  - 交互输入支持快捷选项：1=全量(backtest.yaml)，2=挖掘期口径(backtest_2021_validate.yaml)"
  echo
  while true; do
    local config_pick=""
    read -r -p "Backtest config [1/2 或路径] (default: 1): " config_pick
    config_pick="$(echo "${config_pick:-1}" | xargs)"
    case "$config_pick" in
      1) config_path="configs/backtest.yaml" ;;
      2) config_path="configs/backtest_2021_validate.yaml" ;;
      q|quit|exit)
        echo "Canceled."
        return 0
        ;;
      *)
        config_path="$config_pick"
        ;;
    esac

    # Convenience: allow typing just "backtest.yaml" -> "configs/backtest.yaml"
    if [[ "$config_path" != /* && "$config_path" != */* && "$config_path" != ./* && "$config_path" != ../* ]]; then
      if [[ -f "$PROJECT_ROOT/configs/$config_path" ]]; then
        config_path="configs/$config_path"
      fi
    fi

    if [[ -z "$config_path" ]]; then
      echo "Error: 配置文件路径为空，请重新输入。"
      continue
    fi

    local config_abs="$config_path"
    if [[ "$config_abs" != /* ]]; then
      config_abs="$PROJECT_ROOT/$config_abs"
    fi
    if [[ ! -f "$config_abs" ]]; then
      echo "Error: 配置文件不存在：$config_path"
      continue
    fi
    if [[ "$config_path" == /* ]]; then
      config_path="$config_abs"
    fi
    break
  done

  while true; do
    read -r -p "Cache dir [data/results/factor_cache]: " cache_dir
    cache_dir="$(echo "${cache_dir:-data/results/factor_cache}" | xargs)"
    if [[ -z "$cache_dir" ]]; then
      echo "Error: 缓存目录为空，请重新输入。"
      continue
    fi
    if [[ "$cache_dir" == "q" || "$cache_dir" == "quit" || "$cache_dir" == "exit" ]]; then
      echo "Canceled."
      return 0
    fi

    # Convenience: allow typing "factor_cache_xxx" -> "data/results/factor_cache_xxx"
    if [[ "$cache_dir" != /* && "$cache_dir" != */* && "$cache_dir" != ./* && "$cache_dir" != ../* ]]; then
      cache_dir="data/results/$cache_dir"
    fi

    local cache_abs="$cache_dir"
    if [[ "$cache_abs" != /* ]]; then
      cache_abs="$PROJECT_ROOT/$cache_abs"
    fi
    if [[ -e "$cache_abs" && ! -d "$cache_abs" ]]; then
      echo "Error: 缓存路径已存在但不是目录：$cache_dir"
      continue
    fi
    break
  done

  read -r -p "Max factors to scan (0=all) [100]: " max_factors
  max_factors="$(echo "${max_factors:-100}" | xargs)"
  if ! [[ "$max_factors" =~ ^[0-9]+$ ]]; then
    echo "Error: max_factors must be an integer."
    return 2
  fi

  read -r -p "Warm cache from result.h5 first? [Y/n]: " warm_cache
  warm_cache="$(echo "${warm_cache:-y}" | tr '[:upper:]' '[:lower:]' | xargs)"

  read -r -p "Delete invalid cache entries on apply? [Y/n]: " delete_invalid
  delete_invalid="$(echo "${delete_invalid:-y}" | tr '[:upper:]' '[:lower:]' | xargs)"

  read -r -p "Recompute missing cache entries on apply? [Y/n]: " recompute_missing
  recompute_missing="$(echo "${recompute_missing:-y}" | tr '[:upper:]' '[:lower:]' | xargs)"

  read -r -p "Recompute invalid cache entries on apply? [Y/n]: " recompute_invalid
  recompute_invalid="$(echo "${recompute_invalid:-y}" | tr '[:upper:]' '[:lower:]' | xargs)"

  echo
  echo "Dry-run scan (no changes):"
  local lib
  for lib in "${selected_paths[@]}"; do
    local rel="$lib"
    if [[ "$lib" == "$PROJECT_ROOT/"* ]]; then
      rel="${lib#"$PROJECT_ROOT"/}"
    fi
    echo
    echo "Library: $rel"
    local cmd=(
      "$PYTHON_BIN" "scripts/factor_filtering/repair_factor_cache.py"
      "--library" "$rel"
      "--config" "$config_path"
      "--cache-dir" "$cache_dir"
      "--max-factors" "$max_factors"
    )
    if [[ "$warm_cache" != "n" && "$warm_cache" != "no" ]]; then
      cmd+=("--warm-cache")
    fi
    if ! "${cmd[@]}"; then
      echo "Error: cache repair dry-run failed for: $rel"
      return 1
    fi
  done

  echo
  read -r -p "Apply changes now? [y/N]: " confirm
  confirm="$(echo "${confirm:-}" | tr '[:upper:]' '[:lower:]' | xargs)"
  if [[ "$confirm" != "y" && "$confirm" != "yes" ]]; then
    echo "Canceled."
    return 0
  fi

  echo
  echo "Apply:"
  for lib in "${selected_paths[@]}"; do
    local rel="$lib"
    if [[ "$lib" == "$PROJECT_ROOT/"* ]]; then
      rel="${lib#"$PROJECT_ROOT"/}"
    fi
    echo
    echo "Library: $rel"
    local cmd=(
      "$PYTHON_BIN" "scripts/factor_filtering/repair_factor_cache.py"
      "--library" "$rel"
      "--config" "$config_path"
      "--cache-dir" "$cache_dir"
      "--max-factors" "$max_factors"
      "--apply"
    )
    if [[ "$warm_cache" != "n" && "$warm_cache" != "no" ]]; then
      cmd+=("--warm-cache")
    fi
    if [[ "$delete_invalid" != "n" && "$delete_invalid" != "no" ]]; then
      cmd+=("--delete-invalid")
    fi
    if [[ "$recompute_missing" != "n" && "$recompute_missing" != "no" ]]; then
      cmd+=("--recompute-missing")
    fi
    if [[ "$recompute_invalid" != "n" && "$recompute_invalid" != "no" ]]; then
      cmd+=("--recompute-invalid")
    fi
    if ! "${cmd[@]}"; then
      echo "Error: cache repair apply failed for: $rel"
      return 1
    fi
  done
}

count_factors_in_library() {
  local lib_path="$1"
  "$PYTHON_BIN" - "$lib_path" <<'PY'
import json, sys
p = sys.argv[1]
try:
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f) or {}
    factors = data.get("factors") if isinstance(data, dict) else {}
    print(len(factors) if isinstance(factors, dict) else 0)
except Exception:
    print(0)
PY
}

filter_factor_libraries_by_ids() {
  local patterns=(
    "$PROJECT_ROOT/data/factorlib/all_factors_library*.json"
    "$PROJECT_ROOT/all_factors_library*.json"
  )

  echo "Current libraries:"
  list_factor_libraries
  echo
  read -r -p "Enter ids to filter (use + to join, e.g. 1+2, or all): " filter_ids
  filter_ids="$(echo "${filter_ids:-}" | tr -d '[:space:]')"
  if [[ -z "$filter_ids" ]]; then
    echo "Error: empty ids."
    return 2
  fi

  local selected_paths=()
  local line
  while IFS= read -r line; do
    [[ -n "$line" ]] && selected_paths+=("$line")
  done < <(resolve_factor_library_paths_by_ids "$filter_ids")
  if [[ "${#selected_paths[@]}" -eq 0 ]]; then
    echo "Error: no libraries resolved from ids: $filter_ids"
    return 2
  fi

  echo
  echo "Selected libraries (${#selected_paths[@]}):"
  local p rel
  for p in "${selected_paths[@]}"; do
    rel="$p"
    [[ "$p" == "$PROJECT_ROOT/"* ]] && rel="${p#"$PROJECT_ROOT"/}"
    echo "  - $rel"
  done

  local source_pool_path=""
  local source_stem=""
  local tmp_merged=""
  if [[ "${#selected_paths[@]}" -gt 1 ]]; then
    local merge_ts
    merge_ts="$(date "+%Y%m%d_%H%M%S")"
    tmp_merged="$(mktemp "/tmp/quanta_factor_pool_XXXXXX.json")"
    local libraries_spec
    libraries_spec="$(IFS=,; echo "${selected_paths[*]}")"
    echo
    echo "Building Stage0 total pool from selected libraries..."
    "$PYTHON_BIN" scripts/factor_filtering/merge_factor_libraries.py \
      --libraries "$libraries_spec" \
      --out "$tmp_merged" \
      --zoo-method none
    source_pool_path="$tmp_merged"
    source_stem="factor_pool_selected"
  else
    source_pool_path="${selected_paths[0]}"
    source_stem="$(basename "${selected_paths[0]}")"
    source_stem="${source_stem%.json}"
  fi

  local config_path
  read -r -p "Backtest config [configs/backtest.yaml]: " config_path
  config_path="$(echo "${config_path:-configs/backtest.yaml}" | xargs)"
  if [[ -z "$config_path" ]]; then
    echo "Error: empty config path."
    [[ -n "$tmp_merged" && -f "$tmp_merged" ]] && rm -f "$tmp_merged" || true
    return 2
  fi
  local config_abs="$config_path"
  [[ "$config_abs" != /* ]] && config_abs="$PROJECT_ROOT/$config_abs"
  if [[ ! -f "$config_abs" ]]; then
    echo "Error: config not found: $config_path"
    [[ -n "$tmp_merged" && -f "$tmp_merged" ]] && rm -f "$tmp_merged" || true
    return 2
  fi

  local expr_method="ast"

  local stage_pick
  echo "Output stage options:"
  echo "  0) stage0 full pool"
  echo "  1) stage1 expr dedup"
  echo "  2) stage2 exposure dedup"
  echo "  3) stage3 ic dedup (final)"
  echo "  a) all stages + manifest"
  read -r -p "Select output stage [a]: " stage_pick
  stage_pick="$(echo "${stage_pick:-a}" | tr '[:upper:]' '[:lower:]' | xargs)"
  local output_stage
  case "$stage_pick" in
    0|stage0) output_stage="stage0" ;;
    1|stage1) output_stage="stage1" ;;
    2|stage2) output_stage="stage2" ;;
    3|stage3) output_stage="stage3" ;;
    a|all) output_stage="all" ;;
    *)
      echo "Error: invalid output stage '$stage_pick'."
      [[ -n "$tmp_merged" && -f "$tmp_merged" ]] && rm -f "$tmp_merged" || true
      return 2
      ;;
  esac

  local topn_val="0"  # all

  local out_prefix="data/factorlib/selected/${source_stem}_filter_pipeline"

  local run_ts
  run_ts="$(date "+%Y%m%d_%H%M%S")"

  if [[ "$output_stage" == "stage0" ]]; then
    local n0 out_stage0 out_manifest
    n0="$(count_factors_in_library "$source_pool_path")"
    out_stage0="${out_prefix}_n${n0}_${run_ts}_stage0.json"
    out_manifest="${out_prefix}_n${n0}_${run_ts}_manifest.json"
    cp "$source_pool_path" "$out_stage0"
    "$PYTHON_BIN" - "$source_pool_path" "$out_manifest" "$run_ts" "$config_abs" <<'PY'
import json
import sys
from pathlib import Path

stage0, manifest, ts, cfg = sys.argv[1:5]
try:
    data = json.loads(Path(stage0).read_text(encoding="utf-8")) or {}
    factors = data.get("factors") if isinstance(data, dict) else {}
    n0 = len(factors) if isinstance(factors, dict) else 0
except Exception:
    n0 = 0

payload = {
    "pipeline": "observable_filter_0_to_3",
    "generated_at": ts,
    "config": cfg,
    "stages": {
        "stage0": {
            "name": "full_pool",
            "input": n0,
            "kept": n0,
            "dropped": 0,
            "path": stage0,
        }
    },
}
Path(manifest).parent.mkdir(parents=True, exist_ok=True)
Path(manifest).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY
    echo
    echo "Stage counts: stage0=$n0"
    echo "Output stage0: ${out_stage0#"$PROJECT_ROOT"/}"
    echo "Output manifest: ${out_manifest#"$PROJECT_ROOT"/}"
    [[ -n "$tmp_merged" && -f "$tmp_merged" ]] && rm -f "$tmp_merged" 2>/dev/null || true
    return 0
  fi

  local tmp_stage1 tmp_stage2 tmp_stage3 tmp_report
  tmp_stage1="$(mktemp "/tmp/quanta_stage1_XXXXXX")"
  tmp_stage2="$(mktemp "/tmp/quanta_stage2_XXXXXX")"
  tmp_stage3="$(mktemp "/tmp/quanta_stage3_XXXXXX")"
  tmp_report="$(mktemp "/tmp/quanta_stage3_report_XXXXXX")"
  tmp_stage1="${tmp_stage1}.json"
  tmp_stage2="${tmp_stage2}.json"
  tmp_stage3="${tmp_stage3}.json"
  tmp_report="${tmp_report}.json"

  echo
  echo "Pipeline plan:"
  echo "  source_pool=$source_pool_path"
  echo "  config=$config_abs"
  echo "  expr_dedup_method=$expr_method"
  echo "  output_stage=$output_stage"
  echo "  stage3_topn=all"
  echo "  output_prefix=$out_prefix"
  read -r -p "Proceed? [Y/n]: " confirm
  confirm="$(echo "${confirm:-y}" | tr '[:upper:]' '[:lower:]' | xargs)"
  if [[ "$confirm" == "n" || "$confirm" == "no" ]]; then
    rm -f "$tmp_stage1" "$tmp_stage2" "$tmp_stage3" "$tmp_report" 2>/dev/null || true
    [[ -n "$tmp_merged" && -f "$tmp_merged" ]] && rm -f "$tmp_merged" 2>/dev/null || true
    echo "Canceled."
    return 0
  fi

  echo
  echo "Running stage pipeline (0->3)..."
  "$PYTHON_BIN" scripts/factor_filtering/select_factors.py \
    --library "$source_pool_path" \
    --config "$config_abs" \
    --expr-dedup-method "$expr_method" \
    --out-stage1 "$tmp_stage1" \
    --out-stage2 "$tmp_stage2" \
    --out "$tmp_stage3" \
    --dedup-method two_stage \
    --cluster-linkage complete \
    --topn "$topn_val" \
    --per-cluster 1 \
    --corr-threshold 0.8 \
    --stage2-ic-corr-threshold 0.8 \
    --sample-size 12000 \
    --sample-split train_valid \
    --compute-missing \
    --report "$tmp_report"

  local n0 n1 n2 n3
  n0="$(count_factors_in_library "$source_pool_path")"
  n1="$(count_factors_in_library "$tmp_stage1")"
  n2="$(count_factors_in_library "$tmp_stage2")"
  n3="$(count_factors_in_library "$tmp_stage3")"

  local out_stage0="${out_prefix}_n${n0}_${run_ts}_stage0.json"
  local out_stage1="${out_prefix}_n${n1}_${run_ts}_stage1.json"
  local out_stage2="${out_prefix}_n${n2}_${run_ts}_stage2.json"
  local out_stage3="${out_prefix}_n${n3}_${run_ts}_stage3.json"
  local out_manifest="${out_prefix}_n${n3}_${run_ts}_manifest.json"

  local copy_stage0="false" copy_stage1="false" copy_stage2="false" copy_stage3="false"
  case "$output_stage" in
    stage0) copy_stage0="true" ;;
    stage1) copy_stage1="true" ;;
    stage2) copy_stage2="true" ;;
    stage3) copy_stage3="true" ;;
    all)
      copy_stage0="true"
      copy_stage1="true"
      copy_stage2="true"
      copy_stage3="true"
      ;;
  esac

  [[ "$copy_stage0" == "true" ]] && cp "$source_pool_path" "$out_stage0"
  [[ "$copy_stage1" == "true" ]] && cp "$tmp_stage1" "$out_stage1"
  [[ "$copy_stage2" == "true" ]] && cp "$tmp_stage2" "$out_stage2"
  [[ "$copy_stage3" == "true" ]] && cp "$tmp_stage3" "$out_stage3"

  "$PYTHON_BIN" - "$source_pool_path" "$tmp_stage1" "$tmp_stage2" "$tmp_stage3" "$tmp_report" "$out_manifest" "$run_ts" "$expr_method" "$config_abs" <<'PY'
import json
import sys
from pathlib import Path

stage0, stage1, stage2, stage3, report_path, out_manifest, run_ts, expr_method, config_path = sys.argv[1:10]

def count(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8")) or {}
        f = d.get("factors") if isinstance(d, dict) else {}
        return len(f) if isinstance(f, dict) else 0
    except Exception:
        return 0

def read_json(path):
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

n0, n1, n2, n3 = count(stage0), count(stage1), count(stage2), count(stage3)
s1_meta = (read_json(stage1).get("metadata") or {})
s2_meta = (read_json(stage2).get("metadata") or {})
report = read_json(report_path)
sel = ((report.get("selection") or {}) if isinstance(report, dict) else {})
expr = s1_meta.get("expr_dedup") if isinstance(s1_meta, dict) else {}
snap2 = s2_meta.get("selection_snapshot") if isinstance(s2_meta, dict) else {}

manifest = {
    "pipeline": "observable_filter_0_to_3",
    "generated_at": run_ts,
    "config": config_path,
    "expr_dedup_method": expr_method,
    "stages": {
        "stage0": {
            "name": "full_pool",
            "input": n0,
            "kept": n0,
            "dropped": 0,
            "path": stage0,
        },
        "stage1": {
            "name": "expr_dedup",
            "input": n0,
            "kept": n1,
            "dropped": max(0, n0 - n1),
            "reasons": {
                "duplicates_removed": (expr or {}).get("duplicates_removed"),
                "dropped_empty_expr": (expr or {}).get("dropped_empty_expr"),
                "ast_parse_failed": (expr or {}).get("ast_parse_failed"),
            },
            "path": stage1,
        },
        "stage2": {
            "name": "exposure_dedup",
            "input": n1,
            "kept": n2,
            "dropped": max(0, n1 - n2),
            "reasons": {
                "dropped_missing_or_low_coverage": (snap2 or {}).get("dropped_missing_or_low_coverage"),
                "clusters": (snap2 or {}).get("clusters"),
            },
            "path": stage2,
        },
        "stage3": {
            "name": "ic_dedup_final",
            "input": n2,
            "kept": n3,
            "dropped": max(0, n2 - n3),
            "reasons": {
                "dropped_before_stage2": ((sel.get("stage2") or {}) if isinstance(sel, dict) else {}).get("dropped_before_stage2"),
                "clusters": ((sel.get("stage2") or {}) if isinstance(sel, dict) else {}).get("clusters"),
            },
            "path": stage3,
        },
    },
    "artifacts": {
        "stage3_report": report_path,
    },
}

Path(out_manifest).parent.mkdir(parents=True, exist_ok=True)
Path(out_manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"n0": n0, "n1": n1, "n2": n2, "n3": n3}, ensure_ascii=False))
PY

  local manifest_rel="$out_manifest"
  [[ "$manifest_rel" == "$PROJECT_ROOT/"* ]] && manifest_rel="${manifest_rel#"$PROJECT_ROOT"/}"
  echo
  echo "Stage counts: stage0=$n0 stage1=$n1 stage2=$n2 stage3=$n3"
  [[ "$copy_stage0" == "true" ]] && echo "Output stage0: ${out_stage0#"$PROJECT_ROOT"/}"
  [[ "$copy_stage1" == "true" ]] && echo "Output stage1: ${out_stage1#"$PROJECT_ROOT"/}"
  [[ "$copy_stage2" == "true" ]] && echo "Output stage2: ${out_stage2#"$PROJECT_ROOT"/}"
  [[ "$copy_stage3" == "true" ]] && echo "Output stage3: ${out_stage3#"$PROJECT_ROOT"/}"
  echo "Output manifest: $manifest_rel"

  rm -f "$tmp_stage1" "$tmp_stage2" "$tmp_stage3" "$tmp_report" 2>/dev/null || true
  [[ -n "$tmp_merged" && -f "$tmp_merged" ]] && rm -f "$tmp_merged" 2>/dev/null || true
}

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/run_factors.sh

Interactive options:
  1) List factor libraries (all_factors_library*.json)
  2) Delete factor libraries by id (supports `+` batch input)
  3) Merge libraries by id (supports `+` and `all`)
  4) Repair factor cache by id (dry-run + apply)
  5) Filter pipeline (stage0->3 + manifest)
  0) Exit
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

while true; do
  echo "Step 1/?: choose action"
  echo "  1) [LIST] all factor libraries summary"
  echo "  2) [DELETE] factor libraries by id"
  echo "  3) [MERGE] merge libraries by id"
  echo "  4) [CACHE] repair factor cache by id"
  echo "  5) [FILTER] run observable filter pipeline by id"
  echo "  0) [EXIT]"
  read -r -p "Select [1]: " pick
  pick="${pick:-1}"

  case "$pick" in
    1|list|LIST)
      if ! list_factor_libraries; then
        echo "Error: list failed."
      fi
      echo
      read -r -p "Press Enter to go back: " _
      ;;
    2|delete|DELETE|rm|RM)
      if ! delete_factor_libraries; then
        echo "Error: delete failed."
      fi
      echo
      read -r -p "Press Enter to go back: " _
      ;;
    3|merge|MERGE)
      if ! merge_factor_libraries_by_ids; then
        echo "Error: merge failed."
      fi
      echo
      read -r -p "Press Enter to go back: " _
      ;;
    4|cache|CACHE|repair|REPAIR)
      if ! repair_factor_cache_by_ids; then
        echo "Error: cache repair failed."
      fi
      echo
      read -r -p "Press Enter to go back: " _
      ;;
    5|filter|FILTER)
      if ! filter_factor_libraries_by_ids; then
        echo "Error: filter pipeline failed."
      fi
      echo
      read -r -p "Press Enter to go back: " _
      ;;
    0|exit|EXIT)
      exit 0
      ;;
    *)
      echo "Error: invalid selection '$pick'"
      usage
      echo
      ;;
  esac
done
