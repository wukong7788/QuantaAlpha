#!/usr/bin/env python3
"""
Repair missing factors for a factor library by computing only `need_compute` factors
and writing them into MD5 cache (data/results/factor_cache by default).

Usage:
  .venv/bin/python scripts/fix_missing_factors.py \
    --library data/factorlib/all_factors_library_paper_reproduction_ds.json
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from quantaalpha.backtest.custom_factor_calculator import CustomFactorCalculator
from quantaalpha.factors.library import FactorLibraryManager


def _resolve_library_path(project_root: Path, library: str) -> Path:
    p = Path(library)
    if p.is_file():
        return p.resolve()
    p1 = project_root / "data" / "factorlib" / library
    if p1.is_file():
        return p1
    p2 = project_root / library
    if p2.is_file():
        return p2
    raise FileNotFoundError(f"Factor library not found: {library}")


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML config: {path}")
    return data


def _load_factors_by_id(library_path: Path) -> dict[str, dict[str, Any]]:
    with library_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    factors = data.get("factors", {})
    if not isinstance(factors, dict):
        raise ValueError(f"Invalid factor library format: {library_path}")
    return factors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair missing factors (need_compute) by computing and caching them."
    )
    parser.add_argument(
        "--library",
        required=True,
        help="Factor library JSON filename or path",
    )
    parser.add_argument(
        "--config",
        default="configs/backtest.yaml",
        help="Backtest config YAML (default: configs/backtest.yaml)",
    )
    parser.add_argument(
        "--cache-dir",
        default="data/results/factor_cache",
        help="MD5 cache directory (default: data/results/factor_cache)",
    )
    parser.add_argument(
        "--warm-cache",
        action="store_true",
        help="Warm cache from available result.h5 before computing missing factors",
    )
    parser.add_argument(
        "--report-dir",
        default="log/backtest_manual",
        help="Directory for repair report JSON (default: log/backtest_manual)",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    os.chdir(project_root)

    library_path = _resolve_library_path(project_root, args.library)
    config_path = Path(args.config)
    if not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Repair] library={library_path}")
    print(f"[Repair] config={config_path}")
    print(f"[Repair] cache_dir={cache_dir}")

    before = FactorLibraryManager.check_cache_status(str(library_path), cache_dir=str(cache_dir))
    print(
        f"[Before] total={before['total']} h5={before['h5_cached']} "
        f"md5={before['md5_cached']} need_compute={before['need_compute']}"
    )

    if args.warm_cache:
        warmed = FactorLibraryManager.warm_cache_from_json(str(library_path), cache_dir=str(cache_dir))
        print(f"[Warm] {json.dumps(warmed, ensure_ascii=False)}")
        before = FactorLibraryManager.check_cache_status(str(library_path), cache_dir=str(cache_dir))
        print(
            f"[AfterWarm] total={before['total']} h5={before['h5_cached']} "
            f"md5={before['md5_cached']} need_compute={before['need_compute']}"
        )

    missing_ids = [f["factor_id"] for f in before["factors"] if f["status"] == "need_compute"]
    if not missing_ids:
        print("[Repair] No missing factors. Done.")
        return 0

    all_factors = _load_factors_by_id(library_path)
    target_factors: list[dict[str, Any]] = []
    for fid in missing_ids:
        info = all_factors.get(fid, {})
        expr = info.get("factor_expression", "")
        if not expr:
            continue
        item = {
            "factor_id": fid,
            "factor_name": info.get("factor_name", fid),
            "factor_expression": expr,
            "factor_description": info.get("factor_description", ""),
        }
        cloc = info.get("cache_location")
        if cloc:
            item["cache_location"] = cloc
        target_factors.append(item)

    print(f"[Repair] missing candidates={len(missing_ids)}, computable={len(target_factors)}")
    if not target_factors:
        print("[Repair] No computable missing factors found (empty expressions).")
        return 1

    cfg = _load_yaml(config_path)
    cfg.setdefault("llm", {})
    cfg["llm"]["cache_dir"] = str(cache_dir)

    calculator = CustomFactorCalculator(
        data_df=None,
        cache_dir=cache_dir,
        auto_extract_cache=bool(cfg.get("llm", {}).get("auto_extract_cache", False)),
        config=cfg,
    )
    result_df = calculator.calculate_factors_batch(target_factors, use_cache=True, skip_compute=False)
    repaired_names = set(result_df.columns.tolist()) if result_df is not None and not result_df.empty else set()

    after = FactorLibraryManager.check_cache_status(str(library_path), cache_dir=str(cache_dir))
    print(
        f"[After] total={after['total']} h5={after['h5_cached']} "
        f"md5={after['md5_cached']} need_compute={after['need_compute']}"
    )

    failed = []
    for f in target_factors:
        if f["factor_name"] not in repaired_names:
            failed.append(f["factor_name"])

    report = {
        "library": str(library_path),
        "config": str(config_path),
        "cache_dir": str(cache_dir),
        "timestamp": datetime.now().isoformat(),
        "before": before,
        "after": after,
        "requested_missing_factor_ids": missing_ids,
        "requested_missing_factor_names": [f["factor_name"] for f in target_factors],
        "repaired_factor_names": sorted(repaired_names),
        "failed_factor_names": failed,
    }

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / f"fix_missing_{library_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Repair] report={report_file}")

    if after["need_compute"] > before["need_compute"]:
        print("[Repair] Warning: need_compute increased unexpectedly.")
        return 2

    if failed:
        print(f"[Repair] Completed with partial failures: {len(failed)} factor(s)")
        return 3

    print("[Repair] Completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

