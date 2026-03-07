import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from quantaalpha.backtest import custom_factor_calculator as calculator_module


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "factor_filtering" / "select_factors.py"


def _load_select_factors_module():
    spec = importlib.util.spec_from_file_location("test_select_factors_module", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeCalculator:
    def __init__(self, *args, **kwargs):  # noqa: D401, ANN002, ANN003
        pass

    def _auto_extract_cache_from_logs(self):
        return None


def test_stop_after_stage2_allows_small_candidate_pool(tmp_path, monkeypatch):
    module = _load_select_factors_module()

    library_path = tmp_path / "library.json"
    config_path = tmp_path / "backtest.yaml"
    out_path = tmp_path / "stage2_final.json"
    out_stage1 = tmp_path / "stage1.json"
    out_stage2 = tmp_path / "stage2.json"
    report_path = tmp_path / "report.json"

    factors = {
        f"f{i}": {
            "factor_name": f"factor_{i}",
            "factor_expression": f"TS_MEAN($close, {i + 2})",
            "backtest_results": {
                "1day.excess_return_with_cost.information_ratio": 0.1 * (i + 1),
            },
        }
        for i in range(3)
    }
    library_path.write_text(
        json.dumps({"metadata": {"total_factors": len(factors)}, "factors": factors}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    config_path.write_text("data: {}\ndataset: {}\n", encoding="utf-8")

    sample_index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2020-01-01", "2020-01-02"]), ["A", "B"]],
        names=["datetime", "instrument"],
    )

    monkeypatch.setattr(module, "_load_yaml", lambda path: {"data": {}, "dataset": {}})
    monkeypatch.setattr(module, "_init_qlib", lambda config: None)
    monkeypatch.setattr(module, "_resolve_sample_window", lambda config, split: ("2020-01-01", "2020-01-02", "test"))
    monkeypatch.setattr(module, "_load_base_index", lambda config, start_time, end_time: sample_index)
    monkeypatch.setattr(module, "_sample_index", lambda full_index, sample_size, seed: full_index)
    monkeypatch.setattr(
        module,
        "_load_factor_series",
        lambda calc, factor_name, factor_expression, factor_info, compute_missing: pd.Series(
            np.linspace(0.0, 1.0, len(sample_index)),
            index=sample_index,
        ),
    )
    monkeypatch.setattr(module, "_rank_columns_spearman_corr", lambda x, min_periods: np.eye(x.shape[1]))
    monkeypatch.setattr(
        module,
        "_cluster_indices",
        lambda corr, threshold, linkage_mode: ([[i] for i in range(corr.shape[0])], "connected"),
    )
    monkeypatch.setattr(calculator_module, "CustomFactorCalculator", _FakeCalculator)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "select_factors.py",
            "--library",
            str(library_path),
            "--config",
            str(config_path),
            "--out",
            str(out_path),
            "--out-stage1",
            str(out_stage1),
            "--out-stage2",
            str(out_stage2),
            "--stop-after-stage",
            "stage2",
            "--topn",
            "0",
            "--report",
            str(report_path),
        ],
    )

    assert module.main() == 0

    out_payload = json.loads(out_path.read_text(encoding="utf-8"))
    stage2_payload = json.loads(out_stage2.read_text(encoding="utf-8"))

    assert out_payload["metadata"]["stop_after_stage"] == "stage2"
    assert stage2_payload["metadata"]["selection_stage"] == "stage2_exposure_corr"
    assert len(out_payload["factors"]) == 3
    assert len(stage2_payload["factors"]) == 3
