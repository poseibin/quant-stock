# 架构改造进度备忘（共享 SQLite + DB 轮询版本）

## 仓库布局
- `lh/data_store/meta.db` 共享 SQLite
- `lh/quant_stock_core/` Python 业务（已 mv 改名）
- `lh/quant_stock_desktop/` Wails 应用
- venv = `lh/quant_stock_core/.venv/bin/python`

## 用户最终需求
- desktop 与 quant_stock_core 只通过共享 db 交互（不走 stdout 解析、不走线程通信）
- 当日推荐：db 命中即返回；缺失则生成；同一 target_date 唯一一份；--force 重算
- 进程互斥：同一时刻全局只允许 1 个 py 进程
- 评估结果同样落 SQLite
- 任务实时进度也写入 db；前端通过轮询查询

## 已完成（全部）

### Python 端 (quant_stock_core/)
1. `mv quant_stock -> quant_stock_core`
2. 新建 `infra/__init__.py`、`infra/db.py`、`infra/lock.py`、`infra/status.py`
   - `db.py`: open_db() 读 DESKTOP_DB_PATH (默认 DATA_ROOT/meta.db)；get/upsert_recommendation, get/upsert_evaluation
   - `lock.py`: PyLock 全局锁，30s 心跳，120s 僵尸超时；进入 `with` 块即拿锁，退出 DELETE
   - `status.py`: begin/progress/done/error/get，写入 `py_run_status` 表
3. `scripts/daily_signal.py` 改造：
   - 顶部 QUANT_CPU_LIMIT 限制 BLAS 线程
   - 参数 `--date --json-only --progress --force --push --paper`
   - `with PyLock("global", task="daily_signal"):` -> `status.begin()` -> 查 daily_recommendation 缓存命中即返回 -> 否则 sig.generate(force=True, progress_cb) -> upsert -> status.done()
   - progress_cb 同时写 `status.progress()` 到 db 和（可选）stderr PROGRESS 行
   - 异常调 status.error() 后 raise；LockBusyError sys.exit(2)

### Go/桌面端 (quant_stock_desktop/)
4. `internal/position/service.go`:
   - `quantStockRoot(dataPath)` 候选: lh/quant_stock_core, parent/quant_stock_core, parent/quant_core
   - `quantCorePython(projectRoot)` 候选含 `lh/quant_stock_core/.venv/bin/python`
   - `quantCoreEnv` 加 DESKTOP_DB_PATH=lh/data_store/meta.db
   - `GetRecommendation` 优先读 daily_recommendation（payload->Signal->recommendationFromSignal）
   - `GetRunStatus(task)` 查 py_run_status 表，无记录返回 state=idle
   - `GenerateSignalWithProgress` 保留（py 自己写 db status，但 Go 仍解析 stdout 写 position_recommendations 渲染缓存）
5. `internal/database/db.go` Migrate() 新增三表：
   - daily_recommendation(date PK, generated_at, payload_json, ...)
   - strategy_evaluation(date,strategy 复合 PK, ...)
   - py_run_lock(name PK, pid, hostname, acquired_at, heartbeat, task)
   - py_run_status(task PK, state, idx, total, stage, name, message, started_at, updated_at, finished_at)
6. `app.go`:
   - dbPath 改为 `filepath.Join(DataPath, "meta.db")` + MkdirAll
   - 移除 wailsruntime 的所有 EventsEmit（无线程通信）
   - GeneratePositionSignal 改为异步 go 启动后立即返回 Success: true（py 在后台跑，自己写 status）
   - 新增 GetSignalRunStatus() 暴露给前端
7. `run_signal.sh`: SCRIPT 指向 quant_stock_core，加 DESKTOP_DB_PATH 默认值

## 仍需做（前端）—— 2025-06 进行中

### services/app.ts (位置: frontend/src/services/app.ts)
1. 第 24 行 `GeneratePositionSignal` 类型保持，**追加一行**：
   `GetSignalRunStatus: () => Promise<RunStatus>`
2. 在 `GenerateSignalResponse` interface 后追加：
   ```ts
   export interface RunStatus {
     task: string; state: string; idx: number; total: number;
     stage: string; name: string; message: string;
     started_at: string; updated_at: string; finished_at: string;
   }
   ```
3. 在 `generatePositionSignal` 函数后追加：
   ```ts
   export async function getSignalRunStatus(): Promise<RunStatus> {
     if (window.go?.main?.App?.GetSignalRunStatus) {
       return window.go.main.App.GetSignalRunStatus()
     }
     return { task:'daily_signal', state:'idle', idx:0, total:0, stage:'', name:'', message:'', started_at:'', updated_at:'', finished_at:'' }
   }
   ```

### pages/PositionPage.tsx
1. **删除** `import { EventsOff, EventsOn } from '../../wailsjs/runtime/runtime'`
2. **删除** 当前的 EventsOn/EventsOff useEffect（约 96-115 行）
3. import 增加 `getSignalRunStatus, type RunStatus`
4. state: `const [runStatus, setRunStatus] = useState<RunStatus | null>(null)`，删除 `progress/generating` 单独状态（合并到 runStatus）
5. 加轮询 useEffect：
   ```tsx
   useEffect(() => {
     const tick = () => {
       getSignalRunStatus().then((s) => {
         setRunStatus(s)
         if (s.state === 'done' && runStatus?.state === 'running') {
           getPositionRecommendation().then(setRecommendation).catch(()=>{})
         }
         if (s.state === 'error' && s.message) setError(s.message)
       }).catch(()=>{})
     }
     tick()
     const id = setInterval(tick, 1000)
     return () => clearInterval(id)
   }, [runStatus?.state])
   ```
6. `generate()` 函数：
   ```tsx
   const generate = () => {
     setError('')
     generatePositionSignal({}).catch((e) => setError(e.message || '触发失败'))
   }
   ```
   不再 await 结果（py 异步跑）
7. RecommendationPanel 接收 `runStatus` 替代 `generating/progress`，用 `runStatus?.state === 'running'` 判定按钮 disabled，进度条用 `runStatus.idx/total/stage/name`

## 关键路径
- `quant_stock_desktop/internal/features/position/service.go:155-264` GenerateSignalWithProgress
- `quant_stock_desktop/internal/features/position/service.go:126-143` GetRunStatus
- `quant_stock_desktop/internal/features/position/service.go:638-666` quantStockRoot/quantCorePython
- `quant_stock_desktop/app.go:160-195` Position API
- `quant_stock_desktop/internal/common/database/db.go:97-135` 表 DDL
- `quant_stock_core/scripts/daily_signal.py` 主入口
- `quant_stock_core/infra/status.py` 进度写库
- `quant_stock_core/execution/signal.py:60` sig.generate(target_date, force, progress_cb)

---

## 2026-06 数据拉取 Go 化迁移（进行中）

### 目标
把 quant_stock_core 的 Python 数据拉取代码 (data/fetcher, data/storage/parquet_store, scripts/daily_update, scripts/bootstrap) **全部 Go 重写**到 desktop，core 只保留只读访问层 (data/storage/duckdb_query, data/validator)。

### 关键决策
- parquet 库：复用已有 `github.com/parquet-go/parquet-go v0.30.1`（不引入 go-duckdb）
- HTTP：标准库 net/http
- token 存储：desktop SQLite `app_settings` 的 settings.tushare_token（已加 model 字段）
- task type：新增 `TypeDataUpdate Type = "data_update"`
- 状态写库：复用 py_run_status 表（task='data_update'）
- 全局互斥：复用 py_run_lock 表（name='global'）—— 与 daily_signal/eval 共享
- 输出契约**严格保持**：data_store/raw/<dataset>/data.parquet (single) 或 year=YYYY.parquet (year)，core duckdb_query.py 必须能读

### Datasets 全表（含 PK + 分区 + 日期字段）—— 见 internal/datafetch/config.go
- stock_basic: single, PK[ts_code], 全量覆盖（拉 L/D/P 三态）
- trade_cal: single, PK[cal_date], 全量覆盖（exchange=SSE，从 DataStartDate 到 today）
- daily/daily_basic/adj_factor: year, PK[ts_code,trade_date], 按 trade_date 逐日
- income/balancesheet/cashflow: year(end_date), PK[ts_code,end_date,report_type], 按 period（季末）
  - **API 名要带 _vip 后缀**：income_vip / balancesheet_vip / cashflow_vip
- fina_indicator: year(end_date), PK[ts_code,end_date], **API: fina_indicator_vip**
- forecast: year(ann_date), PK[ts_code,ann_date,end_date], **API: forecast_vip** 按 ann_date 区间
- stk_holdertrade: year(ann_date), PK[ts_code,ann_date,holder_name,in_de], 按 ann_date 区间
- top_list: year(trade_date), PK[ts_code,trade_date,reason], 按 trade_date 逐日
- top_inst: year(trade_date), PK[ts_code,trade_date,exalter,reason], 按 trade_date 逐日

### Parquet schema 实测（已验证）
- 字符串字段在 Python 端是 large_string（pyarrow），数值是 double，is_open 是 int64
- 财务大表字段超多（balancesheet ~140 列，cashflow ~95 列），含 null 类型列（pyarrow null type）
- Go 写出时字符串用 string，数值用 float64，大表很难用 struct，**必须用动态 schema**

### Go parquet-go 动态 schema 写法
- parquet.SchemaOf(map) 不支持
- 用 `parquet.Group{}` 手工构建 schema：每列 `parquet.Optional(parquet.String())` 或 `parquet.Optional(parquet.Leaf(parquet.DoubleType))`
- 写入用 `parquet.NewGenericWriter[map[string]any](w, schema)` 或 row-based API
- 实际推荐：定义 row 为 `[]parquet.Value`，自己构建 schema + 用 parquet.NewWriter，按列追加值
- 备选：把所有列都当字符串写（最简单，但 core duckdb 读 daily.close 会变成 string，破坏现有读路径！）

### **重要：避免 schema 不兼容**
现有 daily/daily_basic 等 parquet 文件，core 读时通过 DuckDB 读 parquet，DuckDB 自动推断类型。
我们的 Go 写出**必须保持类型一致**：
- 字符串列 → parquet STRING（UTF8 logical type）
- 浮点列 → parquet DOUBLE
- 整数列（is_open） → INT64
- 字段名小写 + 下划线（与 Tushare 一致）

### 已完成代码
1. `internal/config/model.go` 加 TushareToken 字段
2. `internal/datafetch/config.go`: Datasets map + Tushare 限频参数
3. `internal/datafetch/tushare.go`: HTTP client，含 throttle (45/min + 接口最小间隔)、3次重试、错误码识别 hard limit

### 待完成代码（按顺序）
4. `internal/datafetch/parquet.go`: 
   - `WriteParquet(path string, fields []string, items [][]any, fieldTypes map[string]ColType) error`
   - `ReadAllAsMaps(path string) ([]map[string]any, error)` (用现有 GenericReader[map[string]interface{}] 模式)
   - `Upsert(dataset, path, fields, items, fieldTypes, pk, overwrite)`：读旧→merge by PK keep last→写 tmp→rename
   - `LatestDate(dataset string, dataPath string, dateField string) (string, error)`：扫所有 parquet 该列 max
5. `internal/datafetch/types.go`：每个 dataset 的字段类型映射（schema 关键，必须正确）
6. `internal/datafetch/jobs.go`：
   - `UpdateStockBasic(ctx, client, dataPath) (int, error)`
   - `UpdateTradeCal(...)`
   - `fetchByTradeDate(api, dataset, dataPath, startOverride)`：从 trade_cal 取交易日列表（要先调用过 UpdateTradeCal，或直接读 trade_cal/data.parquet），逐日 call API → upsert
   - `fetchFinanceByPeriod(api, dataset, dataPath, startOverride)`：生成季度 period 列表（YYYY0331/0630/0930/1231），跳过已有，调 API 全市场
   - `UpdateForecast / UpdateHolderTrade`：按 ann_date 区间一次性
7. `internal/datafetch/service.go`:
   - `Service{ db *sql.DB, client *TushareClient, dataPath string }`
   - `Run(ctx, phase, startDate)`：phase ∈ {basic, price, finance, event, all}
   - 内部用 db 加锁(py_run_lock name='global')、写 status(py_run_status task='data_update')
   - 进度回调：每个 dataset 完成 → status.progress(idx,total,stage,name)
8. `internal/task/model.go` 加 `TypeDataUpdate Type = "data_update"`
9. `app.go` 暴露：
   - `RunDataUpdate(req DataUpdateRequest) error`：异步启动 service.Run，立即返回
   - `GetDataUpdateStatus() (RunStatus, error)`：读 py_run_status task='data_update'
   - settings 透传 tushare_token
10. `frontend/src/services/app.ts` + `frontend/src/pages/DataExplorerPage.tsx`：
    - settings 页加 token 输入
    - DataExplorerPage 加"更新数据" 按钮 + phase 下拉 + 进度条（轮询 GetDataUpdateStatus）
11. core 清理：
    - 删 `quant_stock_core/data/fetcher/`
    - 删 `quant_stock_core/data/storage/parquet_store.py`
    - 删 `quant_stock_core/scripts/daily_update.py`
    - 删 `quant_stock_core/scripts/bootstrap.py`
    - 改 `quant_stock_core/data/__init__.py` 移除 fetcher 引用
    - 改 `quant_stock_core/tests/test_smoke.py` 移除 fetcher 引用
    - `quant_stock_core/requirements.txt`: 移除 tushare、akshare(akshare_client.py 也删，position_pool.py 实时报价处的 akshare 调用保留即可，import 改成 lazy in-function)
    - 注意：`config.DATASETS` 在 core 还有谁用？检查后决定是否保留或精简

### 验证步骤
- `go build ./...` 通过
- 临时小程序：调 stock_basic 拉一次 → 写 data_store_test/raw/stock_basic/data.parquet → 用 pyarrow 读出来检查 schema 与 Python 版一致
- 跑 core 的 daily_signal.py 确认读路径不受影响

### 风险点
- parquet 写入 schema 必须与 Python pyarrow 写出的兼容（DuckDB 读侧才不会爆类型错）
- 财务表字段有 null 类型列：Python 写 NaN，DuckDB 推断为 DOUBLE。Go 端遇到 Tushare 返回 null，写 null（OPTIONAL）即可
- daily 一天约 5000 行 × N 年 = 几百万行，concat 全市场再 dedupe 内存敏感，按 partition 写
- forecast/stk_holdertrade 是按 ann_date 区间一次性拉，单次响应可能很大，注意 has_more 分页（Tushare 单次 6000 行硬限）

### 已知 schema 字段（来自实测，详见 desktop/internal/market/*.go 的 struct + pyarrow 读出）
stock_basic: ts_code,symbol,name,area,industry,fullname,market,exchange,list_status,list_date,delist_date,is_hs (全 string)
trade_cal: exchange(string),cal_date(string),is_open(int64),pretrade_date(string)
daily: ts_code,trade_date(str), open/high/low/close/pre_close/change/pct_chg/vol/amount(double)
daily_basic: ts_code,trade_date(str), close/turnover_rate/turnover_rate_f/volume_ratio/pe/pe_ttm/pb/ps/ps_ttm/dv_ratio/dv_ttm/total_share/float_share/free_share/total_mv/circ_mv (double)
adj_factor: ts_code,trade_date(str), adj_factor(double)
top_list/top_inst/forecast/stk_holdertrade: 见上文 schema
income/balancesheet/cashflow/fina_indicator: 字段巨多（80~140列），均为 ts_code,ann_date,end_date 等 str + 各种 double + update_flag(str)

### parquet-go 动态 schema 关键 API（已查证 v0.30.1）
```go
import "github.com/parquet-go/parquet-go"

// 1. 构建 schema
schema := parquet.NewSchema("dataset_name", parquet.Group{
    "ts_code":    parquet.Optional(parquet.String()),       // string
    "trade_date": parquet.Optional(parquet.String()),
    "close":      parquet.Optional(parquet.Leaf(parquet.DoubleType)),
    "is_open":    parquet.Optional(parquet.Leaf(parquet.Int64Type)),
})

// 2. 写入 with map
w := parquet.NewGenericWriter[map[string]any](file, schema)
w.Write(rows)  // []map[string]any
w.Close()

// 3. 读取（已在 preview.go 用过）
reader := parquet.NewGenericReader[map[string]interface{}](file)
buffer := make([]map[string]interface{}, 128)
count, err := reader.Read(buffer)
```

### 临时验证写出 schema 是否兼容 DuckDB 的方法
```bash
/usr/bin/python3 -c "
import duckdb
con = duckdb.connect()
print(con.execute(\"SELECT * FROM read_parquet('xxx.parquet') LIMIT 5\").fetch_df())
print(con.execute(\"DESCRIBE SELECT * FROM read_parquet('xxx.parquet')\").fetch_df())
"
```

### 当前文件
- ✅ `/Users/tiger/GolandProjects/lh/quant_stock_desktop/internal/features/datafetch/config.go` (Datasets + 限频参数)
- ✅ `/Users/tiger/GolandProjects/lh/quant_stock_desktop/internal/features/datafetch/tushare.go` (HTTP client)
- ✅ `/Users/tiger/GolandProjects/lh/quant_stock_desktop/internal/common/config/model.go` (Settings.TushareToken)
- ⏳ `/Users/tiger/GolandProjects/lh/quant_stock_desktop/internal/features/datafetch/parquet.go` (写入+upsert+latest_date)
- ⏳ `/Users/tiger/GolandProjects/lh/quant_stock_desktop/internal/features/datafetch/types.go` (各 dataset 字段类型)
- ⏳ `/Users/tiger/GolandProjects/lh/quant_stock_desktop/internal/features/datafetch/jobs.go` (各 update_xxx 函数)
- ⏳ `/Users/tiger/GolandProjects/lh/quant_stock_desktop/internal/features/datafetch/lock.go` (PyLock 复刻)
- ⏳ `/Users/tiger/GolandProjects/lh/quant_stock_desktop/internal/features/datafetch/status.go` (写 py_run_status)
- ⏳ `/Users/tiger/GolandProjects/lh/quant_stock_desktop/internal/features/datafetch/service.go` (Run + Phase)
- ⏳ `app.go` 加 RunDataUpdate / GetDataUpdateStatus
- ⏳ 前端
- ⏳ core 清理


---

## 【接续工作必读】context 续接位置（写于 2026-06-01）

### 已完成（4/10 todos）
✅ 1. 勘察现有 Python 代码（schema 已实测）
✅ 2. 建骨架（config.go、Settings.TushareToken）
✅ 3. Tushare HTTP client（tushare.go）
✅ 部分 4. types.go（schema 类型映射）

### 当前要做的下一步（todos 第 4 项的剩余 + 第 5 项）
立即编写 `/Users/tiger/GolandProjects/lh/quant_stock_desktop/internal/features/datafetch/parquet.go`，包含：
1. `BuildSchema(name string, schema map[string]ColType, orderedFields []string) *parquet.Schema`
2. `WriteParquet(path string, fields []string, items [][]any, schema map[string]ColType) error`
   - tushare items 是 `[]any` 数组按 fields 顺序排列
   - 转成 `[]map[string]any`（key=field, value=按 ColType 转好的 Go 类型 string/float64/int64 或 nil）
   - 用 parquet.Group 构建 schema
   - parquet.NewGenericWriter[map[string]any] 写入
3. `ReadParquetAsMaps(path string) ([]map[string]any, []string, error)` 用于 upsert 读旧
4. `Upsert(filePath string, dataset string, newFields []string, newItems [][]any, pk []string, overwrite bool) (int, error)`
   - if overwrite: 直接 WriteParquet 到 .tmp → rename
   - else: 读旧 → merge by PK keep last → 写 .tmp → rename
5. `LatestDate(dataPath string, dataset string, dateField string) (string, error)`
   - glob raw/<dataset>/*.parquet，对每个文件读 dateField 列取 max，返回最大值字符串
6. `NextDay(date string) string`、`Today() string`、辅助函数

### 紧接着实施（todos 第 5-10 项）
- jobs.go：13 个 update_xxx 函数 + JOBS_BASIC/PRICE/FINANCE/EVENT 切片
  - 注意：fetchByTradeDate 需要先有 trade_cal 数据，从 trade_cal/data.parquet 读取交易日（is_open=1）
  - fetchFinanceByPeriod：要扫现有数据的 end_date 列汇成 done_periods set 跳过
- lock.go：复刻 PyLock：INSERT INTO py_run_lock；30s heartbeat goroutine；exit 时 DELETE
- status.go：begin/progress/done/error 写 py_run_status（task='data_update'）
- service.go：Service 结构 + Run(ctx, phase, startDate) + RunAsync(req) 启 goroutine
- task/model.go 加 TypeDataUpdate
- app.go 加 RunDataUpdate + GetDataUpdateStatus
- frontend
- core 清理（删 fetcher / parquet_store.py / daily_update.py / bootstrap.py，调整 requirements）

### 验证流程
1. `cd quant_stock_desktop && go build ./...`
2. 写一个 main_test 或临时 cmd 跑 stock_basic 一次
3. `/usr/bin/python3 -c "import pyarrow.parquet as pq; print(pq.read_schema('xxx'))"` 对比 schema
4. `cd quant_stock_core && python scripts/daily_signal.py` 确认读路径不受影响

### 关键陷阱备忘
- parquet-go GenericWriter 写 map[string]any 时，所有字段必须按 schema 声明的顺序（实测 schema 字段 map iter 顺序不稳，需要 orderedFields）
- Tushare items 中的 nil 必须正确传到 parquet null（不能 panic）
- forecast/stk_holdertrade 单次区间拉取响应可能 has_more=true，需要循环带 offset 继续拉（Python 版本没处理，但 6000 行硬限可能溢出，Go 版应处理）
- balancesheet/cashflow/income 字段可能因 Tushare 接口升级新增列，schema 必须从 fields 动态生成而非硬编码

---

## 【续接说明 v2 - 2026-06-01 第二轮】

### 已完成（todos 1-5）
- ✅ `internal/config/model.go`: Settings.TushareToken
- ✅ `internal/datafetch/config.go`: 13 datasets, 限频参数
- ✅ `internal/datafetch/tushare.go`: HTTP client + 限频(45/min) + 重试 + IsHardLimit. **关键**: TushareRow 是 type alias `= []any`（不是 named type），否则会编译错
- ✅ `internal/datafetch/types.go`: ColType, DatasetSchemas, ResolveSchema, InferFinanceSchema
- ✅ `internal/datafetch/parquet.go`: Upsert, LatestDate, ListExistingPeriods, PartitionPath, readParquetAsMaps. 用 parquet.NewGenericWriter[any] + WriteRows([]parquet.Row), Value 用 `parquet.ValueOf(v).Level(0,1,col)` 非空、`parquet.Value{}.Level(0,0,col)` 空
- ✅ `internal/datafetch/jobs.go`: UpdateStockBasic/TradeCal/Daily/DailyBasic/AdjFactor/Income/Balancesheet/Cashflow/FinaIndicator/Forecast/HolderTrade/TopList/TopInst + JobsForPhase + ParsePhase + callPaged
- ✅ `internal/datafetch/dates.go`: shiftDateImpl
- ✅ `go build ./...` 全工程通过

### 当前正在做（todo 6）：service + task 集成
关键发现：
- `internal/database/db.go:116-135` 已有 py_run_lock 和 py_run_status 表
- `internal/position/model.go:130` 已有 RunStatus 类型（Task/State/Idx/Total/Stage/Name/Message/StartedAt/UpdatedAt/FinishedAt 全 string/int）
- `internal/position/service.go:126-143` 已有 GetRunStatus(task) 实现：直接 SELECT py_run_status WHERE task=?
- `internal/task/model.go` 已有 Type 字符串类型，已存在 TypeSignalGen/TypeBacktest/TypeEvaluation 等

### 下一步要做
1. **`internal/datafetch/lock.go`** （仿 PyLock）：
   ```go
   type DBLock struct {
       db   *sql.DB
       name string
       task string
       stop chan struct{}
   }
   // 用 INSERT OR FAIL INTO py_run_lock (name,pid,hostname,acquired_at,heartbeat,task) 抢锁；
   // 抢到后 goroutine 30s 一次更新 heartbeat；
   // Release：DELETE FROM py_run_lock WHERE name=?
   // 若 INSERT 冲突且 heartbeat 超过 90s（陈旧），强制覆盖
   ```
   
2. **`internal/datafetch/status.go`**：
   ```go
   // Begin(task, total) -> INSERT/REPLACE py_run_status state='running' idx=0 total started_at=now
   // Progress(task, idx, total, stage, name, message)
   // Done(task, message)
   // Error(task, message)
   ```

3. **`internal/datafetch/service.go`**：
   ```go
   type Service struct {
       db       *sql.DB
       dataPath string
   }
   func New(db *sql.DB, dataPath string) *Service
   func (s *Service) Run(ctx, phase Phase, startDate, token string) error {
       // 1. 抢 lock name='global' task='data_update'
       // 2. status.Begin('data_update', len(jobs))
       // 3. defer Release+Done/Error
       // 4. 循环 JobsForPhase(phase)，每个 job 内调 jc.Progress 上报
       // 5. 顶层 Progress 计算 (jobIdx*1000+stageDone)/(totalJobs*1000+stageTotal) 写 status
   }
   func (s *Service) RunAsync(req DataUpdateRequest) error  // goroutine
   func (s *Service) GetStatus() (RunStatus, error)         // 查 py_run_status WHERE task='data_update'
   ```

4. **`internal/task/model.go`** 加：
   ```go
   const TypeDataUpdate Type = "data_update"
   ```

5. **`app.go`** 暴露：
   ```go
   func (a *App) RunDataUpdate(req datafetch.UpdateRequest) error
   func (a *App) GetDataUpdateStatus() (RunStatus, error)
   ```
   - 从 settings 读 TushareToken 传给 Service
   - Service 在 app.New 时构造，挂在 App 结构

6. **前端**：
   - `frontend/src/services/app.ts`：加 RunDataUpdate / GetDataUpdateStatus
   - `frontend/src/pages/DataExplorerPage.tsx`：顶部加"更新数据"按钮 + Phase 下拉(all/basic/price/finance/event) + 进度条 + 轮询 GetDataUpdateStatus（参考 SignalPage 的 GenerateSignal 写法）
   - `frontend/src/pages/SettingsPage.tsx`：加 Tushare Token 输入框

7. **core 清理**（最后做）：
   - rm -rf `quant_stock_core/data/fetcher/`
   - rm `quant_stock_core/data/storage/parquet_store.py`
   - rm `quant_stock_core/scripts/daily_update.py`
   - rm `quant_stock_core/scripts/bootstrap.py`
   - 删 akshare_client.py（孤儿）
   - 改 `quant_stock_core/data/__init__.py` 移除 fetcher 引用
   - `quant_stock_core/requirements.txt`: 移除 tushare, akshare, tqdm, tenacity
   - 注意：execution/position_pool.py 用 akshare 实时报价 → import 改成 lazy
   - 跑 `python scripts/daily_signal.py --help` 确认不依赖被删模块

8. **验证**：
   - go build ./... ✓
   - 写测试 main：用真 token 跑 stock_basic 一次 → /usr/bin/python3 检查 schema
   - 跑 daily 1 天验证 year 分区 + upsert
   - 用 core 的 daily_signal.py 读出最新数据确认兼容

### 关键陷阱备忘（已踩过的）
- `TushareRow []any`（named type）会让 `[][]any` 不能直接 append `[]TushareRow` → 必须用 `type TushareRow = []any` (alias)
- parquet-go Group{} 字段顺序不稳，必须显式 orderedFields 切片
- ResolveSchema 已对齐：已知小表用 DatasetSchemas + 字典序排序保证稳定
- 财务大表字段动态从 fields 推断（financeStringCols 白名单 → string，其余 double）
- **未验证**：parquet-go 写出的 OPTIONAL 列被 DuckDB 读时是否完全等价 Python pyarrow 输出（需要实测）

### 文件清单（datafetch 包）
```
internal/datafetch/
├── config.go    (Datasets + 限频)
├── tushare.go   (HTTP client)
├── types.go     (ColType / Schema)
├── parquet.go   (Upsert / Latest / Path)
├── dates.go     (shiftDateImpl)
└── jobs.go      (13 个 Update + Phase)
```

---

## 【续接 v3 - 锁机制调整】

### 用户反馈
拉数据是 Go 进程内的任务，与 Python 无关。**不要复用 py_run_lock**，自己用进程内 mutex 即可保证全局只有一个拉数据任务运行。

### 调整点
1. **删除 `internal/datafetch/lock.go` 里的 DBLock**：不需要 SQLite 锁、不需要 heartbeat
2. **service.go 用进程内 sync.Mutex + atomic.Bool**：
   - `running atomic.Bool` 已在 service.go 中存在 ← 这就够了
   - RunAsync 用 `running.CompareAndSwap(false, true)` 抢占，保证全局只有一个 goroutine 跑
3. **status 写库还是要保留**：`py_run_status` 表本来就是通用进度表（即便表名带 py 前缀，写入 task='data_update' 仍然合理），用于前端轮询查进度
4. **建议**：把 `py_run_status` 表名后续考虑改成 `run_status`（不本次做，避免破坏 daily_signal/eval 共享）

### 立即操作
1. 删 lock.go 整个文件（DBLock、Acquire/Release、heartbeat 全删）
2. 把 lock.go 里的 status* 函数（statusBegin/statusProgress/statusDone/statusError）和 ErrAlreadyRunning、formatErr 单独移到新文件 `status.go`
3. service.go 的 `s.run()` 删除 lock.Acquire/Release 调用，仅保留 atomic.Bool 互斥
4. go build 验证

### service.go 已有逻辑（保留）
- `running atomic.Bool` + `RunAsync` 的 CompareAndSwap 检查
- `ErrAlreadyRunning` 当抢占失败时返回
- `IsRunning()` 暴露状态
- `GetStatus()` 查 py_run_status

### lock.go 原内容拆分
保留：
- `statusBegin/Progress/Done/Error` 4 个函数
- `ErrAlreadyRunning` 变量
- `statusTask` 常量

删除：
- DBLock struct + 方法
- lockName/lockTask/staleAfter/heartbeatTk 常量
- formatErr（暂时未使用）

---

## 【续接 v4 - 测试阶段】2026-06-01

### 当前状态：全部实现完成，go build ./... 通过，进入测试阶段

### 测试入口：写一个 cmd/test_datafetch/main.go
路径：quant_stock_desktop/cmd/test_datafetch/main.go
作用：用真实 token 跑 stock_basic + trade_cal（basic phase），写到临时目录，验证 parquet schema 与 Python 旧文件兼容

### 测试命令
```bash
cd /Users/tiger/GolandProjects/lh/quant_stock_desktop
export PATH=$PATH:/opt/homebrew/bin
go run cmd/test_datafetch/main.go --token=YOUR_TOKEN --data-path=/tmp/datafetch_test --phase=basic
```

### 验证 schema 兼容
```bash
/usr/bin/python3 -c "
import pyarrow.parquet as pq
p = pq.read_table('/tmp/datafetch_test/raw/stock_basic/data.parquet')
print(p.schema)
print('rows:', len(p))
print(p.to_pandas().head())
"
```

### token 位置
- 从 ~/GolandProjects/lh/quant_stock_core/.env 或 config/settings.py 读
- 或者直接在命令行 --token= 传

### 如果 parquet schema 不兼容
关键差异点：
- Python pyarrow 写的字符串列是 large_utf8（LargeString），parquet-go 写的是 utf8（String）
- DuckDB 两种都能读，但如果 core 的 duckdb_query.py 做了 schema 约束可能报错
- 解决方案：改 buildSchema 用 parquet.Optional(parquet.String()) 已经是 utf8，通常 DuckDB 兼容

### 文件结构
```
quant_stock_desktop/
├── cmd/
│   └── test_datafetch/
│       └── main.go   ← 测试入口
├── internal/datafetch/
│   ├── config.go
│   ├── tushare.go    (HTTP client, TushareRow = []any alias)
│   ├── types.go      (ColType, DatasetSchemas, ResolveSchema)
│   ├── parquet.go    (Upsert, LatestDate, PartitionPath, read/write)
│   ├── dates.go      (shiftDateImpl)
│   ├── jobs.go       (13个UpdateXxx, JobsForPhase)
│   ├── lock.go       (statusBegin/Progress/Done/Error)
│   └── service.go    (Service, RunAsync, GetStatus, atomic.Bool)
```

### app.go 中的集成
- RunDataUpdate(req UpdateRequest) error -> datafetchService.RunAsync(req)
- GetDataUpdateStatus() (RunStatus, error) -> datafetchService.GetStatus()
- ensureDatafetchService() 懒初始化，tokenProvider = func() string { return app.settings.TushareToken }

### core 已清理
- 删除：data/fetcher/, data/storage/parquet_store.py, scripts/daily_update.py, scripts/bootstrap.py
- requirements.txt 已移除：tushare, tenacity, tqdm
- akshare 保留（execution/position_pool.py 实时报价用）
