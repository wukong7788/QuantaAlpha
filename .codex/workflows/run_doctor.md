# Run Doctor Workflow

Goal: Generate one markdown report for the current `run.sh` experiment status and risk diagnosis.

## What the report must include

1. Process health
- Whether `run.sh` / `quantaalpha mine` process is active.
- If active, include PID, elapsed time, and command summary.

2. Current progress position
- Current `phase` / `round`.
- Latest task directory (`original_*` / `mutation_*` / `crossover_*`).
- Current step and completed steps.

3. Factor generation quality
- Total trajectories, generated factors, unique factors.
- Feedback quality summary (`true/false`, false ratio, reason breakdown).

4. Critical errors and research impact
- System-level error signals (JSON parsing failures, recursion errors, expression parse failures).
- Execution-log exceptions / tracebacks.
- Impact level assessment: `OK` / `MEDIUM` / `HIGH` / `CRITICAL`.

5. Storage and disk status
- Current run data usage size (at least include log root; when available include workspace/cache paths for current experiment).
- Remaining disk free space and free ratio.

## Entry command

```bash
./scripts/run_doctor.sh
```

## Notes

- Default output is one-shot markdown report (`--doctor --markdown`).
- Add `--experiment-id <id>` or `--log-root <path>` to bind to a specific run lineage.
- Add `--watch 8` only when continuous refresh is required.
