#!/usr/bin/env python3
"""
A/B test for expression style validation with real API calls.

Baseline: temporarily disable expression style validation.
Optimized: restore original validation logic.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET = PROJECT_ROOT / "quantaalpha" / "factors" / "regulator" / "expression_style.py"
ABTEST_SCRIPT = PROJECT_ROOT / "scripts" / "abtest_experiment.py"
HEARTBEAT_SECONDS = 20


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _run_with_tee(cmd: list[str], cwd: Path, env: dict[str, str], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    start_ts = time.time()
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] start: {' '.join(cmd)}",
        flush=True,
    )

    with out_path.open("w", encoding="utf-8") as f:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        q: Queue[str | None] = Queue()

        def _reader() -> None:
            for line in proc.stdout:
                q.put(line)
            q.put(None)

        t = threading.Thread(target=_reader, daemon=True)
        t.start()

        last_heartbeat = time.time()
        stream_closed = False
        while True:
            try:
                item = q.get(timeout=1.0)
                if item is None:
                    stream_closed = True
                else:
                    sys.stdout.write(item)
                    f.write(item)
                    f.flush()
            except Empty:
                pass

            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_SECONDS and proc.poll() is None:
                elapsed = int(now - start_ts)
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] still running... elapsed={elapsed}s",
                    flush=True,
                )
                last_heartbeat = now

            if stream_closed and proc.poll() is not None:
                break

        rc = proc.wait()
        elapsed_total = int(time.time() - start_ts)
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] done: exit_code={rc}, elapsed={elapsed_total}s",
            flush=True,
        )
        return rc


def _disable_style_check(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    anchor = "    expression = expression.strip()\n"
    inject = (
        "    expression = expression.strip()\n\n"
        "    # A/B baseline: disable expression style validation\n"
        "    return True, \"\"\n"
    )
    if anchor not in source:
        raise RuntimeError("Patch anchor not found in expression_style.py")
    path.write_text(source.replace(anchor, inject, 1), encoding="utf-8")


def _run_variant(
    variant: str,
    test_name: str,
    direction: str,
    step_n: int,
    times: int,
    skip_doctor: bool,
    results_root: Path,
    data_results_root: Path,
    env: dict[str, str],
    python_bin: Path,
) -> Path:
    out_path = Path("/tmp") / f"{test_name}_{variant}.out"
    cmd = [
        str(python_bin),
        str(ABTEST_SCRIPT),
        "run",
        "--name",
        test_name,
        "--variant",
        variant,
        "--base-config",
        "configs/experiment_smoke.yaml",
        "--direction",
        direction,
        "--step-n",
        str(step_n),
        "--times",
        str(times),
        "--results-root",
        str(results_root),
        "--data-results-root",
        str(data_results_root),
    ]
    if skip_doctor:
        cmd.append("--skip-doctor")
    rc = _run_with_tee(cmd, PROJECT_ROOT, env, out_path)
    if rc != 0:
        raise RuntimeError(f"Variant {variant} failed with exit code {rc}")
    return out_path


def _parse_out(path: Path) -> tuple[dict, list[str]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    summary = None
    run_logs: list[str] = []
    for line in text.splitlines():
        if line.startswith("ABTEST_SUMMARY="):
            summary = json.loads(line.split("=", 1)[1])
        elif line.startswith("ABTEST_RESULT="):
            payload = json.loads(line.split("=", 1)[1])
            run_logs.append(payload.get("run_log", ""))
    if summary is None:
        raise RuntimeError(f"ABTEST_SUMMARY not found in {path}")
    return summary, run_logs


def _count_patterns(log_paths: list[str]) -> dict[str, int]:
    patterns = {
        "style_validation_failed": r"Expression style validation failed",
        "disallowed_parser_form": r"Disallowed parser-style arithmetic function forms",
        "mixed_var_naming": r"Mixed variable naming detected",
        "parse_failed_expr": r"Failed to parse expr",
        # JSON instability signals (allow both legacy wording and underscore issue names).
        "json_parse_failed": r"JSON parse failed|json_parse_failed",
        "json_fix_failed": r"json_fix_failed|json fix failed",
        "json_boundary_missing": r"json_boundary_missing|json boundary missing",
        "empty_response": r"empty_response|empty response",
    }
    out = {k: 0 for k in patterns}
    for lp in log_paths:
        if not lp:
            continue
        p = Path(lp)
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for key, pat in patterns.items():
            out[key] += len(re.findall(pat, text))
    return out


def _print_summary(b_summary: dict, b_logs: list[str], o_summary: dict, o_logs: list[str]) -> None:
    b_med = float(b_summary.get("elapsed_s_median", 0.0) or 0.0)
    o_med = float(o_summary.get("elapsed_s_median", 0.0) or 0.0)
    delta = o_med - b_med
    pct = (delta / b_med * 100.0) if b_med else 0.0

    b_cnt = _count_patterns(b_logs)
    o_cnt = _count_patterns(o_logs)

    print("\n=== AB RESULT ===")
    print(f"baseline elapsed_s_median: {b_med}")
    print(f"optimized elapsed_s_median: {o_med}")
    print(f"delta (opt-base): {round(delta, 3)} s ({pct:+.2f}%)")
    print(f"\nbaseline pattern counts: {b_cnt}")
    print(f"optimized pattern counts: {o_cnt}")

    print("\n=== 判定 ===")
    if delta < 0 and o_cnt["parse_failed_expr"] <= b_cnt["parse_failed_expr"]:
        print("更偏向正优化（提速且解析失败未恶化）。")
    elif delta >= 0 and o_cnt["parse_failed_expr"] < b_cnt["parse_failed_expr"]:
        print("更偏向稳定性优化（提速不明显，但失败减少）。")
    else:
        print("更偏向负优化或收益不确定，需要增加 TIMES 复测。")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="A/B test expression style validation with real APIs")
    p.add_argument("--direction", default="价量因子挖掘")
    p.add_argument("--step-n", type=int, default=3)
    p.add_argument("--times", type=int, default=1, help="30-minute target suggests 1")
    p.add_argument("--skip-doctor", action="store_true", default=True)
    p.add_argument("--no-skip-doctor", action="store_false", dest="skip_doctor")
    p.add_argument("--test-name", default=f"ab_expr_style_realapi_{_timestamp()}")
    p.add_argument("--results-root", default="/tmp/quanta_abtests_expr_style")
    p.add_argument("--data-results-root", default="/tmp/quanta_abtest_results_expr_style")
    return p


def main() -> int:
    args = _build_parser().parse_args()

    os.chdir(PROJECT_ROOT)
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required in .env")

    python_bin = PROJECT_ROOT / ".venv" / "bin" / "python"
    if not python_bin.exists():
        raise RuntimeError(f"Python not found: {python_bin}")

    env = os.environ.copy()
    env["USE_CHAT_CACHE"] = "false"
    env["DUMP_CHAT_CACHE"] = "false"

    backup_path = Path(tempfile.mkstemp(prefix="expression_style.py.bak.", dir="/tmp")[1])
    try:
        shutil.copy2(TARGET, backup_path)

        print("== [1/3] baseline (disable style check) ==")
        _disable_style_check(TARGET)
        b_out = _run_variant(
            variant="baseline",
            test_name=args.test_name,
            direction=args.direction,
            step_n=args.step_n,
            times=args.times,
            skip_doctor=args.skip_doctor,
            results_root=Path(args.results_root),
            data_results_root=Path(args.data_results_root),
            env=env,
            python_bin=python_bin,
        )

        print("== [2/3] optimized (restore style check) ==")
        shutil.copy2(backup_path, TARGET)
        o_out = _run_variant(
            variant="optimized",
            test_name=args.test_name,
            direction=args.direction,
            step_n=args.step_n,
            times=args.times,
            skip_doctor=args.skip_doctor,
            results_root=Path(args.results_root),
            data_results_root=Path(args.data_results_root),
            env=env,
            python_bin=python_bin,
        )

        print("== [3/3] summarize ==")
        b_summary, b_logs = _parse_out(b_out)
        o_summary, o_logs = _parse_out(o_out)
        _print_summary(b_summary, b_logs, o_summary, o_logs)

        print("\nDone. artifacts:")
        print(f"- {b_out}")
        print(f"- {o_out}")
        print(f"- {Path(args.results_root) / args.test_name}")
        return 0
    finally:
        if backup_path.exists():
            shutil.copy2(backup_path, TARGET)
            backup_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
