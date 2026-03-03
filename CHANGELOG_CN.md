# 变更日志

格式：按日期分段；常用分区为 `新增 / 修复 / 性能 / 变更 / 移除`（可选：`重点 / 文档 / 内部`）。
每条变更以标签开头：`[area][impact]`（可选严重级别：`[P0|P1|P2]`），便于 grep；标签保持英文以便与 `CHANGELOG.md` 对照。

## 2026-03-03

### 新增
- [scripts][feature] 多因子库合并 + Zoo 构建器：
  - `scripts/factor_filtering/merge_factor_libraries.py` 将多个 `all_factors_library*.json` 合并为一个汇总库（不做 Top-N 选择）。
  - 支持生成用于 A/B 测试的 Zoo 输出：空白归一化（`norm`）与 AST 规范化（`ast`）。
- [scripts][feature] 缓存修复工具：
  - `scripts/factor_filtering/repair_factor_cache.py` 扫描 MD5 cache 条目，删除无效条目并重算以重建 cache。
- [scripts][feature] 过滤阶段导出：
  - `scripts/factor_filtering/select_factors.py` 支持 `--expr-dedup-method`，并提供阶段输出 `--out-stage1/--out-stage2` 用于全流程 vs 分阶段对比。
- [scripts][feature] 交互式因子库管理器：
  - `scripts/run_factors.sh` 选项 `1`：列出 `all_factors_library*.json` 摘要（因子数、quality H/M/L、ARR）。
  - `scripts/run_factors.sh` 选项 `2`：按 id 删除因子库（支持 `+` 批量输入）。
  - `scripts/run_factors.sh` 选项 `4`：按因子库 id 修复 factor MD5 cache（dry-run + apply）。
  - `scripts/run_factors.sh` 选项 `3`：按 id 合并因子库（支持 `+` 批量输入与 `all`），支持 `zoo-method=ast|norm|both|none`，自动命名 `<prefix>_n<count>_<timestamp>.json`，并打印合并后的 `n + H/M/L` 摘要与 `FACTOR_CoSTEER_FACTOR_ZOO_PATH` 的 export 提示。
  - `scripts/run_factors.sh` 选项 `5`：运行可观测的过滤流水线（`stage0→stage3`），可选择阶段输出（`stage0|stage1|stage2|stage3|all`），并输出每次运行的 `manifest.json`。
  - 简化选项 `5` 的交互默认值：Stage1 表达式去重固定为 `ast`，Stage3 topn 固定为 `all`，输出前缀默认 `data/factorlib/selected/<source>_filter_pipeline`（无额外提示）。

### 变更
- [scripts][behavior] 简化安全回测配置布局：
  - 移除 `configs/backtest_limited.yaml`。
  - `scripts/run_backtest_safe.sh` 默认使用 `configs/backtest.yaml`（除非显式传入 `--config`）。
- [scripts][behavior] 简化安全回测运行时控制：
  - 移除 `scripts/run_backtest_safe.sh` 的 `--mode`。
  - 资源控制改为显式 `--threads <N>`。

### 修复
- [backtest][output][P1] 修复回测因子计算时重复 `factor_name` 导致列被静默覆盖（强制唯一输出 key：追加 `__<factor_id>`）。

## 2026-03-02

### 变更
- [factors][behavior] 恢复因子 proposal 历史窗口默认值：
  - `DEFAULT_HISTORY_LIMIT` 从 `4` 改回 `6`。
  - 在保留精简 retry-summary 反馈的同时，使 O3 “history window optimization” 默认不启用。
- [scripts][behavior] 更新相关性去重采样范围以避免测试泄漏：
  - 去重选择器移动到 `scripts/factor_filtering/select_factors.py`。
  - `select_factors.py` 支持 `--sample-split train_valid|full`，默认 `train_valid`。
  - 阶段元数据增加 sample window、linkage/method 等字段。
- [scripts][feature] 实现两阶段去重流水线：
  - Stage-1：暴露（exposure）相关性粗筛。
  - Stage-2：IC 序列相关性细筛。
  - 新增方法开关：`--dedup-method stage1|two_stage`（默认 `two_stage`）。
- [scripts][behavior] 升级去重的聚类与排序：
  - 新增 linkage 开关：`--dedup-linkage complete|connected`（默认 `complete`）。
  - Stage-2 champion score 升级为复合指标：
    `abs(mean_ic)*max(ir,0)*coverage*stability*capacity_penalty`。
- [scripts][behavior] 更新安全回测 wrapper 对去重采样/参数的支持：
  - `scripts/run_backtest_safe.sh` 新增支持：
    - `--dedup-sample-split <train_valid|full>`
    - `--dedup-method <stage1|two_stage>`
    - `--dedup-linkage <complete|connected>`
    - `--dedup-stage2-corr-threshold <T>`
  - 运行摘要与 PID 元数据记录 method/linkage/stage2 threshold 字段。
- [scripts][behavior] 更新交互回测入口：
  - `scripts/run_backtest_safe.sh --interactive` 在 single-library custom mode 增加“一键生产级 dedup preset”。
  - preset 参数：`corr_dedup=true`, `dedup_method=two_stage`, `dedup_linkage=complete`, `sample_split=train_valid`, `topn=50`, `per_cluster=1`, `corr_threshold=0.8`, `stage2_corr_threshold=0.8`, `sample_size=12000`, `compute_missing=true`。
  - Step-1 目标新增 `FILTER`（`factors-filter`）：仅跑过滤流水线（不回测），打印简洁摘要，并将输出保存到 `data/factorlib/selected/`。
- [scripts][output] 简化 FILTER 模式输出命名与摘要：
  - FILTER 快速摘要仅强调 `experiment`、`quality_range` 与最终选中数量。
  - FILTER 结果文件命名简化且绑定 experiment：
    `<experiment>_factors_filter_q<quality>_n<count>_<timestamp>.json`。
  - 稳定别名仍为 `<experiment>_factors_filter_latest.json`，方便回测复用。
- [scripts][feature] 安全脚本新增仅过滤（不回测）CLI 模式：
  - `--factors-filter` 强制走 custom dedup 路径，跳过回测，并输出 preview 产物便于快速检查。

### 修复
- [scripts][reliability] 修正去重 Stage-1 的截断行为：
  - Stage-1 不再做全局 TopN 截断。
  - `--dedup-topn` 仅在 Stage-2 选择后应用。
  - 保留跨 cluster 的多样性，再进入 IC 序列的细筛。

## 2026-02-26

### 新增
- [scripts][feature] `run.sh` 新增真正 relay 模式入口：
  - `--relay`（固定 `LOG_TRACE_PATH` + 明确续跑意图）
  - launcher 接入 `QUANTA_ENABLE_RELAY=1`
- [scripts][feature] `run.sh` 新增严格 resume 入口：
  - `--resume`（与 `--relay` 互斥，直接续跑到目标 round）
- [pipeline][reliability] 增加 relay 恢复源信息日志：
  - `Relay resume source: previous_experiment_id=..., state_saved_at_utc=..., previous_log_trace_path=...`
- [scripts][feature] 增加运行进度查看工具：
  - `scripts/run_doctor.py`
  - `scripts/run_doctor.sh`
- [scripts][feature] 增加 doctor 诊断模式：
  - `scripts/run_doctor.sh --doctor`
  - `scripts/run_doctor.py --doctor`
- [scripts][feature] 增加终端 doctor 入口：
  - `scripts/run_doctor.sh`（默认单次报告）
- [configs][feature] 增加受控并行配置：
  - `evolution.max_parallel_workers` 用于限制 `parallel_enabled=true` 时每 phase 的 worker 上限。
- [configs][feature] 增加空分支重试预算配置：
  - `evolution.max_empty_retries`。
- [configs][feature] 增加 construct 阶段止损预算配置：
  - `quality_gate.max_construct_failures_per_branch`
  - `quality_gate.max_json_parse_failures_per_branch`
- [configs][feature] 增加预计算 cheap quality gate 配置：
  - `quality_gate.cheap_filter_enabled`
  - `quality_gate.cheap_filter_require_acceptable`

### 变更
- [pipeline][behavior] 扩展 `evolution_state.json` 持久化内容：
  - run 元信息（`meta.*`）
  - evolution 配置快照（含 selection/parallel flags）
  - 持久化 planning `directions`
- [pipeline][behavior] relay checkpoint 写入 `directions`（task 级）。
- [pipeline][behavior] 澄清 run-control 元数据与启动日志中的 relay 调度语义：
  - `relay`: `first_leg_chunk_then_finish`
  - `resume`: `resume_to_target`
- [scripts][behavior] `run.sh` 默认开启 low-disk；新增 `--no-low-disk` 显式关闭入口。
- [scripts][behavior] doctor 默认输出改为 Markdown 报告（`--doctor --markdown`），便于终端与工作流使用。
- [factors][behavior] 调整因子 proposal 历史窗口：
  - `DEFAULT_HISTORY_LIMIT` 从 `6` 降为 `4`。
  - retry 反馈改为精简摘要（错误类型 + 修复指令 + 反例），减少 prompt 膨胀。
- [pipeline][behavior] 调整并行调度器行为：
  - 并行模式改为按 worker 上限启动任务，而不是一次性拉满所有任务。
- [pipeline][behavior] 调整因子 loop 行为：
  - 在 `factor_calculate` 前增加 pre-calc 静态过滤，提前跳过无效表达式。

### 修复
- [pipeline][reliability] 修复 relay direction 漂移风险：resume 时恢复已保存的 planning `directions`。
- [pipeline][reliability] 修复“resume 但配置不一致”风险：增加严格 config mismatch 检查（默认 fail-fast）。
- [pipeline][reliability] 修复不安全的 legacy resume 路径（in-progress state 无 `directions`）：默认阻止，除非显式设置 `QUANTA_FORCE_RELAY_RESUME=1`。
- [pipeline][reliability] 修复错误的 resume 行为：当缺失 `evolution_state.json` 时，`--resume` 直接 fail-fast（不再隐式从 round-0 重启）。
- [backtest][output] 修复 BOB `--bob-metric auto` 的混尺度排序：先解析一个全局 metric，再统一给所有因子打分。
- [scripts][reliability] 修复 `scripts/run_backtest_safe.sh` 临时文件清理空窗：在 early-exit 分支前安装 cleanup trap。
- [scripts][reliability] 修复 `scripts/preflight_check.py` 的相对路径解析：使 `uv run preflight_check.py ... --config configs/*.yaml` 在 repo root 与 `scripts/` 目录下均可运行。
- [llm][reliability] 修复 LLM 调用链路的 JSON 响应不稳定：
  - JSON-mode 空响应 fail-fast 并直接重试。
  - 解析失败会先触发一次严格 JSON-only 的 follow-up，再进入外层重试。
  - JSON 失败原因以结构化格式输出，便于诊断。
- [pipeline][reliability] 修复 construct 阶段的长耗时分支卡死：
  - 对重复 JSON parse failure / construct failure 触发分支级 stop-loss，避免无界重试。

## 2026-02-27

### 新增
- [llm][feature] `llm.*` 新增第二轮优化运行时配置项（由 `configs/experiment*.yaml` 注入）：
  - `json_mode_temperature`, `freeform_temperature`
  - `json_mode_response_format`, `json_mode_json_schema`
  - `request_timeout_s`, `retry_backoff`, `retry_jitter`, `retry_max_wait_seconds`
  - `failover_base_urls`
- [pipeline][feature] 在高开销阶段前增加跨轮 exact 去重门：
  - 在 `factor_calculate/factor_backtest` 前跳过重复表达式。
  - skip 原因持久化为 `skip_reason=duplicate_exact`。
- [tests][feature] 增加第二轮优化行为的回归测试：
  - `tests/llm/test_client_second_round_optimization.py`
  - `tests/pipeline/test_loop_exact_duplicate_filter.py`
  - `tests/pipeline/test_factor_mining_llm_runtime_settings.py`

### 变更
- [pipeline][behavior] 改进 evolution task 内 relay/resume 粒度：
  - task 会尝试从各自目录下最新的 `__session__` pickle 快照继续执行。
  - 避免进程重启后重复执行已完成的 step。
- [llm][behavior] 调整 `json_mode` 下的 LLM 请求策略：
  - 可强制协议层 JSON 响应格式（`json_object` / 可选 `json_schema`）。
  - 结构化 vs 自由生成调用采用不同温度。
- [llm][behavior] 调整重试等待策略：从固定延迟扩展为可配置的固定/指数退避，并支持 jitter 与 wait cap。

### 修复
- [llm][reliability] 修复 `reasoning_flag=true && json_mode=false` 路径错误地强制 JSON 抽取/修复。
- [llm][reliability] 通过为 chat/embedding 调用增加 per-request timeout 修复网络尾延迟卡顿。
- [pipeline][reliability] 修复跨 loop 的 duplicate-exact cache 陈旧：在每次 construct step 前失效 seen-expression cache。
- [llm][reliability] 修复 failover 触发过度：仅在传输类异常（timeout/connection/rate-limit/server）切换 endpoint，排除 JSON parse/content error。
- [llm][reliability] 修复运行时 bool option 解析（`llm.json_mode_strict`, `llm.retry_jitter`）：正确处理 `"false"` / `"0"` 等 bool-like 字符串。

## 2026-02-28

### 新增
- [backtest][feature] 增加回测内存 A/B 工具：
  - `scripts/abtest_backtest_memory.py`（输出耗时 + peak RSS；baseline=HEAD，optimized=working tree）。
- [scripts][feature] 增加实验 A/B 工具：
  - `scripts/abtest_experiment.py`（按配置开关对照运行 `./run.sh`，产物隔离到 `/tmp`，输出 `ABTEST_RESULT=...` 并保存 doctor 报告）。
  - 新增 `compare` 模式：baseline+optimized（各重复 N 次）并打印 `ABTEST_COMPARISON=...`。
- [scripts][feature] `scripts/run_backtest_safe.sh` 新增相关性去重入口：
  - `--corr-dedup` 及调参项 `--dedup-topn`, `--dedup-per-cluster`（默认 3）, `--dedup-corr-threshold`, `--dedup-sample-size`。
  - 回测 PID 元数据记录 dedup 设置（`corr_dedup`, `dedup_*`），便于对比复盘。

### 性能
- [backtest][mem][P2] 尝试降低 peak-memory，但 A/B 显示 peak RSS 更高，已回滚（负优化）。
- [pipeline][perf] A/B（STEP_N=3）显示耗时更差，默认关闭 cheap pre-calc filter：
  - `quality_gate.cheap_filter_enabled=false`
  - `quality_gate.cheap_filter_require_acceptable=false`
- [llm][perf] A/B 为正优化，保持协议层 JSON 约束默认开启：
  - `llm.json_mode_strict=true`
  - `llm.json_mode_response_format=json_object`
- [llm][perf] A/B（STEP_N=3）显示耗时更差，回退温度分层默认：
  - 默认保持 `llm.json_mode_temperature=0.5` 与 `llm.freeform_temperature=0.5` 一致
- [scripts][perf] low-disk 精度默认保持 `float64`（避免 A/B 中观测到的指标漂移）：
  - `QUANTA_LOW_DISK_FLOAT32`：默认 `false`（含 `--low-disk`）

### 移除
- [configs][internal] 移除冗余配置 `experiment_full_11.yaml`；11 轮 relay 运行使用 `--rounds` + `configs/experiment.yaml`。

### 变更
- [configs][behavior] 将论文复现参数硬编码为默认 `experiment.yaml`：
  - `factor.factors_per_hypothesis: 3`
  - `evolution.max_rounds: 23`
  - `evolution.relay_chunk_rounds: 6`
- [scripts][behavior] 恢复 `configs/experiment_smoke.yaml` 并让 `minirun.sh` 默认使用 smoke-only 配置。
- [scripts][behavior] 增强 `run.sh` 启动时的 paper-mode 摘要输出：
  - 打印 low-disk 运行时开关（`QUANTA_LOW_DISK_MODE/FLOAT32/PARQUET_COMPRESSION/PURGE_*`）
  - 打印 `paper.factor_setting_match` 状态（针对 `factors_per_hypothesis=3`）

## 2026-02-25

### 新增
- [frontend][feature] 前端后端增加离线回测结果 API：
  - `GET /api/v1/backtest-offline/latest`（支持 `metricsFile`）
  - `GET /api/v1/backtest-offline/runs`（列出可选 runs）
- [frontend][feature] 前端回测页面支持加载离线回测结果，并提供 run 下拉选择器。
- [scripts][feature] `scripts/run_backtest_safe.sh` 与交互向导新增 `--max-factors <N|all|default>`。

### 变更
- [backtest][output] 回测结果命名加入因子数量 + 北京时间戳：
  - `<library_or_exp>_n<num_factors>_<YYYYMMDD_HHMMSS>_backtest_metrics.json`
  - `<library_or_exp>_n<num_factors>_<YYYYMMDD_HHMMSS>_cumulative_excess.csv`
- [frontend][behavior] 前后端离线结果匹配逻辑支持带时间戳的结果文件（按 library 前缀匹配）。
- [frontend][behavior] 在线任务结果加载（`_load_backtest_results`）优先选择当前 library 前缀的 metrics 文件，再回退到全局 latest。

### 修复
- [frontend][reliability] 使用独立 offline 路由前缀（`/api/v1/backtest-offline/...`）以降低 backend route 冲突风险。
- [backtest][output] 通过引入带时间戳的输出文件名，修复同一 library 的回测结果反复覆盖问题。

## 2026-02-23

### 新增
- [scripts][feature] 新增快速冒烟脚本 `minirun.sh`（默认 `STEP_N=3`），并包含 preflight checks。
- [scripts][feature] `minirun.sh` 结束时支持可选 Telegram 通知（成功/失败摘要）。
- [configs][feature] 新增 `configs/experiment_smoke.yaml` 用于轻量本地验证。

### 变更
- [scripts][behavior] `run.sh` 直接支持 `uv`/`.venv` 工作流（不再要求 conda）。
- [scripts][behavior] `frontend-v2/start.sh` 使用 `.venv` 与 `uv`，替代 conda。
- [core][behavior] 当未显式设置 `LOG_TRACE_PATH` 时，log 目录时间戳默认使用 Asia/Shanghai（北京时间）。
- [configs][behavior] `.gitignore` 增加对 `hf_data/cn_data.zip` 的忽略规则。

### 修复
- [core][reliability] macOS 因子数据链接问题：在 `quantaalpha/core/experiment.py` 中启用 Darwin 下的 symlink 创建，解决执行阶段间歇性 `daily_pv.h5` not found。

