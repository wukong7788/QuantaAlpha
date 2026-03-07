#!/usr/bin/env python3
"""
Experiment A/B test harness for QuantaAlpha (`./run.sh` / `quantaalpha mine`).

Design goals:
- Keep codebase unchanged; compare by config toggles.
- Isolate artifacts under /tmp (scheme A): workspace/pickle cache + captured logs/reports.
- Emit a single machine-readable line: `ABTEST_RESULT=...`.

Usage example:
  cd /Users/ron/Documents/QuantaAlpha
  .venv/bin/python scripts/abtest_experiment.py run \
    --name opt1_cheap_gate \
    --variant baseline \
    --base-config configs/experiment_smoke.yaml \
    --direction "价量因子挖掘" \
    --step-n 3 \
    --set quality_gate.cheap_filter_enabled=false
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import re
import subprocess
import sys
import time
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]

QUALITY_METRIC_KEYS: List[str] = [
    "Rank IC",
    "Rank ICIR",
    "IC",
    "ICIR",
    "1day.excess_return_with_cost.information_ratio",
    "1day.excess_return_with_cost.annualized_return",
    "1day.excess_return_with_cost.max_drawdown",
]

# Default KPI for "best factor" selection (higher is better).
TOP_FACTOR_METRIC_KEY = "1day.excess_return_with_cost.information_ratio"


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _parse_value(raw: str) -> Any:
    # Use YAML scalar parsing (true/false/null/123/1.2/"str") for convenience.
    try:
        return yaml.safe_load(raw)
    except Exception:
        return raw


def _set_dotted(cfg: Dict[str, Any], dotted_key: str, value: Any) -> None:
    parts = [p for p in dotted_key.split(".") if p]
    if not parts:
        raise ValueError("Empty dotted key")
    cur: Dict[str, Any] = cfg
    for p in parts[:-1]:
        nxt = cur.get(p)
        if nxt is None:
            nxt = {}
            cur[p] = nxt
        if not isinstance(nxt, dict):
            raise ValueError(f"Cannot set {dotted_key!r}: {p!r} is not a dict")
        cur = nxt
    cur[parts[-1]] = value


def _load_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a dict: {path}")
    return data


def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _run(cmd: List[str], cwd: Path, env: Dict[str, str], stdout_path: Path) -> Tuple[int, float]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    with stdout_path.open("w", encoding="utf-8") as f:
        p = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=f, stderr=subprocess.STDOUT, text=True)
        rc = p.wait()
    return rc, time.perf_counter() - t0


def _run_doctor(experiment_id: str, log_root: str, out_md: Path, env: Dict[str, str]) -> int:
    out_md.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["bash", "scripts/run_doctor.sh", "--experiment-id", experiment_id]
    if log_root:
        cmd.extend(["--log-root", log_root])
    with out_md.open("w", encoding="utf-8") as f:
        p = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), env=env, stdout=f, stderr=subprocess.STDOUT, text=True)
        return p.wait()

def _extract_metrics_from_run_log(run_log: Path) -> Dict[str, Any]:
    """
    Best-effort parsing from run.log (treat as text even if it contains ANSI).
    Returns small, stable metrics for A/B:
      - step_time_s: {step: [float, ...]}
      - step_time_p90_s: {step: float}
      - json_fail_counts: {kind: int}
    """
    try:
        text = run_log.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}

    # Strip ANSI color codes so regexes are stable.
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)

    step_time_s: Dict[str, List[float]] = {}
    for line in text.splitlines():
        # tolerate trailing decorations / non-text characters
        m = re.search(r" - (?P<step>[A-Za-z_]+) took (?P<secs>[0-9]+(?:\.[0-9]+)?)s", line)
        if not m:
            continue
        step = m.group("step")
        secs = float(m.group("secs"))
        step_time_s.setdefault(step, []).append(secs)

    def _p90(xs: List[float]) -> float:
        if not xs:
            return 0.0
        ys = sorted(xs)
        idx = int((0.9 * (len(ys) - 1)))
        return float(ys[idx])

    step_time_p90_s = {k: round(_p90(v), 3) for k, v in step_time_s.items()}

    # Common JSON instability signals (case-insensitive substring counts).
    #
    # NOTE: QuantaAlpha logs often emit structured events like:
    #   {"event": "llm_json_response_issue", "issue": "json_fix_failed", ...}
    # so we must match both legacy "json fix failed" wording and underscore-style issue names.
    lowered = text.lower()

    def _count_any(*needles: str) -> int:
        return sum(lowered.count(n) for n in needles if n)

    json_fail_counts = {
        "json_parse_failed": _count_any("json parse failed", "json_parse_failed"),
        "json_fix_failed": _count_any("json fix failed", "json_fix_failed"),
        "json_fix_success": _count_any("json fix success", "json_fix_success"),
        "empty_json_response": _count_any("empty response", "empty_response"),
        # Additional signal used by some runtimes (not always surfaced as a parse failure).
        "json_boundary_missing": _count_any("json boundary missing", "json_boundary_missing"),
    }

    # Whether the subtree blacklist actually rejected candidates (if enabled).
    sb_rejected_total = 0
    sb_rejected_events = 0
    for m in re.finditer(r"Subtree blacklist rejected factors:\s*(\d+)/(\d+)", text):
        try:
            sb_rejected_total += int(m.group(1))
            sb_rejected_events += 1
        except Exception:
            continue

    return {
        "step_time_s": step_time_s,
        "step_time_p90_s": step_time_p90_s,
        "json_fail_counts": json_fail_counts,
        "llm_connection_error_count": lowered.count("connection error"),
        "llm_retry_line_count": len(re.findall(r"retrying \d+th time", lowered)),
        "subtree_blacklist_rejected_total": sb_rejected_total,
        "subtree_blacklist_rejected_events": sb_rejected_events,
    }

def _median(xs: List[float]) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    n = len(ys)
    mid = n // 2
    if n % 2 == 1:
        return float(ys[mid])
    return float((ys[mid - 1] + ys[mid]) / 2.0)

def _mean(xs: List[float]) -> float:
    if not xs:
        return 0.0
    return float(sum(xs) / float(len(xs)))

def _extract_quality_from_factor_library(library_path: Path) -> Dict[str, Any]:
    """
    Parse `data/factorlib/all_factors_library_<suffix>.json` and summarize per-factor backtest quality.

    Returns:
      - factor_count
      - expr_unique_count
      - metrics_median / metrics_mean / metrics_best for QUALITY_METRIC_KEYS
      - top_factor_by: best factor_name by TOP_FACTOR_METRIC_KEY
    """
    if not library_path.exists():
        return {"factor_count": 0, "expr_unique_count": 0}

    try:
        payload = json.loads(library_path.read_text(encoding="utf-8"))
    except Exception:
        return {"factor_count": 0, "expr_unique_count": 0}

    factors = payload.get("factors") if isinstance(payload, dict) else None
    if not isinstance(factors, dict):
        return {"factor_count": 0, "expr_unique_count": 0}

    # Expression uniqueness.
    exprs: List[str] = []
    for item in factors.values():
        if not isinstance(item, dict):
            continue
        expr = str(item.get("factor_expression", "") or "").strip()
        expr = " ".join(expr.split())
        if expr:
            exprs.append(expr)

    metric_vals: Dict[str, List[float]] = {k: [] for k in QUALITY_METRIC_KEYS}
    top_factor: Dict[str, Any] | None = None
    for item in factors.values():
        if not isinstance(item, dict):
            continue
        br = item.get("backtest_results") or {}
        if isinstance(br, dict):
            for k in QUALITY_METRIC_KEYS:
                v = br.get(k)
                if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
                    metric_vals[k].append(float(v))

        # Best factor by TOP_FACTOR_METRIC_KEY.
        v_top = None
        if isinstance(br, dict):
            v_top = br.get(TOP_FACTOR_METRIC_KEY)
        if isinstance(v_top, (int, float)) and not (isinstance(v_top, float) and math.isnan(v_top)):
            if top_factor is None or float(v_top) > float(top_factor["value"]):
                top_factor = {
                    "metric": TOP_FACTOR_METRIC_KEY,
                    "factor_name": str(item.get("factor_name", "") or ""),
                    "value": float(v_top),
                }

    metrics_median: Dict[str, float] = {}
    metrics_mean: Dict[str, float] = {}
    metrics_best: Dict[str, float] = {}
    metrics_n: Dict[str, int] = {}
    for k, vs in metric_vals.items():
        if not vs:
            continue
        metrics_median[k] = round(_median(vs), 8)
        metrics_mean[k] = round(_mean(vs), 8)
        metrics_best[k] = round(max(vs), 8)
        metrics_n[k] = int(len(vs))

    out: Dict[str, Any] = {
        "factor_count": int(len(factors)),
        "expr_unique_count": int(len(set(exprs))),
        "metrics_median": metrics_median,
        "metrics_mean": metrics_mean,
        "metrics_best": metrics_best,
        "metrics_n": metrics_n,
    }
    if top_factor is not None:
        top_factor["value"] = round(float(top_factor["value"]), 8)
        out["top_factor_by"] = top_factor
    return out

def _build_config(
    base_cfg: Dict[str, Any],
    *,
    sets: List[Tuple[str, Any]],
) -> Dict[str, Any]:
    cfg = copy.deepcopy(base_cfg)
    for k, v in sets:
        _set_dotted(cfg, k, v)
    return cfg


def _run_variant_repeats(
    *,
    name: str,
    variant: str,
    base_ts: str,
    base_config_path: Path,
    direction: str,
    step_n: int,
    times: int,
    skip_doctor: bool,
    results_root_base: Path,
    data_results_root_base: Path,
    cfg: Dict[str, Any],
    applied_sets: List[Tuple[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], bool]:
    payloads: List[Dict[str, Any]] = []
    any_failed = False

    for i in range(1, times + 1):
        run_id = f"{name}_{variant}_{base_ts}_r{i:02d}"
        experiment_id = run_id
        factor_suffix = run_id

        results_root = results_root_base / name / variant / base_ts / f"r{i:02d}"
        data_results_dir = data_results_root_base / name / variant / base_ts / f"r{i:02d}"

        generated_config = results_root / "config.yaml"
        _write_yaml(generated_config, cfg)

        log_root = results_root / "log"
        run_log = results_root / "run.log"
        doctor_md = results_root / "doctor.md"

        env = os.environ.copy()
        env["CONFIG_PATH"] = str(generated_config)
        env["STEP_N"] = str(step_n)
        env["EXPERIMENT_ID"] = experiment_id
        env["FACTOR_LIBRARY_SUFFIX"] = factor_suffix
        env["DATA_RESULTS_DIR"] = str(data_results_dir)
        env["LOG_TRACE_PATH"] = str(log_root)

        print(
            f"[ABTEST] start variant={variant} run={i}/{times} run_id={run_id}",
            flush=True,
        )
        print(
            f"[ABTEST] run_log={run_log} doctor_md={doctor_md} config={generated_config}",
            flush=True,
        )
        rc, elapsed_s = _run(["bash", "./run.sh", direction], cwd=PROJECT_ROOT, env=env, stdout_path=run_log)
        if rc != 0:
            any_failed = True
        print(
            f"[ABTEST] finished variant={variant} run={i}/{times} "
            f"run_id={run_id} exit_code={rc} elapsed_s={round(elapsed_s, 3)}",
            flush=True,
        )

        doctor_rc = 0
        if not skip_doctor:
            print(
                f"[ABTEST] doctor start variant={variant} run={i}/{times} run_id={run_id}",
                flush=True,
            )
            doctor_rc = _run_doctor(experiment_id, str(log_root), doctor_md, env=env)
            print(
                f"[ABTEST] doctor finished variant={variant} run={i}/{times} "
                f"run_id={run_id} doctor_exit_code={doctor_rc}",
                flush=True,
            )

        extra_metrics = _extract_metrics_from_run_log(run_log)
        factor_library_path = PROJECT_ROOT / "data" / "factorlib" / f"all_factors_library_{factor_suffix}.json"
        factor_quality = _extract_quality_from_factor_library(factor_library_path)

        payload: Dict[str, Any] = {
            "name": name,
            "variant": variant,
            "run_id": run_id,
            "experiment_id": experiment_id,
            "factor_library_suffix": factor_suffix,
            "factor_library_path": str(factor_library_path),
            "base_config": str(base_config_path),
            "generated_config": str(generated_config),
            "applied_set": [{"key": k, "value": v} for k, v in applied_sets],
            "direction": direction,
            "step_n": step_n,
            "repeat_idx": i,
            "repeat_total": times,
            "elapsed_s": round(elapsed_s, 3),
            "exit_code": rc,
            "doctor_exit_code": doctor_rc,
            "run_log": str(run_log),
            "doctor_md": str(doctor_md),
            "log_root": str(log_root),
            "data_results_dir": str(data_results_dir),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "factor_quality": factor_quality,
        }
        payload.update(extra_metrics)
        payloads.append(payload)
        print("ABTEST_RESULT=" + json.dumps(payload, ensure_ascii=False))

    elapsed_list = [float(p.get("elapsed_s", 0.0)) for p in payloads if isinstance(p.get("elapsed_s"), (int, float))]
    ok_payloads = [p for p in payloads if int(p.get("exit_code", 1)) == 0]
    elapsed_ok_list = [
        float(p.get("elapsed_s", 0.0)) for p in ok_payloads if isinstance(p.get("elapsed_s"), (int, float))
    ]
    summary: Dict[str, Any] = {
        "name": name,
        "variant": variant,
        "runs": times,
        "runs_success": int(len(ok_payloads)),
        "runs_failed": int(times - len(ok_payloads)),
        "elapsed_s_median": round(_median(elapsed_list), 3),
        "elapsed_s_min": round(min(elapsed_list), 3) if elapsed_list else 0.0,
        "elapsed_s_max": round(max(elapsed_list), 3) if elapsed_list else 0.0,
        "elapsed_s_median_success": round(_median(elapsed_ok_list), 3) if elapsed_ok_list else 0.0,
    }

    agg_json: Dict[str, int] = {}
    for p in payloads:
        j = p.get("json_fail_counts") or {}
        if not isinstance(j, dict):
            continue
        for k, v in j.items():
            try:
                agg_json[k] = int(agg_json.get(k, 0)) + int(v)
            except Exception:
                continue
    if agg_json:
        summary["json_fail_counts_sum"] = agg_json

    # Aggregate subtree blacklist activity.
    sb_rejected_sum = 0
    sb_rejected_events_sum = 0
    for p in payloads:
        try:
            sb_rejected_sum += int(p.get("subtree_blacklist_rejected_total", 0) or 0)
            sb_rejected_events_sum += int(p.get("subtree_blacklist_rejected_events", 0) or 0)
        except Exception:
            continue
    summary["subtree_blacklist_rejected_sum"] = int(sb_rejected_sum)
    summary["subtree_blacklist_rejected_events_sum"] = int(sb_rejected_events_sum)

    # Aggregate factor quality (per-run medians, then median across runs).
    factor_counts = []
    expr_unique_counts = []
    per_run_metric_medians: Dict[str, List[float]] = {k: [] for k in QUALITY_METRIC_KEYS}
    per_run_metric_bests: Dict[str, List[float]] = {k: [] for k in QUALITY_METRIC_KEYS}
    for p in ok_payloads:
        fq = p.get("factor_quality") or {}
        if not isinstance(fq, dict):
            continue
        fc = fq.get("factor_count")
        ec = fq.get("expr_unique_count")
        if isinstance(fc, int):
            factor_counts.append(float(fc))
        if isinstance(ec, int):
            expr_unique_counts.append(float(ec))

        mm = fq.get("metrics_median") or {}
        if isinstance(mm, dict):
            for k in QUALITY_METRIC_KEYS:
                v = mm.get(k)
                if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
                    per_run_metric_medians[k].append(float(v))

        mb = fq.get("metrics_best") or {}
        if isinstance(mb, dict):
            for k in QUALITY_METRIC_KEYS:
                v = mb.get(k)
                if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
                    per_run_metric_bests[k].append(float(v))

    summary_quality: Dict[str, Any] = {}
    if factor_counts:
        summary_quality["factor_count_median_success"] = int(round(_median(factor_counts)))
    if expr_unique_counts:
        summary_quality["expr_unique_count_median_success"] = int(round(_median(expr_unique_counts)))

    med_of_meds: Dict[str, float] = {}
    best_of_bests: Dict[str, float] = {}
    for k in QUALITY_METRIC_KEYS:
        if per_run_metric_medians.get(k):
            med_of_meds[k] = round(_median(per_run_metric_medians[k]), 8)
        if per_run_metric_bests.get(k):
            best_of_bests[k] = round(max(per_run_metric_bests[k]), 8)
    if med_of_meds:
        summary_quality["metrics_median_of_medians_success"] = med_of_meds
    if best_of_bests:
        summary_quality["metrics_best_of_bests_success"] = best_of_bests
    if summary_quality:
        summary["factor_quality_summary"] = summary_quality

    print("ABTEST_SUMMARY=" + json.dumps(summary, ensure_ascii=False))
    return payloads, summary, any_failed


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="QuantaAlpha experiment A/B test harness")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run one variant")
    run_p.add_argument("--name", required=True, help="Test name (e.g. opt1_cheap_gate)")
    run_p.add_argument("--variant", required=True, choices=["baseline", "optimized"])
    run_p.add_argument("--base-config", required=True, help="Base experiment yaml path")
    run_p.add_argument("--direction", required=True, help="Initial direction string for ./run.sh")
    run_p.add_argument("--step-n", type=int, default=3, help="STEP_N env (default: 3)")
    run_p.add_argument("--times", type=int, default=1, help="Repeat runs for this variant (default: 1)")
    run_p.add_argument("--skip-doctor", action="store_true", help="Skip running run_doctor (faster).")
    run_p.add_argument(
        "--set",
        action="append",
        default=[],
        help="Override config key via dotted path, e.g. --set llm.json_mode_strict=false",
    )
    run_p.add_argument(
        "--results-root",
        default="/tmp/quanta_abtests",
        help="Root folder for logs/configs/reports (default: /tmp/quanta_abtests)",
    )
    run_p.add_argument(
        "--data-results-root",
        default="/tmp/quanta_abtest_results",
        help="DATA_RESULTS_DIR root (workspace/pickle cache) (default: /tmp/quanta_abtest_results)",
    )

    cmp_p = sub.add_parser("compare", help="Run baseline + optimized and print a comparison summary")
    cmp_p.add_argument("--name", required=True, help="Test name (e.g. opt2_json_protocol)")
    cmp_p.add_argument("--base-config", required=True, help="Base experiment yaml path")
    cmp_p.add_argument("--direction", required=True, help="Initial direction string for ./run.sh")
    cmp_p.add_argument("--step-n", type=int, default=3, help="STEP_N env (default: 3)")
    cmp_p.add_argument("--times", type=int, default=3, help="Repeat runs per variant (default: 3)")
    cmp_p.add_argument("--skip-doctor", action="store_true", help="Skip running run_doctor (faster).")
    cmp_p.add_argument("--set-common", action="append", default=[], help="Common overrides applied to both variants (key=value)")
    cmp_p.add_argument("--set-baseline", action="append", default=[], help="Baseline-only overrides (key=value)")
    cmp_p.add_argument("--set-optimized", action="append", default=[], help="Optimized-only overrides (key=value)")
    cmp_p.add_argument(
        "--results-root",
        default="/tmp/quanta_abtests",
        help="Root folder for logs/configs/reports (default: /tmp/quanta_abtests)",
    )
    cmp_p.add_argument(
        "--data-results-root",
        default="/tmp/quanta_abtest_results",
        help="DATA_RESULTS_DIR root (workspace/pickle cache) (default: /tmp/quanta_abtest_results)",
    )

    args = parser.parse_args(argv)

    if args.cmd not in {"run", "compare"}:
        raise AssertionError("unreachable")

    base_config_path = (PROJECT_ROOT / args.base_config).resolve() if not os.path.isabs(args.base_config) else Path(args.base_config)
    base_cfg = _load_yaml(base_config_path)

    def _parse_sets(raws: List[str]) -> List[Tuple[str, Any]]:
        out: List[Tuple[str, Any]] = []
        for s in raws:
            if "=" not in s:
                raise SystemExit(f"Invalid set {s!r}: expected key=value")
            k, v_raw = s.split("=", 1)
            out.append((k.strip(), _parse_value(v_raw)))
        return out

    results_root_base = Path(args.results_root)
    data_results_root_base = Path(args.data_results_root)

    if args.cmd == "run":
        applied_sets = _parse_sets(list(args.set))
        cfg = _build_config(base_cfg, sets=applied_sets)
        base_ts = _utc_ts()
        times = max(1, int(args.times))
        _, _, any_failed = _run_variant_repeats(
            name=args.name,
            variant=args.variant,
            base_ts=base_ts,
            base_config_path=base_config_path,
            direction=args.direction,
            step_n=int(args.step_n),
            times=times,
            skip_doctor=bool(args.skip_doctor),
            results_root_base=results_root_base,
            data_results_root_base=data_results_root_base,
            cfg=cfg,
            applied_sets=applied_sets,
        )
        return 1 if any_failed else 0

    common_sets = _parse_sets(list(args.set_common))
    baseline_sets = common_sets + _parse_sets(list(args.set_baseline))
    optimized_sets = common_sets + _parse_sets(list(args.set_optimized))

    baseline_cfg = _build_config(base_cfg, sets=baseline_sets)
    optimized_cfg = _build_config(base_cfg, sets=optimized_sets)

    base_ts = _utc_ts()
    times = max(1, int(args.times))
    print(
        f"[ABTEST] compare name={args.name} times={times} "
        f"base_config={base_config_path} step_n={int(args.step_n)}",
        flush=True,
    )
    print(f"[ABTEST] baseline overrides={baseline_sets}", flush=True)
    print(f"[ABTEST] optimized overrides={optimized_sets}", flush=True)

    _, baseline_summary, baseline_failed = _run_variant_repeats(
        name=args.name,
        variant="baseline",
        base_ts=base_ts,
        base_config_path=base_config_path,
        direction=args.direction,
        step_n=int(args.step_n),
        times=times,
        skip_doctor=bool(args.skip_doctor),
        results_root_base=results_root_base,
        data_results_root_base=data_results_root_base,
        cfg=baseline_cfg,
        applied_sets=baseline_sets,
    )
    _, optimized_summary, optimized_failed = _run_variant_repeats(
        name=args.name,
        variant="optimized",
        base_ts=base_ts,
        base_config_path=base_config_path,
        direction=args.direction,
        step_n=int(args.step_n),
        times=times,
        skip_doctor=bool(args.skip_doctor),
        results_root_base=results_root_base,
        data_results_root_base=data_results_root_base,
        cfg=optimized_cfg,
        applied_sets=optimized_sets,
    )

    b_med = float(baseline_summary.get("elapsed_s_median", 0.0) or 0.0)
    o_med = float(optimized_summary.get("elapsed_s_median", 0.0) or 0.0)
    delta = round(o_med - b_med, 3)
    pct = round(((delta / b_med) * 100.0), 2) if b_med > 0 else None

    b_ok_med = float(baseline_summary.get("elapsed_s_median_success", 0.0) or 0.0)
    o_ok_med = float(optimized_summary.get("elapsed_s_median_success", 0.0) or 0.0)
    delta_ok = round(o_ok_med - b_ok_med, 3)
    pct_ok = round(((delta_ok / b_ok_med) * 100.0), 2) if b_ok_med > 0 else None

    # Quality deltas (median-of-medians across successful runs).
    b_q = (baseline_summary.get("factor_quality_summary") or {}).get("metrics_median_of_medians_success") or {}
    o_q = (optimized_summary.get("factor_quality_summary") or {}).get("metrics_median_of_medians_success") or {}
    delta_q: Dict[str, float] = {}
    if isinstance(b_q, dict) and isinstance(o_q, dict):
        for k in QUALITY_METRIC_KEYS:
            bv = b_q.get(k)
            ov = o_q.get(k)
            if isinstance(bv, (int, float)) and isinstance(ov, (int, float)):
                delta_q[k] = round(float(ov) - float(bv), 8)
    comparison = {
        "name": args.name,
        "runs_per_variant": times,
        "baseline": baseline_summary,
        "optimized": optimized_summary,
        "delta_elapsed_s_median": delta,
        "delta_elapsed_pct_median": pct,
        "delta_elapsed_s_median_success": delta_ok,
        "delta_elapsed_pct_median_success": pct_ok,
        "delta_quality_metrics_median_success": delta_q,
    }
    print("ABTEST_COMPARISON=" + json.dumps(comparison, ensure_ascii=False))

    return 1 if (baseline_failed or optimized_failed) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
