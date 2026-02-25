# Changelog

## 2026-02-25

### Added
- Added offline backtest result APIs in frontend backend:
  - `GET /api/v1/backtest-offline/latest` (supports `metricsFile`)
  - `GET /api/v1/backtest-offline/runs` (list selectable runs)
- Added frontend backtest page support for loading offline results with a run selector dropdown.
- Added `--max-factors <N|all|default>` to `scripts/run_backtest_safe.sh` and interactive wizard prompt.

### Changed
- Changed backtest result naming to include both factor count and Beijing timestamp:
  - `<library_or_exp>_n<num_factors>_<YYYYMMDD_HHMMSS>_backtest_metrics.json`
  - `<library_or_exp>_n<num_factors>_<YYYYMMDD_HHMMSS>_cumulative_excess.csv`
- Changed frontend/backend offline matching logic to support timestamped result files via library-prefix matching.
- Changed online task result loading (`_load_backtest_results`) to prefer current library-prefixed metrics files before global latest.

### Fixed
- Fixed backend route conflict risk by using dedicated offline path prefix (`/api/v1/backtest-offline/...`).
- Fixed repeated overwrite of same-library backtest outputs by introducing timestamped output filenames.

## 2026-02-23

### Added
- Added `minirun.sh` for a fast smoke run (`STEP_N=3` by default) with preflight checks.
- Added optional Telegram notification at the end of `minirun.sh` (success/failure summary).
- Added `configs/experiment_smoke.yaml` for lightweight local validation.

### Changed
- Updated `run.sh` to support `uv`/`.venv` workflow directly (no conda requirement).
- Updated `frontend-v2/start.sh` to use `.venv` and `uv` instead of conda.
- Set default log folder timestamp to Asia/Shanghai (Beijing time) when `LOG_TRACE_PATH` is not explicitly set.
- Added ignore rule for `hf_data/cn_data.zip` in `.gitignore`.

### Fixed
- Fixed macOS factor data linking issue by enabling symlink creation on Darwin in
  `quantaalpha/core/experiment.py`, resolving intermittent `daily_pv.h5` not found during factor execution.
