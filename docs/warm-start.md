# Warm-start 最小改动方案（黑名单去重）

本文总结当前仓库里可直接使用的 warm-start / zoo 去重能力，目标是：
- 改动最少；
- 直接用历史因子做黑名单过滤；
- 继续用 ChatGPT 挖新因子。

## 1. 结论

你现在的思路是可行且改动最少的路径：
1. 先把前几轮实验因子合并；
2. 做 AST 去重得到黑名单 CSV；
3. 在 `run.sh` 前注入 `FACTOR_CoSTEER_FACTOR_ZOO_PATH`；
4. 不改主流程代码，直接继续跑。

额外确认：
- 当前仓库的 warm-start 脚本（`scripts/prepare_warm_start_assets.py`）是“离线产出资产”，默认不会自动接入 `run.sh` 主流程。

## 2. 关键参数说明

### 2.1 `--zoo-dedup` 的“自动更新”是什么意思

当你使用 `run.sh --zoo-dedup` 时：
1. 运行前：`run.sh` 会设置 `FACTOR_CoSTEER_FACTOR_ZOO_PATH` 指向 Zoo CSV；
2. 运行后：会自动执行 `scripts/update_factor_zoo.py update`，把本次新因子追加进 Zoo；
3. 下一次再跑时，会基于更新后的 Zoo 继续过滤。

这意味着：黑名单会“随每次运行自动扩张”。

### 2.2 `chatgpt_only` 是什么

在命令：

```bash
./run.sh "方向" "chatgpt_only"
```

里，`chatgpt_only` 是 `FACTOR_LIBRARY_SUFFIX`（输出库后缀），不是 `EXPERIMENT_ID`。

影响示例：
- 输出文件名可能是 `data/factorlib/all_factors_library_chatgpt_only.json`。

真正控制实验隔离的是 `EXPERIMENT_ID`（不设时自动生成）。

### 2.3 `FACTOR_CoSTEER_FACTOR_ZOO_PATH` 是否会直接生效

会。传入后，构造阶段会直接读取该 CSV 作为去重参考进行过滤。  
CSV 至少需要两列：
- `factor_name`
- `factor_expression`

### 2.4 `--low-disk` 现在有什么区别

当前 `run.sh` 默认已经是 low-disk 开启。  
low-disk 主要行为：
- 关闭 pickle 缓存；
- 使用 parquet 压缩；
- 回测后清理部分临时大文件（如 `result.h5` / 部分 parquet）。

关闭方式是 `--no-low-disk`，通常会占用更多磁盘，但中间产物保留更多，便于排障。

## 3. 两种推荐运行方式

## 3.1 固定黑名单（不自动扩张，最稳定可控）

适合：你希望“先定一版黑名单”，后续运行保持一致口径。

### 第一步：构建 AST 去重黑名单

```bash
.venv/bin/python scripts/factor_filtering/merge_factor_libraries.py \
  --libraries "data/factorlib/all_factors_library*.json" \
  --out data/factorlib/merged/factor_pool_all.json \
  --zoo-method ast --skip-unparsable \
  --zoo-csv data/factorlib/factor_zoo_ast.csv \
  --zoo-json data/factorlib/factor_zoo_ast.json
```

### 第二步：使用固定黑名单直接跑

```bash
FACTOR_CoSTEER_FACTOR_ZOO_PATH=data/factorlib/factor_zoo_ast.csv \
./run.sh --low-disk "价量因子挖掘" "chatgpt_only"
```

注意：此模式下建议不要加 `--zoo-dedup`，避免自动追加改变黑名单。

## 3.2 自动扩张黑名单（省事）

适合：你希望每次跑完自动把新因子并入 Zoo。

```bash
./run.sh --low-disk --zoo-dedup "价量因子挖掘" "chatgpt_only"
```

## 4. 预期收益（token / 计算）

基于当前本地因子库统计：
- 总表达式：`937`
- AST 唯一率：`88.15%`
- AST 重复率：`11.85%`

解释：
1. 黑名单过滤最直接节省的是计算与回测资源；
2. 对 LLM token 的节省通常小于计算侧；
3. 实际 token 下降常见在 `0%~8%`（多数场景约 `3%~5%`），并受重试行为影响。

## 5. 建议默认策略

如果目标是“低风险、可回放、改动最少”，建议默认用：
- 固定黑名单模式（3.1）；
- `--low-disk` 保持开启；
- 用 `suffix`（例如 `chatgpt_only`）分隔输出库。

## 6. A/B Test：`warm-start` vs `blacklist` 模式

目标：
- A 组：只用现有 warm-start（Zoo 去重）；
- B 组：warm-start + subtree blacklist（更激进的坏结构拦截）。

### 6.1 Blacklist 文件格式（JSON）

最小格式（推荐）：

```json
{
  "patterns": [
    {"expr": "delay($close, 1)", "label": "bad_delay"},
    {"expr": "ts_mean($close, 5)", "label": "bad_short_mean"}
  ]
}
```

也支持纯字符串数组：

```json
["delay($close, 1)", "ts_mean($close, 5)"]
```

如果你已经有 Stage1 JSON 或 Zoo CSV，可直接用：

```bash
./scripts/run_factors.sh
# 选择 6) [BLACKLIST] export subtree blacklist JSON
```

脚本会自动导出 `subtree_blacklist.json`，可直接给 `run.sh --blacklist-file` 使用。

### 6.2 直接用 `run.sh` 做 A/B

A 组（warm-start）：

```bash
./run.sh --low-disk --zoo-dedup "价量因子挖掘" "ab_warmstart_a"
```

B 组（warm-start + blacklist）：

```bash
./run.sh --low-disk --zoo-dedup \
  --blacklist-file data/factorlib/subtree_blacklist.json \
  "价量因子挖掘" "ab_warmstart_b"
```

### 6.3 用 `abtest_experiment.py` 对比（推荐）

```bash
.venv/bin/python scripts/abtest_experiment.py compare \
  --name warmstart_vs_blacklist \
  --base-config configs/experiment_smoke.yaml \
  --direction "价量因子挖掘" \
  --step-n 3 \
  --times 3 \
  --set-common quality_gate.subtree_blacklist_path=data/factorlib/subtree_blacklist.json \
  --set-baseline quality_gate.subtree_blacklist_enabled=false \
  --set-optimized quality_gate.subtree_blacklist_enabled=true
```

注意：
1. subtree blacklist 可独立生效，不要求开启 `cheap_filter_enabled`；若同时开启 cheap gate，会在同一前置过滤阶段共同生效。
2. 对比建议优先看 `ABTEST_COMPARISON` 里的 `delta_quality_metrics_median_success`（质量指标）与 `subtree_blacklist_rejected_sum`（是否真的命中）；耗时仅作为次要参考（`delta_elapsed_s_median_success`）。

## 7. 后续落地建议（不破坏主流程的渐进升级）

目标：先把“去重 warm-start”跑稳定，再逐步升级到“坏结构拦截 + 质量闭环”，同时保持 `run.sh` 主模式不被影响。

建议顺序：
1. 先稳定 Zoo 去重：优先把 `--zoo-dedup`（或固定 Zoo CSV）跑通，并用重复率/新增 unique 数验证收益，再讨论更激进的 blacklist。
2. 再做 subtree blacklist（坏结构拦截）：先做“命中验证”（关注 `subtree_blacklist_rejected_sum`），再谈收益；与 Zoo 分工明确（Zoo=跨 run 去重，blacklist=坏结构禁入 calculate/backtest）；同时把 blacklist 资产版本化（日期命名保留 + 固定路径 `data/factorlib/subtree_blacklist.json`）。
3. 预算从“广撒网”转向“精炼”：因子池到 ~400 后，适当降低 `planning.num_directions` 或 `factor.factors_per_hypothesis`，把预算挪给 mutation/crossover 围绕 top-k（通常能更快提升“每 token 的有效改进”）。
4. 真要省 token：仅做后置过滤通常省的是下游 coder/debug/backtest 的 token 与时间；如果要减少 propose/construct 端 token，需要把“禁用结构摘要”写进 prompt，并用 success-only 指标做 A/B（网络不稳时优先看 `*_median_success` 与 `delta_quality_metrics_median_success`）。
