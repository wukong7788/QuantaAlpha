#!/usr/bin/env python3
"""View and compare offline backtest results from metrics files.

This tool reads existing *_backtest_metrics.json files and compares them
horizontally. It also reports potential overwrite risk based on filename scheme
and best-effort run metadata from log/backtest_manual/pids/*.pid.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

TIMESTAMPED_RE = re.compile(
    r"^(?P<prefix>.+)_n(?P<n>\d+)_(?P<ts>\d{8}_\d{6})_backtest_metrics\.json$"
)
LEGACY_RE = re.compile(r"^(?P<prefix>.+)_backtest_metrics\.json$")
PID_FILE_RE = re.compile(r"^backtest_(\d{8}_\d{6})\.pid$")


@dataclass
class RunMeta:
    pid_path: Path
    ts: str
    library_stem: str
    exit_code: int | None
    bob_enabled: bool
    mode: str
    quality_min: str
    max_factors: str
    corr_dedup: bool
    dedup_topn_effective: str
    dedup_per_cluster: str
    dedup_corr_threshold: str
    dedup_sample_size: str
    bob_grade: str
    bob_top: str
    bob_metric: str

    @property
    def source_tag(self) -> str:
        return "BOB" if self.bob_enabled else "EXP"

    @property
    def params_tag(self) -> str:
        base = f"m={self.mode or '-'};q={self.quality_min or '-'};mf={self.max_factors or '-'}"
        if self.corr_dedup:
            topn = self.dedup_topn_effective or "-"
            k = self.dedup_per_cluster or "-"
            th = self.dedup_corr_threshold or "-"
            ss = self.dedup_sample_size or "-"
            base = f"{base};dedup=on(topn={topn},k={k},th={th},ss={ss})"
        if self.bob_enabled:
            return f"{base};bob={self.bob_grade or '-'}/{self.bob_top or '-'}({self.bob_metric or '-'})"
        return base


@dataclass
class ResultRecord:
    idx: int
    path: Path
    stem: str
    exp_name: str
    scheme: str
    num_factors: int | None
    ts_text: str
    ts_sort: str
    collision_key: str
    metrics: dict[str, Any]
    run_meta: RunMeta | None


@dataclass
class OverwriteStats:
    timestamped_files: int
    legacy_files: int
    versioned_groups: int
    success_pid_runs: int
    parameter_risk_stems: list[str]


def _safe_float(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _format_ratio(v: float | None) -> str:
    return "-" if v is None else f"{v:.4f}"


def _format_pct(v: float | None) -> str:
    return "-" if v is None else f"{v * 100:.2f}%"


def _shorten(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    if max_len <= 3:
        return s[:max_len]
    return s[: max_len - 3] + "..."


def _as_bool(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_pid_file(path: Path) -> RunMeta | None:
    m = PID_FILE_RE.match(path.name)
    if not m:
        return None
    ts = m.group(1)

    data: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    except Exception:
        return None

    lib = data.get("library", "")
    library_stem = Path(lib).name if lib else ""

    exit_code_raw = data.get("exit_code", "")
    exit_code: int | None
    try:
        exit_code = int(exit_code_raw)
    except Exception:
        exit_code = None

    return RunMeta(
        pid_path=path,
        ts=ts,
        library_stem=library_stem,
        exit_code=exit_code,
        bob_enabled=_as_bool(data.get("bob_enabled", "false")),
        mode=data.get("mode", ""),
        quality_min=data.get("quality_min", ""),
        max_factors=data.get("max_factors", ""),
        corr_dedup=_as_bool(data.get("corr_dedup", "false")),
        dedup_topn_effective=data.get("dedup_topn_effective", ""),
        dedup_per_cluster=data.get("dedup_per_cluster", ""),
        dedup_corr_threshold=data.get("dedup_corr_threshold", ""),
        dedup_sample_size=data.get("dedup_sample_size", ""),
        bob_grade=data.get("bob_grade", ""),
        bob_top=data.get("bob_top", ""),
        bob_metric=data.get("bob_metric", ""),
    )


def _parse_ts(ts_text: str) -> datetime | None:
    try:
        return datetime.strptime(ts_text, "%Y%m%d_%H%M%S")
    except Exception:
        return None


def _load_pid_metas(project_root: Path) -> list[RunMeta]:
    pid_dir = project_root / "log" / "backtest_manual" / "pids"
    if not pid_dir.exists():
        return []

    metas: list[RunMeta] = []
    for p in sorted(pid_dir.glob("backtest_*.pid")):
        meta = _parse_pid_file(p)
        if meta is not None:
            metas.append(meta)
    return metas


def _parse_record(path: Path, idx: int) -> ResultRecord | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}

    exp_name = str(payload.get("experiment_name") or "")
    stem = path.name.removesuffix("_backtest_metrics.json")

    m_ts = TIMESTAMPED_RE.match(path.name)
    if m_ts:
        prefix = m_ts.group("prefix")
        n_text = m_ts.group("n")
        ts = m_ts.group("ts")
        num_factors = int(n_text)
        scheme = "timestamped"
        collision_key = f"{prefix}_n{n_text}"
        ts_text = ts
        ts_sort = ts
    else:
        m_legacy = LEGACY_RE.match(path.name)
        prefix = m_legacy.group("prefix") if m_legacy else stem
        num_factors = payload.get("num_factors")
        if not isinstance(num_factors, int):
            num_factors = None
        scheme = "legacy"
        collision_key = prefix
        ts_sort = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d_%H%M%S")
        ts_text = "legacy"

    return ResultRecord(
        idx=idx,
        path=path,
        stem=stem,
        exp_name=exp_name,
        scheme=scheme,
        num_factors=num_factors,
        ts_text=ts_text,
        ts_sort=ts_sort,
        collision_key=collision_key,
        metrics=metrics,
        run_meta=None,
    )


def _discover_records(result_dir: Path) -> list[ResultRecord]:
    files = sorted(
        result_dir.glob("*_backtest_metrics.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    records: list[ResultRecord] = []
    for p in files:
        r = _parse_record(p, len(records) + 1)
        if r is not None:
            records.append(r)
    for i, r in enumerate(records, start=1):
        r.idx = i
    return records


def _attach_run_meta(records: list[ResultRecord], metas: list[RunMeta]) -> None:
    if not metas:
        return

    for r in records:
        candidates: list[tuple[int, int, RunMeta]] = []
        rec_ts = _parse_ts(r.ts_sort)
        for m in metas:
            if m.exit_code is not None and m.exit_code != 0:
                continue

            score = 0
            if m.library_stem and (r.stem == m.library_stem or r.stem.startswith(f"{m.library_stem}_n")):
                score += 1000

            diff_penalty = 999999
            m_ts = _parse_ts(m.ts)
            if rec_ts is not None and m_ts is not None:
                diff_penalty = int(abs((rec_ts - m_ts).total_seconds()))
                if diff_penalty <= 4 * 3600:
                    score += 100

            candidates.append((score, -diff_penalty, m))

        if not candidates:
            continue

        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        best = candidates[0][2]
        if candidates[0][0] > 0:
            r.run_meta = best


def _parse_pick(raw: str, max_idx: int) -> list[int]:
    raw = raw.strip().lower()
    if not raw:
        return []
    if raw == "all":
        return list(range(1, max_idx + 1))

    chosen: list[int] = []
    seen = set()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        if not token.isdigit():
            continue
        val = int(token)
        if 1 <= val <= max_idx and val not in seen:
            chosen.append(val)
            seen.add(val)
    return chosen


def _make_type_tag(r: ResultRecord) -> str:
    run_tag = r.run_meta.source_tag if r.run_meta is not None else ("BOB" if "bob" in r.stem.lower() else "EXP")
    scheme_tag = "T" if r.scheme == "timestamped" else "L"
    return f"{run_tag}/{scheme_tag}"


def _print_candidate_list(records: list[ResultRecord], latest: int) -> None:
    show = records[: max(0, latest)]
    print("Available result files:")
    for r in show:
        n_txt = "-" if r.num_factors is None else str(r.num_factors)
        print(
            f"  {r.idx:>2}) {_make_type_tag(r)} "
            f"n={n_txt:<4} ts={r.ts_text:<15} "
            f"{_shorten(r.stem, 72)}"
        )


def _build_row(r: ResultRecord) -> dict[str, str]:
    metrics = r.metrics
    ic = _safe_float(metrics.get("IC"))
    rank_ic = _safe_float(metrics.get("Rank IC"))
    ir = _safe_float(metrics.get("information_ratio"))
    ann_ret = _safe_float(metrics.get("annualized_return"))
    mdd = _safe_float(metrics.get("max_drawdown"))
    calmar = _safe_float(metrics.get("calmar_ratio"))

    params = r.run_meta.params_tag if r.run_meta is not None else "-"

    return {
        "#": str(r.idx),
        "Type": _make_type_tag(r),
        "Experiment": _shorten(r.exp_name or r.stem, 26),
        "N": "-" if r.num_factors is None else str(r.num_factors),
        "Time": r.ts_text,
        "IR": _format_ratio(ir),
        "AnnRet": _format_pct(ann_ret),
        "MDD": _format_pct(mdd),
        "Calmar": _format_ratio(calmar),
        "IC": _format_ratio(ic),
        "RankIC": _format_ratio(rank_ic),
        "Params": _shorten(params, 34),
        "File": _shorten(r.path.name, 52),
    }


def _print_table(rows: list[dict[str, str]], headers: list[str]) -> None:
    widths = {h: len(h) for h in headers}
    for row in rows:
        for h in headers:
            widths[h] = max(widths[h], len(row[h]))

    sep = " | "
    line = "-+-".join("-" * widths[h] for h in headers)
    print(sep.join(h.ljust(widths[h]) for h in headers))
    print(line)
    for row in rows:
        print(sep.join(row[h].ljust(widths[h]) for h in headers))


def _build_overwrite_stats(records: list[ResultRecord], metas: list[RunMeta]) -> OverwriteStats:
    legacy = [r for r in records if r.scheme == "legacy"]
    timestamped = [r for r in records if r.scheme == "timestamped"]

    groups: dict[str, list[ResultRecord]] = {}
    for r in timestamped:
        groups.setdefault(r.collision_key, []).append(r)
    multi_version = sum(1 for g in groups.values() if len(g) > 1)

    success = [m for m in metas if m.exit_code == 0]

    legacy_stems = {r.stem for r in legacy}
    stem_signatures: dict[str, set[str]] = {}
    for m in success:
        if not m.library_stem:
            continue
        sig = m.params_tag
        stem_signatures.setdefault(m.library_stem, set()).add(sig)

    parameter_risk_stems = sorted(
        stem for stem, sigs in stem_signatures.items() if stem in legacy_stems and len(sigs) > 1
    )

    return OverwriteStats(
        timestamped_files=len(timestamped),
        legacy_files=len(legacy),
        versioned_groups=multi_version,
        success_pid_runs=len(success),
        parameter_risk_stems=parameter_risk_stems,
    )


def _print_overwrite_check(stats: OverwriteStats) -> None:
    print("\nOverwrite check (file-based, no recompute):")
    print(f"  timestamped_files={stats.timestamped_files}")
    print(f"  legacy_files={stats.legacy_files}")
    print(f"  versioned_groups(>1 snapshots)={stats.versioned_groups}")
    print(f"  successful_backtest_runs(pid)={stats.success_pid_runs}")

    if stats.legacy_files > 0:
        print("  warning=legacy filenames detected; these names can be overwritten by later runs.")
    else:
        print("  warning=none")

    if stats.parameter_risk_stems:
        joined = ", ".join(_shorten(s, 28) for s in stats.parameter_risk_stems)
        print(f"  parameter_overwrite_risk=legacy stem has multiple parameter sets: {joined}")
    else:
        print("  parameter_overwrite_risk=none_detected")

    print("  note=comparison is direct from existing metrics files only.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="View and compare offline backtest metrics files."
    )
    parser.add_argument(
        "--result-dir",
        default="data/results/backtest_v2_results",
        help="Directory containing *_backtest_metrics.json files.",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=30,
        help="Show latest N candidates in selector list (default: 30).",
    )
    parser.add_argument(
        "--pick",
        default="",
        help="Comma-separated indexes to compare, e.g. 1,2,5 (or 'all').",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Force interactive selector prompt.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result_dir = Path(args.result_dir)
    if not result_dir.exists():
        print(f"Error: result dir not found: {result_dir}")
        return 1

    records = _discover_records(result_dir)
    if not records:
        print(f"No *_backtest_metrics.json files found in: {result_dir}")
        return 1

    project_root = Path.cwd()
    metas = _load_pid_metas(project_root)
    _attach_run_meta(records, metas)

    _print_candidate_list(records, max(1, args.latest))
    stats = _build_overwrite_stats(records, metas)
    _print_overwrite_check(stats)

    pick_raw = args.pick.strip()
    interactive = args.interactive or (not pick_raw and sys.stdin.isatty())

    if interactive and not pick_raw:
        default_count = min(5, len(records))
        default_pick = ",".join(str(i) for i in range(1, default_count + 1))
        print()
        pick_raw = input(f"Select compare targets (e.g. 1,2,3 / all) [{default_pick}]: ").strip()
        if not pick_raw:
            pick_raw = default_pick

    picked_idx = _parse_pick(pick_raw, len(records))
    if not picked_idx:
        picked_idx = list(range(1, min(5, len(records)) + 1))

    selected = [records[i - 1] for i in picked_idx]
    rows = [_build_row(r) for r in selected]
    headers = [
        "#",
        "Type",
        "Experiment",
        "N",
        "Time",
        "IR",
        "AnnRet",
        "MDD",
        "Calmar",
        "IC",
        "RankIC",
        "Params",
        "File",
    ]

    print("\nHorizontal comparison:")
    _print_table(rows, headers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
