#!/usr/bin/env python3
"""
Migrate factor_cache from legacy *.pkl to *.parquet (Parquet + compression).

Safe by default: dry-run unless --apply is passed.
Optional cleanup: --delete-pkl (requires --yes).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Migrate factor_cache *.pkl -> *.parquet")
    p.add_argument(
        "--cache-dir",
        default="data/results/factor_cache",
        help="Cache directory containing md5-named cache files (default: data/results/factor_cache)",
    )
    p.add_argument(
        "--compression",
        default="zstd",
        help="Parquet compression (default: zstd)",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually write parquet files (default: dry-run)",
    )
    p.add_argument(
        "--delete-pkl",
        action="store_true",
        help="Delete source *.pkl after successful conversion (requires --yes)",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive actions (required for --delete-pkl)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Convert at most N files (0 = no limit)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cache_dir = Path(args.cache_dir)

    if args.delete_pkl and not args.yes:
        print("ERROR: --delete-pkl requires --yes", file=sys.stderr)
        return 2

    if not cache_dir.exists():
        print(f"ERROR: cache dir not found: {cache_dir}", file=sys.stderr)
        return 2

    from quantaalpha.utils.factor_cache import write_factor_cache

    pkl_files = sorted(cache_dir.glob("*.pkl"))
    if not pkl_files:
        print(f"No *.pkl found under {cache_dir}")
        return 0

    total = 0
    skipped = 0
    converted = 0
    failed = 0
    deleted = 0
    start = time.time()

    for pkl_path in pkl_files:
        if args.limit and total >= args.limit:
            break
        total += 1

        key = pkl_path.stem
        parquet_path = cache_dir / f"{key}.parquet"
        if parquet_path.exists():
            skipped += 1
            if args.apply and args.delete_pkl:
                try:
                    if parquet_path.stat().st_size > 0:
                        pkl_path.unlink()
                        deleted += 1
                except Exception as e:
                    print(f"[WARN] delete {pkl_path.name} failed: {e}", file=sys.stderr)
            continue

        if not args.apply:
            converted += 1
            continue

        try:
            obj = pd.read_pickle(pkl_path)
        except Exception as e:
            failed += 1
            print(f"[FAIL] read {pkl_path.name}: {e}", file=sys.stderr)
            continue

        ok = write_factor_cache(
            cache_dir,
            key,
            obj,  # type: ignore[arg-type]
            config={
                "cache_format": "parquet",
                "cache_compression": args.compression,
                "cache_dual_write_pkl": False,
            },
            strict_parquet=True,
        )
        if not ok:
            failed += 1
            print(f"[FAIL] write {parquet_path.name}", file=sys.stderr)
            continue

        converted += 1

        if args.delete_pkl:
            try:
                pkl_path.unlink()
                deleted += 1
            except Exception as e:
                print(f"[WARN] delete {pkl_path.name} failed: {e}", file=sys.stderr)

        if converted % 200 == 0:
            elapsed = time.time() - start
            print(f"progress: converted={converted} skipped={skipped} failed={failed} elapsed_s={elapsed:.1f}")

    elapsed = time.time() - start
    mode = "apply" if args.apply else "dry-run"
    print(
        f"Done ({mode}): total_seen={total} converted={converted} skipped={skipped} failed={failed} deleted={deleted} elapsed_s={elapsed:.1f}"
    )

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
