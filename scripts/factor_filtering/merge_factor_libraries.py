#!/usr/bin/env python3
"""
Merge multiple factor library JSONs into one pooled library, and optionally build a Zoo CSV/JSON
for next-round novelty filtering.

Design goals:
1) Do NOT do "Top-N" selection here (no BOB logic). Only merge/union.
2) Preserve all factors; handle factor_id key collisions safely.
3) Zoo output supports both whitespace-normalized ("norm") and AST-canonicalized ("ast") dedup
   for A/B testing.
"""

from __future__ import annotations

import argparse
import copy
import glob
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def _is_number(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        try:
            return bool(float(v) == float(v) and abs(float(v)) != float("inf"))
        except Exception:
            return False
    return False


def _parse_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            x = float(v)
            if x != x or x == float("inf") or x == float("-inf"):
                return None
            return x
        if isinstance(v, str) and v.strip():
            x = float(v)
            if x != x or x == float("inf") or x == float("-inf"):
                return None
            return x
    except Exception:
        return None
    return None


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


def _score_for_dedup(backtest_results: Dict[str, Any], score_key: str) -> float:
    keys = (
        score_key,
        "1day.excess_return_with_cost.information_ratio",
        "1day.excess_return_without_cost.information_ratio",
        "Rank ICIR",
        "ICIR",
        "Rank IC",
        "IC",
        "1day.excess_return_with_cost.annualized_return",
        "1day.excess_return_without_cost.annualized_return",
    )
    x = _metric_from_bt(backtest_results, keys, contains=("information_ratio", "icir", "rank ic", "annualized_return"))
    return float(x) if x is not None else float("-inf")


def _load_factor_dict(path: Path) -> Tuple[dict, Dict[str, Dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid library JSON (expected object): {path}")
    factors = data.get("factors", {}) or {}
    if isinstance(factors, list):
        out: Dict[str, Dict[str, Any]] = {}
        for i, item in enumerate(factors):
            if not isinstance(item, dict):
                continue
            fid = str(item.get("factor_id") or f"idx_{i}").strip() or f"idx_{i}"
            out[fid] = item
        return data.get("metadata") or {}, out
    if not isinstance(factors, dict):
        raise ValueError(f"Invalid library factors payload (expected dict/list): {path}")
    out2: Dict[str, Dict[str, Any]] = {}
    for fid, item in factors.items():
        if isinstance(item, dict):
            out2[str(fid)] = item
    return data.get("metadata") or {}, out2


def _resolve_library_tokens(spec: str) -> List[Path]:
    tokens = [t.strip() for t in (spec or "").split(",") if t.strip()]
    resolved: List[Path] = []
    seen: set[str] = set()

    def _candidate_paths(token: str) -> List[Path]:
        p = Path(token)
        if p.is_absolute():
            return [p]
        return [
            Path(token),
            PROJECT_ROOT / token,
            PROJECT_ROOT / "data" / "factorlib" / token,
        ]

    for token in tokens:
        candidates: List[Path] = []
        for c in _candidate_paths(token):
            s = str(c)
            has_glob = any(ch in s for ch in "*?[]")
            if has_glob:
                for m in glob.glob(s):
                    candidates.append(Path(m))
            else:
                candidates.append(c)
        for p in candidates:
            rp = p.resolve()
            if not rp.is_file():
                continue
            key = str(rp)
            if key in seen:
                continue
            seen.add(key)
            resolved.append(rp)

    return resolved


def _safe_json_dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_zoo_csv(path: Path, rows: Iterable[Tuple[str, str]]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["factor_name", "factor_expression"])
        for name, expr in rows:
            w.writerow([name, expr])


def _unique_id(base: str, *, source_tag: str, factor_expression: str, used: set[str]) -> str:
    seed = f"{base}|{source_tag}|{factor_expression}"
    suffix = hashlib.md5(seed.encode()).hexdigest()[:8]
    cand = f"{base}__{suffix}"
    if cand not in used:
        return cand
    n = 2
    while True:
        cand2 = f"{cand}__dup{n}"
        if cand2 not in used:
            return cand2
        n += 1


@dataclass
class ZooBuildStats:
    method: str
    input_total: int
    kept_unique: int
    dropped_empty_expr: int
    ast_parse_failed: int


def _build_zoo(
    factors: Dict[str, Dict[str, Any]],
    *,
    method: str,
    score_key: str,
    skip_unparsable: bool,
) -> Tuple[dict, List[Tuple[str, str]], ZooBuildStats]:
    from quantaalpha.utils.expression_fingerprint import try_ast_canonical_expression
    from quantaalpha.utils.expression_fingerprint import expression_fingerprint

    picked: Dict[str, Dict[str, Any]] = {}  # fp -> info
    picked_score: Dict[str, float] = {}

    dropped_empty = 0
    ast_failed = 0

    for finfo in factors.values():
        if not isinstance(finfo, dict):
            continue
        expr = str(finfo.get("factor_expression") or "").strip()
        if not expr:
            dropped_empty += 1
            continue

        if method == "ast":
            res = try_ast_canonical_expression(expr)
            if not res.ok:
                ast_failed += 1
                if skip_unparsable:
                    continue
            fp = res.canonical
        else:
            fp = expression_fingerprint(expr, "norm")

        bt = finfo.get("backtest_results") if isinstance(finfo.get("backtest_results"), dict) else {}
        score = _score_for_dedup(bt, score_key)

        cur = picked_score.get(fp)
        if cur is None or score > cur:
            picked[fp] = finfo
            picked_score[fp] = score

    zoo_factors: dict = {}
    csv_rows: List[Tuple[str, str]] = []

    for fp, finfo in picked.items():
        expr = str(finfo.get("factor_expression") or "").strip()
        name = str(finfo.get("factor_name") or finfo.get("factor_id") or "").strip() or "unknown"
        zoo_id = "zoo_" + hashlib.md5(fp.encode()).hexdigest()[:12]
        zoo_factors[zoo_id] = {
            "factor_id": zoo_id,
            "factor_name": name,
            "factor_expression": expr,
            "factor_description": finfo.get("factor_description", ""),
            "source": finfo.get("metadata", {}),
            "fingerprint_method": method,
        }
        csv_rows.append((name, expr))

    stats = ZooBuildStats(
        method=method,
        input_total=len(factors),
        kept_unique=len(zoo_factors),
        dropped_empty_expr=dropped_empty,
        ast_parse_failed=ast_failed,
    )
    return zoo_factors, csv_rows, stats


def main() -> int:
    p = argparse.ArgumentParser(description="Merge factor libraries into one pool; optionally build Zoo.")
    p.add_argument(
        "--libraries",
        required=True,
        help='Comma/glob spec, e.g. "data/factorlib/all_factors_library_*.json,other.json"',
    )
    p.add_argument("--out", required=True, help="Output pooled factor library JSON path")
    p.add_argument("--report", default="", help="Optional report JSON path")

    p.add_argument(
        "--zoo-method",
        choices=("none", "norm", "ast", "both"),
        default="norm",
        help="Zoo dedup method (default: norm). both writes *_norm and *_ast.",
    )
    p.add_argument("--zoo-csv", default="", help="Zoo CSV output path (default derived from --out)")
    p.add_argument("--zoo-json", default="", help="Zoo JSON output path (default derived from --out)")
    p.add_argument("--zoo-score-key", default="1day.excess_return_with_cost.information_ratio", help="Zoo keep-best score key")
    p.add_argument(
        "--skip-unparsable",
        action="store_true",
        help="Skip unparsable expressions when building AST Zoo (recommended).",
    )

    args = p.parse_args()

    os.chdir(PROJECT_ROOT)

    lib_paths = _resolve_library_tokens(args.libraries)
    if not lib_paths:
        print(f"Error: no libraries resolved from spec: {args.libraries}", file=sys.stderr)
        return 2

    print(f"[Merge] libraries={len(lib_paths)}")
    for lp in lib_paths:
        print(f"  - {lp}")

    merged: Dict[str, Dict[str, Any]] = {}
    used_ids: set[str] = set()
    same_id_same_expr_merged = 0
    id_collision_renamed = 0
    dropped_empty_expr = 0

    source_libs: List[str] = []
    for lib_path in lib_paths:
        source_libs.append(lib_path.name)
        _, factors = _load_factor_dict(lib_path)
        for key_id, finfo in factors.items():
            if not isinstance(finfo, dict):
                continue
            expr = str(finfo.get("factor_expression") or "").strip()
            if not expr:
                dropped_empty_expr += 1
                continue

            orig_id = str(finfo.get("factor_id") or key_id).strip() or str(key_id)
            base_id = orig_id

            entry = copy.deepcopy(finfo)
            meta = entry.get("metadata")
            if not isinstance(meta, dict):
                meta = {}
            meta.setdefault("merged_source_libraries", [])
            meta["merged_source_libraries"] = sorted(set([*meta.get("merged_source_libraries", []), lib_path.name]))
            meta["merged_source_factor_id"] = orig_id
            entry["metadata"] = meta

            if base_id in merged:
                existing_expr = str(merged[base_id].get("factor_expression") or "").strip()
                if existing_expr == expr:
                    # Same id + same expression across different libraries -> merge metadata only.
                    ex_meta = merged[base_id].get("metadata")
                    if not isinstance(ex_meta, dict):
                        ex_meta = {}
                    ex_meta.setdefault("merged_source_libraries", [])
                    ex_meta["merged_source_libraries"] = sorted(
                        set([*ex_meta.get("merged_source_libraries", []), lib_path.name])
                    )
                    merged[base_id]["metadata"] = ex_meta
                    same_id_same_expr_merged += 1
                    continue

                # Collision: keep both by renaming.
                new_id = _unique_id(base_id, source_tag=lib_path.name, factor_expression=expr, used=used_ids | set(merged.keys()))
                entry["factor_id"] = new_id
                merged[new_id] = entry
                used_ids.add(new_id)
                id_collision_renamed += 1
                continue

            entry["factor_id"] = base_id
            merged[base_id] = entry
            used_ids.add(base_id)

    out_path = Path(args.out)
    out_payload = {
        "metadata": {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "version": "1.0",
            "type": "merged_factor_pool",
            "input_libraries": [str(p) for p in lib_paths],
            "input_library_count": len(lib_paths),
            "total_factors": len(merged),
            "merge_stats": {
                "same_id_same_expr_merged": same_id_same_expr_merged,
                "id_collision_renamed": id_collision_renamed,
                "dropped_empty_expr": dropped_empty_expr,
            },
        },
        "factors": merged,
    }
    _safe_json_dump(out_path, out_payload)
    print(f"[Merge] wrote pooled library: {out_path} factors={len(merged)}")

    zoo_outputs: List[dict] = []

    def _default_zoo_base() -> Path:
        stem = out_path.stem
        return out_path.with_name(f"{stem}_zoo")

    if args.zoo_method != "none":
        base = _default_zoo_base()
        zoo_csv_base = Path(args.zoo_csv) if args.zoo_csv else base.with_suffix(".csv")
        zoo_json_base = Path(args.zoo_json) if args.zoo_json else base.with_suffix(".json")

        methods = ["norm", "ast"] if args.zoo_method == "both" else [args.zoo_method]
        for m in methods:
            zoo_factors, csv_rows, stats = _build_zoo(
                merged,
                method=m,
                score_key=args.zoo_score_key,
                skip_unparsable=bool(args.skip_unparsable),
            )

            if len(methods) > 1:
                csv_path = zoo_csv_base.with_name(f"{zoo_csv_base.stem}_{m}{zoo_csv_base.suffix}")
                json_path = zoo_json_base.with_name(f"{zoo_json_base.stem}_{m}{zoo_json_base.suffix}")
            else:
                csv_path = zoo_csv_base
                json_path = zoo_json_base

            _write_zoo_csv(csv_path, csv_rows)
            zoo_payload = {
                "metadata": {
                    "description": "Merged Zoo for novelty filtering (generated from merged factor pool).",
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "fingerprint_method": m,
                    "skip_unparsable": bool(args.skip_unparsable) if m == "ast" else False,
                    "source_libs": source_libs,
                    "total_count": len(zoo_factors),
                    "stats": {
                        "input_total": stats.input_total,
                        "kept_unique": stats.kept_unique,
                        "dropped_empty_expr": stats.dropped_empty_expr,
                        "ast_parse_failed": stats.ast_parse_failed,
                    },
                },
                "factors": zoo_factors,
            }
            _safe_json_dump(json_path, zoo_payload)

            zoo_outputs.append(
                {
                    "method": m,
                    "csv": str(csv_path),
                    "json": str(json_path),
                    "count": len(zoo_factors),
                    "ast_parse_failed": stats.ast_parse_failed,
                }
            )
            print(f"[Zoo] method={m} count={len(zoo_factors)} csv={csv_path} json={json_path}")

        if zoo_outputs:
            print("[Zoo] set env (choose one):")
            for z in zoo_outputs:
                print(f"  export FACTOR_CoSTEER_FACTOR_ZOO_PATH={z['csv']}")

    if args.report:
        report_path = Path(args.report)
        report_payload = {
            "pooled_library": str(out_path),
            "input_libraries": [str(p) for p in lib_paths],
            "pooled_total_factors": len(merged),
            "merge_stats": out_payload["metadata"]["merge_stats"],
            "zoo_outputs": zoo_outputs,
        }
        _safe_json_dump(report_path, report_payload)
        print(f"[Report] wrote: {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

