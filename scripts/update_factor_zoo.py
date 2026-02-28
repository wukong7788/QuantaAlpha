#!/usr/bin/env python3
"""
update_factor_zoo.py

将一次实验产出的新因子表达式追加到 factor_zoo（去重过滤库），
下一轮实验启动时自动跳过已见表达式，节省 calculate/backtest 资源。

常态化用法（每次实验结束后调用）：
  ./scripts/update_factor_zoo.py

或通过 run.sh --zoo-dedup 自动触发。

工作逻辑：
  1. 读取当前 factor_zoo（若不存在则从零创建）
  2. 扫描所有 data/factorlib/*.json，提取新增表达式（排除 zoo 中已有）
  3. 将新增因子追加到 zoo，更新元数据

可选子命令：
  build   - 全量重建（从所有 factorlib 重新构建 zoo，不回测，仅整合表达式）
  update  - 增量追加最新轮次的因子到 zoo（默认）
  status  - 打印当前 zoo 的统计信息

用法：
  .venv/bin/python scripts/update_factor_zoo.py           # 等同 update
  .venv/bin/python scripts/update_factor_zoo.py update
  .venv/bin/python scripts/update_factor_zoo.py build
  .venv/bin/python scripts/update_factor_zoo.py status
  .venv/bin/python scripts/update_factor_zoo.py update --lib SUFFIX  # 指定本次实验的库后缀
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)

ZOO_PATH     = PROJECT_ROOT / "data/factorlib/factor_zoo.json"
ZOO_CSV_PATH = PROJECT_ROOT / "data/factorlib/factor_zoo.csv"   # ← factor_regulator reads this
FACTORLIB_DIR = PROJECT_ROOT / "data/factorlib"

# 不归入 zoo 的文件（临时文件、zoo 本身等）
EXCLUDE_PATTERNS = {"factor_zoo", "_pending", "tmp_", ".bak"}


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _normalize(expr: str) -> str:
    return re.sub(r"\s+", " ", str(expr or "").strip())


def _factor_id(expr: str) -> str:
    return "zoo_" + hashlib.md5(_normalize(expr).encode()).hexdigest()[:12]


def _load_lib(path: Path) -> dict:
    """返回 {factor_id: factor_dict}，兼容 dict/list 两种格式。"""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print(f"  [warn] 无法读取 {path.name}: {e}")
        return {}
    if isinstance(d, dict):
        factors = d.get("factors", {})
        if isinstance(factors, dict):
            return factors
        if isinstance(factors, list):
            return {fac.get("factor_id", str(i)): fac for i, fac in enumerate(factors)}
    if isinstance(d, list):
        return {fac.get("factor_id", str(i)): fac for i, fac in enumerate(d)}
    return {}


def _load_zoo() -> dict:
    """读取已有 zoo，若不存在返回空 dict。"""
    if not ZOO_PATH.exists():
        return {}
    return _load_lib(ZOO_PATH)


def _save_zoo(factors: dict, source_libs: list[str]) -> None:
    # 1) JSON — full metadata (for inspection / merge)
    payload = {
        "metadata": {
            "description": (
                "Factor Zoo: 跨轮次去重过滤库。"
                "作为 factor.duplication.factor_zoo_path 使用，"
                "新因子在进入 calculate/backtest 前会与此库进行表达式去重。"
            ),
            "total_count": len(factors),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source_libs": source_libs,
        },
        "factors": factors,
    }
    ZOO_PATH.parent.mkdir(parents=True, exist_ok=True)
    ZOO_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2) CSV — 供 FactorRegulator / factor_regulator.py 使用 (pd.read_csv)
    import csv
    ZOO_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ZOO_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["factor_name", "factor_expression"])
        for fac in factors.values():
            writer.writerow([
                fac.get("factor_name", ""),
                fac.get("factor_expression", ""),
            ])


def _find_factorlib_files(lib_suffix: str | None = None) -> list[Path]:
    """返回 data/factorlib/ 下的所有因子库文件（排除 zoo 本身和临时文件）。"""
    all_files = sorted(FACTORLIB_DIR.glob("all_factors_library*.json"))
    result = []
    for p in all_files:
        name = p.name
        if any(pat in name for pat in EXCLUDE_PATTERNS):
            continue
        if lib_suffix and f"_{lib_suffix}" not in name:
            # 如果指定了 suffix，优先放在前面（但仍保留其他）
            pass
        result.append(p)

    # 若指定 suffix，把对应文件排到最前（最新产出优先）
    if lib_suffix:
        target = [p for p in result if f"_{lib_suffix}" in p.name]
        others  = [p for p in result if f"_{lib_suffix}" not in p.name]
        result = target + others

    return result


# ─── 子命令：status ────────────────────────────────────────────────────────────

def cmd_status() -> int:
    zoo = _load_zoo()
    if not zoo:
        print(f"[status] Zoo 不存在或为空: {ZOO_PATH}")
    else:
        print(f"[status] Zoo JSON: {ZOO_PATH}")
        print(f"[status] Zoo CSV:  {ZOO_CSV_PATH}")
        print(f"[status] 因子总数: {len(zoo)}")
        try:
            with open(ZOO_PATH, encoding="utf-8") as f:
                d = json.load(f)
            meta = d.get("metadata", {})
            print(f"[status] 更新时间: {meta.get('updated_at', 'unknown')}")
            for lib in meta.get("source_libs", []):
                print(f"  - {lib}")
        except Exception:
            pass
    libs = _find_factorlib_files()
    print(f"\n[status] 当前 factorlib 文件数: {len(libs)}")
    total_in_libs = 0
    for p in libs:
        facs = _load_lib(p)
        print(f"  {p.name}: {len(facs)} 因子")
        total_in_libs += len(facs)
    print(f"  合计: {total_in_libs} 因子（含重复）")
    return 0


# ─── 子命令：update（增量追加）────────────────────────────────────────────────

def cmd_update(lib_suffix: str | None = None) -> int:
    zoo = _load_zoo()
    zoo_exprs: dict[str, str] = {}  # normalized_expr -> factor_id
    for fid, fac in zoo.items():
        norm = _normalize(fac.get("factor_expression", ""))
        if norm:
            zoo_exprs[norm] = fid

    before = len(zoo)
    print(f"[update] Zoo 现有: {before} 因子")

    libs = _find_factorlib_files(lib_suffix)
    added = 0
    source_libs = []
    for lib_path in libs:
        facs = _load_lib(lib_path)
        if not facs:
            continue
        new_in_lib = 0
        for fid, fac in facs.items():
            norm = _normalize(fac.get("factor_expression", ""))
            if not norm or norm in zoo_exprs:
                continue
            zoo_id = _factor_id(norm)
            zoo[zoo_id] = {
                "factor_id": zoo_id,
                "factor_name": fac.get("factor_name", zoo_id),
                "factor_expression": fac.get("factor_expression", norm),
                "factor_description": fac.get("factor_description", ""),
                "source_lib": lib_path.name,
                "added_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                # 仅保留回测指标（不含大字段），节省体积
                "backtest_metrics": _extract_metrics(fac),
            }
            zoo_exprs[norm] = zoo_id
            new_in_lib += 1
            added += 1
        if new_in_lib > 0:
            source_libs.append(lib_path.name)
            print(f"  {lib_path.name}: +{new_in_lib} 新因子")

    after = len(zoo)
    print(f"[update] 新增: {added}，Zoo 总计: {after} 因子")
    _save_zoo(zoo, source_libs)
    print(f"[update] ✅ JSON: {ZOO_PATH}")
    print(f"[update] ✅ CSV:  {ZOO_CSV_PATH}")
    print(f"[update] 设置环境变量（在 run.sh 或 .env 中）:")
    print(f"  export FACTOR_CoSTEER_FACTOR_ZOO_PATH={ZOO_CSV_PATH}")
    return 0


def _extract_metrics(fac: dict) -> dict:
    """从 factor_dict 中提取回测指标（轻量存储）。"""
    br = fac.get("backtest_results", {}) or {}
    if not isinstance(br, dict):
        return {}
    inner = br.get("custom", br)
    keys = ["RankIC", "RankICIR", "IC", "annualized_return", "information_ratio", "max_drawdown"]
    return {k: inner.get(k) for k in keys if inner.get(k) is not None}


# ─── 子命令：build（全量重建）────────────────────────────────────────────────

def cmd_build() -> int:
    """从所有 factorlib 全量重建 zoo（不保留旧 zoo 内容）。"""
    print(f"[build] 全量重建 {ZOO_PATH.name} ...")
    zoo: dict = {}
    zoo_exprs: dict[str, str] = {}
    libs = _find_factorlib_files()
    source_libs = []
    for lib_path in libs:
        facs = _load_lib(lib_path)
        if not facs:
            continue
        added = 0
        for fid, fac in facs.items():
            norm = _normalize(fac.get("factor_expression", ""))
            if not norm or norm in zoo_exprs:
                continue
            zoo_id = _factor_id(norm)
            zoo[zoo_id] = {
                "factor_id": zoo_id,
                "factor_name": fac.get("factor_name", zoo_id),
                "factor_expression": fac.get("factor_expression", norm),
                "factor_description": fac.get("factor_description", ""),
                "source_lib": lib_path.name,
                "added_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "backtest_metrics": _extract_metrics(fac),
            }
            zoo_exprs[norm] = zoo_id
            added += 1
        if added > 0:
            source_libs.append(lib_path.name)
        print(f"  {lib_path.name}: {len(facs)} 因子, 新增到 zoo {added}")
    _save_zoo(zoo, source_libs)
    print(f"[build] ✅ Zoo 共 {len(zoo)} 个唯一因子")
    print(f"  JSON: {ZOO_PATH}")
    print(f"  CSV:  {ZOO_CSV_PATH}")
    print(f"[build] 设置环境变量（在 run.sh 或 .env 中）:")
    print(f"  export FACTOR_CoSTEER_FACTOR_ZOO_PATH={ZOO_CSV_PATH}")
    return 0


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(
        description="Update factor zoo with new factors from completed experiments."
    )
    p.add_argument("command", nargs="?", default="update",
                   choices=["update", "build", "status"],
                   help="update=增量追加（默认）; build=全量重建; status=查看统计")
    p.add_argument("--lib", default="", help="指定本次实验的 FACTOR_LIBRARY_SUFFIX，优先处理对应库")
    args = p.parse_args()

    cmds = {"update": cmd_update, "build": cmd_build, "status": cmd_status}
    fn = cmds[args.command]
    if args.command == "update":
        return fn(lib_suffix=args.lib or None)
    else:
        return fn()


if __name__ == "__main__":
    raise SystemExit(main())
