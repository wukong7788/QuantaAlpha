from pathlib import Path

from quantaalpha.backtest.factor_loader import FactorLoader


def _build_loader(tmp_path: Path):
    config = {
        "factor_source": {
            "type": "custom",
            "custom": {
                "json_files": [],
                "quality_filter": None,
            },
        }
    }
    return FactorLoader(config)


def test_ranking_ascending_puts_missing_scores_last(tmp_path: Path):
    lib = tmp_path / "factors.json"
    lib.write_text(
        """
{
  "factors": {
    "f1": {"factor_name": "f1", "factor_expression": "$close", "backtest_results": {"Rank ICIR": "0.2"}},
    "f2": {"factor_name": "f2", "factor_expression": "$open"},
    "f3": {"factor_name": "f3", "factor_expression": "$high", "backtest_results": {"Rank ICIR": "0.1"}}
  }
}
""".strip(),
        encoding="utf-8",
    )

    loader = _build_loader(tmp_path)
    factors = loader._parse_all_factors_from_json(
        lib,
        ranking_metric="Rank ICIR",
        ranking_ascending=True,
    )

    assert [f["factor_name"] for f in factors] == ["f3", "f1", "f2"]
