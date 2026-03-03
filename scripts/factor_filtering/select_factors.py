#!/usr/bin/env python3
"""
Select a smaller, diverse subset of factors from a factor library JSON.

Pipeline:
1) Stage-1 coarse dedup on exposure correlation (sampled panel values)
2) Stage-2 fine dedup on RankIC-series correlation (train/valid by default)

This script outputs a smaller factor library JSON for downstream backtest.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def _load_yaml(path: Path) -> Dict[str, Any]:
    import yaml  # type: ignore

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML (expected mapping): {path}")
    return data


def _write_factor_library_json(path: Path, *, base_meta: Dict[str, Any], factors: Dict[str, Any], extra_meta: Dict[str, Any]) -> None:
    meta = dict(base_meta or {})
    meta.update(extra_meta or {})
    meta["total_factors"] = len(factors)
    out = {"metadata": meta, "factors": factors}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def _init_qlib(config: Dict[str, Any]) -> None:
    import qlib  # type: ignore

    data_cfg = config.get("data", {}) or {}
    provider_uri = (
        os.environ.get("QLIB_DATA_DIR")
        or os.environ.get("QLIB_PROVIDER_URI")
        or data_cfg.get("provider_uri", os.path.expanduser("~/.qlib/qlib_data/cn_data"))
    )
    provider_uri = os.path.expanduser(str(provider_uri))
    region = data_cfg.get("region", "cn")
    try:
        qlib.init(provider_uri=provider_uri, region=region)
    except Exception:
        # Already initialized in this process.
        pass


def _to_datetime_instrument_index(df_or_series):
    """Standardize Qlib index to MultiIndex(datetime, instrument)."""
    idx = df_or_series.index
    if not hasattr(idx, "nlevels") or idx.nlevels != 2:
        return df_or_series

    lvl0 = idx.get_level_values(0)
    lvl1 = idx.get_level_values(1)
    lvl0_is_dt = np.issubdtype(getattr(lvl0, "dtype", object), np.datetime64)
    lvl1_is_dt = np.issubdtype(getattr(lvl1, "dtype", object), np.datetime64)

    if lvl0_is_dt and not lvl1_is_dt:
        out = df_or_series.sort_index()
        out.index = out.index.set_names(["datetime", "instrument"])
        return out

    out = df_or_series.swaplevel(0, 1).sort_index()
    out.index = out.index.set_names(["datetime", "instrument"])
    return out


def _resolve_sample_window(config: Dict[str, Any], sample_split: str) -> Tuple[str, str, str]:
    data_cfg = config.get("data", {}) or {}
    default_start = str(data_cfg.get("start_time", "2016-01-01"))
    default_end = str(data_cfg.get("end_time", "2025-12-31"))

    if sample_split == "full":
        return default_start, default_end, "full(data.start_time~data.end_time)"

    dataset_cfg = config.get("dataset", {}) or {}
    segments = dataset_cfg.get("segments", {}) or {}

    def _parse_segment(seg: Any) -> Optional[Tuple[str, str]]:
        if isinstance(seg, (list, tuple)) and len(seg) >= 2:
            left = str(seg[0]).strip()
            right = str(seg[1]).strip()
            if left and right:
                return left, right
        return None

    train = _parse_segment(segments.get("train"))
    valid = _parse_segment(segments.get("valid"))

    if train and valid:
        return train[0], valid[1], "train_valid(dataset.segments.train.start~valid.end)"
    if train:
        return train[0], train[1], "train_only(fallback_no_valid_segment)"
    return default_start, default_end, "full(fallback_no_dataset_segments)"


def _load_base_index(config: Dict[str, Any], *, start_time: str, end_time: str):
    """Load canonical (datetime, instrument) index from Qlib."""
    from qlib.data import D  # type: ignore

    data_cfg = config.get("data", {}) or {}
    market = data_cfg.get("market", "csi300")
    stock_list = D.instruments(market)
    df = D.features(stock_list, ["$close"], start_time=start_time, end_time=end_time, freq="day")
    df = _to_datetime_instrument_index(df)
    return df.index


def _load_label_series(config: Dict[str, Any], *, start_time: str, end_time: str):
    """Load label series on canonical MultiIndex(datetime, instrument)."""
    from qlib.data import D  # type: ignore

    data_cfg = config.get("data", {}) or {}
    market = data_cfg.get("market", "csi300")
    dataset_cfg = config.get("dataset", {}) or {}
    label_expr = str(dataset_cfg.get("label", "")).strip()
    if not label_expr:
        raise ValueError("dataset.label is empty in backtest config")

    stock_list = D.instruments(market)
    label_df = D.features(stock_list, [label_expr], start_time=start_time, end_time=end_time, freq="day")
    label_df = _to_datetime_instrument_index(label_df)
    if label_df.shape[1] != 1:
        raise ValueError("label feature load returned unexpected shape")
    series = label_df.iloc[:, 0]
    series.name = "label"
    return series.astype(np.float64)


def _parse_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            x = float(v)
            if math.isnan(x) or math.isinf(x):
                return None
            return x
        if isinstance(v, str) and v.strip():
            x = float(v)
            if math.isnan(x) or math.isinf(x):
                return None
            return x
    except Exception:
        return None
    return None


@dataclass
class Candidate:
    factor_id: str
    factor_name: str
    factor_expression: str
    backtest_results: Dict[str, Any]
    factor_info: Dict[str, Any]
    stage1_score: float
    stage2_score: float = float("-inf")
    stage2_metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExprDedupStats:
    method: str
    input_total: int
    input_with_expr: int
    kept_unique: int
    dropped_empty_expr: int
    duplicates_removed: int
    ast_parse_failed: int


def _metric_from_bt(backtest_results: Dict[str, Any], keys: Tuple[str, ...], contains: Tuple[str, ...] = ()) -> Optional[float]:
    if not isinstance(backtest_results, dict):
        return None

    for key in keys:
        x = _parse_float(backtest_results.get(key))
        if x is not None:
            return x

    if contains:
        for k, v in backtest_results.items():
            lk = str(k).lower()
            if any(token in lk for token in contains):
                x = _parse_float(v)
                if x is not None:
                    return x
    return None


def _score_stage1(backtest_results: Dict[str, Any], score_key: str) -> float:
    keys = (score_key, "1day.excess_return_with_cost.information_ratio", "1day.excess_return_without_cost.information_ratio",
            "Rank ICIR", "ICIR", "Rank IC", "IC", "1day.excess_return_with_cost.annualized_return",
            "1day.excess_return_without_cost.annualized_return")
    x = _metric_from_bt(backtest_results, keys)
    return x if x is not None else float("-inf")


def _dedup_factor_items_by_expression(
    factor_items: List[Tuple[str, Dict[str, Any]]],
    *,
    method: str,
    score_key: str,
) -> Tuple[List[Tuple[str, Dict[str, Any]]], ExprDedupStats]:
    """
    Exact-like dedup by expression fingerprint before correlation dedup.

    method:
      - "none": no-op
      - "norm": whitespace-normalized expression string
      - "ast": AST-canonicalized expression (commutative+associative canonicalization)
    Keep rule:
      - pick the factor with best stage1 score within the same fingerprint group
      - tie-breaker: keep the earliest occurrence (stable)
    """
    method_lc = str(method or "none").strip().lower()
    if method_lc == "none":
        stats = ExprDedupStats(
            method="none",
            input_total=len(factor_items),
            input_with_expr=len([1 for _, info in factor_items if str((info or {}).get("factor_expression") or "").strip()]),
            kept_unique=len(factor_items),
            dropped_empty_expr=len([1 for _, info in factor_items if not str((info or {}).get("factor_expression") or "").strip()]),
            duplicates_removed=0,
            ast_parse_failed=0,
        )
        return factor_items, stats

    if method_lc not in {"norm", "ast"}:
        raise ValueError(f"Invalid --expr-dedup-method: {method}")

    from quantaalpha.utils.expression_fingerprint import normalize_expression, try_ast_canonical_expression

    best_by_fp: Dict[str, Tuple[int, float, str, Dict[str, Any]]] = {}
    # fp -> (first_idx, score, factor_id, info)

    input_with_expr = 0
    dropped_empty = 0
    ast_failed = 0

    for idx, (factor_id, info) in enumerate(factor_items):
        if not isinstance(info, dict):
            continue
        expr = str(info.get("factor_expression") or "").strip()
        if not expr:
            dropped_empty += 1
            continue
        input_with_expr += 1

        if method_lc == "norm":
            fp = normalize_expression(expr)
        else:
            res = try_ast_canonical_expression(expr)
            fp = res.canonical
            if not res.ok:
                ast_failed += 1

        score = _score_stage1(info.get("backtest_results") or {}, score_key)

        cur = best_by_fp.get(fp)
        if cur is None:
            best_by_fp[fp] = (idx, float(score), str(factor_id), info)
            continue

        cur_idx, cur_score, _, _ = cur
        if float(score) > float(cur_score):
            best_by_fp[fp] = (idx, float(score), str(factor_id), info)
        elif float(score) == float(cur_score) and idx < cur_idx:
            best_by_fp[fp] = (idx, float(score), str(factor_id), info)

    kept = [(fid, info) for (idx, score, fid, info) in sorted(best_by_fp.values(), key=lambda x: x[0])]
    duplicates_removed = max(0, input_with_expr - len(kept))

    stats = ExprDedupStats(
        method=method_lc,
        input_total=len(factor_items),
        input_with_expr=input_with_expr,
        kept_unique=len(kept),
        dropped_empty_expr=dropped_empty,
        duplicates_removed=duplicates_removed,
        ast_parse_failed=ast_failed,
    )
    return kept, stats


def _capacity_penalty(backtest_results: Dict[str, Any]) -> float:
    turnover = _metric_from_bt(
        backtest_results,
        (
            "1day.turnover",
            "turnover",
            "average_turnover",
            "portfolio_turnover",
        ),
        contains=("turnover",),
    )
    if turnover is None:
        return 1.0
    return 1.0 / (1.0 + max(turnover, 0.0))


def _sample_index(full_index, sample_size: int, seed: int):
    if sample_size <= 0:
        raise ValueError("--sample-size must be > 0")
    n = len(full_index)
    if n == 0:
        raise ValueError("Empty base index (check Qlib data / config range)")
    if sample_size >= n:
        return full_index
    rng = np.random.default_rng(seed)
    picked = np.sort(rng.choice(n, size=sample_size, replace=False))
    return full_index.take(picked)


def _rank_columns_spearman_corr(x: np.ndarray, min_periods: int) -> np.ndarray:
    """Pearson corr of ranks (column-wise Spearman)."""
    import pandas as pd  # type: ignore

    df = pd.DataFrame(x)
    ranked = df.rank(axis=0, method="average", na_option="keep")
    corr = ranked.corr(method="pearson", min_periods=min_periods)
    return corr.to_numpy(dtype=np.float64, copy=True)


def _connected_components_from_adj(adj: List[List[int]]) -> List[List[int]]:
    n = len(adj)
    seen = [False] * n
    comps: List[List[int]] = []
    for i in range(n):
        if seen[i]:
            continue
        stack = [i]
        seen[i] = True
        comp: List[int] = []
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if not seen[v]:
                    seen[v] = True
                    stack.append(v)
        comps.append(comp)
    return comps


def _cluster_with_connected_components(corr: np.ndarray, threshold: float) -> List[List[int]]:
    n = int(corr.shape[0])
    adj: List[List[int]] = [[] for _ in range(n)]
    for a in range(n):
        for b in range(a + 1, n):
            c = corr[a, b]
            if np.isfinite(c) and abs(c) >= threshold:
                adj[a].append(b)
                adj[b].append(a)
    return _connected_components_from_adj(adj)


def _cluster_with_complete_linkage(corr: np.ndarray, threshold: float) -> Tuple[List[List[int]], str]:
    """
    Cluster by complete-linkage with distance = 1 - |corr|.
    Falls back to connected-components when scipy is unavailable.
    """
    try:
        from scipy.cluster.hierarchy import fcluster, linkage  # type: ignore
        from scipy.spatial.distance import squareform  # type: ignore
    except Exception:
        return _cluster_with_connected_components(corr, threshold), "connected(fallback_no_scipy)"

    sim = np.abs(np.nan_to_num(corr, nan=0.0, posinf=1.0, neginf=1.0))
    sim = (sim + sim.T) / 2.0
    np.fill_diagonal(sim, 1.0)

    dist = 1.0 - sim
    dist = np.clip(dist, 0.0, 1.0)
    np.fill_diagonal(dist, 0.0)

    n = dist.shape[0]
    if n <= 1:
        return [[0]] if n == 1 else [], "complete"

    condensed = squareform(dist, checks=False)
    tree = linkage(condensed, method="complete")
    labels = fcluster(tree, t=max(0.0, 1.0 - threshold), criterion="distance")

    groups: Dict[int, List[int]] = {}
    for i, lab in enumerate(labels.tolist()):
        groups.setdefault(int(lab), []).append(i)
    comps = list(groups.values())
    return comps, "complete"


def _cluster_indices(corr: np.ndarray, threshold: float, linkage_mode: str) -> Tuple[List[List[int]], str]:
    if linkage_mode == "connected":
        return _cluster_with_connected_components(corr, threshold), "connected"
    return _cluster_with_complete_linkage(corr, threshold)


def _pick_by_cluster(
    components: List[List[int]],
    scores: List[float],
    per_cluster: int,
    topn: Optional[int] = None,
) -> List[int]:
    selected_idx: List[int] = []
    for comp in components:
        sorted_comp = sorted(comp, key=lambda i: scores[i], reverse=True)
        selected_idx.extend(sorted_comp[:per_cluster])

    uniq = sorted(set(selected_idx), key=lambda i: scores[i], reverse=True)
    if topn is None or topn <= 0:
        return uniq
    return uniq[:topn]


def _load_factor_series(calc: Any, factor_name: str, factor_expression: str, factor_info: Dict[str, Any], compute_missing: bool):
    """Load one factor series from cache/calc and standardize index."""
    series = None
    cache_location = factor_info.get("cache_location") or {}
    if isinstance(cache_location, dict) and cache_location:
        series = calc._load_from_cache_location(cache_location)
    if series is None:
        series = calc._load_from_cache(factor_expression)

    if series is None and compute_missing:
        series = calc.calculate_factor(factor_name, factor_expression)
        if series is not None:
            calc._save_to_cache(factor_expression, series)

    if series is None:
        return None

    try:
        series = _to_datetime_instrument_index(series)
        return series.astype(np.float64)
    except Exception:
        return None


def _materialize_vector(series, sampled_index, min_coverage: float) -> Optional[np.ndarray]:
    try:
        sampled = series.reindex(sampled_index)
        vec = sampled.to_numpy(dtype=np.float64, copy=False)
        finite = np.isfinite(vec)
        coverage = float(finite.mean()) if len(vec) else 0.0
        if coverage < min_coverage:
            return None
        return vec
    except Exception:
        return None


def _compute_rank_ic_series(feature_series, label_series, min_instruments: int):
    """Compute daily cross-sectional Spearman RankIC series."""
    import pandas as pd  # type: ignore

    merged = pd.DataFrame({"factor": feature_series, "label": label_series}).dropna()
    if merged.empty:
        return pd.Series(dtype=np.float64)

    def _day_ic(day_df):
        if len(day_df) < min_instruments:
            return np.nan
        return day_df["factor"].corr(day_df["label"], method="spearman")

    ic = merged.groupby(level=0, sort=True).apply(_day_ic)
    ic.index.name = "datetime"
    return ic.astype(np.float64)


def _build_stage2_metrics(ic_series, total_days: int, capacity_penalty: float) -> Dict[str, Any]:
    arr = ic_series.to_numpy(dtype=np.float64, copy=False)
    finite = np.isfinite(arr)
    n_valid = int(finite.sum())
    valid = arr[finite]

    if n_valid == 0:
        return {
            "n_days": 0,
            "coverage": 0.0,
            "mean_ic": 0.0,
            "std_ic": 0.0,
            "ir": 0.0,
            "ic_positive_ratio": 0.0,
            "stability": 0.0,
            "capacity_penalty": float(capacity_penalty),
            "composite_score": 0.0,
        }

    mean_ic = float(np.mean(valid))
    std_ic = float(np.std(valid, ddof=1)) if n_valid > 1 else 0.0
    if std_ic <= 1e-12:
        ir = 0.0
    else:
        ir = float(mean_ic / std_ic)
    pos_ratio = float(np.mean(valid > 0.0))
    stability = max(pos_ratio, 1.0 - pos_ratio)
    coverage = float(n_valid / max(total_days, 1))
    score = abs(mean_ic) * max(ir, 0.0) * coverage * stability * float(capacity_penalty)

    return {
        "n_days": n_valid,
        "coverage": coverage,
        "mean_ic": mean_ic,
        "std_ic": std_ic,
        "ir": ir,
        "ic_positive_ratio": pos_ratio,
        "stability": stability,
        "capacity_penalty": float(capacity_penalty),
        "composite_score": float(score),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Select diverse Top-N factors for backtest.")
    parser.add_argument("--library", required=True, help="Input factor library JSON path")
    parser.add_argument("--config", default="configs/backtest.yaml", help="Backtest config YAML")
    parser.add_argument("--out", required=True, help="Output factor library JSON path")
    parser.add_argument(
        "--expr-dedup-method",
        choices=("none", "norm", "ast"),
        default="none",
        help="Stage-0 expression dedup before correlation dedup. norm=whitespace; ast=AST canonical.",
    )
    parser.add_argument("--out-stage1", default="", help="Optional output library after expression dedup stage")
    parser.add_argument(
        "--out-stage2",
        default="",
        help="Optional output library after exposure corr stage (before IC-series stage)",
    )

    parser.add_argument(
        "--topn",
        type=int,
        default=80,
        help="Final number of factors to keep (<=0 means no final cap).",
    )
    parser.add_argument("--per-cluster", type=int, default=1, help="Keep K champions per cluster")

    parser.add_argument(
        "--dedup-method",
        choices=("stage1", "two_stage"),
        default="two_stage",
        help="stage1: exposure corr only; two_stage: exposure corr then IC-series corr",
    )
    parser.add_argument(
        "--cluster-linkage",
        choices=("complete", "connected"),
        default="complete",
        help="Cluster linkage mode for corr dedup.",
    )

    parser.add_argument("--corr-threshold", type=float, default=0.8, help="Stage-1 corr threshold on |Spearman corr|")
    parser.add_argument("--sample-size", type=int, default=8000, help="Stage-1 sampled rows for exposure corr")
    parser.add_argument(
        "--sample-split",
        choices=("train_valid", "full"),
        default="train_valid",
        help="Sampling scope for dedup corr. train_valid avoids test leakage.",
    )

    parser.add_argument(
        "--stage2-ic-corr-threshold",
        type=float,
        default=0.8,
        help="Stage-2 corr threshold on |corr(IC-series)|",
    )
    parser.add_argument(
        "--stage2-min-instruments",
        type=int,
        default=20,
        help="Min instruments per day for one RankIC observation",
    )
    parser.add_argument(
        "--stage2-min-periods",
        type=int,
        default=60,
        help="Min overlapping days when computing factor-factor corr on IC series",
    )

    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    parser.add_argument(
        "--score-key",
        default="1day.excess_return_with_cost.information_ratio",
        help="Primary score key used in stage-1 ranking",
    )
    parser.add_argument("--compute-missing", action="store_true", help="Compute/cache factor values when missing")
    parser.add_argument("--cache-dir", default="", help="Optional factor cache dir")
    parser.add_argument("--min-periods", type=int, default=2000, help="Stage-1 min paired rows for corr")
    parser.add_argument("--min-coverage", type=float, default=0.2, help="Min non-NaN coverage for stage-1 vector")
    parser.add_argument("--max-candidates", type=int, default=0, help="Optional cap on candidates (0 = no cap)")
    parser.add_argument("--report", default="", help="Optional report JSON path")
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be done")

    args = parser.parse_args()

    library_path = Path(args.library)
    if not library_path.exists():
        raise SystemExit(f"Library not found: {library_path}")
    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"Config not found: {config_path}")

    if args.per_cluster <= 0:
        raise SystemExit("--per-cluster must be > 0")
    if not (0.0 < args.corr_threshold <= 1.0):
        raise SystemExit("--corr-threshold must be in (0,1]")
    if not (0.0 < args.stage2_ic_corr_threshold <= 1.0):
        raise SystemExit("--stage2-ic-corr-threshold must be in (0,1]")
    if args.sample_size <= 0:
        raise SystemExit("--sample-size must be > 0")
    if args.min_periods <= 10:
        raise SystemExit("--min-periods must be > 10")
    if args.stage2_min_periods <= 10:
        raise SystemExit("--stage2-min-periods must be > 10")
    if args.stage2_min_instruments <= 1:
        raise SystemExit("--stage2-min-instruments must be > 1")

    config = _load_yaml(config_path)
    _init_qlib(config)

    data = json.loads(library_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid library JSON: {library_path}")
    factors = data.get("factors", {}) or {}
    if not isinstance(factors, dict):
        raise SystemExit(f"Invalid factors payload in: {library_path}")

    factor_items = list(factors.items())
    if args.max_candidates and args.max_candidates > 0:
        factor_items = factor_items[: args.max_candidates]

    factor_items, expr_stats = _dedup_factor_items_by_expression(
        factor_items,
        method=args.expr_dedup_method,
        score_key=args.score_key,
    )
    # Always drop empty expressions early (even when expr_dedup_method=none) for stable counts.
    factor_items = [(fid, info) for fid, info in factor_items if str((info or {}).get("factor_expression") or "").strip()]

    print(f"[Input] library={library_path} candidates={len(factor_items)}")
    print(f"[Config] {config_path}")
    print(f"[Dedup] method={args.dedup_method} linkage={args.cluster_linkage}")
    if expr_stats.method != "none" or args.out_stage1:
        print(
            "[ExprDedup] "
            f"method={expr_stats.method} input_total={expr_stats.input_total} "
            f"input_with_expr={expr_stats.input_with_expr} kept_unique={expr_stats.kept_unique} "
            f"duplicates_removed={expr_stats.duplicates_removed} ast_parse_failed={expr_stats.ast_parse_failed}"
        )

    sample_start, sample_end, sample_window_source = _resolve_sample_window(config, args.sample_split)
    full_index = _load_base_index(config, start_time=sample_start, end_time=sample_end)
    sample_idx = _sample_index(full_index, args.sample_size, args.seed)
    print(
        "[Sample] "
        f"split={args.sample_split} "
        f"window={sample_start}~{sample_end} "
        f"source={sample_window_source} "
        f"size={len(sample_idx)} (from base_index={len(full_index)}) seed={args.seed}"
    )

    if args.dry_run:
        print("[DryRun] exit (no selection performed)")
        return 0

    if args.out_stage1:
        stage1_factors = {fid: info for fid, info in factor_items if isinstance(info, dict)}
        _write_factor_library_json(
            Path(args.out_stage1),
            base_meta=(data.get("metadata") or {}) if isinstance(data.get("metadata"), dict) else {},
            factors=stage1_factors,
            extra_meta={
                "selection_stage": "stage1_expression_dedup",
                "expr_dedup": expr_stats.__dict__,
                "source_library": str(library_path),
            },
        )
        print(f"[Stage1] wrote {len(stage1_factors)} factors -> {args.out_stage1}")

    from quantaalpha.backtest.custom_factor_calculator import CustomFactorCalculator

    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    calc = CustomFactorCalculator(data_df=None, config=config, auto_extract_cache=True, cache_dir=cache_dir)
    try:
        calc._auto_extract_cache_from_logs()
    except Exception:
        pass

    # ----------------------
    # Stage-1: exposure corr
    # ----------------------
    candidates: List[Candidate] = []
    vectors: List[np.ndarray] = []
    dropped_missing = 0

    for i, (factor_id, info) in enumerate(factor_items, start=1):
        if not isinstance(info, dict):
            continue

        name = str(info.get("factor_name") or factor_id)
        expr = str(info.get("factor_expression") or "")
        if not expr.strip():
            continue

        series = _load_factor_series(calc, name, expr, info, compute_missing=args.compute_missing)
        if series is None:
            dropped_missing += 1
            continue

        vec = _materialize_vector(series, sample_idx, args.min_coverage)
        if vec is None:
            dropped_missing += 1
            continue

        stage1_score = _score_stage1(info.get("backtest_results") or {}, args.score_key)
        candidates.append(
            Candidate(
                factor_id=str(factor_id),
                factor_name=name,
                factor_expression=expr,
                backtest_results=info.get("backtest_results") or {},
                factor_info=info,
                stage1_score=float(stage1_score),
            )
        )
        vectors.append(vec)

        if i % 20 == 0 or i == 1 or i == len(factor_items):
            print(f"[Load] {i}/{len(factor_items)} kept={len(candidates)} dropped_missing={dropped_missing}")

    min_required = max(5, args.topn) if args.topn > 0 else 5
    if len(candidates) < min_required:
        raise SystemExit(f"Too few usable factors after cache/missing filtering: kept={len(candidates)}")

    x = np.stack(vectors, axis=1)
    corr_stage1 = _rank_columns_spearman_corr(x, min_periods=min(args.min_periods, len(sample_idx)))
    clusters_stage1, linkage_used_stage1 = _cluster_indices(corr_stage1, args.corr_threshold, args.cluster_linkage)
    stage1_scores = [c.stage1_score for c in candidates]
    # Professional workflow: Stage-1 is coarse dedup only; do not truncate by final TopN here.
    selected_stage1 = _pick_by_cluster(clusters_stage1, stage1_scores, args.per_cluster, topn=None)
    print(
        f"[Stage1] threshold={args.corr_threshold} linkage={linkage_used_stage1} "
        f"clusters={len(clusters_stage1)} candidates={len(candidates)} pool={len(selected_stage1)}"
    )
    exposure_pool = [candidates[i] for i in selected_stage1]

    if args.out_stage2:
        stage2_factors = {c.factor_id: c.factor_info for c in exposure_pool}
        _write_factor_library_json(
            Path(args.out_stage2),
            base_meta=(data.get("metadata") or {}) if isinstance(data.get("metadata"), dict) else {},
            factors=stage2_factors,
            extra_meta={
                "selection_stage": "stage2_exposure_corr",
                "expr_dedup": expr_stats.__dict__,
                "source_library": str(library_path),
                "selection_snapshot": {
                    "cluster_linkage_used": linkage_used_stage1,
                    "corr_threshold": args.corr_threshold,
                    "per_cluster": args.per_cluster,
                    "candidates_total": len(factor_items),
                    "kept_usable": len(candidates),
                    "dropped_missing_or_low_coverage": dropped_missing,
                    "clusters": len(clusters_stage1),
                    "selected": len(exposure_pool),
                },
            },
        )
        print(f"[Stage2] wrote {len(stage2_factors)} factors -> {args.out_stage2}")

    # ----------------------
    # Stage-2: IC series corr
    # ----------------------
    final_candidates: List[Candidate]
    clusters_stage2: List[List[int]] = []
    linkage_used_stage2 = "n/a"
    stage2_dropped = 0

    if args.dedup_method == "two_stage":
        label_series = _load_label_series(config, start_time=sample_start, end_time=sample_end)
        total_days = int(label_series.index.get_level_values(0).nunique())

        stage2_pool: List[Candidate] = []
        ic_series_map: Dict[str, Any] = {}

        for cand in exposure_pool:
            series = _load_factor_series(
                calc,
                cand.factor_name,
                cand.factor_expression,
                cand.factor_info,
                compute_missing=args.compute_missing,
            )
            if series is None:
                stage2_dropped += 1
                continue

            series = series.reindex(label_series.index)
            ic_series = _compute_rank_ic_series(series, label_series, args.stage2_min_instruments)
            metrics = _build_stage2_metrics(
                ic_series,
                total_days=total_days,
                capacity_penalty=_capacity_penalty(cand.backtest_results),
            )
            if metrics["n_days"] <= 0:
                stage2_dropped += 1
                continue

            cand.stage2_metrics = metrics
            cand.stage2_score = float(metrics["composite_score"])
            stage2_pool.append(cand)
            ic_series_map[cand.factor_id] = ic_series

        if len(stage2_pool) >= 2:
            import pandas as pd  # type: ignore

            ic_df = pd.DataFrame(ic_series_map)
            corr_df = ic_df.corr(method="spearman", min_periods=min(args.stage2_min_periods, len(ic_df)))
            corr_stage2 = corr_df.to_numpy(dtype=np.float64, copy=True)
            clusters_stage2, linkage_used_stage2 = _cluster_indices(
                corr_stage2,
                args.stage2_ic_corr_threshold,
                args.cluster_linkage,
            )
            stage2_scores = [c.stage2_score for c in stage2_pool]
            selected_stage2 = _pick_by_cluster(
                clusters_stage2,
                stage2_scores,
                args.per_cluster,
                topn=args.topn if args.topn > 0 else None,
            )
            final_candidates = [stage2_pool[i] for i in selected_stage2]
            print(
                f"[Stage2] threshold={args.stage2_ic_corr_threshold} linkage={linkage_used_stage2} "
                f"pool={len(stage2_pool)} dropped={stage2_dropped} clusters={len(clusters_stage2)} "
                f"selected={len(final_candidates)}"
            )
        else:
            print("[Stage2] pool too small after IC construction, fallback to Stage1 selection")
            final_candidates = exposure_pool[: args.topn] if args.topn > 0 else exposure_pool
    else:
        final_candidates = exposure_pool

    # ----------------------
    # Output
    # ----------------------
    final_candidates = sorted(
        final_candidates,
        key=lambda c: c.stage2_score if args.dedup_method == "two_stage" else c.stage1_score,
        reverse=True,
    )
    if args.topn > 0:
        final_candidates = final_candidates[: args.topn]

    selected_factors: Dict[str, Any] = {}
    for cand in final_candidates:
        selected_factors[cand.factor_id] = cand.factor_info

    selection_meta: Dict[str, Any] = {
        "method": "two_stage_exposure_then_ic_corr_topn" if args.dedup_method == "two_stage" else "stage1_exposure_corr_topn",
        "dedup_method": args.dedup_method,
        "expr_dedup": expr_stats.__dict__,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "input_library": str(library_path),
        "config": str(config_path),
        "requested_topn": args.topn,
        "final_selected": len(selected_factors),
        "sample_split": args.sample_split,
        "sample_window_start": sample_start,
        "sample_window_end": sample_end,
        "sample_window_source": sample_window_source,
        "seed": args.seed,
        "cluster_linkage_requested": args.cluster_linkage,
        "stage1": {
            "stage": "stage1_exposure_corr",
            "corr_threshold": args.corr_threshold,
            "sample_size": int(len(sample_idx)),
            "min_periods": args.min_periods,
            "score_key": args.score_key,
            "per_cluster": args.per_cluster,
            "candidates_total": len(factor_items),
            "kept_usable": len(candidates),
            "dropped_missing_or_low_coverage": dropped_missing,
            "clusters": len(clusters_stage1),
            "selected": len(selected_stage1),
            "selected_for_stage2": len(selected_stage1),
            "cluster_linkage_used": linkage_used_stage1,
        },
    }

    if args.dedup_method == "two_stage":
        selection_meta["stage2"] = {
            "stage": "stage2_ic_series_corr",
            "corr_threshold": args.stage2_ic_corr_threshold,
            "min_instruments": args.stage2_min_instruments,
            "min_periods": args.stage2_min_periods,
            "clusters": len(clusters_stage2),
            "dropped_before_stage2": stage2_dropped,
            "cluster_linkage_used": linkage_used_stage2,
            "score_formula": "abs(mean_ic)*max(ir,0)*coverage*stability*capacity_penalty",
        }

    out_data = {
        "metadata": {
            **(data.get("metadata") or {}),
            "selection": selection_meta,
            "total_factors": len(selected_factors),
        },
        "factors": selected_factors,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Output] wrote {len(selected_factors)} factors -> {out_path}")

    if args.report:
        report_payload = {
            "selection": selection_meta,
            "final_ranked": [
                {
                    "rank": i + 1,
                    "factor_id": c.factor_id,
                    "factor_name": c.factor_name,
                    "stage1_score": c.stage1_score,
                    "stage2_score": c.stage2_score,
                    "stage2_metrics": c.stage2_metrics,
                }
                for i, c in enumerate(final_candidates)
            ],
        }
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Report] wrote -> {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
