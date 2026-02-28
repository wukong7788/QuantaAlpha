#!/usr/bin/env python3
"""
A/B test harness for QuantaAlpha backtest memory usage.

This script runs the existing backtest entry (`quantaalpha.backtest.run_backtest`) and reports:
  - wall time (seconds)
  - peak RSS (MB) via `resource.getrusage(...).ru_maxrss`

It supports a "baseline" mode that loads selected modules from `git show HEAD:<path>`
into `sys.modules` before running the backtest, so you can compare current working tree
changes against the repo HEAD without requiring git checkout/stash.

Usage:
  uv run python scripts/abtest_backtest_memory.py baseline -- -c configs/backtest_limited.yaml --factor-source custom --factor-json data/factorlib/all_factors_library.json
  uv run python scripts/abtest_backtest_memory.py optimized -- -c configs/backtest_limited.yaml --factor-source custom --factor-json data/factorlib/all_factors_library.json
"""

from __future__ import annotations

import json
import platform
import resource
import runpy
import subprocess
import sys
import time
import types
from pathlib import Path
from typing import Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _usage() -> None:
    print(
        "Usage:\n"
        "  python scripts/abtest_backtest_memory.py <baseline|optimized> -- <backtest args...>\n"
        "\n"
        "Example:\n"
        "  uv run python scripts/abtest_backtest_memory.py baseline -- -c configs/backtest_limited.yaml --factor-source custom --factor-json data/factorlib/all_factors_library.json\n"
    )


def _ru_maxrss_mb() -> float:
    maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS: bytes; Linux: KiB (most distros).
    if sys.platform == "darwin":
        return float(maxrss) / 1024.0 / 1024.0
    return float(maxrss) / 1024.0


def _git_show(path: str) -> str:
    out = subprocess.check_output(
        ["git", "show", f"HEAD:{path}"],
        cwd=str(PROJECT_ROOT),
        stderr=subprocess.STDOUT,
    )
    return out.decode("utf-8", errors="replace")


def _inject_module(module_name: str, source: str, virtual_file: Path) -> None:
    module = types.ModuleType(module_name)
    module.__file__ = str(virtual_file)
    module.__package__ = module_name.rpartition(".")[0]
    sys.modules[module_name] = module
    code = compile(source, str(virtual_file), "exec")
    exec(code, module.__dict__)


def _inject_baseline_modules() -> None:
    # Keep __file__ pointing to the real repo path to preserve relative project_root logic.
    calc_path = "quantaalpha/backtest/custom_factor_calculator.py"
    runner_path = "quantaalpha/backtest/runner.py"
    _inject_module(
        "quantaalpha.backtest.custom_factor_calculator",
        _git_show(calc_path),
        PROJECT_ROOT / calc_path,
    )
    _inject_module(
        "quantaalpha.backtest.runner",
        _git_show(runner_path),
        PROJECT_ROOT / runner_path,
    )


def main(argv: List[str]) -> int:
    if len(argv) < 3 or "--" not in argv:
        _usage()
        return 2

    variant = argv[1].strip().lower()
    sep_idx = argv.index("--")
    backtest_args = argv[sep_idx + 1 :]
    if not backtest_args:
        _usage()
        return 2

    if variant not in {"baseline", "optimized"}:
        print(f"Unknown variant: {variant!r}")
        _usage()
        return 2

    if variant == "baseline":
        _inject_baseline_modules()

    t0 = time.perf_counter()
    exit_code = 0
    try:
        sys.argv = ["quantaalpha.backtest.run_backtest"] + backtest_args
        runpy.run_module("quantaalpha.backtest.run_backtest", run_name="__main__")
    except SystemExit as e:
        exit_code = int(e.code) if isinstance(e.code, int) else 0
    except Exception:
        exit_code = 1
        raise
    finally:
        elapsed_s = time.perf_counter() - t0
        result: Dict[str, object] = {
            "variant": variant,
            "elapsed_s": round(elapsed_s, 3),
            "max_rss_mb": round(_ru_maxrss_mb(), 1),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "argv": backtest_args,
            "exit_code": exit_code,
        }
        print("ABTEST_RESULT=" + json.dumps(result, ensure_ascii=False))

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

