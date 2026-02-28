#!/usr/bin/env python3
"""
Select a smaller, diverse subset of factors from a factor library JSON.

Goal: make "Top-N" on a laptop less lossy by (1) correlation de-dup, then (2) rank.

Method (pragmatic):
1) For each factor, load a sample vector of factor values (from cache_location result.h5,
   or MD5 cache under data/results/factor_cache, optionally compute and cache if missing).
2) Compute Spearman correlation between factors on the sampled panel values.
3) Build clusters using a simple threshold graph: edge if |corr| >= threshold.
4) Pick up to K champions per cluster (by a score from factor backtest_results).
5) Globally rank champions and keep Top-N.

This does NOT "merge" multi-factor LGBM training; it only produces a smaller JSON library
that you can backtest with the existing backtest runner.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def _load_yaml(path: Path) -> Dict[str, Any]:
    import yaml  # type: ignore

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML (expected mapping): {path}")
    return data


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


def _load_base_index(config: Dict[str, Any]):
    """
    Load the canonical (datetime, instrument) index from Qlib to sample on.
    Kept minimal to avoid holding all raw fields in memory.
    """
    import pandas as pd  # type: ignore
    from qlib.data import D  # type: ignore

    data_cfg = config.get("data", {}) or {}
    market = data_cfg.get("market", "csi300")
    start_time = data_cfg.get("start_time", "2016-01-01")
    end_time = data_cfg.get("end_time", "2025-12-31")
    stock_list = D.instruments(market)
    df = D.features(stock_list, ["$close"], start_time=start_time, end_time=end_time, freq="day")
    idx = df.index
    if isinstance(idx, pd.MultiIndex) and idx.nlevels == 2:
        # Qlib uses (instrument, datetime) by default; we standardize to (datetime, instrument).
        idx = idx.swaplevel(0, 1).sort_values()
        idx = idx.set_names(["datetime", "instrument"])
    return idx


def _parse_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            if math.isnan(float(v)) or math.isinf(float(v)):
                return None
            return float(v)
        if isinstance(v, str) and v.strip():
            x = float(v)
            if math.isnan(x) or math.isinf(x):
                return None
            return x
    except Exception:
        return None
    return None


@dataclass(frozen=True)
class Candidate:
    factor_id: str
    factor_name: str
    factor_expression: str
    score: float
    backtest_results: Dict[str, Any]
    factor_info: Dict[str, Any]


def _score_factor(backtest_results: Dict[str, Any], score_key: str) -> float:
    """
    Score used for selecting champions and global Top-N.
    Default uses '1day.excess_return_with_cost.information_ratio' when present.
    """
    if not isinstance(backtest_results, dict):
        backtest_results = {}

    # Common fallbacks in these libraries.
    keys = [score_key]
    if score_key != "1day.excess_return_with_cost.information_ratio":
        keys.append("1day.excess_return_with_cost.information_ratio")
    keys.extend(
        [
            "1day.excess_return_without_cost.information_ratio",
            "Rank ICIR",
            "ICIR",
            "Rank IC",
            "IC",
            "1day.excess_return_with_cost.annualized_return",
            "1day.excess_return_without_cost.annualized_return",
        ]
    )
    for k in keys:
        x = _parse_float(backtest_results.get(k))
        if x is not None:
            return x
    return float("-inf")


def _load_library(path: Path) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid library JSON: {path}")
    factors = data.get("factors", {}) or {}
    if not isinstance(factors, dict):
        raise ValueError(f"Invalid 'factors' in library JSON: {path}")
    return data, factors


def _sample_index(full_index, sample_size: int, seed: int):
    if sample_size <= 0:
        raise ValueError("--sample-size must be > 0")
    n = len(full_index)
    if n == 0:
        raise ValueError("Empty base index (check Qlib data / config range)")
    if sample_size >= n:
        return full_index
    rng = np.random.default_rng(seed)
    idx = rng.choice(n, size=sample_size, replace=False)
    idx = np.sort(idx)
    try:
        return full_index.take(idx)
    except Exception:
        # Fallback for non-pandas index
        return np.asarray(full_index)[idx]


def _rank_columns_spearman_corr(x: np.ndarray, min_periods: int) -> np.ndarray:
    """
    x: shape (n_samples, n_factors), float with NaNs.
    Returns corr matrix (n_factors, n_factors) computed as Pearson corr of ranks.
    """
    import pandas as pd  # type: ignore

    df = pd.DataFrame(x)
    ranked = df.rank(axis=0, method="average", na_option="keep")
    corr = ranked.corr(method="pearson", min_periods=min_periods)
    return corr.to_numpy(dtype=np.float64, copy=True)


def _connected_components(adj: List[List[int]]) -> List[List[int]]:
    n = len(adj)
    seen = [False] * n
    comps: List[List[int]] = []
    for i in range(n):
        if seen[i]:
            continue
        stack = [i]
        seen[i] = True
        comp = []
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if not seen[v]:
                    seen[v] = True
                    stack.append(v)
        comps.append(comp)
    return comps


def main() -> int:
    parser = argparse.ArgumentParser(description="Select diverse Top-N factors (de-dup then rank).")
    parser.add_argument("--library", required=True, help="Input factor library JSON path")
    parser.add_argument(
        "--config",
        default="configs/backtest_limited.yaml",
        help="Backtest config YAML (used for Qlib data range/market)",
    )
    parser.add_argument("--out", required=True, help="Output factor library JSON path")
    parser.add_argument("--topn", type=int, default=80, help="Final number of factors to keep")
    parser.add_argument("--per-cluster", type=int, default=1, help="Keep K champions per cluster before global Top-N")
    parser.add_argument("--corr-threshold", type=float, default=0.8, help="Cluster edge threshold on |Spearman corr|")
    parser.add_argument("--sample-size", type=int, default=8000, help="Number of (dt,inst) rows to sample for corr")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    parser.add_argument(
        "--score-key",
        default="1day.excess_return_with_cost.information_ratio",
        help="Primary score key in factor backtest_results",
    )
    parser.add_argument(
        "--compute-missing",
        action="store_true",
        help="Compute and cache factor values if not found in cache_location/MD5 cache",
    )
    parser.add_argument(
        "--cache-dir",
        default="",
        help="Optional factor cache dir (MD5 cache: parquet preferred, pkl fallback). Default uses data/results/factor_cache or FACTOR_CACHE_DIR env.",
    )
    parser.add_argument(
        "--min-periods",
        type=int,
        default=2000,
        help="Min paired samples for corr; lowers spurious edges when many NaNs",
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.2,
        help="Min non-NaN coverage on sampled index required to accept a cached series",
    )
    parser.add_argument("--max-candidates", type=int, default=0, help="Optional cap on candidates (0 = no cap)")
    parser.add_argument("--report", default="", help="Optional report JSON path (clusters, scores, selection)")
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be done")

    args = parser.parse_args()

    library_path = Path(args.library)
    if not library_path.exists():
        raise SystemExit(f"Library not found: {library_path}")
    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"Config not found: {config_path}")
    out_path = Path(args.out)

    if args.topn <= 0:
        raise SystemExit("--topn must be > 0")
    if args.per_cluster <= 0:
        raise SystemExit("--per-cluster must be > 0")
    if not (0.0 < args.corr_threshold <= 1.0):
        raise SystemExit("--corr-threshold must be in (0, 1]")
    if args.min_periods <= 10:
        raise SystemExit("--min-periods must be > 10")

    config = _load_yaml(config_path)
    _init_qlib(config)

    lib_root, factors = _load_library(library_path)
    factor_items = list(factors.items())
    if args.max_candidates and args.max_candidates > 0:
        factor_items = factor_items[: args.max_candidates]

    print(f"[Input] library={library_path} candidates={len(factor_items)}")
    print(f"[Config] {config_path}")

    full_index = _load_base_index(config)
    sample_idx = _sample_index(full_index, args.sample_size, args.seed)
    print(f"[Sample] size={len(sample_idx)} (from base_index={len(full_index)}) seed={args.seed}")

    if args.dry_run:
        print("[DryRun] exit (no selection performed)")
        return 0

    from quantaalpha.backtest.custom_factor_calculator import CustomFactorCalculator

    cache_dir = None
    if args.cache_dir:
        cache_dir = Path(args.cache_dir)
    calc = CustomFactorCalculator(data_df=None, config=config, auto_extract_cache=True, cache_dir=cache_dir)
    # Try to extract caches once; cheap when nothing to extract.
    try:
        calc._auto_extract_cache_from_logs()
    except Exception:
        pass

    kept: List[Candidate] = []
    vectors: List[np.ndarray] = []
    dropped_missing = 0

    for i, (factor_id, info) in enumerate(factor_items, start=1):
        if not isinstance(info, dict):
            continue
        name = str(info.get("factor_name") or factor_id)
        expr = str(info.get("factor_expression") or "")
        if not expr.strip():
            continue

        bt = info.get("backtest_results") or {}
        score = _score_factor(bt, args.score_key)

        series = None
        cache_location = info.get("cache_location") or {}
        if isinstance(cache_location, dict) and cache_location:
            series = calc._load_from_cache_location(cache_location)
        if series is None:
            series = calc._load_from_cache(expr)

        def materialize_vector(s) -> Optional[np.ndarray]:
            try:
                sampled_local = s.reindex(sample_idx)
                vec_local = sampled_local.to_numpy(dtype=np.float64, copy=False)
                finite = np.isfinite(vec_local)
                coverage = float(finite.mean()) if len(vec_local) else 0.0
                if coverage < args.min_coverage:
                    return None
                return vec_local
            except Exception:
                return None

        vec = None
        if series is not None:
            vec = materialize_vector(series)

        if vec is None and args.compute_missing:
            series = calc.calculate_factor(name, expr)
            if series is not None:
                calc._save_to_cache(expr, series)
                vec = materialize_vector(series)

        if vec is None:
            dropped_missing += 1
            continue

        kept.append(
            Candidate(
                factor_id=str(factor_id),
                factor_name=name,
                factor_expression=expr,
                score=float(score),
                backtest_results=bt if isinstance(bt, dict) else {},
                factor_info=info,
            )
        )
        vectors.append(vec)
        # Help GC release large cached Series between iterations.
        series = None

        if i % 20 == 0 or i == 1 or i == len(factor_items):
            print(f"[Load] {i}/{len(factor_items)} kept={len(kept)} dropped_missing={dropped_missing}")

    if len(kept) < max(args.topn, 5):
        raise SystemExit(f"Too few usable factors after cache/missing filtering: kept={len(kept)}")

    x = np.stack(vectors, axis=1)  # (n_samples, n_factors)
    corr = _rank_columns_spearman_corr(x, min_periods=min(args.min_periods, len(sample_idx)))

    n = corr.shape[0]
    adj: List[List[int]] = [[] for _ in range(n)]
    for a in range(n):
        for b in range(a + 1, n):
            c = corr[a, b]
            if np.isfinite(c) and abs(c) >= args.corr_threshold:
                adj[a].append(b)
                adj[b].append(a)

    comps = _connected_components(adj)
    print(f"[Cluster] threshold={args.corr_threshold} clusters={len(comps)} factors={n}")

    # Select champions per cluster.
    selected_idx: List[int] = []
    cluster_picks: List[Dict[str, Any]] = []
    for cid, comp in enumerate(comps):
        comp_sorted = sorted(comp, key=lambda j: kept[j].score, reverse=True)
        picks = comp_sorted[: args.per_cluster]
        selected_idx.extend(picks)
        cluster_picks.append(
            {
                "cluster_id": cid,
                "size": len(comp),
                "picks": [
                    {
                        "factor_id": kept[j].factor_id,
                        "factor_name": kept[j].factor_name,
                        "score": kept[j].score,
                    }
                    for j in picks
                ],
            }
        )

    # Global Top-N across champions.
    uniq = sorted(set(selected_idx), key=lambda j: kept[j].score, reverse=True)
    final = uniq[: args.topn]
    print(f"[Select] champions={len(uniq)} final_topn={len(final)}")

    selected_factors: Dict[str, Any] = {}
    for j in final:
        fid = kept[j].factor_id
        selected_factors[fid] = kept[j].factor_info

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_data = {
        "metadata": {
            **(lib_root.get("metadata") or {}),
            "selection": {
                "method": "dedup_spearman_threshold_then_topn",
                "input_library": str(library_path),
                "config": str(config_path),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "corr_threshold": args.corr_threshold,
                "sample_size": int(len(sample_idx)),
                "seed": args.seed,
                "min_periods": args.min_periods,
                "score_key": args.score_key,
                "per_cluster": args.per_cluster,
                "requested_topn": args.topn,
                "kept_usable": len(kept),
                "dropped_missing_or_all_nan": dropped_missing,
                "clusters": len(comps),
                "final_selected": len(final),
            },
            "total_factors": len(selected_factors),
        },
        "factors": selected_factors,
    }
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Output] wrote {len(selected_factors)} factors -> {out_path}")

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "input_candidates": len(factor_items),
            "usable": len(kept),
            "dropped_missing_or_all_nan": dropped_missing,
            "clusters": cluster_picks,
            "final": [
                {
                    "rank": r + 1,
                    "factor_id": kept[j].factor_id,
                    "factor_name": kept[j].factor_name,
                    "score": kept[j].score,
                }
                for r, j in enumerate(final)
            ],
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Report] wrote -> {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
