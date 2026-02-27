from types import SimpleNamespace

import pytest

from quantaalpha.core.exception import FactorEmptyError
from quantaalpha.pipeline.loop import AlphaAgentLoop


class _FakeRegulator:
    def validate_expression_style(self, expr: str):
        if expr == "bad_style":
            return False, "style_error"
        return True, ""

    def is_parsable(self, expr: str) -> bool:
        return expr != "bad_parse"

    def evaluate(self, expr: str):
        if expr == "bad_eval":
            return False, {}
        return True, {"expr": expr}

    def is_expression_acceptable(self, eval_dict: dict) -> bool:
        return eval_dict.get("expr") != "bad_quality"


def _make_loop() -> AlphaAgentLoop:
    loop = AlphaAgentLoop.__new__(AlphaAgentLoop)
    loop.cheap_filter_enabled = True
    loop.cheap_filter_require_acceptable = True
    loop.factor_constructor = SimpleNamespace(factor_regulator=_FakeRegulator())
    loop._last_skip_reason = None
    return loop


def test_precalc_quality_gate_keeps_only_valid_tasks():
    loop = _make_loop()
    experiment = SimpleNamespace(
        sub_tasks=[
            SimpleNamespace(factor_name="f_bad_style", factor_expression="bad_style"),
            SimpleNamespace(factor_name="f_bad_parse", factor_expression="bad_parse"),
            SimpleNamespace(factor_name="f_bad_eval", factor_expression="bad_eval"),
            SimpleNamespace(factor_name="f_bad_quality", factor_expression="bad_quality"),
            SimpleNamespace(factor_name="f_ok", factor_expression="$close"),
        ]
    )

    filtered = loop._apply_precalc_quality_gate(experiment)
    kept_names = [task.factor_name for task in filtered.sub_tasks]

    assert kept_names == ["f_ok"]
    assert loop._last_skip_reason is None


def test_precalc_quality_gate_raises_when_all_filtered_out():
    loop = _make_loop()
    experiment = SimpleNamespace(
        sub_tasks=[
            SimpleNamespace(factor_name="f1", factor_expression="bad_style"),
            SimpleNamespace(factor_name="f2", factor_expression="bad_parse"),
        ]
    )

    with pytest.raises(FactorEmptyError, match="removed all candidate factors"):
        loop._apply_precalc_quality_gate(experiment)

    assert loop._last_skip_reason == "cheap_filter_no_valid_factors"
