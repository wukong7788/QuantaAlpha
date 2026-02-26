# AGENTS.md

This file records practical project knowledge for future Codex/agent runs in this repo.

## Project Summary

QuantaAlpha is an LLM-driven factor mining framework:

1. Generate hypothesis from direction
2. Construct factor tasks/expressions
3. Implement factor code and compute values from `daily_pv.h5`
4. Backtest
5. Feedback and evolve

Core code paths:

- Pipeline: `quantaalpha/pipeline/`
- Factor coding/execution: `quantaalpha/factors/coder/`
- Factor library: `quantaalpha/factors/library.py`
- Backtest: `quantaalpha/backtest/`
- Web UI: `frontend-v2/`

## Specs Sync Policy

- Contract/spec source: `SPECS.md` (project behavior contract, not just notes).
- When to update `SPECS.md`:
  - CLI/script options change (add/remove/rename/default behavior), e.g. `run.sh`, `scripts/run_backtest_safe.sh`.
  - Workflow semantics change (resume/relay logic, cache policy, filtering/ranking rules).
  - Output contract changes (file naming, API fields, metadata schema).
- Rule of thumb:
  - If a user or downstream tool can observe changed behavior, update `SPECS.md` in the same PR/commit.
  - If change is internal-only refactor with no behavior change, `SPECS.md` update is optional.
- Recurring pitfall (must avoid):
  - Code logic gets updated but docs keep old semantics. This is treated as an incomplete change.
- Mandatory doc-sync gate after behavior changes:
  - Update `SPECS.md` plus user-facing docs (`README.md`/`README_CN.md`/`docs/PAPER_REPRODUCTION_GUIDE.md`) and `CHANGELOG.md` in the same task.
  - Run a keyword grep for changed flags/terms (e.g. `--relay`, `--resume`, `BOB`, `low-disk`) to catch stale wording.
  - If intentionally skipping doc updates, explicitly state why (internal-only change) in the final summary.

## Local Runtime (current)

Use `uv + .venv` (no conda required).

### Setup

```bash
cd /Users/ron/Documents/QuantaAlpha
uv venv --python 3.12 .venv
uv pip install -e .
```

### Main run

```bash
./run.sh "价量因子挖掘" "suffix_name"
```

### Fast smoke run

```bash
./minirun.sh
```

- Uses `configs/experiment_smoke.yaml`
- Default `STEP_N=5` (full 5-step)
- Can send Telegram notification on finish

## Interactive Script Index (3-5 steps only)

Scope: human-facing entry scripts used in day-to-day operation.

### 1) Main experiment: `run.sh`

1. Confirm `.env` + `.venv` are ready.
2. Run `./run.sh "方向" "suffix"` (low-disk is ON by default; optional flags: `--no-low-disk`, `--relay`, `--resume`).
3. Check printed `EXPERIMENT_ID`, `WORKSPACE_PATH`, and log output.
4. Relay/resume semantics (`--relay` and `--resume` are mutually exclusive): first relay leg uses chunk (`QUANTA_RELAY_CHUNK_ROUNDS`, default 5), later leg auto-finishes to `max_rounds`; `--resume` requires existing `evolution_state.json` and fails fast if missing.
5. Naming safety: for a new run, change both `EXPERIMENT_ID` and library suffix together; reusing suffix appends/overwrites in the same `all_factors_library_<suffix>.json`.

### 2) Smoke pipeline: `minirun.sh`

1. Confirm `.env` and required `daily_pv.h5` files exist.
2. Run `./minirun.sh` (optional: `STEP_N=5 ./minirun.sh`).
3. Read manifest under `log/minirun_manifests/` for artifact paths.
4. Use Telegram summary for quick success/failure signal.

### 3) Offline/safe backtest: `scripts/run_backtest_safe.sh`

1. Start wizard with `./scripts/run_backtest_safe.sh --interactive` (or pass `--library ...` directly).
2. In wizard step 1, choose one concrete experiment library / `BOB` / `VIEW` (horizontal compare).
3. Script applies defaults automatically (BOB defaults: `grade=sa`, `top=50`) and starts without extra confirm.
4. Check run summary and logs under `log/backtest_manual/` (BOB `auto` metric resolves one global metric before ranking and writes `metric_resolved`; temp files are cleaned up on normal/early exit).

### 4) Safe cleanup: `scripts/safe_cleanup.sh` (wrapper of `scripts/safe_cleanup.py`)

1. Run without args for interactive wizard, or pass explicit cleanup flags.
2. Start with dry-run (default) and review deletion plan.
3. Execute with `--apply --yes` only after confirming reclaim targets.
4. Recheck workspace/pickle/log directories after cleanup.

### 5) Frontend stack startup: `frontend-v2/start.sh`

1. Run `./frontend-v2/start.sh`.
2. Script auto-checks Node, `.venv`, backend deps, and `.env`.
3. Script reuses healthy services or starts backend (`8000`) + frontend (`3000`).
4. Open `http://localhost:3000`; use `Ctrl+C` to stop processes started by this script.

### 6) Result comparison: `scripts/view_results.sh`

1. Run `./scripts/view_results.sh` (interactive) or pass `--pick 1,2,3`.
2. Select experiment snapshots and/or BOB entries for side-by-side comparison.
3. Script compares existing `*_backtest_metrics.json` directly (no recompute).
4. Check built-in overwrite risk warning (`legacy` vs `timestamped` naming).

## Environment Variables That Matter

From root `.env`:

- `QLIB_DATA_DIR`
- `DATA_RESULTS_DIR`
- `OPENAI_API_KEY`, `OPENAI_BASE_URL`
- `CHAT_MODEL`, `REASONING_MODEL`
- `EMBEDDING_MODEL` (+ embedding key/base url when needed)
- `FACTOR_CoSTEER_DATA_FOLDER`
- `FACTOR_CoSTEER_DATA_FOLDER_DEBUG`

Optional:

- `SESSION_DUMP_TXT=true` to output text snapshots besides pickle session dumps
- `EXPERIMENT_ID=shared` to reuse workspace/cache paths across runs

## Data Requirements

Required factor source files:

- `git_ignore_folder/factor_implementation_source_data/daily_pv.h5`
- `git_ignore_folder/factor_implementation_source_data_debug/daily_pv.h5`

Qlib data path must contain:

- `calendars/`
- `features/`
- `instruments/`

## Logging and Session Files

- Log root: `log/<timestamp>/`
- Session snapshots: `log/<timestamp>/__session__/...`
- Snapshots are pickle by default.
- If `SESSION_DUMP_TXT=true`, `.txt` summaries are also written next to snapshot files.
- Timestamp default is Asia/Shanghai unless `LOG_TRACE_PATH` is explicitly set.

## Backtest Output Convention (important)

- Backtest result files now include factor count + Beijing timestamp to avoid overwrite:
  - `<name>_n<num_factors>_<YYYYMMDD_HHMMSS>_backtest_metrics.json`
  - `<name>_n<num_factors>_<YYYYMMDD_HHMMSS>_cumulative_excess.csv`
- Example:
  - `all_factors_library_paper_reproduction_ds_n50_20260225_233015_backtest_metrics.json`
- Output directory is still controlled by `configs/backtest*.yaml -> experiment.output_dir`
  (currently `data/results/backtest_v2_results`).

## Safe Backtest Script (interactive/offline)

- Script: `scripts/run_backtest_safe.sh`
- New key option:
  - `--max-factors <N|all|default>`
  - `N`: use top N custom factors
  - `all`: set `factor_source.custom.max_factors=null`
  - `default`: keep config value (`backtest_limited.yaml` is typically 50)
- Script behavior:
  - generates a temporary config (when override is set),
  - writes full run logs under `log/backtest_manual/`,
  - writes PID metadata for interruption diagnostics.

## Frontend Offline Backtest Result Loading

- Backend APIs:
  - `GET /api/v1/backtest-offline/runs`
  - `GET /api/v1/backtest-offline/latest` (optional `metricsFile=...`)
- Frontend backtest page supports:
  - load latest result by default,
  - select a specific offline run from dropdown and load it.

## Factor Library and Duplicate Behavior

Factor library output:

- `data/factorlib/all_factors_library*.json`

Notes:

- Direction is recorded in metadata, but same direction is not globally auto-skipped.
- Factor IDs are based on `md5(factor_name + factor_expression)` in library manager.
- Repeated runs can still regenerate candidates; backtest side may reuse H5/MD5 cache.

## Known Pitfalls and Fixes Applied

1. macOS data-link issue (`daily_pv.h5` not found)
   - Fixed in `quantaalpha/core/experiment.py` by enabling symlink on Darwin.

2. `run.sh`/`frontend-v2/start.sh` conda dependency
   - Updated to prefer `.venv` and `uv`.

3. LightGBM backtest on macOS
   - Requires `libomp` (`brew install libomp`).

4. `minirun.sh` stability
   - End-time/unbound handling fixed.

## Telegram Notification

Used in local automation:

- `TG_BOT_TOKEN`
- `TG_CHAT_ID`
- Codex notify script: `~/.codex/scripts/notify-telegram.sh`

## Recommended Workflow

1. `./minirun.sh` (sanity)
2. `STEP_N=5 ./minirun.sh` (include later steps)
3. Full run with suffix:
   - `./run.sh "价量因子挖掘" "pv_v1_ds"`
4. Backtest selected library JSON
