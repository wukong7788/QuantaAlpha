# 因子去重系统（面向量化基金实盘）

## 1. 目标与范围

本文档基于 QuantaAlpha 当前代码的**真实可用能力**，给出一套可落地的因子去重方案，目标是：

1. 降低重复表达式与高相关因子进入实盘池，减少拥挤交易和回撤同质化风险。
2. 降低重复计算和无效回测成本，提高挖掘-回测效率。
3. 在 16GB 级别研发机上可稳定执行，不依赖额外大规模基础设施。

本文不定义“全新系统重写”，只描述项目中已经存在并可直接调用的链路。

## 1.1 文件位置（当前）

当前“因子过滤系统”相关文件位置：

1. 主脚本：`scripts/factor_filtering/select_factors.py`
2. 主文档：`docs/factors_filter_system.md`

说明：

1. `scripts/run_backtest_safe.sh` 仍是统一交互入口（不迁移），内部调用上述主脚本完成去重筛选。

---

## 2. 独立回测阶段（优先执行）

### 2.1 独立回测阶段（当前可执行基线）

```bash
BACKTEST_MIN_QUALITY=high ./scripts/run_backtest_safe.sh \
  --library data/factorlib/all_factors_library_prod_dedup_v1.json \
  --factor-source custom \
  --threads 6 \
  --max-factors 120 \
  --corr-dedup \
  --dedup-method two_stage \
  --dedup-linkage complete \
  --dedup-topn 60 \
  --dedup-per-cluster 1 \
  --dedup-corr-threshold 0.8 \
  --dedup-stage2-corr-threshold 0.8 \
  --dedup-sample-size 12000 \
  --dedup-sample-split train_valid \
  --dedup-compute-missing
```

解释：

1. `--dedup-per-cluster 1`：强约束多样性，更贴近实盘去拥挤需求。
2. `--dedup-topn`：控制最终可交易因子池规模。
3. `BACKTEST_MIN_QUALITY=high`：启用质量预筛（`high|medium|low|off|auto`），不显式设置时默认 `off`。
4. `--dedup-compute-missing`：降低因缓存缺失导致的筛选偏差（但会更慢）。
5. `--dedup-sample-split train_valid`：去重相关性估计仅用 train+valid，避免 test 泄漏。

### 2.2 独立回测阶段（升级路线，结合基金实践）

以下是“专业意见”与当前项目结合后的优先级路线：

1. `P0` 防止筛选时间泄漏
   - `已完成`：默认 `sample_split=train_valid`，仅用 train+valid 估计去重相关性。
2. `P1` 二阶段去重
   - `已完成`：默认 `dedup_method=two_stage`，Stage-1 粗筛后执行 Stage-2 IC 序列精筛。
3. `P1` 聚类逻辑升级
   - `已完成`：支持 `dedup_linkage=complete|connected`，默认 `complete`。
4. `P1` 冠军打分升级
   - `已完成`：Stage-2 使用组合分数 `abs(mean_ic)*max(ir,0)*coverage*stability*capacity_penalty`。
5. `P2` 可选增强
   - 对最终候选做小规模残差化复检（仅 Top-M），进一步降低共线暴露。

### 2.3 只看过滤结果（不跑回测）

用于快速确认“当前过滤系统最后会剩多少因子”：

```bash
BACKTEST_MIN_QUALITY=high ./scripts/run_backtest_safe.sh \
  --factors-filter \
  --library data/factorlib/all_factors_library_prod_dedup_v1.json
```

输出会打印：

1. `experiment`
2. `quality_range`
3. `final_selected`

并在 `data/factorlib/selected/` 生成：

1. 带参数快照：`<experiment>_factors_filter_q<quality>_n<count>_<timestamp>.json`
2. 稳定别名：`<experiment>_factors_filter_latest.json`

### 2.4 回测记录（过滤后 + 全量对照）

用于在项目内快速追溯“过滤后因子池”与“未过滤全量因子池”的离线回测结果（以落盘产物为准）。

#### 过滤后因子池（factors_filter_latest，正确）

输入因子库：

- `data/factorlib/selected/all_factors_library_paper_repro_23r2_factors_filter_latest.json`

回测产物（2026-03-03 09:10:35 → 09:16:18，Asia/Shanghai）：

- metrics: `data/results/backtest_v2_results/all_factors_library_paper_repro_23r2_factors_filter_latest_n147_20260303_091602_backtest_metrics.json`
- num_factors: `147`
- annualized_return: `0.0583299303`，information_ratio: `0.8639698829`，max_drawdown: `-0.1007734248`

备注：

- 2026-03-03 08:12:58 的上一轮复跑指标与本轮一致，故不重复记录。

#### 未过滤全量（time_first350，暂不准）

输入因子库：

- `data/factorlib/selected/all_factors_library_paper_repro_23r2_time_first350_20260303_094011.json`

回测产物（2026-03-03 11:58:08 → 12:11:49，Asia/Shanghai）：

- metrics: `data/results/backtest_v2_results/all_factors_library_paper_repro_23r2_time_first350_20260303_094011_n350_20260303_121128_backtest_metrics.json`
- num_factors（名义）: `350`
- annualized_return: `0.0443788186`，information_ratio: `0.6943032461`，max_drawdown: `-0.1024480379`

备注：

- 该 350 因子回测由于 `factor_name` 重名覆盖问题，实际回测使用因子数可能小于 350，暂不作为严谨对比结论；细节与修复项见 [`todo-fix.md`](todo-fix.md)。

---

## 3. 当前项目的三层去重链路（实际生效）

### Layer A：生成阶段 AST 去重（结构去重）

生效位置：

- `quantaalpha/factors/proposal.py`
- `quantaalpha/factors/coder/evaluators.py`
- `quantaalpha/factors/regulator/factor_regulator.py`

机制：

1. 对表达式做 AST 匹配（`match_alphazoo`），计算 `duplicated_subtree_size`。
2. 结合复杂度约束一起判定可接受性：
   - duplication threshold
   - free args ratio
   - unique vars ratio
   - symbol length
   - base features count
3. 若不通过，构造阶段要求模型重生表达式；编码评估阶段也会拒绝不合格表达式。

关键前提：

- 要启用“跨历史因子库”的新颖性对比，必须提供 `factor_zoo.csv`。
- 推荐通过 `run.sh --zoo-dedup` 自动设置：
  - `FACTOR_CoSTEER_FACTOR_ZOO_PATH=data/factorlib/factor_zoo.csv`

---

### Layer B：计算前 exact 去重（工程去重，避免重复算）

生效位置：

- `quantaalpha/pipeline/loop.py` 的 `_apply_precalc_quality_gate`

机制：

1. 在 `factor_calculate` 前加载“已见表达式集合”：
   - 同后缀因子库 `data/factorlib/all_factors_library_<suffix>.json`
   - 当前实验轨迹池 `trajectory_pool.json`
2. 对候选表达式做标准化后 exact match。
3. 重复表达式直接跳过（`duplicate_exact`），不进入 calculate/backtest。

开关状态：

- 由 `quality_gate.cheap_filter_enabled` 控制。
- 当前主配置 `configs/experiment.yaml` 默认是 `false`（默认不开启）。

---

### Layer C：回测前两阶段去重（Stage-1 粗筛 + Stage-2 精筛）

生效入口：

- `scripts/run_backtest_safe.sh --corr-dedup`
- 实际执行 `scripts/factor_filtering/select_factors.py`

机制（当前实现）：

1. Stage-1：从缓存/计算结果读取每个因子的暴露序列（采样 `date×instrument` 面板），做 Spearman 相关粗筛。
   - 仅做“同簇压缩”，不做全局 TopN 截断（避免过早损失多样性）。
2. Stage-2：对 Stage-1 候选计算日度 RankIC 序列，再做 IC 序列相关精筛。
3. 聚类默认使用 complete-linkage（可切到 connected），降低链式连边误杀。
4. 冠军评分在 Stage-2 使用组合分数：`abs(mean_ic)*max(ir,0)*coverage*stability*capacity_penalty`。
5. 最终 TopN（`--dedup-topn`）仅在 Stage-2 之后执行。

注意：

- 默认 `--dedup-method two_stage`：Stage-1 暴露相关粗筛 + Stage-2 IC 序列相关精筛。
- 仅支持 `--factor-source custom`。
- 聚类支持 `complete|connected`，默认 `complete`。
- 默认采样口径 `train_valid`（优先避免 test 泄漏）；可选 `full`。

---

## 4. 实盘推荐基线（建议直接执行）

### 4.1 首次初始化 Zoo

```bash
.venv/bin/python scripts/update_factor_zoo.py build
.venv/bin/python scripts/update_factor_zoo.py status
```

### 4.2 挖掘阶段（启用跨轮次去重）

```bash
./run.sh --low-disk --relay --zoo-dedup "价量因子挖掘" "prod_dedup_v1"
```

建议：

1. 生产前固定 `EXPERIMENT_ID` + `library suffix` 命名规范，避免因子库串线。
2. 若重复表达式密度高，再开启 `quality_gate.cheap_filter_enabled=true` 做计算前 exact 去重。

---

## 5. 参数建议（量化基金实盘口径）

### 挖掘阶段

1. 必开：`--zoo-dedup`（跨轮次表达式去重）。
2. 选开：`quality_gate.cheap_filter_enabled=true`（候选爆量时启用）。
3. 严格化建议（通过环境变量）：
   - `FACTOR_CoSTEER_DUPLICATION_THRESHOLD=5`（默认代码值是 8，更严格）
   - 视策略风格可进一步收紧 symbol/base-feature 阈值。

### 回测筛选阶段

1. 当前版本必开：`--corr-dedup`。
2. 当前版本实盘建议：`--dedup-per-cluster 1`。
3. 当前版本中性起点：`--dedup-corr-threshold 0.8`，按拥挤度再调到 `0.75` 或 `0.85`。
4. 当前版本建议开启：`--dedup-compute-missing`（减少样本选择偏差）。
5. 推荐参数：
   - `--dedup-method two_stage`（暴露相关 + IC相关）
   - `--dedup-linkage complete`（防链式并簇）
- `--dedup-stage2-corr-threshold 0.8`（Stage-2 IC 序列相关阈值）

---

## 6. 监控指标（判断去重是否“真有效”）

建议在每次实验记录以下指标：

1. Zoo 命中率：本轮候选中命中历史表达式的比例。
2. 计算前 exact 去重率（若开启 cheap filter）。
3. 相关性去重压缩率：`final_selected / usable_candidates`。
4. 簇集中度：最大簇占比（越高说明同质化越严重）。
5. 去重前后组合表现变化：IR、换手、最大回撤、行业暴露稳定性。
6. 泄漏检查：去重相关性估计样本是否仅来自 train+valid。
7. 二阶段收益：Stage-1 到 Stage-2 的“同质因子再压缩率”。

---

## 7. 当前已知差距（务实说明）

1. `quality_gate.cheap_filter_enabled` 默认关闭，需要按负载场景手动开启。
2. Stage-2 IC 序列计算会增加时延，且依赖可用缓存/补算能力。
3. complete-linkage 需要 `scipy`；若运行环境缺失，会自动回退到 connected 模式。
4. `factor.duplication.*` 在 `experiment.yaml` 中有配置项，但运行时核心阈值实际由 `FACTOR_CoSTEER_*` 设置/默认值驱动，生产环境建议显式导出环境变量，避免口径漂移。

---

## 8. 最小执行清单（Production Ready）

1. 初始化并检查 Zoo：`build + status`。
2. 挖掘统一使用：`run.sh --zoo-dedup`。
3. 回测统一使用：`run_backtest_safe.sh --corr-dedup --dedup-per-cluster 1 --dedup-compute-missing`。
4. 固化阈值到运行环境（至少 duplication threshold）。
5. 每轮沉淀去重指标到周报，跟踪拥挤度与收益退化。
6. 下一迭代优先实现：Stage-2 小规模残差化复检（降低共线暴露）。
