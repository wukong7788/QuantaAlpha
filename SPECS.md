# SPECS.md

> QuantaAlpha 单一执行文档（Single Source of Truth）  
> 最后更新：2026-03-04

## 1. 当前目标（Active Goals）

1. 稳定完成因子挖掘 5-step 全流程（提议/构建/计算/回测/反馈）。
2. 保证低磁盘模式与真接力模式可长期运行，不跑偏、不静默失败。
3. 提升回测与通知可用性：结果文件可追踪、支持横向对比、通知内容可读且为最新结果。

## 2. 非目标（Out of Scope）

1. 不在当前阶段重构整个 pipeline 架构。
2. 不引入与主流程无关的新 UI/新服务依赖。
3. 不为了短期兼容在核心模块加入临时补丁（优先根因修复）。

## 3. 关键约束（Constraints）

1. 运行环境：`uv + .venv`（Python 3.12），不依赖 conda。
2. 数据前置：
   - `QLIB_DATA_DIR` 必须有效并包含 `calendars/ features/ instruments/`
   - `daily_pv.h5` 主/调试路径都必须存在
3. 资源约束：磁盘空间不足时必须快速失败，不继续长流程。
4. 输出约束：回测结果文件必须带因子数与北京时间戳，避免覆盖。

## 3.1 术语对齐（Terminology）

为避免复现与优化沟通中“round/direction/task/step”混淆，统一采用以下层级定义（以演化模式为主）：

1. Experiment：一次 `run.sh` 运行（绑定一个 `EXPERIMENT_ID`）。
2. Direction：planning 生成的探索方向文本集合（数量由 `planning.num_directions` 控制）。
3. Round + Phase：controller 的 **phase-round**（每跑完一个 phase 才会 `round += 1`），不是“epoch=original+mutation+crossover”。
4. Task：一个分支任务，标识为 `(phase, round_idx, direction_id)`，对应日志目录名 `{phase}_{round:02d}_{direction_id:02d}`。
5. Step：task 内固定 5-step：`factor_propose -> factor_construct -> factor_calculate -> factor_backtest -> feedback`（数量由 `execution.steps_per_loop` 控制，默认 5）。
6. Attempt：task 的“空因子重试”次数（数量由 `evolution.max_empty_retries` 控制，默认每 task 最多 2 次 attempt）。

## 4. 执行清单（Task Checklist）

## P0（必须）

- [ ] `minirun.sh` 全流程 smoke：`STEP_N=5` 可稳定完成
- [ ] `run.sh --relay` 真接力可恢复，日志可识别来源实验
- [x] `run.sh --resume` 缺少 `evolution_state.json` 时必须 fail-fast（禁止伪续跑）
- [x] 接力/续跑调度语义可观测（`first_leg_chunk_then_finish` / `resume_to_target`）
- [ ] 续跑颗粒度：task 内部可从 `__session__` 快照继续（不重复已完成 step）
- [ ] `--low-disk` 模式空间保护有效，失败路径可观测
- [ ] 回测输出命名符合 `*_n<num>_<YYYYMMDD_HHMMSS>_*`
- [ ] 通知脚本发送“最新结果”且 JSON 文本可读（含 `\N`, `[]` 等）

## P1（应完成）

- [ ] `run_backtest_safe.sh` BOB 跨多实验聚合可运行
- [ ] 日志中明确输出：选中哪一轮实验、哪些因子进入 BOB
- [x] `--bob-metric auto` 统一解析单一全局指标后再排序（避免混用量纲）
- [x] `run_backtest_safe.sh` 临时文件清理 trap 覆盖早退路径
- [x] `run_backtest_safe.sh` 增加 VIEW 横向对比入口（直接读取结果文件，不触发回测）
- [x] 结果对比输出覆盖风险检查（legacy 命名风险 + 参数对比提示）
- [x] README/CHANGELOG/复现文档与现有行为一致

## 5. 验收标准（Definition of Done）

1. 至少 1 次完整 smoke run 成功，并可定位输出产物。
2. 失败场景（数据缺失/磁盘不足）会明确退出并给出可执行提示。
3. 回测结果可通过文件名唯一回溯到一次运行（不覆盖历史）。
4. 通知消息可直接阅读，不依赖手动再解析 JSON 字符串。

## 6. 命令速查（Runbook）

```bash
# 环境准备
uv venv --python 3.12 .venv
uv pip install -e .

# 快速烟测
./minirun.sh
STEP_N=5 ./minirun.sh

# 主流程
./run.sh "价量因子挖掘" "pv_v1_ds"
./run.sh --low-disk "价量因子挖掘" "pv_v1_ds"
./run.sh --relay "价量因子挖掘" "pv_v1_ds"
./run.sh --resume "价量因子挖掘" "pv_v1_ds"
./run.sh --zoo-dedup --blacklist-file data/factorlib/subtree_blacklist.json "价量因子挖掘" "pv_v1_ds"

# 重要：suffix 只决定因子库文件名，不决定 relay/resume 续跑 lineage
# 如果没有显式设置 EXPERIMENT_ID，--relay/--resume 会默认落到 relay_shared
EXPERIMENT_ID="pv_v1_ds" ./run.sh --relay "价量因子挖掘" "pv_v1_ds"
EXPERIMENT_ID="pv_v1_ds" ./run.sh --resume "价量因子挖掘" "pv_v1_ds"

# 运行进度查看（round/step/factors）
./scripts/run_doctor.sh
./scripts/run_doctor.sh --watch 8
./scripts/run_doctor.sh
./scripts/run_doctor.sh --experiment-id paper_repro_r2

# 因子库总览（历史 all_factors_library*.json 汇总）
./scripts/run_factors.sh
# 交互选项：
# - 1: 列表（显示 n + H/M/L + ARR(p50)）
# - 2: 按 id 删除（支持 1+3+5）
# - 3: 按 id 合并（支持 1+2 或 all；可选 zoo-method=ast|norm|both|none；可选导出 Stage1 expr-dedup pool）
#   合并输出文件自动带因子数+时间戳：<prefix>_n<count>_<YYYYMMDD_HHMMSS>.json
#   合并后会输出 merged 库摘要（n + H/M/L），并打印可直接 export 的 Zoo 路径。
#   FACTOR_CoSTEER_FACTOR_ZOO_PATH 用于指向去重基准 Zoo CSV（FactorRegulator 读取该文件做跨轮次表达式去重）。
# - 5: 过滤流水线（stage0→stage3，可观测）
#   - 输入支持单库或多库 ids（含 all；多库先聚合成总因子池）
#   - Stage0 全量池、Stage1 公式去重、Stage2 暴露相关去重、Stage3 IC 序列去重
#   - 固定默认：Stage1 expr dedup = ast，Stage3 topn = all，输出前缀 = data/factorlib/selected/<source>_filter_pipeline（交互不再单独询问这三项）
#   - 可选仅导出某个 stage 或 all；产物文件名带 n + 时间戳 + stage 后缀
#   - 同时产出 manifest.json，记录每阶段 input/kept/dropped/reasons/path 便于横向对照
# - 6: 导出 subtree blacklist JSON（来源支持 Stage1/merge JSON 或 Zoo CSV）
#   - 默认输出 data/factorlib/subtree_blacklist.json
#   - 产物可直接用于 run.sh --blacklist-file 做 blacklist 模式 A/B

# 可控并行（建议 8 核机器先用 2）
# configs/experiment.yaml
# evolution.parallel_enabled: true
# evolution.max_parallel_workers: 2
# evolution.max_empty_retries: 1

# 预计算过滤与分支止损（construct -> calculate 前）
# quality_gate.cheap_filter_enabled: false  # 默认关闭（A/B（STEP_N=3）为负优化）
# quality_gate.max_construct_failures_per_branch: 2
# quality_gate.max_json_parse_failures_per_branch: 2
# quality_gate.subtree_blacklist_enabled: false
# quality_gate.subtree_blacklist_path: null
# quality_gate.subtree_blacklist_max_patterns: 200
# quality_gate.subtree_blacklist_min_nodes: 1

# LLM 运行时稳态（优化新增选项，非原始基线默认）
# llm.json_mode_response_format: json_object
# llm.json_mode_json_schema: ""
# llm.json_mode_temperature: 0.7  # 默认与 freeform 保持一致；温度分层需单独 A/B 再启用
# llm.freeform_temperature: 0.7
# NOTE: 为避免 QuantaAlpha 与 RD-Agent/LiteLLM 的 env-only 设置漂移，
#       llm.freeform_temperature 会在启动时同步到环境变量 CHAT_TEMPERATURE。
# llm.request_timeout_s: 60.0
# llm.retry_backoff: exponential
# llm.retry_jitter: true
# llm.retry_max_wait_seconds: 30.0
# llm.failover_base_urls: []

# 安全回测
./scripts/run_backtest_safe.sh --library all_factors_library_xxx.json --threads 6
./scripts/run_backtest_safe.sh --library all_factors_library_xxx.json --threads 6 --max-factors 80 --corr-dedup --dedup-method two_stage --dedup-linkage complete --dedup-sample-split train_valid --dedup-per-cluster 1
./scripts/run_backtest_safe.sh --interactive   # 选择单库后可一键启用实盘去重预设
./scripts/run_backtest_safe.sh --factors-filter --library all_factors_library_xxx.json   # 仅执行过滤并输出最终剩余因子数
# 交互第 1 步支持 FILTER+BT：先过滤再回测，并可选择 stage1/stage2/stage3 做对比
# FILTER+BT 交互可选是否补算 uncached（默认跳过；选 y 等价 --no-skip-uncached）
# 日志里 result.h5 miss 仅代表 cache_location 未命中，会自动回退 MD5 cache；MD5 命中不重算
./scripts/run_backtest_safe.sh --bob --bob-libraries "data/factorlib/all_factors_library_*.json" --bob-top 80

# Factor Zoo 管理
.venv/bin/python scripts/update_factor_zoo.py build    # 全量重建
.venv/bin/python scripts/update_factor_zoo.py update   # 增量上传最新实验
.venv/bin/python scripts/update_factor_zoo.py status   # 查看 zoo 状态

# 多轮因子池合并（不做 Top；输出 pool + Zoo（norm/ast）用于 A/B）
.venv/bin/python scripts/factor_filtering/merge_factor_libraries.py \
  --libraries "data/factorlib/all_factors_library_*.json" \
  --out data/factorlib/merged/factor_pool_all.json \
  --zoo-method both --skip-unparsable

# 分阶段过滤名单（全量对照 + stage1(expr) + stage2(exposure) + stage3(IC)）
.venv/bin/python scripts/factor_filtering/select_factors.py \
  --library data/factorlib/merged/factor_pool_all.json \
  --config configs/backtest.yaml \
  --expr-dedup-method norm \
  --out-stage1 data/factorlib/selected/factor_pool_all_stage1_expr.json \
  --out-stage2 data/factorlib/selected/factor_pool_all_stage2_exposure.json \
  --out data/factorlib/selected/factor_pool_all_stage3_final.json \
  --dedup-method two_stage --cluster-linkage complete --per-cluster 1 --topn 80 --compute-missing

# 缓存修复（删除坏缓存 + 重算）
.venv/bin/python scripts/factor_filtering/repair_factor_cache.py \
  --library data/factorlib/merged/factor_pool_all.json \
  --warm-cache --delete-invalid --recompute-missing --recompute-invalid --apply

# 23 轮完整复现(土豪模式， relay 接力 4 次)
EXPERIMENT_ID="paper_repro_23r" QUANTA_RELAY_CHUNK_ROUNDS=6 ./run.sh --rounds 23 --low-disk --relay --zoo-dedup "价量因子挖掘" "paper_repro_23r"

# 回测内存 A/B（峰值 RSS + 耗时，baseline=HEAD，optimized=当前工作区）
.venv/bin/python scripts/abtest_backtest_memory.py baseline -- -c configs/backtest.yaml --factor-source custom --factor-json data/factorlib/all_factors_library_xxx.json --skip-uncached
.venv/bin/python scripts/abtest_backtest_memory.py optimized -- -c configs/backtest.yaml --factor-source custom --factor-json data/factorlib/all_factors_library_xxx.json --skip-uncached

# 实验流程 A/B（baseline/optimized；可重复 times 次并输出对比汇总）
.venv/bin/python scripts/abtest_experiment.py compare --name opt2_json_protocol --base-config configs/experiment_smoke.yaml --direction "价量因子挖掘" --step-n 3 --times 3 --set-baseline llm.json_mode_response_format=none --set-optimized llm.json_mode_response_format=json_object
# 脚本会实时打印 [ABTEST] 进度（start/finished/doctor + run_log 路径），避免长跑期间“无输出”误判。
# `ABTEST_RESULT`/`ABTEST_SUMMARY` 还会附带基于 `data/factorlib/all_factors_library_<suffix>.json` 提取的 `factor_quality` 汇总（每个因子的 `backtest_results` 指标中位数/最优值），以及 `subtree_blacklist` 是否命中（从 run.log 统计 rejected 次数）。

# 横向对比（不重算，直接读结果文件）
./scripts/run_backtest_safe.sh --view-results
./scripts/run_backtest_safe.sh --view-results --view-pick 1,2,3 --view-latest 20
```

## 7. 会话变更日志（Session Log）

- 2026-03-07:
  - 文档补充 relay/resume 误用陷阱：`suffix` 仅控制 `all_factors_library_<suffix>.json`，不控制续跑 lineage。
  - 明确 `run.sh` 在 `--relay/--resume` 且未显式设置 `EXPERIMENT_ID` 时会默认使用 `relay_shared`，可能导致“接错实验但仍写入目标 suffix 因子库”。

- 2026-02-26:
  - 修复 `~/.codex/scripts/notify-telegram.sh`
  - 优先提取最新结果字段（`last-assistant-message` 等）
  - 增强 JSON 字符串格式化与异常转义兼容（如 `\N`, `[]`）
  - `run_backtest_safe.sh` 交互第 1 步增加 `VIEW`（与 EXP/BOB 并列）
  - 新增结果横向对比能力（读取 `*_backtest_metrics.json` + 关联 `pid` 参数信息）
  - 增加覆盖风险提示（legacy 命名可能覆盖、参数维度风险提示）
  - `run.sh --resume` 严格化：缺少 `evolution_state.json` 立即失败（不再隐式从 round 0 新跑）
  - 接力调度语义落盘并打印：`first_leg_chunk_then_finish`（relay）/`resume_to_target`（resume）
  - `run_backtest_safe.sh` 的 BOB `auto` 指标改为“单次运行统一主指标”后排序
  - `run_backtest_safe.sh` 临时文件清理 trap 前置，覆盖早退/中断路径
  - 同步更新 `README.md`、`README_CN.md`、`docs/PAPER_REPRODUCTION_GUIDE.md`、`CHANGELOG.md`
  - `run.sh` 默认开启 low-disk 模式；新增 `--no-low-disk` 显式关闭入口
  - 运行进度 doctor 入口统一为 `scripts/run_doctor.sh`（默认单次 Markdown 报告，含进度与报错诊断）。
  - LLM JSON 输出稳态化：空响应快速重试；修复失败后触发一次 JSON-only 跟进；失败原因结构化日志输出。
  - 构造阶段上下文窗口恢复：`DEFAULT_HISTORY_LIMIT` 已回到 `6`（初始默认值）；失败反馈仍使用短摘要（错误类型 + 修复指令 + 反例）。
  - 受控并行上线：新增 `evolution.max_parallel_workers`，避免并行阶段一次性拉满所有任务。
  - 预计算 cheap gate 前置：在 `factor_calculate` 前过滤静态不合格表达式，减少无效 calculate/backtest。
  - 分支止损预算外置：新增 `evolution.max_empty_retries`、`quality_gate.max_construct_failures_per_branch`、`quality_gate.max_json_parse_failures_per_branch`。

- 2026-02-27:
  - 细粒度续跑：evolution task 支持从 task 目录下最新 `__session__` pickle 快照继续执行，避免重启后从 task 起始 step 重新跑。
  - LLM 协议层 JSON 约束：`json_mode=true` 调用支持 `response_format=json_object/json_schema`，并修复 `reasoning_flag=true && json_mode=false` 被误判为 JSON 模式的问题。
  - 分阶段温度分层：新增 `llm.json_mode_temperature` 与 `llm.freeform_temperature`，将结构化输出稳定性与自由生成多样性解耦。
  - 网络稳态优化：新增 `llm.request_timeout_s`、指数退避/抖动/最大等待与 `llm.failover_base_urls`，降低尾延迟卡顿。
  - 跨轮次 exact 去重：`factor_calculate/backtest` 前增加历史已见表达式过滤，skip 原因记录 `duplicate_exact`。

- 2026-02-28:
  - 增加回测内存 A/B 工具：`scripts/abtest_backtest_memory.py`（baseline=HEAD，optimized=当前工作区）。
  - `run_backtest_safe.sh` 增加相关性去重入口：`--corr-dedup`（支持 `--dedup-per-cluster`，默认 3）。
  - 第三轮优化（回测降内存）尝试后回滚：A/B Test 显示峰值内存上升，判定为负优化（保留 A/B 工具用于后续验证）。
  - 增加实验流程 A/B 工具：`scripts/abtest_experiment.py`（按配置开关对照运行 `./run.sh`，产物隔离到 `/tmp`，并生成 doctor 报告）。
  - opt1（cheap gate + duplicate_exact）在 `STEP_N=3` 用例下 A/B 为负优化，已默认关闭（仍可手动开启并在目标用例上复测）。
  - opt2（协议层 JSON 强约束）A/B 为正优化，保持默认开启：`llm.json_mode_strict=true`、`llm.json_mode_response_format=json_object`。

- 2026-02-28 (第二批):
  - **Factor Zoo 跨轮次去重流水线**：新增 `scripts/update_factor_zoo.py`（`build / update / status`），同时输出 JSON（元数据）+ CSV（`factor_zoo.csv`，供 `FactorRegulator` `pd.read_csv` 加载）。
  - **`run.sh --zoo-dedup`**：新 flag，导出 `FACTOR_CoSTEER_FACTOR_ZOO_PATH`，实验结束后自动调用 `update_factor_zoo.py update`。
  - **`run.sh --rounds N`**：新 flag，创建临时配置覆盖 `evolution.max_rounds`（基于 Python 文本替换，避免不同 `sed` 实现导致覆盖失效），运行结束后自动清理临时文件。
  - **`minirun.sh --low-disk / --zoo-dedup`**：新增 flag 解析，透传给内部 `run.sh`。
  - **`configs/backtest_2021_validate.yaml`**：新增，回测区间对齐 2021-01-01 ~ 2021-12-31（与挖掘期内打分口径一致）。
  - **`PAPER_REPRODUCTION_GUIDE.md` 脚本区重构**：脚本 0（minirun）、脚本 1（安全模式 + zoo-dedup）、脚本 2（土豪 23 轮，化简为 2 步）。
  - **`AGENTS.md` / `SPECS.md`** 同步更新以上全部变更。
- 2026-02-28 (第三批):
  - **配置入口收敛**：删除冗余的 `configs/experiment_full_11.yaml`；主实验统一使用 `configs/experiment.yaml`。
  - **满血基线硬编码**：在 `experiment.yaml` 中硬编码论文最强探索配置：`factor.factors_per_hypothesis: 3`，`evolution.max_rounds: 23`，并内置分段存盘 `evolution.relay_chunk_rounds: 6`，彻底免除向 CLI 传超长环境变量的负担。
  - **冒烟配置恢复**：恢复 `configs/experiment_smoke.yaml` 作为专用轻量配置；`minirun.sh` 默认使用该配置，避免误触发主实验级参数。
- 2026-03-01:
  - **低磁盘精度默认值调整**：`QUANTA_LOW_DISK_FLOAT32` 默认改为 `false`，包括 `--low-disk` 模式下也默认保持 `float64`；仅在显式设置环境变量时才启用 `float32` 降精度。
  - **启动参数可观测性增强**：`run.sh` 启动时新增打印 low-disk 运行参数，并增加 `paper.factor_setting_match`（检查 `factor.factors_per_hypothesis=3` 是否与论文复现基线一致）。
- 2026-03-02:
  - **因子过滤脚本归档**：将因子去重主脚本迁移到 `scripts/factor_filtering/select_factors.py`（专用目录）。
  - **相关性去重防泄漏口径上线**：`scripts/factor_filtering/select_factors.py` 新增 `--sample-split train_valid|full`，默认 `train_valid`（仅使用 train+valid 估计去重相关性）。
  - **回测安全脚本参数透传**：`scripts/run_backtest_safe.sh` 新增 `--dedup-sample-split` 并写入 summary/pid 元数据。
  - **两阶段去重落地**：默认 `--dedup-method two_stage`，执行 Stage-1（暴露相关粗筛）+ Stage-2（IC 序列相关精筛）。
  - **聚类策略升级**：新增 `--dedup-linkage complete|connected`（默认 `complete`），替代单一连通分量逻辑。
  - **冠军打分升级**：Stage-2 采用组合分数 `abs(mean_ic)*max(ir,0)*coverage*stability*capacity_penalty`。
  - **交互入口一键预设**：`run_backtest_safe.sh --interactive` 在单库 custom 模式下新增“实盘去重预设”开关，可一键填充 two_stage 推荐参数。
  - **交互入口新增 FILTER 模式**：`run_backtest_safe.sh --interactive` 第 1 步新增 `FILTER` 目标，仅执行“质量预筛 + 去重”并退出，输出 `experiment/quality_range/final_selected`，并将结果写入 `data/factorlib/selected/`。
  - **Stage-1 截断口径修正**：`select_factors.py` 中 Stage-1 仅做粗去重池化，不再按 `--dedup-topn` 做全局截断；`--dedup-topn` 只在 Stage-2 后执行，避免早期损失多样性。
- 2026-03-03:
  - **安全回测配置收敛**：移除 `configs/backtest_limited.yaml`，`run_backtest_safe.sh` 在未显式传 `--config` 时统一使用 `configs/backtest.yaml`。
  - **安全回测参数收敛**：移除 `--mode` 入口，资源控制统一通过 `--threads` 显式设置；`limited/performance` 双模式不再保留。
  - **多轮因子池合并 + Zoo A/B**：新增 `scripts/factor_filtering/merge_factor_libraries.py`，可合并多库为 pool，并生成 `norm/ast` 两种 Zoo CSV/JSON 供新实验名单过滤。
  - **过滤分阶段导出**：`scripts/factor_filtering/select_factors.py` 新增 `--expr-dedup-method`（Stage-0 表达式去重）与 `--out-stage1/--out-stage2`（导出 stage1/2 名单）用于对照。
  - **缓存修复脚本**：新增 `scripts/factor_filtering/repair_factor_cache.py`（删除坏缓存 + 重算）。
  - **回测重名列不覆盖**：统一采用“自动改名保留全部”（`<factor_name>__<factor_id>`）策略，并增加回归测试覆盖。

## 8. 使用规则（How to Maintain）

1. 每次开始新任务前，先更新“当前目标”和“执行清单”。
2. 完成任务后，立刻勾选清单并写入“会话变更日志”。
3. 若行为变更影响用户使用，必须同步更新 README/CHANGELOG。
