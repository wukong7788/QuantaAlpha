# SPECS.md

> QuantaAlpha 单一执行文档（Single Source of Truth）  
> 最后更新：2026-02-27

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

# 运行进度查看（round/step/factors）
./scripts/run_doctor.sh
./scripts/run_doctor.sh --watch 8
./scripts/run_doctor.sh
./scripts/run_doctor.sh --experiment-id paper_repro_r2

# 可控并行（建议 8 核机器先用 2）
# configs/experiment.yaml
# evolution.parallel_enabled: true
# evolution.max_parallel_workers: 2
# evolution.max_empty_retries: 1

# 预计算过滤与分支止损（construct -> calculate 前）
# quality_gate.cheap_filter_enabled: true
# quality_gate.max_construct_failures_per_branch: 2
# quality_gate.max_json_parse_failures_per_branch: 2

# LLM 运行时稳态（优化新增选项，非原始基线默认）
# llm.json_mode_response_format: json_object
# llm.json_mode_json_schema: ""
# llm.json_mode_temperature: 0.0
# llm.freeform_temperature: 0.5
# llm.request_timeout_s: 60.0
# llm.retry_backoff: exponential
# llm.retry_jitter: true
# llm.retry_max_wait_seconds: 30.0
# llm.failover_base_urls: []

# 安全回测
./scripts/run_backtest_safe.sh --library all_factors_library_xxx.json --mode limited
./scripts/run_backtest_safe.sh --bob --bob-libraries "data/factorlib/all_factors_library_*.json" --bob-top 80

# 横向对比（不重算，直接读结果文件）
./scripts/run_backtest_safe.sh --view-results
./scripts/run_backtest_safe.sh --view-results --view-pick 1,2,3 --view-latest 20
```

## 7. 会话变更日志（Session Log）

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
  - 构造阶段上下文瘦身：`DEFAULT_HISTORY_LIMIT` 从 `6` 调整到 `4`，失败反馈改为短摘要（错误类型 + 修复指令 + 反例）。
  - 受控并行上线：新增 `evolution.max_parallel_workers`，避免并行阶段一次性拉满所有任务。
  - 预计算 cheap gate 前置：在 `factor_calculate` 前过滤静态不合格表达式，减少无效 calculate/backtest。
  - 分支止损预算外置：新增 `evolution.max_empty_retries`、`quality_gate.max_construct_failures_per_branch`、`quality_gate.max_json_parse_failures_per_branch`。

- 2026-02-27:
  - 细粒度续跑：evolution task 支持从 task 目录下最新 `__session__` pickle 快照继续执行，避免重启后从 task 起始 step 重新跑。
  - LLM 协议层 JSON 约束：`json_mode=true` 调用支持 `response_format=json_object/json_schema`，并修复 `reasoning_flag=true && json_mode=false` 被误判为 JSON 模式的问题。
  - 分阶段温度分层：新增 `llm.json_mode_temperature` 与 `llm.freeform_temperature`，将结构化输出稳定性与自由生成多样性解耦。
  - 网络稳态优化：新增 `llm.request_timeout_s`、指数退避/抖动/最大等待与 `llm.failover_base_urls`，降低尾延迟卡顿。
  - 跨轮次 exact 去重：`factor_calculate/backtest` 前增加历史已见表达式过滤，skip 原因记录 `duplicate_exact`。

## 8. 使用规则（How to Maintain）

1. 每次开始新任务前，先更新“当前目标”和“执行清单”。
2. 完成任务后，立刻勾选清单并写入“会话变更日志”。
3. 若行为变更影响用户使用，必须同步更新 README/CHANGELOG。
