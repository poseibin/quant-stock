# 通用策略 AutoTune V1 TODO

目标：把通用策略从“一次训练后人工判断”升级为“自动实验闭环”。程序负责受控参数搜索和准入裁判，DeepSeek 负责中文复盘和下一轮方向建议，但不直接启用策略。

## 1. 设计边界

- [x] AutoTune V1 先优化 `ml_factor_ranker` 的落地参数，不重训 LightGBM 超参。
- [x] 第一阶段参数范围聚焦：
  - `selection.min_pred_rank`
  - `position.n_holdings`
  - `position.max_single_weight`
  - `position.max_industry_weight`
  - `filters.market_regime.*_exposure`
  - `filters.stress_controls.*`
  - `filters.crash_gate.*`
  - `filters.crash_exit.*`
- [x] LightGBM 超参调优放到 AutoTune V2：
  - `num_leaves`
  - `min_child_samples`
  - `learning_rate`
  - `n_estimators`
  - `sample_weight` 方案
- [x] DeepSeek 只输出解释和方向，不直接写生产配置。
- [x] 所有 DeepSeek 建议必须经过程序白名单和数值边界校验。
- [x] 没有 DeepSeek token、调用失败、返回 JSON 不合规时，规则调参器继续运行。

## 2. MySQL 表设计

- [x] 新增 `factor_autotune_runs`
  - `run_id`
  - `base_model_run_id`
  - `start_date`
  - `end_date`
  - `status`
  - `best_trial_id`
  - `best_model_run_id`
  - `best_admission`
  - `best_score`
  - `summary_json`
  - `created_at`
  - `updated_at`
- [x] 新增 `factor_autotune_trials`
  - `run_id`
  - `trial_id`
  - `round_no`
  - `source`
  - `model_run_id`
  - `eval_run_id`
  - `params_json`
  - `llm_direction_json`
  - `admission`
  - `admission_score`
  - `reason`
  - `annual_return`
  - `total_return`
  - `max_drawdown`
  - `sharpe`
  - `stress_bad_event_count`
  - `stress_crash_state_failed`
  - `stress_weak_drawdown_failed`
  - `passed`
  - `created_at`
  - `updated_at`
- [x] 新增索引：
  - `idx_factor_autotune_trials_run_round`
  - `idx_factor_autotune_trials_passed`
  - `idx_factor_autotune_trials_score`
- [x] 表结构必须只使用 MySQL 类型，不引入 SQLite 兼容字段。

## 3. Core Worker

- [x] 新增 `quant_stock_core/scripts/factor_autotune_worker.py`
- [x] CLI 参数：
  - `--run-id`
  - `--base-model-run-id`
  - `--start`
  - `--end`
  - `--max-rounds`
  - `--trials-per-round`
  - `--use-deepseek`
  - `--deepseek-model`
  - `--deepseek-token`
  - `--activate-best`
- [x] Worker 主流程：
  - [x] 读取最新 `eval_strategy_admission` 和 `factor_model_stress_results`
  - [x] 读取基础 `ml_factor_ranker` 配置
  - [x] 根据失败原因生成第一轮参数候选
  - [x] 每个 trial 设置 `QUANT_STRATEGY_OVERRIDES_JSON`
  - [x] 调用 `evaluate_strategies.evaluate(...)`
  - [x] 保存 `eval_strategy_admission`
  - [x] 保存 `factor_autotune_trials`
  - [x] 每轮结束调用 DeepSeek 生成复盘和下一轮方向
  - [x] 将 DeepSeek 建议映射到受控参数候选
  - [x] 找到可启用 trial 后可提前结束
  - [x] `--activate-best` 时只允许准入通过版本写入 `strategy_model_active`
- [x] Worker 进度写入 `task_run_status`
  - task 名称：`factor_autotune`
  - 阶段：`prepare` / `trial` / `deepseek_review` / `admission` / `done`

## 4. 参数生成规则

- [x] 如果失败原因包含 `股灾状态`
  - 降低 `crash_exposure`
  - 启用/增强 `crash_gate`
  - 启用/增强 `crash_exit`
  - 提高 `min_pred_rank`
- [x] 如果失败原因包含 `弱市回撤`
  - 降低 `weak_exposure`
  - 提高 `stress_min_amount_mult`
  - 降低 `max_vol20`
  - 降低 `max_turnover_rate`
- [x] 如果失败原因包含 `压力段失效`
  - 提高防守过滤强度
  - 降低单票仓位
  - 降低行业上限
- [x] 如果收益低但回撤可接受
  - 轻微放宽 `min_pred_rank`
  - 增加 `n_holdings`
  - 保持 crash gate 不变
- [x] 如果无持仓或样本过少
  - 放宽 `min_pred_rank`
  - 降低过严的波动/换手过滤
- [x] 所有候选必须满足边界：
  - `0.94 <= min_pred_rank <= 0.99`
  - `8 <= n_holdings <= 40`
  - `0.015 <= max_single_weight <= 0.05`
  - `0.06 <= max_industry_weight <= 0.20`
  - `0.0 <= crash_exposure <= 0.10`
  - `0.05 <= weak_exposure <= 0.35`

## 5. DeepSeek 复盘层

- [x] 复用已有 DeepSeek 配置：
  - `deepseek_token`
  - `deepseek_model`
- [x] Python 侧支持从环境变量读取：
  - `DEEPSEEK_TOKEN`
  - `DEEPSEEK_MODEL`
- [x] DeepSeek 输入必须是结构化 JSON：
  - 最近准入记录
  - 压力分段结果
  - 当前参数
  - trial 结果列表
  - 参数边界
- [x] DeepSeek 输出必须是 JSON：
  - `analysis_md`
  - `diagnosis`
  - `next_direction`
  - `parameter_intents`
  - `risks`
  - `validation_plan`
- [x] 程序只接受 `parameter_intents` 中白名单字段。
- [x] DeepSeek 原始返回和解析结果都落 `llm_direction_json`。

## 6. Desktop 任务编排

- [x] 新增 task type：`factor_autotune`
- [x] `task.NewRunID` 增加前缀：`fat`
- [x] `StartTask` 支持 `factor_autotune`
- [x] 新增 App 方法：
  - `RunFactorAutoTune`
  - `ListFactorAutoTuneRuns`
  - `ListFactorAutoTuneTrials`
- [x] 任务参数：
  - `base_model_run_id`
  - `start_date`
  - `end_date`
  - `max_rounds`
  - `trials_per_round`
  - `use_deepseek`
  - `activate_best`
- [x] 运行环境注入：
  - `DATA_ROOT`
  - MySQL DSN
  - DeepSeek token/model

## 7. 前端页面

- [x] 通用策略 > 模型训练 增加 `自动调参` 按钮。
- [x] 增加 AutoTune 面板：
  - 当前最新模型
  - 当前准入状态
  - 当前失败原因
  - 调参运行状态
  - 最佳 trial
- [x] 增加 trial 表格：
  - 轮次
  - 参数摘要
  - 准入结论
  - 准入分
  - 年化
  - 回撤
  - 夏普
  - 压力失败原因
  - DeepSeek 建议摘要
- [x] 只有 `passed=true` 的 trial 显示“可启用”。
- [x] 页面文案必须明确区分：
  - 训练失败
  - 训练成功但准入失败
  - 调参失败
  - 已找到可启用版本

## 8. 自动化测试计划

### 8.1 Python 单测

- [x] `tests/test_factor_autotune_worker.py`
  - [x] 股灾/弱市/压力段失败生成更防守参数
  - [x] 参数边界裁剪正确
  - [x] DeepSeek 空 token 时回退
  - [x] DeepSeek 非 JSON 返回时回退
  - [x] 校验只接受白名单字段
  - [x] trial 结果能写入 MySQL
  - [x] 可启用 trial 能写入 `strategy_model_active`
  - [x] 不可启用 trial 不能写 active

### 8.2 Python MySQL 集成测试

- [x] `make test-mysql` 通过现有 MySQL 辅助和缓存集成测试。
- [x] `make test-mysql` 增加 AutoTune 专项入口：
  - [x] 建表成功
  - [x] trial 写入成功
  - [x] trial upsert 幂等
  - [x] active 只写准入通过版本
  - [x] 不污染真实推荐表
- [x] `make e2e-mysql` 在没有 active 模型时能明确失败原因。

### 8.3 Go 测试

- [x] `go test ./...`
- [x] task type 已接入：
  - [x] `factor_autotune` 能进入任务启动白名单
  - [x] run id 前缀正确
  - [x] DeepSeek token/model 参数注入 worker
  - [x] Python worker 命令参数正确
- [x] DB schema 已接入：
  - [x] `factor_autotune_runs` 存在
  - [x] `factor_autotune_trials` 存在
  - [x] 索引存在

### 8.4 前端测试/构建

- [x] `npm run build`
- [x] TypeScript 类型覆盖：
  - [x] `FactorAutoTuneRun`
  - [x] `FactorAutoTuneTrial`
  - [x] `RunFactorAutoTune`
- [x] 页面状态检查：
  - [x] 无模型
  - [x] 有模型但准入失败
  - [x] 调参运行中
  - [x] 找到可启用 trial
  - [x] DeepSeek 不可用但规则调参继续

### 8.5 手动端到端验收

- [x] 清理 AutoTune 测试数据。
- [x] 确认已有 `factor_model_runs`。
- [x] 运行 AutoTune smoke：
  - `max_rounds=1`
  - `trials_per_round=2`
  - `use_deepseek=false`
- [x] 验证：
  - `factor_autotune_runs` 有记录
  - `factor_autotune_trials` 有记录
  - 每个 trial 有 `params_json`
  - 每个 trial 有准入结论
- [x] 再运行 DeepSeek 模式：
  - `use_deepseek=true`
  - DeepSeek 失败不影响 trial 执行
- [x] 如果有可启用 trial：
  - `strategy_model_active` 写入
  - 通用策略页面显示当前启用版本

## 9. 代码准确性校对清单

- [x] 所有新 SQL 只面向 MySQL，不出现 SQLite 语法。
- [x] 所有 JSON 字段使用 `LONGTEXT`。
- [x] 不使用 MySQL 保留字作为裸列名，例如 `rank`。
- [x] 所有参数候选都经过边界裁剪。
- [x] DeepSeek 输出不能直接覆盖配置。
- [x] DeepSeek 输出不能直接写 active。
- [x] `eval_strategy_admission` 的 run_id 命名可追溯到 trial。
- [x] trial 的 `params_json` 能完整复现实验。
- [x] 失败日志要包含 Python exception。
- [x] 页面展示不能把“准入失败”写成“训练失败”。
- [x] 不改动基础行情数据表。
- [x] 不依赖 `top10_holders`。
- [x] 不引入 SQLite 文件路径或 `meta.db`。

## 10. 验收标准

- [x] `make test` 通过。
- [x] `make test-mysql` 通过。
- [x] `go test ./...` 通过。
- [x] `npm run build` 通过。
- [x] `make e2e-mysql` 在没有 active 模型时能明确失败原因。
- [x] AutoTune smoke 至少能跑完 2 个 trial。
- [x] 页面能看到每个 trial 的参数、收益、回撤、准入和 DeepSeek 复盘。
- [x] 找到可启用 trial 时，`strategy_model_active` 自动更新。
- [x] 没找到可启用 trial 时，不写 active，并给出下一轮方向。

## 11. 后续 V2 Backlog

以下不是本轮 AutoTune V1 验收项，作为下一阶段方向保留：

- 把 LightGBM 超参纳入搜索。
- 引入贝叶斯优化或 successive halving。
- 多目标排序：收益、回撤、压力段、换手、容量。
- 支持 T0、横盘、涨停模型复用 AutoTune 框架。
- DeepSeek 复盘写入微信推送。
