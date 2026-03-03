# my-fix_vs_main 变更总结

更新时间：2026-03-03

对比范围（PR diff 口径）：
- base：`main`
- compare：`codex/my-fix`（远端：`origin/codex/my-fix`）
- merge-base：`6201cf80f9901bfccd91ab8eade0610a7eecfe1a`
- compare HEAD：`dc5d05c`

> 说明：本文为差异摘要与风险清单，细节以 `CHANGELOG.md` / `SPECS.md` 与实际 `git diff` 为准。

---

## 0) ⚠️ 可能影响论文复现结果的高危项（必读）

> 这里的“高危”指：可能改变**因子数值**、**因子集合**、或导致“同名但内容不同/选错结果文件”等复现偏差。

### 0.1 高危开关/行为清单（建议复现时逐条确认）

| 项 | 风险 | 当前默认 | A/B 结论（证据文件） | 影响 | 建议/规避 |
|---|---|---|---|---|---|
| `QUANTA_LOW_DISK_FLOAT32`（low-disk 下 float32） | 高 | `false`（opt-in） | M1：负优化（含 float32；RSS↑+指标漂移），见 `docs/performance_optimization_cn.md` | **可能引入指标漂移**/数值差异（尤其回测/聚合指标） | 论文复现建议保持 `false`；如曾开过，建议清空缓存后重算 |
| 因子缓存复用（cache key 仅基于表达式） | 高 | 开启（默认走 cache） | 无（逻辑风险，非 A/B 项） | **历史（任意旧版本：main 或 my-fix）写入 cache 的错误因子值可能被复用**，影响当前回测；并可能进一步影响演化选择与后续生成 | 修复因子计算逻辑后，建议清空 `FACTOR_CACHE_DIR`（默认 `data/results/factor_cache/`）与相关 workspace/pickle_cache；或设置新的 `FACTOR_CACHE_DIR`/`DATA_RESULTS_DIR` + 新的 `EXPERIMENT_ID`/suffix 做强隔离 |
| 生成侧配置变更（如 `num_directions/max_rounds/factors_per_hypothesis`） | 高 | 已改为“论文复现”参数 | 无（行为变更） | 会改变探索空间与因子数量，**结果不可与旧口径直接对齐** | 复现必须固定 config 文件与 commit；需要 baseline 对照时请回到 main 的 config 或显式指定 config |
| LLM 行为（model/prompt/temperature/json_mode） | 高 | 已增强稳态策略 | O2：正优化（-7.9%）；O4：负优化（+14.31%）；O5：负优化（+10.76%），见 `docs/performance_optimization_cn.md` | 会改变生成内容与接受率（属于“研究过程”的不确定性来源） | 复现报告建议记录：模型名/温度/关键 prompt 版本；需要更严格可把温度降到更保守值并锁定模型 |
| `--zoo-dedup`（跨 run 表达式去重） | 高 | 关闭 | 无（功能开关） | 会跳过已见表达式，**改变候选因子集合**（进而改变回测/演化路径） | 论文复现若要求“同一搜索空间”，建议关闭；开启时请记录 zoo 版本与路径 |
| `--corr-dedup`（相关性去重 + TopN） | 高 | 关闭 | 无（功能开关；待专项评估） | 会先筛掉高度相关因子，**改变入回测的因子集合与排名** | 论文复现建议关闭；若使用，请固定参数并记录产出的 selected library 文件 |
| `quality_gate.cheap_filter_enabled`（cheap gate + exact dedup） | 中-高 | `false` | O1：负优化（+49.8% wall-time），见 `docs/performance_optimization_cn.md` | 仅在开启时生效：会提前过滤 style/parse/quality/duplicate，改变因子集合（且 A/B 显示在某口径下为负优化） | 论文复现建议保持关闭；如开启，务必记录开关与过滤统计 |
| S1 表达式风格稳定性约束（operator + `$` 前缀一致性） | 中 | 开启 | 稳定性修复（单测通过；construct 阶段强校验），见 `docs/performance_optimization_cn.md` | 主要影响**生成/construct 阶段的接受率与重试次数**（不合规会触发重写/重试）；对“已固定 factor library 的离线回测”不直接改变因子数值 | 仅回测既有因子池时可视为低风险；若复现“生成过程”，需固定该约束是否开启及对应 commit |
| warm-start/trajectory pool 复用（`fresh_start=false` 或 relay 续跑复用） | 中-高 | `fresh_start=true`（relay 场景可能例外） | 待专项 A/B（W1），见 `docs/performance_optimization_cn.md` | 会复用历史轨迹，影响后续探索/收敛路径 | 严格复现建议删除旧 `trajectory_pool.json` 并保持 `fresh_start=true` |
| 并行执行（`parallel_enabled=true`） | 中 | 关闭 | 待专项 A/B（P1），见 `docs/performance_optimization_cn.md` | 可能改变执行顺序与时序（结合非确定性组件时影响更大） | 论文复现建议保持关闭 |
| 多线程回测（`--threads`/`num_threads`） | 中 | limited 模式较低线程 | 无（未做专项 A/B） | 某些模型/算子在多线程下可能出现轻微非确定性 | 需要更严格时可把线程数降到 1，并记录 backtest 配置 |
| 回测结果文件命名（`_n<num>_<timestamp>_backtest_metrics.json`） | 中（偏“选错文件”风险） | 开启 | 无（非 A/B；功能性变更） | **不改变回测数值**，但容易导致“读取 latest 时拿到不同文件” | 复现报告建议记录“具体 metrics 文件名/路径”，不要只说 “latest” |

> 注：这里的“历史”不是固定时间窗口，而是指你磁盘上现存 cache 文件生成时所用的代码版本（可能来自 main 或 my-fix 的任意旧提交/旧实验）。系统目前不会自动为 cache 做“版本失效”。

### 0.2 “某个因子曾算错值，会影响后面回测结果吗？”

会，影响路径通常有三类（从直接到间接）：
- **直接影响**：该因子的回测指标/排名不可信（显然）。
- **缓存污染**：若错误值被写入 cache（md5 key 只看表达式），即使你修复了计算逻辑，只要表达式不变，也可能继续复用旧缓存 → 后续回测仍然“看起来正常但其实是旧数据”。
- **间接影响演化**：错误回测/反馈会影响轨迹选择（mutation/crossover/parent selection），从而改变后续 round 的生成方向与候选集合。

复现建议（最稳妥）：
- 对比/复现时使用全新隔离的 `EXPERIMENT_ID` 与 factor library suffix；
- 清理旧 workspace/pickle_cache/factor_cache（至少清与目标表达式相关的缓存目录）后再重跑。

---

## 1) 总览（已提交到分支）

- commits：5
- files changed：82（`+24961 / -287`）
- 主要变更域：入口脚本与运行方式、relay/resume 稳定性、LLM 重试/表达式稳定性、回测工具链（含去重/筛选与结果命名）、run doctor 观测闭环、前端离线回测加载、文档与测试补齐。

提交列表（`main..codex/my-fix`）：
- `01e6e3b` chore: save local WIP on fix branch
- `f3a93c7` feat: stabilize relay/resume flow and sync docs
- `01690d0` stabilize llm retry path and sync docs for run doctor
- `99f359a` backtest: add corr-dedup workflow + zoo tools; sync docs
- `75f7e96` docs: ignore pdf artifacts; add paper_text

---

## 2) 修复了哪些（Fix）

### 2.1 运行入口/环境一致性
- `run.sh` 改为**优先使用 `uv + .venv`**（不再依赖 conda），并补齐 `--help`/参数解析与环境检查。
- 修复 `.env` source 可能覆盖调用方已设定环境变量的问题（先保存再恢复）。
- macOS（Darwin）下启用 `daily_pv.h5` 软链行为，修复本地数据链接间歇性失败。

### 2.2 relay/resume 稳定性与可恢复性
- 增强 `--relay/--resume` 控制语义（互斥、fail-fast、日志路径固定、chunk 轮次控制）。
- 在恢复/续跑路径中加强“配置不一致/方向漂移”风险管控（严格检查 + 元信息持久化）。
- 任务粒度恢复更细：优先从任务目录的最新 `__session__` 快照恢复，避免重跑已完成 step。

### 2.3 LLM 重试稳态 + 表达式格式稳定性
- 增强 JSON/结构化输出的稳态策略：协议层 JSON 约束、重试策略（timeout/backoff/jitter）、更稳定的 JSON 修复路径。
- 落地表达式风格约束（operator 写法 + `$` 前缀一致性；风险：中，主要影响生成阶段接受率），并在 proposal/construct 等环节提供更明确的重试反馈与单测覆盖。

### 2.4 回测链路稳定性与结果可追溯
- 回测输出命名引入**因子数量 + 时间戳**（避免同名覆盖；⚠️不改数值，但会增加“选错 latest 文件”的复现风险）。
- 前端/后端支持加载“离线回测结果”（含 runs 列表与 latest 加载），并兼容时间戳命名的匹配逻辑。
- 因子缓存读写抽象为 `factor_cache`（默认 Parquet + ZSTD，兼容 pickle fallback；⚠️表达式不变时 cache 可能复用旧值）。

---

## 3) 新增了哪些文件/功能（Add）

### 3.1 新增脚本/入口（可交付能力）
- `minirun.sh`：轻量冒烟（完整 5-step）+ manifest + Telegram 汇总（可选）。
- `scripts/run_backtest_safe.sh`：独立/安全回测入口（interactive、BOB、FILTER、corr-dedup⚠️、max-factors override、view-results）。
- `scripts/run_doctor.py` + `scripts/run_doctor.sh`：run 进度与诊断报告（支持 watch/doctor/markdown）。
- `scripts/safe_cleanup.py` + `scripts/safe_cleanup.sh`：交互式安全清理（dry-run 默认）。
- `scripts/view_results.py` + `scripts/view_results.sh`：离线结果横向对比（无需重算）。
- `scripts/update_factor_zoo.py`：跨实验表达式去重 zoo 的 build/update/status。
- A/B 与工具脚本：`scripts/abtest_experiment.py`、`scripts/abtest_backtest_memory.py`、`scripts/migrate_factor_cache_to_parquet.py`、`scripts/prepare_warm_start_assets.py`、`scripts/preflight_check.py`、`scripts/fix_missing_factors.py` 等。

### 3.2 新增配置
- `configs/experiment_smoke.yaml`：本地冒烟配置。
- `configs/backtest_2021_validate.yaml` 等：独立回测/验证用配置（已移除 `configs/backtest_limited.yaml`，统一使用 `configs/backtest.yaml` + `--threads/--config` 控制资源与口径）。
- `configs/etf_rotation_workflow_template.yaml`：ETF rotation 工作流模板（配套文档）。

### 3.3 新增文档/规范/工作流
- `SPECS.md`：行为契约/规格对齐（run/relay/resume/backtest 等）。
- `AGENTS.md`：项目执行知识沉淀与入口索引。
- `CHANGELOG.md`：按日期记录新增/修复/回退结论（含 A/B 结果）。
- `docs/PAPER_REPRODUCTION_GUIDE.md`、`docs/performance_optimization_cn.md`、`docs/todo-fix.md` 等：论文复现与优化看板。
- `.codex/workflows/run_doctor.md`：Codex 工作流文档（用于自动化/规范化诊断输出）。

### 3.4 新增测试（回归护栏）
- pipeline/loop/LLM/backtest/workflow 等多处新增单测，用于覆盖：
  - JSON 稳态与 second-round optimization 行为
  - relay/resume 与 session 恢复边界
  - exact-duplicate gate / cheap gate 行为
  - backtest loader 排序与 index 规范化
  - expression style 校验与 construct 止损预算

---

## 4) 哪些“有效的保留了”（默认策略）

以 `docs/performance_optimization_cn.md` 与 `docs/todo-fix.md` 的结论为准，当前默认保留/开启的核心项：
- **协议层强约束 JSON**（正优化，默认开启）。
- **表达式风格稳定性约束**（稳定性修复；风险：中-低，默认开启）。
- **Parquet + ZSTD 缓存格式**（存储收益，默认保留）。
- **网络稳态（timeout/backoff/jitter）**（能力默认开启；failover 能力存在但默认关闭）。
- **low-disk 模式**：`run.sh` 默认开启（可用 `--no-low-disk` 显式关闭；⚠️float32 为 opt-in，高危时不要开）。

---

## 5) 哪些“验证无效回退/关闭了开关”

同样以 `docs/performance_optimization_cn.md` 与 `CHANGELOG.md` 的 A/B 结论为准：
- cheap gate：`quality_gate.cheap_filter_enabled=false`（A/B 负优化 → 默认关闭）。
- 温度分层：json/freeform 温度分层在当前口径下为负优化 → 默认不启用（温度保持一致）。
- construct 止损“收紧”在当前口径下为负优化 → 保持宽松默认（如 2/2/1 策略）。
- 回测“降内存”改造：出现 RSS 上升 + 指标漂移 → 已回滚到 baseline。
- endpoint failover：能力已落地，但 `failover_base_urls=[]` → 默认关闭。
- 受控并行：能力已落地，但 `parallel_enabled=false` → 默认关闭（待专项 A/B）。
- warm-start：能力已落地，但默认 `fresh_start=true`；relay 场景可例外启用（待专项 A/B）。

---

## 6) 本地 WIP（未提交到分支）

- 无（截至 `dc5d05c` 已清零；以 `git status` 为准）

---

## 7) 建议的验证清单（回归）

- 冒烟：`./minirun.sh`
- 诊断：`./scripts/run_doctor.sh`（或 `--watch`）
- 独立回测：`./scripts/run_backtest_safe.sh --interactive`
- 单测：`.venv/bin/python -m pytest`

---

## 附录A：相对 main 的新增文件（已提交）

> `git diff --name-only --diff-filter=A main...codex/my-fix`

- `.codex/workflows/run_doctor.md`
- `AGENTS.md`
- `CHANGELOG.md`
- `SPECS.md`
- `configs/backtest_2021_validate.yaml`
- `configs/etf_rotation_workflow_template.yaml`
- `configs/experiment_smoke.yaml`
- `docs/ETF_ROTATION_CODEX_WORKFLOW_CN.md`
- `docs/PAPER_REPRODUCTION_GUIDE.md`
- `docs/cloud_deployment_guide_cn.md`
- `docs/paper_text.txt`
- `docs/performance_optimization_cn.md`
- `docs/todo-fix.md`
- `docs/warm-up-optimazation.md`
- `minirun.sh`
- `quantaalpha/factors/regulator/expression_style.py`
- `quantaalpha/utils/factor_cache.py`
- `scripts/abtest_backtest_memory.py`
- `scripts/abtest_experiment.py`
- `scripts/factor_filtering/select_factors.py`
- `scripts/fix_missing_factors.py`
- `scripts/migrate_factor_cache_to_parquet.py`
- `scripts/preflight_check.py`
- `scripts/prepare_warm_start_assets.py`
- `scripts/run_backtest_safe.sh`
- `scripts/run_doctor.py`
- `scripts/run_doctor.sh`
- `scripts/safe_cleanup.py`
- `scripts/safe_cleanup.sh`
- `scripts/update_factor_zoo.py`
- `scripts/view_results.py`
- `scripts/view_results.sh`
- `tests/backtest/test_factor_loader_ranking.py`
- `tests/backtest/test_runner_index_normalization.py`
- `tests/factors/test_expression_style_validation.py`
- `tests/factors/test_proposal_stop_loss.py`
- `tests/llm/test_client_json_stability.py`
- `tests/llm/test_client_second_round_optimization.py`
- `tests/pipeline/test_factor_mining_llm_runtime_settings.py`
- `tests/pipeline/test_factor_mining_retry_and_parallel.py`
- `tests/pipeline/test_loop_exact_duplicate_filter.py`
- `tests/pipeline/test_loop_precalc_quality_gate.py`
- `tests/pipeline/test_task_resume_attempt_gating.py`
- `tests/utils/test_workflow_session_resume.py`
- `uv.lock`

## 附录B：相对 main 的修改文件（已提交）

> `git diff --name-only --diff-filter=M main...codex/my-fix`

- `.gitignore`
- `README.md`
- `README_CN.md`
- `configs/backtest.yaml`
- `configs/experiment.yaml`
- `frontend-v2/backend/app.py`
- `frontend-v2/package-lock.json`
- `frontend-v2/package.json`
- `frontend-v2/src/context/TaskContext.tsx`
- `frontend-v2/src/pages/BacktestPage.tsx`
- `frontend-v2/src/services/api.ts`
- `frontend-v2/start.sh`
- `quantaalpha/backtest/README.md`
- `quantaalpha/backtest/custom_factor_calculator.py`
- `quantaalpha/backtest/factor_calculator.py`
- `quantaalpha/backtest/factor_loader.py`
- `quantaalpha/backtest/runner.py`
- `quantaalpha/core/experiment.py`
- `quantaalpha/factors/coder/expr_parser.py`
- `quantaalpha/factors/coder/qa_prompts.yaml`
- `quantaalpha/factors/library.py`
- `quantaalpha/factors/prompts/prompts.yaml`
- `quantaalpha/factors/proposal.py`
- `quantaalpha/factors/regulator/factor_regulator.py`
- `quantaalpha/factors/runner.py`
- `quantaalpha/factors/workspace.py`
- `quantaalpha/llm/client.py`
- `quantaalpha/llm/config.py`
- `quantaalpha/log/__init__.py`
- `quantaalpha/pipeline/evolution/controller.py`
- `quantaalpha/pipeline/factor_mining.py`
- `quantaalpha/pipeline/loop.py`
- `quantaalpha/utils/workflow.py`
- `requirements.txt`
- `run.sh`
