<div align="center">
  <img src="docs/images/overview.jpg" alt="QuantaAlpha 框架概览" width="90%" style="border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); margin: 10px 0;"/>
</div>

<div align="center">

  <h1 align="center" style="color: #2196F3; font-size: 32px; font-weight: 700; margin: 20px 0; line-height: 1.4;">
    🌟 QuantaAlpha: <span style="color: #555; font-weight: 400; font-size: 20px;"><em>LLM 驱动的自进化因子挖掘框架</em></span>
  </h1>

  <p align="center" style="font-size: 14px; color: #888; max-width: 700px; margin: 10px auto;">
    🧬 <em>基于轨迹的自进化范式，通过多样化规划初始化、轨迹级进化和结构化假设-代码约束，实现卓越的量化 Alpha 因子挖掘</em>
  </p>

  <p style="margin: 20px 0;">
    <a href="https://arxiv.org/abs/2602.07085"><img src="https://img.shields.io/badge/arXiv-b31b1b.svg?style=flat-square&logo=arxiv&logoColor=white" /></a>
    <a href="#"><img src="https://img.shields.io/badge/License-MIT-00A98F.svg?style=flat-square&logo=opensourceinitiative&logoColor=white" /></a>
    <a href="#"><img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat-square&logo=python&logoColor=white" /></a>
    <a href="https://github.com/QuantaAlpha/QuantaAlpha"><img src="https://img.shields.io/github/stars/QuantaAlpha/QuantaAlpha?style=flat-square&logo=github&logoColor=white&color=yellow" /></a>
  </p>

  <p style="font-size: 16px; color: #666; margin: 15px 0; font-weight: 500;">
    🌐 <a href="README.md" style="text-decoration: none; color: #0066cc;">English</a> | <a href="README_CN.md" style="text-decoration: none; color: #0066cc;">中文</a>
  </p>

</div>

<div align="center" style="margin: 30px 0;">
  <a href="#quick-start" style="text-decoration: none; margin: 0 4px;">
    <img src="https://img.shields.io/badge/🚀_快速开始-立即体验-4CAF50?style=flat-square&logo=rocket&logoColor=white&labelColor=2E7D32" alt="快速开始" />
  </a>
  <a href="#web-ui" style="text-decoration: none; margin: 0 4px;">
    <img src="https://img.shields.io/badge/🖥️_Web_界面-立即体验-FF9800?style=flat-square&logo=play&logoColor=white&labelColor=F57C00" alt="Web 界面" />
  </a>
  <a href="docs/user_guide.md" style="text-decoration: none; margin: 0 4px;">
    <img src="https://img.shields.io/badge/📖_用户指南-完整文档-2196F3?style=flat-square&logo=gitbook&logoColor=white&labelColor=1565C0" alt="用户指南" />
  </a>
  <a href="experiment/README_EXPERIMENT_CN.md" style="text-decoration: none; margin: 0 4px;">
    <img src="https://img.shields.io/badge/🔬_实验复现-详细说明-9C27B0?style=flat-square&logo=labview&logoColor=white&labelColor=7B1FA2" alt="实验复现" />
  </a>
</div>

---

## 🎯 概述

**QuantaAlpha** 将大语言模型（LLM）与进化策略结合，通过自进化轨迹自动完成量化 Alpha 因子的挖掘、进化与验证。你只需输入研究方向，其余流程将自动运行。

<p align="center">💬 研究方向 → 🧩 多样化规划 → 🔄 轨迹进化 → ✅ 已验证的 Alpha 因子</p>

**系统演示**：下方为 QuantaAlpha 本地UI从输入研究方向到因子挖掘与回测的完整流程演示，可点击观看。[📹 观看演示视频](docs/images/demo.mp4)

---

## 📊 实验结果

### 1. 因子表现

<div align="center">
  <img src="docs/images/figure3.png" width="90%" alt="零样本迁移" style="border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);"/>
  <p style="font-size: 12px; color: #666;">CSI 300 挖掘因子直接迁移至 CSI 500 / S&P 500</p>
</div>

### 2. 核心指标

<div align="center">

| 维度 | 指标 | 表现 |
| :---: | :---: | :---: |
| **预测效能** | 信息系数 (IC) | **0.1501** |
| | Rank IC | **0.1465** |
| **策略回报** | 年化超额收益 (ARR) | **27.75%** |
| | 最大回撤 (MDD) | **7.98%** |
| | 卡玛比率 (Calmar Ratio) | **3.4774** |

</div>

<div align="center">
  <img src="docs/images/主实验.png" width="90%" alt="主实验结果" style="border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);"/>
</div>

---

<a id="quick-start"></a>
## 🚀 快速开始

<p align="center" style="font-size: 13px; color: #666; margin-top: 10px;">
  🔬 实验复现：论文实验配置与指标口径说明 — <a href="experiment/README_EXPERIMENT_CN.md"><b>中文</b></a> · <a href="experiment/README_EXPERIMENT.md"><b>English</b></a>
</p>

### 1. 克隆与安装

```bash
git clone https://github.com/QuantaAlpha/QuantaAlpha.git
cd QuantaAlpha
# 推荐（无需 conda）：uv + Python 3.12
uv venv --python 3.12 .venv
uv pip install -e .
```

> 仍可使用历史 conda 流程，但当前脚本已支持 `uv`/`.venv` 直接运行。

### 2. 配置环境变量

```bash
cp configs/.env.example .env
```

编辑 `.env` 文件：

```bash
# === 必填：数据路径 ===
QLIB_DATA_DIR=/path/to/your/qlib/cn_data      # Qlib 数据目录
DATA_RESULTS_DIR=/path/to/your/results         # 输出目录

# === 必填：LLM API ===
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://your-llm-provider/v1   # 如: DashScope, OpenAI
CHAT_MODEL=deepseek-v3                         # 或 gpt-4, qwen-max 等
REASONING_MODEL=deepseek-v3
```

### 3. 准备数据

QuantaAlpha 需要两类数据：**Qlib 行情数据**（用于回测）和**预计算的价量 HDF5 文件**（用于因子挖掘）。我们已将所有数据上传至 HuggingFace，方便下载使用。

> **数据集地址**：[https://huggingface.co/datasets/QuantaAlpha/qlib_csi300](https://huggingface.co/datasets/QuantaAlpha/qlib_csi300)

| 文件 | 说明 | 用途 |
| :--- | :--- | :--- |
| `cn_data.zip` | Qlib 原始行情数据（A 股，2016–2025） | Qlib 初始化 & 回测必需 |
| `daily_pv.h5` | 预计算的完整价量数据 | 因子挖掘必需 |
| `daily_pv_debug.h5` | 预计算的调试子集（数据量较小） | 因子挖掘（调试/验证）必需 |

> **为什么同时提供 HDF5 文件？** 系统可以在首次运行时从 Qlib 数据自动生成 `daily_pv.h5`，但该过程非常耗时。直接下载预计算好的 HDF5 文件可以大幅节省时间。

#### 第一步：下载数据

```bash
# 方式 A：使用 huggingface-cli（推荐）
pip install huggingface_hub
huggingface-cli download QuantaAlpha/qlib_csi300 --repo-type dataset --local-dir ./hf_data

# 方式 B：使用 wget
mkdir -p hf_data
wget -P hf_data https://huggingface.co/datasets/QuantaAlpha/qlib_csi300/resolve/main/cn_data.zip
wget -P hf_data https://huggingface.co/datasets/QuantaAlpha/qlib_csi300/resolve/main/daily_pv.h5
wget -P hf_data https://huggingface.co/datasets/QuantaAlpha/qlib_csi300/resolve/main/daily_pv_debug.h5
```

#### 第二步：解压并放置文件

```bash
# 1. 解压 Qlib 数据
unzip hf_data/cn_data.zip -d ./data/qlib

# 2. 将 HDF5 文件放置到默认数据目录
mkdir -p git_ignore_folder/factor_implementation_source_data
mkdir -p git_ignore_folder/factor_implementation_source_data_debug

cp hf_data/daily_pv.h5       git_ignore_folder/factor_implementation_source_data/daily_pv.h5
cp hf_data/daily_pv_debug.h5  git_ignore_folder/factor_implementation_source_data_debug/daily_pv.h5
```

> **注意**：`daily_pv_debug.h5` 放入调试目录时需重命名为 `daily_pv.h5`。

#### 第三步：在 `.env` 中配置路径

```bash
# 指向解压后的 Qlib 数据目录（需包含 calendars/、features/、instruments/ 子目录）
QLIB_DATA_DIR=./data/qlib/cn_data

# 实验结果输出目录
DATA_RESULTS_DIR=./data/results
```

HDF5 数据目录也可以通过环境变量自定义（如果你希望放在其他位置）：

```bash
# 可选：自定义 HDF5 数据路径
FACTOR_CoSTEER_DATA_FOLDER=/your/custom/path/factor_source_data
FACTOR_CoSTEER_DATA_FOLDER_DEBUG=/your/custom/path/factor_source_data_debug
```


### 4. 运行因子挖掘

```bash
./run.sh "<你的输入>"

# 示例：指定研究方向运行
./run.sh "价量因子挖掘"

# 示例：指定因子库后缀
./run.sh "微观结构因子" "exp_micro"

# 示例：低磁盘模式（笔记本推荐）
./run.sh --low-disk "价量因子挖掘" "exp_lowdisk"

# 示例：真接力模式（重启后安全续跑）
EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "价量因子挖掘" "paper_reproduction_r2"

# 示例：严格续跑模式（必须已有接力状态）
EXPERIMENT_ID="paper_repro_r2" ./run.sh --resume "价量因子挖掘" "paper_reproduction_r2"
```

`run.sh` 现在默认开启 low-disk 模式。如需关闭，请显式加 `--no-low-disk`。

命名安全提示（重要）：

- 全新一轮实验时，`EXPERIMENT_ID` 与因子库后缀必须一起换（例如 `paper_repro_r2` + `paper_reproduction_r2`）。
- 复用同一个 `EXPERIMENT_ID` 表示继续同一条 workspace/cache/log 轨迹。
- 复用同一个后缀会继续写入同一个 `data/factorlib/all_factors_library_<suffix>.json`，可能混入历史因子。

受控并行建议（8 核笔记本）：

- 设为 `evolution.parallel_enabled: true`
- 设为 `evolution.max_parallel_workers: 2`（稳定后可逐步调到 `3~4`）
- 这样会限制每个 phase 的并发 worker，避免一次性拉起全部任务。
- 设为 `evolution.max_empty_retries: 1`，限制空分支重试次数。

预计算 cheap gate + 构造止损：

- `quality_gate.cheap_filter_enabled: true`：在 calculate/backtest 前拦截静态不合格表达式。
- `quality_gate.cheap_filter_require_acceptable: true`：仅保留 regulator 判定可接受的表达式。
- `quality_gate.max_construct_failures_per_branch: 2`：限制分支连续构造失败预算。
- `quality_gate.max_json_parse_failures_per_branch: 2`：限制分支 JSON 解析失败预算。

LLM 运行时稳态（优化新增选项，不是原始基线默认项）：

- `llm.json_mode_response_format: json_object`：在 `json_mode=true` 调用启用协议层 JSON 输出约束。
- `llm.json_mode_json_schema: ""`：可按 provider 能力配置 JSON Schema 字符串。
- `llm.json_mode_temperature: 0.0` 与 `llm.freeform_temperature: 0.5`：结构化调用与自由文本调用分层控温。
- `llm.request_timeout_s: 60.0`、`llm.retry_backoff: exponential`、`llm.retry_jitter: true`、`llm.retry_max_wait_seconds: 30.0`：降低尾延迟与卡顿空耗。
- `llm.failover_base_urls: []`：可选备用链路，在连续失败时切换 endpoint。

跨轮次 exact 去重（只减重复计算，不放宽质量门）：

- 在 `factor_calculate/factor_backtest` 前，若表达式在因子库或 trajectory 已出现则直接跳过。
- 跳过原因写入 `skip_reason=duplicate_exact`，便于 doctor/报告统计。

实验会自动挖掘、进化和验证 Alpha 因子，并将所有发现的因子保存到 `all_factors_library*.json`。

### 4.1 最小烟测（快速验证）

在全量运行前，建议先做一次快速环境验证：

```bash
./minirun.sh

# 可选：自定义方向
./minirun.sh "微观结构因子"
```

`minirun.sh` 使用 `configs/experiment_smoke.yaml`，默认 `STEP_N=5`（完整跑完一轮 5-step）。

### 4.2 接力模式 `--relay`（独立入口）

`--relay` 和 `--resume` 是两个独立模式（互斥），不是同一个模式的前后阶段。

`--relay` 用于“分段接力”：

- 首段按 `QUANTA_RELAY_CHUNK_ROUNDS`（默认 5）运行
- 后续再次执行 `--relay` 会自动补齐到 `max_rounds`

```bash
# 首段接力（默认先跑 5 轮）
EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "价量因子挖掘" "paper_reproduction_r2" 2>&1 | tee run_output_r2.log

# 第二次接力（自动补齐到 max_rounds）
EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "价量因子挖掘" "paper_reproduction_r2" 2>&1 | tee -a run_output_r2.log
```

### 4.3 续跑模式 `--resume`（独立入口）

`--resume` 用于“严格从已有状态直接续到目标轮次”，不会使用接力分段策略。

```bash
EXPERIMENT_ID="paper_repro_r2" ./run.sh --resume "价量因子挖掘" "paper_reproduction_r2" 2>&1 | tee -a run_output_r2.log
```

规则：

- 必须存在 `evolution_state.json`
- 若状态文件缺失，会直接失败退出（不会从 round 0 静默新跑）

### 4.4 防跑偏与可追溯保护

- 将 planning 生成的 `directions` 持久化到 `evolution_state.json`，续跑优先恢复，避免方向漂移。
- 续跑前校验“保存配置 vs 当前配置”，不一致默认直接失败退出。
- 每完成一个演化任务就做一次 checkpoint，减少中断损失。
- 日志会明确打印恢复来源：
  - `Relay resume source: previous_experiment_id=..., state_saved_at_utc=..., previous_log_trace_path=...`

强制续跑（仅紧急/人工确认场景）：

```bash
QUANTA_FORCE_RELAY_RESUME=1 EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "价量因子挖掘" "paper_reproduction_r2"
```

### 4.5 运行进度 Workflow（Codex）

用这个 workflow 查看**当前** `run.sh` 进度：
- 活跃进程（`run.sh` / `quantaalpha mine`）
- 最新 phase / round / direction
- 当前步骤（`factor_propose` 到 `feedback`）
- 已产出因子（来自 `trajectory_pool.json`）
- doctor 诊断摘要（报错信号 + 失败原因统计）

受限/沙箱环境提示（含部分 Codex 运行时）：
- 进程扫描可能因权限受限出现“未检测到活跃进程”的误报。
- 若进度字段持续更新但进程状态显示未运行，请在宿主终端用 `ps` 复核。

注意：这里的 `round` 指的是 **controller 的 phase-round**（每跑完一个 phase 才会 `round += 1`），不是“一个 epoch=original+mutation+crossover”。详细术语对齐见 `docs/PAPER_REPRODUCTION_GUIDE.md` 的“术语与层级”小节。

```bash
# 单次快照（自动识别最新日志根目录）
./scripts/run_doctor.sh

# 持续刷新查看
./scripts/run_doctor.sh --watch 8

# 一次性 doctor 报告
./scripts/run_doctor.sh

# 指定实验链路
./scripts/run_doctor.sh --experiment-id paper_repro_r2
```

### 5. 独立回测

挖掘完成后，从因子库中组合因子进行全周期回测：

```bash
# 仅使用自定义因子回测
python -m quantaalpha.backtest.run_backtest \
  -c configs/backtest.yaml \
  --factor-source custom \
  --factor-json all_factors_library.json

# 结合 Alpha158(20) 基线因子
python -m quantaalpha.backtest.run_backtest \
  -c configs/backtest.yaml \
  --factor-source combined \
  --factor-json all_factors_library.json

# 仅加载因子，不执行回测（检查因子加载是否正常）
python -m quantaalpha.backtest.run_backtest \
  -c configs/backtest.yaml \
  --factor-source custom \
  --factor-json all_factors_library.json \
  --dry-run -v
```

结果保存在 `configs/backtest.yaml` 中 `experiment.output_dir` 指定的目录。

回测输出文件名已改为“因子数量 + 北京时间戳”，避免同名结果互相覆盖：

- `<library_or_exp>_n<num_factors>_<YYYYMMDD_HHMMSS>_backtest_metrics.json`
- `<library_or_exp>_n<num_factors>_<YYYYMMDD_HHMMSS>_cumulative_excess.csv`

### 5.1 安全脚本（笔记本推荐）

建议使用安全脚本执行独立回测，支持线程限制、缓存检查、日志落盘、交互式参数输入：

```bash
./scripts/run_backtest_safe.sh --interactive
```

常用参数：

```bash
# limited 模式 + Top50 custom 因子
./scripts/run_backtest_safe.sh \
  --library data/factorlib/all_factors_library_paper_reproduction_ds.json \
  --mode limited \
  --max-factors 50 \
  --warm-cache

# 不限制因子数量（max_factors = null）
./scripts/run_backtest_safe.sh \
  --library data/factorlib/all_factors_library_paper_reproduction_ds.json \
  --max-factors all
```

补充说明：

- BOB 模式下 `--bob-metric auto` 现在会先为本次运行确定一个全局主指标，再统一排序（不再混用不同量纲）。
- 脚本产生的临时文件会在正常退出和异常中断时都自动清理。

说明：

- `--max-factors <N|all|default>`
  - `N`：仅回测 Top-N custom 因子
  - `all`：不限制数量
  - `default`：沿用配置文件中的 `factor_source.custom.max_factors`
- 前端“独立回测”页面支持“加载离线结果”，可默认加载最新，也可在下拉框选择历史轮次。

> 📘 需要帮助？请查阅完整的 **[用户指南](docs/user_guide.md)**，了解高级配置、实验复现和详细使用示例。

---

<a id="web-ui"></a>
## 🖥️ Web 界面

QuantaAlpha 提供基于 Web 的可视化界面，你可以在界面中完成全部工作流——无需命令行操作。

```bash
cd frontend-v2
bash start.sh
# 访问 http://localhost:3000
```

- **⚙️ 系统设置**：在界面中直接配置 LLM API、数据路径和实验参数
- **⛏️ 因子挖掘**：通过自然语言输入启动实验，实时监控进度
- **📚 因子库**：浏览、搜索和筛选所有已挖掘因子，支持质量分级
- **📈 独立回测**：选择因子库，运行全周期回测并查看可视化结果

---

## 说明

- **macOS 因子执行**：已修复 Darwin 下因子数据链接逻辑，`daily_pv.h5` 可正确链接到工作目录。
- **日志时区**：默认日志目录时间戳使用 **Asia/Shanghai（北京时间）**；若显式设置 `LOG_TRACE_PATH` 则以该值为准。
- **本地大文件忽略**：`hf_data/cn_data.zip` 已加入 `.gitignore`。

## 💬 用户社区

<div align="center">

| 微信群 |
| :---: |
| <img src="docs/images/WeChat.jpg" width="250" alt="微信群" /> |

</div>

---

## 🤝 参与贡献

我们欢迎任何形式的贡献，让 QuantaAlpha 变得更好！以下是参与方式：

- **🐛 Bug 反馈**：发现了 Bug？[提交 Issue](https://github.com/QuantaAlpha/QuantaAlpha/issues) 帮助我们修复。
- **💡 功能建议**：有好的想法？[发起讨论](https://github.com/QuantaAlpha/QuantaAlpha/discussions) 提出新功能建议。
- **📝 文档与教程**：改进文档、添加使用示例或编写教程。
- **🔧 代码贡献**：提交 PR 修复 Bug、优化性能或添加新功能。
- **🧬 因子分享**：分享你在实验中发现的高质量因子，造福社区。

---

## 🙏 致谢

特别感谢：
- [Qlib](https://github.com/microsoft/qlib) - 微软开源的量化投资平台
- [RD-Agent](https://github.com/microsoft/RD-Agent) - 微软的自动化研发框架 (NeurIPS 2025)
- [AlphaAgent](https://github.com/RndmVariableQ/AlphaAgent) - 多智能体 Alpha 因子挖掘框架 (KDD 2025)

---

## 🌐 关于 QuantaAlpha

- QuantaAlpha 团队成立于 **2025 年 4 月**，由来自**清华大学、北京大学、中国科学院、CMU、HKUST** 等高校的教授、博士后、博士生和硕士生组成。

🌟 我们的使命是探索智能的 **"量子 (Quantum)"** 本质，开拓 Agent 研究的 **"Alpha"** 前沿——从 **CodeAgent** 到**自进化智能**，再到**金融及跨领域专用 Agent**，致力于重新定义 AI 的边界。

✨ **2026 年**，我们将持续在以下方向产出高质量研究：
- **CodeAgent**：端到端自主执行真实世界任务
- **DeepResearch**：深度推理与检索增强智能
- **Agentic Reasoning / Agentic RL**：基于 Agent 的推理与强化学习
- **自进化与协作学习**：多智能体系统的进化与协调

📢 欢迎对以上方向感兴趣的同学和研究者加入我们！

🔗 **团队主页**：[QuantaAlpha](https://quantaalpha.github.io/)
📧 **邮箱**：quantaalpha.ai@gmail.com

## 🌐 关于 AIFin Lab

- AIFin Lab 由上财张立文教授发起，深耕 **AI + 金融 / 统计 / 数据科学** 交叉领域，团队汇聚上财、复旦、东大、CMU、港中文等校前沿学者，打造数据、模型、评测、智能提示全链路体系。

📢 我们诚挚欢迎全球优秀的本科、硕士、博士生以及前沿学者加入 **AIFin Lab**，共同探索金融人工智能的边界！

📧 **邮箱**：[aifinlab.sufe@gmail.com](mailto:aifinlab.sufe@gmail.com)（主收件），同时抄送 (CC) 至 [zhang.liwen@shufe.edu.cn](mailto:zhang.liwen@shufe.edu.cn)

期待你的加入！

---

## 📖 引用

如果 QuantaAlpha 对你的研究有帮助，请引用我们的工作：

```bibtex
@misc{han2026quantaalphaevolutionaryframeworkllmdriven,
      title={QuantaAlpha: An Evolutionary Framework for LLM-Driven Alpha Mining}, 
      author={Jun Han and Shuo Zhang and Wei Li and Zhi Yang and Yifan Dong and Tu Hu and Jialuo Yuan and Xiaomin Yu and Yumo Zhu and Fangqi Lou and Xin Guo and Zhaowei Liu and Tianyi Jiang and Ruichuan An and Jingping Liu and Biao Wu and Rongze Chen and Kunyi Wang and Yifan Wang and Sen Hu and Xinbing Kong and Liwen Zhang and Ronghao Chen and Huacan Wang},
      year={2026},
      eprint={2602.07085},
      archivePrefix={arXiv},
      primaryClass={q-fin.ST},
      url={https://arxiv.org/abs/2602.07085}, 
}
```

---

## ⭐ Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=QuantaAlpha/QuantaAlpha&type=Date&v=20260209)](https://www.star-history.com/#QuantaAlpha/QuantaAlpha&Date)

---

<div align="center">

**⭐ 如果 QuantaAlpha 对你有帮助，请给我们一个 Star！**

由 QuantaAlpha 团队用 ❤️ 打造


</div>
