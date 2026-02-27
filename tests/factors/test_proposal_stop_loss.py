from types import SimpleNamespace

import pytest

from quantaalpha.core.exception import FactorEmptyError
from quantaalpha.core.proposal import Hypothesis, Trace
from quantaalpha.factors import proposal as proposal_module


class _DummyScenario:
    background = "dummy_background"

    def get_scenario_all_desc(self):
        return "dummy_scenario"


def _make_converter(max_construct_failures: int, max_json_failures: int):
    converter = proposal_module.AlphaAgentHypothesis2FactorExpression.__new__(
        proposal_module.AlphaAgentHypothesis2FactorExpression
    )
    converter.targets = "factors"
    converter.consistency_enabled = False
    converter._quality_gate = None
    converter.max_construct_failures_per_branch = max_construct_failures
    converter.max_json_parse_failures_per_branch = max_json_failures
    converter.factor_regulator = SimpleNamespace(
        validate_expression_style=lambda expr: (True, ""),
        is_parsable=lambda expr: True,
        evaluate=lambda expr: (True, {"expr": expr}),
        is_expression_acceptable=lambda eval_dict: True,
        add_factor=lambda names, exprs: None,
    )
    converter.prepare_context = lambda hypothesis, trace, history_limit: (  # noqa: ARG005
        {
            "target_hypothesis": str(hypothesis),
            "hypothesis_and_feedback": "none",
            "function_lib_description": "lib",
            "target_list": [],
            "RAG": None,
            "experiment_output_format": "{}",
        },
        True,
    )
    converter.convert_response = lambda response, trace: response  # noqa: ARG005
    return converter


def test_convert_stops_after_json_parse_budget(monkeypatch: pytest.MonkeyPatch):
    converter = _make_converter(max_construct_failures=3, max_json_failures=2)
    hypothesis = Hypothesis("h", "", "", "", "", "")
    trace = Trace(scen=_DummyScenario())
    calls = {"count": 0}

    class FakeAPIBackend:
        def build_messages_and_create_chat_completion(self, *args, **kwargs):  # noqa: ARG002
            calls["count"] += 1
            return ""

    monkeypatch.setattr(proposal_module, "APIBackend", FakeAPIBackend)

    with pytest.raises(FactorEmptyError, match="JSON parse failure budget exceeded"):
        converter._convert_with_history_limit(hypothesis, trace, history_limit=1)

    assert calls["count"] == 2


def test_convert_stops_after_construct_failure_budget(monkeypatch: pytest.MonkeyPatch):
    converter = _make_converter(max_construct_failures=2, max_json_failures=3)
    hypothesis = Hypothesis("h", "", "", "", "", "")
    trace = Trace(scen=_DummyScenario())
    calls = {"count": 0}

    class FakeAPIBackend:
        def build_messages_and_create_chat_completion(self, *args, **kwargs):  # noqa: ARG002
            calls["count"] += 1
            return "{}"

    monkeypatch.setattr(proposal_module, "APIBackend", FakeAPIBackend)

    with pytest.raises(FactorEmptyError, match="construct failure budget exceeded"):
        converter._convert_with_history_limit(hypothesis, trace, history_limit=1)

    assert calls["count"] == 2
