import { useEffect, useMemo, useState } from 'react'
import {
  clearPositionPool,
  confirmPositionTrades,
  getPositionRecommendation,
  getPositionSummary,
  refreshPositionRealtimeQuotes,
  type PositionRecommendation,
  type PositionSummary,
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
  industry_rotation: '行业轮动',
  account_rebalance: '账户调仓',
  daily_recommendation: '通用策略',
  limit_up_momentum: '涨停预警',
  limit_breakout: '横盘预警',
  t0_daily: '做T助手',
  ml_factor_ranker: '通用因子',
  limit_up_model: '涨停预警',
  limit_breakout_model: '横盘预警'
}

export function strategyLabel(strategy: string) {
  return strategyNames[strategy] || strategy
}

const today = () => new Date().toISOString().slice(0, 10).replace(/-/g, '')

type PositionTab = 'holdings' | 'rebalance'

interface RebalancePlanRow {
  action: string
  tradeAction: 'BUY' | 'SELL'
  ts_code: string
  name: string
  industry: string
  current_shares: number
  target_shares: number
  trade_shares: number
  price: number
  amount: number
  from_weight: number
  to_weight: number
  delta_weight: number
  sources?: Array<{ strategy: string; weight: number }>
}

export function PositionPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [summary, setSummary] = useState<PositionSummary | null>(null)
  const [recommendation, setRecommendation] = useState<PositionRecommendation | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [refreshingQuotes, setRefreshingQuotes] = useState(false)
  const [activeTab, setActiveTab] = useState<PositionTab>('holdings')
  const [error, setError] = useState('')
  const [confirmReset, setConfirmReset] = useState(false)

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

  const buildRebalancePlan = (nextRecommendation: PositionRecommendation, nextSummary: PositionSummary): RebalancePlanRow[] => {
    const currentShares = new Map(nextSummary.positions.map((item) => [item.ts_code, item.shares]))
    return nextRecommendation.rows.flatMap<RebalancePlanRow>((item) => {
      if (item.price <= 0) return []
      const current = currentShares.get(item.ts_code) ?? 0
      const target = item.target_shares
      const base = {
        action: item.action,
        ts_code: item.ts_code,
        name: item.name,
        industry: item.industry,
        current_shares: current,
        target_shares: target,
        price: item.price,
        from_weight: item.from_weight,
        to_weight: item.to_weight,
        delta_weight: item.delta_weight,
        sources: item.sources
      }
      if (item.action === '新建') {
        if (target <= 0) return []
        return [{ ...base, tradeAction: 'BUY', trade_shares: target, amount: target * item.price }]
      }
      if (item.action === '加仓') {
        const shares = Math.max(0, target - current)
        if (shares <= 0) return []
        return [{ ...base, tradeAction: 'BUY', trade_shares: shares, amount: shares * item.price }]
      }
      if (item.action === '减仓' || item.action === '清仓') {
        const shares = item.action === '清仓' ? current : Math.max(0, current - target)
        if (shares <= 0) return []
        return [{ ...base, tradeAction: 'SELL', trade_shares: shares, amount: shares * item.price }]
      }
      return []
    })
  }

  const buildRebalanceTrades = (nextRecommendation: PositionRecommendation, nextSummary: PositionSummary): TradeRequest[] => {
    return buildRebalancePlan(nextRecommendation, nextSummary).map((item) => ({
      ts_code: item.ts_code,
      action: item.tradeAction,
      shares: item.trade_shares,
      price: item.price,
      date: nextRecommendation.date || today(),
      sources: item.sources
    }))
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

  const refreshRealtimeQuotes = () => {
    setRefreshingQuotes(true)
    setError('')
    refreshPositionRealtimeQuotes()
      .then((nextSummary) => {
        setSummary(nextSummary)
        return getPositionRecommendation()
      })
      .then((nextRecommendation) => setRecommendation(nextRecommendation))
      .catch((err: Error) => setError(err.message || '刷新实时价失败'))
      .finally(() => setRefreshingQuotes(false))
  }

  const clearPositions = () => {
    if (!summary) return
    if (!confirmReset) {
      setConfirmReset(true)
      setError('再次点击“确认重置”会清空持仓、交易流水和旧推荐信号。')
      return
    }
    setClearing(true)
    setError('')
    clearPositionPool()
      .then((nextSummary) => {
        setSummary(nextSummary)
        setRecommendation(null)
        setConfirmReset(false)
      })
      .catch((err: Error) => setError(err.message || '清空持仓失败'))
      .finally(() => setClearing(false))
  }

  useEffect(() => {
    load()
  }, [])

  const rebalancePlan = useMemo(
    () => summary && recommendation ? buildRebalancePlan(recommendation, summary) : [],
    [summary, recommendation]
  )
  const rebalanceCount = rebalancePlan.length
  const rebalanceStats = useMemo(() => buildRebalanceStats(rebalancePlan), [rebalancePlan])
  const rebalanced = recommendation?.rebalanced ?? false
  const recommendationMeta = recommendation
    ? rebalanced
      ? `决策日 ${recommendation.date} · 今日已调仓 ${recommendation.rebalance_trades || 0} 笔 · 当前持仓 ${summary?.n_holdings ?? 0} 只`
      : `决策日 ${recommendation.date} · 目标 ${recommendation.n_holdings} 只 / ${percent(recommendation.total_weight)} · 可执行 ${rebalanceCount} 笔 · 买 ${recommendation.n_buy} / 卖 ${recommendation.n_sell}`
    : ''
  const rebalanceDisabled = loading || saving || rebalanceCount === 0 || rebalanced
  const clearDisabled = loading || saving || clearing || refreshingQuotes || !summary
  return (
    <div className="positionPage">
      {error ? <div className="errorBanner">{error}</div> : null}

      <div className="positionTabs" role="tablist" aria-label="持仓管理页签">
        <button className={activeTab === 'holdings' ? 'active' : ''} onClick={() => setActiveTab('holdings')}>当前持仓</button>
        <button className={activeTab === 'rebalance' ? 'active' : ''} onClick={() => setActiveTab('rebalance')}>一键调仓</button>
      </div>

      {activeTab === 'holdings' ? <HoldingsPanel
        summary={summary}
        loading={loading}
        clearing={clearing}
        refreshingQuotes={refreshingQuotes}
        confirmReset={confirmReset}
        clearDisabled={clearDisabled}
        onRefreshRealtimeQuotes={refreshRealtimeQuotes}
        onClear={clearPositions}
        onOpenResearch={onOpenResearch}
      /> : null}

      {activeTab === 'rebalance' ? <RebalancePanel
        recommendation={recommendation}
        loading={loading}
        saving={saving}
        rebalanced={rebalanced}
        rebalanceDisabled={rebalanceDisabled}
        recommendationMeta={recommendationMeta}
        plan={rebalancePlan}
        stats={rebalanceStats}
        onRebalance={rebalancePositions}
        onOpenResearch={onOpenResearch}
      /> : null}
    </div>
  )
}

function HoldingsPanel({ summary, loading, clearing, refreshingQuotes, confirmReset, clearDisabled, onRefreshRealtimeQuotes, onClear, onOpenResearch }: {
  summary: PositionSummary | null
  loading: boolean
  clearing: boolean
  refreshingQuotes: boolean
  confirmReset: boolean
  clearDisabled: boolean
  onRefreshRealtimeQuotes: () => void
  onClear: () => void
  onOpenResearch?: (tsCode: string) => void
}) {
  return (
    <div className="tableCard">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">HOLDINGS</div>
          <p className="recommendationMeta">当前账户现金、持仓和浮动盈亏</p>
        </div>
        <div className="tableHeaderRight">
          <button className="secondaryButton" onClick={onRefreshRealtimeQuotes} disabled={clearDisabled || loading}>
            {refreshingQuotes ? '刷新中...' : '刷新实时价'}
          </button>
          <button className="secondaryButton dangerButton" onClick={onClear} disabled={clearDisabled}>{clearing ? '重置中...' : confirmReset ? '确认重置' : '重置账户'}</button>
        </div>
      </div>
      <div className="metricGrid holdingsMetricGrid">
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
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th>行业</th>
              <th>来源策略</th>
              <th>持股</th>
              <th>成本价</th>
              <th>现价</th>
              <th>市值</th>
              <th>仓位</th>
              <th>浮动盈亏</th>
              <th>浮盈率</th>
              <th>今日盈亏</th>
            </tr>
          </thead>
          <tbody>
            {summary?.positions.map((item) => (
              <tr key={item.ts_code}>
                <td className="mono">{item.ts_code}</td>
                <td><StockLink tsCode={item.ts_code} onOpenResearch={onOpenResearch}>{item.name || '—'}</StockLink></td>
                <td>{item.industry || '—'}</td>
                <td>{item.sources?.map((source) => `${strategyLabel(source.strategy)} ${percent(source.weight)}`).join(' / ') || '—'}</td>
                <td>{item.shares.toLocaleString('zh-CN')}</td>
                <td>{money(item.avg_cost)}</td>
                <td>{money(item.price)}</td>
                <td>¥{money(item.market_value)}</td>
                <td>{percent(item.weight)}</td>
                <td className={signedClass(item.unrealized_pnl)}>{money(item.unrealized_pnl)}</td>
                <td className={signedClass(item.unrealized_pct)}>{percent(item.unrealized_pct)}</td>
                <td className={signedClass(item.today_pnl)}>{money(item.today_pnl)}</td>
              </tr>
            ))}
            {!loading && (summary?.positions.length ?? 0) === 0 ? <tr><td colSpan={12} className="emptyCell">暂无持仓</td></tr> : null}
            {loading ? <tr><td colSpan={12} className="emptyCell">加载中...</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function RebalancePanel({ recommendation, loading, saving, rebalanced, rebalanceDisabled, recommendationMeta, plan, stats, onRebalance, onOpenResearch }: {
  recommendation: PositionRecommendation | null
  loading: boolean
  saving: boolean
  rebalanced: boolean
  rebalanceDisabled: boolean
  recommendationMeta: string
  plan: RebalancePlanRow[]
  stats: ReturnType<typeof buildRebalanceStats>
  onRebalance: () => void
  onOpenResearch?: (tsCode: string) => void
}) {
  return (
    <div className="tableCard">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">REBALANCE</div>
          <p className="recommendationMeta">
            {recommendation?.date ? recommendationMeta : '等待通用、做T、横盘和涨停推荐生成后查看调仓计划'}
          </p>
        </div>
        <div className="tableHeaderRight">
          {!rebalanced ? (
            <button className="secondaryButton rebalanceButton" onClick={onRebalance} disabled={rebalanceDisabled}>
              {saving ? '调仓中...' : `执行调仓${plan.length > 0 ? ` ${plan.length}` : ''}`}
            </button>
          ) : null}
        </div>
      </div>
      <div className="metricGrid rebalanceMetricGrid">
        <Metric label="买入笔数" value={`${stats.buyCount} 笔`} />
        <Metric label="卖出笔数" value={`${stats.sellCount} 笔`} />
        <Metric label="买入金额" value={`¥${money(stats.buyAmount)}`} />
        <Metric label="卖出金额" value={`¥${money(stats.sellAmount)}`} />
        <Metric label="净买入" value={`¥${money(stats.netBuyAmount)}`} tone={signedClass(stats.netBuyAmount)} />
        <Metric label="清仓/减仓/加仓/新建" value={`${stats.clearCount}/${stats.trimCount}/${stats.addCount}/${stats.newCount}`} />
      </div>
      <div className="tableWrap rebalanceTableWrap">
        <table>
          <thead>
            <tr>
              <th>动作</th>
              <th>代码</th>
              <th>名称</th>
              <th>行业</th>
              <th>现持股</th>
              <th>目标股</th>
              <th>交易股数</th>
              <th>成交价</th>
              <th>交易金额</th>
              <th>仓位变化</th>
              <th>来源策略</th>
            </tr>
          </thead>
          <tbody>
            {plan.map((item) => (
              <tr key={`${item.action}-${item.ts_code}`}>
                <td><span className={`actionBadge ${actionClass(item.action)}`}>{item.action}</span></td>
                <td className="mono">{item.ts_code}</td>
                <td><StockLink tsCode={item.ts_code} onOpenResearch={onOpenResearch}>{item.name || '—'}</StockLink></td>
                <td>{item.industry || '—'}</td>
                <td>{item.current_shares.toLocaleString('zh-CN')}</td>
                <td>{item.target_shares.toLocaleString('zh-CN')}</td>
                <td className={item.tradeAction === 'BUY' ? 'positive' : 'negative'}>{item.tradeAction === 'BUY' ? '+' : '-'}{item.trade_shares.toLocaleString('zh-CN')}</td>
                <td>{money(item.price)}</td>
                <td>¥{money(item.amount)}</td>
                <td>{percent(item.from_weight)} → {percent(item.to_weight)}</td>
                <td>{item.sources?.map((source) => `${strategyLabel(source.strategy)} ${percent(source.weight)}`).join(' / ') || '—'}</td>
              </tr>
            ))}
            {!loading && plan.length === 0 ? <tr><td colSpan={11} className="emptyCell">暂无可执行调仓单</td></tr> : null}
            {loading ? <tr><td colSpan={11} className="emptyCell">加载中...</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function buildRebalanceStats(plan: RebalancePlanRow[]) {
  const buyRows = plan.filter((item) => item.tradeAction === 'BUY')
  const sellRows = plan.filter((item) => item.tradeAction === 'SELL')
  const sumAmount = (rows: RebalancePlanRow[]) => rows.reduce((sum, item) => sum + item.amount, 0)
  return {
    buyCount: buyRows.length,
    sellCount: sellRows.length,
    buyAmount: sumAmount(buyRows),
    sellAmount: sumAmount(sellRows),
    netBuyAmount: sumAmount(buyRows) - sumAmount(sellRows),
    clearCount: plan.filter((item) => item.action === '清仓').length,
    trimCount: plan.filter((item) => item.action === '减仓').length,
    addCount: plan.filter((item) => item.action === '加仓').length,
    newCount: plan.filter((item) => item.action === '新建').length
  }
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
