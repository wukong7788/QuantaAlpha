# QuantaAlpha 性能优化执行看板（按结果归档）

更新时间：2026-03-02  
适用范围：`run.sh` / `run_doctor` / 演化流程（original -> mutation -> crossover）/ 独立回测（`run_backtest.py`）

---

## 1. 文档目的与当前结论

本文件只回答 3 个问题：

1. 已经做了哪些优化。
2. 这些优化里哪些是正优化，哪些是负优化。
3. 还没做的优化里，下一步先做什么收益更高。

当前总结：

- **默认保留**：协议层强约束 JSON（正优化）、表达式风格稳定性约束（稳定性修复）。
- **默认回滚/关闭**：cheap gate、温度分层、收紧止损、回测“降内存”改造（均在当前验证口径下为负优化）。
- **待下一轮重点**：受控并行、网络稳态、warm-start。

---

## 2. 统一评估口径（通过门槛）

每个优化项统一按以下维度评估：

- 速度：`elapsed_s`、阶段耗时中位数/p90、吞吐（tasks/hour）。
- 内存：`max_rss_mb`、swap 行为。
- 质量：`IC/ICIR/Rank IC/Rank ICIR`、策略指标（年化/IR/回撤/Calmar）。
- 稳定性：JSON 失败率、空分支重试、异常率。

通过条件：

- 若目标是提速：速度提升且质量不劣化。
- 若目标是降内存：内存下降且质量不劣化。
- 任一目标出现稳定反向结果，即判定为负优化。

---

## 3. 已做事项总览（状态表）

| ID | 事项 | 状态 | 核心证据 | 当前决策 |
|---|---|---|---|---|
| O2 | 协议层强约束 JSON（`response_format=json_object`） | 正优化 | `STEP_N=3`：`363.289s -> 334.619s`（-7.9%） | 默认开启 |
| O6 | Parquet + ZSTD 缓存格式 | 正优化（空间） | 抽样体积 `0.35~0.54x` pkl | 默认保留 |
| O1 | cheap gate + duplicate_exact | 负优化 | `277.771s -> 415.958s`（+49.8%） | 默认关闭 |
| O3 | 上下文历史窗口改动 | 负优化（本用例） | `119.433s -> 123.209s`（+3.16%） | 恢复原默认 |
| O4 | 温度分层（json/freeform） | 负优化 | `169.201s -> 193.420s`（+14.31%） | 默认不启用 |
| O5 | 收紧分支止损预算 | 负优化 | `247.684s -> 274.327s`（+10.76%） | 保持宽松默认 |
| M1 | 回测“降内存”改造（float32 + 预分配 + memmap 等） | 负优化 | 100 因子两轮均 RSS 上升，且出现指标漂移 | 已回滚到 baseline |
| S1 | 表达式风格稳定性约束（operator + `$` 前缀一致性） | 已落地（稳定性修复） | 单测通过；construct 阶段已强校验 | 默认开启 |
| N1 | 网络稳态（timeout/backoff/jitter） | 已落地，待专项 A/B | `request_timeout_s/retry_backoff/retry_jitter/retry_max_wait_seconds` 已接入运行时 | 默认开启 |
| N2 | endpoint failover | 能力已落地 | `failover_base_urls` 支持链式切换 | 默认关闭（空列表） |
| P1 | 受控并行（worker cap） | 已落地，待专项 A/B | `max_parallel_workers` + `_run_tasks_parallel` | 默认关闭 |
| W1 | warm-start（trajectory pool 复用） | 已落地，待专项 A/B | `fresh_start=false` 可复用；relay 模式会自动覆盖为 `false` | 默认关闭（relay 例外） |

---

## 4. 已做且验证为正优化（按收益排序）

### 4.1 O2 协议层强约束 JSON

- 目标：减少 construct 阶段格式失败和无效重试。
- 配置：`llm.json_mode_strict=true`、`llm.json_mode_response_format=json_object`。
- A/B（`STEP_N=3`）：
  - baseline：`363.289s`
  - optimized：`334.619s`
  - 结果：`-7.9%`。
- 决策：**保留并作为默认**。

### 4.2 O6 Parquet + ZSTD 缓存格式

- 目标：降低缓存磁盘占用。
- 结果：抽样 5 个缓存文件，Parquet+ZSTD 体积约为 pkl 的 `0.35~0.54`。
- 边界：这是“存储收益”，不是直接的端到端提速结论。
- 决策：**保留**，并继续用 A/B 监控读写性能。

---

## 5. 已做但验证为负优化（按影响排序）

### 5.1 M1 回测“降内存”改造（第三轮）

改造内容（已回滚）：

- 因子链路偏向 `float32`。
- 批处理预分配矩阵 + `memmap`。
- `runner` 中 rank/拼接路径向量化改造。

复测结果（100 因子，`num_threads=1`，`n_jobs=2`，`--skip-uncached`）：

- Round-1：
  - baseline：`643.069s` / `8872.4MB`
  - optimized：`193.069s` / `9928.6MB`
- Round-2：
  - baseline：`512.841s` / `9007.3MB`
  - optimized：`188.057s` / `10519.7MB`

关键结论：

- 速度显著提升，但内存稳定上升。
- Round-2 内存变化：`+1512.4MB`（`+16.79%`）。
- 同时出现稳定指标漂移（非仅浮点尾差）：
  - `IC +0.002095`
  - `ICIR +0.005177`
  - `Rank IC +0.001599`
  - `Rank ICIR +0.003267`
  - `annualized_return +0.007097`
  - `information_ratio +0.106872`
  - `max_drawdown +0.043656`
  - `calmar_ratio +0.060747`
- 200 因子在 16GB 机器上出现 kill / 高 swap，不具备稳定性。

决策：**判定负优化，已恢复 baseline 原样**。

### 5.2 O1 cheap gate + duplicate_exact（`STEP_N=3`）

- baseline：`277.771s`
- optimized：`415.958s`
- 变化：`+49.8%`（变慢）
- 决策：**默认关闭 `quality_gate.cheap_filter_enabled`**。

### 5.3 O4 温度分层（`STEP_N=3`）

- baseline：`169.201s`
- optimized：`193.420s`
- 变化：`+14.31%`
- 决策：**默认不启用温度分层**。

### 5.4 O5 收紧止损预算（`STEP_N=3`）

- baseline：`247.684s`
- optimized：`274.327s`
- 变化：`+10.76%`
- 决策：**保持 `2/2/1`，不收紧到 `1/1/0`**。
- 说明（`2/2/1` 对应三段分支止损预算）：
  - `max_construct_failures_per_branch / max_json_parse_failures_per_branch / max_empty_retries`
  - 当前默认：`2/2/1`（分别允许 2 次构造失败、2 次 JSON 解析失败、1 次空分支重试）
  - 收紧方案：`1/1/0`（更早止损，失败分支更快终止）
  - 配置位置：`configs/experiment.yaml`（`quality_gate.*` 与 `evolution.max_empty_retries`）

### 5.5 O3 上下文历史窗口（`STEP_N=3`）

- baseline：`119.433s`
- optimized：`123.209s`
- 变化：`+3.16%`
- 决策：**恢复原默认窗口，不继续推广**。

---

## 6. 已落地但结论仍不充分（含从 `todo-fix` 迁移条目）

### 6.1 S1 表达式风格稳定性约束（来自 `todo-fix`）

- 目标：减少 construct/calculate 阶段可规避的表达式语法失败。
- 当前实现：
  - 拒绝 parser 内部算术函数写法（`ADD/SUBTRACT/MULTIPLY/DIVIDE`），要求使用 `+ - * /`。
  - 拒绝 `$var` 与 `var` 混用，要求基础字段统一使用 `$` 前缀。
  - construct 阶段失败反馈会明确给出修复指令并重试。
- 代码触点：
  - `quantaalpha/factors/regulator/expression_style.py`
  - `quantaalpha/factors/regulator/factor_regulator.py`
  - `quantaalpha/factors/proposal.py`
  - `tests/factors/test_expression_style_validation.py`
- 当前结论：稳定性收益明确，但缺少端到端耗时/质量量化表；保留默认开启。

### 6.2 N1/N2 网络稳态能力（来自 `todo-fix`）

- `timeout/backoff/jitter` 已接入运行时并默认开启，主要针对长尾卡顿/无效等待。
- `failover_base_urls` 能力已落地，但默认配置为空列表，因此 **failover 默认关闭**。
- 当前结论：能力完备但缺少统一口径 A/B（尤其是 p90/p99 和失败率对照）。

### 6.3 P1 受控并行

- 能力已落地：`parallel_enabled + max_parallel_workers`，并发执行已支持 worker 上限。
- 当前结论：默认关闭；需补齐 `workers=1/2/3/4` 的吞吐/质量/内存曲线后再升级默认。

### 6.4 W1 warm-start（trajectory pool 复用）

- 能力已落地：`fresh_start=false` 可加载历史 `trajectory_pool.json`。
- 默认行为：`fresh_start=true`（不复用）；relay 模式下会自动覆盖为 `false` 以保证续跑连贯性。
- 当前结论：需专项 A/B 评估“收敛速度提升 vs 多样性下降”。

### 6.5 运行观测闭环

- `run_doctor` 工具可用，可用于诊断而非直接提速。
- 当前结论：作为观测基础设施保留，不单独计入优化收益。

状态：先不改变默认策略，后续进入专项 A/B。

---

## 7. 待专项 A/B / 待落地事项池（按预期收益从高到低）

> 排序依据：当前瓶颈位置（construct/backtest 占比）+ 实施成本 + 风险。
> 说明：7.1~7.3 为“能力已落地但待专项 A/B”；7.4~7.7 为“尚未落地/需设计后再实现”。

### 7.1 受控并行（高收益，低到中风险）

- 预期收益：吞吐提升最直接。
- 建议：从 `max_parallel_workers=2` 起步，做 `2/3/4` 阶梯 A/B。
- 关注：OOM、swap、失败率、结果稳定性。

### 7.2 网络稳态（timeout/backoff/jitter/failover）（中高收益，中风险）

- 预期收益：降低长尾卡顿和无效等待。
- 建议：先补齐超时与退避策略，再看 p90/p99 改善。

### 7.3 warm-start（中收益，中风险）

- 预期收益：减少盲目探索、加快早期收敛。
- 风险：多样性下降。
- 建议：做 `fresh_start=true/false` 对照，监控多样性指标。

### 7.4 I/O 热启动（中收益，中风险）

- 预期收益：减少每任务初始化开销。
- 建议：先 profiling 再改架构，避免过早复杂化。

### 7.5 LLM 确定性子流程缓存（中收益，中风险）

- 预期收益：降低 JSON 修复等重复请求成本。
- 风险：缓存边界不当会影响探索。

### 7.6 动态预算分配（潜在高收益，高风险）

- 风险：过早收敛，错失长尾。
- 建议：放在后序，先把观测体系做完整。

### 7.7 多保真筛选（潜在高收益，高风险）

- 风险：误杀“慢热型”高质量因子。
- 建议：必须带 `top-k + random-m` 护栏。

---

## 8. 下一轮执行计划（Top 3）

### 8.1 P1 受控并行 A/B

- 对照：`workers=1/2/3/4`。
- 验收：吞吐提升且质量不劣化，RSS/swap 在可控范围。

### 8.2 P2 网络稳态 A/B

- 对照：固定重试 vs 指数退避+jitter+timeout。
- 验收：p90/p99 耗时下降，失败率下降。

### 8.3 P3 warm-start A/B

- 对照：`fresh_start=true/false`。
- 验收：收敛速度提升且多样性不显著下降。

---

## 9. 附录A：关键 A/B 结果索引

### 9.1 回测内存优化（100 因子）

- baseline 结果文件：
  - `data/results/backtest_v2_results/all_factors_library_paper_repro_23r2_n100_20260302_201231_backtest_metrics.json`
- optimized 结果文件：
  - `data/results/backtest_v2_results/all_factors_library_paper_repro_23r2_n100_20260302_201540_backtest_metrics.json`

### 9.2 文档内引用的历史 A/B

- O1：`cheap_filter + duplicate_exact`
- O2：`json response_format`
- O3：历史窗口
- O4：温度分层
- O5：止损预算
- S1：表达式风格稳定性约束
- N1/N2：网络稳态与 failover
- P1：受控并行
- W1：warm-start

详细原始记录见历史日志与本仓库先前版本文档归档。

---

## 10. 附录B：当前默认策略快照（与本结论一致）

- 保留：协议层强约束 JSON、表达式风格稳定性约束。
- 关闭/回滚：cheap gate、温度分层、收紧止损、回测“降内存”方案。
- 网络稳态：`timeout/backoff/jitter` 默认开启；`failover` 默认关闭（空列表）。
- 回测相关代码当前已恢复到 baseline 行为（以一致性优先）。
