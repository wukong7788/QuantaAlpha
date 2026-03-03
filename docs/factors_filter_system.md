# 因子合并与过滤工程说明（`run_factors.sh`）

## 1. 文档目的

本文档只记录两类工程能力：

1. 多个因子库的合并（含 Zoo 产物）
2. 因子过滤流水线与缓存重算

统一快速入口是：

```bash
./scripts/run_factors.sh
```

不包含独立回测执行说明（`run_backtest_safe.sh` 不在本文档范围内）。

---

## 2. 快速上手（交互入口）

```bash
./scripts/run_factors.sh
```

核心选项：

1. `1) [LIST]`：查看历史 `all_factors_library*.json` 概览
2. `3) [MERGE]`：按 id 合并（支持 `1+2`、`all`）
3. `4) [CACHE]`：按 id 做缓存修复（dry-run + apply）

备注：

- `FILTER（stage0→stage3）` 目前尚未整合进 `run_factors.sh`（后续会加），当前请直接调用：
  - `scripts/factor_filtering/select_factors.py`
  - 或使用 `scripts/run_backtest_safe.sh --factors-filter`（项目已有交互入口）

---

## 3. 功能到 Python 脚本映射

### 3.1 合并（`3) [MERGE]`）

- 交互入口：`scripts/run_factors.sh`
- 实际脚本：`scripts/factor_filtering/merge_factor_libraries.py`
- 作用：
  1. 多库聚合为一个 pool
  2. 生成 Zoo（`norm` / `ast` / `both`）
  3. 输出文件名自动带 `n + timestamp`

### 3.2 过滤流水线（未整合入 `run_factors.sh`）

- 交互入口：暂无（后续计划整合到 `scripts/run_factors.sh`）
- 实际脚本：`scripts/factor_filtering/select_factors.py`
- 作用：执行 `stage0→stage3` 并可选择输出某个 stage 或 all
- 默认参数以 `select_factors.py` 的 CLI / `run_backtest_safe.sh` 的封装为准。

### 3.3 缓存修复（`4) [CACHE]`）

- 交互入口：`scripts/run_factors.sh`
- 实际脚本：`scripts/factor_filtering/repair_factor_cache.py`
- 作用：
  1. 扫描无效/缺失缓存
  2. dry-run 预览
  3. apply 时可删除坏缓存并重算

---

## 4. 过滤流水线定义（可观测 0→3）

### Stage0：全量池

输入可以是：

1. 单个因子库
2. 多库 ids（会先聚合成总池）

输出：`*_stage0.json`

### Stage1：公式去重

对表达式做指纹去重（当前默认 `ast`），同指纹只保留一条。

输出：`*_stage1.json`

### Stage2：暴露相关去重

对 Stage1 候选做暴露相关聚类压缩。

算法细节（当前实现）：

1. 对每个因子构建暴露向量（采样 `date×instrument` 面板）。
2. 计算两两 Spearman 相关矩阵。
3. 按阈值建边：`|corr| >= threshold` 才认为“同簇候选”。
4. 采用 `complete` linkage（`run_factors.sh` 入口固定）做簇压缩。
5. 每簇保留冠军（当前固定 `per_cluster=1`）。

当前默认参数（`run_factors.sh` 选项 5 固定）：

1. `corr_threshold = 0.8`
2. `sample_size = 12000`
3. `sample_split = train_valid`
4. `cluster_linkage = complete`

输出：`*_stage2.json`

### Stage3：IC 序列相关去重（最终）

对 Stage2 候选做 IC 序列相关聚类压缩，得到最终集合。

算法细节（当前实现）：

1. 对 Stage2 每个候选计算日度 RankIC 序列。
2. 基于 IC 序列计算因子间 Spearman 相关。
3. 按阈值建边并做相关簇压缩（同样使用 `complete` linkage）。
4. 簇内按综合分数选优：`abs(mean_ic) * max(ir, 0) * coverage * stability * capacity_penalty`。
5. 当前 `run_factors.sh` 默认 `topn=all`（即不再额外截断）。

当前默认参数（`run_factors.sh` 选项 5 固定）：

1. `stage2_ic_corr_threshold = 0.8`
2. `per_cluster = 1`
3. `topn = all`

补充说明：

- 你提到的“默认值 > 0.8”在当前入口不是这样；当前固定就是 `0.8`（不是大于 0.8）。

输出：`*_stage3.json`

---

## 5. 产物命名与 manifest

`run_factors.sh` 选项 5 产物命名：

1. `..._n<count>_<YYYYMMDD_HHMMSS>_stage0.json`
2. `..._n<count>_<YYYYMMDD_HHMMSS>_stage1.json`
3. `..._n<count>_<YYYYMMDD_HHMMSS>_stage2.json`
4. `..._n<count>_<YYYYMMDD_HHMMSS>_stage3.json`
5. `..._n<count>_<YYYYMMDD_HHMMSS>_manifest.json`

`manifest.json` 记录每阶段：

1. `input`
2. `kept`
3. `dropped`
4. `reasons`
5. `path`

用于横向对比阶段压缩效果与问题定位。

---

## 6. 推荐操作顺序

### 场景 A：多实验合池再过滤

1. `3) [MERGE]`（选 `all` 或指定 ids）
2. `5) [FILTER]`（后续计划；当前请直接运行 `select_factors.py` 或 `run_backtest_safe.sh --factors-filter`）
3. 需要时 `4) [CACHE]` 补齐/修复缓存

### 场景 B：单库快速过滤

1. `5) [FILTER]`（后续计划；当前请直接运行 `select_factors.py` 或 `run_backtest_safe.sh --factors-filter`）
2. 只想对照可选 `all stages + manifest`
3. 只要最终集合可选 `stage3`

---

## 7. 相关文件清单

1. 交互入口：`scripts/run_factors.sh`
2. 合并脚本：`scripts/factor_filtering/merge_factor_libraries.py`
3. 过滤脚本：`scripts/factor_filtering/select_factors.py`
4. 缓存修复：`scripts/factor_filtering/repair_factor_cache.py`

---

## 8. TODO-FIX（后续清理/弃用）

以下是当前“新逻辑与旧逻辑并存”的冲突点，建议后续分阶段收敛：

1. 过滤入口未统一（优先级最高）
   - 当前入口：`scripts/run_backtest_safe.sh --factors-filter` 或直接运行 `scripts/factor_filtering/select_factors.py`
   - 计划入口：`scripts/run_factors.sh` 后续整合 `FILTER（stage0→stage3）`
   - 问题：参数默认值、输出命名、稳定别名策略不一致，容易造成结果口径混乱。
   - 建议：先把 `FILTER` 整合进 `run_factors.sh`，再考虑对旧入口加 deprecation 提示并计划移除。

2. 缓存修复脚本重复
   - 候选 A：`scripts/fix_missing_factors.py`
   - 候选 B：`scripts/factor_filtering/repair_factor_cache.py`
   - 问题：能力重叠，维护成本高；B 的能力更完整（invalid_read/invalid_index/delete/recompute）。
   - 建议：保留 `repair_factor_cache.py`，逐步弃用 `fix_missing_factors.py`。

3. 结果查看入口重复（次优先）
   - 入口 A：`scripts/view_results.sh`（包装器）
   - 入口 B：`scripts/run_backtest_safe.sh --view-results`
   - 问题：功能重叠，用户不清楚应走哪个入口。
   - 建议：二选一作为唯一入口，另一侧仅保留跳转或弃用提示。

4. 文档口径待统一
   - 风险：README / SPECS / 本文档若同时描述两套入口，容易出现“文档先后不一致”。
   - 建议：完成上述 1~3 收敛后，同步统一文档口径，只保留最终入口。

5. AST 公式去重的“误杀”兜底复核（后续考虑）
   - 背景：`expr_dedup_method=ast`（Stage-0/Stage-1）可能在极少数表达式上产生误杀风险（parser/canonicalize 边界）。
   - 想法：对“被公式去重丢弃”的因子做保底审计：
     1) 优先做数值一致性复核（cache 可用时直接比对/抽样比对）。
     2) 数值复核不可用时再用 LLM 兜底判断等价性，输出误杀报告（默认不自动捞回）。
