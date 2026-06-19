# Quant Stock — 架构总览

一个面向个人量化研究的桌面端选股 / 回测 / 持仓管理系统，采用 **Wails 桌面壳 (Go) + Python 量化核心 + MySQL/Parquet 数据层** 的混合架构。

> 本文档由代码仓库结构与现有 `quant_stock_core/README.md`、`quant_stock_desktop/MIGRATION_NOTES.md` 总结而成。

## 当前生产口径

当前桌面生产主线只启用 `profit_arena_model`（收益擂台）。收益擂台负责训练、挑战者评估、擂主选择、容量门禁、组合预算和最新截面买入清单。

因子工厂是研究与训练底座，用于构建因子面板、因子检验、模型训练和截面观察；它不再作为一键调仓的直接交易信号源。

旧的多策略、旧推荐入口、旧 `ml_factor_ranker` 调仓入口仅作为历史数据和兼容读取保留。桌面一键调仓统一从收益擂台最新截面读取目标仓位。

正式桌面只允许一个生产入口：`dist/quant-stock-desktop.app`。生产构建必须使用 `quant_stock_desktop/scripts/build_production_app.sh`，正式启动必须使用 `quant_stock_desktop/scripts/open_production_app.sh`，生产体检使用 `quant_stock_desktop/scripts/verify_production_app.sh`。启动脚本会先退出旧实例、校验 Bundle ID 和 App 名，再打开正式包，并反查实际运行 PID 是否来自 `dist/quant-stock-desktop.app`。体检脚本会检查正式包身份、唯一 app 产物、旧入口关键词、旧用户目录 SQLite 状态和异常运行进程。不要手工打开旧包、临时包或任何 `desktop2` 入口。

旧的涨停、横盘、做T/T0 策略已从生产系统删除。生产体检会阻断这些策略在源码入口、打包二进制、`data_store` 模型产物、MySQL 旧结果表、任务表、任务状态表和策略版本表中的残留。收益擂台仍可使用涨跌停、市场风险等因子字段作为特征，但不能恢复为独立策略入口、任务、模型目录或生产表。

---

## 1. 顶层目录

```
lh/
├── data_store/            共享运行期数据（Parquet + 日志 + 回测产出）
├── quant_stock_core/      Python 量化核心（因子快照 / 收益擂台训练 / 回测评估 / 组合复核）
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
| `backtest_results/` | 回测 / 评估 / Paper Trade / 组合回测产出 |
| `positions/` | 持仓相关 JSON（`pool.json` 等） |
| `logs/` | 桌面与 Python 的运行日志 |

关键表（迁移定义见 `quant_stock_desktop/internal/common/database/db.go`）：

- `app_settings` — KV 形式的桌面与 Python 共享配置（含 Tushare token、策略开关、初始资金等）
- `evaluation_tasks` — 桌面侧调度的评估 / 回测 / 优化任务记录
- `daily_recommendation` — 旧推荐缓存表；当前一键调仓由收益擂台最新截面生成
- `strategy_evaluation` — 旧评估兼容表；当前模型准入以收益擂台和因子工厂产物为主
- `portfolio_optimization_runs` / `portfolio_optimization_candidates` — 组合优化运行与候选
- `time_machine_snapshots` / `time_machine_trades` / `time_machine_positions` — 组合回测回放
- `market_data_files` — 已扫描数据文件元信息
- `dataset_update_status` — 各 Tushare 数据集的最近一次拉取状态
- `py_run_lock` — 全局互斥锁（同一时刻只允许一个 Python 工作进程）
- `py_run_status` — 旧通用进度表；当前长任务优先使用 `task_run_status`，`daily_signal` 只作兼容状态名
- `task_run_status` — 任务模式运行状态，因子快照、收益擂台训练/推理、评估等较长离线任务可实时观察进度
- `pool_summary` / `pool_holdings` / `pool_trades` — 实盘持仓池
- `factor_store_manifest` / `factor_store_snapshot` — 收益擂台因子快照治理元信息，记录截面覆盖、签名、门禁和审计产物
- `profit_arena_runs` / `profit_arena_evaluations` / `profit_arena_predictions` / `profit_arena_features` — 收益擂台训练、评估、最新截面推荐和特征重要度

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
| `trading/strategy/` | 历史策略插件；当前桌面生产入口不再直接启用 |
| `trading/strategy/combiner.py` | 历史多策略组合；当前默认只启用收益擂台 |
| `trading/backtest/` | 回测引擎 (`engine.py`) + 成本模型 + 指标 |
| `trading/execution/` | 历史信号生成、退出规则、Paper Trade、组合回测评估、评估 worker、通知 |
| `scripts/` | CLI 入口 |
| `tests/` | 冒烟测试 |

### 3.2 策略与因子工厂口径

历史策略插件仍可用于旧结果读取和离线研究，但桌面生产主线不再直接启用这些插件。当前生产策略只有收益擂台：

- `profit_arena_model`：收益擂台擂主，唯一一键调仓信号源。
- `factor_snapshot_worker.py`：数据更新后的后置因子截面任务，负责快照、签名、质量门禁和漂移摘要。
- `factor_research_worker.py`：因子工厂研究底座，负责因子面板、因子检验、模型训练和截面观察。
- `profit_arena_worker.py`：收益擂台训练、挑战者评估、擂主选择、容量门禁和最新截面推理。

### 3.3 CLI 入口

| 脚本 | 作用 | 触发 |
| --- | --- | --- |
| `scripts/data_update_worker.py` | 原子数据更新，写数据集级进度和失败原因 | 桌面 `数据管理` |
| `scripts/factor_snapshot_worker.py` | 数据更新后的后置因子截面构建，输出收益擂台可复用的快照、签名和质量门禁 | 桌面 `数据管理` / 后置因子截面任务 |
| `scripts/profit_arena_worker.py` | 收益擂台训练、挑战者评估、擂主选择、容量门禁和最新截面推理 | 桌面 `收益擂台` |
| `scripts/pool_confirm.py` | 持仓池交易确认 | 桌面 `ConfirmPositionTrades` |

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
│   ├── market/          市场数据查询、行情缓存、信号评估摘要
│   │   ├── stock / daily / financial / valuation / preview / limit signal ...
│   ├── position/        持仓、估值刷新、交易确认和兼容状态
│   │   ├── service.go   旧信号生成兼容逻辑；当前桌面一键调仓不再调用旧 Python 信号脚本
│   │   ├── priority_unix.go / priority_windows.go  子进程优先级降级
│   │   └── model.go     Recommendation / RunStatus / TradeRequest
└── runtime/
    ├── result/          回测产出结构体（artifact / MySQL 落库）
    ├── task/            任务模型 + Repository（写 evaluation_tasks）
    └── worker/          子进程管理（启动 / 等待 / 取消 Python）
```

`app.go` 是 Wails 绑定入口（`App` 结构体的所有公开方法都会暴露给前端 JS）：设置、市场数据查询、数据拉取、收益擂台训练/推理、任务中心、组合回测详情、组合优化结果应用等。`startup` 中打开数据库并按需懒加载各 service。

### 4.2 进程模型

- **桌面 (Go)** 长驻：UI、MySQL 读写、市场数据只读查询、Tushare 数据拉取（纯 Go）。
- **Python 子进程** 短暂：因子快照、收益擂台训练/推理、回测、评估、组合优化等计算密集任务，由 Go `os/exec` 拉起，通过 venv (`quant_stock_desktop/.venv/bin/python`) 调用 `quant_stock_core/scripts/*.py`。
- **同步方式**：所有进度与结果都落 MySQL（`py_run_status` / `task_run_status` / `daily_recommendation` / `strategy_evaluation` / `evaluation_tasks` / `dataset_update_status`），前端定时轮询读取，**不使用 Wails EventsEmit / stdout 解析作为状态通道**。
- **互斥**：Python 任务用 `py_run_lock` 全局锁；Go 数据拉取用 `sync.Mutex + atomic.Bool` 进程内互斥（同进程已经天然单实例）。

### 4.3 前端布局 `frontend/src/`

React 18 + TypeScript + Vite + lucide-react，左侧菜单按业务入口拆分：

```
App.tsx              侧边导航 + 路由切换
pages/
  DashboardPage      总览
  DataExplorerPage   数据管理（数据集预览 / 健康度 / Tushare 拉取 / 后置因子快照）
  ProfitArenaPage    收益擂台（因子快照门禁、打擂训练、擂主评估、最新截面推荐）
  PositionPage       持仓管理（当前持仓 / 一键调仓；以收益擂台最新截面为主要目标仓来源）
  TaskCenterPage     任务中心（任务列表 / 启动 / 取消 / 日志 / 组合回测详情）
  ScheduleNotifyPage 定时通知（收益擂台生产链路通知）
  FactorResearchPage 因子研究留档（截面观察、模型训练、模型评估）
  StockResearchPage  个股研究（K 线 + 财务 + 估值）
  SettingsPage       设置（生产身份 / 运行偏好 / 收益擂台定时器）
features/data/       数据相关组件（KLineChart、StockBasicPanel、PreviewPanel ...）
components/          通用 UI（Field、format）
services/app.ts      与 Go 后端的桥接层（封装 window.go.main.App.* 调用）
```

前端通过 Wails 自动生成的 `wailsjs/go/main/App.{d.ts,js}` 类型化调用 Go 方法；轮询节奏典型为 1s（收益擂台训练/推理、数据拉取、市场研究进度）或按需触发。

当前核心菜单：

1. `总览`
2. `数据管理`
3. `收益擂台`
4. `持仓管理`
5. `任务中心`
6. `定时通知`
7. `因子研究留档`
8. `个股研究`
9. `设置`
3. `因子工厂`
4. `收益擂台`
5. `定时通知`
6. `个股研究`
7. `托底监测`
8. `数据管理`
9. `设置`

---

## 5. 关键端到端流程

### 5.1 持仓管理 + 一键调仓

```
收益擂台 / 因子工厂
  → 数据更新成功后先生成收益擂台因子快照
  → 收益擂台训练产出擂主，最新截面推理写入推荐篮子、容量门禁和组合预算摘要

PositionPage → GetPositionRecommendation
  → app.go: account rebalance aggregator
    ├─ 读取当前持仓、现金和最新价格
    ├─ 读取 profit_arena_predictions 作为主推荐来源
    ├─ 校验擂主、推荐日期、容量门禁、组合风险和可买篮子
    └─ 过滤过期、容量失败、组合风险失败和观察池候选
  → 输出统一目标仓位、买卖笔数、目标股数、收益擂台元信息

PositionPage → ConfirmPositionTrades
  → scripts/pool_confirm.py
  → 写 portfolio_pool_holdings / portfolio_pool_trades / portfolio_pool_summary
```

持仓管理不再承担“生成信号”的研究职责；它只做账户级调仓决策和交易确认。策略大脑集中在收益擂台，因子工厂只作为研究和训练底座。

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

### 5.3 数据更新 + 因子快照

```
DataExplorerPage → RunDataUpdate
  Go spawn python data_update_worker.py → 写 task_run_status / dataset_update_tasks
  数据更新成功后 → runFactorSnapshotAfterDataUpdate
  Go spawn python factor_snapshot_worker.py → 写 factor_store_snapshots / factor_store_governance
  收益擂台页和任务中心读取同一条快照状态链路
```

### 5.4 收益擂台训练 + 最新截面推理

```
数据管理 → 更新数据
  → Go 数据拉取成功
  → 后置触发 scripts/factor_snapshot_worker.py
  → 写 factor_store/profit_arena_v1/latest.json + 门禁/漂移/签名摘要

收益擂台 → 继续打擂
  → Go 创建 model_training 任务
  → Python scripts/profit_arena_worker.py --mode train
  → 写 profit_arena_runs / evaluations / features
  → 通过硬门禁和 Score 自动产生擂主

收益擂台 → 重新推理
  → Python scripts/profit_arena_worker.py --mode latest
  → 读取当前擂主和最新因子快照
  → 写 profit_arena_predictions
  → 前端展示买入篮子、观察池、容量门禁、组合预算和审计状态
```

所有离线阶段必须写入可观测状态：当前阶段、进度、关键门禁、日志路径、任务表摘要和前端进度卡。没有可观测性，不允许接入生产入口。

### 5.5 因子快照治理

```
原子数据更新
  → 日线/复权/基础信息/每日指标等原子表更新
  → 因子快照按 trade_date 生成横截面
  → 质量门禁检查缺失率、覆盖率、签名版本、收益擂台特征契约
  → 收益擂台训练和推理只消费通过门禁的最新快照
```

---

## 6. 配置与环境

- 桌面所有用户配置存储在 MySQL `app_settings` 表，**不再使用 YAML**。
- Python 端通过桌面注入的 MySQL DSN 读写同一套业务表。
- venv 路径：`quant_stock_desktop/.venv/bin/python`，`quant_stock_core/requirements.txt` 列出依赖。
- 数据目录通过 settings 中的 `WorkspacePath` / `DataPath` 配置，默认指向仓库内 `data_store/`；业务状态以 MySQL 为准。
- 工作流入口：
  - 桌面开发运行：`cd quant_stock_desktop && wails dev`
  - 正式桌面打包：`quant_stock_desktop/scripts/build_production_app.sh`
  - 正式包脚本会覆盖 `dist/quant-stock-desktop.app`、清理旁路产物、修正 macOS Bundle ID / 版本 / 产品名，并校验 `dist` 只保留一个正式 app；不要手工用 `wails build` 作为分发包。
  - Python 冒烟：`cd quant_stock_core && make smoke`
  - 单独跑信号：`bash quant_stock_desktop/run_signal.sh`

---

## 7. 设计要点速记

1. **零线程通信**：Go 与 Python 之间不依赖 stdout 协议或事件总线，状态 / 结果 / 进度全部以 MySQL 表为唯一事实源。
2. **进度通用化**：`py_run_status` 与 `task_run_status` 承接通用进度和任务模式进度，前端只需轮询。
3. **Schema 兼容性**：Go 写出的 Parquet 必须与原 Python pyarrow 输出在 DuckDB 读侧完全等价（字符串 → STRING / 浮点 → DOUBLE / `is_open` → INT64）。
4. **策略零侵入扩展**：新策略文件落 `trading/strategy/` 即生效，registry 自动发现，桌面无需重新编译。
5. **保守上线**：新模型或新挑战者必须通过收益擂台评估、容量门禁、组合预算和最新截面可观测检查后才允许影响一键调仓。
6. **并发安全**：全局 `py_run_lock` + 心跳 / 僵尸超时机制保证同时只有一个 Python 计算进程；Go 端用进程内互斥保护数据拉取。
7. **研究前先留快照**：数据更新后先生成因子快照，训练、评估、推理都消费同一份可审计截面，避免推荐逻辑和事后验证脱节。
