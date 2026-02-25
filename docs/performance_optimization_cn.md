# QuantaAlpha 本地运行效率优化建议（基于最新一轮日志）

更新时间：2026-02-23  
适用环境：本机 `uv + .venv + Python 3.12`，`minirun.sh` 流程

---

## 1. 现状基线（来自最近有效日志）

基线日志目录：`log/2026-02-23_21-44-05-178359`

本轮（`STEP_N=3`）分步耗时：

- `factor_propose`：23.93s（约 9.6%）
- `factor_construct`：71.06s（约 28.4%）
- `factor_calculate`：155.16s（约 62.0%）
- 合计：250.14s

结论：瓶颈主要在 `factor_calculate`（占比最高）。

---

## 2. 优先级最高的优化项

### 2.1 降低 CoSTEER 调试循环次数（最高收益）

`factor_calculate` 内部会跑调试循环（你终端里看到的 `Debugging 10/10`），默认 10 轮。

建议先降到 3 轮：

```env
CoSTEER_MAX_LOOP=3
```

预期：`factor_calculate` 耗时显著下降，通常可减少 40% 以上（依赖候选因子质量和网络）。

---

### 2.2 降低失败任务重试上限（减少无效尝试）

默认失败任务试错上限较高，可先收紧：

```env
CoSTEER_FAIL_TASK_TRIAL_LIMIT=6
```

预期：在候选质量较差时减少空耗时长。

---

### 2.3 开启 coder 缓存（重复试验提速）

针对同方向、同配置反复试验，建议打开：

```env
CoSTEER_CODER_USE_CACHE=True
```

预期：重复运行时明显提速，尤其 `factor_calculate` 阶段。

---

## 3. 次优先级优化项

### 3.1 缩短 LLM 失败等待时间

网络波动时，重试等待会拉长总耗时。可先调为：

```env
MAX_RETRY=3
RETRY_WAIT_SECONDS=2
```

说明：这是“失败快退”策略，优点是更快暴露问题，缺点是弱网下成功率可能略降。

---

### 3.2 先 smoke，再 full run

推荐流程：

1. `./minirun.sh`（默认 `STEP_N=3`，验证环境、数据、LLM连通性）
2. `STEP_N=5 ./minirun.sh`（验证能走到反馈/写库）
3. 再执行完整 `run.sh`

这样可以避免直接全量跑导致长时间后才发现基础问题。

---

## 4. 不建议优先处理的日志项

- `ModuleNotFoundError. CatBoostModel/XGBModel are skipped`：可选模型提示，当前 LightGBM 主流程不受影响。
- `No valid experiment found. Create a new experiment`：qlib 常见提示，通常表示新建实验记录，不是失败。

---

## 5. 建议直接写入 `.env` 的优化组合（第一版）

```env
CoSTEER_MAX_LOOP=3
CoSTEER_FAIL_TASK_TRIAL_LIMIT=6
CoSTEER_CODER_USE_CACHE=True
MAX_RETRY=3
RETRY_WAIT_SECONDS=2
```

---

## 6. 如何验证优化有效

每次调整后，固定用同一命令做对比：

```bash
./minirun.sh
```

对比指标：

- `factor_calculate took ...s`
- `Workflow Progress` 到第 3 步总耗时
- 通过率：`Final decisions: [..] (x/n passed)`

如果耗时下降但通过率大幅下降，可把 `CoSTEER_MAX_LOOP` 从 3 回调到 4~5。

