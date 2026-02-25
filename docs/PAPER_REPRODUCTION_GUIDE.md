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

---

## 3. 标准运行及日志保存命令

全量复现将会发出大量 LLM 并发请求并在后台大量训练、回测因子。如果你需要保留全程所有的屏幕回显用于事后 Debug，推荐使用 Linux 的重定向和 `tee` 工具。

在项目的根目录下执行对应的终端启动指令：

```bash
# 执行完整实验，并将过程中的所有标准输出与错误信息写入 run_output.log 并实时在终端放映保存：
./run.sh "Price-Volume Factor Mining" "paper_reproduction" 2>&1 | tee run_output.log
```
*   **第一个参数 (`"Price-Volume Factor Mining"`)**: 是系统启动向大模型传递的全局研究引导目标，触发 LLM 在量价数据区间找寻切入点。
*   **第二个参数 (`"paper_reproduction"`)**: 自定义后缀。这会使得最终融合产生的优秀因子池命名为 `all_factors_library_paper_reproduction.json` 以便留存。

---

## 4. 断点续跑功能 (Resume Mechanism)

复现实验若因为网络中断、接口限流等异常挂掉（如 `KeyboardInterrupt` / `Timeout`）退出，无需清空任务从头再来，系统内建了直接查验已完成因子断点的接续机制。

### 配置接续模式：
在 `configs/experiment.yaml` 中，关闭“每次开启清空数据”开关：

```yaml
evolution:
  # ... (其他配置保持不变)
  fresh_start: false  # 【关键】从 true 改为 false，确保从本地缓存中加载断点
```

### 传入原始中断的任务 ID 启动：
在跑批崩溃后，你可以前往 `data/results/` 目录查看中断的目录名，提取出形如 `exp_20260224_161131` 的任务 ID。利用这个 ID 设定环境变量拉起服务：

```bash
# 找到中断之前的 ID 并续跑，使用 -a 实现日志续写：
EXPERIMENT_ID="exp_20260224_161131" ./run.sh "Price-Volume Factor Mining" "paper_reproduction" 2>&1 | tee -a run_output.log
```

---

## 5. 独立回测检验

待数十小时/几天的 `run.sh` 执行完毕，所有的合格因子会被吐出到 `data/factorlib/`。接着，使用独立的回测模块评测这些挖掘出来的联合策略对于真实样本外的涨跌幅影响：

```bash
# 使用刚才生成的 paper_reproduction json 为基准，拉起全量历史回测：
python -m quantaalpha.backtest.run_backtest \
  -c configs/backtest.yaml \
  --factor-source custom \
  --factor-json data/factorlib/all_factors_library_paper_reproduction.json
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

输出结果文件会包含“实际因子数 + 北京时间戳”，避免同名覆盖：

- `<library>_n<num_factors>_<YYYYMMDD_HHMMSS>_backtest_metrics.json`
- `<library>_n<num_factors>_<YYYYMMDD_HHMMSS>_cumulative_excess.csv`

---

## 6. 关键说明：`run.sh` 回测 vs 前端“开始回测”

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

## 7. 高负载与崩溃排查建议（macOS）

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
