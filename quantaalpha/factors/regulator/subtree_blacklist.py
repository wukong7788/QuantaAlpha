from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quantaalpha.log import logger


def _count_all_nodes(expr: str) -> int:
    from quantaalpha.factors.coder.factor_ast import count_all_nodes

    return int(count_all_nodes(expr))


def _compare_expressions(expr1: str, expr2: str):
    from quantaalpha.factors.coder.factor_ast import compare_expressions

    return compare_expressions(expr1, expr2)


@dataclass(frozen=True)
class SubtreePattern:
    expression: str
    node_count: int
    label: str = ""


@dataclass(frozen=True)
class SubtreeMatch:
    pattern_expression: str
    pattern_label: str
    matched_size: int
    pattern_node_count: int


class SubtreeBlacklist:
    """
    Match candidate expressions against a curated list of bad subtrees.

    The JSON input can be:
    1) a list of expression strings
    2) a dict with "patterns" field:
       - list[str]
       - list[{"expr": "...", "label": "..."}]
    """

    def __init__(
        self,
        path: str,
        *,
        max_patterns: int = 200,
        min_nodes: int = 1,
    ) -> None:
        self.path = str(path)
        self.max_patterns = max(1, int(max_patterns))
        self.min_nodes = max(1, int(min_nodes))
        self._patterns = self._load_patterns()

    @property
    def size(self) -> int:
        return len(self._patterns)

    def _load_patterns(self) -> list[SubtreePattern]:
        src_path = Path(self.path)
        if not src_path.exists():
            logger.warning(f"Subtree blacklist file not found: {src_path}")
            return []

        try:
            payload = json.loads(src_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Failed to read subtree blacklist file {src_path}: {exc}")
            return []

        raw_items: list[Any]
        if isinstance(payload, list):
            raw_items = payload
        elif isinstance(payload, dict):
            raw_patterns = payload.get("patterns", [])
            raw_items = raw_patterns if isinstance(raw_patterns, list) else []
        else:
            raw_items = []

        loaded: list[SubtreePattern] = []
        seen: set[str] = set()
        for item in raw_items:
            expr = ""
            label = ""
            if isinstance(item, str):
                expr = item
            elif isinstance(item, dict):
                expr = str(item.get("expr", item.get("expression", "")) or "")
                label = str(item.get("label", "") or "")
            expr = " ".join(expr.strip().split())
            if not expr or expr in seen:
                continue
            try:
                node_count = _count_all_nodes(expr)
            except Exception:
                continue
            if node_count < self.min_nodes:
                continue
            seen.add(expr)
            loaded.append(SubtreePattern(expression=expr, node_count=node_count, label=label))

        loaded.sort(key=lambda p: p.node_count, reverse=True)
        if len(loaded) > self.max_patterns:
            loaded = loaded[: self.max_patterns]

        logger.info(
            f"Loaded subtree blacklist: {len(loaded)} patterns from {src_path} "
            f"(min_nodes={self.min_nodes}, max_patterns={self.max_patterns})"
        )
        return loaded

    def match(self, expression: str) -> SubtreeMatch | None:
        expr = str(expression or "").strip()
        if not expr or not self._patterns:
            return None

        for pattern in self._patterns:
            try:
                lcs = _compare_expressions(expr, pattern.expression)
            except Exception:
                continue
            if lcs is None:
                continue
            if int(lcs.size) >= int(pattern.node_count):
                return SubtreeMatch(
                    pattern_expression=pattern.expression,
                    pattern_label=pattern.label,
                    matched_size=int(lcs.size),
                    pattern_node_count=int(pattern.node_count),
                )
        return None
