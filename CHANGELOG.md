# Changelog

Format: Sections per date use `Added / Fixed / Performance / Changed / Removed` (plus optional `Highlights / Docs / Internal`).
Each change entry starts with tags: `[area][impact]` (optionally severity `[P0|P1|P2]`) to make changes greppable.

## 2026-03-07

### Fixed
- [scripts][behavior] Harden `run.sh --blacklist-file` summary printing on macOS shell environments:
  - Replace the truthy regex gate for `QUANTA_SUBTREE_BLACKLIST_ENABLED` with a `case`-based helper to avoid runtime parse issues near blacklist summary output.
  - Add regression coverage to verify valid blacklist runs print raw/usable counts before entering mining.

## 2026-03-04

### Added
- [pipeline][feature] Add optional subtree-blacklist pre-calc gate in `AlphaAgentLoop`:
  - New quality-gate keys: `subtree_blacklist_enabled`, `subtree_blacklist_path`, `subtree_blacklist_max_patterns`, `subtree_blacklist_min_nodes`.
  - When enabled, factors matching blacklisted AST subtrees are rejected before `factor_calculate/factor_backtest`.
- [scripts][feature] Add `run.sh --blacklist-file <path>`:
  - Enables subtree blacklist mode without changing default workflow semantics.
  - Supports env overrides `QUANTA_SUBTREE_BLACKLIST_{PATH,MAX_PATTERNS,MIN_NODES}`.
- [tests][feature] Add subtree-blacklist regression coverage:
  - `tests/pipeline/test_loop_subtree_blacklist.py`
  - `tests/factors/test_subtree_blacklist.py`
- [scripts][feature] Add `scripts/run_factors.sh` option `6) [BLACKLIST]`:
  - Export subtree blacklist JSON from Stage1/merged factor library JSON or Zoo CSV.
  - Output can be used directly with `run.sh --blacklist-file`.
- [scripts][feature] Improve `scripts/abtest_experiment.py` runtime visibility:
  - Print real-time `[ABTEST]` progress logs for each run start/finish and doctor stage.
  - Print run log / doctor report / generated config paths at run start.
- [scripts][feature] Enhance `scripts/abtest_experiment.py` result payloads:
  - Extract `factor_quality` from `data/factorlib/all_factors_library_<suffix>.json` (median/best of key `backtest_results` metrics).
  - Track whether `subtree_blacklist` actually rejected factors (parse run.log) and report success-only deltas in `ABTEST_COMPARISON`.
- [scripts][feature] `scripts/run_backtest_safe.sh --interactive` adds `FILTER+BT` target:
  - Runs factors-filter first, then backtests selected stage output (`stage1` / `stage2` / `stage3`) for direct stage comparison.
- [scripts][feature] Add uncached backtest control in `run_backtest_safe.sh`:
  - New flag `--no-skip-uncached` to include uncached factors (compute during backtest).
  - `FILTER+BT` interactive path now prompts whether to include uncached factors.
- [scripts][feature] Merge can optionally emit Stage1 expr-dedup pool:
  - `scripts/factor_filtering/merge_factor_libraries.py` adds `--out-stage1` (expression hard-dedup on pooled factors).
  - `scripts/run_factors.sh` option `3` prompts to export Stage1 pool so “one expression -> one factor” is explicit (Zoo output remains novelty-only).

### Changed
- [llm][behavior] Restore default run-config temperatures to `0.7` and sync `llm.freeform_temperature` to env `CHAT_TEMPERATURE` at startup to avoid backend drift.

### Fixed
- [scripts][behavior] Fix stage-selection behavior in filter pipeline:
  - Selecting `stage1`/`stage2` now short-circuits after the chosen stage output is written, instead of continuing through later stages.
- [scripts][behavior] Fix `run_backtest_safe.sh` filter dedup defaults:
  - `FILTER` / `FILTER+BT` modes now pass `--expr-dedup-method ast` explicitly to `select_factors.py` (was implicit `none` before).
- [scripts][behavior] Fix `FILTER+BT` stage execution scope:
  - `run_backtest_safe.sh` now passes `--stop-after-stage` based on selected stage so `stage1`/`stage2` no longer run unnecessary later-stage computation.
- [backtest][output] Clarify cache-loading logs in custom factor compute:
  - Suppress per-factor `cache_location result.h5` missing debug noise.
  - Add explicit one-time fallback note and summary field `H5 missing <count>` so users can distinguish fallback hits from real recomputation.
- [scripts][behavior] Fix `run.sh --rounds N` portability bug on macOS/BSD:
  - Replace `sed`-based `max_rounds` override with Python-based text patching.
  - `--rounds 11` now reliably overrides `evolution.max_rounds` before relay scheduling and preflight checks.

### Docs
- [docs][docs] Sync blacklist mode docs in `SPECS.md`, `README.md`, `README_CN.md`, `docs/PAPER_REPRODUCTION_GUIDE.md`, and `docs/warm-start.md` (including warm-start vs blacklist A/B template commands).

## 2026-03-03

### Added
- [scripts][feature] Multi-library merge + Zoo builder:
  - `scripts/factor_filtering/merge_factor_libraries.py` merges multiple `all_factors_library*.json` into a pooled library (no Top-N selection).
  - Can generate Zoo outputs for A/B testing: whitespace-normalized (`norm`) and AST-canonicalized (`ast`).
- [scripts][feature] Cache repair helper:
  - `scripts/factor_filtering/repair_factor_cache.py` scans MD5 cache entries, deletes invalid ones, and recomputes factors to rebuild cache.
- [scripts][feature] Filter stage exports:
  - `scripts/factor_filtering/select_factors.py` supports `--expr-dedup-method` and stage outputs `--out-stage1/--out-stage2` for full vs stage comparisons.
- [scripts][feature] Interactive factor library inspector:
  - `scripts/run_factors.sh` option `1` lists `all_factors_library*.json` summary (factor count, quality H/M/L, ARR).
  - `scripts/run_factors.sh` option `2` deletes libraries by id (supports `+` batch input).
  - `scripts/run_factors.sh` option `4` repairs factor MD5 cache by library id (dry-run + apply).
  - `scripts/run_factors.sh` option `3` merges libraries by id (supports `+` batch input and `all`), supports `zoo-method=ast|norm|both|none`, auto-names output as `<prefix>_n<count>_<timestamp>.json`, and prints merged `n + H/M/L` summary plus `FACTOR_CoSTEER_FACTOR_ZOO_PATH` export hint.
  - `scripts/run_factors.sh` option `5` runs an observable filter pipeline (`stage0→stage3`) with stage-selectable outputs (`stage0|stage1|stage2|stage3|all`) and emits a per-run `manifest.json`.
  - Simplified option `5` interaction defaults: Stage1 expression dedup is fixed to `ast`, Stage3 topn is fixed to `all`, and output prefix defaults to `data/factorlib/selected/<source>_filter_pipeline` (no extra prompts).

### Changed
- [scripts][behavior] Simplify safe backtest config layout:
  - Removed `configs/backtest_limited.yaml`.
  - `scripts/run_backtest_safe.sh` now uses `configs/backtest.yaml` by default unless `--config` is explicitly provided.
- [scripts][behavior] Simplify safe backtest runtime controls:
  - Removed `--mode` from `scripts/run_backtest_safe.sh`.
  - Resource control now uses explicit `--threads <N>`.

### Fixed
- [backtest][output][P1] Fix duplicate `factor_name` collisions silently overwriting columns during factor calculation (enforce unique output keys: append `__<factor_id>`).

## 2026-03-02

### Changed
- [factors][behavior] Restore factor proposal history window default to the initial value:
  - `DEFAULT_HISTORY_LIMIT` changed from `4` back to `6`.
  - This keeps O3 "history window optimization" disabled by default while preserving compact retry-summary feedback.
- [scripts][behavior] Update correlation de-dup sampling scope to prevent test leakage:
  - Dedup selector moved to `scripts/factor_filtering/select_factors.py`.
  - `select_factors.py` supports `--sample-split train_valid|full` and defaults to `train_valid`.
  - Stage metadata now includes sample window fields and linkage/method details.
- [scripts][feature] Implement two-stage dedup pipeline:
  - Stage-1 exposure correlation coarse filter.
  - Stage-2 IC-series correlation fine filter.
  - New method switch: `--dedup-method stage1|two_stage` (default `two_stage`).
- [scripts][behavior] Upgrade clustering and ranking in dedup:
  - New linkage switch: `--dedup-linkage complete|connected` (default `complete`).
  - Stage-2 champion score upgraded to composite:
    `abs(mean_ic)*max(ir,0)*coverage*stability*capacity_penalty`.
- [scripts][behavior] Update safe backtest wrapper for dedup split control:
  - `scripts/run_backtest_safe.sh` now supports:
    - `--dedup-sample-split <train_valid|full>`
    - `--dedup-method <stage1|two_stage>`
    - `--dedup-linkage <complete|connected>`
    - `--dedup-stage2-corr-threshold <T>`
  - Run summary and PID metadata now include method/linkage/stage2 threshold fields.
- [scripts][behavior] Update interactive backtest entry:
  - `scripts/run_backtest_safe.sh --interactive` now includes a one-click production dedup preset in single-library custom mode.
  - Preset values: `corr_dedup=true`, `dedup_method=two_stage`, `dedup_linkage=complete`, `sample_split=train_valid`, `topn=50`, `per_cluster=1`, `corr_threshold=0.8`, `stage2_corr_threshold=0.8`, `sample_size=12000`, `compute_missing=true`.
  - Step-1 target now includes `FILTER` (`factors-filter`): run filter pipeline only (no backtest), print concise filter summary, and save outputs to `data/factorlib/selected/`.
- [scripts][output] Simplify FILTER-mode output naming and summary:
  - FILTER quick summary now emphasizes only `experiment`, `quality_range`, and final selected count.
  - FILTER result file naming is now concise and experiment-bound:
    `<experiment>_factors_filter_q<quality>_n<count>_<timestamp>.json`.
  - Stable alias remains `<experiment>_factors_filter_latest.json` for backtest re-use.
- [scripts][feature] Add filter-only CLI mode in safe script:
  - `--factors-filter` forces custom dedup path, skips backtest, and writes preview artifacts for quick inspection.

### Fixed
- [scripts][reliability] Correct Stage-1 truncation behavior in dedup:
  - Stage-1 no longer applies global TopN truncation.
  - `--dedup-topn` is now applied only after Stage-2 selection.
  - This preserves cross-cluster diversity before IC-series fine filtering.

## 2026-02-26

### Added
- [scripts][feature] Add true relay mode entry in `run.sh`:
  - `--relay` (fixed `LOG_TRACE_PATH` + resume intent)
  - `QUANTA_ENABLE_RELAY=1` wiring in launcher
- [scripts][feature] Add strict resume entry in `run.sh`:
  - `--resume` (mutually exclusive with `--relay`, continue to target rounds)
- [pipeline][reliability] Add relay resume source logging:
  - `Relay resume source: previous_experiment_id=..., state_saved_at_utc=..., previous_log_trace_path=...`
- [scripts][feature] Add run progress inspector scripts:
  - `scripts/run_doctor.py`
  - `scripts/run_doctor.sh`
- [scripts][feature] Add doctor diagnostics mode for run progress inspector:
  - `scripts/run_doctor.sh --doctor`
  - `scripts/run_doctor.py --doctor`
- [scripts][feature] Add terminal doctor entry:
  - `scripts/run_doctor.sh` (one-shot report by default)
- [configs][feature] Add controlled evolution parallelism config:
  - `evolution.max_parallel_workers` to cap per-phase worker count when `parallel_enabled=true`.
- [configs][feature] Add evolution empty-branch retry budget config:
  - `evolution.max_empty_retries`.
- [configs][feature] Add construct-stage stop-loss budget configs:
  - `quality_gate.max_construct_failures_per_branch`
  - `quality_gate.max_json_parse_failures_per_branch`
- [configs][feature] Add pre-calc cheap quality gate config:
  - `quality_gate.cheap_filter_enabled`
  - `quality_gate.cheap_filter_require_acceptable`

### Changed
- [pipeline][behavior] Extend `evolution_state.json` persistence with:
  - run metadata (`meta.*`)
  - evolution config snapshot (including selection/parallel flags)
  - persisted planning `directions`
- [pipeline][behavior] Change relay checkpoint writes to include `directions` at task-level checkpoints.
- [pipeline][behavior] Clarify relay scheduling semantics in run-control metadata and startup logs:
  - `relay`: `first_leg_chunk_then_finish`
  - `resume`: `resume_to_target`
- [scripts][behavior] Change `run.sh` default to low-disk mode ON; add `--no-low-disk` to disable it explicitly.
- [scripts][behavior] Change default doctor output format to markdown report (`--doctor --markdown`) for terminal and workflow usage.
- [factors][behavior] Change factor proposal history window:
  - `DEFAULT_HISTORY_LIMIT` reduced from `6` to `4`.
  - Retry feedback now uses compact summaries (error type + fix instruction + one counter-example), reducing prompt bloat.
- [pipeline][behavior] Change parallel evolution scheduler behavior:
  - Parallel mode now launches tasks with a configurable worker cap instead of always launching all tasks at once.
- [pipeline][behavior] Change factor loop behavior:
  - Added pre-calc static filtering before `factor_calculate` to skip invalid factors early.

### Fixed
- [pipeline][reliability] Fix relay direction drift risk by restoring saved planning `directions` on resume.
- [pipeline][reliability] Fix silent resume-with-different-config risk by adding strict config mismatch checks (fail-fast by default).
- [pipeline][reliability] Fix unsafe legacy resume path (in-progress state without `directions`) by blocking resume unless explicitly forced with `QUANTA_FORCE_RELAY_RESUME=1`.
- [pipeline][reliability] Fix false-resume behavior: `--resume` now fails fast when `evolution_state.json` is missing (no implicit round-0 restart).
- [backtest][output] Fix BOB `--bob-metric auto` mixed-scale ranking by resolving one global metric before scoring all factors.
- [scripts][reliability] Fix temporary file cleanup gap in `scripts/run_backtest_safe.sh` by installing cleanup trap before early-exit branches.
- [scripts][reliability] Fix `scripts/preflight_check.py` relative config path resolution so `uv run preflight_check.py ... --config configs/*.yaml` works from both repo root and `scripts/` directory.
- [llm][reliability] Fix JSON response instability in LLM call path:
  - Empty JSON-mode responses now fail fast and retry directly.
  - Parse failure now triggers one immediate strict JSON-only follow-up request before outer retry.
  - JSON failure reasons are logged in structured format for diagnosis.
- [pipeline][reliability] Fix long-running branch stalls in construct stage:
  - Repeated JSON parse failures / construct failures now trigger branch-level stop-loss instead of unbounded retries.

## 2026-02-27

### Added
- [llm][feature] Add second-round optimization runtime options under `llm.*` (wired from `configs/experiment*.yaml`):
  - `json_mode_temperature`, `freeform_temperature`
  - `json_mode_response_format`, `json_mode_json_schema`
  - `request_timeout_s`, `retry_backoff`, `retry_jitter`, `retry_max_wait_seconds`
  - `failover_base_urls`
- [pipeline][feature] Add cross-round exact dedup gate before expensive stages:
  - Repeated expressions are skipped before `factor_calculate/factor_backtest`.
  - Skip reason is persisted as `skip_reason=duplicate_exact`.
- [tests][feature] Add regression tests for second-round optimization behavior:
  - `tests/llm/test_client_second_round_optimization.py`
  - `tests/pipeline/test_loop_exact_duplicate_filter.py`
  - `tests/pipeline/test_factor_mining_llm_runtime_settings.py`

### Changed
- [pipeline][behavior] Improve relay/resume granularity inside evolution tasks:
  - Tasks now attempt to resume from the latest `__session__` pickle snapshot under each task log directory.
  - This avoids re-running already completed steps after process restarts.
- [llm][behavior] Change LLM request strategy in `json_mode`:
  - Protocol-level JSON response format can be enforced (`json_object` / optional `json_schema`).
  - Temperature is now split by structured vs freeform calls.
- [llm][behavior] Change retry wait policy from fixed-delay-only to configurable fixed/exponential backoff with optional jitter and wait cap.

### Fixed
- [llm][reliability] Fix `reasoning_flag=true && json_mode=false` path incorrectly forcing JSON extraction/repair.
- [llm][reliability] Fix network tail-latency stalls by enforcing per-request timeout in chat/embedding calls.
- [pipeline][reliability] Fix cross-loop duplicate-exact cache staleness by invalidating seen-expression cache before each construct step.
- [llm][reliability] Fix failover over-triggering by limiting endpoint switching to transport-like exceptions (timeout/connection/rate-limit/server), excluding JSON parse/content errors.
- [llm][reliability] Fix runtime bool option parsing (`llm.json_mode_strict`, `llm.retry_jitter`) to correctly handle bool-like strings such as `"false"` / `"0"`.

## 2026-02-28

### Added
- [backtest][feature] Add backtest A/B memory harness script:
  - `scripts/abtest_backtest_memory.py` (reports elapsed time + peak RSS; baseline=HEAD vs optimized=working tree).
- [scripts][feature] Add experiment A/B harness script:
  - `scripts/abtest_experiment.py` (runs `./run.sh` with config toggles; isolates artifacts under `/tmp`; emits `ABTEST_RESULT=...` and saves doctor report).
  - New `compare` mode: runs baseline+optimized (each repeated N times) and prints `ABTEST_COMPARISON=...`.
- [scripts][feature] Add correlation de-dup option in `scripts/run_backtest_safe.sh`:
  - `--corr-dedup` with tuning knobs `--dedup-topn`, `--dedup-per-cluster` (default 3), `--dedup-corr-threshold`, `--dedup-sample-size`.
  - Backtest PID metadata now records dedup settings (`corr_dedup`, `dedup_*`) for later comparison.

### Performance
- [backtest][mem][P2] Attempted peak-memory reduction changes, but reverted after A/B test showed higher peak RSS (negative optimization).
- [pipeline][perf] Disable cheap pre-calc filter by default after A/B (STEP_N=3) showed worse wall-time:
  - `quality_gate.cheap_filter_enabled=false`
  - `quality_gate.cheap_filter_require_acceptable=false`
- [llm][perf] Keep protocol-level JSON constraint defaults enabled (A/B positive):
  - `llm.json_mode_strict=true`
  - `llm.json_mode_response_format=json_object`
- [llm][perf] Revert temperature-split default after A/B (STEP_N=3) showed worse wall-time:
  - default keeps `llm.json_mode_temperature=0.5` aligned with `llm.freeform_temperature=0.5`
- [scripts][perf] Keep low-disk precision default as `float64` (avoid metric drift observed in A/B):
  - `QUANTA_LOW_DISK_FLOAT32`: default `false` (including `--low-disk`)

### Removed
- [configs][internal] Remove redundant config file `experiment_full_11.yaml`; use `--rounds` with `configs/experiment.yaml` for 11-round relay runs.

### Changed
- [configs][behavior] Hardcode full paper reproduction parameters into the default `experiment.yaml`:
  - `factor.factors_per_hypothesis: 3`
  - `evolution.max_rounds: 23`
  - `evolution.relay_chunk_rounds: 6`
- [scripts][behavior] Restore `configs/experiment_smoke.yaml` and switch `minirun.sh` back to smoke-only config by default.
- [scripts][behavior] Enhance `run.sh` startup paper-mode summary:
  - prints low-disk runtime knobs (`QUANTA_LOW_DISK_MODE/FLOAT32/PARQUET_COMPRESSION/PURGE_*`)
  - prints explicit `paper.factor_setting_match` status for `factors_per_hypothesis=3`

## 2026-02-25

### Added
- [frontend][feature] Add offline backtest result APIs in frontend backend:
  - `GET /api/v1/backtest-offline/latest` (supports `metricsFile`)
  - `GET /api/v1/backtest-offline/runs` (list selectable runs)
- [frontend][feature] Add frontend backtest page support for loading offline results with a run selector dropdown.
- [scripts][feature] Add `--max-factors <N|all|default>` to `scripts/run_backtest_safe.sh` and interactive wizard prompt.

### Changed
- [backtest][output] Change backtest result naming to include both factor count and Beijing timestamp:
  - `<library_or_exp>_n<num_factors>_<YYYYMMDD_HHMMSS>_backtest_metrics.json`
  - `<library_or_exp>_n<num_factors>_<YYYYMMDD_HHMMSS>_cumulative_excess.csv`
- [frontend][behavior] Change frontend/backend offline matching logic to support timestamped result files via library-prefix matching.
- [frontend][behavior] Change online task result loading (`_load_backtest_results`) to prefer current library-prefixed metrics files before global latest.

### Fixed
- [frontend][reliability] Fix backend route conflict risk by using dedicated offline path prefix (`/api/v1/backtest-offline/...`).
- [backtest][output] Fix repeated overwrite of same-library backtest outputs by introducing timestamped output filenames.

## 2026-02-23

### Added
- [scripts][feature] Add `minirun.sh` for a fast smoke run (`STEP_N=3` by default) with preflight checks.
- [scripts][feature] Add optional Telegram notification at the end of `minirun.sh` (success/failure summary).
- [configs][feature] Add `configs/experiment_smoke.yaml` for lightweight local validation.

### Changed
- [scripts][behavior] Update `run.sh` to support `uv`/`.venv` workflow directly (no conda requirement).
- [scripts][behavior] Update `frontend-v2/start.sh` to use `.venv` and `uv` instead of conda.
- [core][behavior] Set default log folder timestamp to Asia/Shanghai (Beijing time) when `LOG_TRACE_PATH` is not explicitly set.
- [configs][behavior] Add ignore rule for `hf_data/cn_data.zip` in `.gitignore`.

### Fixed
- [core][reliability] Fix macOS factor data linking issue by enabling symlink creation on Darwin in
  `quantaalpha/core/experiment.py`, resolving intermittent `daily_pv.h5` not found during factor execution.
