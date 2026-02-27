import re
from typing import Tuple

_PARSER_ARITH_FUNC_RE = re.compile(r"\b(ADD|SUBTRACT|MULTIPLY|DIVIDE)\s*\(", re.IGNORECASE)
_DOLLAR_VAR_RE = re.compile(r"\$([A-Za-z_]\w*)")
_BARE_BASE_VAR_RE = re.compile(r"(?<!\$)\b(open|close|high|low|volume|return)\b", re.IGNORECASE)


def validate_expression_style(expression: str) -> Tuple[bool, str]:
    """
    Validate expression style constraints used by proposal/construct stage.

    Rules:
    1) Reject parser-style arithmetic function forms: ADD/SUBTRACT/MULTIPLY/DIVIDE.
    2) Enforce $-prefixed base variables in expressions.
    """
    if not isinstance(expression, str) or not expression.strip():
        return False, "Expression is empty or non-string."

    expression = expression.strip()

    parser_funcs = sorted({m.group(1).upper() for m in _PARSER_ARITH_FUNC_RE.finditer(expression)})
    if parser_funcs:
        return (
            False,
            "Disallowed parser-style arithmetic function forms found: "
            + ", ".join(parser_funcs)
            + ". Use operators '+', '-', '*', '/' directly.",
        )

    bare_vars = sorted({m.group(1).lower() for m in _BARE_BASE_VAR_RE.finditer(expression)})
    if bare_vars:
        dollar_vars = {m.group(1).lower() for m in _DOLLAR_VAR_RE.finditer(expression)}
        mixed = sorted(set(bare_vars) & dollar_vars)
        if mixed:
            return (
                False,
                "Mixed variable naming detected for base fields: "
                + ", ".join(mixed)
                + ". Do not mix '$var' and 'var' in one expression.",
            )
        return (
            False,
            "Non-prefixed base variables detected: "
            + ", ".join(bare_vars)
            + ". Use '$open/$close/$high/$low/$volume/$return' consistently.",
        )

    return True, ""
