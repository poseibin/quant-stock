import { useEffect, useRef, useState } from 'react'
import {
  clearPositionPool,
  confirmPositionTrades,
  generatePositionSignal,
  getPositionRecommendation,
  getPositionSummary,
  getSignalRunStatus,
  type PositionRecommendation,
  type PositionSummary,
  type RunStatus,
  type TradeRequest
} from '../services/app'

function money(value: number) {
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function percent(value: number) {
  return `${(value * 100).toFixed(2)}%`
}

function signedClass(value: number) {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return ''
}

export const strategyNames: Record<string, string> = {
  small_cap_quality: '小盘质量',
  reversal: '业绩反转',
  forecast_revision: '业绩预告',
  trend_quality: '趋势质量',
  dividend_low_vol: '低波红利',
  garp_quality: '质量成长',
  moneyflow_pullback: '资金低吸',
  insider_buy: '高管增持',
  beijing_se: '北交所',
  lhb_follow: '龙虎榜跟踪',
  industry_rotation: '行业轮动'
}

export function strategyLabel(strategy: string) {
  return strategyNames[strategy] || strategy
}

const today = () => new Date().toISOString().slice(0, 10).replace(/-/g, '')

export function PositionPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [summary, setSummary] = useState<PositionSummary | null>(null)
  const [recommendation, setRecommendation] = useState<PositionRecommendation | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [error, setError] = useState('')
  const prevStateRef = useRef<string>('')

  const load = () => {
    setLoading(true)
    setError('')
    Promise.all([getPositionSummary(), getPositionRecommendation()])
      .then(([nextSummary, nextRecommendation]) => {
        setSummary(nextSummary)
        setRecommendation(nextRecommendation)
      })
      .catch((err: Error) => setError(err.message || '加载持仓失败'))
      .finally(() => setLoading(false))
  }

  const generate = () => {
    setError('')
    generatePositionSignal({}).catch((err: Error) => setError(err.message || '触发信号失败'))
  }

  const buildRebalanceTrades = (nextRecommendation: PositionRecommendation, nextSummary: PositionSummary): TradeRequest[] => {
    const currentShares = new Map(nextSummary.positions.map((item) => [item.ts_code, item.shares]))
    return nextRecommendation.rows.flatMap<TradeRequest>((item) => {
      if (item.price <= 0) return []
      const current = currentShares.get(item.ts_code) ?? 0
      const target = item.target_shares
      if (item.action === '新建') {
        if (target <= 0) return []
        return [{
          ts_code: item.ts_code,
          action: 'BUY',
          shares: target,
          price: item.price,
          date: nextRecommendation.date || today(),
          sources: item.sources
        }]
      }
      if (item.action === '加仓') {
        const shares = Math.max(0, target - current)
        if (shares <= 0) return []
        return [{
          ts_code: item.ts_code,
          action: 'BUY',
          shares,
          price: item.price,
          date: nextRecommendation.date || today(),
          sources: item.sources
        }]
      }
      if (item.action === '减仓' || item.action === '清仓') {
        const shares = item.action === '清仓' ? current : Math.max(0, current - target)
        if (shares <= 0) return []
        return [{
          ts_code: item.ts_code,
          action: 'SELL',
          shares,
          price: item.price,
          date: nextRecommendation.date || today(),
          sources: item.sources
        }]
      }
      return []
    })
  }

  const rebalancePositions = () => {
    if (!recommendation || !summary) return
    const trades = buildRebalanceTrades(recommendation, summary)
    if (trades.length === 0) {
      setError('当前推荐没有可执行的调仓单：股数或价格为空')
      return
    }
    setSaving(true)
    setError('')
    confirmPositionTrades(trades)
      .then((nextSummary) => {
        setSummary(nextSummary)
        return getPositionRecommendation()
      })
      .then((nextRecommendation) => setRecommendation(nextRecommendation))
      .catch((err: Error) => setError(err.message || '一键调仓失败'))
      .finally(() => setSaving(false))
  }

  const clearPositions = () => {
    if (!summary) return
    const ok = window.confirm('确认重置当前持仓账户？这会删除持仓和交易流水，并把账户恢复为初始现金。')
    if (!ok) return
    setClearing(true)
    setError('')
    clearPositionPool()
      .then((nextSummary) => {
        setSummary(nextSummary)
        return getPositionRecommendation()
      })
      .then((nextRecommendation) => setRecommendation(nextRecommendation))
      .catch((err: Error) => setError(err.message || '清空持仓失败'))
      .finally(() => setClearing(false))
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    let cancelled = false
    const tick = () => {
      getSignalRunStatus()
        .then((s) => {
          if (cancelled) return
          setRunStatus(s)
          const prev = prevStateRef.current
          prevStateRef.current = s.state
          if (s.state === 'done' && prev === 'running') {
            Promise.all([getPositionRecommendation(), getPositionSummary()])
              .then(([nextRec, nextSummary]) => {
                setRecommendation(nextRec)
                setSummary(nextSummary)
              })
              .catch(() => {})
          }
          if (s.state === 'error' && s.message && prev !== 'error') {
            setError(s.message)
          }
        })
        .catch(() => {})
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  const isRunning = runStatus?.state === 'running'
  const total = runStatus?.total ?? 0
  const idx = runStatus?.idx ?? 0
  const pct = total > 0 ? Math.min(100, Math.round((idx / total) * 100)) : 0
  const stage = runStatus?.stage || ''
  const name = runStatus?.name || ''
  const heartbeat = runStatus?.updated_at || ''
  const rebalanceCount = summary && recommendation
    ? buildRebalanceTrades(recommendation, summary).length
    : 0
  const rebalanced = recommendation?.rebalanced ?? false
  const recommendationMeta = recommendation
    ? rebalanced
      ? `信号日 ${recommendation.date} · 今日已调仓 ${recommendation.rebalance_trades || 0} 笔 · 当前持仓 ${summary?.n_holdings ?? 0} 只`
      : `信号日 ${recommendation.date} · 目标 ${recommendation.n_holdings} 只 / ${percent(recommendation.total_weight)} · 可执行 ${rebalanceCount} 笔 · 信号买 ${recommendation.n_buy} / 卖 ${recommendation.n_sell}`
    : ''
  const rebalanceDisabled = loading || saving || isRunning || rebalanceCount === 0 || rebalanced
  const clearDisabled = loading || saving || clearing || isRunning || !summary
  return (
    <div className="positionPage">
      {error ? <div className="errorBanner">{error}</div> : null}

      <div className="metricGrid">
        <Metric label="初始资金" value={summary ? money(summary.initial_cash) : '—'} />
        <Metric label="当前现金" value={summary ? money(summary.cash) : '—'} />
        <Metric label="持仓市值" value={summary ? money(summary.market_value) : '—'} />
        <Metric label="总资产" value={summary ? money(summary.total_assets) : '—'} />
        <Metric label="累计费用" value={summary ? money(summary.total_fee || 0) : '—'} />
        <Metric label="累计收益率" value={summary ? percent(summary.cum_return) : '—'} tone={summary ? signedClass(summary.cum_return) : ''} />
        <Metric label="浮动盈亏" value={summary ? money(summary.unrealized_pnl) : '—'} tone={summary ? signedClass(summary.unrealized_pnl) : ''} />
        <Metric label="浮盈率" value={summary ? percent(summary.unrealized_pct) : '—'} tone={summary ? signedClass(summary.unrealized_pct) : ''} />
        <Metric label="已实现盈亏" value={summary ? money(summary.realized_pnl) : '—'} tone={summary ? signedClass(summary.realized_pnl) : ''} />
        <Metric label="今日盈亏" value={summary ? money(summary.today_pnl) : '—'} tone={summary ? signedClass(summary.today_pnl) : ''} />
        <Metric label="今日涨跌%" value={summary ? percent(summary.today_pct) : '—'} tone={summary ? signedClass(summary.today_pct) : ''} />
        <Metric label="持仓数" value={summary ? `${summary.n_holdings} 只` : '—'} />
      </div>

      {isRunning ? (
        <div className="signalProgress signalProgressStandalone">
          <div className="signalProgressHeader">
            <span>{total > 0 ? `${stage || '处理中'} · ${name || ''}` : '正在启动 Python...'}</span>
            <span>{total > 0 ? `${idx}/${total} (${pct}%)` : (heartbeat ? `心跳 ${heartbeat}` : '')}</span>
          </div>
          <div className="signalProgressBar"><div className="signalProgressBarFill" style={{ width: total > 0 ? `${pct}%` : '15%' }} /></div>
        </div>
      ) : null}

      <div className="tableCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">TODAY SIGNAL</div>
            <p className="recommendationMeta">
              {recommendationMeta}
            </p>
          </div>
          <div className="tableHeaderRight">
            {!rebalanced ? (
              <button className="secondaryButton rebalanceButton" onClick={rebalancePositions} disabled={rebalanceDisabled}>
                {saving ? '调仓中...' : `一键调仓${rebalanceCount > 0 ? ` ${rebalanceCount}` : ''}`}
              </button>
            ) : null}
            <button className="secondaryButton dangerButton" onClick={clearPositions} disabled={clearDisabled}>{clearing ? '重置中...' : '重置账户'}</button>
            <button className="primaryButton" onClick={generate} disabled={isRunning}>{isRunning ? '生成中...' : '生成信号'}</button>
          </div>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>代码</th>
                <th>名称</th>
                <th>行业</th>
                <th>现价</th>
                <th>涨跌幅</th>
                <th>仓位变动</th>
                <th>Δ</th>
                <th>股数</th>
                <th>建仓金额</th>
                <th>来源策略</th>
              </tr>
            </thead>
            <tbody>
              {recommendation?.rows.map((item) => (
                <tr key={`${item.action}-${item.ts_code}`}>
                  <td className="mono">{item.ts_code}</td>
                  <td>
                    <span className="nameWithBadge">
                      <StockLink tsCode={item.ts_code} onOpenResearch={onOpenResearch}>{item.name || '—'}</StockLink>
                      <span className={`actionBadge inline ${actionClass(item.action)}`} title={item.action}>{actionShortLabel(item.action)}</span>
                    </span>
                  </td>
                  <td>{item.industry || '—'}</td>
                  <td>{item.price ? money(item.price) : '—'}</td>
                  <td className={signedClass(item.pct_chg)}>{item.pct_chg ? `${item.pct_chg.toFixed(2)}%` : '—'}</td>
                  <td>{percent(item.from_weight)} → {percent(item.to_weight)}</td>
                  <td className={signedClass(item.delta_weight)}>{percent(item.delta_weight)}</td>
                  <td>{item.target_shares ? item.target_shares.toLocaleString('zh-CN') : '—'}</td>
                  <td>{item.target_amount ? `¥${money(item.target_amount)}` : '—'}</td>
                  <td>{item.sources?.map((source) => `${strategyLabel(source.strategy)} ${percent(source.weight)}`).join(' / ') || '—'}</td>
                </tr>
              ))}
              {!loading && recommendation?.rows.length === 0 ? <tr><td colSpan={10} className="emptyCell">暂无推荐信号</td></tr> : null}
              {loading ? <tr><td colSpan={10} className="emptyCell">加载中...</td></tr> : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function StockLink({ tsCode, children, onOpenResearch }: { tsCode: string; children: string; onOpenResearch?: (tsCode: string) => void }) {
  return (
    <button className="stockLink" onClick={() => onOpenResearch?.(tsCode)} title="查看个股研究">
      {children}
    </button>
  )
}

function Metric({ label, value, tone = '' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="metricCard">
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
    </div>
  )
}

function actionClass(action: string) {
  if (action === '新建') return 'new'
  if (action === '加仓') return 'add'
  if (action === '清仓') return 'clear'
  if (action === '减仓') return 'trim'
  return 'hold'
}

function actionShortLabel(action: string) {
  if (action === '新建') return '新'
  if (action === '加仓') return '加'
  if (action === '减仓') return '减'
  if (action === '清仓') return '清'
  return '持'
}
