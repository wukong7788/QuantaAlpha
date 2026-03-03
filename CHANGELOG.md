# Changelog

## 2026-03-03

### Changed
- Simplified safe backtest config layout:
  - Removed `configs/backtest_limited.yaml`.
  - `scripts/run_backtest_safe.sh` now uses `configs/backtest.yaml` by default unless `--config` is explicitly provided.
- Simplified safe backtest runtime controls:
  - Removed `--mode` from `scripts/run_backtest_safe.sh`.
  - Resource control now uses explicit `--threads <N>`.

## 2026-03-02

### Changed
- Restored factor proposal history window default to the initial value:
  - `DEFAULT_HISTORY_LIMIT` changed from `4` back to `6`.
  - This keeps O3 "history window optimization" disabled by default while preserving compact retry-summary feedback.
- Updated correlation de-dup sampling scope to prevent test leakage:
  - Dedup selector moved to `scripts/factor_filtering/select_factors.py`.
  - `select_factors.py` supports `--sample-split train_valid|full` and defaults to `train_valid`.
  - Stage metadata now includes sample window fields and linkage/method details.
- Implemented two-stage dedup pipeline:
  - Stage-1 exposure correlation coarse filter.
  - Stage-2 IC-series correlation fine filter.
  - New method switch: `--dedup-method stage1|two_stage` (default `two_stage`).
- Upgraded clustering and ranking in dedup:
  - New linkage switch: `--dedup-linkage complete|connected` (default `complete`).
  - Stage-2 champion score upgraded to composite:
    `abs(mean_ic)*max(ir,0)*coverage*stability*capacity_penalty`.
- Updated safe backtest wrapper for dedup split control:
  - `scripts/run_backtest_safe.sh` now supports:
    - `--dedup-sample-split <train_valid|full>`
    - `--dedup-method <stage1|two_stage>`
    - `--dedup-linkage <complete|connected>`
    - `--dedup-stage2-corr-threshold <T>`
  - Run summary and PID metadata now include method/linkage/stage2 threshold fields.
- Updated interactive backtest entry:
  - `scripts/run_backtest_safe.sh --interactive` now includes a one-click production dedup preset in single-library custom mode.
  - Preset values: `corr_dedup=true`, `dedup_method=two_stage`, `dedup_linkage=complete`, `sample_split=train_valid`, `topn=50`, `per_cluster=1`, `corr_threshold=0.8`, `stage2_corr_threshold=0.8`, `sample_size=12000`, `compute_missing=true`.
  - Step-1 target now includes `FILTER` (`factors-filter`): run filter pipeline only (no backtest), print concise filter summary, and save outputs to `data/factorlib/selected/`.
- Simplified FILTER-mode output naming and summary:
  - FILTER quick summary now emphasizes only `experiment`, `quality_range`, and final selected count.
  - FILTER result file naming is now concise and experiment-bound:
    `<experiment>_factors_filter_q<quality>_n<count>_<timestamp>.json`.
  - Stable alias remains `<experiment>_factors_filter_latest.json` for backtest re-use.
- Added filter-only CLI mode in safe script:
  - `--factors-filter` forces custom dedup path, skips backtest, and writes preview artifacts for quick inspection.
- Corrected Stage-1 truncation behavior in dedup:
  - Stage-1 no longer applies global TopN truncation.
  - `--dedup-topn` is now applied only after Stage-2 selection.
  - This preserves cross-cluster diversity before IC-series fine filtering.

## 2026-02-26

### Added
- Added true relay mode entry in `run.sh`:
  - `--relay` (fixed `LOG_TRACE_PATH` + resume intent)
  - `QUANTA_ENABLE_RELAY=1` wiring in launcher
- Added strict resume entry in `run.sh`:
  - `--resume` (mutually exclusive with `--relay`, continue to target rounds)
- Added relay resume source logging:
  - `Relay resume source: previous_experiment_id=..., state_saved_at_utc=..., previous_log_trace_path=...`
- Added run progress inspector scripts:
  - `scripts/run_doctor.py`
  - `scripts/run_doctor.sh`
- Added doctor diagnostics mode for run progress inspector:
  - `scripts/run_doctor.sh --doctor`
  - `scripts/run_doctor.py --doctor`
- Added terminal doctor entry:
  - `scripts/run_doctor.sh` (one-shot report by default)
- Added controlled evolution parallelism config:
  - `evolution.max_parallel_workers` to cap per-phase worker count when `parallel_enabled=true`.
- Added evolution empty-branch retry budget config:
  - `evolution.max_empty_retries`.
- Added construct-stage stop-loss budget configs:
  - `quality_gate.max_construct_failures_per_branch`
  - `quality_gate.max_json_parse_failures_per_branch`
- Added pre-calc cheap quality gate config:
  - `quality_gate.cheap_filter_enabled`
  - `quality_gate.cheap_filter_require_acceptable`

### Changed
- Extended `evolution_state.json` persistence with:
  - run metadata (`meta.*`)
  - evolution config snapshot (including selection/parallel flags)
  - persisted planning `directions`
- Changed relay checkpoint writes to include `directions` at task-level checkpoints.
- Clarified relay scheduling semantics in run-control metadata and startup logs:
  - `relay`: `first_leg_chunk_then_finish`
  - `resume`: `resume_to_target`
- Changed `run.sh` default to low-disk mode ON; added `--no-low-disk` to disable it explicitly.
- Changed default doctor output format to markdown report (`--doctor --markdown`) for terminal and workflow usage.
- Changed factor proposal history window:
  - `DEFAULT_HISTORY_LIMIT` reduced from `6` to `4`.
  - Retry feedback now uses compact summaries (error type + fix instruction + one counter-example), reducing prompt bloat.
- Changed parallel evolution scheduler behavior:
  - Parallel mode now launches tasks with a configurable worker cap instead of always launching all tasks at once.
- Changed factor loop behavior:
  - Added pre-calc static filtering before `factor_calculate` to skip invalid factors early.

### Fixed
- Fixed relay direction drift risk by restoring saved planning `directions` on resume.
- Fixed silent resume-with-different-config risk by adding strict config mismatch checks (fail-fast by default).
- Fixed unsafe legacy resume path (in-progress state without `directions`) by blocking resume unless explicitly forced with `QUANTA_FORCE_RELAY_RESUME=1`.
- Fixed false-resume behavior: `--resume` now fails fast when `evolution_state.json` is missing (no implicit round-0 restart).
- Fixed BOB `--bob-metric auto` mixed-scale ranking by resolving one global metric before scoring all factors.
- Fixed temporary file cleanup gap in `scripts/run_backtest_safe.sh` by installing cleanup trap before early-exit branches.
- Fixed `scripts/preflight_check.py` relative config path resolution so `uv run preflight_check.py ... --config configs/*.yaml` works from both repo root and `scripts/` directory.
- Fixed JSON response instability in LLM call path:
  - Empty JSON-mode responses now fail fast and retry directly.
  - Parse failure now triggers one immediate strict JSON-only follow-up request before outer retry.
  - JSON failure reasons are logged in structured format for diagnosis.
- Fixed long-running branch stalls in construct stage:
  - Repeated JSON parse failures / construct failures now trigger branch-level stop-loss instead of unbounded retries.

## 2026-02-27

### Added
- Added second-round optimization runtime options under `llm.*` (wired from `configs/experiment*.yaml`):
  - `json_mode_temperature`, `freeform_temperature`
  - `json_mode_response_format`, `json_mode_json_schema`
  - `request_timeout_s`, `retry_backoff`, `retry_jitter`, `retry_max_wait_seconds`
  - `failover_base_urls`
- Added cross-round exact dedup gate before expensive stages:
  - Repeated expressions are skipped before `factor_calculate/factor_backtest`.
  - Skip reason is persisted as `skip_reason=duplicate_exact`.
- Added regression tests for second-round optimization behavior:
  - `tests/llm/test_client_second_round_optimization.py`
  - `tests/pipeline/test_loop_exact_duplicate_filter.py`
  - `tests/pipeline/test_factor_mining_llm_runtime_settings.py`

### Changed
- Improved relay/resume granularity inside evolution tasks:
  - Tasks now attempt to resume from the latest `__session__` pickle snapshot under each task log directory.
  - This avoids re-running already completed steps after process restarts.
- Changed LLM request strategy in `json_mode`:
  - Protocol-level JSON response format can be enforced (`json_object` / optional `json_schema`).
  - Temperature is now split by structured vs freeform calls.
- Changed retry wait policy from fixed-delay-only to configurable fixed/exponential backoff with optional jitter and wait cap.

### Fixed
- Fixed `reasoning_flag=true && json_mode=false` path incorrectly forcing JSON extraction/repair.
- Fixed network tail-latency stalls by enforcing per-request timeout in chat/embedding calls.
- Fixed cross-loop duplicate-exact cache staleness by invalidating seen-expression cache before each construct step.
- Fixed failover over-triggering by limiting endpoint switching to transport-like exceptions (timeout/connection/rate-limit/server), excluding JSON parse/content errors.
- Fixed runtime bool option parsing (`llm.json_mode_strict`, `llm.retry_jitter`) to correctly handle bool-like strings such as `"false"` / `"0"`.

## 2026-02-28

### Added
- Added backtest A/B memory harness script:
  - `scripts/abtest_backtest_memory.py` (reports elapsed time + peak RSS; baseline=HEAD vs optimized=working tree).
- Added experiment A/B harness script:
  - `scripts/abtest_experiment.py` (runs `./run.sh` with config toggles; isolates artifacts under `/tmp`; emits `ABTEST_RESULT=...` and saves doctor report).
  - New `compare` mode: runs baseline+optimized (each repeated N times) and prints `ABTEST_COMPARISON=...`.
- Added correlation de-dup option in `scripts/run_backtest_safe.sh`:
  - `--corr-dedup` with tuning knobs `--dedup-topn`, `--dedup-per-cluster` (default 3), `--dedup-corr-threshold`, `--dedup-sample-size`.
  - Backtest PID metadata now records dedup settings (`corr_dedup`, `dedup_*`) for later comparison.

### Changed
- Attempted backtest peak-memory reduction changes, but reverted after A/B test showed higher peak RSS (negative optimization).
- Disabled cheap pre-calc filter by default after A/B (STEP_N=3) showed worse wall-time:
  - `quality_gate.cheap_filter_enabled=false`
  - `quality_gate.cheap_filter_require_acceptable=false`
- Kept protocol-level JSON constraint defaults enabled (A/B positive):
  - `llm.json_mode_strict=true`
  - `llm.json_mode_response_format=json_object`
- Reverted temperature-split default after A/B (STEP_N=3) showed worse wall-time:
  - default keeps `llm.json_mode_temperature=0.5` aligned with `llm.freeform_temperature=0.5`

### Removed
- Removed redundant config file `experiment_full_11.yaml`; use `--rounds` with `configs/experiment.yaml` for 11-round relay runs.

### Changed
- Hardcoded full paper reproduction parameters into the default `experiment.yaml`:
  - `factor.factors_per_hypothesis: 3`
  - `evolution.max_rounds: 23`
  - `evolution.relay_chunk_rounds: 6`
- Restored `configs/experiment_smoke.yaml` and switched `minirun.sh` back to smoke-only config by default.
- Changed low-disk precision default to keep `float64`:
  - `QUANTA_LOW_DISK_FLOAT32` now defaults to `false` (including `--low-disk` mode)
  - `float32` cast is now opt-in only via explicit env override
- Enhanced `run.sh` startup paper-mode summary:
  - prints low-disk runtime knobs (`QUANTA_LOW_DISK_MODE/FLOAT32/PARQUET_COMPRESSION/PURGE_*`)
  - prints explicit `paper.factor_setting_match` status for `factors_per_hypothesis=3`

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
