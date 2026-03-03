# TODO / Fix / 优化清单

更新时间：2026-03-04

## 背景

在 relay / 常规运行日志中，部分因子候选会在 `factor_calculate` 因表达式语法/格式问题失败。
这不是系统崩溃，但属于可规避的表达式格式问题。

在离线回测中，也发现过因子池 JSON 内 `factor_name` 重名导致回测实际使用因子数少于请求数量的问题。

## 已修复（表达式稳定性）

- [x] 统一算术表达式风格（拒绝“解析器内部函数写法”）
  - 拒绝 `DIVIDE`/`SUBTRACT`/`MULTIPLY`/`ADD` 等 parser 内部函数名写法。
  - 强制使用标准算术操作符：`+`、`-`、`*`、`/`。
  - 示例：
    - 错：`DIVIDE(TS_SUM($return * $volume, 10), TS_STD($volume, 10) + 1e-8)`
    - 对：`TS_SUM($return * $volume, 10) / (TS_STD($volume, 10) + 1e-8)`

- [x] 强制 `$` 前缀变量一致性
  - 拒绝在同一表达式中混用 `$volume` 与 `volume`（或 `$return` 与 `return`）。
  - 要求使用统一的 `$` 前缀列（例如：`$open/$close/$high/$low/$volume/$return`）。

## 实现清单（对应落点）

- [x] 在最终因子代码生成前增加表达式风格校验（`FactorRegulator.validate_expression_style`）。
- [x] 在 proposal/construct 阶段增加严格检查：拒绝 parser-function 形式、拒绝 `$var` 与 `var` 混用。
- [x] 增加失败重试的反馈模板：明确要求 operator 形式与 `$` 前缀变量。
- [x] 增加单元测试覆盖：
  - parser-function 名称拒绝
  - 混用 `$` 前缀检测
  - 典型合法表达式样例

## 代码触点（参考）

- `quantaalpha/factors/regulator/factor_regulator.py`
- `quantaalpha/factors/proposal.py`
- `quantaalpha/factors/prompts/prompts.yaml`
- `quantaalpha/factors/coder/qa_prompts.yaml`
- `tests/factors/test_expression_style_validation.py`

## 验收标准

1. 因子执行日志中不再出现由 `DIVIDE/SUBTRACT/MULTIPLY/ADD` 触发的新增 `SyntaxError`。
2. 不再出现由 `$var` 与 `var` 混用导致的新增语法失败。
3. 与表达式语法相关的 `d/evolving feedback` false 决策显著下降。

## 待确认 / 待修复（回测一致性）

- [x] Backtest: `factor_name` 重名不再覆盖列（自动改名保留全部）
  - 现象：`success 350` 但 `Result DataFrame: (727818, 340)`（log: `log/backtest_manual/backtest_20260303_115808.log`）
  - 处理口径：A) 保留全部。对重复 name 自动重命名（`<factor_name>__<factor_id>`），保证列唯一。
  - 落点：
    - `quantaalpha/backtest/custom_factor_calculator.py`：`calculate_factors_batch()` 内部统一通过唯一 `factor_key` 写入结果列。
    - 单测：`tests/backtest/test_custom_factor_calculator_duplicate_factor_name.py`

- [x] Backtest: 修复 cache index 不一致导致 `pd.DataFrame(results)` 触发巨大 union index（内存暴涨）
  - 现象：MD5 cache 仅按表达式哈希命中；不同 run 的市场/区间可能导致缓存因子 index 不同，`DataFrame(results)` 会构造 union index（峰值 RSS 上升）。
  - 处理口径：以当前回测的 `target_index` 为准，对 cache 命中结果先对齐并强制 `DataFrame(..., index=target_index)` 输出，避免 union index 扩张。
  - 落点：`quantaalpha/backtest/custom_factor_calculator.py`：`calculate_factors_batch()`（`target_index` + 强制输出 index；注释含 “blow up memory by constructing a huge union index”）。

- [ ] Backtest: `CustomFactorCalculator.calculate_factors_batch()` 内置硬编码超时（`signal.alarm(120)`）
  - 现象：慢但有效的因子可能被判定为 `timeout` 而丢弃；不同运行方式（主线程 vs 子线程）行为不一致。
  - 根因：超时逻辑依赖 `signal.SIGALRM`，在非主线程会抛 `ValueError` 并被忽略；不同平台/环境可用性不同。
  - 影响：同一因子库在不同机器/执行方式下可能产生不同的“最终因子集合”（影响回测可复现性）。
  - 建议：将超时改为可配置（例如 env `QUANTA_FACTOR_COMPUTE_TIMEOUT_S`）或默认关闭，仅在诊断/卡死排查时启用。
  - 代码触点：`quantaalpha/backtest/custom_factor_calculator.py`

- [ ] 交互回测流程：优先在 `scripts/run_backtest_safe.sh` 内自动接入 Zoo 路径，不依赖 `run.sh` 和手动 `export`
  - 目标：用户后续可直接用 `run_backtest_safe.sh` 完成回测与去重相关配置，无需手动声明 `FACTOR_CoSTEER_FACTOR_ZOO_PATH`。
  - 现状痛点：当前 Zoo 路径通常在 `run.sh --zoo-dedup` 或手动 `export` 下生效，离线回测脚本链路可用性不够顺滑。
  - 建议方向：
    - 在 `run_backtest_safe.sh` 增加“使用 merged zoo（ast/norm）”交互项或参数；
    - 自动解析最近一次合并产物（如 `data/factorlib/merged/*_zoo*.csv`）并注入环境；
    - 在运行摘要中明确打印最终生效的 Zoo CSV 路径。
  - 代码触点：`scripts/run_backtest_safe.sh`、`scripts/run_factors.sh`（可选联动）。
