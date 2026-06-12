# Quant Stock — 架构总览

一个面向个人量化研究的桌面端选股 / 回测 / 持仓管理系统，采用 **Wails 桌面壳 (Go) + Python 量化核心 + MySQL/Parquet 数据层** 的混合架构。

> 本文档由代码仓库结构与现有 `quant_stock_core/README.md`、`quant_stock_desktop/MIGRATION_NOTES.md` 总结而成。

---

## 1. 顶层目录

```
lh/
├── data_store/            共享运行期数据（Parquet + 日志 + 回测产出）
├── quant_stock_core/      Python 量化核心（策略 / 回测 / 信号生成 / 时光机评估）
├── quant_stock_desktop/   Wails 桌面应用（Go 后端 + React/TS 前端）
└── __ext__/               外部 / 临时素材，不参与运行
```

三块顶层目录通过 `data_store/` 这个**唯一物理状态目录**进行解耦：Go 进程与 Python 进程都不直接 IPC，结构化状态写入 MySQL，行情原始数据和中间结果主要落在 Parquet / 日志目录。

---

## 2. 共享数据层 `data_store/` + MySQL

| 路径 | 作用 |
| --- | --- |
| MySQL | 主业务库，桌面与 Python 共用：配置、任务、推荐、评估、运行状态、持仓池等 |
| `raw/<dataset>/...parquet` | Tushare 原始落地数据，按 `single` 或 `year=YYYY.parquet` 分区 |
| `factor_cache/` | 因子计算的中间缓存 |
| `backtest_results/` | 回测 / 评估 / Paper Trade / 时光机产出 |
| `positions/` | 持仓相关 JSON（`pool.json` 等） |
| `logs/` | 桌面与 Python 的运行日志 |

关键表（迁移定义见 `quant_stock_desktop/internal/common/database/db.go`）：

- `app_settings` — KV 形式的桌面与 Python 共享配置（含 Tushare token、策略开关、初始资金等）
- `evaluation_tasks` — 桌面侧调度的评估 / 回测 / 优化任务记录
- `daily_recommendation` — 当日选股推荐（同一 `target_date` 唯一一份）
- `strategy_evaluation` — 多策略时光机评估明细（`run_id` + `strategy` 复合主键）
- `portfolio_optimization_runs` / `portfolio_optimization_candidates` — 组合优化运行与候选
- `time_machine_snapshots` / `time_machine_trades` / `time_machine_positions` — 时光机回放
- `market_data_files` — 已扫描数据文件元信息
- `dataset_update_status` — 各 Tushare 数据集的最近一次拉取状态
- `py_run_lock` — 全局互斥锁（同一时刻只允许一个 Python 工作进程）
- `py_run_status` — 通用进度表（task PK：`daily_signal` / `data_update` / `evaluation` 等），前端轮询读
- `task_run_status` — 任务模式运行状态，涨停/横盘/T0/因子等较长研究任务可实时观察进度
- `pool_summary` / `pool_holdings` / `pool_trades` — 实盘持仓池
- `market_limit_momentum_cache` / `market_limit_breakout_cache` — 涨停板推荐与横盘突发预警候选缓存
- `market_limit_signal_predictions` — 候选生成时写入的预测快照，用于后续历史回看
- `market_limit_signal_evaluations` — 涨停/横盘信号评估汇总，记录 T+1/T+3/T+5/T+10 收益、回撤、命中率等
- `market_limit_signal_tm_slices` — 历史切面时光机，按交易日聚合当时热点、涨停扩散、候选收益和回撤

> 当前桌面和 Python 均按 **MySQL-only** 路径运行，业务元数据、任务状态、推荐与评估结果统一写入 MySQL。

---

## 3. Python 量化核心 `quant_stock_core/`

仅依赖 `data_store/` 状态。无任何长驻进程，只通过 CLI 入口被桌面拉起。

### 3.1 模块布局

| 子包 | 内容 |
| --- | --- |
| `common/config/` | 配置读取与桌面 settings 桥接（`desktop_settings.py` 从 MySQL 读策略配置） |
| `common/infra/` | 基础设施：`db.py` 打开 MySQL 连接、`lock.py` 全局 PyLock、`status.py` 进度写库、`pool.py` 持仓池 |
| `common/utils/logger.py` | 统一日志 |
| `research/data/storage/duckdb_query.py` | 只读 DuckDB 查询层，统一 `data_store/raw/` 访问 |
| `research/data/validator.py` | 原始数据完整性校验 |
| `research/factors/` | 因子库：动量、价值、质量、规模、流动性、事件、行业中性化 (`base/evaluate/event/...`) |
| `research/universe/` | 选股域构建与过滤器 |
| `trading/strategy/` | 策略插件，**通过 `registry.py` 装饰器自动注册** |
| `trading/strategy/combiner.py` | 多策略组合与权重 |
| `trading/backtest/` | 回测引擎 (`engine.py`) + 成本模型 + 指标 |
| `trading/execution/` | 信号生成 (`signal.py`)、退出规则、Paper Trade、时光机评估 (`time_machine.py`)、评估 worker、通知 |
| `scripts/` | CLI 入口 |
| `tests/` | 冒烟测试 |

### 3.2 策略插件机制

策略通过 `trading/strategy/registry.py` 的 `@register("name", "中文标签")` 装饰器自动登记，新增策略只需新建一个 `.py` 文件并实现 `build_strategy()` 工厂函数。当前已注册：

`small_cap_quality`、`forecast_revision`、`dividend_low_vol`、`trend_quality`、`garp_quality`、`moneyflow_pullback`、`industry_rotation`、`reversal`、`insider_buy`、`lhb_follow`、`beijing_se` 等。

新策略默认进入候选状态（disabled），通过多窗口时光机评估后再升入生产。

### 3.3 CLI 入口

| 脚本 | 作用 | 触发 |
| --- | --- | --- |
| `scripts/daily_signal.py` | 通用策略推荐的历史入口：抢锁 → 命中缓存即返回 → 否则调用 `signal.generate(force, progress_cb)` → upsert | 兼容旧推荐缓存 |
| `scripts/run_backtest.py` | 单策略 / 组合回测 | 桌面任务中心 |
| `scripts/evaluate_strategies.py` | 多策略多窗口时光机评估 | 桌面任务中心 |
| `scripts/optimize_portfolio.py` | 基于评估结果做组合优化，产出候选 | 桌面任务中心 |
| `scripts/pool_confirm.py` | 持仓池交易确认 | 桌面 `ConfirmPositionTrades` |
| `scripts/limit_up_momentum_worker.py` | 涨停板推荐扫描，生成短线候选与预测快照 | 桌面 `涨停预警` |
| `scripts/limit_breakout_worker.py` | 横盘突发预警扫描，生成形态候选与预测快照 | 桌面 `横盘预警` |
| `scripts/evaluate_limit_signals.py` | 涨停/横盘信号历史评估与切面时光机 | 桌面 `评估验证` |
| `scripts/t0_daily_worker.py` | 做T助手日线研究与切面时光机 | 桌面 `做T助手` / 任务模式 |

执行约定：

- 进程入口处通过 `with PyLock("global", task=...)` 抢全局锁，写 `py_run_status` 或 `task_run_status` 的 begin/progress/done/error
- 顶部限制 BLAS 线程数（`QUANT_CPU_LIMIT`）避免桌面 UI 卡顿
- 异常 → `status.error()` → raise；`LockBusyError` → `sys.exit(2)`
- 通过桌面注入的 MySQL DSN / 数据目录环境变量定位运行状态与数据根目录

---

## 4. 桌面应用 `quant_stock_desktop/`

Wails v2 应用：**Go 后端编译为本机二进制** + **React/TS 前端嵌入打包**。

### 4.1 Go 后端布局

```
internal/
├── common/
│   ├── config/          settings 模型 + KV 持久化（写 app_settings 表）
│   ├── database/db.go   MySQL 打开与全部表 Migrate
│   └── logging/         日志
├── features/
│   ├── datafetch/       Tushare 数据拉取（已 Go 化，原 Python fetcher 已迁出）
│   │   ├── config.go    Datasets 元定义 + 限频参数
│   │   ├── tushare.go   HTTP client + 限频 + 重试
│   │   ├── parquet.go   parquet-go 写入 + Upsert by PK + LatestDate
│   │   ├── types.go     ColType / 各数据集 schema
│   │   ├── jobs.go      13 个 Update<Dataset> + Phase 分组（basic/price/finance/event）
│   │   ├── dates.go     日期辅助
│   │   └── service.go   Service.Run / RunAsync / GetStatus，atomic.Bool 进程内互斥
│   ├── market/          市场数据查询、涨停/横盘推荐缓存、信号评估摘要
│   │   ├── stock / daily / financial / valuation / preview / limit signal ...
│   ├── position/        持仓 & 信号生成（调用 Python CLI）
│   │   ├── service.go   GenerateSignalWithProgress：spawn python → 解析 stdout → 写 DB
│   │   ├── priority_unix.go / priority_windows.go  子进程优先级降级
│   │   └── model.go     Recommendation / RunStatus / TradeRequest
└── runtime/
    ├── result/          回测产出结构体（artifact / MySQL 落库）
    ├── task/            任务模型 + Repository（写 evaluation_tasks）
    └── worker/          子进程管理（启动 / 等待 / 取消 Python）
```

`app.go` 是 Wails 绑定入口（`App` 结构体的所有公开方法都会暴露给前端 JS）：设置、市场数据查询、数据拉取、信号生成、任务中心、时光机详情、组合优化结果应用等。`startup` 中打开数据库并按需懒加载各 service。

### 4.2 进程模型

- **桌面 (Go)** 长驻：UI、MySQL 读写、市场数据只读查询、Tushare 数据拉取（纯 Go）。
- **Python 子进程** 短暂：信号生成、回测、评估、组合优化等计算密集任务，由 Go `os/exec` 拉起，通过 venv (`quant_stock_desktop/.venv/bin/python`) 调用 `quant_stock_core/scripts/*.py`。
- **同步方式**：所有进度与结果都落 MySQL（`py_run_status` / `task_run_status` / `daily_recommendation` / `strategy_evaluation` / `evaluation_tasks` / `dataset_update_status`），前端定时轮询读取，**不使用 Wails EventsEmit / stdout 解析作为状态通道**。
- **互斥**：Python 任务用 `py_run_lock` 全局锁；Go 数据拉取用 `sync.Mutex + atomic.Bool` 进程内互斥（同进程已经天然单实例）。

### 4.3 前端布局 `frontend/src/`

React 18 + TypeScript + Vite + lucide-react，左侧菜单按业务入口拆分：

```
App.tsx              侧边导航 + 路由切换
pages/
  DashboardPage      总览
  TaskCenterPage     评估中心（任务列表 / 启动 / 取消 / 日志 / 时光机详情）
  PositionPage       持仓管理（当前持仓 / 一键调仓；聚合通用、做T、涨停、横盘推荐）
  T0AssistantPage    做T助手（日线做T候选、收益验证、时光机）
  FactorResearchPage 因子研究（IC、分层、模型、压力测试、准入对比）
  LimitBreakoutPage  涨停预警 / 横盘预警（推荐/预警列表 + 评估验证）
  PolicySupportPage  托底监测
  StockResearchPage  个股研究（K 线 + 财务 + 估值）
  DataExplorerPage   数据管理（数据集预览 / 健康度 / Tushare 拉取）
  SettingsPage       设置（路径 / token / 策略开关 / 初始资金等）
features/data/       数据相关组件（KLineChart、StockBasicPanel、PreviewPanel ...）
components/          通用 UI（Field、format）
services/app.ts      与 Go 后端的桥接层（封装 window.go.main.App.* 调用）
```

前端通过 Wails 自动生成的 `wailsjs/go/main/App.{d.ts,js}` 类型化调用 Go 方法；轮询节奏典型为 1s（信号生成、数据拉取、市场研究进度）或按需触发。

当前核心菜单：

1. `总览`
2. `持仓管理`
3. `做T助手`
4. `因子研究`
5. `涨停预警`
6. `横盘预警`
7. `评估中心`
8. `个股研究`
9. `托底监测`
10. `数据管理`
11. `设置`

---

## 5. 关键端到端流程

### 5.1 持仓管理 + 一键调仓

```
通用策略 / 做T助手 / 涨停预警 / 横盘预警
  → 各自扫描或评估任务写入推荐缓存、候选表和评估结果

PositionPage → GetPositionRecommendation
  → app.go: account rebalance aggregator
    ├─ 读取当前持仓、现金和最新价格
    ├─ 读取 rec_daily_recommendations 作为通用策略来源
    ├─ 读取 t0_daily_candidates 作为已有持仓的做T来源
    ├─ 读取 market_limit_momentum_cache 作为涨停预警来源
    └─ 读取 market_limit_breakout_cache 作为横盘预警来源
  → 输出统一目标仓位、买卖笔数、目标股数、来源策略

PositionPage → ConfirmPositionTrades
  → scripts/pool_confirm.py
  → 写 portfolio_pool_holdings / portfolio_pool_trades / portfolio_pool_summary
```

持仓管理不再承担“生成信号”的研究职责；它只做账户级调仓决策和交易确认。策略大脑分别留在通用策略、做T、涨停预警、横盘预警页面中，通过任务模式或缓存结果产出推荐。

### 5.2 Tushare 数据拉取（纯 Go）

```
DataExplorerPage → RunDataUpdate(phase) → datafetch.Service.RunAsync
  atomic.Bool 抢占 → statusBegin('data_update')
  for job in JobsForPhase(phase):
    Tushare HTTP（限频 45/min + 重试） → parquet.Upsert by PK
    statusProgress + dataset_update_status upsert
  statusDone
前端轮询 GetDataUpdateStatus + ListDatasetUpdateStatus
```

### 5.3 多策略评估 + 组合优化

```
TaskCenterPage → CreateTask(evaluation) → StartTask
  Go spawn python evaluate_strategies.py → 写 strategy_evaluation
  完成后可基于该 run_id → CreateTask(optimization) → optimize_portfolio.py
  → 写 portfolio_optimization_runs / candidates
  ApplyPortfolioCandidate → 把候选权重写回 app_settings.strategies
```

### 5.4 涨停/横盘预警 + 评估验证

```
涨停预警 → 刷新推荐
  → Go spawn scripts/limit_up_momentum_worker.py
  → 写 market_limit_momentum_cache + market_limit_signal_predictions
  → 前端展示 Top3 小卡 + 推荐列表

横盘预警 → 重新扫描
  → Go spawn scripts/limit_breakout_worker.py
  → 写 market_limit_breakout_cache + market_limit_signal_predictions
  → 前端展示形态候选

评估验证
  → Go 创建/启动 task.TypeLimitSignalEvaluation
  → Python scripts/evaluate_limit_signals.py
  → 回看 T+1/T+3/T+5/T+10 收益、5日回撤、涨停命中
  → 写 market_limit_signal_evaluations + market_limit_signal_tm_slices
  → 前端展示参数版本建议和历史切面时光机
```

切面时光机会把“当时热点/题材标签、涨停扩散、上涨占比、候选成熟度、收益和回撤”按历史交易日聚合，用于回答：某天市场热点强、涨停扩散强、横盘突发多时，这套策略的整体收益和回撤到底怎么样。

### 5.5 做T助手

```
做T助手 → 日线研究
  → scripts/t0_daily_worker.py
  → 输出今日可观察标的、近2月做T收益、触发区间和风险线

做T时光机 / 任务模式
  → 同一 worker 以 time_machine mode 跑不同 lookback/eval window
  → 写入 T0 回看结果
  → 前端展示平均合并收益、最差收益、正收益锚点和稳定性结论
```

---

## 6. 配置与环境

- 桌面所有用户配置存储在 MySQL `app_settings` 表，**不再使用 YAML**。
- Python 端通过桌面注入的 MySQL DSN 读写同一套业务表。
- venv 路径：`quant_stock_desktop/.venv/bin/python`，`quant_stock_core/requirements.txt` 列出依赖。
- 数据目录通过 settings 中的 `WorkspacePath` / `DataPath` 配置，默认指向仓库内 `data_store/`；业务状态以 MySQL 为准。
- 工作流入口：
  - 桌面构建 / 运行：`wails dev` 或 `wails build`（见 `wails.json`）
  - Python 冒烟：`cd quant_stock_core && make smoke`
  - 单独跑信号：`bash quant_stock_desktop/run_signal.sh`

---

## 7. 设计要点速记

1. **零线程通信**：Go 与 Python 之间不依赖 stdout 协议或事件总线，状态 / 结果 / 进度全部以 MySQL 表为唯一事实源。
2. **进度通用化**：`py_run_status` 与 `task_run_status` 承接通用进度和任务模式进度，前端只需轮询。
3. **Schema 兼容性**：Go 写出的 Parquet 必须与原 Python pyarrow 输出在 DuckDB 读侧完全等价（字符串 → STRING / 浮点 → DOUBLE / `is_open` → INT64）。
4. **策略零侵入扩展**：新策略文件落 `trading/strategy/` 即生效，registry 自动发现，桌面无需重新编译。
5. **保守上线**：新策略默认 disabled 候选，需多窗口时光机评估通过后才进生产权重。
6. **并发安全**：全局 `py_run_lock` + 心跳 / 僵尸超时机制保证同时只有一个 Python 计算进程；Go 端用进程内互斥保护数据拉取。
7. **研究前先留快照**：涨停、横盘、T0 等信号生成时先写预测快照，再由评估任务做历史回看，避免推荐逻辑和事后验证脱节。
