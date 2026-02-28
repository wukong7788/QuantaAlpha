#!/usr/bin/env python3
"""
Safe cleanup utility for QuantaAlpha.

Default behavior is dry-run (preview only). To actually delete, pass:
  --apply --yes

Examples:
  # Interactive wizard (if no args and in TTY, wizard starts automatically)
  .venv/bin/python scripts/safe_cleanup.py --interactive

  # Preview cleanup plan (keep newest workspace/pickle cache)
  .venv/bin/python scripts/safe_cleanup.py

  # Actually cleanup old workspace/pickle cache
  .venv/bin/python scripts/safe_cleanup.py --apply --yes

  # Also cleanup old timestamp logs (keep latest 5)
  .venv/bin/python scripts/safe_cleanup.py --clean-logs --apply --yes

  # Prune factor cache files not referenced by factor libraries
  .venv/bin/python scripts/safe_cleanup.py --prune-factor-cache --apply --yes

  # Cleanup minirun temporary artifacts via manifest files
  .venv/bin/python scripts/safe_cleanup.py --clean-minirun-temp --apply --yes
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


TIMESTAMP_LOG_DIR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_.+")


@dataclass
class DeletePlan:
    path: Path
    reason: str
    size_bytes: int


def _human_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size_bytes}B"


def _ensure_under_root(path: Path, root: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as e:
        raise ValueError(f"{label} must be inside repo root: {resolved}") from e
    return resolved


def _path_size(path: Path) -> int:
    if not path.exists() and not path.is_symlink():
        return 0
    if path.is_symlink():
        return path.lstat().st_size
    if path.is_file():
        return path.stat().st_size

    total = 0
    for dirpath, _, filenames in os.walk(path, followlinks=False):
        base = Path(dirpath)
        for name in filenames:
            fp = base / name
            try:
                total += fp.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return total


def _sorted_dirs_by_mtime(parent: Path, pattern: str) -> list[Path]:
    dirs = [p for p in parent.glob(pattern) if p.is_dir()]
    return sorted(dirs, key=lambda p: p.stat().st_mtime, reverse=True)


def _collect_old_dirs(parent: Path, pattern: str, keep_latest: int, reason: str) -> list[DeletePlan]:
    if keep_latest < 0:
        raise ValueError(f"keep_latest must be >= 0, got {keep_latest}")
    candidates = _sorted_dirs_by_mtime(parent, pattern)
    stale = candidates[keep_latest:]
    return [DeletePlan(path=p, reason=reason, size_bytes=_path_size(p)) for p in stale]


def _resolve_glob_paths(root: Path, pattern: str) -> list[Path]:
    abs_pattern = pattern if Path(pattern).is_absolute() else str(root / pattern)
    return sorted(Path(p).resolve() for p in glob.glob(abs_pattern))


def _load_factor_md5_from_library(library_path: Path) -> set[str]:
    with library_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    factors = data.get("factors", {})
    if not isinstance(factors, dict):
        return set()

    md5_set: set[str] = set()
    for info in factors.values():
        if not isinstance(info, dict):
            continue
        expr = info.get("factor_expression", "")
        if not isinstance(expr, str) or not expr.strip():
            continue
        md5_set.add(hashlib.md5(expr.encode()).hexdigest())
    return md5_set


def _collect_orphan_factor_cache(
    repo_root: Path,
    factor_cache_dir: Path,
    factorlib_glob: str,
    verbose: bool = True,
) -> list[DeletePlan]:
    if not factor_cache_dir.exists():
        return []

    library_paths = _resolve_glob_paths(repo_root, factorlib_glob)
    library_paths = [p for p in library_paths if p.is_file()]
    if not library_paths:
        if verbose:
            print(
                f"[WARN] No factor library files matched: {factorlib_glob}. "
                "Skip factor_cache prune."
            )
        return []

    keep_md5: set[str] = set()
    for lib_path in library_paths:
        try:
            keep_md5.update(_load_factor_md5_from_library(lib_path))
        except Exception as e:
            if verbose:
                print(f"[WARN] Failed to read {lib_path}: {e}")

    if not keep_md5:
        if verbose:
            print("[WARN] No factor_expression found in factor libraries. Skip factor_cache prune.")
        return []

    plans: list[DeletePlan] = []
    cache_files = list(factor_cache_dir.glob("*.pkl")) + list(factor_cache_dir.glob("*.parquet"))
    for cache_file in cache_files:
        if cache_file.stem not in keep_md5:
            plans.append(
                DeletePlan(
                    path=cache_file,
                    reason="orphan factor_cache (not referenced by factor libraries)",
                    size_bytes=_path_size(cache_file),
                )
            )
    return plans


def _collect_timestamp_log_dirs(log_dir: Path) -> list[Path]:
    if not log_dir.exists():
        return []
    dirs = [p for p in log_dir.iterdir() if p.is_dir() and TIMESTAMP_LOG_DIR_PATTERN.match(p.name)]
    return sorted(dirs, key=lambda p: p.stat().st_mtime, reverse=True)


def _parse_minirun_manifest(manifest_path: Path) -> tuple[str, list[str]]:
    """
    Parse minirun manifest and return (tag, raw paths).
    raw paths may be absolute or repo-relative.
    """
    tag = manifest_path.stem
    raw_paths: list[str] = []
    in_log_block = False

    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s == "new_log_dirs_begin":
            in_log_block = True
            continue
        if s == "new_log_dirs_end":
            in_log_block = False
            continue

        if in_log_block:
            raw_paths.append(s)
            continue

        if "=" not in s:
            continue
        key, val = s.split("=", 1)
        key = key.strip()
        val = val.strip()
        if key == "tag" and val:
            tag = val
        elif key in {"workspace_path", "pickle_cache_path", "factor_library_path", "latest_log_dir"} and val:
            raw_paths.append(val)

    return tag, raw_paths


def _collect_minirun_artifacts_from_manifests(
    repo_root: Path,
    manifest_dir: Path,
    keep_latest: int,
    minirun_tag: str | None = None,
) -> list[DeletePlan]:
    if keep_latest < 0:
        raise ValueError(f"keep_latest must be >= 0, got {keep_latest}")
    if not manifest_dir.exists():
        return []

    manifests = [p for p in manifest_dir.glob("*.txt") if p.is_file()]
    manifests = sorted(manifests, key=lambda p: p.stat().st_mtime, reverse=True)

    if minirun_tag:
        manifests = [p for p in manifests if p.stem == minirun_tag]
        if not manifests:
            print(f"[WARN] minirun tag not found in manifests: {minirun_tag}")
            return []
    else:
        manifests = manifests[keep_latest:]

    plans: list[DeletePlan] = []
    seen: set[Path] = set()

    for manifest in manifests:
        try:
            tag, raw_paths = _parse_minirun_manifest(manifest)
        except Exception as e:
            print(f"[WARN] Failed to parse minirun manifest {manifest}: {e}")
            continue

        for raw in raw_paths:
            p = Path(raw).expanduser()
            if not p.is_absolute():
                p = (repo_root / p)
            try:
                safe_path = _ensure_under_root(p, repo_root, "minirun-artifact")
            except ValueError as e:
                print(f"[WARN] Skip unsafe path from manifest {manifest.name}: {raw} ({e})")
                continue

            key = safe_path.resolve()
            if key in seen:
                continue
            if not safe_path.exists() and not safe_path.is_symlink():
                continue
            seen.add(key)
            plans.append(
                DeletePlan(
                    path=safe_path,
                    reason=f"minirun artifact ({tag}) from manifest {manifest.name}",
                    size_bytes=_path_size(safe_path),
                )
            )

        manifest_key = manifest.resolve()
        if manifest_key not in seen:
            seen.add(manifest_key)
            plans.append(
                DeletePlan(
                    path=manifest,
                    reason=f"minirun manifest file ({manifest.name})",
                    size_bytes=_path_size(manifest),
                )
            )

    return plans


def _build_cleanup_plans(
    args: argparse.Namespace,
    repo_root: Path,
    results_dir: Path,
    log_dir: Path,
    factor_cache_dir: Path,
    minirun_manifest_dir: Path,
) -> list[DeletePlan]:
    plans: list[DeletePlan] = []

    if results_dir.exists():
        plans.extend(
            _collect_old_dirs(
                results_dir,
                "workspace_*",
                args.keep_workspace,
                reason="old workspace experiment directory",
            )
        )
        plans.extend(
            _collect_old_dirs(
                results_dir,
                "pickle_cache_*",
                args.keep_pickle,
                reason="old pickle cache directory",
            )
        )
    else:
        print(f"[INFO] results_dir does not exist, skip: {results_dir}")

    if args.clean_logs:
        if log_dir.exists():
            for p in _collect_timestamp_log_dirs(log_dir)[args.keep_logs:]:
                plans.append(
                    DeletePlan(
                        path=p,
                        reason="old timestamp log directory",
                        size_bytes=_path_size(p),
                    )
                )
        else:
            print(f"[INFO] log_dir does not exist, skip: {log_dir}")

    if args.clean_root_mlruns:
        root_mlruns = repo_root / "mlruns"
        if root_mlruns.exists():
            plans.append(
                DeletePlan(
                    path=root_mlruns,
                    reason="repo-level mlruns directory",
                    size_bytes=_path_size(root_mlruns),
                )
            )

    if args.prune_factor_cache:
        factor_cache_plans = _collect_orphan_factor_cache(
            repo_root=repo_root,
            factor_cache_dir=factor_cache_dir,
            factorlib_glob=args.factorlib_glob,
        )
        plans.extend(factor_cache_plans)

    if args.clean_minirun_temp:
        minirun_plans = _collect_minirun_artifacts_from_manifests(
            repo_root=repo_root,
            manifest_dir=minirun_manifest_dir,
            keep_latest=args.keep_minirun_manifests,
            minirun_tag=args.minirun_tag,
        )
        plans.extend(minirun_plans)

    # Deduplicate by canonical path (first reason wins).
    dedup: dict[Path, DeletePlan] = {}
    for plan in plans:
        key = plan.path.resolve()
        if key not in dedup:
            dedup[key] = plan

    plans = list(dedup.values())
    plans.sort(key=lambda x: x.size_bytes, reverse=True)
    return plans


def _prompt_yes_no(question: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{question} [{hint}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("请输入 y 或 n。")


def _prompt_int(question: str, default: int, minimum: int = 0) -> int:
    while True:
        raw = input(f"{question} [{default}]: ").strip()
        if not raw:
            return default
        if raw.isdigit():
            value = int(raw)
            if value >= minimum:
                return value
        print(f"请输入 >= {minimum} 的整数。")


def _recommendation_stats(
    repo_root: Path,
    results_dir: Path,
    log_dir: Path,
    factor_cache_dir: Path,
    minirun_manifest_dir: Path,
    factorlib_glob: str,
) -> dict[str, int]:
    ws_total = 0
    pk_total = 0
    ws_count = 0
    pk_count = 0
    ws_stale = 0
    pk_stale = 0
    log_stale = 0
    mlruns_total = _path_size(repo_root / "mlruns")
    factor_cache_total = _path_size(factor_cache_dir)
    orphan_total = 0
    minirun_temp_total = 0

    if results_dir.exists():
        ws_all = _sorted_dirs_by_mtime(results_dir, "workspace_*")
        pk_all = _sorted_dirs_by_mtime(results_dir, "pickle_cache_*")
        ws_count = len(ws_all)
        pk_count = len(pk_all)
        ws_total = sum(_path_size(p) for p in ws_all)
        pk_total = sum(_path_size(p) for p in pk_all)
        ws_stale = sum(_path_size(p) for p in ws_all[1:])
        pk_stale = sum(_path_size(p) for p in pk_all[1:])

    if log_dir.exists():
        log_stale = sum(_path_size(p) for p in _collect_timestamp_log_dirs(log_dir)[5:])

    try:
        orphan_plans = _collect_orphan_factor_cache(
            repo_root=repo_root,
            factor_cache_dir=factor_cache_dir,
            factorlib_glob=factorlib_glob,
            verbose=False,
        )
        orphan_total = sum(p.size_bytes for p in orphan_plans)
    except Exception:
        orphan_total = 0

    try:
        minirun_plans = _collect_minirun_artifacts_from_manifests(
            repo_root=repo_root,
            manifest_dir=minirun_manifest_dir,
            keep_latest=0,
            minirun_tag=None,
        )
        minirun_temp_total = sum(p.size_bytes for p in minirun_plans)
    except Exception:
        minirun_temp_total = 0

    return {
        "workspace_count": ws_count,
        "pickle_count": pk_count,
        "workspace_total": ws_total,
        "pickle_total": pk_total,
        "workspace_stale": ws_stale,
        "pickle_stale": pk_stale,
        "log_stale": log_stale,
        "mlruns_total": mlruns_total,
        "factor_cache_total": factor_cache_total,
        "orphan_factor_cache": orphan_total,
        "minirun_temp_total": minirun_temp_total,
    }


def _print_cn_guidance(stats: dict[str, int]) -> None:
    ws_count = stats["workspace_count"]
    pk_count = stats["pickle_count"]
    p1 = stats["workspace_stale"] + stats["pickle_stale"]
    p2 = stats["log_stale"]
    p3 = stats["mlruns_total"]
    p4 = stats["orphan_factor_cache"]
    p5 = stats["minirun_temp_total"]

    print("\n========== 清理建议（中文说明）==========")
    print("原因简述：")
    print("1) 你这条挖掘链路主要是 CPU + 磁盘 I/O；GPU 不是当前主瓶颈。")
    print("2) 空间最容易膨胀的是历史中间产物（workspace/pickle cache），可重建。")
    print("")
    print("推荐删除优先级（高 -> 低）：")
    print(
        f"1) 旧 workspace_* + 旧 pickle_cache_*（最优先，通常最安全）"
        f"  预计可回收约 {_human_size(p1)}"
    )
    print(
        f"2) 旧日志目录 log/<timestamp>（次优先）"
        f"  预计可回收约 {_human_size(p2)}"
    )
    print(
        f"3) 根目录 mlruns（按需）"
        f"  预计可回收约 {_human_size(p3)}"
    )
    print(
        f"4) factor_cache 孤儿文件（仅删未被 factorlib 引用的缓存）"
        f"  预计可回收约 {_human_size(p4)}"
    )
    print(
        f"5) minirun 临时产物（按 manifest 精确删除）"
        f"  预计可回收约 {_human_size(p5)}"
    )
    if p1 == 0 and ws_count <= 1 and pk_count <= 1:
        print("")
        print(
            f"提示：当前 workspace_*={ws_count}，pickle_cache_*={pk_count}。"
            "默认“保留最新1份”时没有可删历史目录，所以显示 0B。"
        )
        print("如果你现在必须马上腾空间，请使用“紧急腾空间”或自定义 keep=0。")
    print("")
    print("不建议直接删除：")
    print("- data/qlib/cn_data（基础行情特征数据）")
    print("- git_ignore_folder/*/daily_pv.h5（因子执行源数据）")
    print("- 整个 factor_cache（会导致大量因子重算）")
    print("========================================\n")


def _run_interactive_wizard(
    args: argparse.Namespace,
    repo_root: Path,
    results_dir: Path,
    log_dir: Path,
    factor_cache_dir: Path,
    minirun_manifest_dir: Path,
) -> argparse.Namespace:
    stats = _recommendation_stats(
        repo_root=repo_root,
        results_dir=results_dir,
        log_dir=log_dir,
        factor_cache_dir=factor_cache_dir,
        minirun_manifest_dir=minirun_manifest_dir,
        factorlib_glob=args.factorlib_glob,
    )
    _print_cn_guidance(stats)

    print("请选择清理方案：")
    print("1) 推荐（仅清理旧 workspace_*/pickle_cache_*，保留最新1份）")
    print("2) 推荐+日志（方案1 + 清理旧日志，默认保留最新5份）")
    print("3) 深度清理（方案2 + 清理根 mlruns + 清理 factor_cache 孤儿 + 清理 minirun 临时产物）")
    print("4) 自定义")
    print("5) 紧急腾空间（删除全部 workspace_* 和 pickle_cache_*，不保留）")
    choice = input("输入选项 [1]: ").strip() or "1"

    # Reset to safe baseline first.
    args.keep_workspace = 1
    args.keep_pickle = 1
    args.clean_logs = False
    args.keep_logs = 5
    args.clean_root_mlruns = False
    args.prune_factor_cache = False
    args.clean_minirun_temp = False
    args.keep_minirun_manifests = 0
    args.minirun_tag = None

    if choice == "2":
        args.clean_logs = True
    elif choice == "3":
        args.clean_logs = True
        args.clean_root_mlruns = True
        args.prune_factor_cache = True
        args.clean_minirun_temp = True
    elif choice == "5":
        args.keep_workspace = 0
        args.keep_pickle = 0
    elif choice == "4":
        print("\n进入自定义配置：")
        args.keep_workspace = _prompt_int("保留最新 workspace_* 数量", 1, minimum=0)
        args.keep_pickle = _prompt_int("保留最新 pickle_cache_* 数量", 1, minimum=0)
        args.clean_logs = _prompt_yes_no("是否清理旧日志目录", default=True)
        if args.clean_logs:
            args.keep_logs = _prompt_int("保留最新日志目录数量", 5, minimum=0)
        args.clean_root_mlruns = _prompt_yes_no("是否删除根目录 mlruns", default=False)
        args.prune_factor_cache = _prompt_yes_no(
            "是否清理 factor_cache 孤儿文件（仅未被 factorlib 引用）",
            default=False,
        )
        args.clean_minirun_temp = _prompt_yes_no(
            "是否清理 minirun 临时产物（按 manifest）",
            default=True,
        )
        if args.clean_minirun_temp:
            args.keep_minirun_manifests = _prompt_int("保留最新 minirun manifest 数量", 0, minimum=0)
    elif choice not in {"1", "2", "3", "4", "5"}:
        print("无效选项，按默认方案1处理。")

    print("\n已选择配置：")
    print(f"- keep_workspace={args.keep_workspace}")
    print(f"- keep_pickle={args.keep_pickle}")
    print(f"- clean_logs={args.clean_logs}, keep_logs={args.keep_logs}")
    print(f"- clean_root_mlruns={args.clean_root_mlruns}")
    print(f"- prune_factor_cache={args.prune_factor_cache}")
    print(f"- clean_minirun_temp={args.clean_minirun_temp}, keep_minirun_manifests={args.keep_minirun_manifests}")

    execute_now = _prompt_yes_no("\n是否立即执行删除（选择 n 则仅预览）", default=False)
    if execute_now:
        token = input("安全确认：请输入 DELETE 才会执行删除: ").strip()
        if token == "DELETE":
            args.apply = True
            args.yes = True
        else:
            print("未输入 DELETE，已切换为 dry-run 预览模式。")
            args.apply = False
            args.yes = False
    else:
        args.apply = False
        args.yes = False

    return args


def _print_plan(plans: list[DeletePlan]) -> None:
    if not plans:
        print("No files/directories selected for cleanup.")
        return

    total = sum(p.size_bytes for p in plans)
    print("Cleanup plan:")
    for p in plans:
        print(f"  - {_human_size(p.size_bytes):>8}  {p.reason}  ->  {p.path}")
    print(f"\nEstimated reclaimable space: {_human_size(total)}")


def _safe_delete(path: Path, repo_root: Path) -> None:
    resolved = path.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as e:
        raise ValueError(f"Refuse to delete path outside repo root: {resolved}") from e

    if resolved == repo_root:
        raise ValueError("Refuse to delete repo root")

    if not path.exists() and not path.is_symlink():
        return

    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return

    shutil.rmtree(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safe cleanup script (dry-run by default).",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Interactive wizard mode with Chinese guidance.",
    )
    parser.add_argument(
        "--results-dir",
        default=os.environ.get("DATA_RESULTS_DIR", "data/results"),
        help="Results directory (default: DATA_RESULTS_DIR or data/results).",
    )
    parser.add_argument(
        "--keep-workspace",
        type=int,
        default=1,
        help="Keep latest N workspace_* directories (default: 1).",
    )
    parser.add_argument(
        "--keep-pickle",
        type=int,
        default=1,
        help="Keep latest N pickle_cache_* directories (default: 1).",
    )
    parser.add_argument(
        "--clean-logs",
        action="store_true",
        help="Also clean timestamp log directories under log/ (off by default).",
    )
    parser.add_argument(
        "--log-dir",
        default="log",
        help="Log root directory (default: log).",
    )
    parser.add_argument(
        "--keep-logs",
        type=int,
        default=5,
        help="Keep latest N timestamp log dirs when --clean-logs is enabled (default: 5).",
    )
    parser.add_argument(
        "--clean-root-mlruns",
        action="store_true",
        help="Also delete repo-level mlruns directory (off by default).",
    )
    parser.add_argument(
        "--prune-factor-cache",
        action="store_true",
        help="Delete factor_cache *.pkl/*.parquet not referenced by factorlib JSONs (off by default).",
    )
    parser.add_argument(
        "--factor-cache-dir",
        default="data/results/factor_cache",
        help="Factor cache directory (default: data/results/factor_cache).",
    )
    parser.add_argument(
        "--factorlib-glob",
        default="data/factorlib/*.json",
        help="Glob for factor library JSONs when pruning factor cache (default: data/factorlib/*.json).",
    )
    parser.add_argument(
        "--clean-minirun-temp",
        action="store_true",
        help="Delete minirun temporary artifacts referenced by manifest files (off by default).",
    )
    parser.add_argument(
        "--minirun-manifest-dir",
        default="log/minirun_manifests",
        help="Directory containing minirun manifests (default: log/minirun_manifests).",
    )
    parser.add_argument(
        "--keep-minirun-manifests",
        type=int,
        default=0,
        help="Keep latest N minirun manifests when --clean-minirun-temp is enabled (default: 0).",
    )
    parser.add_argument(
        "--minirun-tag",
        default=None,
        help="If set, clean only this minirun tag (exact manifest filename stem).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete selected paths. Without this flag, only preview plan.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required together with --apply as a safety confirmation.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    no_args = len(sys.argv) == 1
    if no_args and sys.stdin.isatty():
        args.interactive = True

    if args.keep_workspace < 0 or args.keep_pickle < 0 or args.keep_logs < 0 or args.keep_minirun_manifests < 0:
        print("[ERROR] --keep-workspace/--keep-pickle/--keep-logs/--keep-minirun-manifests must be >= 0")
        return 2

    try:
        results_dir = _ensure_under_root(Path(args.results_dir), repo_root, "results-dir")
        log_dir = _ensure_under_root(Path(args.log_dir), repo_root, "log-dir")
        factor_cache_dir = _ensure_under_root(Path(args.factor_cache_dir), repo_root, "factor-cache-dir")
        minirun_manifest_dir = _ensure_under_root(
            Path(args.minirun_manifest_dir), repo_root, "minirun-manifest-dir"
        )
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 2

    if args.interactive:
        if not sys.stdin.isatty():
            print("[ERROR] Interactive mode requires a TTY terminal.")
            return 2
        args = _run_interactive_wizard(
            args, repo_root, results_dir, log_dir, factor_cache_dir, minirun_manifest_dir
        )

    if args.keep_workspace < 0 or args.keep_pickle < 0 or args.keep_logs < 0 or args.keep_minirun_manifests < 0:
        print("[ERROR] --keep-workspace/--keep-pickle/--keep-logs/--keep-minirun-manifests must be >= 0")
        return 2

    if args.minirun_tag and not args.clean_minirun_temp:
        print("[WARN] --minirun-tag is ignored unless --clean-minirun-temp is enabled.")

    try:
        plans = _build_cleanup_plans(
            args, repo_root, results_dir, log_dir, factor_cache_dir, minirun_manifest_dir
        )
    except ValueError as e:
        print(f"[ERROR] {e}")
        return 2

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"Repo root : {repo_root}")
    print(f"Mode      : {mode}")
    print(f"Results   : {results_dir}")
    print("")
    _print_plan(plans)

    if not args.apply:
        print("\nDry-run only. Use --apply --yes to execute deletion.")
        return 0

    if not args.yes:
        print("[ERROR] --apply requires --yes for safety confirmation.")
        return 2

    deleted = 0
    failed = 0
    for plan in plans:
        try:
            _safe_delete(plan.path, repo_root=repo_root)
            deleted += 1
        except Exception as e:
            failed += 1
            print(f"[ERROR] Failed to delete {plan.path}: {e}")

    print(f"\nDone. deleted={deleted}, failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
