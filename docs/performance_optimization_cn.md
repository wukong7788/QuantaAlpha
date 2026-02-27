# QuantaAlpha 因子挖掘提速与质量守恒优化指南（第一性原理版）

更新时间：2026-02-26
适用范围：`run.sh` / `run_doctor` / 演化模式（original -> mutation -> crossover）

---

## 1. 目标函数（先定标尺）

不是单纯追求“跑得快”，而是最大化：

`单位时间内产出的高质量、可复现、可泛化因子数量`

因此必须同时优化两件事：

1. 搜索效率（减少无效尝试和重复计算）
2. 质量密度（候选中可通过质量门并稳定回测的比例）

---

## 2. 当前瓶颈画像（来自近期运行数据）

基于 `run_output_r2.log` 统计的平均耗时占比：

- `factor_construct`：约 48.9%（主瓶颈）
- `factor_backtest`：约 22.5%
- `factor_calculate`：约 16.3%
- `factor_propose`：约 5.9%
- `feedback`：约 6.3%

运行稳定性信号（同一日志）：

- `JSON fix failed` 高频出现
- `JSON parse failed` 持续出现
- 少量表达式解析失败与空分支重试

质量侧（近期 doctor）：

- `false_ratio` 仍在中等偏高区间（约 0.15）
- 失败原因以 `syntax_error` 为主，其次是表达式风格类错误

结论：优先顺序应是

1. 降低 construct 阶段无效重试
2. 降低 backtest/calculate 上的无效计算
3. 在不放松质量门的前提下提升并行吞吐

---

## 2.1 当前参数快照（文件与参数）

以下为当前仓库中的关键参数（便于直接定位改动点）：

- 文件：`configs/experiment.yaml`
- `planning.num_directions = 10`
- `evolution.max_rounds = 11`
- `evolution.mutation_enabled = true`
- `evolution.crossover_enabled = true`
- `evolution.crossover_size = 2`
- `evolution.crossover_n = 10`
- `evolution.parallel_enabled = false`
- `evolution.max_parallel_workers = 2`
- `evolution.max_empty_retries = 1`
- `factor.factors_per_hypothesis = 1`
- `quality_gate.consistency_enabled = false`
- `quality_gate.cheap_filter_enabled = true`
- `quality_gate.max_construct_failures_per_branch = 2`
- `quality_gate.max_json_parse_failures_per_branch = 2`
- `llm.max_retries = 3`
- `llm.retry_delay = 1.0`

运行环境（本机）：

- CPU 核心数：8（`sysctl -n hw.ncpu`）
- 当前并行模式：关闭（串行）

相关代码落点（用于进阶改造）：

- 演化主流程：`quantaalpha/pipeline/factor_mining.py`
- 并行任务调度：`_run_tasks_parallel(...)`（已支持 `max_parallel_workers` worker 上限）
- 轮次控制：`quantaalpha/pipeline/evolution/controller.py`
- proposal 历史上下文：`quantaalpha/factors/proposal.py`（`DEFAULT_HISTORY_LIMIT=4`）
- 表达式风格校验：`quantaalpha/factors/regulator/expression_style.py`
- 运行诊断：`scripts/run_doctor.py`

---

## 3. 优化角度总览（含风险标识）

说明：
- 未标注表示低风险或可控风险
- 标记 `[高危]` 的方法若无护栏，容易牺牲质量

### 3.1 [x] 构造阶段失败减量（最高 ROI）

- 优化点：
  - 强化 JSON 输出约束、缩短无效重试链路
  - 把表达式风格硬校验前移到 proposal/construct（已部分落地）
- 文件与参数：
  - `configs/experiment.yaml -> llm.max_retries`（当前 3）
  - `configs/experiment.yaml -> llm.retry_delay`（当前 1.0）
  - `quantaalpha/llm/client.py`（JSON 提取与修复）
  - `quantaalpha/factors/proposal.py`（`robust_json_parse` 失败重试路径）
- 预期收益：
  - 显著减少 `factor_construct` 时间与回炉次数
- 质量护栏：
  - 不降低最终质量门，仅减少无效尝试

### 3.2 [x] 上下文瘦身与分层提示

- 优化点：
  - `construct` 仅保留必要规则 + 最近高价值失败摘要
  - 历史长文本改为结构化短摘要（失败类型、修复指令、反例）
- 文件与参数：
  - `quantaalpha/factors/proposal.py -> DEFAULT_HISTORY_LIMIT`（当前 4）
  - `quantaalpha/factors/prompts/prompts.yaml`（构造提示词模板）
  - `quantaalpha/factors/coder/qa_prompts.yaml`（函数与表达式约束文案）
- 建议起点：
  - 将 `DEFAULT_HISTORY_LIMIT` 从 6 降到 3~4 做 A/B
  - 保留最近 3 条失败摘要，不直接拼接长原文
- 预期收益：
  - 减少 token 和响应波动，提升稳定性
- 质量护栏：
  - 不删除硬约束与关键失败样例模板

### 3.3 [x] 语法/风格自动修复（本地 rewrite + 复检）

- 优化点：
  - 对 `DIVIDE/SUBTRACT/MULTIPLY/ADD`、`$var/var` 混用、裸变量做自动修复
  - 修复后必须再次 parse + regulator 校验
- 文件与参数：
  - `quantaalpha/factors/regulator/expression_style.py`
  - `quantaalpha/factors/regulator/factor_regulator.py`
  - `quantaalpha/factors/proposal.py`
  - 单测：`tests/factors/test_expression_style_validation.py`
- 预期收益：
  - 降低可避免的语法失败，减少无效 backtest
- 质量护栏：
  - 自动修复失败则回退重试，不放行脏表达式

### 3.4 [ ] 多保真筛选（cheap-first）[高危]

- 优化点：
  - 先做轻量筛（信号健康度/稳定性），再做全量 backtest
- 预期收益：
  - 大幅压缩 backtest 计算量
- 文件与参数（建议新增）：
  - `configs/experiment.yaml` 新增：
    - `quality_gate.cheap_filter_enabled`
    - `quality_gate.cheap_filter_top_k`
    - `quality_gate.cheap_filter_random_m`
  - `quantaalpha/pipeline/loop.py` 或 `quantaalpha/pipeline/factor_mining.py` 接入“先筛后测”
- 主要风险：
  - 可能提前淘汰“慢热型高质量因子”
- 必需护栏：
  - `top-k + random-m` 保底探索
  - 定期回捞淘汰池并监控漏检率

### 3.5 [x] 受控并行（按核数和 I/O 约束）

- 优化点：
  - 从串行迁移到小规模并行（如 2~4 并发）
  - 阶段内并行，不跨阶段打乱流程
- 文件与参数：
  - `configs/experiment.yaml -> evolution.parallel_enabled`（当前 false）
  - `quantaalpha/pipeline/factor_mining.py -> _run_tasks_parallel(...)`
- 关键细节：
  - 已支持 `evolution.max_parallel_workers`（例如 2~4），按 worker 上限分批并行。
  - 若不设置上限，仍可能按 phase 内任务数拉满并发。
- 建议起点：
  - 8 核机器先用 `2`，稳定后升到 `3~4`。
- 预期收益：
  - 吞吐显著提升
- 质量护栏：
  - 固定随机种子、任务隔离、失败重试与可复现日志

### 3.6 [ ] 缓存格式升级：Parquet + ZSTD

- 优化点：
  - `factor_cache` 从 `.pkl` 迁移至 `parquet+zstd`（可双写灰度）
- 文件与参数：
  - 读取：`quantaalpha/backtest/custom_factor_calculator.py`
  - 读写：`quantaalpha/backtest/factor_calculator.py`
  - 同步：`quantaalpha/factors/library.py`
  - 路径：`configs/backtest*.yaml -> cache_dir`（当前 `data/results/factor_cache`）
- 预期收益：
  - 空间压力显著下降，I/O 更稳定
- 实验观察：
  - 抽样基准显示体积约可下降 58%（具体以实际数据为准）
- 质量护栏：
  - 先双读（新格式优先，旧格式回退），再完全切换

### 3.7 [ ] 演化预算动态分配（Bandit/Success-weighted）[高危]

- 优化点：
  - 对高潜力分支增加预算，低潜力分支降预算
- 预期收益：
  - 同等预算下提高高质量因子产出密度
- 文件与参数（建议新增）：
  - `configs/experiment.yaml -> evolution.parent_selection_strategy`（当前 `best`）
  - `configs/experiment.yaml -> evolution.top_percent_threshold`（当前 0.3）
  - `quantaalpha/pipeline/evolution/controller.py`（父代选择与轮次预算分配）
- 主要风险：
  - 过早收敛，错失长尾创新
- 必需护栏：
  - 固定探索配额（如 20%）
  - 定期反事实抽样校验

### 3.8 [ ] 模型分层路由（强模型用于关键环节）

- 优化点：
  - `propose` 可用更快模型
  - `construct/final decision` 保持高质量模型
  - 失败再升级模型
- 预期收益：
  - 降时延与成本，同时保关键质量
- 文件与参数：
  - `.env -> CHAT_MODEL / REASONING_MODEL`
  - `quantaalpha/llm/client.py`（按调用标签路由模型）
  - `quantaalpha/factors/proposal.py`、`quantaalpha/factors/coder/eva_utils.py`（按阶段选模型）
- 质量护栏：
  - 关键环节不降模型等级

### 3.9 [ ] 强模型 + 历史知识 warm start

- 优化点：
  - 高分因子作为初始父代
  - 历史日志沉淀为“失败模式库 + 成功模式库”
  - 非 fresh-start 时加载 trajectory pool 作为起点
- 文件与参数：
  - `configs/experiment.yaml -> evolution.fresh_start`（当前 true）
  - `quantaalpha/pipeline/evolution/trajectory.py`（轨迹池）
  - `log/<exp>/trajectory_pool.json`（可复用历史轨迹）
  - `data/factorlib/all_factors_library*.json`（高分因子来源）
- 建议起点：
  - 将 `fresh_start` 设为 `false` 做一组 warm-start A/B。
- 预期收益：
  - 提升首轮质量，减少盲目探索
- 质量护栏：
  - 维持探索多样性，避免只围绕旧解局部搜索

### 3.10 [x] 早停与坏分支止损

- 优化点：
  - 连续语法失败、空分支重试超阈值时提前止损
- 文件与参数：
  - `quantaalpha/pipeline/factor_mining.py -> _run_evolution_task(...)`
  - `configs/experiment.yaml -> evolution.max_empty_retries`（已外置，当前 1）
- 预期收益：
  - 避免长时间消耗在明显无效分支
- 质量护栏：
  - 限制为“分支级”止损，不影响全局继续探索

### 3.11 [x] 质量门前置（先挡再算）

- 优化点：
  - 在进入 `calculate/backtest` 前做更严格的静态校验
- 预期收益：
  - 减少昂贵阶段的无意义执行
- 文件与参数：
  - `configs/experiment.yaml -> quality_gate.*`
  - `quantaalpha/factors/regulator/*`（静态规则）
  - `quantaalpha/factors/proposal.py`（proposal 阶段前置拦截）
- 质量护栏：
  - 校验规则透明可追踪，避免误杀

### 3.12 [x] 运行观测与自动诊断闭环

- 优化点：
  - 使用 `run_doctor` 持续输出阶段耗时、失败原因、存储与磁盘状态
  - 触发阈值告警（如 false_ratio、构造超时、磁盘余量）
- 预期收益：
  - 快速定位瓶颈并持续迭代优化
- 文件与参数：
  - `scripts/run_doctor.py`
  - `scripts/run_doctor.sh`
  - `.codex/workflows/run_doctor.md`

### 3.13 [x] “强约束 JSON”从提示词升级到协议层（response_format / json_schema）

- 优化点：
  - 目前主要靠提示词 + 解析/修复兜底；进一步把“只返回 JSON”变成 API 层的硬约束（能显著降低 `JSON fix failed` 与空响应重试链路）。
- 文件与参数（代码落点）：
  - `quantaalpha/llm/client.py`：
    - 仅在 `json_mode=true` 的调用中启用 `response_format`（或 JSON schema）。
    - 避免 `reasoning_flag=true && json_mode=false` 时强行走 JSON 截取/修复（否则会误伤自然语言输出，导致空字符串与递归解析异常）。
- 现状快照：
  - `configs/experiment.yaml -> llm.max_retries=3`，当前大量时间黑洞仍来自 JSON 修复失败后的多次 retry。
- 建议起点（低风险）：
  - 先用 `response_format=json_object`（或 provider 支持的等价选项）把“结构化输出”固化；
  - 再逐步上 `json_schema`（把 keys/类型/必填字段写死）。
- 预期收益：
  - construct 阶段无效重试显著减少，端到端速度提升且不牺牲质量（只是把格式错误从“事后修复”变为“事前约束”）。
- 质量护栏：
  - schema 只约束“外层结构”，不要把表达式的内容空间写得过窄（避免误伤可行解）。

### 3.14 [ ] LLM 调用去重与“确定性子流程缓存”（只缓存不会降低探索的环节）

- 优化点：
  - 对以下子流程做本地缓存（key 包含：model + system/prompt hash + json_mode + temperature + seed 等）：
    - JSON 修复/截断后的“二次只返 JSON”短提示
    - 语法/风格 rewrite（如 `$var/var`、`DIVIDE->/` 的修复建议）
    - 评审/打分等确定性输出（温度为 0 时更适合）
  - 不缓存“生成候选因子”这类需要多样性的步骤（否则会降低探索，属于高风险）。
- 文件与参数（建议新增）：
  - `configs/experiment.yaml`（建议新增）：
    - `llm.cache_enabled: true|false`（默认 false）
    - `llm.cache_scope: ["json_fix","rewrite","review"]`（默认仅 `json_fix`）
    - `llm.cache_ttl_seconds: 86400`（按天滚动即可）
  - `quantaalpha/llm/client.py`：在 `_create_chat_completion_inner_function` 外围加一层轻量 cache（命中则跳过网络与解析）。
- 现状快照：
  - 你日志里 `JSON fix failed` 频率很高，此类失败通常会触发“固定模板重试”，属于可缓存的“确定性子流程”。
- 预期收益：
  - 在网络抖动/模型偶发空响应时，能把“重试链路”变成快速命中，减少时间黑洞。
- 质量护栏：
  - 默认只缓存 `json_fix`，且 cache 不参与 `propose/construct` 的主生成（避免探索收缩）。

### 3.15 [x] “避免重复计算”的硬门：计算前/回测前的跨轮次去重（exact + near-duplicate）

- 优化点：
  - exact 去重：同一 `(factor_name, factor_expression)` 已在当前实验的 library 或 trajectory 中出现过，直接跳过 `calculate/backtest`。
  - near-duplicate 去重：对表达式做 canonicalization（例如：空白、括号冗余、常量写法）后再做 hash，避免“等价但字符串不同”导致重复算。
- 文件与参数（代码落点）：
  - `quantaalpha/factors/library.py`（因子 ID/去重逻辑）
  - `quantaalpha/pipeline/loop.py`（cheap gate 已存在：可在这里补上“跨轮次已见过”判定）
  - `log/<exp>/trajectory_pool.json`（已存在：可作为“已见集合”）
- 现状快照：
  - `quality_gate.cheap_filter_enabled=true` 只能挡掉明显非法任务，但挡不住“合法但重复”的浪费。
- 建议起点（低风险）：
  - 先做 exact 去重（零风险）；
  - near-duplicate canonicalization 做成可开关（默认 off，避免误判）。
- 预期收益：
  - 直接减少 `calculate/backtest` 的次数，速度提升且不牺牲质量（只减少重复）。
- 质量护栏：
  - near-duplicate 仅在“高置信等价”规则下启用，或先记录但不跳过（观测一段时间再开）。

### 3.16 [ ] 计算/回测 I/O 热启动：复用数据句柄与预热（减少每个因子的固定开销）

- 优化点：
  - `daily_pv.h5` / qlib 数据的加载与索引构建往往是固定成本；通过进程内单例或 worker 常驻复用，降低每个因子的启动开销。
  - 把“初始化一次”的对象（数据集、日历、instrument 列表）放到 worker 生命周期而不是任务生命周期。
- 文件与参数（代码落点，需结合现实现）：
  - `quantaalpha/backtest/*`（因子计算与回测入口）
  - `quantaalpha/core/experiment.py`（实验初始化与数据路径）
  - 若并行启用：`quantaalpha/pipeline/factor_mining.py -> _run_tasks_parallel(...)`（可以复用固定 worker 池，而不是每步重新起进程）
- 现状快照：
  - `evolution.parallel_enabled=false`（当前串行），但即便串行也存在“每任务重复初始化”的可能。
- 建议起点（低风险）：
  - 先加 profiling：把数据加载/索引构建耗时单独打点（中位数、p90）；
  - 若占比显著，再做热启动改造（只改初始化位置，不改计算逻辑）。
- 预期收益：
  - 对 `factor_calculate` 与 `factor_backtest` 的尾部延迟（p90/p99）改善明显，总吞吐提升。
- 质量护栏：
  - 复用只影响性能，不改变计算逻辑；仍需对照验证产出一致性（hash 对比）。

### 3.17 [ ] 轮次结构自适应：根据阶段成功率动态调参（减少“低产出阶段”的预算浪费）[高危]

- 优化点：
  - 从你近期观测看：`crossover` 的 construct/skip 成功率往往显著低于 `mutation`，导致吞吐下降。
  - 在不取消 crossover 的前提下做“预算倾斜”：当某阶段连续 N 轮低于阈值时，临时下调该阶段的 `*_n`（例如 crossover_n），把预算让给更高产出的阶段。
- 文件与参数：
  - `configs/experiment.yaml`：
    - `evolution.crossover_n`（当前 10）
    - `evolution.crossover_size`（当前 2）
  - `quantaalpha/pipeline/evolution/controller.py`（轮次/阶段调度）
  - `scripts/run_doctor.py`（需要输出分阶段成功率，支撑自适应策略）
- 主要风险：
  - crossover 可能产生少量但质量很高的“组合型”因子；过早削弱会错过长尾。
- 必需护栏：
  - 保底：每 K 轮强制跑 1 次 crossover（或保留最小 crossover_n）；
  - 自适应只在“构造失败/格式失败”占比极高时触发，不因为短期收益差就关掉。

### 3.18 [x] 分阶段采样参数：对“格式正确性”与“多样性”分别优化（温度分层）

- 优化点：
  - JSON/结构化输出环节（construct / 评审 / JSON 修复）优先“格式稳定”，用更低温度；
  - 自然语言创意环节（hypothesis/propose）优先“多样性”，保留当前温度或略高；
  - 目标是减少“坏格式导致的重试”，从而提速，而不是减少探索空间。
- 文件与参数（现状快照）：
  - `quantaalpha/llm/config.py -> chat_temperature`（当前 0.5）
  - `quantaalpha/llm/client.py`：调用时会把 `temperature` 传入请求（未区分阶段的话会共享一个默认值）。
- 建议起点（低风险）：
  - 增加“按调用标签”的温度映射（例如 `json_mode -> 0.0`，freeform -> 0.5），只对 `json_mode=true` 强制低温；
  - 保持 hypothesis/propose 的温度不变，避免探索收缩。
- 预期收益：
  - 降低 JSON 修复/重试次数，直接减少 `factor_construct` 时间黑洞。
- 质量护栏：
  - 不动 propose 的采样参数；只降低 JSON/修复链路的温度。

### 3.19 [x] 网络稳态与尾延迟优化：超时、退避与备用链路（减少“卡住等半天”的空耗）

- 优化点：
  - 为 LLM 请求设置明确超时（connect/read/overall），避免偶发卡死把轮次拖慢；
  - retry 使用指数退避 + jitter，避免短时间内连续撞同一个失败窗口；
  - 可选：配置备用 `OPENAI_BASE_URL`（或多 endpoint）在连续失败时自动切换。
- 文件与参数（建议新增）：
  - `configs/experiment.yaml`（建议新增）：
    - `llm.request_timeout_s: 60`（单次请求上限，按模型实际调）
    - `llm.retry_backoff: exponential`、`llm.retry_jitter: true`
    - `llm.failover_base_urls: [...]`（可选）
  - `quantaalpha/llm/client.py`：把 timeout/backoff/failover 落到调用栈，并把“失败原因”结构化写进日志（用于 run_doctor 统计）。
- 现状快照：
  - 目前 `llm.max_retries=3`、`llm.retry_delay=1.0` 是固定间隔，遇到短期抖动可能会浪费多次无意义 retry。
- 预期收益：
  - 提升稳定吞吐与 p90/p99 延迟，特别是夜间网络/服务波动场景。
- 质量护栏：
  - 只改变传输与重试策略，不改变提示词与质量门。

---

## 4. 明确标记的高危方法（可能伤质量）

以下方法必须加护栏后再用：

1. `[高危]` 只保留 top-k，完全不做随机探索
2. `[高危]` 在关键阶段降级到低质量模型
3. `[高危]` 过度裁剪上下文导致约束丢失
4. `[高危]` 仅按短期指标分配预算，导致过早收敛
5. `[高危]` 对“生成候选因子”步骤做 LLM 缓存/去重，导致探索多样性下降
6. `[高危]` 过度削弱 crossover 等低产出阶段，错过组合型高质量因子

---

## 5. 推荐落地顺序（先易后难）

1. 先做“低风险高收益”：
   - construct 失败减量
   - 提示词分层与摘要化
   - 语法/风格自动修复 + 复检
2. 再做“结构性提速”：
   - 受控并行
   - cache 迁移（parquet+zstd，双写灰度）
3. 最后做“策略级优化”：
   - 多保真筛选
   - 动态预算分配
   - 强模型 + warm start

---

## 5.1 可直接执行的最小改动建议（示例）

仅作为起点，不代表最终最优：

1. 并行起步（低风险）
   - 文件：`configs/experiment.yaml`
   - 参数：`evolution.parallel_enabled: true`
   - 同时在代码中增加 `evolution.max_parallel_workers: 2`（建议新增）
2. 上下文降噪
   - 文件：`quantaalpha/factors/proposal.py`
   - 参数：`DEFAULT_HISTORY_LIMIT: 6 -> 4`（A/B 验证）
3. warm-start 对照
   - 文件：`configs/experiment.yaml`
   - 参数：`evolution.fresh_start: true -> false`（单独实验组）

---

## 6. 验证标准（必须同时看速度与质量）

每轮优化都应做 A/B 对比，并至少跟踪：

- 速度：
  - 单任务总耗时
  - `factor_construct/backtest` 中位数与 p90
  - 每小时完成任务数
- 质量：
  - `false_ratio`
  - `syntax_error`、`parser_function_form`、`mixed_dollar_variable` 计数
  - 最终可用因子数与回测关键指标稳定性
- 稳定性：
  - JSON 解析失败率
  - 空分支重试次数
  - tracebacks / 严重异常

只有在“速度提升且质量不劣于基线”时，优化才算通过。

建议固定一个“对照模板命令”：

- 基线组：`EXPERIMENT_ID=... ./run.sh --resume "...direction..." "...suffix..."`
- 实验组：仅改一个参数，其他保持一致
- 评估：`./scripts/run_doctor.sh --experiment-id <id> --doctor --markdown`

---

## 7. 第二轮优化代办（建议先做的 4 项）

说明：
- 以下 4 项按优先级排序（提速且不降质量）。
- 其中涉及的“温度映射/网络超时与退避”等配置项，属于本次优化**新增选项**，不是原项目默认选项。落地时需要同步更新 `SPECS.md`（配置项可观测）。

1. [x] 3.13 协议层强约束 JSON（`response_format` / `json_schema`）
   - 目标：把“只返回 JSON”从提示词升级为 API 层硬约束，降低 `JSON fix failed/parse failed` 的重试黑洞。
   - 改动点：`quantaalpha/llm/client.py`
   - 护栏：仅在 `json_mode=true` 的调用启用；`reasoning_flag=true && json_mode=false` 不得触发 JSON 截取/修复链路。

2. [x] 3.18 分阶段温度分层（只对 `json_mode` 降温到 0~0.1）
   - 目标：提升结构化输出的格式稳定性，减少 construct/repair 的无效重试；不影响 hypothesis/propose 的探索多样性。
   - 新增配置（建议放到 `configs/experiment.yaml -> llm.*`，并在 `quantaalpha/llm/config.py` 读取）：
     - `llm.json_mode_temperature: 0.0`（或 0.1）
     - `llm.freeform_temperature: 0.5`（默认沿用现有 `chat_temperature`）
   - 改动点：`quantaalpha/llm/client.py`（按 `json_mode` 选择温度）。

3. [x] 3.15 跨轮次去重（先做 exact 去重，near-duplicate 先观测后启用）
   - 目标：减少重复 `calculate/backtest` 的浪费（只减少重复，不改变质量门）。
   - 改动点：
     - `quantaalpha/pipeline/loop.py`：进入 `calculate/backtest` 前，查 `factor_library` + `trajectory_pool` 是否已存在同一 `(factor_name, factor_expression)`。
   - 产出：skip 时写 `skip_reason=duplicate_exact`（便于 doctor 统计）。

4. [x] 3.19 网络稳态与尾延迟优化（timeout/指数退避+jitter/可选 failover）
   - 目标：减少“卡住等半天”的空耗，改善 p90/p99；只改变传输与重试策略，不改变提示词与质量门。
   - 新增配置（建议放到 `configs/experiment.yaml -> llm.*`）：
     - `llm.request_timeout_s: 60`（单次请求上限，按实际模型/服务调）
     - `llm.retry_backoff: exponential`
     - `llm.retry_jitter: true`
     - `llm.failover_base_urls: []`（可选）
   - 改动点：`quantaalpha/llm/client.py`（timeout/backoff/failover + 结构化日志字段）。
