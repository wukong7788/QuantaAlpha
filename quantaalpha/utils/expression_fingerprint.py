from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal, Optional


DedupMethod = Literal["norm", "ast"]


def normalize_expression(expr: str) -> str:
    """
    Whitespace-only normalization for expression-level dedup.

    Notes:
    - We intentionally avoid aggressive rewriting (e.g., commutative sorting) here.
    - Use `ast_canonical_expression()` for AST-based canonicalization.
    """
    return re.sub(r"\s+", " ", str(expr or "").strip())


def expression_fingerprint(expr: str, method: DedupMethod) -> str:
    if method == "norm":
        return normalize_expression(expr)
    if method == "ast":
        return ast_canonical_expression(expr)
    raise ValueError(f"Unknown dedup method: {method}")


def expression_fingerprint_md5(expr: str, method: DedupMethod) -> str:
    s = expression_fingerprint(expr, method)
    return hashlib.md5(s.encode()).hexdigest()


@dataclass(frozen=True)
class AstCanonicalizeResult:
    ok: bool
    canonical: str
    error: Optional[str] = None


def try_ast_canonical_expression(expr: str) -> AstCanonicalizeResult:
    try:
        return AstCanonicalizeResult(ok=True, canonical=ast_canonical_expression(expr))
    except Exception as e:
        return AstCanonicalizeResult(ok=False, canonical=normalize_expression(expr), error=str(e))


def ast_canonical_expression(expr: str) -> str:
    """
    Canonicalize an expression by parsing it into AST and applying:
    - commutative operand sorting for +, *, ==, !=, &, &&, |, ||
    - associative flattening + sorting for +, *, &, &&, |, ||
    The output is a valid expression string (operator form).
    """
    from quantaalpha.factors.coder.factor_ast import (  # type: ignore
        BinaryOpNode,
        ConditionalNode,
        FunctionNode,
        NumberNode,
        UnaryOpNode,
        VarNode,
        parse_expression,
    )

    tree = parse_expression(str(expr or "").strip())

    commutative_ops = {"+", "*", "==", "!=", "&", "&&", "|", "||"}
    associative_ops = {"+", "*", "&", "&&", "|", "||"}

    def _fmt_num(v: float) -> str:
        # Use repr for stable round-trip-ish formatting (e.g. 1e-08).
        return repr(float(v))

    def _flatten(node, op: str):
        if isinstance(node, BinaryOpNode) and node.op == op:
            yield from _flatten(node.left, op)
            yield from _flatten(node.right, op)
        else:
            yield node

    def _canon(node) -> str:
        if isinstance(node, VarNode):
            return str(node.name)
        if isinstance(node, NumberNode):
            return _fmt_num(node.value)
        if isinstance(node, UnaryOpNode):
            return f"({node.op}{_canon(node.operand)})"
        if isinstance(node, FunctionNode):
            args = ", ".join(_canon(a) for a in node.args)
            return f"{node.name}({args})"
        if isinstance(node, ConditionalNode):
            return f"({_canon(node.condition)} ? {_canon(node.true_expr)} : {_canon(node.false_expr)})"
        if isinstance(node, BinaryOpNode):
            op = str(node.op)
            if op in associative_ops:
                parts = [_canon(n) for n in _flatten(node, op)]
                if op in commutative_ops:
                    parts.sort()
                return "(" + f" {op} ".join(parts) + ")"

            left = _canon(node.left)
            right = _canon(node.right)
            if op in commutative_ops:
                a, b = sorted([left, right])
                return f"({a} {op} {b})"
            return f"({left} {op} {right})"

        # Fallback: best-effort string
        return str(node)

    return _canon(tree)

