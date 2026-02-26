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

## 2. 复现参数修改 (configs/experiment.yaml)

为了实现论文中 **"发散10个子方向种子，并通过突变交叉演化11轮"** 的最大规模实验配置，你需要对默认项目配置做以下调整。打开 `configs/experiment.yaml`：

1.  **初始探索规模调大（10个并发方向）**：
    找到 `planning` 配置区，将子方向数提高：
    ```yaml
    planning:
      enabled: true
      num_directions: 10   # 从默认的 2 改为论文标准 10
    ```
2.  **演化回合数补全（5个 Epoch 合计 11 轮）**：
    找到 `evolution` 配置区，将最大回合次数提高：
    ```yaml
    evolution:
      enabled: true
      mutation_enabled: true
      crossover_enabled: true
      max_rounds: 11       # 从默认的 3 改为论文标准 11（首发 1 轮 + 5x交替的突变/交叉=10）
    ```

> *注意：其它默认配置如基于 Alpha158 模板生成的因子过滤规则、测试回合数据集划分（2016-2020 训练，2021 验证），以及独立回测阶段配置（2022-2025 样本外测试）等均不需要变动。*

### 2.1 建议：先做配置预检（仅告警，不阻断）

从当前版本开始，`run.sh` 会自动执行预检；也可以手工先跑一次：

```bash
python scripts/preflight_check.py experiment --config configs/experiment.yaml
```

预检会提示常见复现偏差风险，例如：

- `evolution.crossover_n` 过低导致分支快速塌缩
- `factor.*` 段落与主流程接线不一致（仅提示，不改行为）
- `quality_gate` 中部分开关当前未完整透传（仅提示）

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

---

## 4. 接力模式与续跑模式（独立入口）

这里最容易混淆：`--relay` 和 `--resume` 是两个**独立模式**，而且互斥，不是“同一个模式先后两步”。

### 4.1 接力模式 `--relay`（分段跑）

适用场景：计划分段执行（例如先跑 5 轮，后面再补齐）。

```bash
# 首段接力（默认先跑 5 轮）
EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "Price-Volume Factor Mining" "paper_reproduction_r2" 2>&1 | tee run_output_r2.log

# 第二次接力（同一 EXPERIMENT_ID，自动补齐到 max_rounds）
EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "Price-Volume Factor Mining" "paper_reproduction_r2" 2>&1 | tee -a run_output_r2.log
```

当前 `--relay` 调度策略：

- 首段按 `QUANTA_RELAY_CHUNK_ROUNDS` 运行（默认 5）
- 后续再次执行 `--relay` 自动补齐到 `evolution.max_rounds`（默认 11）

### 4.2 续跑模式 `--resume`（直达目标轮次）

适用场景：已有保存状态，想直接续到目标轮次，不走分段调度。

```bash
EXPERIMENT_ID="paper_repro_r2" ./run.sh --resume "Price-Volume Factor Mining" "paper_reproduction_r2" 2>&1 | tee -a run_output_r2.log
```

`--resume` 严格规则：

- 必须存在 `evolution_state.json`
- 若状态文件不存在，会**直接失败退出**（不会从 round 0 隐式新开）

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

- `--mode limited|performance`：资源模式（笔记本建议 `limited`）
- `--threads N`：线程数上限
- `--max-factors <N|all|default>`：控制 custom 因子数量
  - `N`：只回测 Top-N（按配置排序指标）
  - `all`：不限制数量
  - `default`：沿用配置文件（`backtest_limited.yaml` 默认为 50）
- `--warm-cache`：先同步 `result.h5 -> md5 cache`

默认行为（当前版本）：

- 启动时自动做 backtest 配置预检（仅告警，不阻断）
- `--mode limited` + `--factor-source custom` 时，默认执行“质量先筛选，再 TopN”
  - 默认质量阈值：`high`
  - 顺序：`质量筛选 -> max_factors 截断`
  - 可通过环境变量覆盖：`BACKTEST_MIN_QUALITY=off|low|medium|high|auto`
    - `auto`：`limited=high`，`performance=off`
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
