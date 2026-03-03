#!/usr/bin/env python3
"""Inspect current run.sh progress and output doctor diagnostics report."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import pickle
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

STEP_NAMES = [
    "factor_propose",
    "factor_construct",
    "factor_calculate",
    "factor_backtest",
    "feedback",
]

TASK_DIR_RE = re.compile(r"^(original|mutation|crossover)_(\d+)_(\d+)$")
SESSION_STEP_RE = re.compile(r"^(\d+)_([^.]+)$")

DOCTOR_SIGNAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "json_fix_failed": re.compile(r"JSON fix failed", re.IGNORECASE),
    "max_recursion": re.compile(r"maximum recursion depth exceeded", re.IGNORECASE),
    "parse_failed": re.compile(r"Failed to parse expression|Failed to parse expr", re.IGNORECASE),
    "no_json_boundaries": re.compile(r"No JSON boundaries found in model response", re.IGNORECASE),
}

DOCTOR_FALSE_REASON_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "parser_function_form",
        re.compile(
            r"unsupported parser-generated functions|\b(DIVIDE|SUBTRACT|MULTIPLY|ADD)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "mixed_dollar_variable",
        re.compile(
            r"without the dollar sign|inconsistent variable naming|mixing .*\$\w+.* and .*\b\w+\b",
            re.IGNORECASE,
        ),
    ),
    (
        "syntax_error",
        re.compile(r"syntaxerror|syntax error|invalid syntax", re.IGNORECASE),
    ),
    (
        "output_missing",
        re.compile(r"Expected output file not found", re.IGNORECASE),
    ),
]

DOCTOR_OPTIONAL_MODEL_PATTERNS: dict[str, re.Pattern[str]] = {
    "catboost": re.compile(r"CatBoostModel are skipped", re.IGNORECASE),
    "xgboost": re.compile(r"XGBModel is skipped", re.IGNORECASE),
    "pytorch": re.compile(r"PyTorch models are skipped", re.IGNORECASE),
}


@dataclass
class ProcessInfo:
    pid: int
    etime: str
    command: str


@dataclass
class TaskInfo:
    path: Path
    phase: str
    round_idx: int
    direction_id: int
    completed_steps: list[int]
    done_count: int
    current_step_idx: int | None
    mtime: float


def _shorten(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3] + "..."


def _format_bytes(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(max(0, num_bytes))
    unit_idx = 0
    while value >= 1024.0 and unit_idx < len(units) - 1:
        value /= 1024.0
        unit_idx += 1
    return f"{value:.2f} {units[unit_idx]}"


def _safe_read_json(path: Path, retries: int = 2, sleep_s: float = 0.15) -> dict[str, Any]:
    for attempt in range(retries + 1):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            if attempt >= retries:
                return {}
            time.sleep(sleep_s)
        except Exception:
            return {}
    return {}


def _project_root_from_here() -> Path:
    return Path(__file__).resolve().parent.parent


def _find_processes(project_root: Path) -> tuple[list[ProcessInfo], str | None]:
    try:
        out = subprocess.check_output(
            ["ps", "-ax", "-o", "pid=,etime=,command="],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        return [], str(exc)

    procs: list[ProcessInfo] = []
    root_text = str(project_root)
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\s*(\d+)\s+(\S+)\s+(.+)$", line)
        if not m:
            continue
        pid = int(m.group(1))
        etime = m.group(2)
        command = m.group(3)
        if "run_doctor.py" in command:
            continue

        is_run = (
            ("run.sh" in command)
            or ("quantaalpha mine" in command)
            or (".venv/bin/quantaalpha mine" in command)
        )
        if not is_run:
            continue

        in_repo = (root_text in command) or ("./run.sh" in command) or (" run.sh " in command)
        if not in_repo:
            continue

        procs.append(ProcessInfo(pid=pid, etime=etime, command=command))

    procs.sort(key=lambda p: p.pid)
    return procs, None


def _has_task_dirs(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    try:
        for child in path.iterdir():
            if child.is_dir() and TASK_DIR_RE.match(child.name):
                return True
    except Exception:
        return False
    return False


def _discover_log_roots(log_parent: Path) -> list[Path]:
    if not log_parent.exists() or not log_parent.is_dir():
        return []

    roots: list[Path] = []
    for child in log_parent.iterdir():
        if not child.is_dir():
            continue
        if (child / "evolution_state.json").exists() or (child / "trajectory_pool.json").exists() or _has_task_dirs(child):
            roots.append(child)

    roots.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return roots


def _choose_log_root(log_parent: Path, experiment_id: str | None) -> Path | None:
    roots = _discover_log_roots(log_parent)
    if not roots:
        return None
    if not experiment_id:
        return roots[0]

    scored: list[tuple[float, Path]] = []
    for root in roots:
        score = root.stat().st_mtime
        if experiment_id in root.name:
            score += 10_000_000_000.0
        state = _safe_read_json(root / "evolution_state.json")
        meta = state.get("meta", {}) if isinstance(state, dict) else {}
        if isinstance(meta, dict) and str(meta.get("experiment_id", "")) == experiment_id:
            score += 10_000_000_000.0
        scored.append((score, root))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _latest_mtime(path: Path) -> float:
    best = path.stat().st_mtime
    for root, _dirs, files in os.walk(path):
        for fn in files:
            fp = Path(root) / fn
            try:
                best = max(best, fp.stat().st_mtime)
            except Exception:
                continue
    return best


def _dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            fp = Path(root) / fn
            try:
                total += fp.stat().st_size
            except Exception:
                continue
    return total


def _parse_task(path: Path) -> TaskInfo | None:
    m = TASK_DIR_RE.match(path.name)
    if not m:
        return None
    phase = m.group(1)
    round_idx = int(m.group(2))
    direction_id = int(m.group(3))

    completed: set[int] = set()
    session_dir = path / "__session__" / "0"
    if session_dir.exists():
        for f in session_dir.iterdir():
            if not f.is_file():
                continue
            if f.suffix == ".txt":
                continue
            mm = SESSION_STEP_RE.match(f.name)
            if not mm:
                continue
            idx = int(mm.group(1))
            if 0 <= idx < len(STEP_NAMES):
                completed.add(idx)

    done_count = 0
    while done_count in completed and done_count < len(STEP_NAMES):
        done_count += 1

    current_step_idx = None if done_count >= len(STEP_NAMES) else done_count
    return TaskInfo(
        path=path,
        phase=phase,
        round_idx=round_idx,
        direction_id=direction_id,
        completed_steps=sorted(completed),
        done_count=done_count,
        current_step_idx=current_step_idx,
        mtime=_latest_mtime(path),
    )


def _discover_tasks(log_root: Path) -> list[TaskInfo]:
    tasks: list[TaskInfo] = []
    if not log_root.exists():
        return tasks
    for child in log_root.iterdir():
        if not child.is_dir():
            continue
        task = _parse_task(child)
        if task is not None:
            tasks.append(task)
    tasks.sort(key=lambda t: t.mtime, reverse=True)
    return tasks


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.min


def _collect_factor_summary(pool_data: dict[str, Any], limit: int, all_factors: bool) -> dict[str, Any]:
    trajectories_raw = pool_data.get("trajectories", {})
    if not isinstance(trajectories_raw, dict):
        trajectories_raw = {}

    trajectories: list[dict[str, Any]] = []
    for tid, payload in trajectories_raw.items():
        if not isinstance(payload, dict):
            continue
        item = payload.copy()
        item["trajectory_id"] = str(item.get("trajectory_id") or tid)
        trajectories.append(item)

    phase_counts: dict[str, int] = {}
    total_factors = 0
    unique_names: set[str] = set()
    for t in trajectories:
        phase = str(t.get("phase", "unknown"))
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
        factors = t.get("factors", [])
        if isinstance(factors, list):
            total_factors += len(factors)
            for f in factors:
                if isinstance(f, dict):
                    name = str(f.get("name", "")).strip()
                    if name:
                        unique_names.add(name)

    trajectories.sort(key=lambda t: _parse_iso(str(t.get("created_at", ""))), reverse=True)

    latest_lines: list[str] = []
    for t in trajectories:
        factors = t.get("factors", [])
        if not isinstance(factors, list):
            continue
        for f in factors:
            if not isinstance(f, dict):
                continue
            name = str(f.get("name", "")).strip()
            if not name:
                continue
            line = (
                f"{name} "
                f"[phase={t.get('phase', '?')}, round={t.get('round_idx', '?')}, dir={t.get('direction_id', '?')}]"
            )
            latest_lines.append(line)
            if not all_factors and len(latest_lines) >= limit:
                break
        if not all_factors and len(latest_lines) >= limit:
            break

    all_unique_sorted = sorted(unique_names)
    if all_factors:
        latest_lines = all_unique_sorted

    return {
        "total_trajectories": len(trajectories),
        "phase_counts": phase_counts,
        "total_factors": total_factors,
        "unique_factor_count": len(unique_names),
        "factor_lines": latest_lines,
        "all_unique_factors": all_unique_sorted,
    }


def _safe_load_pickle(path: Path) -> Any | None:
    try:
        with (
            path.open("rb") as f,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            return pickle.load(f)
    except Exception:
        return None


def _extract_text_payloads(payload: Any) -> list[str]:
    texts: list[str] = []
    queue: list[Any] = [payload]
    visited: set[int] = set()

    while queue:
        current = queue.pop()
        oid = id(current)
        if oid in visited:
            continue
        visited.add(oid)

        if isinstance(current, str):
            if current:
                texts.append(current)
            continue
        if isinstance(current, bytes):
            try:
                decoded = current.decode("utf-8", errors="ignore")
            except Exception:
                decoded = ""
            if decoded:
                texts.append(decoded)
            continue
        if isinstance(current, dict):
            queue.extend(list(current.values())[:16])
            continue
        if isinstance(current, (list, tuple, set)):
            queue.extend(list(current)[:24])
            continue

        for attr in (
            "stdout",
            "message",
            "msg",
            "final_feedback",
            "execution_feedback",
            "code_feedback",
            "value_feedback",
        ):
            value = getattr(current, attr, None)
            if value is not None:
                queue.append(value)
    return texts


def _find_task_dir_from_path(path: Path) -> str:
    for part in path.parts:
        if TASK_DIR_RE.match(part):
            return part
    return "<unknown>"


def _collect_system_signal_diagnostics(log_root: Path, max_examples: int) -> dict[str, Any]:
    counter: Counter[str] = Counter()
    examples: dict[str, list[dict[str, str]]] = {k: [] for k in DOCTOR_SIGNAL_PATTERNS}

    for pkl_path in log_root.rglob("*.pkl"):
        payload = _safe_load_pickle(pkl_path)
        if payload is None:
            continue
        texts = _extract_text_payloads(payload)
        for text in texts:
            for key, pattern in DOCTOR_SIGNAL_PATTERNS.items():
                if not pattern.search(text):
                    continue
                counter[key] += 1
                if len(examples[key]) < max_examples:
                    match = pattern.search(text)
                    if match is None:
                        snippet = text[:220]
                    else:
                        start = max(0, match.start() - 80)
                        end = min(len(text), match.end() + 140)
                        snippet = text[start:end]
                    examples[key].append(
                        {
                            "task_dir": _find_task_dir_from_path(pkl_path),
                            "file": str(pkl_path),
                            "snippet": " ".join(snippet.strip().split()),
                        }
                    )

    return {
        "counts": {key: int(counter.get(key, 0)) for key in DOCTOR_SIGNAL_PATTERNS},
        "examples": examples,
    }


def _categorize_false_reason(feedback: str) -> str:
    for reason, pattern in DOCTOR_FALSE_REASON_PATTERNS:
        if pattern.search(feedback):
            return reason
    return "other"


def _collect_feedback_diagnostics(log_root: Path, max_examples: int) -> dict[str, Any]:
    true_count = 0
    false_count = 0
    unknown_count = 0
    reason_counter: Counter[str] = Counter()
    examples: dict[str, list[dict[str, str]]] = {}

    for pkl_path in log_root.glob("**/d/evolving feedback/*/*.pkl"):
        payload = _safe_load_pickle(pkl_path)
        if payload is None:
            continue
        items = payload if isinstance(payload, (list, tuple)) else [payload]
        for item in items:
            decision = getattr(item, "final_decision", None)
            feedback = str(getattr(item, "final_feedback", "") or "").strip()
            if decision is True:
                true_count += 1
            elif decision is False:
                false_count += 1
                reason = _categorize_false_reason(feedback)
                reason_counter[reason] += 1
                examples.setdefault(reason, [])
                if len(examples[reason]) < max_examples:
                    examples[reason].append(
                        {
                            "task_dir": _find_task_dir_from_path(pkl_path),
                            "file": str(pkl_path),
                            "snippet": _shorten(" ".join(feedback.split()), 220),
                        }
                    )
            else:
                unknown_count += 1

    total = true_count + false_count + unknown_count
    false_ratio = (float(false_count) / float(total)) if total > 0 else 0.0
    return {
        "total_feedback_items": total,
        "true_decisions": true_count,
        "false_decisions": false_count,
        "unknown_decisions": unknown_count,
        "false_ratio": round(false_ratio, 4),
        "false_reasons": dict(reason_counter),
        "false_examples": examples,
    }


def _collect_exec_log_diagnostics(log_root: Path, max_examples: int) -> dict[str, Any]:
    qlib_log_files = sorted(log_root.glob("**/ef/Qlib_execute_log/*/*.pkl"))

    missing_optional_counter: Counter[str] = Counter()
    traceback_files = 0
    warning_files = 0
    severe_examples: list[dict[str, str]] = []
    warning_examples: list[dict[str, str]] = []

    for pkl_path in qlib_log_files:
        payload = _safe_load_pickle(pkl_path)
        if not isinstance(payload, str):
            continue

        has_warning = False
        has_traceback = False
        for name, pattern in DOCTOR_OPTIONAL_MODEL_PATTERNS.items():
            if pattern.search(payload):
                missing_optional_counter[name] += 1

        traceback_match = re.search(r"Traceback \(most recent call last\):", payload, re.IGNORECASE)
        if traceback_match:
            has_traceback = True
            traceback_files += 1

        warning_match = re.search(r"\bWARNING\b|RuntimeWarning|UserWarning|FutureWarning", payload)
        if warning_match is not None:
            has_warning = True
            warning_files += 1

        if has_traceback and len(severe_examples) < max_examples:
            start = max(0, traceback_match.start() - 120) if traceback_match else 0
            snippet = payload[start : min(len(payload), start + 260)]
            severe_examples.append(
                {
                    "task_dir": _find_task_dir_from_path(pkl_path),
                    "file": str(pkl_path),
                    "snippet": " ".join(snippet.split()),
                }
            )
        elif has_warning and len(warning_examples) < max_examples:
            wm = warning_match
            if wm is None:
                snippet = payload[:220]
            else:
                start = max(0, wm.start() - 80)
                end = min(len(payload), wm.end() + 140)
                snippet = payload[start:end]
            warning_examples.append(
                {
                    "task_dir": _find_task_dir_from_path(pkl_path),
                    "file": str(pkl_path),
                    "snippet": " ".join(snippet.split()),
                }
            )

    return {
        "qlib_execute_log_files": len(qlib_log_files),
        "missing_optional_models": {
            "catboost": int(missing_optional_counter.get("catboost", 0)),
            "xgboost": int(missing_optional_counter.get("xgboost", 0)),
            "pytorch": int(missing_optional_counter.get("pytorch", 0)),
        },
        "traceback_files": traceback_files,
        "warning_files": warning_files,
        "traceback_examples": severe_examples,
        "warning_examples": warning_examples,
    }


def _build_doctor_report(log_root: Path, max_examples: int) -> dict[str, Any]:
    feedback = _collect_feedback_diagnostics(log_root, max_examples=max_examples)
    exec_log = _collect_exec_log_diagnostics(log_root, max_examples=max_examples)
    system_signals = _collect_system_signal_diagnostics(log_root, max_examples=max_examples)

    system_count = sum(int(v) for v in system_signals.get("counts", {}).values())
    traceback_files = int(exec_log.get("traceback_files", 0))
    false_decisions = int(feedback.get("false_decisions", 0))

    if system_count > 0:
        status = "error"
    elif traceback_files > 0 or false_decisions > 0:
        status = "warning"
    else:
        status = "ok"

    return {
        "status": status,
        "system_signals": system_signals,
        "feedback": feedback,
        "execution_logs": exec_log,
    }


def _build_report(
    project_root: Path,
    log_root: Path,
    factor_limit: int,
    all_factors: bool,
    doctor: bool,
    doctor_max_examples: int,
) -> dict[str, Any]:
    state_path = log_root / "evolution_state.json"
    pool_path = log_root / "trajectory_pool.json"
    state = _safe_read_json(state_path)
    pool = _safe_read_json(pool_path)
    processes, process_scan_error = _find_processes(project_root)
    tasks = _discover_tasks(log_root)
    latest_task = tasks[0] if tasks else None

    factor_summary = _collect_factor_summary(pool, limit=factor_limit, all_factors=all_factors)

    phase_state = state.get("current_phase")
    round_state = state.get("current_round")
    run_control = state.get("run_control", {})
    meta = state.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}
    if not isinstance(run_control, dict):
        run_control = {}

    latest_task_payload: dict[str, Any] | None = None
    if latest_task is not None:
        latest_task_payload = {
            "task_dir": latest_task.path.name,
            "phase": latest_task.phase,
            "round_idx": latest_task.round_idx,
            "direction_id": latest_task.direction_id,
            "done_count": latest_task.done_count,
            "total_steps": len(STEP_NAMES),
            "completed_steps": latest_task.completed_steps,
            "current_step_idx": latest_task.current_step_idx,
            "current_step_name": (
                "completed"
                if latest_task.current_step_idx is None
                else STEP_NAMES[latest_task.current_step_idx]
            ),
            "mtime": datetime.fromtimestamp(latest_task.mtime).isoformat(),
        }

    exp_id = str(meta.get("experiment_id", "")).strip() if isinstance(meta, dict) else ""
    results_base_raw = os.environ.get("DATA_RESULTS_DIR", str(project_root / "data" / "results"))
    results_base = Path(results_base_raw)
    if not results_base.is_absolute():
        results_base = project_root / results_base

    run_paths = [log_root]
    if exp_id and exp_id != "shared":
        run_paths.extend(
            [
                results_base / f"workspace_{exp_id}",
                results_base / f"pickle_cache_{exp_id}",
            ]
        )

    run_path_items: list[dict[str, Any]] = []
    run_total_size = 0
    for p in run_paths:
        exists = p.exists()
        size_bytes = _dir_size_bytes(p) if exists else 0
        run_total_size += size_bytes
        run_path_items.append(
            {
                "path": str(p),
                "exists": exists,
                "size_bytes": size_bytes,
                "size_human": _format_bytes(size_bytes),
            }
        )

    du = shutil.disk_usage(project_root)
    disk_free_ratio = (float(du.free) / float(du.total)) if du.total > 0 else 0.0

    report = {
        "project_root": str(project_root),
        "log_root": str(log_root),
        "has_state_file": state_path.exists(),
        "has_pool_file": pool_path.exists(),
        "active_processes": [
            {"pid": p.pid, "etime": p.etime, "command": p.command}
            for p in processes
        ],
        "process_scan_error": process_scan_error,
        "state": {
            "current_phase": phase_state,
            "current_round": round_state,
            "saved_at_utc": meta.get("saved_at_utc"),
            "experiment_id": meta.get("experiment_id"),
            "run_control": run_control,
        },
        "latest_task": latest_task_payload,
        "factor_summary": factor_summary,
        "storage": {
            "run_data_total_bytes": run_total_size,
            "run_data_total_human": _format_bytes(run_total_size),
            "run_data_paths": run_path_items,
            "disk_total_bytes": int(du.total),
            "disk_total_human": _format_bytes(int(du.total)),
            "disk_used_bytes": int(du.used),
            "disk_used_human": _format_bytes(int(du.used)),
            "disk_free_bytes": int(du.free),
            "disk_free_human": _format_bytes(int(du.free)),
            "disk_free_ratio": round(disk_free_ratio, 4),
        },
    }
    if doctor:
        report["doctor"] = _build_doctor_report(
            log_root=log_root,
            max_examples=max(1, int(doctor_max_examples)),
        )
    return report


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Run Progress Snapshot")
    lines.append(f"project_root={report.get('project_root')}")
    lines.append(f"log_root={report.get('log_root')}")
    lines.append("")

    procs = report.get("active_processes", [])
    scan_error = str(report.get("process_scan_error") or "").strip()
    if procs:
        lines.append(f"active_processes={len(procs)}")
        for p in procs[:3]:
            lines.append(
                f"  - pid={p.get('pid')} etime={p.get('etime')} "
                f"cmd={_shorten(str(p.get('command', '')), 120)}"
            )
    elif scan_error:
        lines.append("active_processes=unknown")
        lines.append(f"process_scan_error={scan_error}")
    else:
        lines.append("active_processes=0")

    state = report.get("state", {})
    lines.append(
        f"controller_checkpoint=phase:{state.get('current_phase')} round:{state.get('current_round')}"
    )
    if state.get("saved_at_utc"):
        lines.append(f"state_saved_at_utc={state.get('saved_at_utc')}")
    if state.get("experiment_id"):
        lines.append(f"experiment_id={state.get('experiment_id')}")

    run_control = state.get("run_control", {})
    if isinstance(run_control, dict) and run_control:
        items = []
        for key in ["mode", "leg_index", "pending_stop_round", "target_max_rounds"]:
            if key in run_control:
                items.append(f"{key}={run_control.get(key)}")
        if items:
            lines.append("run_control=" + ", ".join(items))

    lines.append("")
    task = report.get("latest_task")
    if isinstance(task, dict):
        lines.append(
            f"latest_task={task.get('task_dir')} "
            f"(phase={task.get('phase')} round={task.get('round_idx')} dir={task.get('direction_id')})"
        )
        done_count = int(task.get("done_count", 0))
        total_steps = int(task.get("total_steps", len(STEP_NAMES)))
        current_name = task.get("current_step_name")
        if current_name == "completed":
            lines.append(f"step=completed ({total_steps}/{total_steps})")
        else:
            lines.append(f"step={done_count + 1}/{total_steps} {current_name}")
        done_labels = [
            STEP_NAMES[idx] if 0 <= idx < len(STEP_NAMES) else str(idx)
            for idx in task.get("completed_steps", [])
        ]
        lines.append(f"completed_steps={done_labels if done_labels else '[]'}")
        lines.append(f"task_last_update={task.get('mtime')}")
    else:
        lines.append("latest_task=<none>")

    lines.append("")
    factors = report.get("factor_summary", {})
    phase_counts = factors.get("phase_counts", {})
    lines.append(
        "trajectory_summary="
        + f"total:{factors.get('total_trajectories', 0)} "
        + f"by_phase:{phase_counts}"
    )
    lines.append(
        "factor_summary="
        + f"generated:{factors.get('total_factors', 0)} "
        + f"unique:{factors.get('unique_factor_count', 0)}"
    )

    factor_lines = factors.get("factor_lines", [])
    if factor_lines:
        lines.append("factors:")
        for idx, item in enumerate(factor_lines, start=1):
            lines.append(f"  {idx:>2}. {item}")
    else:
        lines.append("factors=<none>")

    storage = report.get("storage", {})
    if isinstance(storage, dict):
        lines.append("")
        lines.append(
            "storage="
            + f"run_data:{storage.get('run_data_total_human', '0 B')} "
            + f"disk_free:{storage.get('disk_free_human', '0 B')} "
            + f"free_ratio:{storage.get('disk_free_ratio', 0.0)}"
        )
        path_items = storage.get("run_data_paths", [])
        if isinstance(path_items, list):
            lines.append("run_data_paths:")
            for item in path_items:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    "  - "
                    + f"path={item.get('path')} "
                    + f"exists={item.get('exists')} "
                    + f"size={item.get('size_human')}"
                )

    doctor = report.get("doctor")
    if isinstance(doctor, dict):
        lines.append("")
        lines.append("doctor_report:")
        lines.append(f"status={doctor.get('status')}")

        system_signals = doctor.get("system_signals", {})
        if isinstance(system_signals, dict):
            counts = system_signals.get("counts", {})
            if isinstance(counts, dict):
                non_zero = {k: v for k, v in counts.items() if int(v) > 0}
                lines.append(
                    "system_signals="
                    + (str(non_zero) if non_zero else "<none>")
                )

        feedback = doctor.get("feedback", {})
        if isinstance(feedback, dict):
            lines.append(
                "feedback="
                + f"true:{feedback.get('true_decisions', 0)} "
                + f"false:{feedback.get('false_decisions', 0)} "
                + f"ratio:{feedback.get('false_ratio', 0.0)}"
            )
            reasons = feedback.get("false_reasons", {})
            if isinstance(reasons, dict) and reasons:
                lines.append(f"false_reasons={reasons}")

        execution_logs = doctor.get("execution_logs", {})
        if isinstance(execution_logs, dict):
            lines.append(
                "exec_logs="
                + f"files:{execution_logs.get('qlib_execute_log_files', 0)} "
                + f"traceback_files:{execution_logs.get('traceback_files', 0)} "
                + f"warning_files:{execution_logs.get('warning_files', 0)}"
            )
            optional = execution_logs.get("missing_optional_models", {})
            if isinstance(optional, dict):
                lines.append(f"optional_models_skipped={optional}")

    return "\n".join(lines)


def _render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Run Doctor Report")
    lines.append("")
    lines.append(f"- project_root: `{report.get('project_root')}`")
    lines.append(f"- log_root: `{report.get('log_root')}`")

    state = report.get("state", {})
    if isinstance(state, dict) and state.get("saved_at_utc"):
        lines.append(f"- state_saved_at_utc: `{state.get('saved_at_utc')}`")
    lines.append("")

    lines.append("## 1. 进程健康扫描")
    procs = report.get("active_processes", [])
    scan_error = str(report.get("process_scan_error") or "").strip()
    if procs:
        lines.append(f"- 状态: 运行中（active_processes={len(procs)}）")
        for p in procs[:3]:
            lines.append(
                f"- 进程: pid={p.get('pid')} etime={p.get('etime')} cmd=`{_shorten(str(p.get('command', '')), 120)}`"
            )
    elif scan_error:
        lines.append("- 状态: 无法扫描进程（权限/环境限制）")
        lines.append(f"- process_scan_error: `{_shorten(scan_error, 180)}`")
    else:
        lines.append("- 状态: 未检测到活跃 `run.sh/quantaalpha mine` 进程（可能已结束或当前未运行）")
    lines.append("")

    lines.append("## 2. 当前运行位置")
    if isinstance(state, dict):
        lines.append(
            f"- controller_checkpoint: phase=`{state.get('current_phase')}` round=`{state.get('current_round')}`"
        )
        if state.get("experiment_id"):
            lines.append(f"- experiment_id: `{state.get('experiment_id')}`")

    task = report.get("latest_task")
    if isinstance(task, dict):
        lines.append(
            "- latest_task: "
            + f"`{task.get('task_dir')}` "
            + f"(phase={task.get('phase')}, round={task.get('round_idx')}, dir={task.get('direction_id')})"
        )
        done_count = int(task.get("done_count", 0))
        total_steps = int(task.get("total_steps", len(STEP_NAMES)))
        current_name = task.get("current_step_name")
        if current_name == "completed":
            lines.append(f"- step: completed ({total_steps}/{total_steps})")
        else:
            lines.append(f"- step: {done_count + 1}/{total_steps} `{current_name}`")
        lines.append(f"- task_last_update: `{task.get('mtime')}`")
    else:
        lines.append("- latest_task: `<none>`")
    lines.append("")

    lines.append("## 3. 因子生成质量")
    factors = report.get("factor_summary", {})
    if isinstance(factors, dict):
        lines.append(
            f"- trajectory_summary: total={factors.get('total_trajectories', 0)} by_phase={factors.get('phase_counts', {})}"
        )
        lines.append(
            f"- factor_summary: generated={factors.get('total_factors', 0)} unique={factors.get('unique_factor_count', 0)}"
        )

    doctor = report.get("doctor")
    if isinstance(doctor, dict):
        feedback = doctor.get("feedback", {})
        if isinstance(feedback, dict):
            lines.append(
                "- feedback_quality: "
                + f"true={feedback.get('true_decisions', 0)} "
                + f"false={feedback.get('false_decisions', 0)} "
                + f"false_ratio={feedback.get('false_ratio', 0.0)}"
            )
            reasons = feedback.get("false_reasons", {})
            if isinstance(reasons, dict) and reasons:
                lines.append(f"- false_reasons: {reasons}")
    lines.append("")

    lines.append("## 4. 存储占用与磁盘余量")
    storage = report.get("storage", {})
    if isinstance(storage, dict):
        lines.append(
            "- run_data_usage: "
            + f"`{storage.get('run_data_total_human', '0 B')}`"
        )
        lines.append(
            "- disk_free_space: "
            + f"`{storage.get('disk_free_human', '0 B')}` "
            + f"(free_ratio={storage.get('disk_free_ratio', 0.0)})"
        )
        path_items = storage.get("run_data_paths", [])
        if isinstance(path_items, list) and path_items:
            lines.append("- run_data_breakdown:")
            for item in path_items:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"  - `{item.get('path')}` "
                    + f"(exists={item.get('exists')}, size={item.get('size_human')})"
                )
    lines.append("")

    lines.append("## 5. 关键报错/异常与研究影响")
    impact_notes: list[str] = []
    impact_level = "OK"

    if isinstance(doctor, dict):
        lines.append(f"- doctor_status: `{doctor.get('status')}`")

        system_signals = doctor.get("system_signals", {})
        if isinstance(system_signals, dict):
            counts = system_signals.get("counts", {})
            if isinstance(counts, dict):
                non_zero = {k: v for k, v in counts.items() if int(v) > 0}
                lines.append(f"- system_signals: {non_zero if non_zero else '<none>'}")
                if non_zero:
                    impact_notes.append("存在系统级异常信号（可能影响流程稳定性）")
                    impact_level = "CRITICAL"

        execution_logs = doctor.get("execution_logs", {})
        if isinstance(execution_logs, dict):
            traceback_files = int(execution_logs.get("traceback_files", 0))
            warning_files = int(execution_logs.get("warning_files", 0))
            lines.append(
                "- execution_logs: "
                + f"files={execution_logs.get('qlib_execute_log_files', 0)} "
                + f"traceback_files={traceback_files} warning_files={warning_files}"
            )
            optional = execution_logs.get("missing_optional_models", {})
            if isinstance(optional, dict):
                lines.append(f"- optional_models_skipped: {optional}")

            if traceback_files > 0 and impact_level != "CRITICAL":
                impact_level = "HIGH"
                impact_notes.append("存在执行 Traceback，可能影响回测或指标可信度")

        feedback = doctor.get("feedback", {})
        if isinstance(feedback, dict):
            false_ratio = float(feedback.get("false_ratio", 0.0))
            if false_ratio >= 0.20 and impact_level not in {"CRITICAL", "HIGH"}:
                impact_level = "HIGH"
                impact_notes.append("因子失败率偏高（>=20%），研究质量受影响")
            elif false_ratio >= 0.10 and impact_level == "OK":
                impact_level = "MEDIUM"
                impact_notes.append("因子失败率中等（>=10%），建议优化表达式质量")

    if not impact_notes:
        impact_notes.append("未发现关键系统级异常，当前主要是常规质量波动")

    lines.append(f"- quality_impact_level: `{impact_level}`")
    lines.append(f"- quality_impact_assessment: {'; '.join(impact_notes)}")

    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Show current run.sh mining progress: active process, round/phase/step, and generated factors."
        )
    )
    p.add_argument(
        "--log-root",
        default="",
        help="Explicit log root (for example: log/relay_paper_repro_r2). If omitted, auto-detect latest.",
    )
    p.add_argument(
        "--experiment-id",
        default="",
        help="Prefer log root whose folder name or state meta.experiment_id matches this value.",
    )
    p.add_argument(
        "--watch",
        type=int,
        default=0,
        help="Refresh every N seconds (0 means run once).",
    )
    p.add_argument(
        "--factor-limit",
        type=int,
        default=20,
        help="How many factors to print (ignored when --all-factors).",
    )
    p.add_argument(
        "--all-factors",
        action="store_true",
        help="Print all unique factor names from trajectory_pool.json.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of text.",
    )
    p.add_argument(
        "--markdown",
        action="store_true",
        help="Output a markdown report instead of plain text.",
    )
    p.add_argument(
        "--doctor",
        action="store_true",
        help="Include log diagnostics (error signals, failed decision reasons, execution warning summary).",
    )
    p.add_argument(
        "--doctor-max-examples",
        type=int,
        default=3,
        help="Max examples per diagnosis category.",
    )
    return p.parse_args()


def _run_once(args: argparse.Namespace) -> int:
    project_root = _project_root_from_here()
    if args.log_root:
        log_root = Path(args.log_root)
        if not log_root.is_absolute():
            log_root = project_root / log_root
    else:
        log_root = _choose_log_root(project_root / "log", args.experiment_id or None)
        if log_root is None:
            print("Error: no eligible log root found under ./log", file=sys.stderr)
            return 1

    if not log_root.exists():
        print(f"Error: log root not found: {log_root}", file=sys.stderr)
        return 1

    report = _build_report(
        project_root=project_root,
        log_root=log_root,
        factor_limit=max(1, int(args.factor_limit)),
        all_factors=bool(args.all_factors),
        doctor=bool(args.doctor),
        doctor_max_examples=max(1, int(args.doctor_max_examples)),
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.markdown:
        print(_render_markdown(report))
    else:
        print(_render_text(report))
    return 0


def main() -> int:
    args = _parse_args()
    watch = max(0, int(args.watch or 0))
    if watch <= 0:
        return _run_once(args)

    try:
        while True:
            print("\033[2J\033[H", end="")
            now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[run_doctor] refreshed_at={now_text}")
            code = _run_once(args)
            if code != 0:
                return code
            print(f"\n(refresh every {watch}s, Ctrl+C to stop)")
            time.sleep(watch)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
