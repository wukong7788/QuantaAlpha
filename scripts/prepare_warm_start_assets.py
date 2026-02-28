#!/usr/bin/env python3
"""
Prepare warm-start assets from an existing experiment log folder.

This script is read-only to the running mining process: it reads log artifacts
(`trajectory_pool.json`, `evolution_state.json`) and writes derived assets into
`data/warm_start_assets/`.

Outputs (under one timestamped folder):
- seed_bank.json: diversified seed list for prompt few-shot injection.
- failure_playbook.jsonl: top failure categories -> short fix instructions.
- near_dup_report.json: duplicate/near-duplicate observation report (no blocking).
- summary.json: metadata + counts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


TASK_DIR_RE = re.compile(r"^(original|mutation|crossover)_(\d+)_(\d+)$")
TOKEN_FUNC_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
TOKEN_FEATURE_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _normalize_ws(expr: str) -> str:
    if not isinstance(expr, str):
        return ""
    return " ".join(expr.strip().split())


def _normalize_nows(expr: str) -> str:
    return re.sub(r"\s+", "", str(expr or "").strip())


def _signature(expr: str) -> set[str]:
    expr = str(expr or "")
    if not expr.strip():
        return set()
    tokens: set[str] = set()
    for m in TOKEN_FUNC_RE.finditer(expr):
        name = m.group(1)
        if name:
            tokens.add(f"fn:{name.lower()}")
    for m in TOKEN_FEATURE_RE.finditer(expr):
        feat = m.group(0)
        if feat:
            tokens.add(f"feat:{feat.lower()}")
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _safe_read_json(path: Path, retries: int = 6, sleep_s: float = 0.25) -> dict[str, Any]:
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


def _choose_log_root(project_root: Path, experiment_id: str | None, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = project_root / p
        return p

    roots = _discover_log_roots(project_root / "log")
    if not roots:
        raise SystemExit("No eligible log root found under ./log")
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


def _git_head(project_root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return out
    except Exception:
        return ""


def _mechanism_hint(expr: str) -> str:
    expr = _normalize_ws(expr)
    if not expr:
        return ""
    funcs = [m.group(1).upper() for m in TOKEN_FUNC_RE.finditer(expr)]
    feats = [m.group(0) for m in TOKEN_FEATURE_RE.finditer(expr)]
    funcs = funcs[:4]
    feats = feats[:4]
    parts = []
    if funcs:
        parts.append(" / ".join(funcs))
    if feats:
        parts.append("uses " + ", ".join(feats))
    return " | ".join(parts)


@dataclass
class Traj:
    tid: str
    phase: str
    round_idx: int
    direction_id: int
    parent_ids: list[str]
    metrics: dict[str, float | None]
    expressions: list[str]

    @property
    def rank_ic(self) -> float | None:
        v = self.metrics.get("RankIC")
        return float(v) if isinstance(v, (float, int)) else None


def _load_trajectories(pool: dict[str, Any]) -> dict[str, Traj]:
    raw = pool.get("trajectories", {})
    if not isinstance(raw, dict):
        return {}

    out: dict[str, Traj] = {}
    for tid, t in raw.items():
        if not isinstance(t, dict):
            continue
        phase = str(t.get("phase", "") or "")
        round_idx = int(_as_float(t.get("round_idx")) or 0)
        direction_id = int(_as_float(t.get("direction_id")) or 0)
        raw_parents = t.get("parent_ids", [])
        parent_ids = [str(x) for x in raw_parents] if isinstance(raw_parents, list) else []

        raw_metrics = t.get("backtest_metrics", {})
        metrics: dict[str, float | None] = {}
        if isinstance(raw_metrics, dict):
            for k, v in raw_metrics.items():
                metrics[str(k)] = _as_float(v)

        expressions: list[str] = []
        raw_factors = t.get("factors", [])
        if isinstance(raw_factors, list):
            for finfo in raw_factors:
                if not isinstance(finfo, dict):
                    continue
                expr = finfo.get("expression", finfo.get("factor_expression", ""))
                expr = str(expr or "").strip()
                if expr:
                    expressions.append(expr)

        out[str(tid)] = Traj(
            tid=str(tid),
            phase=phase,
            round_idx=round_idx,
            direction_id=direction_id,
            parent_ids=parent_ids,
            metrics=metrics,
            expressions=expressions,
        )
    return out


def _build_children_map(trajs: dict[str, Traj]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {}
    for tid, t in trajs.items():
        for pid in t.parent_ids:
            children.setdefault(pid, []).append(tid)
    return children


def _parent_transfer_stats(trajs: dict[str, Traj], children: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for pid, cids in children.items():
        if not cids:
            continue
        child_rankics: list[float] = []
        for cid in cids:
            ric = trajs.get(cid).rank_ic if cid in trajs else None
            if ric is not None:
                child_rankics.append(float(ric))
        if not child_rankics:
            continue
        parent_rankic = trajs.get(pid).rank_ic if pid in trajs else None
        n = len(child_rankics)
        n_pos = sum(1 for x in child_rankics if x > 0)
        best = max(child_rankics)
        improved = None
        if parent_rankic is not None:
            improved = sum(1 for x in child_rankics if x > parent_rankic) / n

        stats[pid] = {
            "child_count": n,
            "child_success_rate": round(n_pos / n, 4),
            "child_RankIC_best": round(best, 6),
            "child_improve_rate_vs_parent": round(improved, 4) if improved is not None else None,
        }
    return stats


def _select_diverse_seeds(
    trajs: dict[str, Traj],
    parent_stats: dict[str, dict[str, Any]],
    *,
    top_k: int,
    seed_count: int,
    max_sim: float,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, str]] = []
    for tid, t in trajs.items():
        ric = t.rank_ic
        if ric is None:
            continue
        transfer = parent_stats.get(tid, {})
        child_best = _as_float(transfer.get("child_RankIC_best"))
        child_succ = _as_float(transfer.get("child_success_rate"))
        bonus = 0.0
        if child_best is not None and child_best > ric:
            bonus += 0.6 * (child_best - ric)
        if child_succ is not None:
            bonus += 0.2 * child_succ * max(0.0, ric)
        seed_score = float(ric) + bonus
        scored.append((seed_score, tid))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_k = max(1, int(top_k))
    candidates = [tid for _score, tid in scored[:top_k]]

    picked: list[dict[str, Any]] = []
    picked_sigs: list[set[str]] = []
    for tid in candidates:
        t = trajs.get(tid)
        if t is None:
            continue
        expr = t.expressions[0] if t.expressions else ""
        sig = _signature(expr)
        if sig and picked_sigs:
            if any(_jaccard(sig, ps) >= max_sim for ps in picked_sigs if ps):
                continue

        transfer = parent_stats.get(tid, {})
        entry = {
            "trajectory_id": t.tid,
            "phase": t.phase,
            "round_idx": t.round_idx,
            "direction_id": t.direction_id,
            "expression": expr,
            "expr_normalized": _normalize_ws(expr),
            "signature": sorted(sig),
            "mechanism_hint": _mechanism_hint(expr),
            "metrics": {
                "RankIC": t.metrics.get("RankIC"),
                "RankICIR": t.metrics.get("RankICIR"),
                "IC": t.metrics.get("IC"),
                "annualized_return": t.metrics.get("annualized_return"),
                "information_ratio": t.metrics.get("information_ratio"),
                "max_drawdown": t.metrics.get("max_drawdown"),
            },
            "transferability": transfer,
            "prompt_fewshot": {
                "one_line_mechanism": "",
                "avoid": "",
            },
        }
        picked.append(entry)
        picked_sigs.append(sig)
        if len(picked) >= seed_count:
            break

    return picked


def _near_duplicate_report(trajs: dict[str, Traj], *, max_expr: int, sim_threshold: float) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for t in trajs.values():
        ric = t.rank_ic
        for expr in t.expressions:
            items.append(
                {
                    "trajectory_id": t.tid,
                    "phase": t.phase,
                    "round_idx": t.round_idx,
                    "RankIC": ric,
                    "expr": expr,
                    "expr_ws": _normalize_ws(expr),
                    "expr_nows": _normalize_nows(expr),
                    "signature": sorted(_signature(expr)),
                }
            )

    # Unique by expr_ws (keep best RankIC record as representative).
    by_expr_ws: dict[str, dict[str, Any]] = {}
    for it in items:
        key = it["expr_ws"]
        if not key:
            continue
        prev = by_expr_ws.get(key)
        if prev is None:
            by_expr_ws[key] = it
            continue
        prev_ric = _as_float(prev.get("RankIC")) or -1e9
        cur_ric = _as_float(it.get("RankIC")) or -1e9
        if cur_ric > prev_ric:
            by_expr_ws[key] = it

    uniq = list(by_expr_ws.values())
    uniq.sort(key=lambda x: (_as_float(x.get("RankIC")) or -1e9), reverse=True)
    uniq = uniq[: max(1, int(max_expr))]

    # Formatting duplicates: same expr_nows but different expr_ws.
    fmt_groups: dict[str, list[dict[str, Any]]] = {}
    for it in uniq:
        fmt_groups.setdefault(str(it["expr_nows"]), []).append(it)
    fmt_dups = [
        {"expr_nows": k, "count": len(v), "examples": [x["expr_ws"] for x in v[:5]]}
        for k, v in fmt_groups.items()
        if k and len(v) >= 2
    ]
    fmt_dups.sort(key=lambda x: x["count"], reverse=True)

    # Signature duplicates: same signature but different expr.
    sig_groups: dict[str, list[dict[str, Any]]] = {}
    for it in uniq:
        sig = tuple(it.get("signature", []))
        if not sig:
            continue
        sig_groups.setdefault("|".join(sig), []).append(it)
    sig_dups = [
        {
            "signature": k.split("|"),
            "count": len(v),
            "examples": [x["expr_ws"] for x in v[:5]],
        }
        for k, v in sig_groups.items()
        if len(v) >= 2
    ]
    sig_dups.sort(key=lambda x: x["count"], reverse=True)

    # Pairwise similarity on signatures (cheap heuristic).
    pairs: list[dict[str, Any]] = []
    sig_sets = [set(it.get("signature", [])) for it in uniq]
    for i in range(len(uniq)):
        for j in range(i + 1, len(uniq)):
            a = sig_sets[i]
            b = sig_sets[j]
            if not a or not b:
                continue
            sim = _jaccard(a, b)
            if sim >= sim_threshold:
                pairs.append(
                    {
                        "sim": round(sim, 6),
                        "a": uniq[i]["expr_ws"],
                        "b": uniq[j]["expr_ws"],
                    }
                )
    pairs.sort(key=lambda x: x["sim"], reverse=True)

    return {
        "params": {
            "max_expr": len(uniq),
            "signature_sim_threshold": sim_threshold,
        },
        "format_duplicates": fmt_dups[:50],
        "signature_duplicates": sig_dups[:50],
        "high_similarity_pairs": pairs[:200],
        "note": "This is observation-only. Do not block calculate/backtest until false-positive rate is evaluated.",
    }


def _run_doctor_json(project_root: Path, log_root: Path) -> dict[str, Any]:
    script = project_root / "scripts" / "run_doctor.py"
    py = project_root / ".venv" / "bin" / "python"
    if not py.exists():
        py = Path(os.environ.get("PYTHON", "python3"))
    try:
        out = subprocess.check_output(
            [str(py), str(script), "--log-root", str(log_root), "--doctor", "--json"],
            cwd=str(project_root),
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return json.loads(out)
    except Exception:
        return {}


def _failure_playbook_from_doctor(doctor_report: dict[str, Any]) -> list[dict[str, Any]]:
    playbook: list[dict[str, Any]] = []
    doctor = doctor_report.get("doctor", {})
    if not isinstance(doctor, dict):
        return playbook

    feedback = doctor.get("feedback", {})
    false_reasons = feedback.get("false_reasons", {}) if isinstance(feedback, dict) else {}
    if not isinstance(false_reasons, dict):
        false_reasons = {}

    def add(reason: str, count: int, fix: str, priority: int) -> None:
        playbook.append(
            {
                "reason": reason,
                "count": int(count),
                "priority": int(priority),
                "prompt_patch": fix,
            }
        )

    # Recommended prompt patches (short, reusable).
    for reason, count in sorted(false_reasons.items(), key=lambda x: int(x[1]), reverse=True):
        count_i = int(count)
        if reason == "syntax_error":
            add(
                reason,
                count_i,
                "表达式必须可解析：括号/逗号配对；所有变量统一使用 `$xxx`；避免未定义标识符；长度控制在阈值内。",
                1,
            )
        elif reason == "parser_function_form":
            add(
                reason,
                count_i,
                "禁止输出 `DIVIDE/SUBTRACT/MULTIPLY/ADD` 等 parser 函数形式；必须使用 `/ - * +` 与合法函数签名。",
                1,
            )
        elif reason == "mixed_dollar_variable":
            add(
                reason,
                count_i,
                "变量命名必须一致：同一变量只能出现 `$close` 这类形式，禁止 `$close` 与 `close` 混用。",
                1,
            )
        else:
            add(
                reason,
                count_i,
                "输出前自检：风格校验 + parse + evaluate 全通过才提交；失败则重写表达式而不是解释。",
                2,
            )

    playbook.sort(key=lambda x: (x["priority"], -x["count"]))
    return playbook


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description="Prepare warm-start assets from experiment logs.")
    p.add_argument("--log-root", default="", help="Explicit log root (e.g. log/relay_paper_repro_r2).")
    p.add_argument("--experiment-id", default="", help="Prefer log root that matches this experiment_id.")
    p.add_argument(
        "--out-dir",
        default="data/warm_start_assets",
        help="Output base directory (default: data/warm_start_assets).",
    )
    p.add_argument("--top-k", type=int, default=40, help="Top-K trajectory candidates before diversity filtering.")
    p.add_argument("--seed-count", type=int, default=10, help="How many seeds to select for seed_bank.json.")
    p.add_argument("--max-sim", type=float, default=0.55, help="Max Jaccard similarity allowed between picked seeds.")
    p.add_argument("--near-max-expr", type=int, default=500, help="Max unique expressions for near-dup observation.")
    p.add_argument("--near-sim-threshold", type=float, default=0.9, help="Signature similarity threshold for near-dup pairs.")
    args = p.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    log_root = _choose_log_root(
        project_root=project_root,
        experiment_id=(args.experiment_id or None),
        explicit=(args.log_root or None),
    )
    if not log_root.exists():
        raise SystemExit(f"log root not found: {log_root}")

    state = _safe_read_json(log_root / "evolution_state.json")
    meta = state.get("meta", {}) if isinstance(state, dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    exp_id = str(meta.get("experiment_id", "") or "").strip() or log_root.name

    pool = _safe_read_json(log_root / "trajectory_pool.json")
    trajs = _load_trajectories(pool)
    children = _build_children_map(trajs)
    parent_stats = _parent_transfer_stats(trajs, children)

    seeds = _select_diverse_seeds(
        trajs,
        parent_stats,
        top_k=max(5, int(args.top_k)),
        seed_count=max(1, int(args.seed_count)),
        max_sim=float(args.max_sim),
    )

    near_dup = _near_duplicate_report(
        trajs,
        max_expr=max(50, int(args.near_max_expr)),
        sim_threshold=float(args.near_sim_threshold),
    )

    doctor_json = _run_doctor_json(project_root, log_root)
    playbook_rows = _failure_playbook_from_doctor(doctor_json)

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = f"{exp_id}__{log_root.name}__{now}"
    out_base = Path(args.out_dir)
    if not out_base.is_absolute():
        out_base = project_root / out_base
    out_dir = out_base / folder
    out_dir.mkdir(parents=True, exist_ok=True)

    _write_json(out_dir / "seed_bank.json", {"meta": {"experiment_id": exp_id, "log_root": str(log_root)}, "seeds": seeds})
    _write_jsonl(out_dir / "failure_playbook.jsonl", playbook_rows)
    _write_json(out_dir / "near_dup_report.json", near_dup)

    summary = {
        "created_at": datetime.now().isoformat(),
        "project_root": str(project_root),
        "log_root": str(log_root),
        "experiment_id": exp_id,
        "git_head": _git_head(project_root),
        "counts": {
            "trajectories": len(trajs),
            "parents_with_children": len(parent_stats),
            "seed_count": len(seeds),
            "playbook_items": len(playbook_rows),
        },
        "params": {
            "top_k": int(args.top_k),
            "seed_count": int(args.seed_count),
            "max_sim": float(args.max_sim),
            "near_max_expr": int(args.near_max_expr),
            "near_sim_threshold": float(args.near_sim_threshold),
        },
        "outputs": {
            "seed_bank": str(out_dir / "seed_bank.json"),
            "failure_playbook": str(out_dir / "failure_playbook.jsonl"),
            "near_dup_report": str(out_dir / "near_dup_report.json"),
        },
        "note": "Assets are observation/summary artifacts. No mining behavior is changed by this script.",
    }
    _write_json(out_dir / "summary.json", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

