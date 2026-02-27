from types import SimpleNamespace

import pytest

from quantaalpha.core.exception import FactorEmptyError
from quantaalpha.pipeline.loop import AlphaAgentLoop


class _PassRegulator:
    def validate_expression_style(self, expr: str):  # noqa: ARG002
        return True, ""

    def is_parsable(self, expr: str):  # noqa: ARG002
        return True

    def evaluate(self, expr: str):  # noqa: ARG002
        return True, {"ok": True}

    def is_expression_acceptable(self, eval_dict: dict):  # noqa: ARG002
        return True


def _make_loop() -> AlphaAgentLoop:
    loop = AlphaAgentLoop.__new__(AlphaAgentLoop)
    loop.cheap_filter_enabled = True
    loop.cheap_filter_require_acceptable = True
    loop.factor_constructor = SimpleNamespace(factor_regulator=_PassRegulator())
    loop._last_skip_reason = None
    loop._seen_expressions_cache = None
    return loop


def test_exact_duplicate_filter_removes_seen_and_in_batch_duplicates(monkeypatch: pytest.MonkeyPatch):
    loop = _make_loop()
    monkeypatch.setattr(loop, "_load_seen_expressions", lambda: {"RANK($close)"})

    experiment = SimpleNamespace(
        sub_tasks=[
            SimpleNamespace(factor_name="seen", factor_expression="RANK($close)"),
            SimpleNamespace(factor_name="new1", factor_expression="TS_MEAN($close, 5)"),
            SimpleNamespace(factor_name="dup_in_batch", factor_expression="TS_MEAN($close, 5)"),
        ]
    )

    filtered = loop._apply_precalc_quality_gate(experiment)
    kept = [task.factor_name for task in filtered.sub_tasks]
    assert kept == ["new1"]
    assert loop._last_skip_reason is None


def test_exact_duplicate_filter_sets_skip_reason_when_all_removed(monkeypatch: pytest.MonkeyPatch):
    loop = _make_loop()
    monkeypatch.setattr(loop, "_load_seen_expressions", lambda: {"RANK($close)"})

    experiment = SimpleNamespace(
        sub_tasks=[
            SimpleNamespace(factor_name="seen1", factor_expression="RANK($close)"),
            SimpleNamespace(factor_name="seen2", factor_expression="RANK($close)"),
        ]
    )

    with pytest.raises(FactorEmptyError, match="duplicate_exact"):
        loop._apply_precalc_quality_gate(experiment)

    assert loop._last_skip_reason == "duplicate_exact"


def test_factor_construct_invalidates_seen_expression_cache(monkeypatch: pytest.MonkeyPatch):
    loop = AlphaAgentLoop.__new__(AlphaAgentLoop)
    loop._seen_expressions_cache = {"RANK($close)"}
    loop._last_skip_reason = "duplicate_exact"
    loop.trace = SimpleNamespace()
    loop.factor_constructor = SimpleNamespace(
        convert=lambda hypothesis, trace: SimpleNamespace(sub_tasks=[]),  # noqa: ARG005
    )
    monkeypatch.setattr("quantaalpha.pipeline.loop.STOP_EVENT", None)

    loop.factor_construct({"factor_propose": "dummy"})

    assert loop._seen_expressions_cache is None
    assert loop._last_skip_reason is None
