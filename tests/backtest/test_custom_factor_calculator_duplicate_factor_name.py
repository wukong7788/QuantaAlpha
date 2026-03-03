import hashlib

import numpy as np
import pandas as pd

from quantaalpha.backtest.custom_factor_calculator import CustomFactorCalculator
from quantaalpha.utils.factor_cache import write_factor_cache


def _md5(expr: str) -> str:
    return hashlib.md5(expr.encode()).hexdigest()


def test_custom_factor_calculator_keeps_all_columns_when_factor_name_duplicates(tmp_path):
    idx = pd.MultiIndex.from_product(
        [pd.to_datetime(["2024-01-02", "2024-01-03"]), ["SH600000", "SZ000001"]],
        names=["datetime", "instrument"],
    )
    data_df = pd.DataFrame({"$close": np.arange(len(idx), dtype=np.float64)}, index=idx)

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    expr1 = "$close"
    expr2 = "($close + 1)"

    s1 = pd.Series(np.arange(len(idx), dtype=np.float64), index=idx, name="dup")
    s2 = pd.Series(np.arange(len(idx), dtype=np.float64) + 100.0, index=idx, name="dup")

    # Write pickle cache to avoid any pyarrow dependency in tests.
    assert write_factor_cache(cache_dir, _md5(expr1), s1, config={"cache_format": "pkl"})
    assert write_factor_cache(cache_dir, _md5(expr2), s2, config={"cache_format": "pkl"})

    calc = CustomFactorCalculator(
        data_df=data_df,
        cache_dir=cache_dir,
        auto_extract_cache=False,
        config={"llm": {"cache_dir": str(cache_dir)}},
    )

    factors = [
        {"factor_id": "id1", "factor_name": "dup", "factor_expression": expr1},
        {"factor_id": "id2", "factor_name": "dup", "factor_expression": expr2},
    ]

    df = calc.calculate_factors_batch(factors, use_cache=True, skip_compute=True)

    assert isinstance(df, pd.DataFrame)
    assert df.shape[1] == 2
    assert set(df.columns) == {"dup", "dup__id2"}
    assert (df["dup"].to_numpy() == s1.to_numpy()).all()
    assert (df["dup__id2"].to_numpy() == s2.to_numpy()).all()

