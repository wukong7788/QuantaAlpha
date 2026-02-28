# Warm-start 优化：更快挖掘高质量因子（效率×质量×成本）

更新时间：2026-02-27  
目标：在固定 API/CPU 预算下，最大化 **单位时间产出的高质量、可复现、可泛化因子数量**。

> 本文是对 `docs/PAPER_REPRODUCTION_GUIDE.md` 与 `docs/performance_optimization_cn.md` 的“warm-start/提效视角补充”，重点解决：如何把正在跑的模型（如 ds）产出的成功/废弃结果沉淀为“种子资产”和“过滤资产”，从而加速后续突变/交叉演进，同时降低 API 成本浪费。

---

## 0. 术语统一：只用 warm-start

- **warm-start**：利用历史产出（成功因子/轨迹/失败模式）作为“下一轮搜索的起点/先验”，提升命中率并降低浪费。
- 备注：需要一段小规模试跑来建立量化基线时，仍归入 warm-start 流程（但会标注为“baseline run / A/B run”），不另起 “warm-up” 名称。

## 1. 第一性原理：4 类损耗源（先压缩浪费，再谈提速）

在因子挖掘（original → mutation → crossover）中，主要浪费来自：

1. **无效 LLM 输出**：JSON 解析/修复失败、风格/语法错误反复重试。
2. **重复探索/重复计算**：等价表达式重复进入 calculate/backtest（exact + near-duplicate）。
3. **低质量候选进入昂贵阶段**：本可在 cheap gate 被挡掉，却消耗了 calculate/backtest。
4. **演化没吃到历史信息红利**：成功因子/轨迹没有变成“可复用的结构知识”，失败没有沉淀成“可复用的负样本过滤器”。

---

## 2. “ds 进程结果”是否具备种子样本能力？（Seedability）

种子样本的价值不在“跑出来了”，而在它能否 **稳定提升后续搜索命中率**。建议用 3 个信号评估：

### 2.1 稳定性（Stability）

理想判据：同一表达式在不同时间窗口/不同复测中，核心指标（RankIC/IC/回测收益）方差可控、方向一致。  
现实约束：挖掘过程中的 `trajectory_pool.json` 通常只包含一次挖掘内回测指标，无法天然提供多窗口方差；因此需要：

- **代理指标（proxy）**：多指标一致性（RankIC>0、annualized_return>0、RankICIR 不极端、max_drawdown 不恶化）；
- **重复出现时的重复性**：若同一表达式在历史中重复出现，统计 RankIC 的离散程度（std/p50/p90）。

### 2.2 可迁移性（Transferability）

看它作为 parent（突变/交叉父代）时，子代是否更容易成功：

- 子代产出率：`child_success_rate = 子代中 RankIC>0 的比例`
- 子代质量：子代 RankIC/收益的均值、最好值
- 改进率：子代指标超过父代的比例（可作为“助推剂强度”）

如果一个因子本身不错，但子代几乎都语法失败或指标塌缩，它更像“偶然解”，种子能力弱。

### 2.3 多样性（Diversity）

种子集合要覆盖“机制空间”，否则 warm start 会加速早熟收敛：

- 不用单纯 top-k；建议 **聚类后每簇取代表**。
- 低成本实现：对表达式做 token/算子签名（函数名 + base feature）后做 Jaccard 相似度与簇计数。

### 2.4 工具化（推荐）

把以上 3 点做成可重复统计，优先落在 `run_doctor` 的报告中（见 `scripts/run_doctor.py` 的“种子样本能力”小节）。

---

## 3. 成功因子如何成为“演进助推剂”（正样本资产化）

把“成功”从被动记录升级为主动注入演化与提示词：

1. **Elite 轨迹摘要**：从成功轨迹抽取“机制 + 关键算子结构 + 适用情景 + 常见失败修复”。
2. **结构化 seed bank（few-shot）**：按机制簇选 5~10 个代表性因子（表达式 + 一句机制解释 + 一个避免点），用于提示词注入（优先落地）。
3. **父代选择策略保底探索**：避免长期只用 `best`，建议使用“利用 + 探索”策略（如 `top_percent_plus_random`），并在 crossover 强制多样性（跨 direction）。

---

## 4. 废弃因子如何成为“过滤器”（负样本资产化）

核心：把“失败原因”标准化、可统计、可复用。

1. **失败分类体系**（至少三类）
   - 语法/风格类（可自动修复/可规则拦截）
   - 可计算但无效类（信号弱/不泛化/依赖特定时期）
   - 资源杀手类（计算/回测极慢、高缺失导致下游浪费）
2. **黑名单分层**
   - 规则层：高确定性错误模式（直接拦截）
   - 语义层：相似失败机制降优先级（避免误杀）
3. **near-duplicate 去重**
   - 先“记录并观测”疑似等价（canonicalization），验证误判率后再开启真正跳过计算。

---

## 5. API 成本控制：强模型用在“不可替代环节”

建议把模型能力分配到不同阶段（并避免对探索主生成做缓存）：

- `propose`：便宜/快模型（多样性优先）
- `construct`：强模型（正确率优先，减少 JSON 修复黑洞）
- `json_fix / rewrite / review`：温度=0 的便宜模型（确定性，适合缓存）
- `feedback`：中等模型即可（除非它强影响下一轮方向）

缓存原则：**只缓存确定性子流程**，不缓存 `propose/construct` 主采样，避免探索收缩。

> warm-start 第一阶段约定：**暂不对 construct 做模型分层/路由**（保创造性与一致性）。优先做提示词注入、失败模板、去重观测与量化基线。

---

## 6. 多模型并发（Gemini/GPT/DeepSeek）怎么做才不“烧钱还不涨产出”

推荐优先级：

1. **多实验并行（稳、可复现）**：同 config（除模型外）跑多条实验线 → 统一去重/聚类 → 统一离线回测排名。
2. **单实验内多模型路由（省钱但工程复杂）**：按阶段路由 + 失败升级策略（失败再升级强模型）。

如果当前目标是“更快挖到高质量因子”，优先 1；当失败资产化/去重/cheap-first 稳定后，再上 2 压成本。

---

## 7. 最小可验证 warm-start 方案（A/B）

目标：只改一个变量就能看出方向，且可复现。

- **规模建议**：`planning.num_directions=3~4`，`evolution.max_rounds=3~5`，保持 `steps_per_loop=5`。
- **对照组（A）**：不注入 seed few-shot（或注入为空），只跑 baseline。
- **实验组（B）**：注入 seed few-shot（提示词注入），其余不变。
- **判定指标（至少 6 项）**：
  - `construct_success_rate`（或 construct 失败次数/分支）
  - `false_ratio` 与 `false_reasons`（重点看 `syntax_error` 是否下降）
  - `duplicate_exact` 命中/占比（以及 near-duplicate 观测数）
  - `tasks/hour`（吞吐）
  - `seedability`（stability_proxy / transferability / diversity）
  - `磁盘增速（GB/hour）` 与 `free_ratio`（避免因为 I/O 把收益吃掉）

---

## 8. Warm-start TODO（做完打勾）

> 说明：该清单以“可复现的量化对比”为第一优先级；每次提交/改动尽量只影响一个变量，方便 A/B。

### 8.1 量化基线（必须先做）

- [ ] 固化 baseline run 配方（方向、config、规模、停止条件），并约定只改 1 个变量做 A/B。
- [ ] 输出 baseline 快照（建议保存 `run_doctor --doctor --json` 报告 + config hash + commit hash + 时间戳）。
- [ ] 确认磁盘红线与止损规则（例如 `disk_free_ratio < 0.12` 自动停止/清理策略）。

### 8.2 资产准备（seed / failure / dedup）

- [ ] 运行 `scripts/prepare_warm_start_assets.py` 生成资产（默认输出到 `data/warm_start_assets/<exp>__<log_root>__<timestamp>/`）：
  - `seed_bank.json`：按“可迁移性优先 + 多样性约束去同质”选种
  - `failure_playbook.jsonl`：从 `run_doctor --doctor --json` 提取 Top-N 失败模式并给出短修复指令
  - `near_dup_report.json`：near-duplicate 观测报告（仅观测、先不拦截）
  - `summary.json`：本次资产生成的参数与计数快照
- [ ] near-duplicate 统一口径：以 `expr_normalized` 为准（建议先做 canonicalization 的“观测期”，评估误判率再启用跳过）。

### 8.3 提示词注入（第一阶段只做这个落点）

- [ ] 设计 seed few-shot 模板（每条：表达式 + 一句机制解释 + 一个避免点；按簇抽样，避免同形重复）。
- [ ] 选择注入位置与开关策略（例如仅用于 mutation/crossover 的 construct 提示；或全阶段 construct 提示；必须可配置开关）。
- [ ] 运行 A/B：A=不注入，B=注入；其余保持一致；出具对比结论（至少覆盖第 7 节 6 个指标）。

### 8.4 后续（先不做，除非前面收益已验证）

- [ ] 将 near-duplicate 从“观测”升级为“跳过 calculate/backtest”（需要误判率评估与回滚开关）。
- [ ] 对确定性子流程启用缓存（仅 `json_fix/rewrite/review`，不缓存 propose/construct 主生成）。
- [ ] 再讨论模型分层/路由（construct 暂不动）。
