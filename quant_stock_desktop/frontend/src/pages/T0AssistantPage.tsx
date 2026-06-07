import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, LineChart, RefreshCw, ShieldCheck, Target } from 'lucide-react'
import { getT0DailyResearchStatus, getT0TimeMachineStatus, listT0DailyBacktests, listT0DataPullCandidates, listT0Recommendations, listT0TimeMachineResults, runT0DailyResearch, runT0TimeMachine, type RunStatus, type T0DailyBacktest, type T0DataPullCandidate, type T0Recommendation, type T0TimeMachineResult } from '../services/app'

function money(value: number) {
  if (!Number.isFinite(value) || value === 0) return '—'
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function percent(value: number, signed = false) {
  if (!Number.isFinite(value)) return '—'
  const pct = value * 100
  const sign = signed && pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
}

function numberText(value: number) {
  if (!Number.isFinite(value) || value === 0) return '—'
  return value.toLocaleString('zh-CN')
}

function amountYi(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '—'
  return `${(value / 100000).toFixed(2)}亿`
}

function actionBadge(action: string) {
  if (action === '适合做T') return 'success'
  if (action === '观察') return 'running'
  return 'failed'
}

function signedClass(value: number) {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return ''
}

function formatDate(value: string) {
  if (!value) return '—'
  if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
  return value
}

function planBand(row: T0DataPullCandidate) {
  const band = Math.max(0.008, Math.min(0.04, row.avg_range_20d * 0.55))
  const stopBand = Math.max(0.018, Math.min(0.06, row.avg_range_20d * 0.9))
  return {
    reduce: row.price * (1 + band),
    buy: row.price * (1 - band),
    stop: row.price * (1 - stopBand),
    tRatio: row.score >= 85 ? '30%' : row.score >= 72 ? '20%' : '10%',
  }
}

type RecentT0Stats = {
  n_candidates: number
  start_date: string
  end_date: string
  two_sided_rate: number
  one_sided_rate: number
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
  positive_window_rate?: number
  worst_avg_combined_return?: number
  mean_avg_combined_return?: number
  window_count?: number
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
      avg_edge: Number(recent.avg_edge || 0),
      total_edge: Number(recent.total_edge || 0),
      avg_next_range: Number(recent.avg_next_range || 0),
    }
  } catch {
    return null
  }
}

function amountRatio(row: T0DataPullCandidate) {
  if (!Number.isFinite(row.amount) || !Number.isFinite(row.avg_amount_20d) || row.avg_amount_20d <= 0) return Number.NaN
  return row.amount / row.avg_amount_20d
}

function flowSignal(row: T0DataPullCandidate) {
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

export function T0AssistantPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [rows, setRows] = useState<T0Recommendation[]>([])
  const [pullCandidates, setPullCandidates] = useState<T0DataPullCandidate[]>([])
  const [backtests, setBacktests] = useState<T0DailyBacktest[]>([])
  const [timeMachineRows, setTimeMachineRows] = useState<T0TimeMachineResult[]>([])
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [timeMachineStatus, setTimeMachineStatus] = useState<RunStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [timeMachineRunning, setTimeMachineRunning] = useState(false)
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    setError('')
    Promise.all([listT0Recommendations(80), listT0DataPullCandidates(80), listT0DailyBacktests(80), listT0TimeMachineResults(80), getT0DailyResearchStatus(), getT0TimeMachineStatus()])
      .then(([nextRows, nextPullCandidates, nextBacktests, nextTimeMachineRows, nextStatus, nextTimeMachineStatus]) => {
        setRows(nextRows)
        setPullCandidates(nextPullCandidates)
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

  const runTimeMachine = () => {
    setTimeMachineRunning(true)
    setError('')
    runT0TimeMachine()
      .then(() => getT0TimeMachineStatus())
      .then(setTimeMachineStatus)
      .catch((err: Error) => setError(err.message || '启动做T时光机失败'))
      .finally(() => setTimeMachineRunning(false))
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

  const operationTop10 = useMemo(() => pullCandidates.slice(0, 10), [pullCandidates])
  const backtestByCode = useMemo(() => {
    const map = new Map<string, T0DailyBacktest>()
    backtests.forEach((row) => map.set(row.ts_code, row))
    return map
  }, [backtests])
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

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">T0 ASSISTANT</div>
            <h2>做T实盘观察清单</h2>
            <p className="recommendationMeta">先用时光机验证策略整体收益，再给今日 Top10 观察票；当前只给操作计划，不自动下单、不改仓位。</p>
          </div>
          <div className="tableHeaderRight">
            <button className="secondaryButton startButton" onClick={run} disabled={loading || running || isRunning}>
              {running || isRunning ? '运行中' : '运行日线评估'}
            </button>
            <button className="secondaryButton startButton" onClick={runTimeMachine} disabled={loading || timeMachineRunning || isTimeMachineRunning}>
              {timeMachineRunning || isTimeMachineRunning ? '时光机运行中' : '运行时光机'}
            </button>
            <button className="secondaryButton quietButton" onClick={load} disabled={loading}>
              <RefreshCw size={15} />{loading ? '刷新中' : '刷新'}
            </button>
          </div>
        </div>

        <div className="metricStrip">
          <div className={`metricCard ${timeMachineSummary.avgCombined > 0 ? 'good' : ''}`}>
            <span>策略结论</span>
            <b>{timeMachineSummary.verdict}</b>
            <em>{timeMachineSummary.grid?.best ? `最佳 ${timeMachineSummary.grid.best.lookback}/${timeMachineSummary.grid.best.eval_days} · ${timeMachineSummary.grid.best.anchor_count || 1}锚点` : timeMachineSummary.count > 0 ? `${timeMachineSummary.count} 只历史样本` : '先运行时光机'}</em>
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
            <em>{operationTop10.length} 只今日观察</em>
          </div>
        </div>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">ACTION LIST</div>
            <h2>今日 Top10 做T观察票</h2>
            <p className="recommendationMeta">只适合已有底仓做T观察；高抛、低吸、止损都是日线计划价，实盘要等盘中价格触发，不追价。</p>
          </div>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>排名</th>
                <th>股票</th>
                <th>评分 / 状态</th>
                <th>近2月做T收益</th>
                <th>资金 / 砸盘</th>
                <th>高抛价</th>
                <th>低吸价</th>
                <th>止损观察</th>
                <th>T仓建议</th>
                <th>风险</th>
              </tr>
            </thead>
            <tbody>
              {operationTop10.map((row, index) => {
                const plan = planBand(row)
                const recent = parseRecentT0Stats(backtestByCode.get(row.ts_code))
                const flow = flowSignal(row)
                return (
                  <tr key={row.ts_code}>
                    <td><strong>{index + 1}</strong></td>
                    <td>
                      <button className="tableActionButton" onClick={() => onOpenResearch?.(row.ts_code)}>
                        {row.name || row.ts_code}
                      </button>
                      <div className="mono">{row.ts_code}</div>
                      <div className="recommendationMeta">{row.industry || '—'} · {formatDate(row.trade_date)}</div>
                    </td>
                    <td>
                      <strong>{row.score.toFixed(1)}</strong>
                      <div><span className={`badge ${pullBadge(row.action)}`}>{row.action}</span></div>
                    </td>
                    <td>
                      <strong className={signedClass(recent?.total_edge ?? Number.NaN)}>{recent ? percent(recent.total_edge, true) : '—'}</strong>
                      <div className="recommendationMeta">
                        {recent ? `${recent.n_candidates}次 · 两边 ${percent(recent.two_sided_rate)}` : '需重跑日线评估'}
                      </div>
                      {recent?.start_date ? <div className="recommendationMeta">{formatDate(recent.start_date)} - {formatDate(recent.end_date)}</div> : null}
                    </td>
                    <td>
                      <span className={`badge ${flow.badge}`}>{flow.label}</span>
                      <div className={signedClass(row.today_pct)}>今日 {percent(row.today_pct, true)}</div>
                      <div className="recommendationMeta">成交额 {amountYi(row.amount)} / {flow.detail}</div>
                    </td>
                    <td>
                      <strong>{money(plan.reduce)}</strong>
                      <div className="recommendationMeta">现价上方 {percent((plan.reduce / row.price) - 1)}</div>
                    </td>
                    <td>
                      <strong>{money(plan.buy)}</strong>
                      <div className="recommendationMeta">现价下方 {percent(1 - (plan.buy / row.price))}</div>
                    </td>
                    <td className="negative">
                      <strong>{money(plan.stop)}</strong>
                      <div className="recommendationMeta">破位先停手</div>
                    </td>
                    <td>
                      <strong>{plan.tRatio}</strong>
                      <div className="recommendationMeta">仅用可T底仓</div>
                    </td>
                    <td>
                      <ul className="compactList">
                        {row.risks.slice(0, 2).map((risk) => <li key={risk}><AlertTriangle size={13} /> {risk}</li>)}
                        {row.risks.length === 0 ? <li>暂无显著风险</li> : null}
                      </ul>
                    </td>
                  </tr>
                )
              })}
              {!loading && operationTop10.length === 0 ? <tr><td colSpan={10} className="emptyCell">暂无 Top10，请先运行日线评估</td></tr> : null}
              {loading ? <tr><td colSpan={10} className="emptyCell">加载中...</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">DAILY TARGETS</div>
            <h2>日线候选明细</h2>
            <p className="recommendationMeta">这里是 Top10 的候选池证据，用来解释为什么入选，不作为第一眼的操作入口。</p>
          </div>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>股票</th>
                <th>计划优先级</th>
                <th>评分</th>
                <th>状态</th>
                <th>数据层</th>
                <th>日线特征</th>
                <th>依据</th>
                <th>风险</th>
              </tr>
            </thead>
            <tbody>
              {pullCandidates.map((row) => (
                <tr key={row.ts_code}>
                  <td>
                    <button className="tableActionButton" onClick={() => onOpenResearch?.(row.ts_code)}>
                      {row.name || row.ts_code}
                    </button>
                    <div className="mono">{row.ts_code}</div>
                    <div className="recommendationMeta">{row.industry || '—'} · {formatDate(row.trade_date)}</div>
                  </td>
                  <td><span className={`badge ${pullBadge(row.action)}`}>{row.action}</span></td>
                  <td><strong>{row.score.toFixed(1)}</strong></td>
                  <td>{row.state || '—'}</td>
                  <td>
                    <div>{row.target_freq || 'daily'}</div>
                    <div className="recommendationMeta">不依赖分钟线</div>
                  </td>
                  <td>
                    <div>现价 {money(row.price)}</div>
                    <div className={signedClass(row.today_pct)}>今日 {percent(row.today_pct, true)}</div>
                    <div className={signedClass(row.return_20d)}>20日 {percent(row.return_20d, true)}</div>
                    <div>振幅 {percent(row.avg_range_20d)} · 价差 {percent(row.expected_edge)}</div>
                  </td>
                  <td>
                    <ul className="compactList">
                      {row.reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}
                      {row.reasons.length === 0 ? <li>暂无正向依据</li> : null}
                    </ul>
                  </td>
                  <td>
                    <ul className="compactList">
                      {row.risks.slice(0, 3).map((risk) => <li key={risk}><AlertTriangle size={13} /> {risk}</li>)}
                      {row.risks.length === 0 ? <li>暂无显著风险</li> : null}
                    </ul>
                  </td>
                </tr>
              ))}
              {!loading && pullCandidates.length === 0 ? <tr><td colSpan={8} className="emptyCell">暂无日线候选，请先运行日线评估</td></tr> : null}
              {loading ? <tr><td colSpan={8} className="emptyCell">加载中...</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">TIME MACHINE</div>
            <h2>做T时光机整体收益</h2>
            <p className="recommendationMeta">在历史截面只用当时之前的数据选候选，再评估后续 20 个交易日底仓做T价差、标的涨跌和合并收益。</p>
          </div>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>股票</th>
                <th>区间</th>
                <th>评分</th>
                <th>做T价差</th>
                <th>标的涨跌</th>
                <th>合并收益</th>
                <th>完成次数</th>
                <th>最大回撤</th>
              </tr>
            </thead>
            <tbody>
              {timeMachineRows.map((row) => (
                <tr key={row.ts_code}>
                  <td>
                    <button className="tableActionButton" onClick={() => onOpenResearch?.(row.ts_code)}>
                      {row.name || row.ts_code}
                    </button>
                    <div className="mono">{row.ts_code}</div>
                    <div className="recommendationMeta">{row.industry || '—'}</div>
                  </td>
                  <td>
                    <div>{formatDate(row.as_of_date)}</div>
                    <div className="recommendationMeta">{formatDate(row.eval_start_date)} - {formatDate(row.eval_end_date)}</div>
                  </td>
                  <td><strong>{row.score.toFixed(1)}</strong></td>
                  <td className={signedClass(row.t0_edge)}>{percent(row.t0_edge, true)}</td>
                  <td className={signedClass(row.underlying_return)}>{percent(row.underlying_return, true)}</td>
                  <td className={signedClass(row.combined_return)}>{percent(row.combined_return, true)}</td>
                  <td>{row.two_sided_count}/{row.n_eval_days}<div className="recommendationMeta">单边 {row.one_sided_count}</div></td>
                  <td className="negative">{percent(row.max_drawdown)}</td>
                </tr>
              ))}
              {!loading && timeMachineRows.length === 0 ? <tr><td colSpan={8} className="emptyCell">暂无时光机结果，请先运行时光机</td></tr> : null}
              {loading ? <tr><td colSpan={8} className="emptyCell">加载中...</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">BACKTEST</div>
            <h2>日线近似回测</h2>
            <p className="recommendationMeta">只在次日 high/low 同时触达高抛和低吸区间时计为完成做T；不知道日内顺序，结果用于粗验规则正期望。</p>
          </div>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>股票</th>
                <th>评分</th>
                <th>样本</th>
                <th>两边触达</th>
                <th>单边触达</th>
                <th>平均价差</th>
                <th>累计价差</th>
                <th>次日振幅</th>
              </tr>
            </thead>
            <tbody>
              {backtests.map((row) => (
                <tr key={row.ts_code}>
                  <td>
                    <button className="tableActionButton" onClick={() => onOpenResearch?.(row.ts_code)}>
                      {row.name || row.ts_code}
                    </button>
                    <div className="mono">{row.ts_code}</div>
                    <div className="recommendationMeta">{row.industry || '—'}</div>
                  </td>
                  <td><strong>{row.score.toFixed(1)}</strong></td>
                  <td>{row.n_candidates} / {row.n_days} 日</td>
                  <td className={signedClass(row.two_sided_rate)}>{percent(row.two_sided_rate)}</td>
                  <td>{percent(row.one_sided_rate)}</td>
                  <td className={signedClass(row.avg_edge)}>{percent(row.avg_edge, true)}</td>
                  <td className={signedClass(row.total_edge)}>{percent(row.total_edge, true)}</td>
                  <td>{percent(row.avg_next_range)}</td>
                </tr>
              ))}
              {!loading && backtests.length === 0 ? <tr><td colSpan={8} className="emptyCell">暂无回测结果，请先运行日线评估</td></tr> : null}
              {loading ? <tr><td colSpan={8} className="emptyCell">加载中...</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">CANDIDATES</div>
            <h2>当前持仓做T建议</h2>
          </div>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>股票</th>
                <th>建议</th>
                <th>评分</th>
                <th>状态</th>
                <th>持仓 / 可T</th>
                <th>区间价</th>
                <th>近况</th>
                <th>依据</th>
                <th>风险</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.ts_code}>
                  <td>
                    <button className="tableActionButton" onClick={() => onOpenResearch?.(row.ts_code)}>
                      {row.name || row.ts_code}
                    </button>
                    <div className="mono">{row.ts_code}</div>
                    <div className="recommendationMeta">{row.industry || '—'} · {formatDate(row.trade_date)}</div>
                  </td>
                  <td>
                    <span className={`badge ${actionBadge(row.action)}`}>{row.action}</span>
                    <div className="recommendationMeta">{row.recommendation || '—'}</div>
                  </td>
                  <td><strong>{row.score.toFixed(1)}</strong></td>
                  <td>{row.state || '—'}</td>
                  <td>
                    <div>{numberText(row.shares)} / {numberText(row.max_t0_shares)}</div>
                    <div className="recommendationMeta">仓位 {percent(row.position_weight)}</div>
                  </td>
                  <td>
                    <div><Target size={14} /> 减 {money(row.reduce_price)}</div>
                    <div><LineChart size={14} /> 接 {money(row.buy_back_price)}</div>
                    <div><ShieldCheck size={14} /> 止 {money(row.stop_price)}</div>
                  </td>
                  <td>
                    <div>现价 {money(row.price)}</div>
                    <div className={signedClass(row.today_pct)}>今日 {percent(row.today_pct, true)}</div>
                    <div className={signedClass(row.return_20d)}>20日 {percent(row.return_20d, true)}</div>
                    <div>振幅 {percent(row.avg_range_20d)}</div>
                  </td>
                  <td>
                    <ul className="compactList">
                      {row.reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}
                      {row.reasons.length === 0 ? <li>暂无正向依据</li> : null}
                    </ul>
                  </td>
                  <td>
                    <ul className="compactList">
                      {row.risks.slice(0, 3).map((risk) => <li key={risk}><AlertTriangle size={13} /> {risk}</li>)}
                      {row.risks.length === 0 ? <li>暂无显著风险</li> : null}
                    </ul>
                  </td>
                </tr>
              ))}
              {!loading && rows.length === 0 ? <tr><td colSpan={9} className="emptyCell">暂无持仓或行情不足</td></tr> : null}
              {loading ? <tr><td colSpan={9} className="emptyCell">加载中...</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function pullBadge(action: string) {
  if (action === '优先计划') return 'success'
  if (action === '候选观察') return 'running'
  return 'created'
}
