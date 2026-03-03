import numpy as np
import pandas as pd

from quantaalpha.backtest.factor_calculator import FactorCalculator


def test_factor_calculator_does_not_consume_base_name_on_failed_duplicate():
    idx = pd.MultiIndex.from_product(
        [pd.to_datetime(["2024-01-02", "2024-01-03"]), ["SH600000", "SZ000001"]],
        names=["datetime", "instrument"],
    )
    data_df = pd.DataFrame({"$close": np.arange(len(idx), dtype=np.float64)}, index=idx)

    calc = FactorCalculator(config={"llm": {"cache_results": False, "enabled": False}}, data_df=data_df)

    def _fake_calculate(expr: str):
        if expr == "bad_expr":
            return None
        return pd.Series(np.arange(len(idx), dtype=np.float64), index=idx, name="dup")

    calc._calculate_with_parser = _fake_calculate  # type: ignore[method-assign]

    factors = [
        {"factor_id": "id1", "factor_name": "dup", "factor_expression": "bad_expr"},
        {"factor_id": "id2", "factor_name": "dup", "factor_expression": "$close"},
    ]

    df = calc.calculate_factors(factors)

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["dup"]
    assert df.shape[1] == 1
