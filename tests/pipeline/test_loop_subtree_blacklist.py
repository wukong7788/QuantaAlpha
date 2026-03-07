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


class _FakeSubtreeBlacklist:
    def match(self, expr: str):
        if expr == "blocked_expr":
            return SimpleNamespace(
                pattern_expression="delay($close, 1)",
                pattern_label="bad_delay",
                matched_size=3,
                pattern_node_count=3,
            )
        return None


def _make_loop() -> AlphaAgentLoop:
    loop = AlphaAgentLoop.__new__(AlphaAgentLoop)
    loop.cheap_filter_enabled = True
    loop.cheap_filter_require_acceptable = False
    loop.factor_constructor = SimpleNamespace(factor_regulator=_PassRegulator())
    loop.subtree_blacklist = _FakeSubtreeBlacklist()
    loop._last_skip_reason = None
    return loop


def test_subtree_blacklist_works_without_cheap_filter(monkeypatch: pytest.MonkeyPatch):
    loop = _make_loop()
    loop.cheap_filter_enabled = False
    monkeypatch.setattr(loop, "_load_seen_expressions", lambda: set())
    experiment = SimpleNamespace(
        sub_tasks=[
            SimpleNamespace(factor_name="blocked", factor_expression="blocked_expr"),
            SimpleNamespace(factor_name="kept", factor_expression="TS_MEAN($close, 5)"),
        ]
    )

    filtered = loop._apply_precalc_quality_gate(experiment)
    kept = [task.factor_name for task in filtered.sub_tasks]
    assert kept == ["kept"]


def test_subtree_blacklist_filters_matching_factors(monkeypatch: pytest.MonkeyPatch):
    loop = _make_loop()
    monkeypatch.setattr(loop, "_load_seen_expressions", lambda: set())
    experiment = SimpleNamespace(
        sub_tasks=[
            SimpleNamespace(factor_name="blocked", factor_expression="blocked_expr"),
            SimpleNamespace(factor_name="kept", factor_expression="TS_MEAN($close, 5)"),
        ]
    )

    filtered = loop._apply_precalc_quality_gate(experiment)
    kept = [task.factor_name for task in filtered.sub_tasks]

    assert kept == ["kept"]
    assert loop._last_skip_reason is None


def test_subtree_blacklist_sets_skip_reason_when_all_removed(monkeypatch: pytest.MonkeyPatch):
    loop = _make_loop()
    monkeypatch.setattr(loop, "_load_seen_expressions", lambda: set())
    experiment = SimpleNamespace(
        sub_tasks=[
            SimpleNamespace(factor_name="blocked_1", factor_expression="blocked_expr"),
            SimpleNamespace(factor_name="blocked_2", factor_expression="blocked_expr"),
        ]
    )

    with pytest.raises(FactorEmptyError, match="subtree_blacklist"):
        loop._apply_precalc_quality_gate(experiment)

    assert loop._last_skip_reason == "subtree_blacklist"
