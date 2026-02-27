<div align="center">
  <img src="docs/images/overview.jpg" alt="QuantaAlpha Framework Overview" width="90%" style="border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); margin: 10px 0;"/>
</div>

<div align="center">

  <h1 align="center" style="color: #2196F3; font-size: 32px; font-weight: 700; margin: 20px 0; line-height: 1.4;">
    🌟 QuantaAlpha: <span style="color: #555; font-weight: 400; font-size: 20px;"><em>LLM-Driven Self-Evolving Framework for Factor Mining</em></span>
  </h1>

  <p align="center" style="font-size: 14px; color: #888; max-width: 700px; margin: 10px auto;">
    🧬 <em>Achieving superior quantitative alpha through trajectory-based self-evolution with diversified planning initialization, trajectory-level evolution, and structured hypothesis-code constraint</em>
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
  <a href="#-quick-start" style="text-decoration: none; margin: 0 4px;">
    <img src="https://img.shields.io/badge/🚀_Quick_Start-Get_Started-4CAF50?style=flat-square&logo=rocket&logoColor=white&labelColor=2E7D32" alt="Quick Start" />
  </a>
  <a href="#️-web-dashboard" style="text-decoration: none; margin: 0 4px;">
    <img src="https://img.shields.io/badge/🖥️_Web_UI-Try_It_Now-FF9800?style=flat-square&logo=play&logoColor=white&labelColor=F57C00" alt="Web Dashboard" />
  </a>
  <a href="docs/user_guide.md" style="text-decoration: none; margin: 0 4px;">
    <img src="https://img.shields.io/badge/📖_User_Guide-Complete_Guide-2196F3?style=flat-square&logo=gitbook&logoColor=white&labelColor=1565C0" alt="User Guide" />
  </a>
  <a href="experiment/README_EXPERIMENT.md" style="text-decoration: none; margin: 0 4px;">
    <img src="https://img.shields.io/badge/🔬_Experiments-Replication-9C27B0?style=flat-square&logo=labview&logoColor=white&labelColor=7B1FA2" alt="Experiments" />
  </a>
</div>

---

## 🎯 Overview

**QuantaAlpha** transforms how you discover quantitative alpha factors by combining LLM intelligence with evolutionary strategies. Just describe your research direction, and watch as factors are automatically mined, evolved, and validated through self-evolving trajectories.

<p align="center">💬 Research Direction → 🧩 Diversified Planning → 🔄 Trajectory → ✅ Validated Alpha Factors</p>

**Demo**: Below is a short demo of the full flow from research direction to factor mining and backtesting UI. 

<div align="center">
  <video src="https://github.com/user-attachments/assets/726511ce-a384-4727-a7be-948a2cf05e4b"
         controls
         style="max-width: 90%; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
    Your browser does not support the video tag.
    <a href="https://github.com/user-attachments/assets/726511ce-a384-4727-a7be-948a2cf05e4b">Watch the demo video</a>.
  </video>
  <p style="font-size: 12px; color: #666; margin-top: 8px;">
    ▶ Click to play the QuantaAlpha end-to-end workflow demo.
  </p>
</div>

---

## 📊 Performance

### 1. Factor Performance

<div align="center">
  <img src="docs/images/figure3.png" width="90%" alt="Zero-Shot Transfer" style="border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);"/>
  <p style="font-size: 12px; color: #666;">CSI 300 factors transferred to CSI 500/S&P 500</p>
</div>

### 2. Key Results

<div align="center">

| Dimension | Metric | Performance |
| :---: | :---: | :---: |
| **Predictive Power** | Information Coefficient (IC) | **0.1501** |
| | Rank IC | **0.1465** |
| **Strategy Return** | Annualized Excess Return (ARR) | **27.75%** |
| | Max Drawdown (MDD) | **7.98%** |
| | Calmar Ratio (CR) | **3.4774** |

</div>

<div align="center">
  <img src="docs/images/主实验.png" width="90%" alt="Main Experiment Results" style="border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);"/>
</div>

---

## 🚀 Quick Start

<p align="center" style="font-size: 13px; color: #666; margin-top: 10px;">
  🔬 Experiments: paper reproduction settings & metric definitions — <a href="experiment/README_EXPERIMENT.md"><b>English</b></a> · <a href="experiment/README_EXPERIMENT_CN.md"><b>中文</b></a>
</p>

### 1. Clone & Install

```bash
git clone https://github.com/QuantaAlpha/QuantaAlpha.git
cd QuantaAlpha
# Recommended (no conda): uv + Python 3.12
uv venv --python 3.12 .venv
uv pip install -e .
```

> Legacy conda workflow is still possible, but project scripts now support `uv`/`.venv` directly.

### 2. Configure Environment

```bash
cp configs/.env.example .env
```

Edit `.env` with your settings:

```bash
# === Required: Data Paths ===
QLIB_DATA_DIR=/path/to/your/qlib/cn_data      # Qlib data directory
DATA_RESULTS_DIR=/path/to/your/results         # Output directory

# === Required: LLM API ===
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://your-llm-provider/v1   # e.g. DashScope, OpenAI
CHAT_MODEL=deepseek-v3                         # or gpt-4, qwen-max, etc.
REASONING_MODEL=deepseek-v3
```

### 3. Prepare Data

QuantaAlpha requires two types of data: **Qlib market data** (for backtesting) and **pre-computed price-volume HDF5 files** (for factor mining). We provide all of them on HuggingFace for convenience.

> **Dataset**: [https://huggingface.co/datasets/QuantaAlpha/qlib_csi300](https://huggingface.co/datasets/QuantaAlpha/qlib_csi300)

| File | Description | Size | Usage |
| :--- | :--- | :--- | :--- |
| `cn_data.zip` | Qlib raw market data (A-share, 2016–2025) | 493 MB | Required for Qlib initialization & backtesting |
| `daily_pv.h5` | Pre-computed full price-volume data | 398 MB | Required for factor mining |
| `daily_pv_debug.h5` | Pre-computed debug subset (smaller) | 1.41 MB | Required for factor mining (debug/validation) |

> **Why provide HDF5 files?** The system can auto-generate `daily_pv.h5` from Qlib data on first run, but this process is very slow. Downloading pre-built HDF5 files saves significant time.

#### Step 1: Download

```bash
# Option A: Using huggingface-cli (recommended)
pip install huggingface_hub
huggingface-cli download QuantaAlpha/qlib_csi300 --repo-type dataset --local-dir ./hf_data

# Option B: Using wget
mkdir -p hf_data
wget -P hf_data https://huggingface.co/datasets/QuantaAlpha/qlib_csi300/resolve/main/cn_data.zip
wget -P hf_data https://huggingface.co/datasets/QuantaAlpha/qlib_csi300/resolve/main/daily_pv.h5
wget -P hf_data https://huggingface.co/datasets/QuantaAlpha/qlib_csi300/resolve/main/daily_pv_debug.h5
```

#### Step 2: Extract & Place Files

```bash
# 1. Extract Qlib data
unzip hf_data/cn_data.zip -d ./data/qlib

# 2. Place HDF5 files into the default data directories
mkdir -p git_ignore_folder/factor_implementation_source_data
mkdir -p git_ignore_folder/factor_implementation_source_data_debug

cp hf_data/daily_pv.h5       git_ignore_folder/factor_implementation_source_data/daily_pv.h5
cp hf_data/daily_pv_debug.h5  git_ignore_folder/factor_implementation_source_data_debug/daily_pv.h5
```

> **Note**: `daily_pv_debug.h5` must be renamed to `daily_pv.h5` when placed in the debug directory.

#### Step 3: Configure Paths in `.env`

```bash
# Point to the extracted Qlib data directory (must contain calendars/, features/, instruments/)
QLIB_DATA_DIR=./data/qlib/cn_data

# Output directory for experiment results
DATA_RESULTS_DIR=./data/results
```

The HDF5 data directories can also be customized via environment variables if you prefer a different location:

```bash
# Optional: override default HDF5 data paths
FACTOR_CoSTEER_DATA_FOLDER=/your/custom/path/factor_source_data
FACTOR_CoSTEER_DATA_FOLDER_DEBUG=/your/custom/path/factor_source_data_debug
```

### 4. Run Factor Mining

```bash
./run.sh "<your input>"

# Example: Run with a research direction
./run.sh "Price-Volume Factor Mining"

# Example: Run with custom factor library suffix
./run.sh "Microstructure Factors" "exp_micro"

# Example: low-disk mode (recommended on laptops)
./run.sh --low-disk "Price-Volume Factor Mining" "exp_lowdisk"

# Example: true relay mode (safe resume across restarts)
EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "Price-Volume Factor Mining" "paper_reproduction_r2"

# Example: strict resume mode (requires existing relay state)
EXPERIMENT_ID="paper_repro_r2" ./run.sh --resume "Price-Volume Factor Mining" "paper_reproduction_r2"
```

`run.sh` now enables low-disk mode by default. Use `--no-low-disk` to disable it explicitly.

Naming safety (important):

- For a brand-new run, change both `EXPERIMENT_ID` and library suffix together (e.g. `paper_repro_r2` + `paper_reproduction_r2`).
- Reusing `EXPERIMENT_ID` means you continue the same workspace/cache/log lineage.
- Reusing library suffix writes to the same `data/factorlib/all_factors_library_<suffix>.json`, which can mix with old factors.

Controlled parallelism (recommended on 8-core laptop):

- Set `evolution.parallel_enabled: true`
- Set `evolution.max_parallel_workers: 2` (then tune to `3~4` after stability check)
- This caps per-phase workers and avoids launching all evolution tasks at once.
- Set `evolution.max_empty_retries: 1` to limit empty-branch retries.

Pre-calc cheap gate + construct stop-loss:

- `quality_gate.cheap_filter_enabled: true` rejects invalid expressions before calculate/backtest.
- `quality_gate.cheap_filter_require_acceptable: true` keeps only regulator-acceptable expressions.
- `quality_gate.max_construct_failures_per_branch: 2` caps repeated construct failures.
- `quality_gate.max_json_parse_failures_per_branch: 2` caps repeated JSON parse failures in construct.

LLM runtime hardening (optimization-added options, not original baseline defaults):

- `llm.json_mode_response_format: json_object` enables protocol-level JSON output in `json_mode=true`.
- `llm.json_mode_json_schema: ""` can be set to a JSON Schema string when provider supports schema mode.
- `llm.json_mode_temperature: 0.0` and `llm.freeform_temperature: 0.5` split temperature by structured vs freeform calls.
- `llm.request_timeout_s: 60.0`, `llm.retry_backoff: exponential`, `llm.retry_jitter: true`, `llm.retry_max_wait_seconds: 30.0` stabilize tail latency.
- `llm.failover_base_urls: []` enables optional endpoint failover for consecutive failures.

Cross-round exact dedup (compute-saving, no quality gate relaxation):

- Before `factor_calculate/factor_backtest`, repeated expressions are skipped by library + trajectory seen set.
- Skip reason is recorded as `skip_reason=duplicate_exact` for doctor/report diagnostics.

The experiment will automatically mine, evolve, and validate alpha factors, and save all discovered factors to `all_factors_library*.json`.

### 4.1 Minimal Smoke Run (Fast Validation)

Use this to quickly validate environment/data/LLM connectivity before a full run:

```bash
./minirun.sh

# optional custom direction
./minirun.sh "Microstructure Factors"
```

`minirun.sh` uses `configs/experiment_smoke.yaml` and default `STEP_N=5` (runs one full 5-step loop).

### 4.2 Relay Mode `--relay` (Independent Entry)

`--relay` and `--resume` are two independent modes (mutually exclusive), not two phases of one mode.

Use `--relay` for chunked relay execution:

- first leg runs `QUANTA_RELAY_CHUNK_ROUNDS` (default 5)
- next `--relay` run auto-completes to `max_rounds`

```bash
# first relay leg (default first 5 rounds)
EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "Price-Volume Factor Mining" "paper_reproduction_r2" 2>&1 | tee run_output_r2.log

# second relay leg (auto-finish to max_rounds)
EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "Price-Volume Factor Mining" "paper_reproduction_r2" 2>&1 | tee -a run_output_r2.log
```

### 4.3 Resume Mode `--resume` (Independent Entry)

Use `--resume` to continue directly from saved state to target rounds (no chunk scheduling):

```bash
EXPERIMENT_ID="paper_repro_r2" ./run.sh --resume "Price-Volume Factor Mining" "paper_reproduction_r2" 2>&1 | tee -a run_output_r2.log
```

Rules:

- requires existing `evolution_state.json`
- fails fast if state is missing (no implicit round-0 restart)

### 4.4 Anti-Drift and Traceability Guards

- Persist and restore planning `directions` from `evolution_state.json` to avoid direction drift.
- Validate saved config vs current config before resume; mismatch fails fast by default.
- Checkpoint state after each completed evolution task.
- Log resume source explicitly:
  - `Relay resume source: previous_experiment_id=..., state_saved_at_utc=..., previous_log_trace_path=...`

Force override (only for emergency/manual recovery):

```bash
QUANTA_FORCE_RELAY_RESUME=1 EXPERIMENT_ID="paper_repro_r2" ./run.sh --relay "Price-Volume Factor Mining" "paper_reproduction_r2"
```

### 4.5 Run Progress Workflow (Codex)

Use this workflow to inspect the **current** `run.sh` progress:
- active process (`run.sh` / `quantaalpha mine`)
- latest phase/round/direction
- current step (`factor_propose` ... `feedback`)
- generated factors from `trajectory_pool.json`
- doctor diagnostics (error signals + failed decision reasons)

Note on restricted/sandboxed environments (including some Codex runtimes):
- process scan may be permission-limited and show a false negative for active processes.
- if progress fields continue updating but process status shows inactive, verify with a direct terminal `ps` check in your host shell.

```bash
# one-shot snapshot (auto-detect latest log root)
./scripts/run_doctor.sh

# continuous watch
./scripts/run_doctor.sh --watch 8

# one-shot doctor report
./scripts/run_doctor.sh

# bind to one experiment lineage explicitly
./scripts/run_doctor.sh --experiment-id paper_repro_r2
```

### 5. Independent Backtesting

After mining, combine factors from the library for a full-period backtest:

```bash
# Backtest with custom factors only
python -m quantaalpha.backtest.run_backtest \
  -c configs/backtest.yaml \
  --factor-source custom \
  --factor-json all_factors_library.json

# Combine with Alpha158(20) baseline factors
python -m quantaalpha.backtest.run_backtest \
  -c configs/backtest.yaml \
  --factor-source combined \
  --factor-json all_factors_library.json

# Dry run (load factors only, skip backtest)
python -m quantaalpha.backtest.run_backtest \
  -c configs/backtest.yaml \
  --factor-source custom \
  --factor-json all_factors_library.json \
  --dry-run -v
```

Results are saved to the directory specified in `configs/backtest.yaml` (`experiment.output_dir`).

Backtest output files are timestamped in Beijing time and include the actual factor count to avoid overwrite:

- `<library_or_exp>_n<num_factors>_<YYYYMMDD_HHMMSS>_backtest_metrics.json`
- `<library_or_exp>_n<num_factors>_<YYYYMMDD_HHMMSS>_cumulative_excess.csv`

### 5.1 Safe Script (Recommended on laptops)

Use the safer wrapper script for logging, thread control, cache checks, and interactive mode:

```bash
./scripts/run_backtest_safe.sh --interactive
```

Useful options:

```bash
# Run limited mode with top-50 custom factors
./scripts/run_backtest_safe.sh \
  --library data/factorlib/all_factors_library_paper_reproduction_ds.json \
  --mode limited \
  --max-factors 50 \
  --warm-cache

# Run without factor-count limit (config max_factors = null)
./scripts/run_backtest_safe.sh \
  --library data/factorlib/all_factors_library_paper_reproduction_ds.json \
  --max-factors all
```

Notes:

- In BOB mode, `--bob-metric auto` now resolves one global primary metric for this run before ranking (no mixed-scale sorting).
- Temporary files generated by the script are cleaned up on both normal exit and early abort.

> 📘 Need help? Check our comprehensive **[User Guide](docs/user_guide.md)** for advanced configuration, experiment reproduction, and detailed usage examples.

---

## 🖥️ Web UI

QuantaAlpha provides a web-based dashboard where you can complete the entire workflow through a visual interface — no command line needed.

```bash
cd frontend-v2
bash start.sh
# Visit http://localhost:3000
```

- **⚙️ Settings**: Configure LLM API, data paths, and experiment parameters directly in the UI
- **⛏️ Factor Mining**: Start experiments with natural language input and monitor progress in real-time
- **📚 Factor Library**: Browse, search, and filter all discovered factors with quality classifications
- **📈 Independent Backtest**: Select a factor library and run full-period backtests with visual results

---

## Notes

- **macOS factor execution**: symlink behavior for factor data files is fixed; `daily_pv.h5` is now correctly linked on Darwin.
- **Log timezone**: default log folder timestamps use **Asia/Shanghai (UTC+8)** unless `LOG_TRACE_PATH` is explicitly set.
- **Large local dataset file**: `hf_data/cn_data.zip` is ignored by git.

<a id="windows-deploy"></a>
## 🪟 Windows Deployment

QuantaAlpha is natively developed for Linux. Below is a guide to run it on **Windows 10/11**.

> For technical details, see [`docs/WINDOWS_COMPAT.md`](docs/WINDOWS_COMPAT.md).

### Key Differences from Linux

| Feature | Linux | Windows |
| :--- | :--- | :--- |
| Start mining | `./run.sh "direction"` | `python launcher.py mine --direction "direction"` |
| Start frontend | `bash start.sh` | Start backend & frontend separately (see below) |
| `.env` path format | `/home/user/data` | `C:/Users/user/data` (use forward slashes) |
| Extra config | None | Must set `CONDA_DEFAULT_ENV` (see below) |
| rdagent patches | None | Auto-applied (`quantaalpha/compat/rdagent_patches.py`) |

### Installation

```powershell
# 1. Install Miniconda (check "Add to PATH" during setup)
# 2. Create conda environment
conda create -n quantaalpha python=3.11 -y
conda activate quantaalpha

# 3. Clone and install
git clone https://github.com/QuantaAlpha/QuantaAlpha.git
cd QuantaAlpha
set SETUPTOOLS_SCM_PRETEND_VERSION=0.1.0
pip install -e .
```

### Configure `.env`

```powershell
copy configs\.env.example .env
```

Edit `.env` — use **forward slashes** for paths:

```bash
QLIB_DATA_DIR=C:/Users/yourname/path/to/cn_data
DATA_RESULTS_DIR=C:/Users/yourname/path/to/results
CONDA_ENV_NAME=quantaalpha
CONDA_DEFAULT_ENV=quantaalpha    # ← Required on Windows
```

### Run

```powershell
# Factor mining
python launcher.py mine --direction "price-volume factor mining"

# Standalone backtest
python -m quantaalpha.backtest.run_backtest -c configs/backtest.yaml --factor-source custom --factor-json data/factorlib/all_factors_library.json -v
```

### Web Frontend (Optional)

Requires Node.js (v18+). Start in two terminals:

```powershell
# Terminal 1 — Backend API
cd frontend-v2 && python backend/app.py

# Terminal 2 — Frontend
cd frontend-v2 && npm install && npm run dev
```

Visit http://localhost:3000.

### Troubleshooting

| Error | Fix |
| :--- | :--- |
| `CondaConf conda_env_name: Input should be a valid string` | Add `CONDA_DEFAULT_ENV=quantaalpha` to `.env` |
| `UnicodeEncodeError: 'gbk'` | Run `chcp 65001` or set `PYTHONIOENCODING=utf-8` |
| `Failed to resolve import "@radix-ui/react-hover-card"` | `cd frontend-v2 && npm install` |

---

## 💬 User Community

<div align="center">

| WeChat Group |
| :---: |
| <img src="docs/images/WeChat.jpg" width="250" alt="WeChat Group" /> |

</div>

---

## 🤝 Contributing

We welcome all forms of contributions to make QuantaAlpha better! Here's how you can get involved:

- **🐛 Bug Reports**: Found a bug? [Open an issue](https://github.com/QuantaAlpha/QuantaAlpha/issues) to help us fix it.
- **💡 Feature Requests**: Have a great idea? [Start a discussion](https://github.com/QuantaAlpha/QuantaAlpha/discussions) to suggest new features.
- **📝 Docs & Tutorials**: Improve documentation, add usage examples, or write tutorials.
- **🔧 Code Contributions**: Submit PRs for bug fixes, performance improvements, or new functionality.
- **🧬 New Factors**: Share high-quality factors discovered in your own runs to benefit the community.

---

## 🙏 Acknowledgments

Special thanks to:
- [Qlib](https://github.com/microsoft/qlib) - Quantitative investment platform by Microsoft
- [RD-Agent](https://github.com/microsoft/RD-Agent) - An automated R&D framework by Microsoft (NeurIPS 2025)
- [AlphaAgent](https://github.com/RndmVariableQ/AlphaAgent) - Multi-agent alpha factor mining framework (KDD 2025)

---

## 🌐 About QuantaAlpha
- QuantaAlpha was founded in **April 2025** by a team of professors, postdocs, PhDs, and master's students from **Tsinghua University, Peking University, CAS, CMU, HKUST**, and more.  

🌟 Our mission is to explore the **"quantum"** of intelligence and pioneer the **"alpha"** frontier of agent research — from **CodeAgents** to **self-evolving intelligence**, and further to **financial and cross-domain specialized agents**, we are committed to redefining the boundaries of AI. 

✨ In **2026**, we will continue to produce high-quality research in the following directions:  

- **CodeAgent**: End-to-end autonomous execution of real-world tasks  

- **DeepResearch**: Deep reasoning and retrieval-augmented intelligence  

- **Agentic Reasoning / Agentic RL**: Agent-based reasoning and reinforcement learning 

- **Self-evolution and collaborative learning**: Evolution and coordination of multi-agent systems  

📢 We welcome students and researchers interested in these directions to join us!  

🔗 **Team Homepage**: [QuantaAlpha](https://quantaalpha.github.io/)

📧 **Email**: quantaalpha.ai@gmail.com

## 🌐 About AIFin Lab

Initiated by Professor Liwen Zhang from Shanghai University of Finance and Economics (SUFE), **AIFin Lab** is deeply rooted in the interdisciplinary fields of **AI + Finance, Statistics, and Data Science**. The team brings together cutting-edge scholars from top institutions such as SUFE, FDU, SEU, CMU, and CUHK. We are dedicated to building a comprehensive "full-link" system covering data, models, benchmarks, and intelligent prompting. 

📢 We are actively looking for talented students (UG/Master/PhD) and researchers worldwide who are passionate about AI Agent security and financial intelligence to join **AIFin Lab**! 

📧 **Email**: [aifinlab.sufe@gmail.com](mailto:aifinlab.sufe@gmail.com) (please CC to [zhang.liwen@shufe.edu.cn](mailto:zhang.liwen@shufe.edu.cn))

We look forward to hearing from you!

---

## 📖 Citation

If you find QuantaAlpha useful in your research, please cite our work:

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

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=QuantaAlpha/QuantaAlpha&type=date&legend=top-left)](https://www.star-history.com/#QuantaAlpha/QuantaAlpha&type=date&legend=top-left)

---

<div align="center">

**⭐ If QuantaAlpha helps you, please give us a star!**

Made with ❤️ by the QuantaAlpha Team

</div>
