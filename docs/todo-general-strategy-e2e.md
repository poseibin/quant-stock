# 通用策略端到端重构 Todo

本文档是后续推进的唯一 todo 主线。每一项完成后必须把 `[ ]` 改为 `[x]`，并补充“验收结论”和“证据输出”。没有实际证据不得打勾。

## 推进规则

- 每推进一项，必须更新本文档。
- 每项必须有【分类】、【目标】、【验收结论】、【证据输出】。
- 证据必须来自当前代码、数据、日志、测试命令、报告文件、截图或数据库查询结果。
- 不允许只写“已完成”“应该没问题”。
- 长任务必须有 UI/任务中心/状态表可观测证据。
- 端到端完成前，不得把目标视为完成。

## 0. 当前基线

- [x] 【基线盘点】确认当前代码、数据、模型、快照的真实状态
  - 【目标】列出当前 `stock_factor_base_v1`、旧 `profit_arena_v1`、当前冠军版本、当前持仓执行逻辑的状态。
  - 【验收结论】当前生产宽基座 `stock_factor_base_v1` 尚未生成；旧 `profit_arena_v1` 快照存在但只覆盖 `20240102 -> 20260618`，且无 `quality_gate` 和 `factor_testcase`；当前冠军版本存在；当前持仓执行路径仍存在“非今日目标池持仓清仓”的旧逻辑。
  - 【证据输出】命令 `python3 - <<'PY' ... latest.json ... PY` 输出：`stock_factor_base_v1 latest_exists False`；`profit_arena_v1 latest_exists True`，`feature_set v6all`，`start 20240101`，`trade_date_min 20240102`，`trade_date_max 20260618`，`row_count 1642768`，`feature_count 104`，`quality_gate None`，`factor_testcase None`，`panel_size_bytes 869832155`。执行路径证据见 `quant_stock_desktop/app.go:4672`、`quant_stock_desktop/app.go:5304-5311`、`quant_stock_desktop/app.go:5366-5370`。

- [x] 【旧冠军冻结】冻结当前冠军模型基线指标
  - 【目标】在任何重训前，记录当前冠军模型 run_id、模型文件、feature_set、factor_store_id、horizon、top_n、止盈/止损、收益、回撤、Sharpe、Calmar、RankIC、交易次数等指标。
  - 【验收结论】当前冠军记录已冻结：冠军 JSON 为 `data_store/profit_arena/arena_champion_profit_nolev_rankic_sharpe_dd20_ann45.json`，`run_id=profit_arena_evalonly_h20_near4292_bucket_sharpe_grid_20260615`，`arena_score=93.5`，`champion_version=53`，实际模型来自 `source_run_id=profit_arena_v6all_h20_rawscore_cache_20260615` 的 `model_small_20d.joblib`。
  - 【证据输出】冠军 JSON 输出：`best.scope=small`，`best.horizon=20`，`best.top_n=3`，`best.execution_take_profit=0.25`，`best.execution_stop_loss=0.0`，`best.trade_count=495`，`best.trade_years=10`，`best.capital_annual_return=0.3329873489730901`，`best.capital_max_drawdown=-0.10339757697826435`，`best.capital_sharpe=1.2334687774916866`，`best.rank_ic=0.13139009179621466`，`rank_ic_days=141`。summary 输出：`feature_set=all`，`model_kind=regressor`，`target_mode=net_return`。source 输出：`source_run_id profit_arena_v6all_h20_rawscore_cache_20260615`，`source_predictions data_store/profit_arena/profit_arena_v6all_h20_rawscore_cache_20260615/predictions_small_20d.parquet`，`source_feature_set v6all`，`source_model_file data_store/profit_arena/profit_arena_v6all_h20_rawscore_cache_20260615/model_small_20d.joblib 5098408`。

- [x] 【当前执行基线】冻结当前持仓/调仓执行路径证据
  - 【目标】证明当前执行逻辑是否仍存在每日 TopN 重平衡、清掉不在今日候选的旧持仓等问题，作为修复前基线。
  - 【验收结论】当前执行基线确认存在不一致风险：调仓推荐调用 `buildAccountRebalanceRows(..., true)`，当持仓不在今日目标池且 `clearUnmatched=true` 时设置 `TargetWeight: 0`，随后 `targetShares <= 0` 生成 `action = "清仓"`。这与 h20 生命周期持仓逻辑不一致，是后续必须修复项。
  - 【证据输出】`nl -ba quant_stock_desktop/app.go` 输出：`4672 rows := app.buildAccountRebalanceRows(targets, summary, date, true)`；`5299 func ... clearUnmatched bool`；`5304 if clearUnmatched {`；`5310 TargetWeight: 0`；`5366 action := "持有"`；`5369-5370 holding.Shares > 0 && targetShares <= 0 -> action = "清仓"`。

## 1. 命名与边界

- [x] 【命名】物理宽因子基座统一为 `stock_factor_base_v1`
  - 【目标】代码、配置、前端、任务参数里不再使用错误的长基座名。
  - 【验收结论】已完成命名统一；错误旧名 `stock_daily_technical_hotmoney_v1`、`profit_arena_h20_general_final_v1`、`profit_arena_h20_hotmoney_daily_v1`、`champion_h20_hotmoney_daily_v1` 在核心脚本、桌面端和 docs 中无残留。
  - 【证据输出】命令 `rg -n "stock_daily_technical_hotmoney_v1|profit_arena_h20_general_final_v1|profit_arena_h20_hotmoney_daily_v1|champion_h20_hotmoney_daily_v1" quant_stock_core/scripts quant_stock_desktop docs || true` 输出为空；命令 `feature_columns_for_set('stock_factor_base_v1')` 输出 `137`。

- [x] 【命名】用户可见“收益擂台”改为“通用策略”
  - 【目标】页面、任务中心、通知、错误提示统一展示“通用策略”。底层历史表/技术 ID 可暂保留兼容。
  - 【验收结论】已完成当前源码范围内的用户可见旧文案清理；技术 ID、表名、函数名中的 `profit_arena` 暂保留兼容，不作为用户展示名。
  - 【证据输出】命令 `rg -n "收益擂台|擂主|擂台签名|擂台评估|打擂" quant_stock_desktop/frontend/src quant_stock_desktop/app.go quant_stock_core/scripts/profit_arena_worker.py quant_stock_core/scripts/factor_snapshot_worker.py | head -120` 输出为空。

- [x] 【命名】当前 h20 通用特征集命名为 `stock_h20_general_final_v1`
  - 【目标】不带 `profit_arena_`，因为这是股票 h20 通用模型特征集，不是训练方式本身。
  - 【验收结论】命名已完成且 Python worker 可解析；该项只验收命名，最终子集规模由 `【特征集】收敛 stock_h20_general_final_v1 为 h20 通用最终子集` 单独验收。
  - 【证据输出】命令 `feature_columns_for_set('stock_h20_general_final_v1')` 可解析；`python3 -m py_compile quant_stock_core/scripts/profit_arena_worker.py quant_stock_core/scripts/factor_snapshot_worker.py` 通过。

## 2. 因子体系分层

- [ ] 【架构】完成原子数据、宽因子基座、策略特征集、标签、模型产物分层
  - 【目标】物理宽基座只保存一份，策略特征集只是列选择配置，不复制大 parquet。
  - 【验收结论】待填写。
  - 【证据输出】需要代码路径、快照 manifest、feature_set 定义文件。

- [ ] 【框架】抽象通用策略训练框架
  - 【目标】把“因子基座 -> 策略特征集 -> 标签/目标函数 -> walk-forward 训练 -> 参数打擂 -> 产物准入 -> 最新推理”抽成可复用框架；`stock_h20_general_final_v1`、未来热门/做T模型只作为不同策略配置接入，不复制流程。
  - 【验收结论】待填写。
  - 【证据输出】需要框架入口、策略配置结构、通用训练/推理代码路径、至少 h20 通用策略和预留热门/做T配置的调用证据。

- [x] 【因子】补齐 `stock_factor_base_v1` 宽因子
  - 【目标】纳入当前日线可回溯因子，包括趋势、动量、波动、成交额、换手、涨停热度、行业热度、小票生态、做T预备因子。
  - 【验收结论】代码层宽因子集合已补齐并可解析；当前 `stock_factor_base_v1` 包含 137 个日线可回溯因子。注意：这里只证明因子定义完成，生产基座 parquet 回溯由 `【回溯】回溯生成 stock_factor_base_v1` 单独验收。
  - 【证据输出】命令 `feature_columns_for_set('stock_factor_base_v1')` 输出 `137`；代表尾部字段为 `turnover_pct_rank, hot_money_score20, t_intraday_space, t_reversal_score, t_pressure_score`；`python3 -m py_compile quant_stock_core/scripts/profit_arena_worker.py quant_stock_core/scripts/factor_snapshot_worker.py` 通过。

- [x] 【特征集】收敛 `stock_h20_general_final_v1` 为 h20 通用最终子集
  - 【目标】不能等于宽基座全量；排除明显做T专用、过短周期或执行层专用因子。
  - 【验收结论】已收敛为宽基座子集：`stock_factor_base_v1=137`，`stock_h20_general_final_v1=129`，`h20_is_subset=True`，`h20_extra_count=0`。
  - 【证据输出】命令输出差集：`base_minus_h20_count 8`，排除字段为 `consecutive_down_days, consecutive_up_days, gap_fill_strength, lower_shadow_pct, t_intraday_space, t_pressure_score, t_reversal_score, turnover_volatility20`。

- [x] 【特征集】保留 `hot_t_daily_v1` 作为热门做T日线特征集
  - 【目标】作为未来做T模型的候选特征集，不阻塞当前 h20 通用策略。
  - 【验收结论】已保留并可解析，`hot_t_daily_v1=76`，且 `hot_is_subset=True`，不会复制物理大基座。
  - 【证据输出】命令 `feature_columns_for_set('hot_t_daily_v1')` 输出 `76`；代表尾部字段为 `turnover_pct_rank, hot_money_score20, t_intraday_space, t_reversal_score, t_pressure_score`。

- [x] 【解耦】物理基座名和模型特征集名解耦
  - 【目标】加载快照使用 `factor_store_id=stock_factor_base_v1` 和 `factor_store_feature_set=stock_factor_base_v1`；训练模型使用 `feature_set=stock_h20_general_final_v1`。
  - 【验收结论】已完成代码路径解耦：快照 spec 使用物理基座特征集，模型训练列使用模型 feature_set；桌面训练/推理参数显式传入 `--factor-store-feature-set stock_factor_base_v1`。
  - 【证据输出】源码搜索输出：`profit_arena_worker.py:2969-2980 factor_snapshot_spec` 使用 `factor_store_feature_set` 写入 `spec.feature_set`；`profit_arena_worker.py:3280` 使用 `feature_columns_for_set(args.feature_set)` 得到模型列；`app.go:7251-7254` 和 `app.go:7318-7321` 同时传入 `--feature-set stock_h20_general_final_v1`、`--factor-store-id stock_factor_base_v1`、`--factor-store-feature-set stock_factor_base_v1`。构造 args 验证输出：`spec.factor_store_id stock_factor_base_v1`，`spec.feature_set stock_factor_base_v1`，`args.feature_set stock_h20_general_final_v1`，`base_feature_count 137`，`model_feature_count 129`，`model_subset_of_base True`，`base_minus_model_count 8`，`model_minus_base_count 0`。基础测试：Python py_compile 通过，`go test ./...` 通过，`npm run build` 通过。

## 3. 因子准入与可观测性

- [x] 【testcase】因子快照生成后必须跑固化 testcase
  - 【目标】使用独立算法抽样复算因子，与基座计算结果对比。
  - 【验收结论】固化 testcase 流程已接入并用 smoke 快照验证通过：`stock_factor_base_smoke_e2e` 在 `20260601 -> 20260618` 生成快照后执行 30 个样本、420 个因子复算检查，`failed_count=0`，`status=pass`。注意：该项验收的是“生成后必须跑 testcase 的机制和 smoke 产物”，全量生产基座是否通过由 `【准入】新基座通过 testcase 和质量门禁` 单独验收。
  - 【证据输出】`data_store/factor_store/stock_factor_base_smoke_e2e/latest.json` 输出：`row_count 40682`，`feature_count 137`，`factor_testcase.status pass`，`sample_count 30`，`check_count 420`，`failed_count 0`，`max_abs_diff 5.773159728050814e-15`，`tolerance 1e-08`；报告文件存在：`factor_testcase_report.parquet size=11909`，`factor_testcase_report.json size=86492`。代码证据：`quant_stock_core/scripts/factor_snapshot_worker.py:240-294` 独立复算并生成 pass/fail，`quant_stock_core/scripts/factor_snapshot_worker.py:364-385` 生成快照时执行 testcase 且失败直接抛错，`quant_stock_core/scripts/factor_snapshot_worker.py:463-464` 写出 testcase 报告，`quant_stock_core/scripts/factor_snapshot_worker.py:476-484` 写入 metadata。

- [x] 【门禁】因子质量门禁参与生产准入
  - 【目标】`quality_gate=fail` 不允许训练/推理；`pass/warn` 才允许进入后续流程。
  - 【验收结论】质量门禁和 testcase 已参与桌面生产准入：后端只接受 `quality_gate.status in pass/warn` 且 `factor_testcase.status=pass`；前端生产就绪卡片同时展示“因子门禁”和“testcase”。smoke 快照质量门禁为 `warn`，无 failed checks，因此按当前准入规则可进入后续流程。注意：全量生产基座自己的准入仍由 `【准入】新基座通过 testcase 和质量门禁` 单独验收。
  - 【证据输出】smoke metadata 输出：`quality_gate.status warn`，`failed_checks []`，`warn_checks ["summary","factor_keep_ratio","median_coverage"]`；质量报告存在：`quality_gate_report.parquet size=3803`，`quality_gate_report.json size=931`。后端准入代码：`quant_stock_desktop/app.go:3468-3475` 计算 `production_snapshot_ready` 时同时检查 quality/testcase；`quant_stock_desktop/app.go:3517-3525` 训练/推理预检中 quality 非 pass/warn 或 testcase 非 pass 直接报错。前端展示代码：`quant_stock_desktop/frontend/src/pages/ProfitArenaPage.tsx:152-159` 解析 quality/testcase/spec，`quant_stock_desktop/frontend/src/pages/ProfitArenaPage.tsx:853-856` 展示“因子门禁”“testcase”“策略签名”。验证命令 `python3 -m py_compile quant_stock_core/scripts/profit_arena_worker.py quant_stock_core/scripts/factor_snapshot_worker.py && cd quant_stock_desktop && go test ./... && cd frontend && npm run build` 通过；前端 build 仅有 Vite chunk size warning。

- [ ] 【可观测】所有离线任务实时上报进度
  - 【目标】数据更新、因子快照、训练、推理、调仓计划均可在 UI/任务中心看到阶段、进度、失败原因。
  - 【验收结论】部分完成，不能打勾。因子快照长任务已补充预处理细粒度进度：winsorize/fill_missing/rank/standardize 按因子上报，neutralize 按交易日批次上报，并接入 `run_status.progress`；但“所有离线任务”还未逐一验收，所以保持未完成。
  - 【证据输出】第一次全量回溯中断栈显示黑盒瓶颈在 `quant_stock_core/common/factor_store/preprocess.py:187 out.loc[idx, column] = y - x.dot(beta)`；第二次中断栈显示 `winsorize_by_date` 的 `groupby.transform(lambda quantile)` 长时间无进度。修复代码：`quant_stock_core/common/factor_store/preprocess.py` 增加 `progress_callback`、`preprocess_winsorize_progress`、`preprocess_fill_missing_progress`、`preprocess_neutralize_progress`、`preprocess_standardize_progress`；`quant_stock_core/scripts/factor_snapshot_worker.py` 增加 `preprocess_progress` 并写入 `run_status.progress`。实跑输出：`preprocess_start rows=7497077 factor_count=137`，`preprocess_winsorize_progress factor_index=137 factor_count=137`，`preprocess_fill_missing_progress factor_index=137 factor_count=137`，`preprocess_neutralize_progress date_index=3900 total_dates=3995`，`preprocess_done rows=7497077 factor_count=137`。长 metadata 修复证据：`task_run_status.metadata_json` 由 `TEXT` 改为 `LONGTEXT`；`to_backend_ddl` 修复 `LONGTEXT -> LONGVARCHAR(255)` 的错误映射；schema 探针输出可写入 `metadata_len=20096`。

- [ ] 【数据更新联动】数据更新成功后自动触发因子快照
  - 【目标】桌面“数据更新”按钮完成原子数据更新后，自动触发最新截面的 `stock_factor_base_v1` 因子快照更新，并继承 testcase、quality gate、进度上报和失败提示；不能只停留在原子数据层。
  - 【验收结论】待填写。
  - 【证据输出】需要按钮触发代码路径、任务链状态记录、成功链路截图或状态表、失败时不会进入训练/推理的准入证据。

## 4. 历史数据与基座回溯

- [x] 【原子数据】确认历史原子数据覆盖 `20100101 -> 最新交易日`
  - 【目标】日线、股票基础信息、行情数据完整覆盖训练区间。
  - 【验收结论】原子数据主覆盖成立：`20100101` 非交易日，实际首个交易日为 `20100104`；日线、复权因子、daily_basic 均覆盖 `20100104 -> 20260618`，共 3995 个交易日。检查发现原始日线中有 3 个代码共 7637 行缺 `stock_basic`，已修正读取口径，后续因子/训练基座必须要求 `stock_basic` 存在，修正后过滤口径下 `missing_adj=0`、`missing_daily_basic=0`、`missing_stock_basic=0`。
  - 【证据输出】DuckDB 查询输出：`daily min_date=20100104 max_date=20260618 row_count=14040616 trade_days=3995 stocks=5790`；`adj_factor min_date=20100104 max_date=20260618 row_count=14696942 trade_days=3995 stocks=5794`；`daily_basic min_date=20100104 max_date=20260618 row_count=13949510 trade_days=3995 stocks=5790`；`stock_basic row_count=5855 listed=5529`。缺口追踪输出：缺 `stock_basic` 的代码为 `300114.SZ`、`000043.SZ`、`000022.SZ`，共 7637 行。代码修正：`quant_stock_core/scripts/profit_arena_worker.py:646` 增加 `AND s.ts_code IS NOT NULL`。修正后同口径查询输出：`min_date=20100104`，`max_date=20260618`，`row_count=12359905`，`trade_days=3995`，`stocks=4979`，`missing_adj=0`，`missing_daily_basic=0`，`missing_stock_basic=0`。验证命令 `python3 -m py_compile quant_stock_core/scripts/profit_arena_worker.py quant_stock_core/scripts/factor_snapshot_worker.py` 通过。

- [x] 【补数据】如历史原子数据缺失，补齐历史数据
  - 【目标】补齐后才能回溯宽因子基座。
  - 【验收结论】当前不需要补历史原子数据：训练/因子读取口径修正后，过滤池内日线、复权因子、daily_basic、stock_basic 都无缺口，最新交易日已到 `20260618`。本项完成方式不是执行补数，而是用当前数据覆盖查询证明“无需补数”；若后续数据更新目标日变更，需要重新验收。
  - 【证据输出】同上原子数据覆盖查询；最新 8 个日线交易日输出：`20260618 row_count=5507`，`20260617 row_count=5509`，`20260616 row_count=5513`，`20260615 row_count=5508`，`20260612 row_count=5512`，`20260611 row_count=5511`，`20260610 row_count=5512`，`20260609 row_count=5515`。

- [x] 【回溯】回溯生成 `stock_factor_base_v1`
  - 【目标】使用 `20100101 -> 最新交易日` 生成一份生产宽因子 parquet，并写入 `latest.json`。
  - 【验收结论】已完成生产全量回溯并写入 `latest.json`。生产宽基座为 `stock_factor_base_v1`，版本 `profit_arena_panel_v7`，物理 feature_set 为 `stock_factor_base_v1`，覆盖 `20100104 -> 20260618`，产出 `7,497,077` 行、物理 `305` 列、`137` 个因子。注意：DuckDB 读取 hive 分区路径时会额外显示 `end/feature_set/horizons/start/version` 5 个分区列，因此 `DESCRIBE read_parquet` 为 310 列；manifest/latest 的物理 `column_count=305` 是快照实际写入列口径。
  - 【证据输出】启动命令：`DATA_ROOT=data_store python3 quant_stock_core/scripts/factor_snapshot_worker.py --data-path data_store --factor-store-id stock_factor_base_v1 --start 20100101 --end 20260618 --horizons 20 --feature-set stock_factor_base_v1 --preprocess institutional --enforce-quality-gate --execution-stop-loss 0 --execution-take-profit 0.20,0.25,0.30 --factor-testcase-samples 200`。运行输出：`factor_snapshot_raw_loaded rows=9043609 columns=24`；预处理进度输出：`preprocess_start rows=7497077 factor_count=137`、`preprocess_neutralize_progress date_index=3900 total_dates=3995`、`preprocess_done rows=7497077 factor_count=137`；完成输出：`factor_snapshot_written path=data_store/factor_store/stock_factor_base_v1/version=profit_arena_panel_v7/feature_set=stock_factor_base_v1/start=20100101/end=20260618/horizons=20/821513922cb70389/panel.parquet rows=7497077 columns=305 manifest_path=.../manifest.json`。`latest.json` 查询输出：`latest_exists True`，`row_count 7497077`，`column_count 305`，`feature_count 137`，`path_exists True size 8095332806`，`manifest_path_exists True size 5319`。

- [x] 【基座数据交付】输出最新 `stock_factor_base_v1` 数据摘要
  - 【目标】基座完成后，必须明确给出最新基座数据：路径、版本、feature_set、起止日期、交易日数量、股票数量、行数、列数、因子数量、文件大小、生成时间、testcase 状态、quality gate 状态。
  - 【验收结论】最新生产基座摘要已输出：`factor_store_id=stock_factor_base_v1`，`version=profit_arena_panel_v7`，`feature_set=stock_factor_base_v1`，`start=20100101`，`end=20260618`，实际覆盖 `trade_date_min=20100104`、`trade_date_max=20260618`，`trade_days=3995`，`stocks=3019`，`row_count=7497077`，`column_count=305`，`feature_count=137`，文件大小 `8095332806` bytes，生成时间 `2026-06-19T16:45:05`。
  - 【证据输出】`latest.json` 摘要输出：`path=data_store/factor_store/stock_factor_base_v1/version=profit_arena_panel_v7/feature_set=stock_factor_base_v1/start=20100101/end=20260618/horizons=20/821513922cb70389/panel.parquet`；`manifest_path=.../manifest.json`；`quality_gate.status=warn failed_checks=[] warn_checks=["summary","factor_keep_ratio","median_coverage"]`；`factor_testcase.status=pass sample_count=200 check_count=2800 failed_count=0 max_abs_diff=4.75175454539567e-13 tolerance=1e-08`。DuckDB 覆盖查询输出：`min_date=20100104`，`max_date=20260618`，`row_count=7497077`，`trade_days=3995`，`stocks=3019`，`label_20d_rows=3563316`，`latest_rows=2874`，`latest_label_rows=0`。最近截面行数：`20260618 rows=2874`，`20260617 rows=2884`，`20260616 rows=2897`，`20260615 rows=2911`。

- [x] 【准入】新基座通过 testcase 和质量门禁
  - 【目标】基座不通过不得进入训练。
  - 【验收结论】新生产基座准入通过：`factor_testcase.status=pass`；`quality_gate.status=warn` 且 `failed_checks=[]`，符合当前后端准入规则 `pass/warn` 可继续训练/推理。warning 需要在最终 E2E 报告中解释，但不阻塞当前准入。
  - 【证据输出】`latest.json` 输出：`factor_testcase {"status":"pass","sample_count":200,"check_count":2800,"failed_count":0,"max_abs_diff":4.75175454539567e-13,"tolerance":1e-08}`；`quality_gate {"status":"warn","failed_checks":[],"warn_checks":["summary","factor_keep_ratio","median_coverage"]}`。报告文件存在：`factor_testcase_report.parquet size=54215`，`factor_testcase_report.json size=576668`，`quality_gate_report.parquet size=3814`，`quality_gate_report.json size=943`。

## 5. 模型训练与冠军校验

- [x] 【旧擂主复现审计】搞清楚旧擂主怎么训练、当前为什么不能训练级复现
  - 【目标】暂停其他推进项，先证明旧擂主到底是训练产物还是二次评估产物，并定位当前不能从原始数据重训复现的原因。
  - 【验收结论】已查清：当前生产旧擂主 `profit_arena_evalonly_h20_near4292_bucket_sharpe_grid_20260615` 不是旧 source 训练 run 的直接 best，而是基于旧预测文件 `profit_arena_v6all_h20_rawscore_cache_20260615/predictions_small_20d.parquet` 做 eval-only 网格重评估筛出来的版本。当前代码在旧预测 parquet 上可以复出旧擂主指标，说明“评估层”可复现；但从当前 raw 数据、当前代码、旧 v6all 参数重训 source 模型不能复现旧 source 指标，说明“训练层”不可复现。主要断点是：旧训练输入没有不可变快照，当前 raw 重建 small 样本从旧 `956672` 变为 `957331`；当前默认参数已漂移，`min-test-year` 默认会从 2020 开始而旧 run 是 2014；当前新增 `institutional` 预处理不是旧 source 链路，未显式关闭会卡在预处理；即使显式恢复旧窗口、关闭 factor-store 和预处理，重训预测分布和收益指标仍显著塌陷。旧擂主因此只能视为“旧预测文件 eval-only 层可复现”的历史参考，不能视为已从原子数据完整可复现的生产级冠军。
  - 【证据输出】旧 eval-only 隔离复算命令使用临时 `data_path=/tmp/quant_stock_old_champion_repro`、临时 `arena_name=repro_old_champion_audit`，输出与旧擂主一致：`best_capital_annual_return=0.3329873489730901`，`best_capital_max_drawdown=-0.10339757697826435`，`best_capital_sharpe=1.2334687774916866`，`best_rank_ic=0.13139009179621466`，`best_rank_ic_days=141`，`best_challenger_score=93.5`。代码证据：`quant_stock_core/scripts/profit_arena_worker.py:5481-5524` 的 `eval_only_model()` 只读取 `eval_only_predictions` 并执行 `evaluate_prediction_grid()`，不重新训练模型。旧 source 训练 progress 证据：`profit_arena_v6all_h20_rawscore_cache_20260615` 为 `feature_set=v6all`、`model_kind=hybrid`、`feature_count=104`、`test_years=2014..2026`、`walk_forward_start rows=956672`、old best 为 `top_n=1`、`execution_take_profit=0.35`、`capital_annual_return=0.40147588267544276`、`capital_max_drawdown=-0.14795862403036564`、`capital_sharpe=1.11079527523371`、`rank_ic=0.127323112219625`、`rank_ic_days=93`。当前同口径复训 `repro_old_source_train_v6all_exact_20260619` 显式设置 `--min-test-year 2014 --factor-store-mode off --factor-preprocess none --no-panel-cache` 后，`walk_forward_start rows=957331`，严格 RankIC 门禁下直接 `evaluation_skipped_by_rank_ic_gate` 并报错 `通用策略没有产生可评估模型`。去掉 RankIC 门槛的量化复训 `repro_old_source_train_v6all_nogate_20260619` 输出 best：`top_n=2`、`trade_count=206`、`trade_years=9`、`capital_annual_return=0.06904507880735156`、`capital_max_drawdown=-0.241882234724901`、`capital_sharpe=0.5719545459634279`、`rank_ic=0.1022684280023568`、`rank_ic_days=24`、`best_challenger_score=31.0`。预测文件分布对比：旧 source `row_count=840622 stocks=2197 latest_rows=623 avg_pred=-0.000781 std_pred=0.06589 avg_score=0.586798 avg_crash=0.353498`；当前重训 `row_count=841243 stocks=2201 latest_rows=620 avg_pred=-0.003916 std_pred=0.054147 avg_score=0.580688 avg_crash=0.373732`。

- [ ] 【目标函数】固化 h20 标签与目标函数定义
  - 【目标】明确 h20 标签到底按哪种交易收益计算：买入价口径、未来 20 个交易日退出、25% 止盈、止损是否启用、交易成本、停牌/涨跌停不可成交处理、样本最后 20 日无标签如何处理。最新截面只能做推理，不得要求存在未来 20 日 label。
  - 【验收结论】部分完成，不能打勾。当前 h20 标签定义已经明确：因子截面日 T 不在当天买入，而是用 T+1 开盘作为买入价；默认持有到 raw 序列中 `horizon + 1` 后的收盘价，生成 `future_return_20d`；`net_return_20d` 在此基础上扣 `buy_slippage=0.0015`、`sell_slippage=0.0015`、`commission=0.00025`、`stamp_tax=0.0005`；如果 `next_open<=0` 或 T+1 涨停附近不可买，则 `net_return_20d` 置空不进训练。训练目标默认是 `net_return_20d`，而 `execution_take_profit=0.20/0.25/0.30` 是打擂评估阶段的执行参数，不是默认训练 label 本身。抽样中一度发现 `000020.SZ/20240102` 看似 `lead(20)`，后续定位为标签在过滤前 raw 序列计算，而最终生产面板过滤掉了 `20240111` 这类低成交额日期，导致用最终面板行号复算会错位；按 raw 序列复算 `lead21=20240131`，与落库一致。已把标签复算接入 `factor_snapshot_worker.py` 的 testcase 流程，未来基座生成会同时校验 label；但当前生产全量基座尚未重新生成出带 `label_check_count` 的正式报告，所以保持未完成。
  - 【证据输出】源码证据：`quant_stock_core/scripts/profit_arena_worker.py:876-900` 使用 `next_open = group["open"].shift(-1)`、`exit_shift = horizon + 1`、`exit_close = group["close"].shift(-exit_shift)`、`future_return_{horizon}d = gross`、`net_return_{horizon}d = np.where(can_buy_next_open, net, np.nan)`；`profit_arena_worker.py:1287-1316` 回测执行规则用 `future_max_return`/`future_drawdown` 覆盖止盈止损退出；`profit_arena_worker.py:5694-5697` 默认交易成本为 `0.0015/0.0015/0.00025/0.0005`。生产基座最新截面查询：`max_date=20260618`，`latest_rows=2874`，`latest_label_rows=0`，`max_label_date=20260520`。抽样复算：普通样本如 `000001.SZ/20240102`、`000002.SZ/20240102`、`000021.SZ/20240102` 与默认成本公式 `abs_diff<=2.22e-16`；`000020.SZ/20240102` raw 序列输出 `20240111 raw_close=12.49 amount=19253.348`，该日因 `amount<20000` 被最终面板过滤，但标签计算发生在过滤前 raw 序列上，因此 raw 序列 `lead20=20240130`、`lead21=20240131`，与落库 `exit_date_20d=20240131`、`future_return_20d=0.172068`、`net_return_20d=0.167388` 一致。自动化 testcase 代码：`factor_snapshot_worker.py` 新增 `_recompute_label_values`、`_append_label_testcase_rows`，并在 `build_factor_testcase_report` 中输出 `label_check_count`、`label_failed_count`、`latest_unmatured_label_checks`。小窗口验证命令通过：`python3 -m py_compile quant_stock_core/scripts/factor_snapshot_worker.py`；真实小窗口 testcase 输出 `status=pass`、`check_count=100`、`failed_count=0`、`label_check_count=30`、`label_failed_count=0`、`latest_unmatured_label_checks=5`、`max_abs_diff=4.440892098500626e-16`。

- [ ] 【标签一致性】修复或重建生产基座 h20 标签口径
  - 【目标】保证 `stock_factor_base_v1` 生产基座中的 `future_return_20d/net_return_20d/exit_date_20d` 与当前源码定义、训练目标函数、回测执行规则完全一致；如源码口径调整，必须同步重建基座、重训模型、重跑冠军校验。
  - 【验收结论】已解释上一轮抽样中的表面错位：标签按过滤前 raw 序列计算，最终面板过滤会让直接按生产面板行号复算出现假错位。已把标签一致性接入自动化 testcase，小窗口真实数据验证通过。但本项仍保持未完成，因为当前生产全量基座还未重新生成带标签 testcase 的正式 artifact，也还没有覆盖更多生产随机样本。
  - 【证据输出】小窗口真实数据 testcase 输出 `label_check_count=30`、`label_failed_count=0`、`latest_unmatured_label_checks=5`；仍需要生产全量基座重新生成后的 `factor_testcase_report`、`latest.json`、testcase、quality gate、训练 summary 和冠军对照。

- [ ] 【防泄漏】验证训练不使用未来信息
  - 【目标】因子截面只能使用当日及历史原子数据；h20 label 只在训练样本成熟后回填到历史训练集，不写入或依赖最新推理截面。
  - 【验收结论】部分证据成立，但不能打勾。已确认训练入口会丢弃未成熟 label 样本，且 walk-forward 每个测试年只用历史年份训练；最新生产截面 `20260618` 没有 `net_return_20d` label，能用于 latest inference 但不会进入训练样本。仍需补齐因子本身的逐列防未来审计，尤其要结合上面的标签口径不一致风险重新跑完整抽样校验。
  - 【证据输出】源码证据：`profit_arena_worker.py:2289` 使用 `source_data.dropna(subset=[train_target, eval_target])`，未成熟 label 不进入训练；`profit_arena_worker.py:2332-2336` walk-forward 中 `train_mask = sample["year"] < year`、`test_mask = sample["year"] == year`，测试年不进入训练。生产基座查询输出：`min_date=20100104`，`max_date=20260618`，`row_count=7497077`，`label_rows=3563316`，`latest_rows=2874`，`latest_label_rows=0`，`max_label_date=20260520`；最近 21 个交易日中 `20260618 -> 20260521` 的 `label_rows=0`，`20260520` 开始出现成熟 label。

- [x] 【训练】使用 `stock_h20_general_final_v1` 重新训练通用策略主模型
  - 【目标】训练方式仍然是版本竞争/打擂式评估，但产品语义是通用策略。
  - 【验收结论】已使用新生产基座和 `stock_h20_general_final_v1` 完成一版 h20/small 通用策略训练，并产出 summary、模型文件、预测文件和特征一致性报告。该 run 用于“当前冠军参数复验”：`top_n=3`、`min_pred_return=0.04`、`max_crash_prob=0.12`、`position_weighting=score`、`execution_take_profit=0.20/0.25/0.30`。注意：这不是全量新冠军搜索，150 组合大网格因 ETA 过长已中断，后续冠军搜索仍需单独跑。
  - 【证据输出】训练 run：`stock_h20_general_final_v1_basev1_champion_params_20260619`。训练输出：`factor_snapshot_hit factor_store_id=stock_factor_base_v1 rows=7497077 columns=305 freshness.status=pass`；`feature_consistency_train_done status=warn failed_checks=[] warn_checks=["summary","schema_hash_observed"]`；`train_model_start feature_set=stock_h20_general_final_v1 feature_count=129 scopes=["small"] horizons=[20]`；`walk_forward_start rows=959761 test_years=2014..2026 model_kind=hybrid`；`evaluation_start pred_rows=843053 base_combinations=3 evaluation_records=3`；`summary_write_done path=data_store/profit_arena/stock_h20_general_final_v1_basev1_champion_params_20260619/summary.json`。产物存在：`summary.json size=276696`，`model_small_20d.joblib size=560587`，`predictions_small_20d.parquet size=908945741`，`feature_consistency_train.json size=1305`，`progress.jsonl size=28291`。

- [ ] 【冠军校验】校验新冠军模型和当前版本指标是否一致或可解释
  - 【目标】基座搞完后，必须给出最新基座下冠军模型对应收益、回撤、Sharpe/Calmar、RankIC、TopN、horizon、止盈等指标，并与当前版本对照。
  - 【验收结论】已完成“当前冠军参数在新基座/新特征集下的复验”，结果与旧冠军显著不一致，且挑战失败；但还未完成全量新冠军搜索，所以本项保持未完成。当前复验显示，新基座下同类参数最佳为 `execution_take_profit=0.20`，`capital_annual_return=0.11314288999937183`，`capital_max_drawdown=-0.6427845710652895`，`capital_sharpe=0.5092056546873227`，`rank_ic=0.09168227806886214`；旧冠军为 `execution_take_profit=0.25`，`capital_annual_return=0.3329873489730901`，`capital_max_drawdown=-0.10339757697826435`，`capital_sharpe=1.2334687774916866`，`rank_ic=0.13139009179621466`。
  - 【证据输出】新 run `summary.json` 输出：`new_best scope=small horizon=20 top_n=3 min_pred_return=0.04 max_crash_prob=0.12 execution_take_profit=0.2 execution_stop_loss=0 position_weighting=score trade_count=2882 trade_years=13 capital_annual_return=0.11314288999937183 capital_max_drawdown=-0.6427845710652895 capital_sharpe=0.5092056546873227 rank_ic=0.09168227806886214 rank_ic_days=360 capacity_status=pass portfolio_risk_status=fail`。旧冠军 JSON 输出：`old_best scope=small horizon=20 top_n=3 min_pred_return=0.04 max_crash_prob=0.12 execution_take_profit=0.25 execution_stop_loss=0 position_weighting=score trade_count=495 trade_years=10 capital_annual_return=0.3329873489730901 capital_max_drawdown=-0.10339757697826435 capital_sharpe=1.2334687774916866 rank_ic=0.13139009179621466 rank_ic_days=141`。训练日志输出：`arena_challenge_failed challenger_score=37.0 incumbent_score=93.5 validation_confirmed=false`。

- [ ] 【冠军一致性判定】给出新旧冠军差异结论
  - 【目标】如果新基座下冠军指标与旧版本不一致，必须判断差异来源：因子集变化、基座覆盖范围变化、标签/执行规则变化、训练随机性、数据补齐差异或代码 bug。
  - 【验收结论】初步判定：差异真实存在，不能视为一致。已知差异来源至少包括：物理基座从旧 `profit_arena_v1/v6all/20240102->20260618/104因子/row_count=1642768` 变为新 `stock_factor_base_v1/stock_h20_general_final_v1/20100104->20260618/129模型因子/row_count=7497077`；训练样本从旧源 run 的配置不完整可追溯变为新基座全历史；新复验的 OOS 预测最大到 `20260520`，最新 `20260618` 需要 latest inference 单独生成。仍需继续做配置 diff 和必要的旧参数复跑，故本项保持未完成。
  - 【证据输出】输入基座差异：旧 `profit_arena_v1 feature_set=v6all row_count=1642768 feature_count=104 trade_date_min=20240102 trade_date_max=20260618 quality_gate=None factor_testcase=None`；新 `stock_factor_base_v1 feature_set=stock_factor_base_v1 row_count=7497077 feature_count=137 model_feature_count=129 trade_date_min=20100104 trade_date_max=20260618 quality_gate.status=warn factor_testcase.status=pass`。预测覆盖证据：`predictions_small_20d.parquet min_date=20140102 max_date=20260520 row_count=843902 trade_days=2999 stocks=2203 latest_rows=0`。

- [ ] 【生产准入】只有通过打擂的新模型才能替换当前生产冠军
  - 【目标】训练/复验模型即使能推理，也不能自动替换当前生产冠军；只有 testcase、quality gate、冠军指标、执行契约一致性全部通过，且打擂胜出或人工确认后，才能更新生产指针和桌面默认推理来源。
  - 【验收结论】待填写。
  - 【证据输出】需要当前冠军指针、挑战失败不替换生产源的代码路径、DB/JSON 指针查询、挑战成功或人工确认的更新路径。

- [x] 【推理】使用新冠军模型生成最新买入清单
  - 【目标】最新截面推理必须来自新基座和新冠军模型。
  - 【验收结论】已使用新生产基座和新训练模型生成 `20260618` 最新截面买入清单。注意：当前 source run 是“新基座下当前冠军参数复验模型”，不是全量搜索产生的新冠军；因此本项完成的是“最新推理链路可用且产物正确”，不代表新冠军已替换旧冠军。
  - 【证据输出】latest inference run：`stock_h20_general_final_v1_basev1_latest_20260619_fixname`，source run：`stock_h20_general_final_v1_basev1_champion_params_20260619`，model path：`data_store/profit_arena/stock_h20_general_final_v1_basev1_champion_params_20260619/model_small_20d.joblib`。运行输出：`factor_snapshot_hit factor_store_id=stock_factor_base_v1 rows=7497077 columns=305 freshness.status=pass`；`feature_consistency_latest_inference_done status=warn failed_checks=[]`；`capacity_latest_inference_done status=pass`；`portfolio_risk_latest_inference_done status=pass`；`latest_buy_plan_status_done status=ready tradable_count=3 target_count=3`；`latest_inference_db_write_done rows=3 latest_date=20260618`。DB 查询输出 3 行：`002725.SZ 跃岭股份 model_score=0.7565519769145118 pred_return=0.010742145600704625 price=35.99645 is_latest=1`；`603669.SH 灵康药业 model_score=0.5575797401394225 pred_return=-0.006911317400826283 price=15.621849999999998 is_latest=1`；`605588.SH 冠石科技 model_score=0.4257772955336485 pred_return=0.014094103683275527 price=63.5544 is_latest=1`。summary 输出：`latest_date=20260618 latest_count=3 buy_plan.status=ready`。

## 6. 执行路径与持仓生命周期

- [ ] 【回测契约】把冠军回测交易规则固化为实盘执行契约
  - 【目标】把当前冠军的真实赚钱规则写成可执行契约：每日 TopN 是新增开仓候选；单笔持仓按 horizon 生命周期管理；达到止盈、到期或启用止损时才退出；不得因为跌出次日 TopN 自动卖出。
  - 【验收结论】待填写。
  - 【证据输出】需要冠军 JSON、回测代码路径、执行器代码路径、场景测试证明三者一致。

- [ ] 【一致性】修正训练路径和实盘执行路径不一致问题
  - 【目标】h20 模型训练是 20 日生命周期；实盘不得因为跌出今日 TopN 就清仓。
  - 【验收结论】部分完成，不能打勾。已修正最危险的不一致：调仓计划生成不再把“非今日 TopN 的旧持仓”强制塞入 `TargetWeight=0`，因此不会仅因跌出今日 TopN 自动生成 `清仓`。但完整 h20 生命周期卖出规则还没实现，仍需补止盈、到期、止损的场景测试后才能验收。
  - 【证据输出】代码修改：`buildAccountRebalanceRecommendation` 调用从 `app.buildAccountRebalanceRows(targets, summary, date, true)` 改为 `app.buildAccountRebalanceRows(targets, summary, date, false)`；`buildAccountRebalanceRows` 在 `clearUnmatched=false` 时会为旧持仓保留 `TargetWeight=item.Weight`，不会进入 `targetShares<=0 -> 清仓` 路径。验证：`cd quant_stock_desktop && go test ./...` 通过。

- [ ] 【持仓生命周期】买入时记录模型执行参数
  - 【目标】记录 entry_date、entry_price、source_run_id、feature_set、horizon、take_profit、stop_loss、planned_exit_date。
  - 【验收结论】待填写。
  - 【证据输出】需要数据库字段/持仓记录/确认交易后的查询结果。

- [ ] 【卖出规则】按模型生命周期生成卖出计划
  - 【目标】卖出条件为止盈、持满 horizon、止损启用时触发；不因不在今日 TopN 卖出。
  - 【验收结论】待填写。
  - 【证据输出】需要场景测试：旧持仓不在今日 TopN 但未触发退出时继续持有。

- [ ] 【买入规则】今日 TopN 只作为新增开仓候选
  - 【目标】已有同股持仓不重复加仓；空出仓位或预算允许时新增买入。
  - 【验收结论】部分完成，不能打勾。已在通用策略目标合并时跳过当前已持有股票，避免今日 TopN 对已有同股生成重复买入/加减仓目标；但还缺真实持仓样例和数据库调仓计划验证。
  - 【证据输出】代码修改：`mergeProfitArenaTargets` 根据 `summary.Positions` 建立 `held` 集合，`selected` 中如果 `row.TSCode` 已持仓则 `continue`，并在 metadata 写入 `existing_holding_skipped_count`。验证：`cd quant_stock_desktop && go test ./...` 通过。

- [ ] 【预算】执行每日买入预算 2W、账户本金 50W
  - 【目标】h20 滚动持仓最大投入约 40W，与账户规模匹配。
  - 【验收结论】待填写。
  - 【证据输出】需要调仓计划金额、持仓总投入、预算计算日志。

- [ ] 【持仓刷新】修复数据更新最后一步持仓刷新不成功
  - 【目标】数据更新链路最后的当前持仓/实时行情刷新必须稳定完成；失败时要进入任务中心和状态表，显示具体失败原因，不允许静默卡住。
  - 【验收结论】待填写。
  - 【证据输出】需要持仓刷新函数路径、失败日志/状态表、修复后成功状态、持仓页最新更新时间或行情字段查询。

## 7. 前端展示

- [ ] 【持仓页】展示生命周期字段
  - 【目标】持仓页展示来源模型、买入日、已持有天数、计划退出日、止盈价、止损价、卖出触发原因。
  - 【验收结论】待填写。
  - 【证据输出】需要前端截图或 DOM/构建结果。

- [ ] 【调仓页】展示卖出原因
  - 【目标】调仓计划里明确显示卖出原因：止盈、到期、止损、手动/异常。
  - 【验收结论】待填写。
  - 【证据输出】需要调仓计划样例。

- [ ] 【界面回归】统一桌面页面间距、菜单和卡片布局
  - 【目标】所有保留页面使用同一套内容间距、卡片间距、标签/主体卡布局和侧边菜单；删除不用的旧界面入口，避免出现 `desktop2` 或新旧界面并存造成混乱。
  - 【验收结论】待填写。
  - 【证据输出】需要页面清单、关键页面截图或自动化视觉检查、前端 build 结果。

## 8. 端到端验收

- [ ] 【E2E】完整跑通生产链路
  - 【目标】数据更新 -> 因子快照 -> testcase -> 质量门禁 -> 训练 -> 冠军校验 -> 最新推理 -> 买入清单 -> 生命周期调仓计划。
  - 【验收结论】待填写。
  - 【证据输出】需要每一步命令/任务 ID/日志/状态/产物路径。

- [ ] 【E2E】端到端测试不能有未解释失败
  - 【目标】所有测试通过；如有 warn，必须说明影响和是否接受。
  - 【验收结论】待填写。
  - 【证据输出】需要 Python 编译、Go test、前端 build、关键业务测试、真实数据校验输出。

- [ ] 【验收矩阵】逐项完成审计
  - 【目标】对本文档每一个 todo 给出当前状态：完成、未完成、阻塞、证据不足；不得用局部测试证明全局完成。
  - 【验收结论】待填写。
  - 【证据输出】需要最终审计表，逐项引用证据路径或命令输出。

- [ ] 【文档】最终验收报告归档
  - 【目标】把最终基座数据、冠军模型指标、执行路径校验、端到端证据汇总到本文档或单独验收报告。
  - 【验收结论】待填写。
  - 【证据输出】待填写。
