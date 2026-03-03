#!/usr/bin/env python3
"""
Repair factor MD5 cache for a factor library.

What it does:
1) Scan MD5 cache (data/results/factor_cache by default) for each factor expression.
2) Mark cache entries as:
   - ok
   - missing
   - invalid_read (cache exists but cannot be read)
   - invalid_index (cache index mismatch vs current backtest config target index)
3) Optionally delete invalid cache files and recompute factors to rebuild cache.

This script is meant for "cache is present but wrong" cases (e.g. market/date-range mismatch).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from quantaalpha.backtest.custom_factor_calculator import CustomFactorCalculator
from quantaalpha.factors.library import FactorLibraryManager
from quantaalpha.utils.factor_cache import cache_paths, read_factor_cache


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
        data = json.load(f) or {}
    factors = data.get("factors", {}) or {}
    if not isinstance(factors, dict):
        raise ValueError(f"Invalid factor library format: {library_path}")
    out: dict[str, dict[str, Any]] = {}
    for fid, info in factors.items():
        if isinstance(info, dict):
            out[str(fid)] = info
    return out


@dataclass
class CacheStatusRow:
    factor_id: str
    factor_name: str
    cache_key: str
    parquet_path: str
    pkl_path: str
    status: str  # ok | missing | invalid_read | invalid_index | skipped_empty_expr
    reason: str = ""


def _md5(expr: str) -> str:
    return hashlib.md5(expr.encode()).hexdigest()


def _delete_cache_files(cache_dir: Path, cache_key: str) -> List[str]:
    parquet_path, pkl_path = cache_paths(cache_dir, cache_key)
    deleted: List[str] = []
    for p in [parquet_path, pkl_path]:
        if p.exists():
            try:
                p.unlink()
                deleted.append(str(p))
            except Exception:
                pass
    return deleted


def main() -> int:
    p = argparse.ArgumentParser(description="Repair factor MD5 cache by deleting invalid cache and recomputing.")
    p.add_argument("--library", required=True, help="Factor library JSON filename or path")
    p.add_argument("--config", default="configs/backtest.yaml", help="Backtest config YAML (default: configs/backtest.yaml)")
    p.add_argument("--cache-dir", default="data/results/factor_cache", help="MD5 cache directory (default: data/results/factor_cache)")
    p.add_argument("--warm-cache", action="store_true", help="Warm MD5 cache from available result.h5 before repairing")
    p.add_argument("--max-factors", type=int, default=0, help="Optional cap on scanned factors (0 = no cap)")
    p.add_argument("--progress-every", type=int, default=25, help="Progress print frequency during scan (default: 25)")

    p.add_argument("--delete-invalid", action="store_true", help="Delete invalid cache files (requires --apply)")
    p.add_argument("--recompute-missing", action="store_true", help="Recompute missing cache entries (requires --apply)")
    p.add_argument("--recompute-invalid", action="store_true", help="Recompute invalid cache entries (requires --apply)")
    p.add_argument("--apply", action="store_true", help="Apply changes (delete/recompute). Default is dry-run.")
    p.add_argument("--report", default="", help="Optional report JSON path (default: log/backtest_manual/cache_repair_<lib>_<ts>.json)")

    args = p.parse_args()

    project_root = PROJECT_ROOT
    os.chdir(project_root)

    library_path = _resolve_library_path(project_root, args.library)
    config_path = Path(args.config)
    if not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"[RepairCache] library={library_path}")
    print(f"[RepairCache] config={config_path}")
    print(f"[RepairCache] cache_dir={cache_dir}")

    if args.warm_cache:
        warmed = FactorLibraryManager.warm_cache_from_json(str(library_path), cache_dir=str(cache_dir))
        print(f"[Warm] {json.dumps(warmed, ensure_ascii=False)}")

    factors_by_id = _load_factors_by_id(library_path)
    factor_items = list(factors_by_id.items())
    if args.max_factors and args.max_factors > 0:
        factor_items = factor_items[: args.max_factors]

    cfg = _load_yaml(config_path)
    cfg.setdefault("llm", {})
    cfg["llm"]["cache_dir"] = str(cache_dir)

    calculator = CustomFactorCalculator(
        data_df=None,
        cache_dir=cache_dir,
        auto_extract_cache=bool(cfg.get("llm", {}).get("auto_extract_cache", False)),
        config=cfg,
    )

    # Determine target index (forces Qlib data load). Needed to validate cache correctness.
    print("[RepairCache] Loading target index from Qlib data (this can take a while)...")
    t0 = time.perf_counter()
    try:
        target_index = calculator.data_df.index
        if hasattr(target_index, "duplicated") and target_index.duplicated().any():
            target_index = target_index[~target_index.duplicated(keep="last")]
    except Exception as e:
        print(f"[RepairCache] Error: failed to load target index from Qlib data: {e}", file=sys.stderr)
        return 3
    finally:
        dt = time.perf_counter() - t0
        if "target_index" in locals() and target_index is not None:
            try:
                n = len(target_index)
            except Exception:
                n = -1
            print(f"[RepairCache] Target index loaded: rows={n} elapsed_s={dt:.1f}")
        else:
            print(f"[RepairCache] Target index load finished: elapsed_s={dt:.1f}")

    rows: List[CacheStatusRow] = []
    ok = 0
    missing = 0
    invalid_read = 0
    invalid_index = 0
    skipped_empty = 0

    scan_t0 = time.perf_counter()
    total_factors = len(factor_items)
    progress_every = int(args.progress_every) if int(args.progress_every) > 0 else 0

    for i, (factor_id, info) in enumerate(factor_items, start=1):
        if progress_every and (i == 1 or i % progress_every == 0 or i == total_factors):
            elapsed = time.perf_counter() - scan_t0
            print(
                f"[ScanProgress] {i}/{total_factors} "
                f"ok={ok} missing={missing} invalid_read={invalid_read} invalid_index={invalid_index} "
                f"elapsed_s={elapsed:.1f}"
            )
        name = str(info.get("factor_name") or factor_id)
        expr = str(info.get("factor_expression") or "").strip()
        if not expr:
            skipped_empty += 1
            rows.append(
                CacheStatusRow(
                    factor_id=str(factor_id),
                    factor_name=name,
                    cache_key="",
                    parquet_path="",
                    pkl_path="",
                    status="skipped_empty_expr",
                    reason="empty factor_expression",
                )
            )
            continue

        key = _md5(expr)
        parquet_path, pkl_path = cache_paths(cache_dir, key)

        has_files = parquet_path.exists() or pkl_path.exists()
        if not has_files:
            missing += 1
            rows.append(
                CacheStatusRow(
                    factor_id=str(factor_id),
                    factor_name=name,
                    cache_key=key,
                    parquet_path=str(parquet_path),
                    pkl_path=str(pkl_path),
                    status="missing",
                )
            )
            continue

        series = read_factor_cache(cache_dir, key, config=calculator._llm_cache_config)  # type: ignore[attr-defined]
        if series is None:
            invalid_read += 1
            rows.append(
                CacheStatusRow(
                    factor_id=str(factor_id),
                    factor_name=name,
                    cache_key=key,
                    parquet_path=str(parquet_path),
                    pkl_path=str(pkl_path),
                    status="invalid_read",
                    reason="read_factor_cache returned None (corrupt/unsupported)",
                )
            )
            continue

        validated = calculator._validate_and_align_result(series, name, target_index)  # type: ignore[attr-defined]
        if validated is None:
            invalid_index += 1
            rows.append(
                CacheStatusRow(
                    factor_id=str(factor_id),
                    factor_name=name,
                    cache_key=key,
                    parquet_path=str(parquet_path),
                    pkl_path=str(pkl_path),
                    status="invalid_index",
                    reason="index mismatch vs target index (will recompute)",
                )
            )
            continue

        ok += 1
        rows.append(
            CacheStatusRow(
                factor_id=str(factor_id),
                factor_name=name,
                cache_key=key,
                parquet_path=str(parquet_path),
                pkl_path=str(pkl_path),
                status="ok",
            )
        )

    print(
        "[Scan] "
        f"total={len(rows)} ok={ok} missing={missing} invalid_read={invalid_read} "
        f"invalid_index={invalid_index} skipped_empty_expr={skipped_empty}"
    )

    deleted_files: List[str] = []
    recomputed: List[str] = []
    recompute_failed: List[str] = []

    if args.apply:
        if args.delete_invalid:
            for r in rows:
                if r.status in {"invalid_read", "invalid_index"} and r.cache_key:
                    deleted_files.extend(_delete_cache_files(cache_dir, r.cache_key))
            print(f"[Delete] deleted_files={len(deleted_files)}")

        to_recompute: List[Tuple[str, str, str]] = []  # (factor_id, name, expr)
        for factor_id, info in factor_items:
            name = str(info.get("factor_name") or factor_id)
            expr = str(info.get("factor_expression") or "").strip()
            if not expr:
                continue

            key = _md5(expr)
            parquet_path, pkl_path = cache_paths(cache_dir, key)
            exists_now = parquet_path.exists() or pkl_path.exists()
            if not exists_now and args.recompute_missing:
                # Either truly missing or deleted due to invalid.
                to_recompute.append((str(factor_id), name, expr))
                continue

            if exists_now and args.recompute_invalid:
                # Recompute invalid without deleting first is not deterministic; require delete-invalid for invalid cases.
                # We still allow it, but only for entries that were flagged invalid_index/invalid_read.
                # Build a set for quick membership.
                pass

        # If recompute_invalid is requested, include previously flagged invalid items (even if cache still exists).
        if args.recompute_invalid:
            flagged_invalid = {(r.factor_id, r.factor_name) for r in rows if r.status in {"invalid_read", "invalid_index"}}
            for factor_id, info in factor_items:
                name = str(info.get("factor_name") or factor_id)
                expr = str(info.get("factor_expression") or "").strip()
                if not expr:
                    continue
                if (str(factor_id), name) in flagged_invalid:
                    to_recompute.append((str(factor_id), name, expr))

        # De-dup recompute list by cache key
        seen_keys: set[str] = set()
        unique_recompute: List[Tuple[str, str, str]] = []
        for fid, name, expr in to_recompute:
            k = _md5(expr)
            if k in seen_keys:
                continue
            seen_keys.add(k)
            unique_recompute.append((fid, name, expr))

        if unique_recompute:
            print(f"[Recompute] targets={len(unique_recompute)}")
        for i, (fid, name, expr) in enumerate(unique_recompute, start=1):
            print(f"  [{i}/{len(unique_recompute)}] compute: {name} (id={fid}) ...", end="", flush=True)
            try:
                s = calculator.calculate_factor(name, expr)
                if s is None:
                    raise RuntimeError("calculate_factor returned None")
                validated = calculator._validate_and_align_result(s, name, target_index)  # type: ignore[attr-defined]
                if validated is None:
                    raise RuntimeError("computed result index validation failed")
                calculator._save_to_cache(expr, validated)  # type: ignore[attr-defined]
                recomputed.append(name)
                print(" ✓")
            except Exception as e:
                recompute_failed.append(f"{name}: {str(e)[:120]}")
                print(" ✗")

        print(f"[Recompute] ok={len(recomputed)} failed={len(recompute_failed)}")
    else:
        if args.delete_invalid or args.recompute_missing or args.recompute_invalid:
            print("[DryRun] no changes applied (add --apply).")

    report_path = Path(args.report) if args.report else None
    if report_path is None:
        report_path = project_root / "log" / "backtest_manual" / (
            f"cache_repair_{library_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

    report_payload = {
        "library": str(library_path),
        "config": str(config_path),
        "cache_dir": str(cache_dir),
        "timestamp": datetime.now().isoformat(),
        "scan": {
            "total": len(rows),
            "ok": ok,
            "missing": missing,
            "invalid_read": invalid_read,
            "invalid_index": invalid_index,
            "skipped_empty_expr": skipped_empty,
        },
        "actions": {
            "apply": bool(args.apply),
            "delete_invalid": bool(args.delete_invalid) and bool(args.apply),
            "recompute_missing": bool(args.recompute_missing) and bool(args.apply),
            "recompute_invalid": bool(args.recompute_invalid) and bool(args.apply),
        },
        "deleted_files": deleted_files,
        "recomputed_factor_names": recomputed,
        "recompute_failed": recompute_failed,
        "details": [r.__dict__ for r in rows],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Report] {report_path}")

    if args.apply and recompute_failed:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
