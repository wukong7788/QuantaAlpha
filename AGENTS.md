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

## Terminology (Round/Direction/Task/Step)

These terms are easy to mix up during paper reproduction and performance optimization. Use this hierarchy:

1. Experiment: one `run.sh` execution (bound to an `EXPERIMENT_ID`).
2. Direction: one planned exploration direction text (count = `planning.num_directions`).
3. Round + Phase: controller **phase-round** (round increments after finishing one phase), not “epoch=original+mutation+crossover”.
4. Task: one branch task identified by `(phase, round_idx, direction_id)` and stored under `{phase}_{round}_{direction}` log dir.
5. Step: the fixed 5-step loop inside a task: `factor_propose -> factor_construct -> factor_calculate -> factor_backtest -> feedback`.
6. Attempt: empty-factor retry count for a task (count = `evolution.max_empty_retries` + 1 attempts total).

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

## Agent Execution Principles

- Do not add compatibility aliases by default. Avoid duplicated entry scripts/docs that create long-term confusion.
- Prefer one canonical entrypoint and one canonical documentation path for each workflow.
- Use first-principles reasoning: keep the simplest structure that satisfies the real user goal.
- If requirements are ambiguous, ask the user for clarification before implementing structural changes.
- If the user is brainstorming or "just want to discuss options", provide a concrete proposal first and do not start modifying code/files until the user explicitly asks to implement.
- Process lifetime guardrail: only add `timeout` to short-lived diagnostic/probing commands. Do not apply `timeout` by default to long-running experiment/backtest/data jobs unless the user explicitly requests a hard stop.

## Documentation Hygiene (non-spec docs)

- `SPECS.md` is the contract/spec source and must be kept in sync (see "Specs Sync Policy" above).
- For other docs (e.g. `docs/*.md`, `CHANGELOG.md`, `README*.md`):
  - Do **not** blindly append/stack notes ("堆砌") if the new content is large.
  - First propose a clearer structure outline (sections + ordering) to keep the doc readable.
  - Apply the restructure **only after** the user explicitly agrees to the proposed new structure.

### Changelog Policy (`CHANGELOG.md`)

- Structure: one section per date (`## YYYY-MM-DD`).
- Subsections (include only if non-empty; keep order):
  - `### Highlights` (max 3 lines)
  - `### Added` / `### Fixed` / `### Performance` / `### Changed` / `### Removed`
  - Optional: `### Docs` / `### Internal`
- Every bullet must start with searchable tags:
  - Format: `[area][impact]` (optionally add severity: `[P0|P1|P2]`)
  - Suggested areas: `core`, `pipeline`, `factors`, `backtest`, `llm`, `scripts`, `frontend`, `configs`, `docs`, `tests`
  - Suggested impacts: `feature`, `behavior`, `output`, `reliability`, `perf`, `mem`, `docs`, `internal`
- `### Performance` / `mem` entries must include measurement context when applicable:
  - dataset/market/date range, factor count, and metric name (e.g. wall time, peak RSS)
  - harness/tool used (e.g. `scripts/abtest_backtest_memory.py`)
- Default/semantic changes must be explicit:
  - write `A -> B` and name the flag/env/config key(s).
- Keep entries scannable:
  - 1-line summary first; add indented sub-bullets only for file paths, keys/flags, tests, or A/B results.

## Local Runtime (current)

Use `uv + .venv` (no conda required).

Environment policy:
- Use `uv` as the primary environment/package manager.
- Prefer the project-local interpreter and tools under `./.venv` first.
- Avoid system/global Python or mixed environments unless explicitly requested.

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
2. Run `./run.sh "方向" "suffix"` (low-disk ON by default; see flag table below).
3. Check printed `EXPERIMENT_ID`, `WORKSPACE_PATH`, and log output.
4. Relay/resume semantics (`--relay` and `--resume` are mutually exclusive): first relay leg uses chunk (`QUANTA_RELAY_CHUNK_ROUNDS`, default follows `evolution.relay_chunk_rounds`, current main config is 6), later leg auto-finishes to `max_rounds`; `--resume` requires existing `evolution_state.json` and fails fast if missing.
5. Round terminology: `evolution.max_rounds` uses **phase-round** (each phase completion increments `round`), not “epoch=original+mutation+crossover”.
6. Fine-grained resume: on restart via `--relay/--resume`, each task directory will resume from the latest `__session__` snapshot and continue from the next unfinished step (within the 5-step loop). If the task enters an “empty-factor retry attempt”, it will re-run fresh (not resume the previous attempt).
7. Naming safety: change both `EXPERIMENT_ID` and suffix for a new run; reusing suffix appends to same `all_factors_library_<suffix>.json`.

| Flag | Default | Description |
|------|---------|-------------|
| `--low-disk` | ON | Disable pickle cache, compress parquet, purge temp after backtest |
| `--no-low-disk` | — | Disable low-disk mode explicitly |
| `--relay` | — | Run N rounds then exit; re-run same command to continue |
| `--resume` | — | Continue directly to `max_rounds` from saved state |
| `--zoo-dedup` | — | Skip expressions in `factor_zoo.csv`; auto-update zoo after run |
| `--rounds N` | — | Override `evolution.max_rounds` without editing yaml (temp config) |

Env: `QUANTA_RELAY_CHUNK_ROUNDS` (overrides config value), `QUANTA_FACTOR_ZOO_PATH`, `EXPERIMENT_ID`.


### 2) Smoke pipeline: `minirun.sh`

1. Confirm `.env` and required `daily_pv.h5` files exist.
2. Run `./minirun.sh` with optional flags: `--low-disk`, `--zoo-dedup`.
   - Example: `./minirun.sh --low-disk --zoo-dedup "价量因子测试" "smoke_test"`
3. Read manifest under `log/minirun_manifests/` for artifact paths.
4. Use Telegram summary for quick success/failure signal.

### 3) Offline/safe backtest: `scripts/run_backtest_safe.sh`

1. Start wizard with `./scripts/run_backtest_safe.sh --interactive` (or pass `--library ...` directly).
2. In wizard step 1, choose one concrete experiment library / `BOB` / `VIEW` (horizontal compare) / `FILTER` (filter-only preview, no backtest).
3. Script applies defaults automatically (BOB defaults: `grade=sa`, `top=50`) and starts without extra confirm.
4. Check run summary and logs under `log/backtest_manual/` (BOB `auto` metric resolves one global metric before ranking and writes `metric_resolved`; FILTER mode writes preview library/report under `data/factorlib/selected/`; temp files are cleaned up on normal/early exit).

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

### 7) Run progress doctor (terminal entry): `scripts/run_doctor.sh`

1. Run `./scripts/run_doctor.sh` for one-shot snapshot (auto-detect latest run log).
2. Run `./scripts/run_doctor.sh --watch 8` for live refresh.
3. Run `./scripts/run_doctor.sh` for one-shot progress + log diagnostics Markdown report.
4. Use `./scripts/run_doctor.sh --experiment-id <id>` to bind to one experiment lineage.
5. Output includes active process, phase/round/direction, current step, generated factor summary, and doctor diagnostics.

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

- `SESSION_DUMP_TXT=true` — also write text snapshots beside pickle session dumps
- `EXPERIMENT_ID=shared` — reuse workspace/cache paths across runs
- `QUANTA_RELAY_CHUNK_ROUNDS=6` — override first relay leg chunk size
- `QUANTA_FACTOR_ZOO_PATH=...` — override zoo CSV path (used by `--zoo-dedup`)
- `FACTOR_CoSTEER_FACTOR_ZOO_PATH=...` — set directly if bypassing `run.sh` (matches `FactorCoSTEERSettings` env prefix)

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
- `__session__` snapshots are used for task-level step resume in relay/resume mode (continue from the next unfinished step after a restart).
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
  - `default`: keep config value (default base config is `configs/backtest.yaml`)
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

## Factor Library, Zoo, and Duplicate Behavior

Factor library output:
- `data/factorlib/all_factors_library_<suffix>.json` — per-experiment factor results

**Factor Zoo (cross-run dedup):**
- `data/factorlib/factor_zoo.json` — full metadata (inspection/merge)
- `data/factorlib/factor_zoo.csv` — CSV used by `FactorRegulator` via `pd.read_csv()` for AST dedup
  - This is what `FACTOR_CoSTEER_FACTOR_ZOO_PATH` must point to.

Managing the zoo:
```bash
.venv/bin/python scripts/update_factor_zoo.py build    # full rebuild from all factorlib files
.venv/bin/python scripts/update_factor_zoo.py update   # incremental: add new factors from latest run
.venv/bin/python scripts/update_factor_zoo.py status   # show zoo stats
```

- Factor IDs: `md5(factor_name + factor_expression)` in library manager.
- Zoo IDs: `md5(normalized_expression)` with prefix `zoo_`.
- `--zoo-dedup` in `run.sh` auto-calls `update` after experiment finishes.
- `factor_zoo.csv` columns: `factor_name`, `factor_expression`.

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

1. **冒烟验证**：`./minirun.sh --low-disk "价量因子测试" "smoke_test"`
2. **安全模式（11 轮）**：`./run.sh --rounds 11 --low-disk --relay --zoo-dedup "价量因子挖掘" "r3"`
3. **土豪模式（23 轮）**：  
   `./scripts/safe_cleanup.sh` → `EXPERIMENT_ID="paper_repro_23r" ./run.sh --rounds 23 --low-disk --relay --zoo-dedup "价量因子挖掘" "paper_repro_23r"`
4. **独立回测**：`./scripts/run_backtest_safe.sh --interactive`
