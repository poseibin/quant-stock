import { useEffect, useRef, useState } from 'react'
import {
  confirmPositionTrades,
  generatePositionSignal,
  getPositionRecommendation,
  getPositionSummary,
  getSignalRunStatus,
  listGovernanceDashboard,
  listRecommendationHindsight,
  refreshGovernanceAudit,
  refreshRecommendationHindsight,
  type GovernanceDashboard,
  type PositionRecommendation,
  type PositionSummary,
  type RecommendationHindsight,
  type RunStatus,
  type TradeRequest
} from '../services/app'

function money(value: number) {
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function percent(value: number) {
  return `${(value * 100).toFixed(2)}%`
}

function formatNullablePercent(value?: number | null, multiplier = 1) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return `${(value * multiplier).toFixed(2)}%`
}

function signedClass(value: number) {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return ''
}

const strategyNames: Record<string, string> = {
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

function strategyLabel(strategy: string) {
  return strategyNames[strategy] || strategy
}

const today = () => new Date().toISOString().slice(0, 10).replace(/-/g, '')

export function PositionPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [summary, setSummary] = useState<PositionSummary | null>(null)
  const [recommendation, setRecommendation] = useState<PositionRecommendation | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [hindsight, setHindsight] = useState<RecommendationHindsight[]>([])
  const [governance, setGovernance] = useState<GovernanceDashboard>(emptyGovernance())
  const [hindsightLoading, setHindsightLoading] = useState(false)
  const [governanceLoading, setGovernanceLoading] = useState(false)
  const [error, setError] = useState('')
  const prevStateRef = useRef<string>('')

  const load = () => {
    setLoading(true)
    setError('')
    Promise.all([getPositionSummary(), getPositionRecommendation(), listRecommendationHindsight(), listGovernanceDashboard()])
      .then(([nextSummary, nextRecommendation, nextHindsight, nextGovernance]) => {
        setSummary(nextSummary)
        setRecommendation(nextRecommendation)
        setHindsight(nextHindsight || [])
        setGovernance(nextGovernance || emptyGovernance())
      })
      .catch((err: Error) => setError(err.message || '加载持仓失败'))
      .finally(() => setLoading(false))
  }

  const generate = () => {
    setError('')
    generatePositionSignal({}).catch((err: Error) => setError(err.message || '触发信号失败'))
  }

  const refreshHindsight = () => {
    setHindsightLoading(true)
    setError('')
    refreshRecommendationHindsight()
      .then((rows) => setHindsight(rows || []))
      .catch((err: Error) => setError(err.message || '刷新推荐回看失败'))
      .finally(() => setHindsightLoading(false))
  }

  const refreshGovernance = () => {
    setGovernanceLoading(true)
    setError('')
    refreshGovernanceAudit()
      .then((dashboard) => {
        setGovernance(dashboard || emptyGovernance())
        setHindsight(dashboard?.hindsight || [])
      })
      .catch((err: Error) => setError(err.message || '刷新治理审计失败'))
      .finally(() => setGovernanceLoading(false))
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
  const hindsightSummary = summarizeHindsight(hindsight)
  const latestRisk = governance.risk?.[0]
  const topPromotions = (governance.promotion || []).slice(0, 6)
  const recentPaper = (governance.paper || []).slice(0, 6)
  const walkSummary = summarizeStatus(governance.walk || [], 'pass')
  const paramSummary = summarizeStatus(governance.params || [], 'stable')

  return (
    <div className="positionPage">
      {error ? <div className="errorBanner">{error}</div> : null}

      <div className="metricGrid">
        <Metric label="初始资金" value={summary ? money(summary.initial_cash) : '—'} />
        <Metric label="当前现金" value={summary ? money(summary.cash) : '—'} />
        <Metric label="持仓市值" value={summary ? money(summary.market_value) : '—'} />
        <Metric label="总资产" value={summary ? money(summary.total_assets) : '—'} />
        <Metric label="总成本" value={summary ? money(summary.total_cost) : '—'} />
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

      <div className="tableCard hindsightCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">SIGNAL HINDSIGHT</div>
            <p className="recommendationMeta">
              {hindsight.length
                ? `已回看 ${hindsight.length} 个信号日 · 加权 ${formatNullablePercent(hindsightSummary.weightedReturn)} · 等权 ${formatNullablePercent(hindsightSummary.equalReturn)} · 命中 ${formatNullablePercent(hindsightSummary.hitRate, 100)}`
                : '暂无推荐回看，生成过历史信号后可刷新'}
            </p>
          </div>
          <button className="secondaryButton" onClick={refreshHindsight} disabled={hindsightLoading}>
            {hindsightLoading ? '刷新中...' : '刷新回看'}
          </button>
        </div>
        {hindsight.length ? (
          <div className="hindsightStrip">
            {hindsight.slice(0, 8).map((item) => (
              <div className="hindsightItem" key={`${item.recommendation_date}-${item.horizon_days}`}>
                <span>{item.recommendation_date} → {item.next_date || '—'}</span>
                <strong className={signedClass(item.weighted_return || 0)}>{formatNullablePercent(item.weighted_return)}</strong>
                <em>命中 {formatNullablePercent(item.hit_rate, 100)} · {item.n_eval}/{item.n_holdings}</em>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <div className="tableCard governanceCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">GOVERNANCE AUDIT</div>
            <p className="recommendationMeta">多周期回看、风险暴露、模拟盘信号和策略晋级建议统一从 SQLite 审计结果读取</p>
          </div>
          <button className="secondaryButton startButton" onClick={refreshGovernance} disabled={governanceLoading}>
            {governanceLoading ? '审计中...' : '刷新治理审计'}
          </button>
        </div>
        <div className="governanceGrid">
          <div className="governanceBlock">
            <div className="miniCardTitle">风险暴露</div>
            {latestRisk ? (
              <>
                <div className="riskMetrics">
                  <span>持仓 {latestRisk.n_holdings}</span>
                  <span>总仓 {percent(latestRisk.total_weight)}</span>
                  <span>单票 {percent(latestRisk.max_single_weight)}</span>
                  <span>Top5 {percent(latestRisk.top5_weight)}</span>
                </div>
                <MiniWeightList values={latestRisk.industry} />
              </>
            ) : <div className="mutedText">暂无风险暴露快照</div>}
          </div>
          <div className="governanceBlock">
            <div className="miniCardTitle">策略晋级</div>
            {topPromotions.length ? topPromotions.map((item) => (
              <div className="governanceRow" key={`${item.strategy}-${item.strategy_version}`}>
                <span>{strategyLabel(item.strategy)} v{item.strategy_version}</span>
                <b>{promotionLabel(item.recommended_status)} · {Math.round(item.score * 100)}%</b>
              </div>
            )) : <div className="mutedText">暂无晋级建议</div>}
          </div>
          <div className="governanceBlock">
            <div className="miniCardTitle">模拟盘信号</div>
            {recentPaper.length ? recentPaper.map((item) => (
              <div className="governanceRow" key={item.id}>
                <span>{item.signal_date} {item.name || item.ts_code}</span>
                <b>{item.action} · {percent(item.target_weight)}</b>
              </div>
            )) : <div className="mutedText">暂无模拟盘日志</div>}
          </div>
          <div className="governanceBlock">
            <div className="miniCardTitle">Walk-forward</div>
            <div className="riskMetrics">
              <span>窗口 {walkSummary.total}</span>
              <span>通过 {walkSummary.pass}</span>
              <span>通过率 {formatNullablePercent(walkSummary.rate, 100)}</span>
              <span>失败 {walkSummary.fail}</span>
            </div>
          </div>
          <div className="governanceBlock">
            <div className="miniCardTitle">参数实验</div>
            <div className="riskMetrics">
              <span>实验 {paramSummary.total}</span>
              <span>稳定 {paramSummary.pass}</span>
              <span>稳定率 {formatNullablePercent(paramSummary.rate, 100)}</span>
              <span>不稳 {paramSummary.fail}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="tableCard">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">TODAY SIGNAL</div>
            <p className="recommendationMeta">
              {recommendationMeta}
            </p>
            {recommendation?.active_strategy_versions?.length ? (
              <div className="signalVersionPills">
                {recommendation.active_strategy_versions.map((item) => (
                  <span key={`${item.strategy}-${item.version}`}>{item.label || item.strategy} v{item.version || '—'} · {percent(item.weight || 0)}</span>
                ))}
              </div>
            ) : null}
          </div>
          <div className="tableHeaderRight">
            {!rebalanced ? (
              <button className="secondaryButton rebalanceButton" onClick={rebalancePositions} disabled={rebalanceDisabled}>
                {saving ? '调仓中...' : `一键调仓${rebalanceCount > 0 ? ` ${rebalanceCount}` : ''}`}
              </button>
            ) : null}
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

function MiniWeightList({ values }: { values: Record<string, number> }) {
  const rows = Object.entries(values || {})
    .map(([name, value]) => ({ name, value: Number(value) || 0 }))
    .sort((left, right) => right.value - left.value)
    .slice(0, 5)
  if (!rows.length) return <div className="mutedText">暂无权重分布</div>
  return (
    <div className="miniWeightList">
      {rows.map((item) => (
        <div key={item.name}>
          <span>{item.name}</span>
          <b>{percent(item.value)}</b>
        </div>
      ))}
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

function promotionLabel(status: string) {
  return ({
    research: '研究',
    paper: '进模拟',
    active_candidate: '可生效',
    rejected: '拒绝',
    active: '生效',
    promotable: '可模拟'
  } as Record<string, string>)[status] || status || '研究'
}

function emptyGovernance(): GovernanceDashboard {
  return { hindsight: [], risk: [], paper: [], promotion: [], walk: [], params: [] }
}

function summarizeStatus(rows: Array<{ status: string }>, passStatus: string) {
  const total = rows.length
  const pass = rows.filter((row) => row.status === passStatus).length
  const fail = rows.filter((row) => row.status === 'fail' || row.status === 'unstable' || row.status === 'rejected').length
  return { total, pass, fail, rate: total ? pass / total : null }
}

function summarizeHindsight(rows: RecommendationHindsight[]) {
  let weightedSum = 0
  let weightedCount = 0
  let equalSum = 0
  let equalCount = 0
  let hitSum = 0
  let hitCount = 0
  for (const row of rows) {
    if (typeof row.weighted_return === 'number' && Number.isFinite(row.weighted_return)) {
      weightedSum += row.weighted_return
      weightedCount += 1
    }
    if (typeof row.equal_weight_return === 'number' && Number.isFinite(row.equal_weight_return)) {
      equalSum += row.equal_weight_return
      equalCount += 1
    }
    if (typeof row.hit_rate === 'number' && Number.isFinite(row.hit_rate)) {
      hitSum += row.hit_rate
      hitCount += 1
    }
  }
  return {
    weightedReturn: weightedCount ? weightedSum / weightedCount : null,
    equalReturn: equalCount ? equalSum / equalCount : null,
    hitRate: hitCount ? hitSum / hitCount : null
  }
}
