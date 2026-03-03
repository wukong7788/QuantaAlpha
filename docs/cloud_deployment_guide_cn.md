# QuantaAlpha 混合执行云端部署指南（本地挖掘 + 云端回测）

本文档整理了如何通过**“本地慢速挖掘 + 云端高速回测”**的拆分方案，以极低的成本复现 QuantaAlpha 论文 11-12 Iterations（产出多达 350+ 因子）的全量成果。

QuantaAlpha 的演化挖掘过程（即“生出”因子）和下游的投资组合测试（即“将几百个因子合成跑 LightGBM 测试”）在资源消耗上有很大区别。如果你的本地电脑由于内存受限总是 OOM 崩溃，我们将推荐下方的两阶段剥离式流程。

---

## 阶段一：本地执行核心挖掘（探索期）

利用个人电脑（如 Macbook M3 16G）的算力运行大模型交互与因子初步生成，负责慢速“开荒”。

### 1.1 为什么在本地开荒？
*   **低成本挂机**：挖掘 23 轮（约 350 个高阶因子尝试）可能耗时 15～20 个小时。在本地挂机只需保证网络和电源，无需支付按时计费的服务器租金。
*   **性能限制**：本地电脑只有 16G 内存，因此在 `configs/experiment.yaml` 中需要将 `max_parallel_workers` 限制在 2 左右防止内存爆炸。

### 1.2 执行命令
启动终端，使用 `--low-disk` 防止本地硬盘被大量缓存挤爆，并带上 `--relay` 防断线：
```bash
CONFIG=configs/experiment.yaml ./run.sh --low-disk --relay "价量因子挖掘" "mac_run_01"
```
* **阶段一产物**：经过漫长的大模型交流运行，你会在本地根目录得到一个包含所有因子代码和单次回测收益特征的 JSON 文件（如 `all_factors_library_mac_run_01.json`）；同时，在 `data/results/factor_cache/` 目录下会积累几十个小时算出的因子日频特征缓存文件（.parquet）。

---

## 阶段二：云端模型融合与深度测试（验证期）

拿到 350 个因子后，如果要在多年份全样本上训练 LightGBM 树模型，极大概率会打爆本地 16G 内存。我们需要将这些提纯后的因子传到资源充足的云端进行最后高吞吐“收网”。

### 2.1 硬件资源评估与选型（云端）
无需 GPU，核心需求是**多核 CPU 与充足的大内存**。
*   **推荐配置**：16 核 CPU + 64GB / 128GB 内存 + 150GB 系统盘的计算或内存优化型实例（如阿里云的 `g8i`/`c8i`，AWS 的 `c6i`/`m6i` 等）。
*   **费用极低**：只跑长周期回测过程只需几十分钟即可多核拉满完成，按量付费的成本仅需一顿早餐钱。

### 2.2 上云所需数据打包
云上执行下游回测无需配置整个演化管道，只需将以下核心内容打包上传至服务器（总容量通常约在 500MB 到几 GB 不等，避免打包深层的原 `workspace_*` 减小体积）：

1.  **工程目录**：整个干净的 `QuantaAlpha` 代码夹（删掉深层的 `.venv` 和原 `workspace_*`）。
2.  **挖掘战利品**：你在本地阶段一生成的 JSON（如 `all_factors_library_mac_run_01.json`）。
3.  **挖掘子产物（特征缓存）**：**务必打包上传本地的 `data/results/factor_cache/` 文件夹！** 这非常关键，由于缓存了你本地花费几十个小时算出的因子日频表数据，到了云端以后回测系统直接复用就可以免去重新解数学公式算几百张冷表的极大开销。
4.  **回测底座数据**：`git_ignore_folder/factor_implementation_source_data/daily_pv.h5` 和 `data/qlib/cn_data` 文件夹。

### 2.3 云端全样本回测命令实操
登录 16 核 64G 的强力云服务器，定位到项目根目录，展开代码与数据后：

#### 第一步：极速配置环境
```bash
# 避免使用 pip 或 conda 慢慢下，直接用 uv 几秒内装完依赖
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

#### 第二步：一键极致大模型验证（BOB 模式）
不需要再敲 `./run.sh` 启动完整的全生命周期探索协议了。我们使用专为后端组合验证打包的安全脚本 `./scripts/run_backtest_safe.sh`。

如果你想把你上传的因子库融合，并挑出最好的 Top 50 因子喂给 LightGBM 进行长程（2016-2025）复合回测：
```bash
# 由于运行仍需大量时间加载，务必采用 tmux 防止 ssh 断线
tmux new -s backtest_task

# 执行 BOB 聚合回测
 ./scripts/run_backtest_safe.sh --bob \
   --bob-libraries "all_factors_library_mac_run_01.json" \
   --bob-top 50 \
   --bob-metric "information_ratio" \
   --threads 16
```

*   `--bob`：开启 Best-of-Best 精英合成模式，它将抽取因子池中胜出者。
*   `--bob-top 50`：从所有上传的 JSON 候选者里筛选出信息比率 (IR) 最高的 50 个优质因子。
*   `--threads 16`：显式设置线程上限，云端可按 CPU 核心数调大以提高吞吐。

> 如果你想手动进行交互式引导而不是输入长长的参数：
> 可以直接输入 `./scripts/run_backtest_safe.sh --interactive` 跟着提示走。

### 2.4 回收验证报告并销毁

终端跑完 LightGBM 的 TopkDropout 聚合策略后，屏幕上会看到夏普比率、最大回撤等核心综合表现表格。
此时，你需要从云端打包下载的唯二文件是：
1. `--bob` 产生的聚合日志路径（如 `/tmp/quantaalpha_backtest_...` 或屏幕最后提示的**最终回测详细报告目录**，里面包含详细的资金曲线 `pnl.png` 和多因子累计收益热力图）。
2. `data/results/backtest_v2_results/` 中的详细汇总对比数据。

验证收益无误后，**立刻前往云服务器控制台销毁按量计费实例（注意不仅是关机而已！）**，避免公网 IP 与云盘持续扣费。阶段二至此光速且低成本完成！
