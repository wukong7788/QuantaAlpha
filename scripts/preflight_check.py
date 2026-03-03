#!/usr/bin/env python3
"""
Warn-only preflight checks for QuantaAlpha configs.

This script is intentionally non-blocking: it surfaces risky or inconsistent
settings before long runs, but does not change runtime behavior.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


def _repo_root() -> Path:
    # scripts/preflight_check.py -> repo root is parent of scripts/
    return Path(__file__).resolve().parent.parent


def _resolve_config_path(raw_path: str) -> Path:
    p = Path(raw_path).expanduser()
    if p.is_absolute():
        return p

    cwd_candidate = (Path.cwd() / p).resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    repo_candidate = (_repo_root() / p).resolve()
    if repo_candidate.exists():
        return repo_candidate

    # Keep cwd-style path in error text for least surprise.
    return cwd_candidate


def _warn(msg: str) -> None:
    print(f"[Preflight][WARN] {msg}")


def _info(msg: str) -> None:
    print(f"[Preflight][INFO] {msg}")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Top-level YAML must be a mapping: {path}")
    return data


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def check_experiment(cfg_path: Path) -> int:
    cfg = _load_yaml(cfg_path)
    planning = cfg.get("planning") or {}
    evolution = cfg.get("evolution") or {}
    execution = cfg.get("execution") or {}
    quality_gate = cfg.get("quality_gate") or {}

    _info(f"Checking experiment config: {cfg_path}")

    if bool(planning.get("enabled", False)):
        n_dirs = _to_int(planning.get("num_directions"), 1)
        if n_dirs < 10:
            _warn(
                f"planning.num_directions={n_dirs} is below paper-style baseline 10; "
                "exploration breadth may be insufficient."
            )

    if bool(evolution.get("enabled", False)):
        max_rounds = _to_int(evolution.get("max_rounds"), 0)
        if max_rounds < 11:
            _warn(
                f"evolution.max_rounds={max_rounds} is below paper-style baseline 11."
            )

        if bool(evolution.get("crossover_enabled", True)):
            crossover_n = _to_int(evolution.get("crossover_n"), 0)
            if crossover_n < 5:
                _warn(
                    f"evolution.crossover_n={crossover_n} is low; branches may collapse early."
                )

    if "factor" in cfg:
        _warn(
            "Found factor.* section in experiment config. Current mining entry does not "
            "directly wire this section into generation count/constraints."
        )

    if "complexity_enabled" in quality_gate or "redundancy_enabled" in quality_gate:
        _warn(
            "quality_gate.complexity_enabled/redundancy_enabled are configured, but current "
            "constructor path forwards consistency_enabled only."
        )

    if bool(execution.get("parallel_execution", False)) and bool(
        evolution.get("parallel_enabled", False)
    ):
        _warn(
            "Both execution.parallel_execution and evolution.parallel_enabled are enabled. "
            "Make sure this is intentional to avoid heavy system load."
        )

    _info("Experiment preflight completed (warn-only).")
    return 0


def check_backtest(cfg_path: Path, factor_source: str) -> int:
    cfg = _load_yaml(cfg_path)
    factor_cfg = cfg.get("factor_source") or {}
    custom = factor_cfg.get("custom") or {}
    model = cfg.get("model") or {}
    model_params = model.get("params") or {}

    _info(f"Checking backtest config: {cfg_path}")

    qf = custom.get("quality_filter")
    max_factors = custom.get("max_factors")
    ranking_metric = custom.get("ranking_metric")

    if factor_source == "custom":
        if max_factors not in (None, "", 0) and not ranking_metric:
            _warn(
                "custom.max_factors is set but custom.ranking_metric is empty; "
                "topN will depend on JSON insertion order."
            )
        if qf in (None, "", "null"):
            _warn("custom.quality_filter is empty.")

    threads = _to_int(model_params.get("num_threads"), -1)
    if threads > 8:
        _warn(
            f"model.params.num_threads={threads} looks high for local runs; "
            "consider lowering threads for stability."
        )

    _info("Backtest preflight completed (warn-only).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Warn-only config preflight checks")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_exp = subparsers.add_parser("experiment", help="Check experiment config")
    p_exp.add_argument("--config", required=True, help="Path to experiment config YAML")

    p_bt = subparsers.add_parser("backtest", help="Check backtest config")
    p_bt.add_argument("--config", required=True, help="Path to backtest config YAML")
    p_bt.add_argument(
        "--factor-source",
        default="custom",
        choices=["custom", "combined", "alpha158", "alpha158_20", "alpha360"],
        help="Factor source context",
    )

    args = parser.parse_args()

    try:
        if args.command == "experiment":
            return check_experiment(_resolve_config_path(args.config))
        return check_backtest(_resolve_config_path(args.config), args.factor_source)
    except Exception as exc:
        _warn(f"Preflight check failed unexpectedly: {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
