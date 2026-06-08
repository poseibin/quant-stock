import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { getT0DailyResearchStatus, getT0TimeMachineStatus, listT0DailyBacktests, listT0DailyRuns, listT0DataPullCandidates, listT0Recommendations, listT0TimeMachineResults, runT0DailyResearch, runT0TimeMachine, type RunStatus, type T0DailyBacktest, type T0DailyRunSummary, type T0DataPullCandidate, type T0Recommendation, type T0TimeMachineResult } from '../services/app'

function money(value: number) {
  if (!Number.isFinite(value) || value === 0) return '—'
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function roundLotShares(price: number, cash: number) {
  if (!Number.isFinite(price) || price <= 0 || !Number.isFinite(cash) || cash <= 0) return 0
  return Math.floor(cash / price / 100) * 100
}

function percent(value: number, signed = false) {
  if (!Number.isFinite(value)) return '—'
  const pct = value * 100
  const sign = signed && pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
}

function amountYi(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '—'
  return `${(value / 100000).toFixed(2)}亿`
}

function signedClass(value: number) {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return ''
}

function avgNumber(values: number[]) {
  const finite = values.filter(Number.isFinite)
  return finite.length ? finite.reduce((sum, value) => sum + value, 0) / finite.length : Number.NaN
}

function formatDate(value: string) {
  if (!value) return '—'
  if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
  return value
}

function formatDateTime(value: string) {
  if (!value) return '暂无'
  if (/^\d{8}$/.test(value)) return formatDate(value)
  const normalized = value.replace('T', ' ').replace(/\.\d+Z?$/, '')
  return normalized.slice(0, 16) || value
}

type T0PlanRow = (T0DataPullCandidate | T0Recommendation) & {
  buy_price?: number
  buy_back_price?: number
  avg_amount_20d?: number
  max_t0_shares?: number
  shares?: number
  recommendation?: string
}

type T0AssistantView = 'recommend' | 'model' | 'experiment'

const t0AssistantTabs: Array<{ key: T0AssistantView; label: string }> = [
  { key: 'recommend', label: '推荐列表' },
  { key: 'model', label: '模型训练' },
  { key: 'experiment', label: '模型评估' },
]

const t0FeatureLabels = [
  '箱体位置',
  '20日振幅',
  '两边触达率',
  '单边风险',
  '成交额稳定性',
  '停手线距离',
  '趋势斜率',
  '近2月价差',
]

const t0FeatureNameMap: Record<string, string> = {
  rule_score: '规则分',
  avg_range_20d: '20日振幅',
  range_std_20d: '振幅稳定性',
  box_width_20d: '20日箱体宽度',
  box_width_60d: '60日箱体宽度',
  close_position_20d: '箱体位置',
  ma_gap_20d: '均线偏离',
  ma5_ma20_gap: '短中均线差',
  amount_ratio_20d: '量能倍率',
  return_5d: '5日收益',
  return_20d: '20日收益',
  drawdown_20d: '20日回撤',
  today_pct: '当日涨跌',
  expected_edge: '计划价差',
}

function planBand(row: T0PlanRow) {
  const band = Math.max(0.008, Math.min(0.04, row.avg_range_20d * 0.55))
  const stopBand = Math.max(0.018, Math.min(0.06, row.avg_range_20d * 0.9))
  const tRatio = Number.isFinite(row.t_ratio) && row.t_ratio > 0
    ? `${Math.round(row.t_ratio * 100)}%`
    : row.score >= 85 ? '30%' : row.score >= 72 ? '20%' : '10%'
  return {
    reduce: Number.isFinite(row.reduce_price) && row.reduce_price > 0 ? row.reduce_price : row.price * (1 + band),
    buy: Number.isFinite(row.buy_price) && (row.buy_price || 0) > 0 ? row.buy_price || 0 : Number.isFinite(row.buy_back_price) && (row.buy_back_price || 0) > 0 ? row.buy_back_price || 0 : row.price * (1 - band),
    stop: Number.isFinite(row.stop_price) && row.stop_price > 0 ? row.stop_price : row.price * (1 - stopBand),
    tRatio,
  }
}

type RecentT0Stats = {
  n_candidates: number
  start_date: string
  end_date: string
  two_sided_rate: number
  one_sided_rate: number
  stop_hit_rate: number
  sell_first_miss_rate: number
  buy_first_drawdown_rate: number
  avg_edge: number
  total_edge: number
  avg_next_range: number
}

type TimeMachineGridSummary = {
  best?: {
    lookback?: number
    eval_days?: number
    avg_combined_return?: number
    mean_avg_combined_return?: number
    worst_avg_combined_return?: number
    positive_anchor_rate?: number
    anchor_count?: number
    avg_t0_edge?: number
    mean_avg_t0_edge?: number
    win_rate?: number
    mean_win_rate?: number
    stability_score?: number
  }
  windows?: Array<{
    lookback?: number
    eval_days?: number
    anchor_count?: number
    mean_avg_combined_return?: number
    worst_avg_combined_return?: number
    positive_anchor_rate?: number
    mean_avg_t0_edge?: number
    mean_win_rate?: number
    stability_score?: number
  }>
  positive_window_rate?: number
  worst_avg_combined_return?: number
  mean_avg_combined_return?: number
  window_count?: number
}

type T0ModelFeatureImportance = {
  feature: string
  importance: number
  rank_no: number
}

type T0ModelFold = {
  year: number
  rows: number
  positive_rate: number
  top10_two_sided: number
  top10_avg_edge: number
  top10_total_edge: number
  rank_ic: number
  roc_auc: number
  avg_precision: number
}

type T0ModelSummary = {
  status?: string
  reason?: string
  rows?: number
  positive_rate?: number
  test_start?: string
  test_end?: string
  rank_ic?: number
  top10_avg_edge?: number
  top10_two_sided?: number
  folds?: T0ModelFold[]
  feature_importance?: T0ModelFeatureImportance[]
  model_path?: string
}

type TraderRiskStats = {
  stop_hit_rate: number
  sell_first_miss_rate: number
  buy_first_drawdown_rate: number
}

function parseRecentT0Stats(backtest?: T0DailyBacktest): RecentT0Stats | null {
  if (!backtest?.summary_json) return null
  try {
    const payload = JSON.parse(backtest.summary_json) as { recent_2m?: Partial<RecentT0Stats> }
    const recent = payload.recent_2m
    if (!recent) return null
    return {
      n_candidates: Number(recent.n_candidates || 0),
      start_date: String(recent.start_date || ''),
      end_date: String(recent.end_date || ''),
      two_sided_rate: Number(recent.two_sided_rate || 0),
      one_sided_rate: Number(recent.one_sided_rate || 0),
      stop_hit_rate: Number(recent.stop_hit_rate || 0),
      sell_first_miss_rate: Number(recent.sell_first_miss_rate || 0),
      buy_first_drawdown_rate: Number(recent.buy_first_drawdown_rate || 0),
      avg_edge: Number(recent.avg_edge || 0),
      total_edge: Number(recent.total_edge || 0),
      avg_next_range: Number(recent.avg_next_range || 0),
    }
  } catch {
    return null
  }
}

function parseTraderRiskStats(backtest?: T0DailyBacktest): TraderRiskStats | null {
  if (!backtest?.summary_json) return null
  try {
    const payload = JSON.parse(backtest.summary_json) as { trader_risk?: Partial<TraderRiskStats> }
    const risk = payload.trader_risk
    if (!risk) return null
    return {
      stop_hit_rate: Number(risk.stop_hit_rate || 0),
      sell_first_miss_rate: Number(risk.sell_first_miss_rate || 0),
      buy_first_drawdown_rate: Number(risk.buy_first_drawdown_rate || 0),
    }
  } catch {
    return null
  }
}

function amountRatio(row: T0PlanRow) {
  const avgAmount = row.avg_amount_20d || 0
  if (!Number.isFinite(row.amount) || !Number.isFinite(avgAmount) || avgAmount <= 0) return Number.NaN
  return row.amount / avgAmount
}

function flowSignal(row: T0PlanRow) {
  const ratio = amountRatio(row)
  if (!Number.isFinite(ratio)) return { label: '无量能数据', badge: 'created', detail: '无法判断砸盘' }
  if (ratio >= 2 && row.today_pct <= -0.025) return { label: '疑似砸盘', badge: 'failed', detail: `放量 ${ratio.toFixed(1)}x 下跌` }
  if (ratio >= 1.6 && row.today_pct < 0) return { label: '放量下跌', badge: 'failed', detail: `成交额 ${ratio.toFixed(1)}x` }
  if (ratio >= 1.6 && row.today_pct > 0) return { label: '放量承接', badge: 'success', detail: `成交额 ${ratio.toFixed(1)}x` }
  if (ratio < 0.55) return { label: '缩量', badge: 'created', detail: `成交额 ${ratio.toFixed(1)}x` }
  return { label: '量能正常', badge: 'running', detail: `成交额 ${ratio.toFixed(1)}x` }
}

function parseTimeMachineGrid(rows: T0TimeMachineResult[]): TimeMachineGridSummary | null {
  const source = rows.find((row) => row.summary_json)?.summary_json
  if (!source) return null
  try {
    const payload = JSON.parse(source) as { grid?: TimeMachineGridSummary }
    return payload.grid || null
  } catch {
    return null
  }
}

function parseT0ModelSummary(run?: T0DailyRunSummary): T0ModelSummary | null {
  if (!run?.summary_json) return null
  try {
    const payload = JSON.parse(run.summary_json) as { model?: T0ModelSummary }
    return payload.model || null
  } catch {
    return null
  }
}

function t0FeatureLabel(feature: string) {
  return t0FeatureNameMap[feature] || feature
}

function isT0ModelTrained(model: T0ModelSummary | null | undefined) {
  return model?.status === 'trained' || model?.status === 'success'
}

function topGridWindows(grid: TimeMachineGridSummary | null) {
  return (grid?.windows || []).slice(0, 6)
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function waitForRunDone(loadStatus: () => Promise<RunStatus>, label: string) {
  for (let attempt = 0; attempt < 900; attempt += 1) {
    const status = await loadStatus()
    if (status.state === 'done' || status.state === 'success') return status
    if (status.state === 'error' || status.state === 'failed') {
      throw new Error(status.message || `${label}失败`)
    }
    await sleep(1200)
  }
  throw new Error(`${label}等待超时`)
}

function actionPriority(action: string) {
  if (action === '可试仓') return 3
  if (action === '观察') return 2
  if (action === '放弃') return 0
  if (action === '优先计划') return 3
  if (action === '候选观察') return 2
  return 1
}

function countBy<T>(rows: T[], pick: (row: T) => string) {
  const counts = new Map<string, number>()
  rows.forEach((row) => {
    const key = pick(row) || '未分类'
    counts.set(key, (counts.get(key) || 0) + 1)
  })
  return Array.from(counts.entries())
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count)
}

function t0TierConclusion(row: { topK: number; avgEdge: number; totalEdge: number; twoSidedRate: number; oneSidedRate: number; stopRate: number }) {
  if (row.topK <= 3 && row.avgEdge > 0.02 && row.twoSidedRate >= 0.3) return '给条件单'
  if (row.avgEdge > 0.01 && row.totalEdge > 0) return '观察'
  return '停用'
}

export function T0AssistantPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [rows, setRows] = useState<T0Recommendation[]>([])
  const [pullCandidates, setPullCandidates] = useState<T0DataPullCandidate[]>([])
  const [dailyRuns, setDailyRuns] = useState<T0DailyRunSummary[]>([])
  const [backtests, setBacktests] = useState<T0DailyBacktest[]>([])
  const [timeMachineRows, setTimeMachineRows] = useState<T0TimeMachineResult[]>([])
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [timeMachineStatus, setTimeMachineStatus] = useState<RunStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [timeMachineRunning, setTimeMachineRunning] = useState(false)
  const [cycleRunning, setCycleRunning] = useState(false)
  const [activeView, setActiveView] = useState<T0AssistantView>('recommend')
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    setError('')
    return Promise.all([listT0Recommendations(80), listT0DataPullCandidates(80), listT0DailyRuns(5), listT0DailyBacktests(80), listT0TimeMachineResults(80), getT0DailyResearchStatus(), getT0TimeMachineStatus()])
      .then(([nextRows, nextPullCandidates, nextDailyRuns, nextBacktests, nextTimeMachineRows, nextStatus, nextTimeMachineStatus]) => {
        setRows(nextRows)
        setPullCandidates(nextPullCandidates)
        setDailyRuns(nextDailyRuns)
        setBacktests(nextBacktests)
        setTimeMachineRows(nextTimeMachineRows)
        setRunStatus(nextStatus)
        setTimeMachineStatus(nextTimeMachineStatus)
      })
      .catch((err: Error) => setError(err.message || '加载做T建议失败'))
      .finally(() => setLoading(false))
  }

  const run = () => {
    setRunning(true)
    setError('')
    runT0DailyResearch()
      .then(() => getT0DailyResearchStatus())
      .then(setRunStatus)
      .catch((err: Error) => setError(err.message || '启动日线做T评估失败'))
      .finally(() => setRunning(false))
  }

  const runTimeMachine = (mode: 'quick' | 'deep') => {
    setTimeMachineRunning(true)
    setError('')
    runT0TimeMachine(mode)
      .then(() => getT0TimeMachineStatus())
      .then(setTimeMachineStatus)
      .catch((err: Error) => setError(err.message || '启动做T时光机失败'))
      .finally(() => setTimeMachineRunning(false))
  }

  const runModelCycle = async () => {
    setCycleRunning(true)
    setRunning(true)
    setError('')
    try {
      await runT0DailyResearch()
      const dailyStatus = await waitForRunDone(getT0DailyResearchStatus, '日线做T研究')
      setRunStatus(dailyStatus)
      setRunning(false)
      await load()
      setTimeMachineRunning(true)
      await runT0TimeMachine('quick')
      const tmStatus = await waitForRunDone(getT0TimeMachineStatus, '做T快速时光机')
      setTimeMachineStatus(tmStatus)
      setTimeMachineRunning(false)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setRunning(false)
      setTimeMachineRunning(false)
      setCycleRunning(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    let cancelled = false
    const tick = () => {
      getT0DailyResearchStatus()
        .then((status) => {
          if (cancelled) return
          const prev = runStatus?.state || ''
          setRunStatus(status)
          if (prev === 'running' && status.state !== 'running') {
            load()
          }
        })
        .catch(() => {})
    }
    const id = setInterval(tick, 1200)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [runStatus?.state])

  useEffect(() => {
    let cancelled = false
    const tick = () => {
      getT0TimeMachineStatus()
        .then((status) => {
          if (cancelled) return
          const prev = timeMachineStatus?.state || ''
          setTimeMachineStatus(status)
          if (prev === 'running' && status.state !== 'running') {
            load()
          }
        })
        .catch(() => {})
    }
    const id = setInterval(tick, 1200)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [timeMachineStatus?.state])

  const backtestByCode = useMemo(() => {
    const map = new Map<string, T0DailyBacktest>()
    backtests.forEach((row) => map.set(row.ts_code, row))
    return map
  }, [backtests])
  const positionByCode = useMemo(() => {
    const map = new Map<string, T0Recommendation>()
    rows.forEach((row) => map.set(row.ts_code, row))
    return map
  }, [rows])
  const operationTop10 = useMemo(() => {
    const source: T0PlanRow[] = pullCandidates
    return source
      .map((row) => ({ row, recent: parseRecentT0Stats(backtestByCode.get(row.ts_code)) }))
      .filter((item) => item.recent && item.recent.total_edge > 0 && item.recent.two_sided_rate > 0)
      .sort((a, b) => {
        const actionDiff = actionPriority(b.row.action) - actionPriority(a.row.action)
        if (actionDiff !== 0) return actionDiff
        const riskA = (a.recent?.one_sided_rate || 0) + (a.recent?.stop_hit_rate || 0) * 1.5
        const riskB = (b.recent?.one_sided_rate || 0) + (b.recent?.stop_hit_rate || 0) * 1.5
        const qualityA = (a.recent?.total_edge || 0) * 1.4 + (a.recent?.two_sided_rate || 0) * 0.8 - riskA * 0.28
        const qualityB = (b.recent?.total_edge || 0) * 1.4 + (b.recent?.two_sided_rate || 0) * 0.8 - riskB * 0.28
        const qualityDiff = qualityB - qualityA
        if (Math.abs(qualityDiff) > 0.0001) return qualityDiff
        const edgeDiff = (b.recent?.total_edge || 0) - (a.recent?.total_edge || 0)
        if (Math.abs(edgeDiff) > 0.0001) return edgeDiff
        const hitDiff = (b.recent?.two_sided_rate || 0) - (a.recent?.two_sided_rate || 0)
        if (Math.abs(hitDiff) > 0.0001) return hitDiff
        return b.row.score - a.row.score
      })
      .slice(0, 10)
      .map((item) => item.row)
  }, [pullCandidates, backtestByCode])
  const heldCandidateCount = operationTop10.filter((row) => positionByCode.has(row.ts_code)).length
  const watchCandidateCount = Math.max(operationTop10.length - heldCandidateCount, 0)
  const profitSummary = useMemo(() => {
    const recentRows = operationTop10
      .map((row) => parseRecentT0Stats(backtestByCode.get(row.ts_code)))
      .filter((item): item is RecentT0Stats => Boolean(item))
    const avgRecentTotal = recentRows.length ? recentRows.reduce((sum, row) => sum + row.total_edge, 0) / recentRows.length : Number.NaN
    const avgTwoSided = recentRows.length ? recentRows.reduce((sum, row) => sum + row.two_sided_rate, 0) / recentRows.length : Number.NaN
    const avgStopHit = recentRows.length ? recentRows.reduce((sum, row) => sum + row.stop_hit_rate, 0) / recentRows.length : Number.NaN
    const bestRecentTotal = recentRows.length ? Math.max(...recentRows.map((row) => row.total_edge)) : Number.NaN
    return { avgRecentTotal, avgTwoSided, avgStopHit, bestRecentTotal, count: recentRows.length }
  }, [operationTop10, backtestByCode])
  const modelExplainSummary = useMemo(() => {
    const model = parseT0ModelSummary(dailyRuns[0])
    const count = pullCandidates.length
    const avgRange = count ? pullCandidates.reduce((sum, row) => sum + row.avg_range_20d, 0) / count : Number.NaN
    const avgAmount = count ? pullCandidates.reduce((sum, row) => sum + row.avg_amount_20d, 0) / count : Number.NaN
    const avgScore = count ? pullCandidates.reduce((sum, row) => sum + row.score, 0) / count : Number.NaN
    const setupCounts = countBy(pullCandidates, (row) => row.setup || row.state).slice(0, 4)
    const actionCounts = countBy(pullCandidates, (row) => row.first_action || row.action).slice(0, 4)
    const admissionCounts = countBy(pullCandidates, (row) => row.action).slice(0, 4)
    const featureImportance = (model?.feature_importance || [])
      .slice()
      .sort((a, b) => (a.rank_no || 999) - (b.rank_no || 999))
      .slice(0, 8)
    const folds = (model?.folds || []).slice().sort((a, b) => a.year - b.year)
    return {
      model,
      count,
      avgRange,
      avgAmount,
      avgScore,
      setupCounts,
      actionCounts,
      admissionCounts,
      featureImportance,
      folds,
      trainRows: Number(model?.rows || 0),
      positiveRate: Number(model?.positive_rate ?? Number.NaN),
      rankIC: Number(model?.rank_ic ?? Number.NaN),
      top10AvgEdge: Number(model?.top10_avg_edge ?? Number.NaN),
      top10TwoSided: Number(model?.top10_two_sided ?? Number.NaN),
    }
  }, [dailyRuns, pullCandidates])
  const timeMachineSummary = useMemo(() => {
    const grid = parseTimeMachineGrid(timeMachineRows)
    if (timeMachineRows.length === 0) {
      return {
        verdict: '未验证',
        avgT0Edge: Number.NaN,
        avgUnderlying: Number.NaN,
        avgCombined: Number.NaN,
        winRate: Number.NaN,
        evalStart: '',
        evalEnd: '',
        count: 0,
        grid,
      }
    }
    const count = timeMachineRows.length
    const avg = (pick: (row: T0TimeMachineResult) => number) => timeMachineRows.reduce((sum, row) => sum + pick(row), 0) / count
    const avgT0Edge = avg((row) => row.t0_edge)
    const avgUnderlying = avg((row) => row.underlying_return)
    const avgCombined = avg((row) => row.combined_return)
    const winRate = timeMachineRows.filter((row) => row.combined_return > 0).length / count
    const evalStart = timeMachineRows.map((row) => row.eval_start_date).filter(Boolean).sort()[0] || ''
    const evalEnds = timeMachineRows.map((row) => row.eval_end_date).filter(Boolean).sort()
    const evalEnd = evalEnds.length ? evalEnds[evalEnds.length - 1] : ''
    const positiveWindowRate = grid?.positive_window_rate ?? Number.NaN
    const worstWindow = grid?.worst_avg_combined_return ?? Number.NaN
    const isStable = Number.isFinite(positiveWindowRate) && positiveWindowRate >= 0.67 && Number.isFinite(worstWindow) && worstWindow > -0.03
    const verdict = avgCombined > 0.04 && avgT0Edge > 0.03 && isStable ? '稳定可观察' : avgCombined > 0.03 && avgT0Edge > 0.03 ? '收益好待稳定' : avgCombined > 0 ? '仅观察' : '暂不自动化'
    return { verdict, avgT0Edge, avgUnderlying, avgCombined, winRate, evalStart, evalEnd, count, grid }
  }, [timeMachineRows])
  const isRunning = runStatus?.state === 'running'
  const isTimeMachineRunning = timeMachineStatus?.state === 'running'
  const total = runStatus?.total ?? 0
  const idx = runStatus?.idx ?? 0
  const pct = total > 0 ? Math.min(100, Math.round((idx / total) * 100)) : 0
  const tmTotal = timeMachineStatus?.total ?? 0
  const tmIdx = timeMachineStatus?.idx ?? 0
  const tmPct = tmTotal > 0 ? Math.min(100, Math.round((tmIdx / tmTotal) * 100)) : 0
  const dataUpdatedAt = pullCandidates[0]?.generated_at || rows[0]?.generated_at || runStatus?.updated_at || timeMachineStatus?.updated_at || ''
  const bestWindow = timeMachineSummary.grid?.best
  const bestCombined = bestWindow?.mean_avg_combined_return ?? timeMachineSummary.avgCombined
  const bestT0Edge = bestWindow?.mean_avg_t0_edge ?? timeMachineSummary.avgT0Edge
  const bestWorst = bestWindow?.worst_avg_combined_return ?? timeMachineSummary.grid?.worst_avg_combined_return ?? Number.NaN
  const bestPositiveRate = bestWindow?.positive_anchor_rate ?? timeMachineSummary.grid?.positive_window_rate ?? Number.NaN
  const evaluationTiers = [1, 3, 5, 10].map((topK) => {
    const tierRows = backtests.slice(0, Math.min(topK, backtests.length))
    const risks = tierRows.map(parseTraderRiskStats)
    return {
      topK,
      count: tierRows.length,
      avgEdge: avgNumber(tierRows.map((row) => row.avg_edge)),
      totalEdge: avgNumber(tierRows.map((row) => row.total_edge)),
      twoSidedRate: avgNumber(tierRows.map((row) => row.two_sided_rate)),
      oneSidedRate: avgNumber(tierRows.map((row) => row.one_sided_rate)),
      stopRate: avgNumber(risks.map((risk) => risk?.stop_hit_rate ?? Number.NaN)),
      avgNextRange: avgNumber(tierRows.map((row) => row.avg_next_range)),
    }
  }).filter((row) => row.count > 0)
  const yearMetrics = Array.from(timeMachineRows.reduce((map, row) => {
    const year = (row.eval_end_date || row.eval_start_date || '').slice(0, 4) || '未知'
    const rowsForYear = map.get(year) || []
    rowsForYear.push(row)
    map.set(year, rowsForYear)
    return map
  }, new Map<string, T0TimeMachineResult[]>()).entries())
    .map(([year, items]) => ({
      year,
      combined: avgNumber(items.map((item) => item.combined_return)),
      t0Edge: avgNumber(items.map((item) => item.t0_edge)),
      underlying: avgNumber(items.map((item) => item.underlying_return)),
      winRate: items.length ? items.filter((item) => item.combined_return > 0).length / items.length : Number.NaN,
      count: items.length,
    }))
    .sort((a, b) => a.year.localeCompare(b.year))
  const recentYears = yearMetrics.slice(-3)
  const recentCombined = avgNumber(recentYears.map((item) => item.combined))
  const recentT0Edge = avgNumber(recentYears.map((item) => item.t0Edge))
  const worstYear = yearMetrics.reduce<typeof yearMetrics[number] | null>((worst, item) => !worst || item.combined < worst.combined ? item : worst, null)
  const tradingRows = [3, 5, 10].map((topK) => {
    const tierRows = backtests.slice(0, Math.min(topK, backtests.length))
    const signalCount = tierRows.reduce((sum, row) => sum + row.n_candidates, 0)
    const tradeCount = tierRows.reduce((sum, row) => sum + Math.round(row.n_candidates * row.two_sided_rate), 0)
    const avgReturn = avgNumber(tierRows.map((row) => row.avg_edge))
    const winRate = avgNumber(tierRows.map((row) => row.two_sided_rate))
    const maxDrawdown = -Math.abs(avgNumber(tierRows.map((row) => row.one_sided_rate + (parseTraderRiskStats(row)?.stop_hit_rate ?? 0))))
    const compoundReturn = avgNumber(tierRows.map((row) => row.total_edge))
    return {
      name: `Top${topK} / 两边触达`,
      signalCount,
      tradeCount,
      fillRate: signalCount > 0 ? tradeCount / signalCount : Number.NaN,
      avgReturn,
      winRate,
      compoundReturn,
      maxDrawdown,
    }
  }).filter((row) => row.signalCount > 0)
  const bestTrading = tradingRows.reduce<typeof tradingRows[number] | null>((best, item) => !best || item.compoundReturn > best.compoundReturn ? item : best, null)
  const recentSlices = timeMachineRows.slice(0, 12)
  const evalSignalPass = profitSummary.avgRecentTotal > 0 && profitSummary.avgTwoSided > 0
  const evalTradePass = bestCombined > 0 && bestT0Edge > 0 && (!Number.isFinite(bestWorst) || bestWorst > -0.05) && (!bestTrading || bestTrading.compoundReturn > 0)
  const evalVerdict = timeMachineRows.length === 0
    ? { tone: 'warningText', label: '未验证', text: '还没有做T时光机评估。先去模型训练页更新模型，再决定推荐页是否可执行。' }
    : evalSignalPass && evalTradePass
      ? { tone: 'positiveText', label: '可观察', text: `时光机合并收益 ${percent(bestCombined, true)}，做T贡献 ${percent(bestT0Edge, true)}，近2月候选价差 ${percent(profitSummary.avgRecentTotal, true)}。` }
      : evalSignalPass
        ? { tone: 'warningText', label: '观察', text: `日线信号有价差，但时光机稳定性不足；最差窗口 ${percent(bestWorst, true)}，暂不自动化。` }
        : { tone: 'negativeText', label: '不通过', text: '近2月候选价差或两边触达不足，模型暂不适合作为实盘条件单入口。' }

  return (
    <div className="positionPage">
      {error ? <div className="errorBanner">{error}</div> : null}
      {isRunning ? (
        <div className="signalProgress signalProgressStandalone">
          <div className="signalProgressHeader">
            <span>{runStatus?.stage || 'running'} · {runStatus?.name || '日线做T研究'}</span>
            <span>{total > 0 ? `${idx}/${total} (${pct}%)` : runStatus?.updated_at || ''}</span>
          </div>
          <div className="signalProgressBar"><div className="signalProgressBarFill" style={{ width: total > 0 ? `${pct}%` : '15%' }} /></div>
        </div>
      ) : null}
      {isTimeMachineRunning ? (
        <div className="signalProgress signalProgressStandalone">
          <div className="signalProgressHeader">
            <span>{timeMachineStatus?.stage || 'running'} · {timeMachineStatus?.name || '做T时光机'}</span>
            <span>{tmTotal > 0 ? `${tmIdx}/${tmTotal} (${tmPct}%)` : timeMachineStatus?.updated_at || ''}</span>
          </div>
          <div className="signalProgressBar"><div className="signalProgressBarFill" style={{ width: tmTotal > 0 ? `${tmPct}%` : '15%' }} /></div>
        </div>
      ) : null}

      <div className="pageTabsHeader">
        <div className="inlineTabs evaluationModeTabs signalViewTabs">
          {t0AssistantTabs.map((tab) => (
            <button key={tab.key} className={activeView === tab.key ? 'active' : ''} onClick={() => setActiveView(tab.key)}>
              {tab.label}
            </button>
          ))}
        </div>
        <div className="dataUpdatedPill">数据更新：{formatDateTime(dataUpdatedAt)}</div>
      </div>

      {activeView === 'recommend' ? (
        <>
      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">T0 ASSISTANT</div>
            <h2>做T实盘观察清单</h2>
            <p className="recommendationMeta">先用时光机验证策略整体收益，再给今日 Top10 观察票；当前只给操作计划，不自动下单、不改仓位。</p>
          </div>
          <div className="tableHeaderRight">
            <button className="secondaryButton startButton" onClick={run} disabled={loading || running || isRunning}>
              {running || isRunning ? '更新中' : '更新推荐'}
            </button>
          </div>
        </div>

        <div className="metricStrip">
          <div className={`metricCard ${timeMachineSummary.avgCombined > 0 ? 'good' : ''}`}>
            <span>策略结论</span>
            <b>{timeMachineSummary.verdict}</b>
            <em>{timeMachineSummary.grid?.best ? `最佳 ${timeMachineSummary.grid.best.lookback}/${timeMachineSummary.grid.best.eval_days} · ${timeMachineSummary.grid.best.anchor_count || 1}锚点` : timeMachineSummary.count > 0 ? `${timeMachineSummary.count} 只历史样本` : '先更新模型'}</em>
          </div>
          <div className="metricCard good">
            <span>时光机合并收益</span>
            <b className={signedClass(timeMachineSummary.avgCombined)}>{percent(timeMachineSummary.avgCombined, true)}</b>
            <em>{timeMachineSummary.evalStart ? `${formatDate(timeMachineSummary.evalStart)} - ${formatDate(timeMachineSummary.evalEnd)}` : '暂无区间'}</em>
          </div>
          <div className="metricCard">
            <span>稳定窗口</span>
            <b className={signedClass(timeMachineSummary.avgT0Edge)}>{percent(timeMachineSummary.avgT0Edge, true)}</b>
            <em>
              {timeMachineSummary.grid
                ? `正收益 ${percent(timeMachineSummary.grid.positive_window_rate ?? Number.NaN)} · 最差 ${percent(timeMachineSummary.grid.worst_avg_combined_return ?? Number.NaN, true)}`
                : `标的自身 ${percent(timeMachineSummary.avgUnderlying, true)}`}
            </em>
          </div>
          <div className="metricCard">
            <span>胜率 / 今日Top10</span>
            <b>{percent(timeMachineSummary.winRate)}</b>
            <em>{operationTop10.length} 只候选 · {heldCandidateCount} 只已有持仓</em>
          </div>
        </div>

        <div className="metricStrip">
          <div className="metricCard">
            <span>1 发现候选</span>
            <b>{pullCandidates.length}</b>
            <em>全市场做T适配扫描</em>
          </div>
          <div className={`metricCard ${operationTop10.length > 0 ? 'good' : ''}`}>
            <span>2 验证通过</span>
            <b>{operationTop10.length}</b>
            <em>近2月价差为正且两边触达</em>
          </div>
          <div className="metricCard">
            <span>3 观察建底仓</span>
            <b>{watchCandidateCount}</b>
            <em>未持仓，先等低吸/建仓机会</em>
          </div>
          <div className={`metricCard ${heldCandidateCount > 0 ? 'good' : ''}`}>
            <span>4 可执行做T</span>
            <b>{heldCandidateCount}</b>
            <em>已有底仓，按计划价执行</em>
          </div>
        </div>

        <div className="metricStrip">
          <div className={`metricCard ${profitSummary.avgRecentTotal > 0 ? 'good' : ''}`}>
            <span>Top10近2月价差</span>
            <b className={signedClass(profitSummary.avgRecentTotal)}>{percent(profitSummary.avgRecentTotal, true)}</b>
            <em>{profitSummary.count} 只候选均值，只统计两边触达价差</em>
          </div>
          <div className="metricCard">
            <span>Top10两边触达</span>
            <b>{percent(profitSummary.avgTwoSided)}</b>
            <em>越高越适合机械高抛低吸</em>
          </div>
          <div className="metricCard">
            <span>Top10停手触达</span>
            <b className={profitSummary.avgStopHit > 0.2 ? 'negative' : ''}>{percent(profitSummary.avgStopHit)}</b>
            <em>越低越不容易做成破位低吸</em>
          </div>
          <div className={`metricCard ${profitSummary.bestRecentTotal > 0 ? 'good' : ''}`}>
            <span>最佳近2月价差</span>
            <b className={signedClass(profitSummary.bestRecentTotal)}>{percent(profitSummary.bestRecentTotal, true)}</b>
            <em>单票累计做T价差上限参考</em>
          </div>
        </div>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">ACTION LIST</div>
            <h2>做T条件单清单</h2>
            <p className="recommendationMeta">Top3 才给条件单；Top4-10 只观察，不下单。未持仓先按建底仓条件单，已有底仓才给高抛/接回条件单。</p>
          </div>
        </div>
        <div className="metricStrip signalTierStrip">
          {evaluationTiers.map((tier) => (
            <div className={`metricCard ${t0TierConclusion(tier) === '给条件单' ? 'good' : ''}`} key={`t0-tier-${tier.topK}`}>
              <span>Top{tier.topK}</span>
              <b className={signedClass(tier.avgEdge)}>{percent(tier.avgEdge, true)}</b>
              <em>{t0TierConclusion(tier)} · 累计 {percent(tier.totalEdge, true)} · 两边 {percent(tier.twoSidedRate)}</em>
            </div>
          ))}
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>排名</th>
                <th>股票</th>
                <th>动作</th>
                <th>条件买入</th>
                <th>买入股数</th>
                <th>条件卖出</th>
                <th>卖出股数</th>
                <th>止损/停手</th>
                <th>验证 / 风险</th>
              </tr>
            </thead>
            <tbody>
              {operationTop10.map((row, index) => {
                const plan = planBand(row)
                const recent = parseRecentT0Stats(backtestByCode.get(row.ts_code))
                const flow = flowSignal(row)
                const position = positionByCode.get(row.ts_code)
                const held = Boolean(position)
                const tShares = position?.max_t0_shares || 0
                const buildShares = roundLotShares(plan.buy, 10000)
                const executable = index < 3
                const buyShares = executable ? held ? tShares : buildShares : 0
                const sellShares = executable && held ? tShares : 0
                const displayAction = executable ? '可试仓' : '观察'
                return (
                  <tr key={row.ts_code}>
                    <td><strong>{index + 1}</strong></td>
                    <td className="t0StockCell">
                      <button className="tableActionButton" onClick={() => onOpenResearch?.(row.ts_code)}>
                        {row.name || row.ts_code}
                      </button>
                      <div className="mono">{row.ts_code}</div>
                      <div className="recommendationMeta t0CurrentPrice">当前价 ¥{money(row.price)}</div>
                      <div className="recommendationMeta">{row.industry || '—'} · {formatDate(row.trade_date)}</div>
                      <div className="recommendationMeta">{held ? `已持仓 · 可T ${tShares} 股` : '未持仓 · 先建底仓条件单'}</div>
                      <div className="recommendationMeta">首次推荐 {formatDate(row.first_seen_date)} · 观察 {row.observation_days || 0} 天 · 保留 {row.seen_count || 0} 次</div>
                      <div className="recommendationMeta">{row.observation_result || '观察中'}</div>
                    </td>
                    <td>
                      <span className={`badge ${pullBadge(displayAction)}`}>{displayAction}</span>
                      <div className="recommendationMeta">{row.setup || row.state || '交易员模型'}</div>
                      <div className="recommendationMeta">{executable ? row.first_action || '挂单等待' : 'Top4-10 不执行'}</div>
                      <div className="recommendationMeta">{flow.label} · 今日 {percent(row.today_pct, true)}</div>
                      <div className="recommendationMeta">保留原因：{row.observation_reason || row.setup || row.action || '做T候选'}</div>
                    </td>
                    <td>
                      <strong>¥{money(plan.buy)}</strong>
                      <div className="recommendationMeta">{held ? '高抛后接回价' : '建底仓触发价'}</div>
                      <div className="recommendationMeta">现价下方 {percent(1 - (plan.buy / row.price))}</div>
                      <div className="recommendationMeta">不到价不追</div>
                    </td>
                    <td>
                      <strong>{buyShares > 0 ? `${buyShares} 股` : '不买'}</strong>
                      <div className="recommendationMeta">{executable ? held ? '卖出后同股数接回' : '按1万元试仓估算' : '观察层不下单'}</div>
                      <div className="recommendationMeta">100股取整</div>
                    </td>
                    <td>
                      <strong>¥{money(plan.reduce)}</strong>
                      <div className="recommendationMeta">{held ? '高抛触发价' : '建仓后目标卖出价'}</div>
                      <div className="recommendationMeta">距当前 {percent((plan.reduce / row.price) - 1, true)}</div>
                      <div className="recommendationMeta">未触达不抢跑</div>
                    </td>
                    <td>
                      <strong>{sellShares > 0 ? `${sellShares} 股` : '不卖'}</strong>
                      <div className="recommendationMeta">{executable && held ? `T仓 ${plan.tRatio}` : executable ? '未持仓无卖单' : '观察层不卖出'}</div>
                      <div className="recommendationMeta">{executable && held ? '保留底仓' : executable ? '建仓后再生成卖单' : '等下次排名确认'}</div>
                    </td>
                    <td>
                      <strong className="negative">¥{money(plan.stop)}</strong>
                      <div className="recommendationMeta">{held ? '跌破停止低吸/控仓' : '跌破不建底仓'}</div>
                      <div className="recommendationMeta">重新站回再评估</div>
                    </td>
                    <td>
                      <strong className={signedClass(recent?.total_edge ?? Number.NaN)}>{recent ? percent(recent.total_edge, true) : '—'}</strong>
                      <div className="recommendationMeta">{recent ? `两边 ${percent(recent.two_sided_rate)} · 单边 ${percent(recent.one_sided_rate)}` : '需重跑日线评估'}</div>
                      {recent ? <div className="recommendationMeta">停手 {percent(recent.stop_hit_rate)}</div> : null}
                      <ul className="compactList">
                        {row.risks.slice(0, 2).map((risk) => <li key={risk}><AlertTriangle size={13} /> {risk}</li>)}
                        {row.risks.length === 0 ? <li>暂无显著风险</li> : null}
                      </ul>
                    </td>
                  </tr>
                )
              })}
              {!loading && operationTop10.length === 0 ? <tr><td colSpan={9} className="emptyCell">暂无做T条件单候选，请先去模型训练页更新模型</td></tr> : null}
              {loading ? <tr><td colSpan={9} className="emptyCell">加载中...</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
        </>
      ) : null}

      {activeView === 'experiment' ? (
        <>
      <section className="limitModelPanel">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">MODEL EVALUATION</div>
            <div className="dashboardPanelTitle">做T效果评估</div>
            <div className="cardHint">这里看模型固定后的时光机窗口、近2月做T价差、触达率、最差窗口和交易风险；不展示旧规则流水。</div>
          </div>
        </div>
        {(error || timeMachineStatus?.message || runStatus?.message) && <div className={error ? 'errorBox' : 'cardHint'}>{error || timeMachineStatus?.message || runStatus?.message}</div>}
        {profitSummary.count > 0 ? <div className="cardHint">做T模型完成：Top10价差 {percent(profitSummary.avgRecentTotal, true)}</div> : null}
        <div className="limitModelVerdict">
          <div>
            <span className={evalVerdict.tone}>{evalVerdict.label}</span>
            <b>{timeMachineSummary.evalStart ? `${formatDate(timeMachineSummary.evalStart)} - ${formatDate(timeMachineSummary.evalEnd)}` : '等待验证'}</b>
            <p>{evalVerdict.text}</p>
          </div>
          <div className="limitModelMetrics">
            <Mini label="样本" value={backtests.length ? `${backtests.reduce((sum, row) => sum + row.n_candidates, 0)}/${backtests.reduce((sum, row) => sum + row.n_days, 0)}` : '—'} />
            <Mini label="TOP10价差" value={percent(profitSummary.avgRecentTotal, true)} valueClassName={signedClass(profitSummary.avgRecentTotal)} />
            <Mini label="做T贡献" value={percent(bestT0Edge, true)} valueClassName={signedClass(bestT0Edge)} />
            <Mini label="两边触达率" value={percent(profitSummary.avgTwoSided)} />
            <Mini label="最大回撤" value={percent(bestWorst, true)} valueClassName={signedClass(bestWorst)} />
            <Mini label="稳定率" value={percent(bestPositiveRate)} />
          </div>
        </div>
        <div className="limitValidationGates">
          <div className={`metricCard ${evalSignalPass ? 'good' : ''}`}>
            <span>第一关 信号有效</span>
            <b>{evalSignalPass ? '信号有效' : profitSummary.count ? '信号谨慎' : '待验证'}</b>
            <em>{profitSummary.count ? `Top10价差 ${percent(profitSummary.avgRecentTotal, true)} · 两边 ${percent(profitSummary.avgTwoSided)}` : '先更新模型'}</em>
          </div>
          <div className={`metricCard ${evalTradePass ? 'good' : ''}`}>
            <span>第二关 交易可做</span>
            <b>{evalTradePass ? '交易可做' : timeMachineRows.length ? '交易未过' : '待验证'}</b>
            <em>{timeMachineRows.length ? `合并 ${percent(bestCombined, true)} · 最差 ${percent(bestWorst, true)} · 正收益 ${percent(bestPositiveRate)}` : '缺时光机验证'}</em>
          </div>
          <div className="metricCard">
            <span>推荐动作</span>
            <b>{evalSignalPass && evalTradePass ? '可试仓验证' : evalSignalPass ? '观察不自动化' : '先停用推荐'}</b>
            <em>{evalSignalPass && !evalTradePass ? '有票但稳定性没过，推荐页只给观察计划' : '已有底仓才允许做T条件单'}</em>
          </div>
        </div>
        <div className="limitModelNote">
          <b>近年稳定性</b>
          <span>
            {recentYears.length ? `最近${recentYears.length}年合并收益 ${percent(recentCombined, true)}，做T贡献 ${percent(recentT0Edge, true)}，${recentCombined < bestCombined * 0.75 ? '低于全周期均值，说明模型有衰减，需要看最近切面。' : '仍高于零轴，暂未出现明显失效。'}` : '暂无分年稳定性数据，请先更新模型。'}
          </span>
          <b>最大压力年</b>
          <span>{worstYear ? `${worstYear.year} 年合并收益 ${percent(worstYear.combined, true)}，做T贡献 ${percent(worstYear.t0Edge, true)}。` : Number.isFinite(bestWorst) ? `当前最差窗口合并收益 ${percent(bestWorst, true)}。` : '暂无压力数据。'}</span>
          <b>交易验证</b>
          <span>{bestTrading ? `当前保守做T规则最优为 ${bestTrading.name}，累计价差 ${percent(bestTrading.compoundReturn, true)}，成交率 ${percent(bestTrading.fillRate)}。${bestTrading.compoundReturn <= 0 ? '交易层暂不通过，不能自动实盘。' : '交易层可继续小仓验证。'}` : '暂无交易层验证，更新模型后生成。'}</span>
        </div>
        <div className="limitModelEvalGrid">
          <div>
            <div className="formTitle">Top 分层表现</div>
            <div className="modelEvalTableWrap">
              <table className="modelEvalTable">
                <thead>
                  <tr>
                    <th>层级</th>
                    <th>单次价差</th>
                    <th>累计价差</th>
                    <th>次日振幅</th>
                    <th>两边触达</th>
                    <th>单边触达</th>
                    <th>停手</th>
                  </tr>
                </thead>
                <tbody>
                  {evaluationTiers.length === 0 ? (
                    <tr><td colSpan={7}>暂无分层评估，更新模型后生成</td></tr>
                  ) : evaluationTiers.map((row) => (
                    <tr key={row.topK}>
                      <td>Top{row.topK}</td>
                      <td className={signedClass(row.avgEdge)}>{percent(row.avgEdge, true)}</td>
                      <td className={signedClass(row.totalEdge)}>{percent(row.totalEdge, true)}</td>
                      <td>{percent(row.avgNextRange)}</td>
                      <td>{percent(row.twoSidedRate)}</td>
                      <td>{percent(row.oneSidedRate)}</td>
                      <td>{percent(row.stopRate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div>
            <div className="formTitle">分年 Walk-forward</div>
            <div className="modelEvalTableWrap">
              <table className="modelEvalTable">
                <thead>
                  <tr>
                    <th>年份</th>
                    <th>合并收益</th>
                    <th>做T贡献</th>
                    <th>标的自身</th>
                    <th>胜率</th>
                    <th>样本</th>
                  </tr>
                </thead>
                <tbody>
                  {yearMetrics.length === 0 ? (
                    <tr><td colSpan={6}>暂无分年评估，更新模型后生成</td></tr>
                  ) : yearMetrics.map((row) => (
                    <tr key={row.year}>
                      <td>{row.year}</td>
                      <td className={signedClass(row.combined)}>{percent(row.combined, true)}</td>
                      <td className={signedClass(row.t0Edge)}>{percent(row.t0Edge, true)}</td>
                      <td className={signedClass(row.underlying)}>{percent(row.underlying, true)}</td>
                      <td>{percent(row.winRate)}</td>
                      <td>{row.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <div>
          <div className="formTitle">交易层验证</div>
          <div className="cardHint">已有底仓才做T；只在次日 high/low 同时触达高抛和低吸区间时计为成交；不知道日内顺序，先用作保守验证。</div>
          <div className="modelEvalTableWrap">
            <table className="modelEvalTable tradingEvalTable">
              <thead>
                <tr>
                  <th>规则</th>
                  <th>成交/信号</th>
                  <th>成交率</th>
                  <th>单次价差</th>
                  <th>胜率</th>
                  <th>累计价差</th>
                  <th>最大回撤</th>
                </tr>
              </thead>
              <tbody>
                {tradingRows.length === 0 ? (
                  <tr><td colSpan={7}>暂无交易验证，更新模型后生成</td></tr>
                ) : tradingRows.map((row) => (
                  <tr key={row.name}>
                    <td>{row.name}</td>
                    <td>{row.tradeCount}/{row.signalCount}</td>
                    <td>{percent(row.fillRate)}</td>
                    <td className={signedClass(row.avgReturn)}>{percent(row.avgReturn, true)}</td>
                    <td>{percent(row.winRate)}</td>
                    <td className={signedClass(row.compoundReturn)}>{percent(row.compoundReturn, true)}</td>
                    <td className={signedClass(row.maxDrawdown)}>{percent(row.maxDrawdown, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="limitModelColumns twoColumns">
          <div>
            <div className="formTitle">最近评测切面</div>
            <div className="limitModelList">
              {recentSlices.length === 0 ? <div className="taskGridEmpty compactEmpty">暂无时光机切面</div> : recentSlices.map((item) => (
                <div className="limitModelSliceRow" key={`${item.ts_code}-${item.eval_end_date}`}>
                  <b>{formatDate(item.eval_end_date)}</b>
                  <span>{item.name || item.ts_code} · 合并 {percent(item.combined_return, true)} · 做T {percent(item.t0_edge, true)} · {item.combined_return > 0 ? '正收益' : '负收益'}</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="formTitle">重要特征</div>
            <div className="limitModelFeatureList">
              {t0FeatureLabels.map((label, index) => <span key={label}>{index + 1}. {label}</span>)}
            </div>
          </div>
        </div>
      </section>
        </>
      ) : null}

      {activeView === 'model' ? (
        <>
      <section className="limitModelPanel">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">T0 MODEL</div>
            <div className="dashboardPanelTitle">做T交易员模型</div>
            <div className="cardHint">基于箱体位置、波动空间、触达质量、流动性和交易风险训练做T准入模型；按近2月日线近似回测校验，宁可多给观察，不把单边风险高的票直接推成执行。</div>
          </div>
          <div className="tableHeaderRight">
            <button className="primaryButton" onClick={runModelCycle} disabled={loading || running || isRunning || timeMachineRunning || isTimeMachineRunning || cycleRunning} title="先更新做T日线模型，再自动运行快速时光机验收">
              {cycleRunning || running || isRunning || timeMachineRunning || isTimeMachineRunning ? '模型更新中...' : '更新模型'}
            </button>
          </div>
        </div>
        {(error || runStatus?.message) && <div className={error ? 'errorBox' : 'cardHint'}>{error || runStatus?.message}</div>}
        <div className="limitModelVerdict">
          <div>
            <span className={isT0ModelTrained(modelExplainSummary.model) ? 'positiveText' : profitSummary.avgRecentTotal > 0 ? 'warningText' : 'negativeText'}>
              {isT0ModelTrained(modelExplainSummary.model) ? '可观察' : modelExplainSummary.model?.reason ? '样本不足' : '等待训练'}
            </span>
            <b>{dataUpdatedAt ? formatDateTime(dataUpdatedAt) : '等待更新'}</b>
            <p>
              {isT0ModelTrained(modelExplainSummary.model)
                ? `LightGBM walk-forward 已训练，样本 ${modelExplainSummary.trainRows}，正样本率 ${percent(modelExplainSummary.positiveRate)}，Top10单次价差 ${percent(modelExplainSummary.top10AvgEdge, true)}。`
                : modelExplainSummary.model?.reason
                  ? `本轮模型未训练：${modelExplainSummary.model.reason}。推荐页会退回交易员规则分，不自动放大执行。`
                : '还没有做T模型结果。先更新模型，完成后才有条件单推荐和时光机评测。'}
            </p>
          </div>
          <div className="limitModelMetrics">
            <Mini label="今日候选" value={String(modelExplainSummary.count || '—')} />
            <Mini label="训练样本" value={modelExplainSummary.trainRows ? modelExplainSummary.trainRows.toLocaleString('zh-CN') : '—'} />
            <Mini label="正样本率" value={percent(modelExplainSummary.positiveRate)} />
            <Mini label="RANK IC" value={Number.isFinite(modelExplainSummary.rankIC) ? modelExplainSummary.rankIC.toFixed(3) : '—'} valueClassName={signedClass(modelExplainSummary.rankIC)} />
            <Mini label="Top10价差" value={percent(modelExplainSummary.top10AvgEdge, true)} valueClassName={signedClass(modelExplainSummary.top10AvgEdge)} />
            <Mini label="Top10两边" value={percent(modelExplainSummary.top10TwoSided)} />
          </div>
        </div>
        <div className="limitModelColumns twoColumns">
          <div>
            <div className="formTitle">重要特征</div>
            <div className="limitModelFeatureList">
              {modelExplainSummary.featureImportance.length > 0
                ? modelExplainSummary.featureImportance.map((item, index) => <span key={item.feature}>{index + 1}. {t0FeatureLabel(item.feature)} · {item.importance.toFixed(1)}</span>)
                : t0FeatureLabels.map((label, index) => <span key={label}>{index + 1}. {label}</span>)}
            </div>
          </div>
          <div>
            <div className="formTitle">训练说明</div>
            <div className="limitModelNote">
              <b>训练方式</b>
              <span>全市场历史截面训练 LightGBM 做T准入模型；每个历史日只使用当时可见指标，按年份 walk-forward 验证，避免未来函数。</span>
              <b>目标标签</b>
              <span>次日 high/low 同时触达高抛价和低吸价、扣成本后价差大于 0.6%，且不触发停手线；模型输出推荐页的观察、建底仓、已有底仓执行分层。</span>
              <b>当前分布</b>
              <span>结构：{modelExplainSummary.setupCounts.map((item) => `${item.label} ${item.count}`).join(' · ') || '—'}；动作：{modelExplainSummary.actionCounts.map((item) => `${item.label} ${item.count}`).join(' · ') || '—'}；训练区间：{modelExplainSummary.model?.test_start ? `${formatDate(modelExplainSummary.model.test_start)} - ${formatDate(modelExplainSummary.model.test_end || '')}` : '—'}。</span>
            </div>
          </div>
        </div>
        <div className="modelEvalTableWrap">
          <table className="modelEvalTable">
            <thead>
              <tr>
                <th>年份</th>
                <th>样本</th>
                <th>正样本率</th>
                <th>Top10两边</th>
                <th>Top10单次价差</th>
                <th>Rank IC</th>
                <th>AUC</th>
              </tr>
            </thead>
            <tbody>
              {modelExplainSummary.folds.length === 0 ? (
                <tr><td colSpan={7}>暂无 walk-forward 明细，更新模型后生成</td></tr>
              ) : modelExplainSummary.folds.map((row) => (
                <tr key={row.year}>
                  <td>{row.year}</td>
                  <td>{row.rows.toLocaleString('zh-CN')}</td>
                  <td>{percent(row.positive_rate)}</td>
                  <td>{percent(row.top10_two_sided)}</td>
                  <td className={signedClass(row.top10_avg_edge)}>{percent(row.top10_avg_edge, true)}</td>
                  <td className={signedClass(row.rank_ic)}>{Number.isFinite(row.rank_ic) ? row.rank_ic.toFixed(3) : '—'}</td>
                  <td>{Number.isFinite(row.roc_auc) ? row.roc_auc.toFixed(3) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
        </>
      ) : null}

    </div>
  )
}

function pullBadge(action: string) {
  if (action === '可试仓') return 'success'
  if (action === '观察') return 'running'
  if (action === '放弃') return 'created'
  if (action === '优先计划') return 'success'
  if (action === '候选观察') return 'running'
  if (action === '只观察') return 'running'
  return 'created'
}

function Mini({ label, value, valueClassName = '' }: { label: string; value: string; valueClassName?: string }) {
  return <div className="miniMetric compact"><span>{label}</span><b className={valueClassName}>{value}</b></div>
}
