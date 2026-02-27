from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[2] / "quantaalpha" / "factors" / "regulator" / "expression_style.py"
_SPEC = spec_from_file_location("expression_style", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
validate_expression_style = _MODULE.validate_expression_style


def test_rejects_parser_arithmetic_function_forms():
    ok, feedback = validate_expression_style(
        "RANK(DIVIDE(TS_SUM($return, 10), TS_STD($return, 10) + 1e-8))"
    )
    assert ok is False
    assert "parser-style arithmetic function forms" in feedback


def test_rejects_mixed_or_nonprefixed_base_variables():
    ok, feedback = validate_expression_style(
        "RANK(TS_MEAN($return, 5) / (TS_STD(return, 5) + 1e-8))"
    )
    assert ok is False
    assert "Do not mix '$var' and 'var'" in feedback


def test_accepts_canonical_operator_form_with_prefixed_variables():
    ok, feedback = validate_expression_style(
        "RANK((TS_MEAN($return, 5) - TS_MEDIAN($return, 5)) / (TS_STD($return, 5) + 1e-8))"
    )
    assert ok is True
    assert feedback == ""
