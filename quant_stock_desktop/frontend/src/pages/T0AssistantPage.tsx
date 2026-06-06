import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, LineChart, RefreshCw, ShieldCheck, Target } from 'lucide-react'
import { listT0Recommendations, type T0Recommendation } from '../services/app'

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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    setError('')
    listT0Recommendations(80)
      .then(setRows)
      .catch((err: Error) => setError(err.message || '加载做T建议失败'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  const stats = useMemo(() => {
    const tradable = rows.filter((row) => row.action === '适合做T').length
    const watch = rows.filter((row) => row.action === '观察').length
    const avgScore = rows.length ? rows.reduce((sum, row) => sum + row.score, 0) / rows.length : 0
    const generatedTimes = rows.map((row) => row.generated_at).filter(Boolean).sort()
    const latest = generatedTimes.length ? generatedTimes[generatedTimes.length - 1] : ''
    return { tradable, watch, avgScore, latest }
  }, [rows])

  return (
    <div className="positionPage">
      {error ? <div className="errorBanner">{error}</div> : null}

      <section className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">T0 ASSISTANT</div>
            <h2>单票做T规则评分基线</h2>
            <p className="recommendationMeta">只读取当前持仓和最近日线，输出可观察区间；不下单、不改仓位，分钟线和盘口接入后再训练模型。</p>
          </div>
          <div className="tableHeaderRight">
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
            <span>观察</span>
            <b>{stats.watch}</b>
            <em>等待区间触发</em>
          </div>
          <div className="metricCard">
            <span>平均评分</span>
            <b>{rows.length ? stats.avgScore.toFixed(1) : '—'}</b>
            <em>{stats.latest ? `更新 ${formatDate(stats.latest.slice(0, 10).replace(/-/g, ''))}` : '无更新时间'}</em>
          </div>
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
