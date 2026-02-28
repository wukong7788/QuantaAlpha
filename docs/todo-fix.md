# TODO / Fix / 优化清单（含 A/B 结论）

更新时间：2026-02-28

## 背景

在 relay / 常规运行日志中，部分因子候选会在 `factor_calculate` 因表达式语法/格式问题失败。
这不是系统崩溃，但属于可规避的表达式格式问题。

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

---

## 已落地的优化（做了什么 + 结果是什么）

说明：
- 这里的“已落地”指仓库里已经有代码/配置支持（不代表都已 A/B 验证）。
- A/B 结果只引用已在 `docs/performance_optimization_cn.md` 记录的跑数。

### 已 A/B 验证（有明确正/负结果）

1. **协议层强约束 JSON（3.13）**
   - 开关：`configs/experiment.yaml -> llm.json_mode_strict` / `llm.json_mode_response_format`
   - 结果：正优化（2026-02-28，`STEP_N=3`：`363.289s -> 334.619s`，差 `-28.670s` / `-7.9%`）
   - 结论：**保留并默认开启**
   - 参考：`docs/performance_optimization_cn.md` 的 **5.3 opt2**

2. **Pre-calc cheap gate + exact 去重（3.11 + 3.15，绑在一起）**
   - 开关：`quality_gate.cheap_filter_enabled` / `quality_gate.cheap_filter_require_acceptable`
   - 结果：负优化（2026-02-28，`STEP_N=3`：`277.771s -> 415.958s`，差 `+138.187s` / `+49.8%`）
   - 结论：**默认关闭**（仅建议在包含 backtest 的用例上另做 A/B，再决定是否开启）
   - 参考：`docs/performance_optimization_cn.md` 的 **5.2 opt1**

3. **上下文瘦身 / 历史窗口（3.2）**
   - 开关：`quantaalpha/factors/proposal.py -> DEFAULT_HISTORY_LIMIT`（需改代码；当前主分支固定为 4）
   - 结果：本用例下未提速（2026-02-28，`STEP_N=3`：median `119.433s -> 123.209s`，差 `+3.776s` / `+3.16%`；两组 JSON 失败计数均为 0）
   - 结论：暂不作为“提速优化”成立；已恢复原始固定窗口行为（不做运行时覆盖）；若目标是降 token/费用，**建议单独分支改代码再复测**
   - 参考：`docs/performance_optimization_cn.md` 的 **5.4 opt3**

4. **温度分层（json vs freeform）（3.18）**
   - 开关：`llm.json_mode_temperature` / `llm.freeform_temperature`
   - 结果：本用例下耗时变差（2026-02-28，`STEP_N=3`：median `169.201s -> 193.420s`，差 `+24.219s` / `+14.31%`；两组 JSON 失败计数均为 0）
   - 结论：暂不作为“提速优化”成立；**默认不启用分层**；是否保留需在“JSON 不稳定/网络抖动明显”的用例上复测
   - 参考：`docs/performance_optimization_cn.md` 的 **5.5 opt4**

5. **第三轮：回测峰值内存优化尝试**
   - 结果：负优化（峰值 RSS 上升），已回滚
   - 结论：**不保留该轮优化代码**（保留 A/B 工具用于后续验证）
   - 参考：`docs/performance_optimization_cn.md` 的 **10.3 A/B Test**

6. **缓存格式升级（3.6，Parquet + ZSTD）**
   - 开关：`configs/backtest*.yaml -> llm.cache_format/cache_compression/cache_dual_write_pkl`
   - 结果：空间占用显著下降（无需每次都做 A/B；已有抽样体积对照）
   - 结论：**保留并默认开启**（不改精度/逻辑时风险较低；读失败可回退到 `*.pkl`）
   - 参考：`docs/performance_optimization_cn.md` 的 **5.1 3.6**

7. **分支止损预算（3.10）**
   - 开关：`quality_gate.max_construct_failures_per_branch` / `quality_gate.max_json_parse_failures_per_branch` / `evolution.max_empty_retries`
   - 结果：负优化（2026-02-28，`STEP_N=3`：median `247.684s -> 274.327s`，差 `+26.643s` / `+10.76%`）
   - 结论：**默认不收紧**（保持 `2 / 2 / 1`）；若复测建议切到更长链路并补充质量指标
   - 参考：`docs/performance_optimization_cn.md` 的 **5.6 opt5**

### 已落地但未系统性 A/B（先标清默认策略与风险）

- **3.19 网络稳态（timeout/backoff/jitter/failover）**：已落地；默认开启；风险低-中（多在网络不稳时影响明显）。
- **3.5 受控并行**：已落地；默认关闭；风险中（时序/外部服务导致漂移，且要看 16GB 峰值内存）。
- **3.9 warm start（复用 trajectory pool）**：已支持；默认关闭（`fresh_start=true`）；风险高（搜索路径变）。
- **3.7 动态预算 / 3.4 多保真筛选**：未落地（仅文档规划）。

---

## 待优化 / 待 A/B（按建议顺序排列）

说明：
- 已在“已 A/B 验证”中明确判定为负优化且默认关闭/回滚的项（如 3.18、3.11+3.15、3.2、3.10）不再放入本待办列表。

1. **网络稳态（3.19）**：主看长尾卡顿（p90/p99 step 耗时）是否下降；稳定网络下可能不显著。
2. **受控并行（3.5）**：主看吞吐（tasks/hour）提升 vs 稳定性（OOM/失败率/峰值内存/交换）。
3. **warm start（3.9）**：对照 `fresh_start=true/false`，主看“收敛速度 vs 多样性”。
4. **动态预算（3.7）**：未落地（需要先定义预算/分配策略与质量护栏）。
5. **多保真筛选（3.4）**：未落地（需要先定义保真层级与误杀护栏）。
