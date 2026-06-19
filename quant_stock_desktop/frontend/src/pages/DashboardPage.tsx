import { useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import {
  getDataUpdateStatus,
  getFactorSnapshotStatus,
  getFactorStoreGovernance,
  getPositionHistory,
  getPositionRecommendation,
  getPositionSummary,
  getProductionDiagnostics,
  listDatasetUpdateStatus,
  listTasks,
  type AppInfo,
  type DatasetUpdateStatus,
  type FactorStoreGovernance,
  type PositionHistoryPoint,
  type PositionRecommendation,
  type PositionSummary,
  type RunStatus,
  type TaskDTO
} from '../services/app'
import { formatDate } from '../components/format'
import { strategyLabel } from './PositionPage'

echarts.use([CanvasRenderer, GridComponent, LegendComponent, LineChart, TooltipComponent])

function money(value: number) {
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function percent(value: number) {
  return `${(value * 100).toFixed(2)}%`
}

function signedPercent(value: number) {
  return `${value >= 0 ? '+' : ''}${percent(value)}`
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    created: '待启动',
    queued: '排队中',
    running: '运行中',
    success: '已完成',
    failed: '失败',
    interrupted: '已中断',
    cancelled: '已取消',
    done: '已完成',
    idle: '空闲',
    error: '异常',
    skipped: '已跳过',
    historical_offline: '已归档'
  }
  return labels[status] || status || '—'
}

function tone(value: number) {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return ''
}

export function DashboardPage({ appInfo }: { appInfo: AppInfo }) {
  const [summary, setSummary] = useState<PositionSummary | null>(null)
  const [history, setHistory] = useState<PositionHistoryPoint[]>([])
  const [recommendation, setRecommendation] = useState<PositionRecommendation | null>(null)
  const [tasks, setTasks] = useState<TaskDTO[]>([])
  const [dataStatus, setDataStatus] = useState<RunStatus | null>(null)
  const [factorSnapshotStatus, setFactorSnapshotStatus] = useState<RunStatus | null>(null)
  const [factorGovernance, setFactorGovernance] = useState<FactorStoreGovernance>({})
  const [datasetStatus, setDatasetStatus] = useState<DatasetUpdateStatus[]>([])
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown>>({})
  const [dashboardRefreshedAt, setDashboardRefreshedAt] = useState('')

  useEffect(() => {
    let mounted = true
    const loadDashboard = () => {
      Promise.all([
        getPositionSummary(),
        getPositionHistory(),
        getPositionRecommendation().catch(() => null),
        listTasks({ limit: 200 }),
        getDataUpdateStatus(),
        getFactorSnapshotStatus().catch(() => null),
        getFactorStoreGovernance('stock_factor_base_v1').catch(() => ({})),
        listDatasetUpdateStatus(),
        getProductionDiagnostics().catch(() => ({}))
      ]).then(([nextSummary, nextHistory, nextRecommendation, nextTasks, nextDataStatus, nextFactorSnapshotStatus, nextFactorGovernance, nextDatasetStatus, nextDiagnostics]) => {
        if (!mounted) return
        setSummary(nextSummary)
        setHistory(nextHistory)
        setRecommendation(nextRecommendation)
        setTasks(nextTasks.filter(isProductionTask))
        setDataStatus(nextDataStatus)
        setFactorSnapshotStatus(nextFactorSnapshotStatus)
        setFactorGovernance(nextFactorGovernance || {})
        setDatasetStatus(nextDatasetStatus)
        setDiagnostics(nextDiagnostics || {})
        setDashboardRefreshedAt(new Date().toISOString())
      }).catch(() => {})
    }
    loadDashboard()
    const timer = window.setInterval(loadDashboard, 15000)
    return () => {
      mounted = false
      window.clearInterval(timer)
    }
  }, [])

  const topLevelTasks = tasks.filter((task) => !task.parent_id)
  const productionTasks = topLevelTasks.filter(isProductionTask)
  const activeTasks = productionTasks.filter((task) => task.status === 'running')
  const staleRunningTasks = productionTasks.filter(isDashboardTaskHeartbeatStale)
  const pendingTasks = productionTasks.filter((task) => task.status === 'created' || task.status === 'queued')
  const runningTask = activeTasks[0]
  const completedTasks = productionTasks.filter((task) => task.status === 'success' || task.status === 'done')
  const failedTasks = productionTasks.filter((task) => task.status === 'failed' || task.status === 'interrupted' || task.status === 'cancelled')
  const dataFinished = datasetStatus.filter((item) => item.state === 'done' || item.state === 'success').length
  const dataFailed = datasetStatus.filter((item) => item.state === 'failed' || item.state === 'error').length
  const dataRunning = datasetStatus.filter((item) => item.state === 'running').length
  const dataTotal = datasetStatus.length
  const risk = buildRisk(summary)
  const returnStats = useMemo(() => buildReturnStats(history, summary), [history, summary])
  const signalReady = hasRecommendationSignal(recommendation)
  const signalStats = buildSignalStats(signalReady ? recommendation : null)
  const dataQuality = {}
  const displayDataQuality = buildDataQualityFallback(dataQuality, datasetStatus, dataStatus)
  const missingData = asStringArray(displayDataQuality.missing)
  const recovery = {}
  const displayRecovery = buildRecoveryFallback(recovery, topLevelTasks)
  const recoveryRetryable = num(displayRecovery.retryable_failed)
  const recoveryBlocked = num(displayRecovery.blocked_failed)
  const recoveryHint = recoveryBlocked
    ? `可重跑 ${recoveryRetryable} · 自动链路阻断 ${recoveryBlocked}，先回数据页重跑数据更新触发因子快照`
    : `可重跑 ${recoveryRetryable} · 阻断 0`
  const topPromotion = null
  const promotionFallback = topPromotion || recommendationSourcePromotion(signalReady ? recommendation : null)
  const topAttribution = aggregateRecommendationSources(signalReady ? recommendation : null)[0]
  const events = buildEvents({ recommendation, summary, tasks: productionTasks, dataStatus, datasetStatus })
  const currentTaskLabel = runningTask ? taskDisplayLabel(runningTask) : '无'
  const productionReadiness = buildProductionReadiness({
    dataStatus,
    factorSnapshotStatus,
    factorGovernance,
    recommendation,
    runningTask,
    staleRunningTasks,
    failedTasks
  })
  const runtimeReadiness = buildRuntimeReadiness(diagnostics)

  return (
    <div className="dashboardPage">
      <section className={`productionReadinessBanner dashboardProductionBanner ${runtimeReadiness.tone}`}>
        <div>
          <span>运行身份</span>
          <b>{runtimeReadiness.title}</b>
          <em>{runtimeReadiness.message}</em>
        </div>
        <div className="productionReadinessSteps">
          {runtimeReadiness.steps.map((step) => (
            <span className={step.tone} key={step.label}>{step.label} {step.value}</span>
          ))}
          <span className="pass">刷新 {dashboardRefreshedAt ? formatDate(dashboardRefreshedAt).replace(/^\d{4}-/, '').slice(0, 16) : '等待'}</span>
        </div>
      </section>

      <section className={`productionReadinessBanner dashboardProductionBanner ${productionReadiness.tone}`}>
        <div>
          <span>生产闭环</span>
          <b>{productionReadiness.title}</b>
          <em>{productionReadiness.message}</em>
        </div>
        <div className="productionReadinessSteps">
          {productionReadiness.steps.map((step) => (
            <span className={step.tone} key={step.label}>{step.label} {step.value}</span>
        ))}
        </div>
      </section>

      <section className="dashboardAssetPanel returnPanel">
        <div className="returnPanelIntro">
          <div>
            <div className="sectionLabel">PORTFOLIO</div>
            <div className="dashboardPanelTitle">收益与资金状态</div>
          </div>
          <div className="returnHeadline">
            <span>累计收益率</span>
            <b className={summary ? tone(summary.cum_return) : ''}>{summary ? signedPercent(summary.cum_return) : '—'}</b>
            <em>
              区间收益 {returnStats ? signedPercent(returnStats.periodReturn) : '—'}
              {summary ? ` · 持仓 ${summary.n_holdings} 只` : ''}
            </em>
          </div>
        </div>
        <div className="returnPanelBody">
          <div className="assetGrid returnMetricGrid">
            <AssetBlock label="总资产" value={summary ? money(summary.total_assets) : '—'} hint={summary ? `累计 ${signedPercent(summary.cum_return)}` : ''} tone={summary ? tone(summary.cum_return) : ''} />
            <AssetBlock label="持仓市值" value={summary ? money(summary.market_value) : '—'} hint={summary ? `仓位 ${percent(risk.positionWeight)}` : ''} />
            <AssetBlock label="可用现金" value={summary ? money(summary.cash) : '—'} hint={summary ? `占比 ${percent(risk.cashWeight)}` : ''} />
            <AssetBlock label="今日收益率" value={summary ? signedPercent(summary.today_pct) : '—'} hint={summary ? `盈亏 ${money(summary.today_pnl)}` : ''} tone={summary ? tone(summary.today_pct) : ''} />
            <AssetBlock label="年化收益率" value={returnStats ? signedPercent(returnStats.annualReturn) : '—'} hint={returnStats ? `${returnStats.days} 个自然日` : '暂无历史'} tone={returnStats ? tone(returnStats.annualReturn) : ''} />
            <AssetBlock label="最大回撤" value={returnStats ? signedPercent(returnStats.maxDrawdown) : '—'} hint={summary ? `累计盈亏 ${money(summary.total_pnl)}` : ''} tone={returnStats ? tone(returnStats.maxDrawdown) : ''} />
            <AssetBlock label="浮动盈亏" value={summary ? money(summary.unrealized_pnl) : '—'} hint={summary ? signedPercent(summary.unrealized_pct) : ''} tone={summary ? tone(summary.unrealized_pnl) : ''} />
            <AssetBlock label="已实现盈亏" value={summary ? money(summary.realized_pnl) : '—'} hint={summary ? `已平仓 ${summary.n_closed} 只` : ''} tone={summary ? tone(summary.realized_pnl) : ''} />
          </div>
          <ReturnChart history={history} />
        </div>
      </section>

      <div className="dashboardGrid">
        <section className="dashboardPanel">
          <div className="sectionLabel">BUY LIST</div>
          <div className="dashboardPanelTitle">通用策略买入清单</div>
          <div className="dashboardRows">
            <Row label="清单日期" value={signalReady ? recommendation?.date || '—' : '—'} />
            <Row label="目标仓位" value={signalReady && recommendation ? percent(recommendation.total_weight) : '—'} />
            <Row label="目标只数" value={signalReady && recommendation ? `${recommendation.n_holdings} 只` : '—'} />
            <Row label="调仓状态" value={signalReady && recommendation ? recommendation.rebalanced ? `今日已调仓 ${recommendation.rebalance_trades} 笔` : '待调仓' : '等待买入清单'} />
            <Row label="买入 / 卖出" value={signalReady ? `${signalStats.buy} / ${signalStats.sell}` : '—'} />
          </div>
        </section>

        <section className="dashboardPanel">
          <div className="sectionLabel">SYSTEM</div>
          <div className="dashboardPanelTitle">系统任务</div>
          <div className="dashboardRows">
            <Row label="当前运行" value={currentTaskLabel} />
            <Row label="待处理任务" value={`${activeTasks.length + pendingTasks.length} 个`} />
            <Row label="今日完成" value={`${completedTasks.length} 个`} />
            <Row label="异常 / 取消" value={`${failedTasks.length} 个`} tone={failedTasks.length ? 'negative' : ''} />
            <Row label="生产闭环" value={`${completedTasks.length}/${productionTasks.length}`} />
          </div>
        </section>

        <section className="dashboardPanel">
          <div className="sectionLabel">DATA</div>
          <div className="dashboardPanelTitle">数据状态</div>
          <div className="dashboardRows">
            <Row label="更新任务" value={statusLabel(dataStatus?.state || '')} />
            <Row label="当前阶段" value={dataStatus?.stage || '—'} />
            <Row label="数据集" value={dataTotal ? `${dataFinished}/${dataTotal}` : '—'} />
            <Row label="运行 / 异常" value={`${dataRunning} / ${dataFailed}`} tone={dataFailed ? 'negative' : ''} />
            <Row label="更新时间" value={dataStatus?.updated_at ? formatDate(dataStatus.updated_at) : '—'} />
          </div>
        </section>
      </div>

      <section className="dashboardPanel governanceSummaryPanel">
        <div className="dashboardSectionHeader">
          <div>
            <div className="sectionLabel">GOVERNANCE</div>
            <div className="dashboardPanelTitle">系统健康与研究闭环</div>
          </div>
          <p>数据闸门、任务恢复、通用策略冠军版本和调仓计划统一看这里，全部来自当前生产链路</p>
        </div>
        <div className="governanceSummaryGrid">
          <SummaryTile title="买入清单" value={signalReady && recommendation ? `${recommendation.rows.length} 条` : '暂无'} hint={signalReady && recommendation ? `决策日 ${formatCompactDate(recommendation.date)} · 可执行 ${recommendation.n_buy + recommendation.n_sell}` : '等待通用策略生成清单'} />
          <SummaryTile title="数据闸门" value={String(displayDataQuality.status || '—')} hint={missingData.length ? `缺少 ${missingData.join('、')}` : `数据集 ${Object.keys(asRecord(displayDataQuality.datasets) || {}).length}`} tone={missingData.length || dataFailed ? 'negative' : 'positive'} />
          <SummaryTile title="任务恢复" value={`${num(displayRecovery.total)} 个`} hint={recoveryHint} tone={recoveryBlocked ? 'negative' : ''} />
          <SummaryTile title="风险暴露" value={summary ? `${summary.n_holdings} 只` : '暂无'} hint={summary ? `总仓 ${percent(risk.positionWeight)} · 单票 ${risk.topPosition ? percent(risk.topPosition.weight) : '—'}` : '等待持仓'} />
          <SummaryTile title="冠军版本治理" value={promotionFallback ? strategyLabel(promotionFallback.strategy) : '暂无'} hint={promotionFallback ? `${promotionLabel(promotionFallback.recommended_status)} · v${promotionFallback.strategy_version} · ${Math.round(promotionFallback.score * 100)}%` : '等待通用策略冠军版本'} />
          <SummaryTile title="模型归因" value={topAttribution ? strategyLabel(String(topAttribution.strategy || '')) : '暂无'} hint={topAttribution ? `权重 ${percent(num(topAttribution.weight))}` : '等待归因结果'} />
        </div>
      </section>

      <div className="dashboardBottomGrid">
        <section className="dashboardPanel">
          <div className="sectionLabel">RISK</div>
          <div className="dashboardPanelTitle">持仓风险概览</div>
          <div className="dashboardRows">
            <Row label="最大单票权重" value={risk.topPosition ? `${risk.topPosition.name} ${percent(risk.topPosition.weight)}` : '—'} />
            <Row label="行业集中 Top 1" value={risk.topIndustry ? `${risk.topIndustry.name} ${percent(risk.topIndustry.weight)}` : '—'} />
            <Row label="今日上涨 / 下跌" value={`${risk.upCount} / ${risk.downCount}`} tone={risk.downCount > risk.upCount ? 'negative' : ''} />
            <Row label="盈利 / 亏损持仓" value={`${risk.winCount} / ${risk.lossCount}`} tone={risk.lossCount > risk.winCount ? 'negative' : ''} />
            <Row label="现金缓冲" value={percent(risk.cashWeight)} />
          </div>
        </section>

        <section className="dashboardPanel eventPanel">
          <div className="sectionLabel">TIMELINE</div>
          <div className="dashboardPanelTitle">最近事件</div>
          <div className="eventList">
            {events.map((event, index) => (
              <div className="eventItem" key={`${event.time}-${event.title}-${index}`}>
                <span className={event.tone} />
                <div>
                  <b>{event.title}</b>
                  <em>{event.detail}</em>
                </div>
                <time>{event.time}</time>
              </div>
            ))}
            {events.length === 0 && <div className="emptyEvent">暂无系统事件</div>}
          </div>
        </section>
      </div>
    </div>
  )
}

function Row({ label, value, tone = '' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="dashboardRow">
      <span>{label}</span>
      <b className={tone}>{value}</b>
    </div>
  )
}

function AssetBlock({ label, value, hint, tone = '' }: { label: string; value: string; hint: string; tone?: string }) {
  return (
    <div className="assetBlock">
      <span>{label}</span>
      <b className={tone}>{value}</b>
      <em>{hint}</em>
    </div>
  )
}

function buildRuntimeReadiness(diagnostics: Record<string, unknown>) {
  const runtime = dashboardRecord(diagnostics.runtime)
  const status = dashboardString(diagnostics.status)
  const databaseBackend = dashboardString(diagnostics.database_backend)
  const expectedDatabaseBackend = dashboardString(diagnostics.expected_database_backend) || 'mysql'
  const databaseMessage = dashboardString(diagnostics.message)
  const legacyUserSQLiteState = dashboardBool(diagnostics.legacy_user_sqlite_state)
  const retiredStrategyVersionCount = dashboardNumber(diagnostics.retired_strategy_version_count)
  const retiredStrategyTaskCount = dashboardNumber(diagnostics.retired_strategy_task_count)
  const retiredStrategyStatusCount = dashboardNumber(diagnostics.retired_strategy_status_count)
  const retiredActiveModelCount = dashboardNumber(diagnostics.retired_active_model_count)
  const retiredValidationResultCount = dashboardNumber(diagnostics.retired_validation_result_count)
  const retiredObservationCount = dashboardNumber(diagnostics.retired_observation_count)
  const retiredMySQLTableCount = dashboardNumber(diagnostics.retired_mysql_table_count)
  const retiredDataArtifactCount = dashboardNumber(diagnostics.retired_data_artifact_count)
  const profitArenaActiveRunID = dashboardString(diagnostics.profit_arena_active_run_id)
  const profitArenaChampionRunID = dashboardString(diagnostics.profit_arena_champion_run_id)
  const profitArenaLatestPredictionRunID = dashboardString(diagnostics.profit_arena_latest_prediction_run_id)
  const profitArenaActiveMatchesChampion = dashboardBool(diagnostics.profit_arena_active_matches_champion)
  const profitArenaActiveMatchesLatestPrediction = dashboardBool(diagnostics.profit_arena_active_matches_latest_prediction)
  const profitArenaRunCount = dashboardNumber(diagnostics.profit_arena_run_count)
  const profitArenaLatestPredictionDate = dashboardString(diagnostics.profit_arena_latest_prediction_date)
  const profitArenaLatestPredictionCount = dashboardNumber(diagnostics.profit_arena_latest_prediction_count)
  const bundleName = dashboardString(runtime.bundle_name)
  const bundlePath = dashboardString(runtime.bundle_path)
  const executablePath = dashboardString(runtime.real_executable_path) || dashboardString(runtime.executable_path)
  const executableModifiedAt = dashboardString(runtime.real_executable_modified_at) || dashboardString(runtime.executable_modified_at)
  const workerMode = dashboardString(runtime.worker_mode) || 'unknown'
  const processPid = dashboardNumber(runtime.process_pid)
  const processStartedAt = dashboardString(runtime.process_started_at)
  const binaryNewerThanProcess = dashboardIsAfter(executableModifiedAt, processStartedAt)
  const productionApp = dashboardBool(runtime.production_app)
  const expectedBundle = dashboardBool(runtime.expected_bundle)
  const bundleIdentifier = dashboardString(runtime.bundle_identifier)
  const expectedBundleIdentifier = dashboardBool(runtime.expected_bundle_identifier)
  const isPackaged = Boolean(bundleName || bundlePath)
  const bundleIdentifierBad = isPackaged && Boolean(bundleIdentifier) && !expectedBundleIdentifier
  const databaseBad = status === 'error' || (databaseBackend !== '' && databaseBackend !== expectedDatabaseBackend)
  const retiredStrategyTotal = retiredStrategyVersionCount + retiredStrategyTaskCount + retiredStrategyStatusCount + retiredActiveModelCount + retiredValidationResultCount + retiredObservationCount + retiredMySQLTableCount + retiredDataArtifactCount
  const retiredStrategyBad = retiredStrategyTotal > 0
  const profitArenaBad = !profitArenaActiveRunID || !profitArenaChampionRunID || !profitArenaLatestPredictionRunID || !profitArenaActiveMatchesChampion || !profitArenaActiveMatchesLatestPrediction || profitArenaRunCount <= 0 || profitArenaLatestPredictionCount <= 0
  const instanceText = [
    processPid ? `PID ${processPid}` : '',
    processStartedAt ? `启动 ${formatCompactDate(processStartedAt.replace('T', ' ').slice(0, 16))}` : ''
  ].filter(Boolean).join(' · ')
  const title = !productionApp
    ? '当前不是正式生产工作台'
    : databaseBad
      ? '生产数据库未就绪'
    : legacyUserSQLiteState
      ? '发现旧桌面 SQLite 状态'
    : retiredStrategyBad
      ? '发现旧策略版本残留'
    : profitArenaBad
      ? '通用策略生产主线未就绪'
    : binaryNewerThanProcess
      ? '当前实例需要重启'
    : isPackaged && !expectedBundle
      ? '当前打开的不是正式包'
    : bundleIdentifierBad
      ? '正式包 Bundle ID 异常'
      : '正式生产工作台已就绪'
  const message = !productionApp
    ? '请退出当前窗口，打开正式生产包，避免旧菜单或旧配置污染生产判断'
    : databaseBad
      ? databaseMessage || `当前数据库后端 ${databaseBackend || '未连接'}，生产要求 ${expectedDatabaseBackend}`
    : legacyUserSQLiteState
      ? '用户目录仍存在旧 meta.db，请使用正式启动脚本隔离后再运行'
    : retiredStrategyBad
      ? `旧策略残留：版本 ${retiredStrategyVersionCount}，任务 ${retiredStrategyTaskCount}，状态 ${retiredStrategyStatusCount}，激活指针 ${retiredActiveModelCount}，验证结果 ${retiredValidationResultCount}，观察池 ${retiredObservationCount}，旧表 ${retiredMySQLTableCount}，旧产物 ${retiredDataArtifactCount}`
    : profitArenaBad
      ? `active=${shortRunID(profitArenaActiveRunID)} champion=${shortRunID(profitArenaChampionRunID)} latestRun=${shortRunID(profitArenaLatestPredictionRunID)} runs=${profitArenaRunCount} latest=${profitArenaLatestPredictionDate || '无'}:${profitArenaLatestPredictionCount}`
    : binaryNewerThanProcess
      ? '磁盘上的正式包比当前进程更新，请退出当前窗口后重新打开正式 app'
    : isPackaged && !expectedBundle
      ? `当前包 ${bundleName || bundlePath} 不等于 quant-stock-desktop.app，请切回正式包`
    : bundleIdentifierBad
      ? `当前 Bundle ID ${bundleIdentifier || '未获取'} 不等于 com.quantstock.productionworkspace，请使用正式生产包`
      : bundlePath
        ? `当前运行自 ${bundlePath}${instanceText ? ` · ${instanceText}` : ''}`
        : executablePath
          ? `开发运行模式，执行文件 ${executablePath}${instanceText ? ` · ${instanceText}` : ''}`
          : '等待运行身份诊断上报'
  return {
    tone: !productionApp || databaseBad || legacyUserSQLiteState || retiredStrategyBad || profitArenaBad || binaryNewerThanProcess || (isPackaged && !expectedBundle) || bundleIdentifierBad ? 'blocked' : 'ready',
    title,
    message,
    steps: [
      { label: '身份', value: productionApp ? '生产' : '异常', tone: productionApp ? 'pass' : 'wait' },
      { label: '数据库', value: databaseBackend || '等待', tone: databaseBad ? 'wait' : 'pass' },
      { label: '冠军版本', value: profitArenaActiveMatchesChampion ? '对齐' : '异常', tone: profitArenaBad ? 'wait' : 'pass' },
      { label: '预测源', value: profitArenaActiveMatchesLatestPrediction ? '对齐' : '异常', tone: profitArenaBad ? 'wait' : 'pass' },
      { label: '预测', value: profitArenaLatestPredictionCount ? `${profitArenaLatestPredictionCount}` : '0', tone: profitArenaLatestPredictionCount ? 'pass' : 'wait' },
      { label: '旧状态', value: legacyUserSQLiteState ? '存在' : '隔离', tone: legacyUserSQLiteState ? 'wait' : 'pass' },
      { label: '旧策略', value: retiredStrategyTotal ? `${retiredStrategyTotal}` : '0', tone: retiredStrategyBad ? 'wait' : 'pass' },
      { label: '包名', value: isPackaged ? expectedBundle ? '通过' : '异常' : '开发', tone: !isPackaged || expectedBundle ? 'pass' : 'wait' },
      { label: 'BundleID', value: bundleIdentifier ? expectedBundleIdentifier ? '通过' : '异常' : '未获取', tone: !bundleIdentifier || expectedBundleIdentifier ? 'pass' : 'wait' },
      { label: '实例', value: binaryNewerThanProcess ? '需重启' : '当前', tone: binaryNewerThanProcess ? 'wait' : 'pass' },
      { label: '进程', value: processPid ? String(processPid) : '等待', tone: processPid ? 'pass' : 'wait' },
      { label: 'Worker', value: workerMode, tone: workerMode === 'bundled' ? 'pass' : 'run' }
    ]
  }
}

function shortRunID(value: string) {
  if (!value) return '无'
  return value.length > 18 ? `${value.slice(0, 18)}...` : value
}

function dashboardRecord(value: unknown): Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function dashboardString(value: unknown) {
  return typeof value === 'string' ? value : ''
}

function dashboardBool(value: unknown) {
  return value === true
}

function dashboardNumber(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function dashboardIsAfter(left: string, right: string) {
  const leftTime = Date.parse(left)
  const rightTime = Date.parse(right)
  return Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime > rightTime + 1000
}

function SummaryTile({ title, value, hint, tone = '' }: { title: string; value: string; hint: string; tone?: string }) {
  return (
    <div className="summaryTile">
      <span>{title}</span>
      <b className={tone}>{value}</b>
      <em>{hint}</em>
    </div>
  )
}

function ReturnChart({ history }: { history: PositionHistoryPoint[] }) {
  const chartRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!chartRef.current) return
    const chart = echarts.init(chartRef.current, 'dark')
    const rows = history.filter((item) => item.equity > 0).sort((left, right) => left.date.localeCompare(right.date))
    if (rows.length === 0) {
      chart.clear()
      return () => chart.dispose()
    }
    const dates = rows.map((item) => formatCompactDate(item.date))
    const equity = rows.map((item) => Number(item.equity.toFixed(2)))
    const returns = rows.map((item) => Number((item.cum_return * 100).toFixed(2)))
    chart.setOption({
      backgroundColor: 'transparent',
      animationDuration: 360,
      color: ['#ffb000', '#26c281'],
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(10, 15, 24, 0.96)',
        borderColor: 'rgba(255, 176, 0, 0.35)',
        textStyle: { color: '#eef2ff', fontFamily: 'JetBrains Mono, Menlo, monospace' },
        formatter: (params: unknown) => {
          const items = Array.isArray(params) ? params as Array<{ dataIndex: number }> : []
          const row = rows[items[0]?.dataIndex ?? 0]
          if (!row) return ''
          return [
            `<b>${formatCompactDate(row.date)}</b>`,
            `总资产 ${money(row.equity)}`,
            `累计收益 ${signedPercent(row.cum_return)}`,
            `日收益 ${signedPercent(row.daily_return)}`
          ].join('<br/>')
        }
      },
      legend: {
        top: 0,
        right: 6,
        textStyle: { color: '#8f9ab3' },
        itemWidth: 14,
        itemHeight: 8
      },
      grid: { left: 62, right: 58, top: 38, bottom: 34 },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.16)' } },
        axisTick: { show: false },
        axisLabel: { color: '#8f9ab3' }
      },
      yAxis: [
        {
          type: 'value',
          scale: true,
          axisLabel: { color: '#8f9ab3', formatter: (value: number) => `${Math.round(value / 10000)}万` },
          splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.07)' } }
        },
        {
          type: 'value',
          scale: true,
          axisLabel: { color: '#8f9ab3', formatter: (value: number) => `${value.toFixed(0)}%` },
          splitLine: { show: false }
        }
      ],
      series: [
        {
          type: 'line',
          name: '总资产',
          data: equity,
          smooth: true,
          symbol: rows.length <= 12 ? 'circle' : 'none',
          lineStyle: { width: 3 },
          areaStyle: { color: 'rgba(255, 176, 0, 0.10)' }
        },
        {
          type: 'line',
          name: '累计收益率',
          yAxisIndex: 1,
          data: returns,
          smooth: true,
          symbol: rows.length <= 12 ? 'circle' : 'none',
          lineStyle: { width: 2 }
        }
      ]
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [history])

  if (history.length === 0) {
    return <div className="returnChart emptyReturnChart">暂无历史快照</div>
  }
  return <div ref={chartRef} className="returnChart" />
}

function buildReturnStats(history: PositionHistoryPoint[], summary: PositionSummary | null) {
  const rows = history.filter((item) => item.equity > 0).sort((left, right) => left.date.localeCompare(right.date))
  if (rows.length === 0) return null
  const first = rows[0]
  const last = rows[rows.length - 1]
  const periodReturn = first.equity > 0 ? last.equity / first.equity - 1 : (summary?.cum_return || 0)
  const days = Math.max(1, daysBetween(first.date, last.date))
  const annualReturn = days > 0 ? Math.pow(1 + periodReturn, 365 / days) - 1 : periodReturn
  let peak = first.equity
  let maxDrawdown = 0
  for (const row of rows) {
    peak = Math.max(peak, row.equity)
    if (peak > 0) {
      maxDrawdown = Math.min(maxDrawdown, row.equity / peak - 1)
    }
  }
  return { periodReturn, annualReturn, maxDrawdown, days }
}

function daysBetween(start: string, end: string) {
  const s = parseCompactDate(start)
  const e = parseCompactDate(end)
  if (!s || !e) return 1
  return Math.max(1, Math.round((e.getTime() - s.getTime()) / 86400000))
}

function parseCompactDate(value: string) {
  if (!/^\d{8}$/.test(value)) return null
  return new Date(Number(value.slice(0, 4)), Number(value.slice(4, 6)) - 1, Number(value.slice(6, 8)))
}

function formatCompactDate(value: string) {
  if (/^\d{8}$/.test(value)) {
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
  }
  return value || '—'
}

function hasRecommendationSignal(recommendation: PositionRecommendation | null) {
  return Boolean(recommendation && (recommendation.generated_at || recommendation.date || (recommendation.rows || []).length > 0))
}

function buildSignalStats(recommendation: PositionRecommendation | null) {
  const rows = recommendation?.rows || []
  return rows.reduce((stats, row) => {
    if (row.action === 'BUY' || row.action === 'ADD' || row.action === '新建' || row.action === '加仓') stats.buy += 1
    if (row.action === 'SELL' || row.action === 'TRIM' || row.action === '减仓' || row.action === '清仓') stats.sell += 1
    return stats
  }, { buy: 0, sell: 0 })
}

function buildRisk(summary: PositionSummary | null) {
  const positions = summary?.positions || []
  const totalAssets = Math.max(summary?.total_assets || 0, 0)
  const marketValue = Math.max(summary?.market_value || 0, 0)
  const cash = Math.max(summary?.cash || 0, 0)
  const topPosition = positions.reduce<typeof positions[number] | null>((best, item) => {
    if (!best || item.weight > best.weight) return item
    return best
  }, null)
  const industryWeights = new Map<string, number>()
  positions.forEach((item) => {
    const name = item.industry || '未知行业'
    industryWeights.set(name, (industryWeights.get(name) || 0) + item.weight)
  })
  const topIndustry = [...industryWeights.entries()]
    .map(([name, weight]) => ({ name, weight }))
    .sort((left, right) => right.weight - left.weight)[0] || null
  return {
    positionWeight: totalAssets > 0 ? marketValue / totalAssets : 0,
    cashWeight: totalAssets > 0 ? cash / totalAssets : 0,
    topPosition,
    topIndustry,
    upCount: positions.filter((item) => item.today_pnl > 0).length,
    downCount: positions.filter((item) => item.today_pnl < 0).length,
    winCount: positions.filter((item) => item.unrealized_pnl > 0).length,
    lossCount: positions.filter((item) => item.unrealized_pnl < 0).length
  }
}

function buildEvents({ recommendation, summary, tasks, dataStatus, datasetStatus }: {
  recommendation: PositionRecommendation | null
  summary: PositionSummary | null
  tasks: TaskDTO[]
  dataStatus: RunStatus | null
  datasetStatus: DatasetUpdateStatus[]
}) {
  const events: Array<{ title: string; detail: string; time: string; tone: string; sortTime: string }> = []
  if (recommendation?.generated_at) {
    events.push({
      title: '今日买入清单已生成',
      detail: `${recommendation.n_holdings} 只目标持仓，${recommendation.rebalanced ? `已调仓 ${recommendation.rebalance_trades} 笔` : '待调仓'}`,
      time: formatDate(recommendation.generated_at),
      tone: recommendation.rebalanced ? 'good' : 'warn',
      sortTime: recommendation.generated_at
    })
  }
  if (summary?.updated_at) {
    events.push({
      title: '持仓收益已刷新',
      detail: `今日盈亏 ${money(summary.today_pnl)}，当前持仓 ${summary.n_holdings} 只`,
      time: formatDate(summary.updated_at),
      tone: summary.today_pnl >= 0 ? 'good' : 'bad',
      sortTime: summary.updated_at
    })
  }
  if (dataStatus?.updated_at) {
    events.push({
      title: `数据更新${statusLabel(dataStatus.state)}`,
      detail: dataStatus.stage || dataStatus.message || '数据任务状态已更新',
      time: formatDate(dataStatus.updated_at),
      tone: dataStatus.state === 'error' || dataStatus.state === 'failed' ? 'bad' : dataStatus.state === 'running' ? 'warn' : 'good',
      sortTime: dataStatus.updated_at
    })
  }
  datasetStatus
    .filter((item) => item.state === 'failed' || item.state === 'error' || item.state === 'running')
    .slice(0, 3)
    .forEach((item) => {
      events.push({
        title: `${item.dataset} ${statusLabel(item.state)}`,
        detail: item.message || item.error_message || `${item.progress_done}/${item.progress_total}`,
        time: formatDate(item.updated_at),
        tone: item.state === 'running' ? 'warn' : 'bad',
        sortTime: item.updated_at
      })
    })
  tasks.slice(0, 6).forEach((task) => {
    if (!['running', 'failed', 'error', 'interrupted', 'success', 'done'].includes(task.status)) return
    events.push({
      title: `${task.name} ${statusLabel(task.status)}`,
      detail: task.error_message || taskProgressSummary(task) || taskTypeLabel(task),
      time: formatDate(task.updated_at),
      tone: task.status === 'running' ? 'warn' : task.status === 'success' || task.status === 'done' ? 'good' : 'bad',
      sortTime: task.updated_at
    })
  })
  return events
    .filter((event) => event.sortTime)
    .sort((left, right) => right.sortTime.localeCompare(left.sortTime))
    .slice(0, 6)
}

function formatNullablePercent(value?: number | null, multiplier = 1) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return `${(value * multiplier).toFixed(2)}%`
}

function taskDisplayLabel(task: TaskDTO) {
  const progress = `${taskProgressPct(task)}%`
  const summary = taskProgressSummary(task)
  return summary ? `${task.name} · ${summary} · ${progress}` : `${task.name} · ${progress}`
}

function taskProgressPct(task: TaskDTO) {
  const pct = Number(task.progress) * 100
  if (!Number.isFinite(pct)) return 0
  return Math.max(0, Math.min(100, Math.round(pct)))
}

const DASHBOARD_TASK_HEARTBEAT_STALE_MS = 5 * 60 * 1000

function isDashboardTaskHeartbeatStale(task: TaskDTO) {
  if (task.status !== 'running') return false
  const timestamp = Date.parse(String(task.updated_at || task.started_at || ''))
  if (!Number.isFinite(timestamp)) return true
  return Date.now() - timestamp > DASHBOARD_TASK_HEARTBEAT_STALE_MS
}

function taskProgressSummary(task: TaskDTO) {
  if (task.task_type === 'factor_snapshot') {
    const snapshot = factorSnapshotSummary(task)
    if (snapshot) return snapshot
  }
  const stage = String(task.summary.name || task.summary.stage || task.subtask_name || task.subtask_key || '').trim()
  if (stage) return stage
  const message = String(task.summary.message || '')
  if (valueToken(message, 'buy_plan')) return `买入计划${buyPlanLabel(valueToken(message, 'buy_plan'))}`
  if (valueToken(message, 'portfolio_status')) return `组合预算${gateLabel(valueToken(message, 'portfolio_status'))}`
  if (message.includes('capacity_pass') || message.includes('capacity_fail')) return '容量门禁'
  if (message.includes('gate_pass') || message.includes('gate_fail')) return '硬门禁'
  return ''
}

function factorSnapshotSummary(task: TaskDTO) {
  const observability = asRecord(task.summary.observability)
  const snapshot = asRecord(observability?.factor_snapshot)
  const message = String(task.summary.message || '')
  const rows = numericValue(snapshot?.row_count, numberToken(message, 'rows'))
  const factors = numericValue(snapshot?.factor_count, numberToken(message, 'factors'))
  const quality = String(snapshot?.quality_status || valueToken(message, 'quality') || '')
  const parts = [
    rows > 0 ? `${rows}行` : '',
    factors > 0 ? `${factors}因子` : '',
    quality ? `质量${gateLabel(quality)}` : '',
  ].filter(Boolean)
  return parts.join(' · ')
}

function taskTypeLabel(task: TaskDTO) {
  if (task.task_type === 'profit_arena_rebalance') return '通用策略调仓'
  if (task.task_type === 'factor_snapshot') return '因子快照'
  if (task.task_type === 'model_training' && isProfitArenaTask(task)) return '通用策略'
  return task.task_type
}

function isProfitArenaTask(task: TaskDTO) {
  const strategy = String(task.params.strategy || '')
  const name = String(task.name || '')
  const external = String(task.external_run_id || '')
  return strategy.includes('profit_arena') || name.includes('通用策略') || external.includes('profit_arena')
}

function valueToken(message: string, key: string) {
  const match = new RegExp(`${key}=([^\\s,;]+)`).exec(message)
  return match ? match[1].trim() : ''
}

function numberToken(message: string, key: string) {
  const value = Number(valueToken(message, key))
  return Number.isFinite(value) ? value : 0
}

function numericValue(value: unknown, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function gateLabel(status: string) {
  if (status === 'pass') return '通过'
  if (status === 'warn') return '警告'
  if (status === 'fail') return '失败'
  if (status === 'missing') return '等待'
  return status
}

function buyPlanLabel(status: string) {
  if (status === 'ready') return '就绪'
  if (status === 'partial_capacity') return '容量部分可用'
  if (status === 'blocked_by_capacity') return '容量阻断'
  if (status === 'blocked_by_portfolio_risk') return '组合风险阻断'
  if (status === 'missing') return '等待'
  return status
}

function buildDataQualityFallback(dataQuality: Record<string, unknown>, datasetStatus: DatasetUpdateStatus[], runStatus: RunStatus | null) {
  const existingDatasets = asRecord(dataQuality.datasets)
  if (Object.keys(existingDatasets || {}).length > 0) return dataQuality
  const datasets: Record<string, unknown> = {}
  datasetStatus.forEach((item) => {
    datasets[item.dataset] = {
      state: item.state,
      rows: item.rows_written,
      progress_done: item.progress_done,
      progress_total: item.progress_total,
      updated_at: item.updated_at
    }
  })
  const missing = datasetStatus
    .filter((item) => item.state === 'failed' || item.state === 'error')
    .map((item) => item.dataset)
  let status = datasetStatus.length ? 'pass' : String(dataQuality.status || '—')
  if (missing.length) status = 'blocked'
  if (datasetStatus.some((item) => item.state === 'running') || runStatus?.state === 'running') status = 'running'
  return { ...dataQuality, status, missing, datasets }
}

function buildRecoveryFallback(recovery: Record<string, unknown>, tasks: TaskDTO[]) {
  if (num(recovery.total) > 0) return recovery
  const productionTasks = tasks.filter(isProductionTask)
  const failed = productionTasks.filter((task) => task.status === 'failed' || task.status === 'interrupted' || task.status === 'cancelled')
  const retryable = failed.filter((task) => isManualRecoveryTask(task) && (task.max_attempts <= 0 || task.attempt < task.max_attempts))
  return {
    ...recovery,
    total: productionTasks.length,
    retryable_failed: retryable.length,
    blocked_failed: failed.length - retryable.length
  }
}

function isProductionTask(task: TaskDTO) {
  if (task.task_type === 'data_update') return true
  if (task.task_type === 'factor_snapshot') return true
  if (task.task_type === 'profit_arena_rebalance') return true
  if (task.task_type === 'model_training') return isProfitArenaTask(task)
  return false
}

function isManualRecoveryTask(task: TaskDTO) {
  if (task.task_type === 'factor_snapshot') return false
  return isProductionTask(task)
}

function aggregateRecommendationSources(recommendation: PositionRecommendation | null): Array<Record<string, unknown>> {
  const weights = new Map<string, number>()
  recommendation?.rows.forEach((row) => {
    row.sources?.forEach((source) => {
      if (source.strategy !== 'profit_arena_model' && source.strategy !== 'profit_arena') return
      if (num(source.weight) <= 0) return
      weights.set(source.strategy, (weights.get(source.strategy) || 0) + source.weight)
    })
  })
  return [...weights.entries()]
    .map(([strategy, weight]) => ({ strategy, weight }))
    .sort((left, right) => num(right.weight) - num(left.weight))
}

function recommendationSourcePromotion(recommendation: PositionRecommendation | null) {
  const source = recommendation?.active_strategy_versions?.find((item) => item.strategy === 'profit_arena_model' || item.strategy === 'profit_arena')
  if (!source) return null
  return {
    strategy: source.strategy,
    recommended_status: source.mode || 'research',
    strategy_version: source.version || 1,
    score: source.weight || 0
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item)).filter(Boolean)
}

function num(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function buildProductionReadiness({
  dataStatus,
  factorSnapshotStatus,
  factorGovernance,
  recommendation,
  runningTask,
  staleRunningTasks,
  failedTasks
}: {
  dataStatus: RunStatus | null
  factorSnapshotStatus: RunStatus | null
  factorGovernance: FactorStoreGovernance
  recommendation: PositionRecommendation | null
  runningTask?: TaskDTO
  staleRunningTasks: TaskDTO[]
  failedTasks: TaskDTO[]
}) {
  const gate = asRecord(factorGovernance.quality_gate) || {}
  const spec = asRecord(factorGovernance.profit_arena_spec) || {}
  const freshness = asRecord(factorGovernance.snapshot_freshness) || {}
  const gateStatus = String(gate.status || factorGovernance.status || 'missing').toLowerCase()
  const specStatus = String(spec.status || factorGovernance.snapshot_fresh_status || 'missing').toLowerCase()
  const factorReady = (gateStatus === 'pass' || gateStatus === 'warn') && specStatus === 'pass'
  const snapshotDate = String(freshness.actual || factorGovernance.trade_date_max || factorGovernance.end || '')
  const signalReady = hasRecommendationSignal(recommendation)
  const dataState = dataStatus?.state || 'idle'
  const factorStep = factorSnapshotStatus?.state === 'running'
    ? { value: '生成中', tone: 'run' }
    : factorReady
      ? { value: '就绪', tone: 'pass' }
      : specStatus === 'fail' || gateStatus === 'fail'
        ? { value: '未通过', tone: 'wait' }
        : { value: '等待', tone: 'wait' }
  const steps = [
    { label: '数据', value: statusLabel(dataState), tone: productionStateTone(dataState) },
    { label: '因子', value: factorStep.value, tone: factorStep.tone },
    { label: '签名', value: gateLabel(specStatus), tone: specStatus === 'pass' ? 'pass' : 'wait' },
    { label: '心跳', value: staleRunningTasks.length ? `${staleRunningTasks.length}异常` : '正常', tone: staleRunningTasks.length ? 'wait' : 'pass' },
    { label: '买入清单', value: signalReady ? formatCompactDate(recommendation?.date || '') : '等待', tone: signalReady ? 'pass' : 'wait' },
    { label: '调仓', value: recommendation?.rebalanced ? '已执行' : signalReady ? '待执行' : '等待', tone: recommendation?.rebalanced ? 'pass' : signalReady ? 'run' : 'wait' }
  ]
  if (staleRunningTasks.length > 0) {
    const staleTask = staleRunningTasks[0]
    return {
      tone: 'blocked',
      title: `有 ${staleRunningTasks.length} 个生产任务疑似卡住`,
      message: `${staleTask.name}：running 但超过 5 分钟没有进度上报，请到任务中心查看日志或取消后重跑`,
      steps
    }
  }
  if (failedTasks.length > 0) {
    return {
      tone: 'blocked',
      title: `有 ${failedTasks.length} 个生产任务异常`,
      message: `${failedTasks[0].name}：${failedTasks[0].error_message || taskProgressSummary(failedTasks[0]) || '请到任务中心查看失败原因'}`,
      steps
    }
  }
  if (runningTask || dataStatus?.state === 'running' || factorSnapshotStatus?.state === 'running') {
    return {
      tone: 'running',
      title: '生产链路运行中',
      message: runningTask ? taskDisplayLabel(runningTask) : dataStatus?.state === 'running' ? (dataStatus.stage || dataStatus.message || '数据更新中') : (factorSnapshotStatus?.stage || factorSnapshotStatus?.message || '因子快照生成中'),
      steps
    }
  }
  if (!factorReady) {
    return {
      tone: 'blocked',
      title: '因子快照未就绪',
      message: snapshotDate ? `${formatCompactDate(snapshotDate)} 快照未通过通用策略生产签名` : '请先在数据管理执行数据更新并自动抽取因子',
      steps
    }
  }
  if (!signalReady) {
    return {
      tone: 'blocked',
      title: '等待通用策略买入清单',
      message: '因子快照已就绪，下一步需要训练冠军版本或重新推理最新截面',
      steps
    }
  }
  return {
    tone: 'ready',
    title: '通用策略生产闭环可用',
    message: `买入清单 ${formatCompactDate(recommendation?.date || '')} · ${recommendation?.n_holdings || 0} 只 · ${recommendation?.rebalanced ? '今日已调仓' : '等待条件价调仓'}`,
    steps
  }
}

function productionStateTone(state: string) {
  if (state === 'running' || state === 'queued' || state === 'created') return 'run'
  if (state === 'success' || state === 'done' || state === 'pass') return 'pass'
  if (state === 'warn' || state === 'skipped') return 'run'
  return 'wait'
}

function promotionLabel(status: string) {
  return ({
    research: '研究',
    paper: '观察中',
    active_candidate: '可生效',
    rejected: '拒绝',
    active: '生效',
    promotable: '可观察'
  } as Record<string, string>)[status] || status || '研究'
}
