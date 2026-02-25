import pandas as pd

from quantaalpha.backtest.runner import BacktestRunner


def _make_series(level0, level1, names):
    index = pd.MultiIndex.from_arrays([level0, level1], names=names)
    return pd.Series(range(len(index)), index=index, name="score")


def test_normalize_swaps_when_index_names_are_explicit():
    signal = _make_series(
        level0=["SH600000", "SZ000001"],
        level1=pd.to_datetime(["2024-01-03", "2024-01-02"]),
        names=["instrument", "datetime"],
    )

    normalized = BacktestRunner._normalize_dt_inst_index(signal, "pred")

    assert list(normalized.index.names) == ["datetime", "instrument"]
    assert pd.api.types.is_datetime64_any_dtype(normalized.index.get_level_values("datetime"))
    assert set(normalized.index.tolist()) == {
        (pd.Timestamp("2024-01-03"), "SH600000"),
        (pd.Timestamp("2024-01-02"), "SZ000001"),
    }


def test_normalize_uses_datetime_dtype_when_names_missing():
    signal = _make_series(
        level0=["SH600000", "SZ000001"],
        level1=pd.to_datetime(["2024-01-03", "2024-01-02"]),
        names=[None, None],
    )

    normalized = BacktestRunner._normalize_dt_inst_index(signal, "pred")

    assert list(normalized.index.names) == ["datetime", "instrument"]
    assert pd.api.types.is_datetime64_any_dtype(normalized.index.get_level_values("datetime"))
    assert set(normalized.index.tolist()) == {
        (pd.Timestamp("2024-01-03"), "SH600000"),
        (pd.Timestamp("2024-01-02"), "SZ000001"),
    }


def test_normalize_strict_fallback_for_object_object_index():
    signal = _make_series(
        level0=["2024-01-03", "2024-01-02"],
        level1=["SH600000", "SZ000001"],
        names=[None, None],
    )

    normalized = BacktestRunner._normalize_dt_inst_index(signal, "pred")

    assert list(normalized.index.names) == ["datetime", "instrument"]
    assert pd.api.types.is_datetime64_any_dtype(normalized.index.get_level_values("datetime"))
    assert set(normalized.index.tolist()) == {
        (pd.Timestamp("2024-01-03"), "SH600000"),
        (pd.Timestamp("2024-01-02"), "SZ000001"),
    }


def test_normalize_skips_ambiguous_object_object_index():
    signal = _make_series(
        level0=["2024-01-03", "2024-01-02"],
        level1=["2024-02-03", "2024-02-02"],
        names=[None, None],
    )

    normalized = BacktestRunner._normalize_dt_inst_index(signal, "pred")

    assert normalized.index.equals(signal.index)
    assert list(normalized.index.names) == [None, None]


def test_normalize_does_not_drop_rows_on_invalid_datetime_values():
    signal = _make_series(
        level0=["2024-01-03", "NOT_A_DATE"],
        level1=["SH600000", "SZ000001"],
        names=["datetime", "instrument"],
    )

    normalized = BacktestRunner._normalize_dt_inst_index(signal, "pred")

    assert len(normalized) == 2
    assert normalized.index.equals(signal.index)
    assert list(normalized.index.names) == ["datetime", "instrument"]
