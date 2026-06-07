import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, LineChart, RefreshCw, ShieldCheck, Target } from 'lucide-react'
import { getT0DailyResearchStatus, listT0DailyBacktests, listT0DataPullCandidates, listT0Recommendations, runT0DailyResearch, type RunStatus, type T0DailyBacktest, type T0DataPullCandidate, type T0Recommendation } from '../services/app'

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

export function T0AssistantPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [rows, setRows] = useState<T0Recommendation[]>([])
  const [pullCandidates, setPullCandidates] = useState<T0DataPullCandidate[]>([])
  const [backtests, setBacktests] = useState<T0DailyBacktest[]>([])
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    setError('')
    Promise.all([listT0Recommendations(80), listT0DataPullCandidates(80), listT0DailyBacktests(80), getT0DailyResearchStatus()])
      .then(([nextRows, nextPullCandidates, nextBacktests, nextStatus]) => {
        setRows(nextRows)
        setPullCandidates(nextPullCandidates)
        setBacktests(nextBacktests)
        setRunStatus(nextStatus)
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

  const stats = useMemo(() => {
    const tradable = rows.filter((row) => row.action === '适合做T').length
    const priorityPulls = pullCandidates.filter((row) => row.action === '优先计划').length
    const generatedTimes = [...rows.map((row) => row.generated_at), ...pullCandidates.map((row) => row.generated_at)].filter(Boolean).sort()
    const latest = generatedTimes.length ? generatedTimes[generatedTimes.length - 1] : ''
    return { tradable, priorityPulls, latest }
  }, [rows, pullCandidates])
  const isRunning = runStatus?.state === 'running'
  const total = runStatus?.total ?? 0
  const idx = runStatus?.idx ?? 0
  const pct = total > 0 ? Math.min(100, Math.round((idx / total) * 100)) : 0

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

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">T0 ASSISTANT</div>
            <h2>日线做T计划与回测</h2>
            <p className="recommendationMeta">Go 只负责编排和展示，日线评分与近似回测由 Python 研究引擎落库；当前不训练模型、不下单、不改仓位。</p>
          </div>
          <div className="tableHeaderRight">
            <button className="secondaryButton startButton" onClick={run} disabled={loading || running || isRunning}>
              {running || isRunning ? '运行中' : '运行日线评估'}
            </button>
            <button className="secondaryButton quietButton" onClick={load} disabled={loading}>
              <RefreshCw size={15} />{loading ? '刷新中' : '刷新'}
            </button>
          </div>
        </div>

        <div className="metricStrip">
          <div className="metricCard">
            <span>持仓候选</span>
            <b>{rows.length}</b>
            <em>当前账户持仓</em>
          </div>
          <div className="metricCard good">
            <span>适合做T</span>
            <b>{stats.tradable}</b>
            <em>满足价差和底仓</em>
          </div>
          <div className="metricCard">
            <span>日线候选</span>
            <b>{pullCandidates.length}</b>
            <em>日线全市场粗筛</em>
          </div>
          <div className="metricCard">
            <span>优先计划</span>
            <b>{stats.priorityPulls}</b>
            <em>{stats.latest ? `更新 ${formatDate(stats.latest.slice(0, 10).replace(/-/g, ''))}` : '无更新时间'}</em>
          </div>
        </div>
      </section>

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">DAILY TARGETS</div>
            <h2>日线做T计划候选</h2>
            <p className="recommendationMeta">用最近日线筛选适合底仓做T的股票；后续每日收盘生成明日高抛/低吸计划。</p>
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
