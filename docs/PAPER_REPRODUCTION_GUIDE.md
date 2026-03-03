# QuantaAlpha 论文全量复现指南 (Paper Reproduction Guide)

本文档整理了如何**完全复现**《QuantaAlpha: An Evolutionary Framework for LLM-Driven Alpha Mining》论文中主实验的具体步骤与相关配置。

---

## 1. 环境与数据预备检查

在启动全量演化挖掘之前，必须确保底层数据和环境已正确挂载：

*   **环境依赖**：推荐使用 `uv` 提供虚拟环境支持（即 `.venv`，搭配 Python 3.12）。
*   **基础配置文件 (`.env`)**：确保填写了有效的 LLM 调用 Key 与接口地址。由于涉及大量去重算子匹配，强烈建议配置好 Embedding 服务（例如 `text-embedding-3-small`）。
*   **数据资产状态**：
    *   **Qlib 基本面市场数据**：解压于 `data/qlib/cn_data` 目录下（含 `calendars`, `features`, `instruments` 文件夹）。
    *   **全样本量价 HDF5 数据**：放置于 `git_ignore_folder/factor_implementation_source_data/daily_pv.h5`。这部分数据大小约为 398MB。
    *   **抽样测试 HDF5 数据**：放置于 `git_ignore_folder/factor_implementation_source_data_debug/daily_pv.h5`（务必确认已经将原本带 `_debug` 后缀的文件更名以保障脚本对齐）。

---

## 2. 快速启动与复现脚本 (Quick Start Scripts)

为了方便直接运行复现，本仓库提供了三个层级的启动脚本。您可以直接复制对应的命令到终端执行。
此外，复现后建议使用 `./scripts/run_factors.sh` 做因子库管理：
- `1` 列表汇总（`n`、`H/M/L`、`ARR(p50)`）
- `2` 按 id 删除（支持 `1+3+5`）
- `3` 按 id 合并（支持 `1+2` 或 `all`；可选 `zoo-method=ast|norm|both|none`，输出文件自动带 `n` 和时间戳，并输出 `FACTOR_CoSTEER_FACTOR_ZOO_PATH` 导出提示）
- `5` 按 id 执行可观测过滤流水线（`stage0→stage3`；可选只导出某个 stage 或 all，输出带 stage 后缀，并生成 `manifest.json`；默认固定 `expr_dedup=ast`、`stage3_topn=all` 与标准输出前缀）

### 脚本 0：冒烟测试 — 优先跑这一步（`minirun.sh`）

> **用途**：验证环境、LLM 调用、数据读取全链路是否通畅，只跑最基础的 2 个回合。  
> **强烈建议**：每次换模型 / 换配置 / 换机器前，先用此脚本快速验证，再启动正式实验。

```bash
# 基础冒烟测试
./minirun.sh "价量因子测试" "smoke_test"

# 冒烟 + 低磁盘模式（推荐，避免测试产生大量缓存）
./minirun.sh --low-disk "价量因子测试" "smoke_test"

# 冒烟 + 低磁盘 + Zoo 去重（验证 --zoo-dedup 工作是否正常）
./minirun.sh --low-disk --zoo-dedup "价量因子测试" "smoke_test"
```

> **说明**：`minirun.sh` 默认使用轻量配置 `configs/experiment_smoke.yaml`，仅作验证，不产出有效因子。

---

### 脚本 1：推荐安全模式（Macbook M3 16G / 100G 磁盘专项）

> **用途**：专为空间有限的个人电脑安全跑完 11 轮主实验设计。  
> **机制**：
> 1. 强制走 `--low-disk` 模式，算完因子自动清理几十 GB 的缓存文件。
> 2. 强制走 `--relay` 接力模式（默认每 6 轮存盘并退出，第二次启动同一命令自动补齐剩余轮次）。
> 3. 已指定专用配置文件（清理庞大演化历史废料，因子假设=3）。

```bash
# 接力模式机制说明：
# - 第 1 次执行：跑前 6 轮（默认取 evolution.relay_chunk_rounds=6）
# - 第 2 次执行：同一命令，自动补齐剩余所有轮次（无需改命令）
# - 按模型区分后缀便于横向比较，例如 deepseek_v3_11r, gpt4o_11r 等

# 基础安全模式（推荐入门）
./run.sh --low-disk --relay "Price-Volume Factor Mining" "deepseek_v3_11r"

# 安全模式 + Zoo 去重（推荐：有历史实验数据时使用，自动跳过已探索过的因子表达式）
# 前置步骤：首次需先初始化 Zoo（仅首次，此后每轮实验自动更新）：
#   .venv/bin/python scripts/update_factor_zoo.py build
./run.sh --low-disk --relay --zoo-dedup "Price-Volume Factor Mining" "deepseek_v3_11r"
```

> **Zoo 去重说明**：
> - `--zoo-dedup` 会在 calculate/backtest 前将每条因子表达式与 `data/factorlib/factor_zoo.csv` 进行去重，跳过已在历史实验中探索过的表达式，避免重复计算。
> - 实验结束后自动调用 `scripts/update_factor_zoo.py update`，将本次新因子追加到 Zoo，下次运行即可复用。
> - **初次使用前**需先执行 `build` 初始化 Zoo（或使用 `status` 查看当前状态）：
>   ```bash
>   .venv/bin/python scripts/update_factor_zoo.py build    # 全量重建（首次）
>   .venv/bin/python scripts/update_factor_zoo.py status   # 查看 Zoo 统计
>   ```

---

### 脚本 2：土豪拉满模式（23 轮 — 完整论文复现）

> **用途**：完全对齐论文 11-12 Iterations 最佳权衡点（对应代码 23 轮）。  
> **要求**：磁盘 20-30GB+ 剩余，API 预算 $150–$350，时间约 30 小时（4 段 × 6–8h）。

#### 第 1 步：清理历史数据（推荐，避免旧实验残留混入）

```bash
./scripts/safe_cleanup.sh
```

> 清理内容：log、workspace、pickle cache、minirun 临时文件。**不会动** factorlib 因子库、Qlib 数据、Zoo 文件。

#### 第 2 步：直接启动（默认每段 6 rounds，接力 4 次跑完 23 轮）

```bash
# 自动读取底层的 6 轮断点机制和 23 轮总长，每次只需重复执行这同一条命令即可
EXPERIMENT_ID="paper_repro_23r" ./run.sh --low-disk --relay --zoo-dedup "Price-Volume Factor Mining" "paper_repro_23r" 2>&1 | tee -a run_23r.log
```

- `--zoo-dedup`：跳过历史已探索因子（已有 466 个表达式），加速挖掘
- `--relay`：基于底层的 6 rounds 自动存盘退出机制，跑完后只需再次执行本命令即可自动接续
- 首次运行前若要初始化 Zoo：`.venv/bin/python scripts/update_factor_zoo.py build`

> **纯净对照版（无优化，还原论文基线）：**
> 不使用 `--zoo-dedup`，完全从零探索，严格对齐论文：
> ```bash
> EXPERIMENT_ID="paper_repro_23r2" ./run.sh --low-disk --relay "Price-Volume Factor Mining" "paper_repro_23r2" 2>&1 | tee -a run_23r2.log
> ```


---

### 2.1 底层满配参数说明 (configs/experiment.yaml)

为了避免配置混乱，**本项目已统一使用 `configs/experiment.yaml` 作为唯一配置入口，并将论文满血版参数作为推荐默认值**。
在执行复现时，建议对比以下两种模式（在 `experiment.yaml` 中设置）：

| 参数项 (Parameter) | **深度模式 (Depth Mode) - 严格复现** | **平衡模式 (Balanced Mode) - 当前默认** |
| :--- | :--- | :--- |
| `planning.num_directions` | **5** (种子方向更聚焦) | 10 (探索更广) |
| `evolution.max_rounds` | **23** (对齐论文 11-12 Iterations) | 23 (对齐论文) |
| `evolution.crossover_n` | **5** (每轮产生因子较少) | 10 (每轮产生因子较多) |
| `selection_strategy` | `best` (严格按表现筛选) | `best` (按表现筛选) |
| **预期产出** | 约 350 个因子 | 约 700+ 个因子 |

**为什么要定 23 轮？**
- 论文中 1 个 Iteration = `Mutation` + `Crossover` 两个阶段。
- 代码中 1 个 Round = 1 个单阶段（Phase）。
- *论文最优 Trade-off*：收益与风险在 11-12 Iterations 达到平衡，换算到代码就是 **23 轮**（1 次 Original + 11 次 Mutation + 11 次 Crossover）。为了防崩溃，底层强制每 6 轮断点落盘。

> *注意：其它配置如基于 Alpha158 模板生成的因子过滤规则等均不需要变动。*

### 2.0 术语与层级（强烈建议先对齐这段）

QuantaAlpha 的演化流程中，“round/direction/task/step”很容易混淆。以下是**层级、顺序、数量**（以当前默认复现配置为例：`planning.num_directions=10`, `evolution.max_rounds=11`, `steps_per_loop=5`, `evolution.crossover_n=10`, `evolution.max_empty_retries=1`）：

1. **Experiment（一次实验）**
   - 你启动一次 `./run.sh ...`（绑定一个 `EXPERIMENT_ID`）就是 1 个 experiment。

2. **Direction（探索方向）**
   - 数量：`planning.num_directions=10`
   - 含义：planning 生成的 10 条“研究方向文本”（主要驱动 original/mutation 的提示）。

3. **Round + Phase（演化轮次与阶段）**
    - 重要：这里的 **round 是 controller 的 phase-round**，即每跑完一个 phase（original/mutation/crossover）才会 `round += 1`，并不是“一个 iteration=original+mutation+crossover”。
    - 当 `mutation_enabled=true && crossover_enabled=true` 时，phase 顺序通常是：
      - `round 0 = original`
      - `round 1 = mutation`
      - `round 2 = crossover`
      - `round 3 = mutation`
      - `round 4 = crossover`
      - ...交替进行。
    - 论文中的**1个 Iteration = 2个 Rounds**（一次 mutation 加上一次 crossover）。
    - **主实验（5 Iterations）**对应：`1 次 original + 5 次 mutation + 5 次 crossover` = `11 Rounds`。
    - **最优探索（11 Iterations）**对应：`1 次 original + 11 次 mutation + 11 次 crossover` = `23 Rounds`。

4. **Task (任务单元)**  & **Step (单步骤)** & **Attempt (尝试)**
   - **注意**：Task / Step / Attempt **并不是**演进层级的概念。它们只是代码里为了**分布式执行、错误重试、或者给日志打标签**抽象出来的执行层概念。
   - **Task**：日志目录里的最小单元。标识为：`{phase}_{round:02d}_{direction_id:02d}`（例如 `crossover_06_03`）。它的范围是“执行单次 phase 内的一条完整链路”。
     - 链路里固定走 5 个 **Step**：`propose -> construct -> calculate -> backtest -> feedback`。
   - **Attempt**：如果这个 Task 里的 LLM 返空了，触发的内部原位重试就是一次 attempt（由 `evolution.max_empty_retries=1` 控制）。

### 2.1 建议：先做配置预检（仅告警，不阻断）

从当前版本开始，`run.sh` 会自动执行预检；也可以手工先跑一次：

```bash
python scripts/preflight_check.py experiment --config configs/experiment.yaml
```

预检会提示常见复现偏差风险，例如：

- `evolution.crossover_n` 过低导致分支快速塌缩
- `factor.*` 段落与主流程接线不一致（仅提示，不改行为）
- `quality_gate` 中部分开关当前未完整透传（仅提示）

### 2.2 第二轮优化新增配置（可选，非论文原始基线默认）

如果你的目标是“提速且不降质量”，可开启以下 `llm.*` 运行时选项（均已在 `configs/experiment.yaml` 提供）：

```yaml
llm:
  # [Optimization Added, not original baseline defaults]
  json_mode_strict: true
  json_mode_temperature: 0.5
  freeform_temperature: 0.5
  json_mode_response_format: json_object
  json_mode_json_schema: ""
  request_timeout_s: 60.0
  retry_backoff: exponential
  retry_jitter: true
  retry_max_wait_seconds: 30.0
  failover_base_urls: []
```

### 2.3 优化 A/B 测试（推荐流程，先验证再启用）

说明：

- 下述优化都属于“非论文基线默认”。为了避免复现偏差，建议先做 A/B，再决定是否在主复现配置中开启。
- 本仓库提供了一个 A/B 驱动脚本：`scripts/abtest_experiment.py`。
- 产物隔离（方案 A）：脚本会把 workspace/pickle cache 放到 `/tmp/quanta_abtest_results/...`，把运行日志/doctor 报告放到 `/tmp/quanta_abtests/...`，避免污染主复现产物目录。
- LLM 相关 A/B 需要真实 API 可用；如果你在受限/沙盒环境运行，可能出现 “Connection error / DNS 失败”，这不是优化本身失败，换到本机正常网络终端再跑即可。

固定对照命令模板（请保持 direction 与 base-config 一致）：

```bash
cd /Users/ron/Documents/QuantaAlpha
```

#### A/B #1：`cheap_filter + duplicate_exact`（3.11 + 3.15）

只改变 `quality_gate.cheap_filter_enabled`（以及 `cheap_filter_require_acceptable`），其他保持一致：

```bash
cd /Users/ron/Documents/QuantaAlpha

.venv/bin/python scripts/abtest_experiment.py compare \
  --name opt1_cheap_gate \
  --base-config configs/experiment_smoke.yaml \
  --direction "价量因子挖掘" \
  --step-n 3 \
  --times 3 \
  --set-baseline quality_gate.cheap_filter_enabled=false \
  --set-baseline quality_gate.cheap_filter_require_acceptable=false \
  --set-optimized quality_gate.cheap_filter_enabled=true \
  --set-optimized quality_gate.cheap_filter_require_acceptable=true
```

记录结果：

- 重点对比：`elapsed_s_median`、doctor 中的失败原因分布、以及是否出现 `skip_reason=duplicate_exact` 等信号。
- 运行日志与 doctor 报告默认落在 `/tmp/quanta_abtests/...`（不会污染主复现产物目录）。

结果（2026-02-28，STEP_N=3）：

- baseline（cheap gate 关闭）：`elapsed_s=277.771`
- optimized（cheap gate 开启）：`elapsed_s=415.958`（负优化，+49.8%）
- 详细记录见：`docs/performance_optimization_cn.md` 的 **5.2 opt1**

#### A/B #2：协议层强约束 JSON（3.13）

只改变 `llm.json_mode_strict` 与 `llm.json_mode_response_format`，其他保持一致：

```bash
cd /Users/ron/Documents/QuantaAlpha

.venv/bin/python scripts/abtest_experiment.py compare \
  --name opt2_json_protocol \
  --base-config configs/experiment_smoke.yaml \
  --direction "价量因子挖掘" \
  --step-n 3 \
  --times 3 \
  --set-baseline llm.json_mode_strict=false \
  --set-baseline llm.json_mode_response_format=none \
  --set-optimized llm.json_mode_strict=true \
  --set-optimized llm.json_mode_response_format=json_object
```

记录结果：

- 把两次的 `ABTEST_RESULT=...` 原样保存到本节（含 `run_log` / `doctor_md` 路径）。
- 重点对比：JSON parse/fix 相关失败次数、construct 阶段耗时与重试行为、以及整体 `elapsed_s`。

结果（2026-02-28，STEP_N=3）：

- baseline：`elapsed_s=363.289`
- optimized：`elapsed_s=334.619`（正优化，-7.9%）
- 详细记录见：`docs/performance_optimization_cn.md` 的 **5.3 opt2**

说明：

- 这些选项用于降低 JSON 解析失败与网络尾延迟，不改变因子质量门定义。
- 若需严格贴近“原始基线设置”，可将这些新增选项回退到默认逻辑或关闭。
- 当前版本还包含跨轮次 exact 去重（`duplicate_exact`）：仅在启用 cheap gate 时生效；在 `factor_calculate/factor_backtest` 前若命中历史已见表达式，会标记 `skip_reason=duplicate_exact` 并跳过重复计算。

---

## 3. 标准运行及日志保存命令

全量复现将会发出大量 LLM 并发请求并在后台大量训练、回测因子。如果你需要保留全程所有的屏幕回显用于事后 Debug，推荐使用 Linux 的重定向和 `tee` 工具。

在项目的根目录下执行对应的终端启动指令：

```bash
# 推荐：固定 EXPERIMENT_ID + 开启 --relay，便于分段接力执行
EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "Price-Volume Factor Mining" "paper_reproduction_r2" 2>&1 | tee run_output_r2.log
```
*   **第一个参数 (`"Price-Volume Factor Mining"`)**: 是系统启动向大模型传递的全局研究引导目标，触发 LLM 在量价数据区间找寻切入点。
*   **第二个参数 (`"paper_reproduction_r2"`)**: 自定义后缀。这会使得最终融合产生的优秀因子池命名为 `all_factors_library_paper_reproduction_r2.json` 以便留存。
*   **low-disk 默认开启**：当前 `run.sh` 默认启用 low-disk；若你要关闭可加 `--no-low-disk`。
*   **命名安全（避免覆盖/混库）**：新一轮实验请同时更换 `EXPERIMENT_ID` 与后缀；复用后缀会写入同一个因子库 JSON，可能混入历史因子。

### 3.1 运行中进度查看（Codex Workflow）

```bash
# 单次快照
./scripts/run_doctor.sh --experiment-id paper_repro_r2

# 持续刷新
./scripts/run_doctor.sh --experiment-id paper_repro_r2 --watch 8

# 单次 doctor 诊断报告（进度 + 报错汇总）
./scripts/run_doctor.sh --experiment-id paper_repro_r2
```

该 workflow 会读取 `evolution_state.json`、`trajectory_pool.json`、任务 `__session__` 快照，以及执行日志 pickle 事件，汇总当前轮次/步骤、已产出因子与报错诊断信息。

---

## 4. 接力模式与续跑模式（独立入口）

这里最容易混淆：`--relay` 和 `--resume` 是两个**独立模式**，而且互斥，不是“同一个模式先后两步”。

### 4.1 接力模式 `--relay`（分段跑）

适用场景：计划分段执行（例如先跑一段 relay chunk，后面再补齐）。

```bash
# 首段接力（当前主配置默认先跑 6 轮）
EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "Price-Volume Factor Mining" "paper_reproduction_r2" 2>&1 | tee run_output_r2.log

# 第二次接力（同一 EXPERIMENT_ID，自动补齐到 max_rounds）
EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "Price-Volume Factor Mining" "paper_reproduction_r2" 2>&1 | tee -a run_output_r2.log
```

当前 `--relay` 调度策略：

- 首段按 `QUANTA_RELAY_CHUNK_ROUNDS` 运行（默认取配置中的 `evolution.relay_chunk_rounds`，当前主配置为 6）
- 后续再次执行 `--relay` 自动补齐到 `evolution.max_rounds`（取当前配置值）

### 4.2 续跑模式 `--resume`（直达目标轮次）

适用场景：已有保存状态，想直接续到目标轮次，不走分段调度。

```bash
EXPERIMENT_ID="paper_repro_r2" ./run.sh --resume "Price-Volume Factor Mining" "paper_reproduction_r2" 2>&1 | tee -a run_output_r2.log
```

`--resume` 严格规则：

- 必须存在 `evolution_state.json`
- 若状态文件不存在，会**直接失败退出**（不会从 round 0 隐式新开）

补充：**task 内细粒度续跑（step 级）**

- 从当前版本开始，`--resume/--relay` 在进入某个 task 时，会优先读取该 task 日志目录下最新的 `__session__` pickle 快照，并从未完成的 step 继续执行。
- 粒度是“step 完成后落盘”。如果中断发生在某个 step 的执行中（例如 `factor_backtest` 过程中被杀掉），续跑会从该 step 重新执行（但不会重跑更早的已完成 step）。

建议：**为了复现稳定性，尽量在“非 LLM 阶段”暂停**

- 5-step 顺序是：`factor_propose(LLM) -> factor_construct(LLM) -> factor_calculate -> factor_backtest -> feedback(LLM)`
- 如果你的目标是“已生成的因子表达式不漂移”（复现更稳定）：
  - 建议在 `factor_calculate` 或 `factor_backtest` 阶段暂停/中断（此时表达式已由 construct 决定，续跑不需要重新生成表达式）。
- 如果你的目标是“后续演化路径也尽量不漂移”（下一轮生成也更一致）：
  - 更严格地建议在 `feedback` 完成之后再暂停（否则续跑可能会重新跑一次 LLM feedback，影响下一轮候选生成）。

### 4.3 防跑偏保护（两种模式共用）

为避免“看似续跑，实际跑偏”，当前版本增加了两层保护：

1. 保存并恢复 `directions`：  
   - 每次 checkpoint 都会把 planning 方向写入 `evolution_state.json`。  
   - 恢复时优先使用该方向集合，避免重新 planning 导致轨迹漂移。
2. 严格配置一致性校验：  
   - 恢复前对比保存配置与当前配置（如 `num_directions`、`max_rounds`、`crossover_n`、`parent_selection_strategy` 等）。  
   - 不一致默认直接失败退出，防止静默跑偏。

若你明确知道风险并要强制恢复，可显式设置：

```bash
QUANTA_FORCE_RELAY_RESUME=1 EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "Price-Volume Factor Mining" "paper_reproduction_r2"
```

### 4.4 恢复来源可追溯日志

成功加载状态后，日志会输出来源信息（用于确认接的是哪一轮）：

```text
Relay resume source: previous_experiment_id=..., state_saved_at_utc=..., previous_log_trace_path=...
```

### 4.5 空分支容错（Zero-Factor Retry）

从当前版本开始，进化任务若出现“0 因子产出”：

1. 自动重试 1 次；
2. 若仍为 0，则将该轨迹标记为 `skipped` 并继续后续轮次（不再静默吞掉）。

对应信息会写入 `trajectory_pool.json` 的 `extra_info` 字段，便于复盘。

---

## 5. 独立回测检验

待数十小时/几天的 `run.sh` 执行完毕，所有的合格因子会被吐出到 `data/factorlib/`。接着，使用独立的回测模块评测这些挖掘出来的联合策略对于真实样本外的涨跌幅影响：

```bash
# 使用刚才生成的 paper_reproduction_r2 json 为基准，拉起全量历史回测：
python -m quantaalpha.backtest.run_backtest \
  -c configs/backtest.yaml \
  --factor-source custom \
  --factor-json data/factorlib/all_factors_library_paper_reproduction_r2.json
```
如果需要在终端查看干跑逻辑（即载入数据和校验语法合法性但不执行重度的 XGBoost/LightGBM 推演），可以在末行补充 `--dry-run -v`。

### 5.1 推荐：使用安全脚本执行（可控资源 + 完整日志）

为避免前端直接回测导致机器高负载，建议优先使用：

```bash
./scripts/run_backtest_safe.sh --interactive
```

关键选项：

- `--threads N`：线程数上限
- `--factors-filter`：只执行过滤链路并退出（不跑回测），用于快速查看“最终剩余因子数”
  - 输出 `experiment / quality_range / final_selected`
  - 结果落盘到 `data/factorlib/selected/<experiment>_factors_filter_q<quality>_n<count>_<timestamp>.json`
  - 同时更新 `data/factorlib/selected/<experiment>_factors_filter_latest.json`
- `--max-factors <N|all|default>`：控制 custom 因子数量
  - `N`：只回测 Top-N（按配置排序指标）
  - `all`：不限制数量
  - `default`：沿用当前配置文件值（默认 `configs/backtest.yaml`）
- `--corr-dedup`：在回测前先做“相关性去重 + 多样性 Top-N”筛选（输出临时库再回测）
  - Stage-1 不做全局 TopN 截断，仅做同簇粗去重，避免过早损失多样性
  - 默认 `--dedup-method two_stage`：Stage-1 暴露相关粗筛 + Stage-2 IC 序列相关精筛
  - `--dedup-linkage complete|connected`：聚类联接策略（默认 `complete`）
  - `--dedup-sample-split train_valid|full`：相关性采样范围（默认 `train_valid`，避免 test 泄漏）
  - `--dedup-stage2-corr-threshold T`：Stage-2 的 IC 序列相关阈值（默认 `0.8`）
  - `--dedup-per-cluster K`：每个相关性簇保留 K 个冠军（默认 3；设为 1 更严格）
  - `--dedup-topn N`：最终保留 N 个因子（未指定时尽量从配置 `custom.max_factors` 推断）
- `--warm-cache`：先同步 `result.h5 -> md5 cache`

默认行为（当前版本）：

- 启动时自动做 backtest 配置预检（仅告警，不阻断）
- `--interactive` 第 1 步目标包含 `EXP / BOB / VIEW / FILTER`
- `--factor-source custom` 且未锁定质量档位时，默认 `quality_min=off`（不做质量预筛选）
  - 若将 `quality_min` 设置为 `low|medium|high`，且显式设置 `--max-factors N`，则顺序为：`质量筛选 -> max_factors 截断`
  - 可通过环境变量覆盖：`BACKTEST_MIN_QUALITY=off|low|medium|high|auto`
    - `auto`：当前等价于 `off`
- BOB 模式下 `--bob-metric auto` 先解析本次运行的统一主指标，再执行排序（避免跨指标量纲混排）
- 安全脚本临时文件在正常退出与中断场景都会自动清理

输出结果文件会包含“实际因子数 + 北京时间戳”，避免同名覆盖：

- `<library>_n<num_factors>_<YYYYMMDD_HHMMSS>_backtest_metrics.json`
- `<library>_n<num_factors>_<YYYYMMDD_HHMMSS>_cumulative_excess.csv`

---

## 6. 论文基准指标参考 (Paper Benchmark Reference)

为了评估你复现出的因子库效果，你可以将其与论文中报告的主实验性能（即 QuantaAlpha 的目标基准）进行对比。

**论文主实验报告的核心指标基准**：

| 评估维度 (Dimension) | 核心评估指标 (Metric) | 论文原报性能 (Performance) |
| :---: | :---: | :---: |
| **预测能力 (Predictive Power)** | Information Coefficient (IC) | **0.1501** |
| | Rank IC | **0.1465** |
| **组合收益 (Strategy Return)** | 超额年化收益 (Annualized Excess Return) | **27.75%** |
| | 超额最大回撤 (Max Drawdown) | **7.98%** |
| | 卡尔玛比率 (Calmar Ratio) | **3.4774** |

*(详细对比曲线图可以参考项目 `README.md` 中的 `Key Results` 部分或 `docs/images/主实验.png`)*

如果你需要自行运行论文中作为对照组的传统机器学习基准，以观察相同回测环境下的表现差距，可以使用独立回测模块运行 Qlib 内置因子库：

```bash
# 回测 Alpha158(20) 对照组基准：
python -m quantaalpha.backtest.run_backtest \
  -c configs/backtest.yaml \
  --factor-source alpha158_20

# 回测 Alpha158 完整对照组基准：
python -m quantaalpha.backtest.run_backtest \
  -c configs/backtest.yaml \
  --factor-source alpha158
```

同样地，运行完毕后会生成对应的 `_backtest_metrics.json` 和 `_cumulative_excess.csv`。你可以将其与此前生成的复现指标进行公平对比。

---

## 7. 关键说明：`run.sh` 回测 vs 前端“开始回测”

这两个流程**不是同一条执行链路**，请勿混为一谈。

1. `run.sh` 中的回测（挖掘内回测）
   - 入口：`quantaalpha mine ...`
   - 作用：在因子挖掘/进化过程中做快速打分和反馈，用于筛选候选因子。
   - 配置来源：`quantaalpha/factors/factor_template/conf_baseline.yaml` 与 `quantaalpha/factors/factor_template/conf_combined_factors.yaml`
   - 组合策略回测窗口（默认）：`2021-01-01 ~ 2021-12-31`

2. 前端“开始回测”（独立回测）
   - 前端调用：`POST /api/v1/backtest/start`
   - 后端实际启动命令：
     ```bash
     python -m quantaalpha.backtest.run_backtest \
       -c configs/backtest.yaml \
       --factor-source custom|combined \
       --factor-json <factor_json_path> \
       --skip-uncached -v
     ```
   - 作用：对已产出的因子库做独立评估（样本外验证）。
   - 配置来源：`configs/backtest.yaml`
   - 组合策略回测窗口（默认）：`2022-01-01 ~ 2025-12-26`

结论：`run.sh` 回测用于“挖掘时的阶段性筛选”，前端独立回测用于“最终样本外评估”。

补充：前端“独立回测”页面支持“加载离线结果”并可在下拉框选择具体历史轮次；不选择时默认加载最新一轮。

---

## 8. 高负载与崩溃排查建议（macOS）

当复现过程中出现“机器卡死/重启后仍高 CPU”时，优先确认是否是系统索引而非回测残留。

1. 先查是否还有项目残留进程
   ```bash
   ps -ax -o pid=,ppid=,%cpu=,%mem=,etime=,command= | rg -i "quantaalpha|backtest|minirun|run.sh|python|uv"
   ```
2. 再查系统高占用是否来自 `mds/mdworker`（Spotlight 索引）
   ```bash
   ps -ax -o pid=,%cpu=,etime=,command= | rg -i "mds|mdworker|spotlight"
   ```
3. 临时止血（可选）
   ```bash
   sudo mdutil -a -i off && sudo killall mds mds_stores mdworker_shared
   ```
4. 恢复索引（任务稳定后）
   ```bash
   sudo mdutil -a -i on
   ```
5. 建议为回测限制线程，降低 OOM/过热风险
   ```bash
   export OMP_NUM_THREADS=4
   export MKL_NUM_THREADS=4
   export OPENBLAS_NUM_THREADS=4
   export NUMEXPR_NUM_THREADS=4
   ```

## 9. 核心技术细节与评价标准 (Technical Details & Evaluation Standards)

为了确保复现的严谨性，请注意以下文档中识别的关键细节：

### 9.1 评价指标：全是“超额” (Excess Metrics Only)
⚠️ **重要**：复现过程中看到的所有收益指标（Annualized Return, Max Drawdown, IR, Calmar）**均为超额指标**（相对于沪深300指数）。
- **超额收益** = 组合收益 - 基准收益 - 交易成本。
- 如果年化收益显示为 15%，这意味着你的因子组合每年跑赢沪深300 **15个百分点**，而不是总收益 15%。

### 9.2 复杂度正则化 (Complexity Regularization)
系统通过 `FactorRegulator` 严格限制因子的“过拟合”风险，这是复现论文中“鲁棒因子”的关键：
- **符号长度 (SL)**：单个因子表达式字符数 ≤ 300。
- **基础特征数 (ER)**：单个因子最多引用 6 个基础量价指标（如 $close, $volume 等）。
- **自由参数比例**：数值常量（如 10, 20, 0.5）在表达式中的占比需 < 50%。
- **重复性校验**：新因子与已有因子的重复子树大小不能超过阈值（通常为 8）。

### 9.3 基础因子 (Base Factors)
在挖掘时的初步回测阶段，新因子会与以下 **4 个基础因子** 组合进行评估：
1. `OPEN_RET`: `($close-$open)/$open` (日内涨幅)
2. `VOL_RATIO`: `$volume/Mean($volume, 20)` (量比)
3. `RANGE_RET`: `($high-$low)/Ref($close, 1)` (振幅)
4. `CLOSE_RET`: `$close/Ref($close, 1)-1` (涨跌幅)

### 9.4 时间周期 (Time Periods)
请确保你的数据覆盖以下三个标准区间：
- **训练集 (2016-01-01 ~ 2020-12-31)**：模型学习历史规律。
- **验证集 (2021-01-01 ~ 2021-12-31)**：挖掘过程中的初步筛选（对应 `round` 评估）。
- **测试集 (2022-01-01 ~ 2025-12-26)**：样本外最终评估（对应“独立回测”）。
