import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, BrainCircuit, CheckCircle2, Play, RefreshCw, ShieldCheck, Trophy } from 'lucide-react'
import {
  getFactorStoreGovernance,
  getFactorSnapshotStatus,
  getProfitArenaMarketDate,
  getProfitArenaRunStatus,
  getProductionDiagnostics,
  listProfitArenaEvaluations,
  listProfitArenaFeatures,
  listProfitArenaPredictions,
  listProfitArenaRuns,
  listTasks,
  runProfitArenaLatestInference,
  runProfitArenaTraining,
  type ProfitArenaEvaluation,
  type ProfitArenaFeature,
  type ProfitArenaPrediction,
  type ProfitArenaRunSummary,
  type RunStatus,
  type TaskDTO,
  type FactorStoreGovernance
} from '../services/app'

type ArenaTab = 'recommend' | 'training' | 'evaluation'

type ArenaScorePayload = {
  score?: number
  raw?: {
    capital_annual_return?: number
    capital_max_drawdown?: number
    capital_sharpe?: number
    rank_ic?: number
    rank_ic_days?: number
    trade_count?: number
    calmar?: number
  }
}

type ArenaSummaryPayload = {
  arena_score?: number
  best_challenger_score_components?: ArenaScorePayload
  best?: Record<string, unknown>
  leaderboards?: Record<string, unknown[]>
  gate_summary?: Record<string, unknown>
  source_run_id?: string
  source_predictions?: string
  champion_validation?: Record<string, unknown>
  validation_status?: string
}

type ArenaExecutionConfig = {
  topN: number
  horizon: number
  maxCrashProb: number
  takeProfit: number
  stopLoss: number
  positionWeighting: string
  capitalFraction: number
}

const ARENA_ACCOUNT_INITIAL_CAPITAL = 500000
const ARENA_ACCOUNT_INITIAL_CAPITAL_LABEL = `${Math.round(ARENA_ACCOUNT_INITIAL_CAPITAL / 10000)}万元`
const ARENA_DAILY_BUY_BUDGET = 20000
const ARENA_DAILY_BUY_BUDGET_LABEL = `${Math.round(ARENA_DAILY_BUY_BUDGET / 10000)}万元`
const ARENA_AMOUNT_UNIT = 1000
const ARENA_TARGET_PARTICIPATION = 0.02
const ARENA_MAX_PARTICIPATION = 0.05
const ARENA_TARGET_PARTICIPATION_LABEL = `${Math.round(ARENA_TARGET_PARTICIPATION * 100)}%`
const ARENA_MAX_PARTICIPATION_LABEL = `${Math.round(ARENA_MAX_PARTICIPATION * 100)}%`
const ARENA_IMPACT_BPS_COEFFICIENT = 50

const tabs: Array<{ key: ArenaTab; label: string }> = [
  { key: 'recommend', label: '买入清单' },
  { key: 'training', label: '通用策略训练' },
  { key: 'evaluation', label: '冠军版本评估' }
]

function refreshFailure(label: string, result: PromiseSettledResult<unknown>): string {
  if (result.status === 'fulfilled') return ''
  const reason = result.reason
  const message = reason instanceof Error ? reason.message : String(reason || '未知错误')
  return `${label}: ${message}`
}

export function ProfitArenaPage({ onOpenResearch, onOpenData }: { onOpenResearch?: (tsCode: string) => void, onOpenData?: () => void }) {
  const [activeTab, setActiveTab] = useState<ArenaTab>('recommend')
  const [runs, setRuns] = useState<ProfitArenaRunSummary[]>([])
  const [evaluations, setEvaluations] = useState<ProfitArenaEvaluation[]>([])
  const [predictions, setPredictions] = useState<ProfitArenaPrediction[]>([])
  const [features, setFeatures] = useState<ProfitArenaFeature[]>([])
  const [tasks, setTasks] = useState<TaskDTO[]>([])
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [factorSnapshotStatus, setFactorSnapshotStatus] = useState<RunStatus | null>(null)
  const [factorGovernance, setFactorGovernance] = useState<FactorStoreGovernance>({})
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown>>({})
  const [marketDate, setMarketDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const sortedRuns = useMemo(() => [...runs].sort(compareArenaRuns), [runs])
  const selectedRun = sortedRuns[0]
  const summary = useMemo(() => parseArenaSummary(selectedRun), [selectedRun])
  const hasChampion = Boolean(selectedRun?.run_id)
  const capacitySummary = useMemo(() => arenaCapacitySummary(summary), [summary])
  const portfolioRiskSummary = useMemo(() => arenaPortfolioRiskSummary(summary), [summary])
  const gateSummary = useMemo(() => arenaGateSummary(summary), [summary])
  const gateFailures = useMemo(() => arenaGateFailures(summary), [summary])
  const selectedScore = useMemo(() => runScore(selectedRun), [selectedRun])
  const bestEval = useMemo(() => bestEvaluation(evaluations), [evaluations])
  const executionConfig = useMemo(() => arenaExecutionConfig(bestEval, selectedRun), [bestEval, selectedRun])
  const latestDate = predictions.find((row) => row.is_latest)?.trade_date || predictions[0]?.trade_date || ''
  const hasLatestPrediction = Boolean(latestDate)
  const recommendationStale = Boolean(marketDate && latestDate && normalizeDateKey(latestDate) < normalizeDateKey(marketDate))
  const latestPredictions = useMemo(() => {
    const rows = latestDate ? predictions.filter((row) => row.trade_date === latestDate || row.is_latest) : predictions
    return rows
      .sort((a, b) => b.model_score - a.model_score)
      .slice(0, 20)
  }, [latestDate, predictions])
  const latestBuyCandidates = useMemo(() => latestPredictions.filter(predictionIsBuyCandidate), [latestPredictions])
  const latestObservationCandidates = useMemo(() => latestPredictions.filter((row) => !predictionIsBuyCandidate(row)), [latestPredictions])
  const displayFeatures = useMemo(() => features
    .filter((row) => Number(row.importance) > 0)
    .sort((left, right) => {
      const rankDelta = Number(left.rank_no || 9999) - Number(right.rank_no || 9999)
      if (rankDelta !== 0) return rankDelta
      return Number(right.importance || 0) - Number(left.importance || 0)
    }), [features])
  const capacityAwareLatest = useMemo(() => latestBuyCandidates.some((row) => predictionCapacityStatus(row) !== ''), [latestBuyCandidates])
  const portfolioRiskBlockedLatest = useMemo(() => latestBuyCandidates.some((row) => predictionBuyPlanStatus(row) === 'blocked_by_portfolio_risk' || predictionPortfolioRiskStatus(row) === 'fail'), [latestBuyCandidates])
  const capacityFailedLatestCount = useMemo(() => latestBuyCandidates.filter((row) => predictionCapacityStatus(row) === 'fail').length, [latestBuyCandidates])
  const tradableLatestPredictions = useMemo(() => latestBuyCandidates.filter((row) => {
    if (portfolioRiskBlockedLatest) return false
    const status = predictionCapacityStatus(row)
    return capacityAwareLatest ? status === 'pass' || status === 'warn' : status !== 'fail'
  }), [capacityAwareLatest, latestBuyCandidates, portfolioRiskBlockedLatest])
  const capacityTradableLatestCount = tradableLatestPredictions.length
  const topRecommendations = recommendationStale ? [] : tradableLatestPredictions.slice(0, executionConfig.topN)
  const arenaTasks = useMemo(() => tasks.filter((task) => {
    const strategy = String(task.params?.strategy || '')
    return task.task_type === 'model_training' && (strategy === 'profit_arena_model' || strategy === 'profit_arena')
  }), [tasks])
  const runningTasks = arenaTasks.filter((task) => task.status === 'running').length
  const queuedTasks = arenaTasks.filter((task) => task.status === 'queued' || task.status === 'created').length
  const failedTasks = arenaTasks.filter((task) => task.status === 'failed' || task.status === 'interrupted').length
  const latestInferenceTask = arenaTasks.find((task) => isArenaLatestInferenceTask(task) && isActiveTask(task))
  const activeTask = latestInferenceTask || arenaTasks.find(isActiveTask)
  const factorSnapshotTask = tasks.find((task) => task.task_type === 'factor_snapshot' || task.id.includes('factor_snapshot') || task.name.includes('因子快照'))
  const factorSnapshotRunning = factorSnapshotStatus?.state === 'running'
  const factorGate = parseJSONRecord(factorGovernance.quality_gate)
  const factorDrift = parseJSONRecord(factorGovernance.drift_summary)
  const factorTestcase = parseJSONRecord(factorGovernance.factor_testcase)
  const factorGateStatus = String(factorGate.status || factorGovernance.status || 'missing').toLowerCase()
  const factorTestcaseStatus = String(factorTestcase.status || 'missing').toLowerCase()
  const factorArenaSpec = parseJSONRecord(factorGovernance.profit_arena_spec)
  const factorArenaSpecStatus = String(factorArenaSpec.status || factorGovernance.snapshot_fresh_status || 'missing').toLowerCase()
  const factorSnapshotReady = (factorGateStatus === 'pass' || factorGateStatus === 'warn') && factorTestcaseStatus === 'pass' && factorArenaSpecStatus === 'pass'
  const productionReadiness = arenaProductionReadiness({
    hasChampion,
    factorSnapshotReady,
    factorSnapshotRunning,
    recommendationStale,
    marketDate,
    latestDate,
    factorGateStatus,
    factorTestcaseStatus,
    factorArenaSpecStatus,
    factorSnapshotStatus,
    factorGovernance
  })

  const refresh = useCallback(async () => {
    const refreshErrors: string[] = []
    const [runResult, taskResult, statusResult, snapshotStatusResult, marketResult, governanceResult, diagnosticsResult] = await Promise.allSettled([
      listProfitArenaRuns(30),
      listTasks({ limit: 300 }),
      getProfitArenaRunStatus(),
      getFactorSnapshotStatus(),
      getProfitArenaMarketDate(),
      getFactorStoreGovernance('stock_factor_base_v1'),
      getProductionDiagnostics()
    ])

    const runItems = runResult.status === 'fulfilled' ? runResult.value : runs
    if (runResult.status === 'fulfilled') {
      setRuns(runResult.value)
    } else {
      refreshErrors.push(refreshFailure('冠军版本版本', runResult))
    }
    if (taskResult.status === 'fulfilled') {
      setTasks(taskResult.value)
    } else {
      refreshErrors.push(refreshFailure('任务中心', taskResult))
    }
    if (statusResult.status === 'fulfilled') {
      setRunStatus(statusResult.value)
    } else {
      refreshErrors.push(refreshFailure('通用策略状态', statusResult))
    }
    if (snapshotStatusResult.status === 'fulfilled') {
      setFactorSnapshotStatus(snapshotStatusResult.value)
    } else {
      refreshErrors.push(refreshFailure('因子快照状态', snapshotStatusResult))
    }
    if (marketResult.status === 'fulfilled') {
      setMarketDate(marketResult.value || '')
    } else {
      refreshErrors.push(refreshFailure('市场日期', marketResult))
    }
    if (governanceResult.status === 'fulfilled') {
      setFactorGovernance(governanceResult.value || {})
    } else {
      refreshErrors.push(refreshFailure('因子治理', governanceResult))
    }
    if (diagnosticsResult.status === 'fulfilled') {
      setDiagnostics(diagnosticsResult.value || {})
    } else {
      refreshErrors.push(refreshFailure('生产诊断', diagnosticsResult))
    }

    const runID = [...runItems].sort(compareArenaRuns)[0]?.run_id || ''
    if (runID) {
      const [evaluationResult, predictionResult, featureResult] = await Promise.allSettled([
        listProfitArenaEvaluations(runID, 160),
        listProfitArenaPredictions('', 160),
        listProfitArenaFeatures(runID, 60)
      ])
      if (evaluationResult.status === 'fulfilled') {
        setEvaluations(evaluationResult.value)
      } else {
        refreshErrors.push(refreshFailure('策略评估', evaluationResult))
      }
      if (predictionResult.status === 'fulfilled') {
        setPredictions(predictionResult.value)
      } else {
        refreshErrors.push(refreshFailure('买入清单', predictionResult))
      }
      if (featureResult.status === 'fulfilled') {
        setFeatures(featureResult.value)
      } else {
        refreshErrors.push(refreshFailure('特征重要度', featureResult))
      }
    } else if (runResult.status === 'fulfilled') {
      setEvaluations([])
      setPredictions([])
      setFeatures([])
    }

    if (refreshErrors.length > 0) {
      setError(`通用策略刷新部分失败：${refreshErrors.slice(0, 4).join('；')}`)
    } else {
      setError('')
    }
  }, [runs])

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [refresh])

  useEffect(() => {
    const intervalMs = busy || runningTasks > 0 || queuedTasks > 0 || factorSnapshotRunning ? 3000 : 15000
    const timer = window.setInterval(() => {
      refresh().catch((err) => setError(err instanceof Error ? err.message : String(err)))
    }, intervalMs)
    return () => window.clearInterval(timer)
  }, [busy, factorSnapshotRunning, queuedTasks, refresh, runningTasks])

  const startTraining = async () => {
    setBusy(true)
    setNotice('')
    setError('')
    try {
      await runProfitArenaTraining()
      await refresh()
      setNotice('已启动通用策略训练任务，可在训练页查看实时进度')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const refreshLatestInference = async () => {
    setBusy(true)
    setNotice('')
    setError('')
    try {
      const task = await runProfitArenaLatestInference()
      await refresh()
      setNotice(`已启动通用策略最新截面推理：${task.name || task.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="factorResearchPage profitArenaPage">
      {notice ? <div className="saveHint">{notice}</div> : null}
      {error ? <div className="errorBanner">{error}</div> : null}

      <div className="pageTabsHeader">
        <div className="inlineTabs evaluationModeTabs signalViewTabs" role="tablist" aria-label="通用策略页签">
          {tabs.map((tab) => (
            <button key={tab.key} className={activeTab === tab.key ? 'active' : ''} onClick={() => setActiveTab(tab.key)}>
              {tab.label}
            </button>
          ))}
        </div>
        <div className="dataUpdatedPill">市场数据：{dateLabel(marketDate || latestDate || selectedRun?.updated_at || '')}</div>
      </div>
      <ProductionDiagnosticsBanner diagnostics={diagnostics} runs={runs} />
      <ArenaProductionBanner readiness={productionReadiness} onOpenData={onOpenData} />
      <ArenaRuntimeOverview
        runStatus={runStatus}
        factorSnapshotStatus={factorSnapshotStatus}
        activeTask={activeTask}
        hasChampion={hasChampion}
        factorSnapshotReady={factorSnapshotReady}
        latestDate={latestDate}
        marketDate={marketDate}
        recommendationStale={recommendationStale}
        runningTasks={runningTasks}
        queuedTasks={queuedTasks}
        failedTasks={failedTasks}
      />

      {activeTab === 'recommend' ? (
        <>
          {activeTask ? <ArenaTaskProgress task={activeTask} /> : null}
          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">PROFIT ARENA</div>
                <h2>通用策略买入清单</h2>
                <p className="recommendationMeta">基于当前冠军版本规则输出买入项；冠军版本按 Score 自动守擂，不需要人工选择生效。</p>
              </div>
              <div className="tableHeaderRight">
                <button className="secondaryButton startButton" onClick={refreshLatestInference} disabled={busy || !hasChampion || !factorSnapshotReady} title={!hasChampion ? '等待训练产生冠军版本后才能重新推理' : factorSnapshotReady ? '使用当前冠军版本重新生成买入清单' : '请先完成数据更新并生成通过通用策略签名的因子快照'}>
                  <RefreshCw size={16} />
                  {!hasChampion ? '等待冠军版本' : !factorSnapshotReady ? '等待因子快照' : marketDate ? `重新推理至 ${dateLabel(marketDate)}` : '重新推理'}
                </button>
              </div>
            </div>

            <div className="metricStrip">
              <div className={`metricCard ${hasChampion ? 'good' : ''}`}><span>当前冠军版本</span><b>{hasChampion ? '自动生效' : '等待冠军版本'}</b><em>{shortRunID(selectedRun?.run_id || '') || '未产生冠军版本'}</em></div>
              <div className="metricCard"><span>冠军版本评分</span><b>{hasChampion ? decimalText(selectedScore.score, 1) : '—'}</b><em>{hasChampion ? '按当前100分桶规则重算' : '等待训练产生冠军版本'}</em></div>
              <div className="metricCard"><span>年化 / 回撤</span><b>{hasChampion ? pct(rawMetric(selectedRun, 'capital_annual_return')) : '—'}</b><em>{hasChampion ? `回撤 ${pct(rawMetric(selectedRun, 'capital_max_drawdown'))}` : '暂无冠军版本绩效'}</em></div>
              <div className={`metricCard ${hasChampion && rawMetric(selectedRun, 'rank_ic') >= 0.08 ? 'good' : ''}`}><span>样本外质量</span><b>{hasChampion ? decimalText(rawMetric(selectedRun, 'rank_ic'), 4) : '—'}</b><em>{hasChampion ? `收益稳定度 ${decimalText(rawMetric(selectedRun, 'capital_sharpe'), 2)}` : '暂无样本外指标'}</em></div>
              <div className={`metricCard ${hasChampion && capacitySummary.status === 'pass' ? 'good' : hasChampion && capacitySummary.status === 'fail' ? 'bad' : ''}`}><span>容量门禁</span><b>{hasChampion ? factorGateLabel(String(capacitySummary.status || 'missing')) : '等待'}</b><em>{hasChampion ? `参与率 ${pct(capacitySummary.max_participation_rate)} · 冲击 ${decimalText(capacitySummary.max_estimated_impact_bps, 1)}bps` : '等待冠军版本容量复验'}</em></div>
              <div className={`metricCard ${hasChampion && portfolioRiskSummary.status === 'pass' ? 'good' : hasChampion && portfolioRiskSummary.status === 'fail' ? 'bad' : ''}`}><span>组合预算</span><b>{hasChampion ? factorGateLabel(String(portfolioRiskSummary.status || 'missing')) : '等待'}</b><em>{hasChampion ? `单票 ${pct(portfolioRiskSummary.max_single_weight)} · 行业 ${pct(portfolioRiskSummary.max_industry_weight)}` : '等待冠军版本组合预算'}</em></div>
            </div>

            <div className="metricStrip">
              <div className={`metricCard ${recommendationStale ? 'bad' : ''}`}><span>买入截面</span><b>{dateLabel(latestDate)}</b><em>{!hasLatestPrediction ? '等待最新预测' : recommendationStale ? `落后市场数据 ${dateLabel(marketDate)}` : `Top${numberText(executionConfig.topN)} 买入清单`}</em></div>
              <div className="metricCard"><span>买入数量</span><b>{hasLatestPrediction ? numberText(topRecommendations.length) : '—'}</b><em>{latestDate ? `${dateLabel(latestDate)} 截面` : '等待最新预测'}</em></div>
              <div className="metricCard"><span>冠军版本TopN</span><b>{hasChampion ? numberText(executionConfig.topN) : '—'}</b><em>{hasChampion ? '只展示模型买入清单' : '等待冠军版本配置'}</em></div>
              <div className="metricCard"><span>观察项</span><b>{hasLatestPrediction ? numberText(latestObservationCandidates.length) : '—'}</b><em>{hasLatestPrediction ? '展示池非买入' : '等待展示池'}</em></div>
              <div className={`metricCard ${capacityAwareLatest && capacityTradableLatestCount < executionConfig.topN ? 'bad' : capacityAwareLatest ? 'good' : ''}`}><span>容量后可买</span><b>{capacityAwareLatest ? numberText(capacityTradableLatestCount) : '—'}</b><em>{capacityAwareLatest ? `目标 Top${numberText(executionConfig.topN)}` : '等待容量摘要'}</em></div>
              <div className={`metricCard ${capacityAwareLatest && capacityFailedLatestCount > 0 ? 'bad' : capacityAwareLatest ? 'good' : ''}`}><span>容量剔除</span><b>{capacityAwareLatest ? numberText(capacityFailedLatestCount) : '—'}</b><em>{capacityAwareLatest ? 'fail 不进入买入计划' : '等待容量摘要'}</em></div>
              <div className={`metricCard ${portfolioRiskBlockedLatest ? 'bad' : hasLatestPrediction && latestBuyCandidates.length > 0 ? 'good' : ''}`}><span>组合预算</span><b>{!hasLatestPrediction || latestBuyCandidates.length === 0 ? '等待' : portfolioRiskBlockedLatest ? '阻断' : '放行'}</b><em>{!hasLatestPrediction || latestBuyCandidates.length === 0 ? '等待最新买入篮子' : portfolioRiskBlockedLatest ? '整篮子不进入买入计划' : '最新篮子风险可用'}</em></div>
            </div>
            <FactorGovernancePanel governance={factorGovernance} gate={factorGate} drift={factorDrift} task={factorSnapshotTask} status={factorSnapshotStatus || undefined} onOpenData={onOpenData} />
          </section>

          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">STOCK LIST</div>
                <h2>今日买入计划</h2>
                <p className="recommendationMeta">通用策略只输出当前冠军版本最新买入截面和风控解释；容量或组合预算未通过时不生成执行股数，不自动成交。</p>
              </div>
              <span>{selectedRun ? `${dateLabel(latestDate)} · ${shortRunID(selectedRun.run_id)}` : '暂无买入截面'}</span>
            </div>
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th>排名</th>
                    <th>股票</th>
                    <th>策略动作</th>
                    <th>参考入场</th>
                    <th>计划仓位</th>
                    <th>退出参考</th>
                    <th>退出口径</th>
                    <th>风险线</th>
                    <th>验证 / 风险</th>
                  </tr>
                </thead>
                <tbody>
                  {topRecommendations.length === 0 ? (
                    <tr><td colSpan={9} className="emptyCell">{recommendationStale ? `买入截面 ${dateLabel(latestDate)} 落后市场数据 ${dateLabel(marketDate)}，今日不生成通用策略买入计划` : portfolioRiskBlockedLatest ? '最新截面组合风险预算失败，今日不生成通用策略买入计划' : capacityAwareLatest && latestPredictions.length > 0 ? '最新截面买入项全部被容量门禁挡下，今日不生成买入计划' : '暂无通用策略买入计划，请先完成训练或重新推理最新截面'}</td></tr>
                  ) : topRecommendations.map((row, index) => {
                    const plan = arenaPlan(row, index, executionConfig, topRecommendations)
                    return (
                      <tr key={`${row.run_id}-${row.trade_date}-${row.ts_code}`} className="highlightRow">
                        <td><strong>{index + 1}</strong></td>
                        <td className="stockCell">
                          <button className="tableActionButton" onClick={() => onOpenResearch?.(row.ts_code)} title="查看个股研究">
                            {row.name || row.ts_code}
                          </button>
                          <div className="mono">{row.ts_code}</div>
                          <div className="recommendationMeta currentPrice">截面收盘 {priceText(row.price)}</div>
                          <div className="recommendationMeta">{row.industry || '—'} · {dateLabel(row.trade_date)}</div>
                          <div className="recommendationMeta">市值层 {row.size_bucket || row.scope || '—'} · 持有 {numberText(executionConfig.horizon)} 日</div>
                          <div className="recommendationMeta">冠军版本 {shortRunID(row.run_id)}</div>
                        </td>
                        <td>
                          <span className={`badge ${plan.status === 'fail' ? 'failed' : 'success'}`}>{plan.status === 'fail' ? '观察' : '买入候选'}</span>
                          <div className="recommendationMeta">冠军版本 Top{numberText(executionConfig.topN)} 买入清单</div>
                          <div className="recommendationMeta">预测净收益 {pct(row.pred_return)}</div>
                          <div className="recommendationMeta">模型分数 {decimalText(row.model_score, 4)}</div>
                        </td>
                        <td>
                          <strong>{plan.buyLabel}</strong>
                          <div className="recommendationMeta">{Number(row.price) > 0 ? '使用最新截面收盘价' : '截面价缺失，需先刷新推理'}</div>
                          <div className="recommendationMeta">训练回测按次日可买入价近似</div>
                          <div className={`recommendationMeta ${plan.capacityTone}`}>容量 {plan.capacityLabel}</div>
                        </td>
                        <td>
                          <strong>{plan.shares > 0 ? `${plan.shares} 股` : '不生成执行股数'}</strong>
                          <div className="recommendationMeta">{plan.weightLabel} 资金</div>
                          <div className="recommendationMeta">{executionConfig.positionWeighting} 权重</div>
                          <div className="recommendationMeta">{plan.capitalScaleLabel}</div>
                          <div className="recommendationMeta">{plan.status === 'fail' ? '容量门禁未通过，仅保留观察解释' : `按每日买入预算${ARENA_DAILY_BUY_BUDGET_LABEL}估算`}</div>
                          <div className="recommendationMeta">账户本金{ARENA_ACCOUNT_INITIAL_CAPITAL_LABEL} · 参与率 {plan.participationLabel}</div>
                          <div className="recommendationMeta">容量阈值：目标≤{ARENA_TARGET_PARTICIPATION_LABEL} / 上限≤{ARENA_MAX_PARTICIPATION_LABEL}</div>
                        </td>
                        <td>
                          <strong>{plan.sellLabel}</strong>
                          <div className="recommendationMeta">{executionConfig.takeProfit > 0 ? `止盈 ${pct(executionConfig.takeProfit)}` : '模型未启用硬止盈'}</div>
                          <div className="recommendationMeta">退出参考 {dateLabel(row.exit_date)}</div>
                          <div className="recommendationMeta">未触达不抢跑</div>
                        </td>
                        <td>
                          <strong>{plan.shares > 0 ? `${plan.shares} 股` : '无执行股数'}</strong>
                          <div className="recommendationMeta">{plan.shares > 0 ? '对应计划仓位' : '容量未通过，不生成退出单'}</div>
                          <div className="recommendationMeta">先买后卖，不做裸卖</div>
                        </td>
                        <td>
                          <strong className="negative">{plan.stopLabel}</strong>
                          <div className="recommendationMeta">{executionConfig.stopLoss > 0 ? `止损 ${pct(executionConfig.stopLoss)}` : '模型未启用硬止损'}</div>
                          <div className="recommendationMeta">crash {pct(row.crash_prob)}</div>
                          <div className="recommendationMeta">阈值 {pct(executionConfig.maxCrashProb)}</div>
                        </td>
                        <td>
                          <strong>{decimalText(row.model_score, 4)}</strong>
                          <div className="recommendationMeta">预测净收益 {pct(row.pred_return)}</div>
                          <div className="recommendationMeta">未来收益 {pct(row.future_return)} · 最大冲高 {pct(row.future_max_return)}</div>
                          <div className="recommendationMeta">未来回撤 {pct(row.future_drawdown)} · 已结算 {pct(row.realized_return)}</div>
                          <div className="recommendationMeta">{predictionBuyPlanLabel(row)}</div>
                          <div className={`recommendationMeta ${plan.capacityTone}`}>冲击成本 {plan.impactLabel} · {plan.capacityStatusLabel}</div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}

      {activeTab === 'training' ? (
        <>
          {activeTask ? <ArenaTaskProgress task={activeTask} /> : null}
          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">TASK FRAMEWORK</div>
                <h3>通用策略训练任务</h3>
              </div>
              <div className="tableHeaderRight">
                <button className="primaryButton startButton" onClick={startTraining} disabled={busy || !factorSnapshotReady} title={factorSnapshotReady ? '基于当前因子快照继续通用策略训练' : '请先完成数据更新并生成通过通用策略签名的因子快照'}>
                  <Play size={16} />
                  {factorSnapshotReady ? '继续训练' : factorSnapshotRunning ? '因子快照生成中' : '等待因子快照'}
                </button>
              </div>
            </div>
            <div className="metricStrip">
              <div className="metricCard"><span>任务数</span><b>{numberText(arenaTasks.length)}</b><em>Task 框架内可观测</em></div>
              <div className={`metricCard ${runningTasks > 0 ? 'good' : ''}`}><span>运行中</span><b>{numberText(runningTasks)}</b><em>{runningTasks > 0 ? 'worker 正在执行' : '暂无运行任务'}</em></div>
              <div className="metricCard"><span>排队/待启动</span><b>{numberText(queuedTasks)}</b><em>created/queued</em></div>
              <div className={`metricCard ${failedTasks > 0 ? 'bad' : ''}`}><span>失败/中断</span><b>{numberText(failedTasks)}</b><em>{failedTasks > 0 ? '需要检查日志' : '暂无异常任务'}</em></div>
            </div>
            <FactorGovernancePanel governance={factorGovernance} gate={factorGate} drift={factorDrift} task={factorSnapshotTask} status={factorSnapshotStatus || undefined} onOpenData={onOpenData} />
            <table>
              <thead>
                <tr>
                  <th>任务</th>
                  <th>状态</th>
                  <th>进度</th>
                  <th>当前步骤</th>
                  <th>关键门禁</th>
                  <th>Run ID</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                {arenaTasks.length === 0 ? (
                  <tr><td colSpan={7} className="mutedText">暂无通用策略训练任务</td></tr>
                ) : arenaTasks.slice(0, 14).map((task) => {
                  const signals = arenaTaskProgressSignals(task)
                  return (
                    <tr key={task.id}>
                      <td><b>{task.name}</b><div className="mutedText">{task.id}</div></td>
                      <td><span className={`badge ${statusBadgeClass(task.status)}`}>{statusLabel(task.status)}</span></td>
                      <td>{taskProgressPct(task)}%</td>
                      <td>{task.subtask_name || task.subtask_key || taskStatusMessage(task)}</td>
                      <td>
                        <div className={`mutedText ${signals.capacityTone === 'bad' ? 'negative' : signals.capacityTone === 'good' ? 'positive' : ''}`}>容量：{signals.capacityLabel}</div>
                        <div className={`mutedText ${signals.riskTone === 'bad' ? 'negative' : signals.riskTone === 'good' ? 'positive' : ''}`}>组合：{signals.riskLabel}</div>
                        <div className="mutedText">{signals.buyPlanLabel}</div>
                      </td>
                      <td className="mono">{task.external_run_id || task.group_run_id || '-'}</td>
                      <td className="mono">{task.updated_at || task.created_at}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </section>

          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">VERSIONS</div>
                <h3>冠军版本和挑战者版本</h3>
              </div>
              <span>{selectedRun ? `当前冠军版本 ${shortRunID(selectedRun.run_id)}` : '暂无冠军版本版本'}</span>
            </div>
            <table>
              <thead>
                <tr>
                  <th>版本</th>
                  <th>状态</th>
                  <th>Score</th>
                  <th>年化</th>
                  <th>最大回撤</th>
                  <th>RankIC</th>
                  <th>Sharpe</th>
                  <th>规则</th>
                  <th>守擂状态</th>
                </tr>
              </thead>
              <tbody>
                {sortedRuns.length === 0 ? (
                  <tr><td colSpan={9} className="mutedText">暂无通用策略版本</td></tr>
                ) : sortedRuns.slice(0, 12).map((run, index) => {
                  const champion = index === 0
                  const score = runScore(run)
                  return (
                    <tr key={run.run_id}>
                      <td>
                        <b>{champion ? '当前冠军版本' : '历史挑战者'} · {shortRunID(run.run_id)}</b>
                        {champion ? <span className="versionActiveTag">守擂中</span> : null}
                        <div className="mono">{dateTimeLabel(run.updated_at)}</div>
                      </td>
                      <td><span className={`badge ${run.status === 'success' ? 'success' : run.status === 'running' ? 'running' : 'failed'}`}>{statusLabel(run.status)}</span></td>
                      <td>{decimalText(score.score, 1)}</td>
                      <td className="positive">{pct(score.annual)}</td>
                      <td className={score.drawdown >= -0.15 ? 'positive' : 'negative'}>{pct(score.drawdown)}</td>
                      <td>{decimalText(score.rankIC, 4)}</td>
                      <td>{decimalText(score.sharpe, 2)}</td>
                      <td>Top{numberText(run.best_top_n)} / {numberText(run.best_horizon)}日 / {run.best_scope || '-'}</td>
                      <td>
                        <span className={`badge ${champion ? 'success' : 'created'}`}>{champion ? '默认生效' : '未打赢冠军版本'}</span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </section>
        </>
      ) : null}

      {activeTab === 'evaluation' ? (
        <>
          {activeTask ? <ArenaTaskProgress task={activeTask} /> : null}
          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">CHAMPION REVIEW</div>
                <h3>冠军版本复验和核心指标</h3>
              </div>
              <Trophy size={22} />
            </div>
            <div className="modelChecklist">
              <div><CheckCircle2 size={16} /><span>按 Score 决定冠军版本，未打赢不替换</span></div>
              <div><ShieldCheck size={16} /><span>新冠军版本需要同配置复验后才允许通知</span></div>
              <div><BrainCircuit size={16} /><span>训练采用 4 年训练、第 5 年样本外滚动验证</span></div>
              <div><Activity size={16} /><span>买入清单进入市场验证，不自动交易</span></div>
            </div>
            <div className="factorModelSummary">
              <div><span>Score</span><b>{hasChampion ? decimalText(selectedScore.score, 1) : '—'}</b></div>
              <div><span>年化收益</span><b>{hasChampion ? pct(rawMetric(selectedRun, 'capital_annual_return')) : '—'}</b></div>
              <div><span>最大回撤</span><b>{hasChampion ? pct(rawMetric(selectedRun, 'capital_max_drawdown')) : '—'}</b></div>
              <div><span>Calmar</span><b>{hasChampion ? decimalText(rawMetric(selectedRun, 'calmar'), 2) : '—'}</b></div>
              <div><span>RankIC</span><b>{hasChampion ? decimalText(rawMetric(selectedRun, 'rank_ic'), 4) : '—'}</b></div>
              <div><span>Sharpe</span><b>{hasChampion ? decimalText(rawMetric(selectedRun, 'capital_sharpe'), 2) : '—'}</b></div>
              <div><span>交易数</span><b>{hasChampion ? numberText(rawMetric(selectedRun, 'trade_count')) : '—'}</b></div>
              <div><span>RankIC天数</span><b>{hasChampion ? numberText(rawMetric(selectedRun, 'rank_ic_days')) : '—'}</b></div>
              <div className="wide"><span>模型来源</span><code>{summary.source_run_id || selectedRun?.model_path || '—'}</code></div>
            </div>
            <div className="metricStrip">
              <div className={`metricCard ${hasChampion ? gateSummary.pass_ratio >= 0.5 ? 'good' : gateSummary.pass_count > 0 ? '' : 'bad' : ''}`}><span>硬门禁通过</span><b>{hasChampion ? `${numberText(gateSummary.pass_count)} / ${numberText(gateSummary.tradable_count)}` : '—'}</b><em>{hasChampion ? `通过率 ${pct(gateSummary.pass_ratio)}` : '等待冠军版本评估'}</em></div>
              <div className={`metricCard ${hasChampion && gateSummary.fail_count > 0 ? 'bad' : hasChampion ? 'good' : ''}`}><span>硬门禁淘汰</span><b>{hasChampion ? numberText(gateSummary.fail_count) : '—'}</b><em>{hasChampion ? gateSummary.primary_label || '无主要失败' : '等待冠军版本评估'}</em></div>
              <div className="metricCard"><span>主要失败占比</span><b>{hasChampion ? pct(gateSummary.primary_ratio) : '—'}</b><em>{hasChampion ? gateSummary.primary_count ? `${gateSummary.primary_count} 个买入项` : '暂无失败买入项' : '等待冠军版本评估'}</em></div>
            </div>
            <ArenaGateDiagnosticsPanel failures={gateFailures} hasChampion={hasChampion} />
          </section>

          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">ARENA GRID</div>
                <h3>通用策略评估结果</h3>
              </div>
              <span>{selectedRun ? shortRunID(selectedRun.run_id) : '暂无 run'}</span>
            </div>
            <table>
              <thead>
                <tr>
                  <th>规则</th>
                  <th>交易数</th>
                  <th>胜率</th>
                  <th>年化</th>
                  <th>最大回撤</th>
                  <th>Sharpe</th>
                  <th>资金终值</th>
                  <th>机构门禁</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                {evaluations.length === 0 ? (
                  <tr><td colSpan={9} className="mutedText">暂无策略评估结果</td></tr>
                ) : evaluations.slice(0, 20).map((row) => {
                  const gate = arenaEvaluationGate(row)
                  return (
                    <tr key={`${row.run_id}-${row.scope}-${row.horizon}-${row.top_n}-${row.min_pred_return}-${row.segment}`}>
                      <td>
                        <b>{arenaEvaluationRuleLabel(row)}</b>
                        <div className="mutedText">{numberText(row.horizon)}日持有 · 收益门槛 {pct(row.min_pred_return)}</div>
                        {row.segment && row.segment !== 'all' ? <div className="mutedText">{row.segment}</div> : null}
                      </td>
                      <td>{numberText(row.trade_count)}</td>
                      <td>{pct(row.win_rate)}</td>
                      <td className="positive">{pct(row.capital_annual_return || row.annual_return)}</td>
                      <td className={(row.capital_max_drawdown || row.max_drawdown) >= -0.15 ? 'positive' : 'negative'}>{pct(row.capital_max_drawdown || row.max_drawdown)}</td>
                      <td>{decimalText(row.capital_sharpe || row.sharpe, 2)}</td>
                      <td>{decimalText(row.capital_final_equity, 2)}</td>
                      <td>
                        <span className={`badge ${gate.ok ? 'success' : 'failed'}`}>{gate.ok ? '可守擂' : '已淘汰'}</span>
                        <div className="mutedText">{gate.text}</div>
                        {gate.detail ? <div className="mutedText">{gate.detail}</div> : null}
                      </td>
                      <td className="mono">{dateTimeLabel(row.updated_at)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </section>

          <section className="detailCard">
            <div className="tableHeader">
              <div>
                <div className="sectionLabel">FEATURES</div>
                <h3>模型特征重要度</h3>
              </div>
              <span>{hasChampion ? `${numberText(displayFeatures.length || features.length)} 个特征` : '等待特征'}</span>
            </div>
            <div className="researchModelFeatureList">
              {features.length === 0 ? (
                <div className="taskGridEmpty compactEmpty">暂无特征重要度</div>
              ) : displayFeatures.length === 0 ? (
                <div className="taskGridEmpty compactEmpty">当前版本未写入有效特征重要度，避免展示全 0 噪声；请以下次训练产物为准。</div>
              ) : displayFeatures.slice(0, 30).map((row) => (
                <span key={`${row.run_id}-${row.feature}`}>{row.rank_no}. {featureLabel(row.feature)} · {decimalText(row.importance, 1)}</span>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}

function isActiveTask(task: TaskDTO) {
  return task.status === 'running'
}

function isArenaLatestInferenceTask(task: TaskDTO) {
  const profile = String(task.params?.profile || '')
  const name = String(task.name || '')
  return profile === 'inference' || name.includes('重新推理')
}

type ArenaProductionReadiness = {
  tone: string
  title: string
  message: string
  action: string
  steps: Array<{ label: string; value: string; tone: string }>
}

function ArenaRuntimeOverview({
  runStatus,
  factorSnapshotStatus,
  activeTask,
  hasChampion,
  factorSnapshotReady,
  latestDate,
  marketDate,
  recommendationStale,
  runningTasks,
  queuedTasks,
  failedTasks,
}: {
  runStatus: RunStatus | null
  factorSnapshotStatus: RunStatus | null
  activeTask?: TaskDTO
  hasChampion: boolean
  factorSnapshotReady: boolean
  latestDate: string
  marketDate: string
  recommendationStale: boolean
  runningTasks: number
  queuedTasks: number
  failedTasks: number
}) {
  const activeStage = activeTask ? arenaTaskProgressSignals(activeTask).stageLabel : runStatusMessage(runStatus)
  const factorState = factorSnapshotStatus?.state || 'idle'
  const arenaState = activeTask?.status || runStatus?.state || 'idle'
  const factorTone = factorSnapshotReady
    ? 'good'
    : factorState === 'running'
      ? ''
      : factorState === 'error' || factorState === 'failed' || factorState === 'interrupted'
        ? 'bad'
        : ''
  const buyListState = !hasChampion
    ? '等待冠军版本'
    : recommendationStale
      ? '需重新推理'
      : latestDate
        ? '已生成'
        : '等待截面'
  return (
    <section className="detailCard arenaRuntimeOverview">
      <div className="metricStrip compactMetrics">
        <div className={`metricCard ${arenaState === 'running' ? 'good' : failedTasks > 0 ? 'bad' : ''}`}>
          <span>训练/推理</span>
          <b>{statusLabel(arenaState)}</b>
          <em>{activeStage || `运行 ${numberText(runningTasks)} · 排队 ${numberText(queuedTasks)} · 异常 ${numberText(failedTasks)}`}</em>
        </div>
        <div className={`metricCard ${factorTone}`}>
          <span>因子截面</span>
          <b>{factorSnapshotReady ? '可用' : statusLabel(factorState)}</b>
          <em>{runStatusMessage(factorSnapshotStatus)}</em>
        </div>
        <div className={`metricCard ${hasChampion ? 'good' : ''}`}>
          <span>当前冠军版本</span>
          <b>{hasChampion ? '已有' : '缺失'}</b>
          <em>{hasChampion ? '训练胜出版本自动守擂' : '需要先完成训练'}</em>
        </div>
        <div className={`metricCard ${recommendationStale ? 'bad' : latestDate ? 'good' : ''}`}>
          <span>买入清单</span>
          <b>{buyListState}</b>
          <em>{latestDate ? `${dateLabel(latestDate)}${marketDate ? ` · 市场 ${dateLabel(marketDate)}` : ''}` : '等待最新推理结果'}</em>
        </div>
      </div>
    </section>
  )
}

function ArenaProductionBanner({ readiness, onOpenData }: { readiness: ArenaProductionReadiness, onOpenData?: () => void }) {
  return (
    <section className={`productionReadinessBanner arenaReadinessBanner ${readiness.tone}`}>
      <div>
        <span>生产就绪状态</span>
        <b>{readiness.title}</b>
        <em>{readiness.message}</em>
      </div>
      <div className="productionReadinessSteps">
        {readiness.steps.map((step) => (
          <span className={step.tone} key={step.label}>{step.label} {step.value}</span>
        ))}
      </div>
      {readiness.action === 'data' && onOpenData ? (
        <button className="secondaryButton quietButton" onClick={onOpenData}>去数据管理</button>
      ) : null}
    </section>
  )
}

function ProductionDiagnosticsBanner({ diagnostics, runs }: { diagnostics: Record<string, unknown>; runs: ProfitArenaRunSummary[] }) {
  const status = String(diagnostics.status || '')
  const counts = parseJSONRecord(diagnostics.counts)
  const arenaRunCount = Number(counts.profit_arena_runs || 0)
  const predictionCount = Number(counts.profit_arena_predictions || 0)
  const latestTradeDate = String(diagnostics.latest_trade_date || '')
  const backend = String(diagnostics.database_backend || '')
  const message = String(diagnostics.message || '')
  const shouldShow = status === 'error' || status === 'offline' || (arenaRunCount > 0 && runs.length === 0)
  if (!shouldShow) return null
  return (
    <section className="productionReadinessBanner arenaReadinessBanner blocked">
      <div>
        <span>生产数据诊断</span>
        <b>{status === 'ok' ? '通用策略数据未进入页面' : '后端数据连接异常'}</b>
        <em>{message || `backend=${backend || 'unknown'} · 冠军版本 ${numberText(arenaRunCount)} · 预测 ${numberText(predictionCount)} · 最新行情 ${dateLabel(latestTradeDate)}`}</em>
      </div>
    </section>
  )
}

function arenaProductionReadiness({
  hasChampion,
  factorSnapshotReady,
  factorSnapshotRunning,
  recommendationStale,
  marketDate,
  latestDate,
  factorGateStatus,
  factorTestcaseStatus,
  factorArenaSpecStatus,
  factorSnapshotStatus,
  factorGovernance
}: {
  hasChampion: boolean
  factorSnapshotReady: boolean
  factorSnapshotRunning: boolean
  recommendationStale: boolean
  marketDate: string
  latestDate: string
  factorGateStatus: string
  factorTestcaseStatus: string
  factorArenaSpecStatus: string
  factorSnapshotStatus: RunStatus | null
  factorGovernance: FactorStoreGovernance
}): ArenaProductionReadiness {
  const rowCount = Number(factorGovernance.row_count || 0)
  const factorCount = Number(factorGovernance.feature_count || factorGovernance.factor_count || 0)
  const snapshotDate = String(factorGovernance.trade_date_max || factorGovernance.end || '')
  const productionSnapshotMessage = String(factorGovernance.production_snapshot_message || '')
  const steps = [
    { label: '因子门禁', value: factorGateLabel(factorGateStatus), tone: factorGateStatus === 'pass' || factorGateStatus === 'warn' ? 'pass' : 'wait' },
    { label: 'testcase', value: factorGateLabel(factorTestcaseStatus), tone: factorTestcaseStatus === 'pass' ? 'pass' : 'wait' },
    { label: '策略签名', value: factorGateLabel(factorArenaSpecStatus), tone: factorArenaSpecStatus === 'pass' ? 'pass' : 'wait' },
    { label: '当前冠军版本', value: hasChampion ? '已有' : '缺失', tone: hasChampion ? 'pass' : 'wait' },
    { label: '买入截面', value: latestDate ? dateLabel(latestDate) : '等待', tone: latestDate && !recommendationStale ? 'pass' : 'wait' }
  ]
  if (factorSnapshotRunning) {
    return {
      tone: 'running',
      title: '因子快照生成中',
      message: runStatusMessage(factorSnapshotStatus) || '数据更新后的因子截面正在写入，训练和推理会先锁住',
      action: '',
      steps
    }
  }
  if (!factorSnapshotReady) {
    return {
      tone: 'blocked',
      title: '先完成数据更新和因子快照',
      message: productionSnapshotMessage || (snapshotDate ? `${dateLabel(snapshotDate)} 快照未通过生产签名，当前 ${numberText(rowCount)} 行 / ${numberText(factorCount)} 因子` : '缺少通用策略生产因子快照，请到数据管理运行全部/基础/行情更新'),
      action: 'data',
      steps
    }
  }
  if (!hasChampion) {
    return {
      tone: 'blocked',
      title: '等待通用策略冠军版本',
      message: '因子快照已就绪，可以进入通用策略训练页创建训练任务，训练成功后才会产生买入清单',
      action: '',
      steps
    }
  }
  if (recommendationStale) {
    return {
      tone: 'blocked',
      title: '买入截面落后市场数据',
      message: `市场数据 ${dateLabel(marketDate)}，买入清单 ${dateLabel(latestDate)}。请重新推理到最新截面后再看执行股数`,
      action: '',
      steps
    }
  }
  return {
    tone: 'ready',
    title: '通用策略生产链路就绪',
    message: `${dateLabel(snapshotDate || latestDate)} 因子快照可用，冠军版本和买入截面处于同一生产链路`,
    action: '',
    steps
  }
}

function arenaTaskProgressSignals(task: TaskDTO) {
  const stage = String(task.summary?.stage || task.summary?.current_stage || task.subtask_key || '').trim()
  const name = String(task.summary?.name || task.subtask_name || '').trim()
  const message = String(task.summary?.message || '').trim()
  const combined = `${stage} ${name} ${message}`.toLowerCase()
  const observability = parseJSONRecord(task.summary?.observability)
  const capacityObs = parseJSONRecord(observability.capacity)
  const portfolioObs = parseJSONRecord(observability.portfolio_risk)
  const hardGateObs = parseJSONRecord(observability.hard_gate)
  const stageLabel = name || stage || '等待进度'
  const messageLabel = message || taskStatusMessage(task)
  const capacityStatus = extractStatusToken(message, 'status')
  const failCount = extractNumberToken(message, 'fail')
  const warnCount = extractNumberToken(message, 'warn')
  const capacityPassCount = extractNumberToken(message, 'capacity_pass')
  const capacityWarnCount = extractNumberToken(message, 'capacity_warn')
  const capacityFailCount = extractNumberToken(message, 'capacity_fail')
  const portfolioStatus = extractStatusToken(message, 'portfolio_status')
  const portfolioFailCount = extractNumberToken(message, 'portfolio_fail')
  const portfolioWarnCount = extractNumberToken(message, 'portfolio_warn')
  const gatePassCount = extractNumberToken(message, 'gate_pass')
  const gateFailCount = extractNumberToken(message, 'gate_fail')
  const buyPlan = extractStatusToken(message, 'buy_plan')
  const hasCapacitySummary = hasProgressToken(message, 'capacity_pass') || hasProgressToken(message, 'capacity_warn') || hasProgressToken(message, 'capacity_fail')
  const hasGateSummary = hasProgressToken(message, 'gate_pass') || hasProgressToken(message, 'gate_fail')
  let capacityLabel = '等待容量门禁'
  let capacityTone = ''
  if (Object.keys(capacityObs).length > 0) {
    const pass = Number(capacityObs.pass_count || 0)
    const warn = Number(capacityObs.warn_count || 0)
    const fail = Number(capacityObs.fail_count || 0)
    capacityLabel = `通过 ${numberText(pass)} / 警告 ${numberText(warn)} / 失败 ${numberText(fail)}`
    capacityTone = fail > 0 ? 'bad' : 'good'
  } else if (hasCapacitySummary) {
    capacityLabel = `通过 ${numberText(capacityPassCount)} / 警告 ${numberText(capacityWarnCount)} / 失败 ${numberText(capacityFailCount)}`
    capacityTone = capacityFailCount > 0 ? 'bad' : 'good'
  } else if (combined.includes('capacity_gate') || combined.includes('容量')) {
    capacityLabel = gateStatusDisplay(capacityStatus, failCount, warnCount)
    capacityTone = capacityStatusTone(capacityStatus, failCount)
  } else if (buyPlan === 'ready') {
    capacityLabel = '通过 · 买入计划就绪'
    capacityTone = 'good'
  } else if (buyPlan === 'partial_capacity') {
    capacityLabel = '警告 · 买入计划部分可用'
  } else if (buyPlan === 'blocked_by_capacity') {
    capacityLabel = '失败 · 买入计划被容量阻断'
    capacityTone = 'bad'
  }
  let riskLabel = '等待组合预算'
  let riskTone = ''
  if (Object.keys(portfolioObs).length > 0) {
    const status = String(portfolioObs.status || '')
    const fail = Number(portfolioObs.fail_count || 0)
    const warn = Number(portfolioObs.warn_count || 0)
    riskLabel = gateStatusDisplay(status, fail, warn)
    riskTone = capacityStatusTone(status, fail)
  } else if (Object.keys(hardGateObs).length > 0) {
    const pass = Number(hardGateObs.pass_count || 0)
    const fail = Number(hardGateObs.fail_count || 0)
    const gatePrefix = hardGateObs.final === true ? '硬门禁' : '累计硬门禁'
    riskLabel = `${gatePrefix}通过 ${numberText(pass)} / 淘汰 ${numberText(fail)}`
    riskTone = fail > 0 ? 'bad' : 'good'
  } else if (portfolioStatus) {
    riskLabel = gateStatusDisplay(portfolioStatus, portfolioFailCount, portfolioWarnCount)
    riskTone = capacityStatusTone(portfolioStatus, portfolioFailCount)
  } else if (hasGateSummary) {
    const gatePrefix = stage === 'done' ? '硬门禁' : '累计硬门禁'
    riskLabel = `${gatePrefix}通过 ${numberText(gatePassCount)} / 淘汰 ${numberText(gateFailCount)}`
    riskTone = gateFailCount > 0 ? 'bad' : 'good'
  } else if (combined.includes('portfolio_risk_gate') || combined.includes('组合风险') || combined.includes('组合预算')) {
    riskLabel = gateStatusDisplay(capacityStatus, failCount, warnCount)
    riskTone = capacityStatusTone(capacityStatus, failCount)
  } else if (buyPlan === 'ready' || buyPlan === 'partial_capacity' || buyPlan === 'blocked_by_capacity') {
    riskLabel = '通过 · 未阻断买入计划'
    riskTone = 'good'
  } else if (buyPlan === 'blocked_by_portfolio_risk') {
    riskLabel = '失败 · 买入计划被组合风险阻断'
    riskTone = 'bad'
  }
  const structuredBuyPlan = String(observability.buy_plan_status || '')
  const buyPlanLabel = structuredBuyPlan ? `买入计划 ${buyPlanStatusLabel(structuredBuyPlan)}` : buyPlan ? `买入计划 ${buyPlanStatusLabel(buyPlan)}` : '等待买入计划状态'
  const taskStatus = String(task.status || '').toLowerCase()
  const stageTone = taskStatus === 'failed' || taskStatus === 'error' || taskStatus === 'interrupted' || taskStatus === 'cancelled' || combined.includes('任务失败')
    ? 'bad'
    : taskStatus === 'success' || taskStatus === 'done' || combined.includes('done') || combined.includes('完成')
      ? 'good'
      : ''
  return { stageLabel, messageLabel, capacityLabel, capacityTone, riskLabel, riskTone, buyPlanLabel, stageTone }
}

function ArenaTaskProgress({ task }: { task: TaskDTO }) {
  const progress = taskProgressPct(task)
  const progressSignals = arenaTaskProgressSignals(task)
  return (
    <section className="detailCard compactRunCard">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">运行任务</div>
          <h3>{task.name}</h3>
        </div>
        <span>{statusLabel(task.status)} · {progress}%</span>
      </div>
      <div className="progressTrack"><div style={{ width: `${progress}%` }} /></div>
      <div className="cardHint">{task.subtask_name || task.subtask_key || taskStatusMessage(task)}</div>
      <div className="metricStrip">
        <div className={`metricCard ${progressSignals.stageTone}`}><span>当前阶段</span><b>{progressSignals.stageLabel}</b><em>{progressSignals.messageLabel}</em></div>
        <div className={`metricCard ${progressSignals.capacityTone}`}><span>容量信号</span><b>{progressSignals.capacityLabel}</b><em>每日买入{ARENA_DAILY_BUY_BUDGET_LABEL} · 目标≤{ARENA_TARGET_PARTICIPATION_LABEL} / 上限≤{ARENA_MAX_PARTICIPATION_LABEL}</em></div>
        <div className={`metricCard ${progressSignals.riskTone}`}><span>组合预算</span><b>{progressSignals.riskLabel}</b><em>{progressSignals.buyPlanLabel}</em></div>
      </div>
      <div className="recommendationMeta">
        {task.worker_pid ? `PID ${task.worker_pid}` : '等待进程号'} · {task.log_path ? shortPath(task.log_path) : '日志待创建'}
      </div>
    </section>
  )
}

function ArenaGateDiagnosticsPanel({ failures, hasChampion }: { failures: Array<Record<string, unknown>>, hasChampion: boolean }) {
  if (!hasChampion) {
    return (
      <div className="modelChecklist">
        <div><Activity size={16} /><span>等待冠军版本产生后展示硬门禁诊断；当前没有可复验的通用策略版本。</span></div>
      </div>
    )
  }
  if (failures.length === 0) {
    return (
      <div className="modelChecklist">
        <div><CheckCircle2 size={16} /><span>硬门禁暂无失败项，当前冠军版本没有被容量、组合预算或收益稳定性门禁挡下。</span></div>
      </div>
    )
  }
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            <th>失败门禁</th>
            <th>淘汰数</th>
            <th>占比</th>
            <th>典型配置</th>
            <th>关键证据</th>
          </tr>
        </thead>
        <tbody>
          {failures.slice(0, 6).map((failure) => {
            const examples = Array.isArray(failure.examples) ? failure.examples : []
            const first = parseJSONRecord(examples[0])
            return (
              <tr key={String(failure.name || failure.label)}>
                <td><b>{String(failure.label || failure.name || '未知门禁')}</b><div className="mutedText">{String(failure.name || '')}</div></td>
                <td>{numberText(Number(failure.count || 0))}</td>
                <td>{pct(Number(failure.ratio || 0))}</td>
                <td>{gateExampleConfig(first)}</td>
                <td>{gateExampleEvidence(String(failure.name || ''), first)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function FactorGovernancePanel({ governance, gate, drift, task, status, onOpenData }: { governance: FactorStoreGovernance, gate: Record<string, unknown>, drift: Record<string, unknown>, task?: TaskDTO, status?: RunStatus, onOpenData?: () => void }) {
  const gateStatus = String(gate.status || governance.status || 'missing')
  const driftStatus = String(drift.status || 'missing')
  const artifactPaths = parseJSONRecord(governance.artifact_paths)
  const freshness = parseJSONRecord(governance.snapshot_freshness)
  const arenaSpec = parseJSONRecord(governance.profit_arena_spec)
  const factorCount = Number(governance.feature_count ?? governance.factor_count ?? 0)
  const rowCount = Number(governance.row_count ?? 0)
  const freshStatus = String(freshness.status || governance.snapshot_fresh_status || 'missing')
  const specStatus = String(arenaSpec.status || 'missing')
  const specFailed = specStatus === 'fail'
  const expectedDate = String(freshness.expected || governance.expected_trade_date || '')
  const actualDate = String(freshness.actual || governance.trade_date_max || governance.end || '')
  const statusRunning = status?.state === 'running'
  const taskRunning = Boolean(task && isActiveTask(task))
  const snapshotMissing = gateStatus === 'missing' && freshStatus === 'missing' && specStatus === 'missing' && rowCount === 0 && factorCount === 0
  const statusProgress = runStatusProgressPct(status)
  const progress = task ? taskProgressPct(task) : statusProgress
  const statusText = task ? statusLabel(task.status) : status ? statusLabel(status.state) : '当前空闲'
  const statusMessage = task ? taskStatusMessage(task) : status ? runStatusMessage(status) : snapshotMissing ? '请先在数据管理执行数据更新，成功后自动生成因子快照' : `manifest ${shortPath(String(governance.manifest_path || '')) || '未生成'}`
  const snapshotObservability = factorSnapshotObservability(task, statusMessage)
  const progressText = taskRunning || statusRunning || progress > 0 ? `${statusText} ${progress}%` : statusText
  return (
    <>
      <div className="metricStrip">
        <div className={`metricCard ${gateStatus === 'pass' ? 'good' : gateStatus === 'fail' ? 'bad' : ''}`}>
          <span>因子门禁</span>
          <b>{factorGateLabel(gateStatus)}</b>
          <em>{gateSummaryText(gate)}</em>
        </div>
        <div className={`metricCard ${driftStatus === 'pass' ? 'good' : driftStatus === 'warn' ? 'bad' : ''}`}>
          <span>因子漂移</span>
          <b>{factorGateLabel(driftStatus)}</b>
          <em>{Object.keys(drift).length > 0 ? `warn ${numberText(drift.warn_count)} · new ${numberText(drift.new_factor_count)}` : '等待漂移基线'}</em>
        </div>
        <div className={`metricCard ${freshStatus === 'pass' ? 'good' : freshStatus === 'fail' ? 'bad' : ''}`}>
          <span>快照覆盖</span>
          <b>{actualDate ? dateLabel(actualDate) : '—'}</b>
          <em>{snapshotMissing ? '等待因子快照生成' : `${factorGateLabel(freshStatus)} · 目标 ${dateLabel(expectedDate)} · ${numberText(rowCount)} 行 · ${numberText(factorCount)} 因子`}</em>
        </div>
        <div className={`metricCard ${specStatus === 'pass' ? 'good' : specStatus === 'fail' ? 'bad' : ''}`}>
          <span>策略签名</span>
          <b>{factorGateLabel(specStatus)}</b>
          <em>{String(arenaSpec.message || '等待因子快照签名校验')}</em>
        </div>
        <div className={`metricCard ${taskRunning || statusRunning ? 'good' : ''}`}>
          <span>快照任务</span>
          <b>{task || status ? progressText : '当前空闲'}</b>
          <em>{statusMessage}</em>
        </div>
        <div className="metricCard">
          <span>快照日志</span>
          <b>{status?.worker_pid ? `PID ${status.worker_pid}` : task?.worker_pid ? `PID ${task.worker_pid}` : snapshotMissing ? '未启动' : '等待进程号'}</b>
          <em>{task?.log_path ? shortPath(task.log_path) : status?.updated_at ? `更新 ${status.updated_at}` : snapshotMissing ? '数据管理页触发更新' : '等待任务启动'}</em>
        </div>
        <div className="metricCard">
          <span>审计产物</span>
          <b>{snapshotMissing ? '—' : numberText(Object.keys(artifactPaths).length)}</b>
          <em>{shortPath(String(governance.latest_meta_path || governance.path || snapshotObservability.manifest || '')) || (snapshotMissing ? '等待数据更新生成' : '等待快照')}</em>
        </div>
        {snapshotObservability.ready ? (
          <div className={`metricCard ${snapshotObservability.quality === 'pass' ? 'good' : snapshotObservability.quality === 'fail' ? 'bad' : ''}`}>
            <span>运行摘要</span>
            <b>{snapshotObservabilitySummary(snapshotObservability)}</b>
            <em>{snapshotObservabilityMeta(snapshotObservability)}</em>
          </div>
        ) : null}
      </div>
      {(snapshotMissing || specFailed) && onOpenData ? (
        <div className="modelChecklist">
          <div className="snapshotActionHint">
            <Activity size={16} />
            <span>{snapshotMissing ? '通用策略训练依赖因子快照。先到数据管理执行数据更新，成功后会自动生成最新因子截面。' : '通用策略因子快照签名未通过。请到数据管理运行全部/基础/行情更新，等待后置因子截面任务成功后再训练或推理。'}</span>
            <button className="secondaryButton quietButton" onClick={onOpenData}>去数据管理</button>
          </div>
        </div>
      ) : null}
    </>
  )
}

function parseArenaSummary(run?: ProfitArenaRunSummary): ArenaSummaryPayload {
  if (!run?.summary_json) return {}
  try {
    const parsed = JSON.parse(run.summary_json) as ArenaSummaryPayload
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function parseJSONRecord(value?: unknown): Record<string, unknown> {
  if (!value) return {}
  if (typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
  const text = String(value)
  try {
    const parsed = JSON.parse(text)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

function factorGateLabel(status: string) {
  if (status === 'pass') return '通过'
  if (status === 'warn') return '警告'
  if (status === 'fail') return '失败'
  if (status === 'missing') return '等待'
  return status || '-'
}

function gateSummaryText(gate: Record<string, unknown>) {
  if (Object.keys(gate).length === 0) return '等待快照'
  const failed = Array.isArray(gate.failed_checks) ? gate.failed_checks.length : 0
  const warned = Array.isArray(gate.warn_checks) ? gate.warn_checks.length : 0
  if (failed > 0) return `fail ${failed} · warn ${warned}`
  return `warn ${warned}`
}

function shortPath(path: string) {
  if (!path) return ''
  return path.length > 42 ? `…${path.slice(-42)}` : path
}

function bestEvaluation(rows: ProfitArenaEvaluation[]) {
  return rows.reduce<ProfitArenaEvaluation | null>((best, row) => {
    const score = row.capital_annual_return || row.annual_return || 0
    const bestScore = best ? best.capital_annual_return || best.annual_return || 0 : Number.NEGATIVE_INFINITY
    return score > bestScore ? row : best
  }, null)
}

function runScore(run?: ProfitArenaRunSummary) {
  const summary = parseArenaSummary(run)
  const raw = summary.best_challenger_score_components?.raw || {}
  const best = summary.best || {}
  const annual = Number(raw.capital_annual_return ?? best.capital_annual_return ?? 0)
  const drawdown = Number(raw.capital_max_drawdown ?? best.capital_max_drawdown ?? 0)
  const rankIC = Number(raw.rank_ic ?? best.rank_ic ?? 0)
  const sharpe = Number(raw.capital_sharpe ?? best.capital_sharpe ?? 0)
  const calmar = drawdown < 0 ? annual / Math.abs(drawdown) : annual > 0 ? annual / 1e-9 : 0
  return {
    score: currentArenaScore(annual, drawdown, rankIC, sharpe),
    annual,
    drawdown,
    calmar,
    rankIC,
    sharpe
  }
}

function currentArenaScore(annual: number, drawdown: number, rankIC: number, sharpe: number) {
  const calmar = drawdown < 0 ? annual / Math.abs(drawdown) : annual > 0 ? annual / 1e-9 : 0
  return annualBucketScore(annual) * 0.40
    + calmarBucketScore(calmar) * 0.30
    + rankICBucketScore(rankIC) * 0.20
    + sharpeBucketScore(sharpe) * 0.10
}

function annualBucketScore(annual: number) {
  if (annual < 0.05) return 0
  if (annual < 0.10) return 20
  if (annual < 0.15) return 40
  if (annual < 0.20) return 60
  if (annual < 0.30) return 80
  if (annual < 0.40) return 90
  if (annual <= 0.60) return 95
  return 100
}

function calmarBucketScore(calmar: number) {
  if (calmar < 0.5) return 0
  if (calmar < 1.0) return 30
  if (calmar < 1.5) return 60
  if (calmar < 2.0) return 80
  if (calmar < 2.5) return 90
  if (calmar < 3.0) return 95
  return 100
}

function rankICBucketScore(rankIC: number) {
  if (rankIC < 0.01) return 0
  if (rankIC < 0.03) return 30
  if (rankIC < 0.05) return 50
  if (rankIC < 0.08) return 70
  if (rankIC < 0.10) return 85
  if (rankIC < 0.12) return 95
  return 100
}

function sharpeBucketScore(sharpe: number) {
  if (sharpe < 0.5) return 0
  if (sharpe < 1.0) return 40
  if (sharpe < 1.2) return 60
  if (sharpe < 1.5) return 75
  if (sharpe < 2.0) return 90
  return 100
}

function compareArenaRuns(a: ProfitArenaRunSummary, b: ProfitArenaRunSummary) {
  const left = runScore(a)
  const right = runScore(b)
  return (
    right.score - left.score ||
    right.annual - left.annual ||
    right.rankIC - left.rankIC ||
    right.sharpe - left.sharpe ||
    right.drawdown - left.drawdown
  )
}

function rawMetric(run: ProfitArenaRunSummary | undefined, key: string) {
  const summary = parseArenaSummary(run)
  const raw = summary.best_challenger_score_components?.raw || {}
  const best = summary.best || {}
  return Number((raw as Record<string, unknown>)[key] ?? best[key] ?? 0)
}

function arenaCapacitySummary(summary: ArenaSummaryPayload): Record<string, unknown> {
  const capacity = parseJSONRecord((summary as Record<string, unknown>).capacity)
  const best = parseJSONRecord(capacity.best_challenger)
  const bestSummary = parseJSONRecord(best.summary)
  return {
    status: String(bestSummary.status || 'missing'),
    max_participation_rate: Number(bestSummary.max_participation_rate || 0),
    max_estimated_impact_bps: Number(bestSummary.max_estimated_impact_bps || 0),
    fail_count: Number(bestSummary.fail_count || 0),
    warn_count: Number(bestSummary.warn_count || 0)
  }
}

function arenaPortfolioRiskSummary(summary: ArenaSummaryPayload): Record<string, unknown> {
  const risk = parseJSONRecord((summary as Record<string, unknown>).portfolio_risk)
  const best = parseJSONRecord(risk.best_challenger || risk.latest_inference)
  const bestSummary = parseJSONRecord(best.summary)
  return {
    status: String(bestSummary.status || 'missing'),
    fail_count: Number(bestSummary.fail_count || 0),
    warn_count: Number(bestSummary.warn_count || 0),
    max_single_weight: Number(bestSummary.max_single_weight || 0),
    max_industry_weight: Number(bestSummary.max_industry_weight || 0),
    max_size_bucket_weight: Number(bestSummary.max_size_bucket_weight || 0),
    max_avg_crash_prob: Number(bestSummary.max_avg_crash_prob || 0),
    capacity_fail_count: Number(bestSummary.capacity_fail_count || 0)
  }
}

function arenaGateSummary(summary: ArenaSummaryPayload) {
  const gate = parseJSONRecord(summary.gate_summary)
  const failures = Array.isArray(gate.top_failures) ? gate.top_failures : []
  const primary = parseJSONRecord(failures[0])
  const tradable = Number(gate.tradable_evaluations || 0)
  const passCount = Number(gate.hard_gate_pass_count || 0)
  const failCount = Number(gate.hard_gate_fail_count || 0)
  return {
    tradable_count: tradable,
    pass_count: passCount,
    fail_count: failCount,
    pass_ratio: Number(gate.hard_gate_pass_ratio || 0),
    primary_label: String(primary.label || ''),
    primary_count: Number(primary.count || 0),
    primary_ratio: Number(primary.ratio || 0)
  }
}

function arenaGateFailures(summary: ArenaSummaryPayload): Array<Record<string, unknown>> {
  const gate = parseJSONRecord(summary.gate_summary)
  const failures = Array.isArray(gate.top_failures) ? gate.top_failures : []
  return failures.map(parseJSONRecord).filter((item) => Number(item.count || 0) > 0)
}

function arenaEvaluationGate(row: ProfitArenaEvaluation) {
  const payload = parseJSONRecord(row.summary_json)
  const gate = parseJSONRecord(payload.gate_diagnostics)
  const labels = Array.isArray(gate.labels) ? gate.labels.map((item) => String(item)).filter(Boolean) : []
  const failures = Array.isArray(gate.failures) ? gate.failures.map((item) => String(item)).filter(Boolean) : []
  const ok = Boolean(gate.hard_gate_ok ?? failures.length === 0)
  const details = parseJSONRecord(gate.details)
  const firstFailure = failures[0] || ''
  const firstDetail = parseJSONRecord(details[firstFailure])
  let detail = ''
  if (firstFailure === 'capacity_gate') {
    detail = `参与率 ${pct(Number(firstDetail.max_participation_rate || 0))} · 冲击 ${decimalText(Number(firstDetail.max_estimated_impact_bps || 0), 1)}bps`
  } else if (firstFailure === 'portfolio_risk_gate') {
    detail = `单票 ${pct(Number(firstDetail.max_single_weight || 0))} · 行业 ${pct(Number(firstDetail.max_industry_weight || 0))} · 闪崩 ${pct(Number(firstDetail.max_avg_crash_prob || 0))}`
  } else if (firstDetail.value !== undefined || firstDetail.threshold !== undefined) {
    detail = `实际 ${formatGateValue(firstFailure, firstDetail.value)} / 门槛 ${formatGateValue(firstFailure, firstDetail.threshold)}`
  }
  return {
    ok,
    text: ok ? '硬门禁通过' : labels.slice(0, 3).join(' / ') || failures.slice(0, 3).join(' / ') || '硬门禁失败',
    detail
  }
}

function arenaEvaluationRuleLabel(row: ProfitArenaEvaluation) {
  return `${arenaScopeLabel(row.scope)} · Top${numberText(row.top_n)}`
}

function arenaScopeLabel(scope: string) {
  if (scope === 'small') return '小盘池'
  if (scope === 'mid') return '中盘池'
  if (scope === 'large') return '大盘池'
  if (scope === 'all') return '全市场'
  return scope || '默认池'
}

function gateExampleConfig(example: Record<string, unknown>) {
  const scope = String(example.scope || '-')
  const horizon = numberText(Number(example.horizon || 0))
  const topN = numberText(Number(example.top_n || 0))
  const segment = String(example.segment || '-')
  const fraction = Number(example.capital_tranche_fraction || 0)
  return `${scope} / Top${topN} / ${horizon}日 / ${segment} / 仓位 ${pct(fraction)}`
}

function gateExampleEvidence(name: string, example: Record<string, unknown>) {
  if (!example || Object.keys(example).length === 0) return '暂无生产样本'
  if (name === 'capacity_gate') {
    return `容量 ${String(example.capacity_status || '-')} · 参与率 ${pct(Number(example.capacity_max_participation_rate || 0))}`
  }
  if (name === 'portfolio_risk_gate') {
    return `组合 ${String(example.portfolio_risk_status || '-')} · 最差值 ${pct(Number(example.portfolio_risk_worst_value || 0))}`
  }
  if (name.includes('rank_ic')) return `RankIC ${decimalText(Number(example.rank_ic || 0), 4)}`
  if (name.includes('drawdown')) return `最大回撤 ${pct(Number(example.capital_max_drawdown || 0))}`
  if (name.includes('return')) return `年化 ${pct(Number(example.capital_annual_return || 0))}`
  return `年化 ${pct(Number(example.capital_annual_return || 0))} · 回撤 ${pct(Number(example.capital_max_drawdown || 0))} · RankIC ${decimalText(Number(example.rank_ic || 0), 4)}`
}

function formatGateValue(name: string, value: unknown) {
  const num = Number(value || 0)
  if (name.includes('rank_ic')) return decimalText(num, 4)
  if (name.includes('return') || name.includes('drawdown')) return pct(num)
  if (name.includes('sharpe')) return decimalText(num, 2)
  return numberText(num)
}

function arenaExecutionConfig(evalRow?: ProfitArenaEvaluation | null, run?: ProfitArenaRunSummary): ArenaExecutionConfig {
  const payload = parseJSONRecord(evalRow?.summary_json)
  const topN = Math.max(1, Math.round(Number(payload.top_n ?? evalRow?.top_n ?? run?.best_top_n ?? 3)))
  const horizon = Math.max(1, Math.round(Number(payload.horizon ?? evalRow?.horizon ?? run?.best_horizon ?? 20)))
  const capitalFractionRaw = Number(payload.capital_tranche_fraction ?? 1)
  const capitalFraction = Number.isFinite(capitalFractionRaw) && capitalFractionRaw > 0
    ? Math.min(1, capitalFractionRaw)
    : 1 / horizon
  return {
    topN,
    horizon,
    maxCrashProb: Number(payload.max_crash_prob ?? 999),
    takeProfit: Math.max(0, Number(payload.execution_take_profit ?? 0)),
    stopLoss: Math.max(0, Number(payload.execution_stop_loss ?? 0)),
    positionWeighting: String(payload.position_weighting || 'equal'),
    capitalFraction
  }
}

function arenaPlan(row: ProfitArenaPrediction, index: number, config: ArenaExecutionConfig, topRows: ProfitArenaPrediction[]) {
  const price = Number(row.price)
  const hasPrice = Number.isFinite(price) && price > 0
  const buy = hasPrice ? price : Number.NaN
  const sell = hasPrice && config.takeProfit > 0 ? price * (1 + config.takeProfit) : Number.NaN
  const stop = hasPrice && config.stopLoss > 0 ? price * (1 - config.stopLoss) : Number.NaN
  const weight = arenaPositionWeight(row, topRows, config, index)
  const capacity = arenaCapacity(row, weight)
  const shares = hasPrice && capacity.status !== 'fail' ? roundLotShares(buy, ARENA_DAILY_BUY_BUDGET * weight) : 0
  return {
    buyLabel: hasPrice ? `¥${moneyText(buy)}` : '截面价缺失',
    sellLabel: hasPrice && config.takeProfit > 0 ? `¥${moneyText(sell)}` : '按持有期退出',
    stopLabel: hasPrice && config.stopLoss > 0 ? `¥${moneyText(stop)}` : '无硬止损',
    weightLabel: pct(weight),
    capitalScaleLabel: capitalScaleLabel(row),
    shares,
    ...capacity
  }
}

function arenaCapacity(row: ProfitArenaPrediction, weight: number) {
  const summary = parseJSONRecord(row.summary_json)
  const storedParticipation = Number(summary.capacity_participation_rate)
  const storedImpact = Number(summary.capacity_impact_bps)
  const storedStatus = String(summary.capacity_status || '')
  const dailyAmount = Number(row.amount || 0) * ARENA_AMOUNT_UNIT
  const orderNotional = ARENA_DAILY_BUY_BUDGET * Math.max(0, weight)
  const participation = Number.isFinite(storedParticipation) && storedParticipation > 0
    ? storedParticipation
    : dailyAmount > 0 ? orderNotional / dailyAmount : 0
  const impactBps = Number.isFinite(storedImpact) && storedImpact > 0
    ? storedImpact
    : ARENA_IMPACT_BPS_COEFFICIENT * Math.sqrt(Math.max(0, participation))
  const status = storedStatus || (dailyAmount <= 0 ? 'fail' : participation > ARENA_MAX_PARTICIPATION ? 'fail' : participation > ARENA_TARGET_PARTICIPATION ? 'warn' : 'pass')
  return {
    status,
    participationLabel: pct(participation),
    impactLabel: `${decimalText(impactBps, 1)} bps`,
    capacityLabel: dailyAmount > 0 ? `日额 ${largeMoneyText(dailyAmount)} / 可承载 ${largeMoneyText(dailyAmount * ARENA_MAX_PARTICIPATION)}` : '成交额缺失',
    capacityStatusLabel: status === 'pass' ? '容量通过' : status === 'warn' ? '容量警告' : '容量失败',
    capacityTone: status === 'pass' ? 'positive' : status === 'warn' ? '' : 'negative'
  }
}

function predictionCapacityStatus(row: ProfitArenaPrediction) {
  const summary = parseJSONRecord(row.summary_json)
  const status = String(summary.capacity_status || '').toLowerCase()
  if (status) return status
  const participation = Number(summary.capacity_participation_rate || 0)
  if (participation > ARENA_MAX_PARTICIPATION) return 'fail'
  if (participation > ARENA_TARGET_PARTICIPATION) return 'warn'
  return ''
}

function predictionPortfolioRiskStatus(row: ProfitArenaPrediction) {
  const summary = parseJSONRecord(row.summary_json)
  const status = String(summary.portfolio_risk_status || '').toLowerCase()
  return status === 'pass' || status === 'warn' || status === 'fail' ? status : ''
}

function predictionBuyPlanStatus(row: ProfitArenaPrediction) {
  const summary = parseJSONRecord(row.summary_json)
  return String(summary.buy_plan_status || '').toLowerCase()
}

function predictionIsBuyCandidate(row: ProfitArenaPrediction) {
  const summary = parseJSONRecord(row.summary_json)
  if (!Object.prototype.hasOwnProperty.call(summary, 'is_buy_candidate')) return true
  return Number(summary.is_buy_candidate || 0) > 0
}

function predictionBuyPlanLabel(row: ProfitArenaPrediction) {
  const summary = parseJSONRecord(row.summary_json)
  const status = String(summary.buy_plan_status || '').toLowerCase()
  const reason = buyPlanReasonLabel(String(summary.buy_plan_reason || ''))
  if (status === 'ready') return '买入计划 ready'
  if (status === 'partial_capacity') return `买入计划部分可用${reason ? ` · ${reason}` : ''}`
  if (status === 'blocked_by_capacity') return `买入计划容量阻断${reason ? ` · ${reason}` : ''}`
  if (status === 'blocked_by_portfolio_risk') return `买入计划组合风险阻断${reason ? ` · ${reason}` : ''}`
  if (status === 'missing') return '买入计划状态缺失'
  return '买入计划按通用策略门禁'
}

function buyPlanReasonLabel(reason: string) {
  if (reason === 'portfolio_risk_gate_failed') return '组合风险预算失败'
  if (reason === 'no_capacity_tradable_candidates') return '无容量可交易买入项'
  if (reason === 'capacity_tradable_candidates_below_top_n') return '容量可交易数不足TopN'
  if (reason === 'missing_target_count') return '目标数量缺失'
  return reason
}

function roundLotShares(price: number, cash: number) {
  if (!Number.isFinite(price) || price <= 0 || !Number.isFinite(cash) || cash <= 0) return 0
  return Math.floor(cash / price / 100) * 100
}

function arenaPositionWeight(row: ProfitArenaPrediction, rows: ProfitArenaPrediction[], config: ArenaExecutionConfig, index: number) {
  const capital = Math.max(0, Math.min(1, config.capitalFraction || 1))
  const summary = parseJSONRecord(row.summary_json)
  const storedWeight = Number(summary.position_weight || 0)
  const storedScale = Number(summary.capital_scale ?? 1)
  if (storedWeight > 0) {
    const scale = Math.max(0, Math.min(1, Number.isFinite(storedScale) ? storedScale : 1))
    return capital * storedWeight * scale
  }
  if (rows.length === 0) return 0
  if (config.positionWeighting === 'equal') return capital / rows.length
  const scores = rows.map((item) => Math.max(0, Number(item.model_score) || 0))
  const total = scores.reduce((sum, value) => sum + value, 0)
  if (total <= 0) return capital / rows.length
  let weight = capital * (Math.max(0, Number(row.model_score) || 0) / total)
  if (config.positionWeighting === 'score_cap50') {
    weight = Math.min(weight, 0.5)
  }
  if (!Number.isFinite(weight) || weight <= 0) return capital / rows.length
  return weight
}

function capitalScaleLabel(row: ProfitArenaPrediction) {
  const summary = parseJSONRecord(row.summary_json)
  const scale = Number(summary.capital_scale)
  if (!Number.isFinite(scale) || scale <= 0 || scale >= 0.999) return '资金缩放 100%'
  return `资金缩放 ${pct(scale)}`
}

function numberText(value: unknown) {
  const n = Number(value)
  return Number.isFinite(n) ? n.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) : '-'
}

function moneyText(value: unknown) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return '-'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function largeMoneyText(value: unknown) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return '-'
  if (n >= 100000000) return `${(n / 100000000).toFixed(2)}亿`
  if (n >= 10000) return `${(n / 10000).toFixed(2)}万`
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

function priceText(value: unknown) {
  const text = moneyText(value)
  return text === '-' ? '缺失' : `¥${text}`
}

function decimalText(value: unknown, digits = 2) {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(digits) : '-'
}

function pct(value: unknown, digits = 2) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return `${n > 0 ? '+' : ''}${(n * 100).toFixed(digits)}%`
}

function dateLabel(value?: string) {
  if (!value) return '-'
  if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(0, 10)
  return value
}

function normalizeDateKey(value?: string) {
  if (!value) return ''
  const text = String(value)
  if (/^\d{8}$/.test(text)) return text
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 10).replace(/-/g, '')
  return text.replace(/-/g, '').slice(0, 8)
}

function dateTimeLabel(value?: string) {
  if (!value) return '-'
  if (/^\d{8}$/.test(value)) return dateLabel(value)
  return value.replace('T', ' ').replace(/\.\d+Z?$/, '').slice(0, 16) || value
}

function shortRunID(runID: string) {
  if (!runID) return ''
  return runID.length > 28 ? `${runID.slice(0, 12)}…${runID.slice(-8)}` : runID
}

function statusLabel(status: string) {
  return {
    idle: '空闲',
    created: '待启动',
    queued: '排队中',
    running: '运行中',
    success: '完成',
    done: '完成',
    error: '失败',
    failed: '失败',
    cancelled: '取消',
    interrupted: '中断',
    skipped: '已跳过',
    historical_offline: '已归档'
  }[status] || status || '-'
}

function statusBadgeClass(status: string) {
  if (status === 'success' || status === 'done' || status === 'pass') return 'success'
  if (status === 'running' || status === 'queued' || status === 'created' || status === 'warn') return 'running'
  if (status === 'skipped' || status === 'idle' || status === '') return 'created'
  return 'failed'
}

function taskProgressPct(task: TaskDTO) {
  const pct = Number(task.progress) * 100
  if (!Number.isFinite(pct)) return 0
  return Math.max(0, Math.min(100, Math.round(pct)))
}

function runStatusProgressPct(status?: RunStatus) {
  if (!status || status.total <= 0) return 0
  const pct = (Number(status.idx || 0) / Number(status.total || 1)) * 100
  if (!Number.isFinite(pct)) return 0
  return Math.max(0, Math.min(100, Math.round(pct)))
}

function taskStatusMessage(task: TaskDTO) {
  const stage = String(task.summary?.stage || task.summary?.current_stage || '').trim()
  const name = String(task.summary?.name || task.subtask_name || task.subtask_key || '').trim()
  const message = String(task.summary?.message || task.error_message || '').trim()
  const parts = [stage, name, message].filter(Boolean)
  if (parts.length) return parts.join(' · ')
  if (task.status === 'queued' || task.status === 'created') return '等待任务启动'
  return '等待任务进度上报'
}

function extractStatusToken(message: string, key: string) {
  const match = new RegExp(`${key}=([^\\s,;]+)`).exec(message)
  return match ? match[1].trim().toLowerCase() : ''
}

function extractNumberToken(message: string, key: string) {
  const match = new RegExp(`${key}=(-?\\d+(?:\\.\\d+)?)`).exec(message)
  return match ? Number(match[1]) : 0
}

function hasProgressToken(message: string, key: string) {
  return new RegExp(`${key}=`).test(message)
}

function gateStatusDisplay(status: string, failCount: number, warnCount: number) {
  if (status === 'pass') return `通过 · fail ${numberText(failCount)} / warn ${numberText(warnCount)}`
  if (status === 'warn') return `警告 · fail ${numberText(failCount)} / warn ${numberText(warnCount)}`
  if (status === 'fail') return `失败 · fail ${numberText(failCount)} / warn ${numberText(warnCount)}`
  if (status) return `${status} · fail ${numberText(failCount)} / warn ${numberText(warnCount)}`
  return '等待门禁结果'
}

function capacityStatusTone(status: string, failCount: number) {
  if (status === 'pass') return 'good'
  if (status === 'fail' || failCount > 0) return 'bad'
  return ''
}

function buyPlanStatusLabel(status: string) {
  if (status === 'ready') return '就绪'
  if (status === 'partial_capacity') return '容量部分可用'
  if (status === 'blocked_by_capacity') return '容量阻断'
  if (status === 'blocked_by_portfolio_risk') return '组合风险阻断'
  if (status === 'missing') return '缺失'
  return status || '等待'
}

function runStatusMessage(status: RunStatus | null | undefined) {
  if (!status) return '等待任务状态上报'
  const parts = [status.stage, status.name, status.message].map((item) => String(item || '').trim()).filter(Boolean)
  if (parts.length) return parts.join(' · ')
  if (status.state === 'idle' || status.state === '') return '等待数据更新成功后自动触发'
  return '等待任务进度上报'
}

type FactorSnapshotObservabilityView = {
  ready: boolean
  rows: number
  factors: number
  quality: string
  drift: string
  manifest: string
}

function factorSnapshotObservability(task: TaskDTO | undefined, message: string): FactorSnapshotObservabilityView {
  const observability = parseJSONRecord(task?.summary?.observability)
  const structured = parseJSONRecord(observability.factor_snapshot)
  const messageRows = extractNumberToken(message, 'rows')
  const messageFactors = extractNumberToken(message, 'factors')
  const quality = String(structured.quality_status || extractValueToken(message, 'quality') || '')
  const drift = String(structured.drift_status || extractValueToken(message, 'drift') || '')
  const manifest = String(structured.manifest_path || extractValueToken(message, 'manifest') || '')
  const rows = Number(structured.row_count || messageRows || 0)
  const factors = Number(structured.factor_count || messageFactors || 0)
  return {
    ready: Boolean(rows || factors || quality || drift || manifest),
    rows,
    factors,
    quality,
    drift,
    manifest,
  }
}

function snapshotObservabilitySummary(value: FactorSnapshotObservabilityView) {
  if (value.rows > 0 && value.factors > 0) return `${numberText(value.rows)} 行 / ${numberText(value.factors)} 因子`
  if (value.rows > 0) return `${numberText(value.rows)} 行`
  if (value.factors > 0) return `${numberText(value.factors)} 因子`
  return '等待快照摘要'
}

function snapshotObservabilityMeta(value: FactorSnapshotObservabilityView) {
  const parts = [
    value.quality ? `质量 ${factorGateLabel(value.quality)}` : '',
    value.drift ? `漂移 ${factorGateLabel(value.drift)}` : '',
    value.manifest ? `manifest ${shortPath(value.manifest)}` : '',
  ].filter(Boolean)
  return parts.join(' · ') || '等待质量和漂移摘要'
}

function extractValueToken(message: string, key: string) {
  const match = new RegExp(`${key}=([^\\s,;]+)`).exec(message)
  return match ? match[1].trim() : ''
}

function featureLabel(value: string) {
  const labels: Record<string, string> = {
    ret5: '近5日收益',
    ret10: '近10日收益',
    ret20: '近20日收益',
    ret60: '近60日收益',
    turnover_rate: '换手率',
    amount_chg5: '5日成交变化',
    amount_chg20: '20日成交变化',
    volatility20: '20日波动',
    drawdown20: '20日回撤',
    circ_mv_log: '流通市值',
    pb: 'PB',
    pe_ttm: 'PE TTM',
    market_up_ratio: '市场上涨占比',
    small_up_ratio: '小盘上涨占比',
    industry_up_ratio: '行业上涨占比',
    rs_market20: '20日相对市场',
    rs_industry20: '20日相对行业'
  }
  return labels[value] || value
}
