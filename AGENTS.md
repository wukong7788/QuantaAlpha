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
- Default `STEP_N=3`
- Can send Telegram notification on finish

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
