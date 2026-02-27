# TODO Fix List

Updated: 2026-02-26

## Background

During relay run logs, some factor candidates failed at `factor_calculate` due to expression syntax issues.
These are not system crashes, but avoidable expression-format problems.

## Fix Status

- [x] Normalize arithmetic expression style
  - Reject parser-internal function names such as `DIVIDE`, `SUBTRACT`, `MULTIPLY`, `ADD`.
  - Enforce standard arithmetic operators directly: `+`, `-`, `*`, `/`.
  - Example:
    - Bad: `DIVIDE(TS_SUM($return * $volume, 10), TS_STD($volume, 10) + 1e-8)`
    - Good: `TS_SUM($return * $volume, 10) / (TS_STD($volume, 10) + 1e-8)`

- [x] Enforce consistent variable naming with `$` prefix
  - Reject mixed `$volume` and `volume` (or `$return` and `return`) in one expression.
  - Require consistent `$`-prefixed columns (for example: `$open`, `$close`, `$high`, `$low`, `$volume`, `$return`).

## Implementation Checklist

- [x] Add expression style validation before final factor code generation (`FactorRegulator.validate_expression_style`).
- [x] Add strict check in proposal/construct stage to reject parser-function forms and mixed/non-prefixed base variables.
- [x] Add retry feedback template that explicitly requires operator form and `$`-prefixed variables.
- [x] Add unit tests for:
  - parser-function names rejection
  - mixed variable prefix detection
  - accepted canonical expression examples

## Code Touchpoints

- `quantaalpha/factors/regulator/factor_regulator.py`
- `quantaalpha/factors/proposal.py`
- `quantaalpha/factors/prompts/prompts.yaml`
- `quantaalpha/factors/coder/qa_prompts.yaml`
- `tests/factors/test_expression_style_validation.py`

## Acceptance Criteria

1. No new `SyntaxError` caused by `DIVIDE/SUBTRACT/MULTIPLY/ADD` in factor execution logs.
2. No new syntax failures caused by mixed `$var` and `var`.
3. `d/evolving feedback` false decisions related to expression syntax are significantly reduced.
