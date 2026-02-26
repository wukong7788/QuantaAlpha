# A 股 ETF 轮动改进：Codex Workflow（借鉴 QuantaAlpha）

## 1. 目标

把 QuantaAlpha 的 `假设 -> 生成 -> 计算 -> 回测 -> 反馈 -> 进化` 闭环，迁移到 A 股 ETF 轮动策略，形成可持续迭代的研究流水线。

核心输出：
- 可追踪的策略轨迹（每轮假设、信号、参数、回测、反馈）
- 可复现实验结果（固定数据切分、成本、评估口径）
- 自动筛选出的下一轮候选方向

---

## 2. 最值得借鉴的方向（按优先级）

1. 多方向并行起步  
先并行探索多个策略方向，不要单一路径深挖。

2. 轨迹化进化（Mutation/Crossover）  
从“最优单策略”切换为“策略种群演化”。

3. 质量闸门（复杂度、冗余、可交易性）  
先过滤低质量信号，再进入回测。

4. 统一评估口径 + 结构化反馈  
每轮用同一组指标打分，避免“换口径得结论”。

5. 因子/策略库沉淀  
保留所有候选及 lineage（父子关系），方便复盘与二次利用。

---

## 3. Codex 工作流（可执行）

## 阶段 0：定义约束（一次性）

输入：
- ETF 池（宽基/行业/风格/商品）
- 交易频率（周频或月频）
- 成本模型（双边费率 + 滑点）
- 最大持仓数、单标的权重上限、行业集中度上限

输出：
- `data/etf_rotation/config/constraints.yaml`

Gate：
- 没有明确成本与仓位约束，不进入下一步。

## 阶段 1：多方向假设生成（每轮）

做法：
- 一次生成 6-10 个方向，每个方向一句话定义 alpha 机制。
- 方向示例：趋势延续、均值回复、风格轮动、拥挤度反转、风险偏好切换、宏观状态映射。

输出：
- `data/etf_rotation/round_{k}/directions.json`

Gate：
- 方向两两相似度过高（语义重复）则重采样。

## 阶段 2：方向 -> 信号表达式

做法：
- 每个方向生成 3-5 个可计算信号。
- 信号分层：`raw feature -> transform -> score -> position rule`。

输出：
- `data/etf_rotation/round_{k}/signals_raw.json`

Gate（质量闸门）：
- 复杂度：操作符数量、回看窗口、参数数量不能超限。
- 冗余：与历史信号相关性过高则剔除。
- 可交易性：预估换手超阈值则降权或剔除。

## 阶段 3：统一回测矩阵

做法：
- 固定滚动窗口做 walk-forward（例如 3 年训练 + 1 年验证，滚动）。
- 每个信号都跑同样的频率、成本、风控约束。

输出：
- `data/etf_rotation/round_{k}/backtest_metrics.csv`
- `data/etf_rotation/round_{k}/equity_curves.parquet`

Gate：
- 只按统一口径比较，不允许手工挑窗口。

## 阶段 4：结构化反馈与打分

建议综合评分（可改权重）：

```text
score =
  0.30 * z(IR_net) +
  0.20 * z(Calmar) +
  0.15 * z(OOS_Stability) +
  0.15 * z(Monthly_WinRate) -
  0.10 * z(MaxDrawdown) -
  0.10 * z(Turnover)
```

输出：
- `data/etf_rotation/round_{k}/leaderboard.csv`
- `data/etf_rotation/round_{k}/feedback.json`

Gate：
- 前 20%-30% 进入进化池，其余归档。

## 阶段 5：进化生成下一轮

Mutation（正交探索）：
- 对 Top 策略做“不同机制”的变异，而不是仅调参。

Crossover（融合）：
- 从不同机制的优胜策略中抽样组合，生成混合策略。

输出：
- `data/etf_rotation/round_{k+1}/seed_from_round_{k}.json`

Gate：
- 子代与父代高度同质（表达式哈希或相关性阈值）则拒绝。

---

## 4. 推荐的第一批方向（A 股 ETF）

1. 风险偏好切换  
用市场宽度、成交额分层、波动率状态决定“进攻/防守 ETF”。

2. 行业相对强弱 + 拥挤度约束  
动量选强，但对高拥挤行业加惩罚，避免高位接力。

3. 趋势/反转双状态机  
同一 ETF 在不同波动 regime 下启用不同规则。

4. 跨资产确认  
用国债、商品、汇率代理变量对权益轮动信号做确认或过滤。

5. 回撤主导的仓位调节  
把仓位管理作为一等公民，不只优化选券分数。

---

## 5. 给 Codex 的执行提示模板

可直接在 Codex 发：

```text
你是量化研究工程师。请在 /Users/ron/Documents/QuantaAlpha 内执行以下任务：
1) 基于 data/etf_rotation/config/constraints.yaml 生成 round_0 的 8 个策略方向，保存为 directions.json。
2) 每个方向生成 4 个可计算轮动信号，保存为 signals_raw.json。
3) 对 signals_raw.json 执行复杂度/冗余/可交易性过滤，输出 signals_filtered.json，并解释每个剔除原因。
4) 用统一回测参数跑 walk-forward，输出 backtest_metrics.csv 和 leaderboard.csv。
5) 根据综合评分选择 Top 30%，生成 mutation/crossover 的下一轮 seed 文件。
要求：每步都落盘；失败时保留错误上下文；不要覆盖历史轮次文件。
```

---

## 6. 最小可行落地（两周）

第 1 周：
- 先跑 `round_0`：6 个方向、每方向 3 个信号、周频轮动。
- 目标是验证流程完整性，不追求最终收益。

第 2 周：
- 上 mutation + crossover，各 1 轮。
- 引入换手惩罚和回撤仓位控制，观察 OOS 稳定性变化。

---

## 7. 与 QuantaAlpha 代码映射关系

- 循环骨架：`quantaalpha/utils/workflow.py`
- 主流程步骤：`quantaalpha/pipeline/loop.py`
- 轨迹与进化控制：`quantaalpha/pipeline/evolution/`
- 回测执行与统一产物：`quantaalpha/backtest/runner.py`

建议先把 ETF 轮动版本按本文件落成独立数据目录，确认闭环后再考虑接入现有 pipeline 类。
