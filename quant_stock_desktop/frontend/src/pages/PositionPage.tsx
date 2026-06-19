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
  profit_arena: '通用策略',
  profit_arena_model: '通用策略'
}

export function strategyLabel(strategy: string) {
  return strategyNames[strategy] || '非生产来源'
}

function sourceText(sources?: Array<{ strategy: string; weight: number }>) {
  const visible = (sources || []).filter((source) =>
    (source.strategy === 'profit_arena_model' || source.strategy === 'profit_arena') && Number(source.weight || 0) > 0
  )
  return visible.map((source) => `${strategyLabel(source.strategy)} ${percent(source.weight)}`).join(' / ') || '—'
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
  buy_trigger_price: number
  sell_target_price: number
  stop_price: number
  trigger_type: 'buy_below' | 'sell_above' | 'stop_below' | ''
  trigger_price: number
  triggered: boolean
  trigger_label: string
  sources?: Array<{ strategy: string; weight: number }>
}

function buyTriggerState(price: number, triggerPrice: number) {
  if (!Number.isFinite(triggerPrice) || triggerPrice <= 0) {
    return { trigger_type: '' as const, trigger_price: 0, triggered: true, trigger_label: '无条件价' }
  }
  const triggered = price <= triggerPrice
  return {
    trigger_type: 'buy_below' as const,
    trigger_price: triggerPrice,
    triggered,
    trigger_label: triggered ? `已到买入价 ≤¥${money(triggerPrice)}` : `等待买入价 ≤¥${money(triggerPrice)}`
  }
}

function sellTriggerState(price: number, sellTargetPrice: number, stopPrice: number) {
  if (Number.isFinite(stopPrice) && stopPrice > 0 && price <= stopPrice) {
    return {
      trigger_type: 'stop_below' as const,
      trigger_price: stopPrice,
      triggered: true,
      trigger_label: `跌破止损 ≤¥${money(stopPrice)}`
    }
  }
  if (Number.isFinite(sellTargetPrice) && sellTargetPrice > 0) {
    const triggered = price >= sellTargetPrice
    return {
      trigger_type: 'sell_above' as const,
      trigger_price: sellTargetPrice,
      triggered,
      trigger_label: triggered ? `已到卖出价 ≥¥${money(sellTargetPrice)}` : `等待卖出价 ≥¥${money(sellTargetPrice)}`
    }
  }
  return { trigger_type: '' as const, trigger_price: 0, triggered: true, trigger_label: '无条件价' }
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
  const [quoteNotice, setQuoteNotice] = useState('')
  const [quoteState, setQuoteState] = useState('')
  const [confirmReset, setConfirmReset] = useState(false)

  const load = async () => {
    setLoading(true)
    setError('')
    setQuoteNotice('')
    setQuoteState('')
    let quoteWarning = ''
    try {
      let nextSummary: PositionSummary
      try {
        nextSummary = await refreshPositionRealtimeQuotes()
      } catch (err) {
        quoteWarning = err instanceof Error ? err.message : '刷新实时价失败'
        nextSummary = await getPositionSummary()
      }
      setSummary(nextSummary)
      if (quoteWarning) {
        setQuoteState('fallback')
        setQuoteNotice(`${quoteWarning}，已显示最近一次持仓估值`)
      } else {
        setQuoteState(nextSummary.quote_status || '')
        setQuoteNotice(nextSummary.quote_message || '')
      }
      try {
        const nextRecommendation = await getPositionRecommendation()
        setRecommendation(nextRecommendation)
      } catch (err) {
        setRecommendation(null)
        setError(err instanceof Error ? `持仓估值已刷新，但调仓计划加载失败：${err.message}` : '持仓估值已刷新，但调仓计划加载失败')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载持仓失败')
    } finally {
      setLoading(false)
    }
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
        buy_trigger_price: item.buy_trigger_price || 0,
        sell_target_price: item.sell_target_price || 0,
        stop_price: item.stop_price || 0,
        sources: item.sources
      }
      if (item.action === '新建') {
        if (target <= 0) return []
        const trigger = buyTriggerState(item.price, item.buy_trigger_price)
        return [{ ...base, ...trigger, tradeAction: 'BUY', trade_shares: target, amount: target * item.price }]
      }
      if (item.action === '加仓') {
        const shares = Math.max(0, target - current)
        if (shares <= 0) return []
        const trigger = buyTriggerState(item.price, item.buy_trigger_price)
        return [{ ...base, ...trigger, tradeAction: 'BUY', trade_shares: shares, amount: shares * item.price }]
      }
      if (item.action === '减仓' || item.action === '清仓') {
        const shares = item.action === '清仓' ? current : Math.max(0, current - target)
        if (shares <= 0) return []
        const trigger = sellTriggerState(item.price, item.sell_target_price, item.stop_price)
        return [{ ...base, ...trigger, tradeAction: 'SELL', trade_shares: shares, amount: shares * item.price }]
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
      trigger_type: item.trigger_type,
      trigger_price: item.trigger_price,
      sources: item.sources
    }))
  }

  const rebalancePositions = () => {
    if (!recommendation || !summary) return
    const trades = buildRebalanceTrades(recommendation, summary)
    if (trades.length === 0) {
      setError('当前没有达到条件价的调仓单：未到条件买入价/卖出价/止损价前不执行')
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
    setQuoteNotice('')
    setQuoteState('')
    refreshPositionRealtimeQuotes()
      .then((nextSummary) => {
        setSummary(nextSummary)
        setQuoteState(nextSummary.quote_status || 'success')
        setQuoteNotice(nextSummary.quote_message || '实时行情刷新完成')
        return getPositionRecommendation()
          .then((nextRecommendation) => setRecommendation(nextRecommendation))
          .catch((err: Error) => {
            setError(err.message ? `实时行情已刷新，但调仓计划刷新失败：${err.message}` : '实时行情已刷新，但调仓计划刷新失败')
          })
      })
      .catch((err: Error) => {
        setQuoteState('fallback')
        setQuoteNotice(`${err.message || '刷新实时价失败'}，已保留最近一次持仓估值`)
      })
      .finally(() => setRefreshingQuotes(false))
  }

  const clearPositions = () => {
    if (!summary) return
    if (!confirmReset) {
      setConfirmReset(true)
      setError('再次点击“确认重置”会清空持仓、交易流水和本地买入清单缓存。')
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
  const executablePlan = useMemo(() => rebalancePlan.filter((item) => item.triggered), [rebalancePlan])
  const rebalanceCount = executablePlan.length
  const rebalanceStats = useMemo(() => buildRebalanceStats(executablePlan), [executablePlan])
  const plannedStats = useMemo(() => buildRebalanceStats(rebalancePlan), [rebalancePlan])
  const rebalanced = recommendation?.rebalanced ?? false
  const arenaMetaText = recommendation ? profitArenaRecommendationMetaText(recommendation.metadata) : ''
  const recommendationMeta = recommendation
    ? `决策日 ${recommendation.date} · 买入清单 ${rebalancePlan.length} 只 / ${percent(recommendation.total_weight)} · 条件价可执行 ${rebalanceCount} 笔 · 买 ${rebalanceStats.buyCount} / 卖 ${rebalanceStats.sellCount}${rebalanced ? ` · 今日已执行 ${recommendation.rebalance_trades || 0} 笔` : ''}${arenaMetaText ? ` · ${arenaMetaText}` : ''}`
    : ''
  const rebalanceDisabled = loading || saving || rebalanceCount === 0
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
        quoteNotice={quoteNotice}
        quoteState={quoteState}
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
        plannedStats={plannedStats}
        onRebalance={rebalancePositions}
        onOpenResearch={onOpenResearch}
      /> : null}
    </div>
  )
}

function HoldingsPanel({ summary, loading, clearing, refreshingQuotes, confirmReset, quoteNotice, quoteState, clearDisabled, onRefreshRealtimeQuotes, onClear, onOpenResearch }: {
  summary: PositionSummary | null
  loading: boolean
  clearing: boolean
  refreshingQuotes: boolean
  confirmReset: boolean
  quoteNotice: string
  quoteState: string
  clearDisabled: boolean
  onRefreshRealtimeQuotes: () => void
  onClear: () => void
  onOpenResearch?: (tsCode: string) => void
}) {
  const effectiveQuoteState = quoteState || summary?.quote_status || ''
  const quoteMeta = quoteMetaText(summary)
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
      <div className="modelChecklist quoteStatusChecklist">
        <div>
          <span className={`badge ${quoteBadgeClass(effectiveQuoteState)}`}>{quoteStatusLabel(effectiveQuoteState)}</span>
          <span>{quoteNotice || summary?.quote_message || '实时行情状态等待刷新；失败时会自动保留最近估值或使用日线收盘价兜底。'}{quoteMeta ? ` · ${quoteMeta}` : ''}</span>
        </div>
      </div>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th>行业</th>
              <th>来源模型</th>
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
                <td>{sourceText(item.sources)}</td>
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
      <div className="tableHeader accountLedgerHeader">
        <div>
          <div className="sectionLabel">ACCOUNT LEDGER</div>
          <p className="recommendationMeta">最近买卖流水、成交后现金和已实现盈亏</p>
        </div>
      </div>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>日期</th>
              <th>方向</th>
              <th>代码</th>
              <th>名称</th>
              <th>股数</th>
              <th>成交价</th>
              <th>成交额</th>
              <th>费用</th>
              <th>净现金流</th>
              <th>成交后现金</th>
              <th>已实现盈亏</th>
            </tr>
          </thead>
          <tbody>
            {summary?.trades?.map((trade) => (
              <tr key={trade.id || `${trade.date}-${trade.ts_code}-${trade.action}-${trade.shares}`}>
                <td>{trade.date || '—'}</td>
                <td>{trade.action === 'buy' ? '买入' : trade.action === 'sell' ? '卖出' : trade.action}</td>
                <td className="mono">{trade.ts_code}</td>
                <td><StockLink tsCode={trade.ts_code} onOpenResearch={onOpenResearch}>{trade.name || '—'}</StockLink></td>
                <td>{trade.shares.toLocaleString('zh-CN')}</td>
                <td>{money(trade.price)}</td>
                <td>¥{money(trade.amount)}</td>
                <td>¥{money(trade.fee || 0)}</td>
                <td>{trade.action === 'buy' ? '-' : '+'}¥{money(trade.net_amount || 0)}</td>
                <td>¥{money(trade.cash_after || 0)}</td>
                <td className={signedClass(trade.realized_pnl || 0)}>{money(trade.realized_pnl || 0)}</td>
              </tr>
            ))}
            {!loading && (summary?.trades?.length ?? 0) === 0 ? <tr><td colSpan={11} className="emptyCell">暂无交易流水</td></tr> : null}
            {loading ? <tr><td colSpan={11} className="emptyCell">加载中...</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function quoteStatusLabel(status: string) {
  if (status === 'success') return '实时价'
  if (status === 'fallback') return '日线兜底'
  if (status === 'error') return '保留估值'
  if (status === 'idle') return '空闲'
  return '等待刷新'
}

function quoteBadgeClass(status: string) {
  if (status === 'success') return 'success'
  if (status === 'fallback') return 'running'
  if (status === 'error') return 'failed'
  return 'created'
}

function quoteMetaText(summary: PositionSummary | null) {
  if (!summary) return ''
  const parts: string[] = []
  if (summary.quote_source) parts.push(`来源 ${quoteSourceLabel(summary.quote_source)}`)
  if (summary.quote_updated_at) parts.push(`刷新 ${compactDateTime(summary.quote_updated_at)}`)
  return parts.join(' · ')
}

function quoteSourceLabel(source: string) {
  if (source === 'realtime') return '实时行情'
  if (source === 'realtime+latest_close') return '实时行情+日线收盘'
  if (source === 'cached') return '最近估值'
  if (source === 'none') return '无持仓'
  return source
}

function compactDateTime(value: string) {
  const text = String(value || '').trim()
  if (!text) return ''
  const normalized = text.replace('T', ' ').replace(/\.\d+Z?$/, '').replace(/Z$/, '')
  return normalized.slice(0, 19)
}

function RebalancePanel({ recommendation, loading, saving, rebalanced, rebalanceDisabled, recommendationMeta, plan, stats, plannedStats, onRebalance, onOpenResearch }: {
  recommendation: PositionRecommendation | null
  loading: boolean
  saving: boolean
  rebalanced: boolean
  rebalanceDisabled: boolean
  recommendationMeta: string
  plan: RebalancePlanRow[]
  stats: ReturnType<typeof buildRebalanceStats>
  plannedStats: ReturnType<typeof buildRebalanceStats>
  onRebalance: () => void
  onOpenResearch?: (tsCode: string) => void
}) {
  const executableCount = plan.filter((item) => item.triggered).length
  const waitingCount = Math.max(0, plan.length - executableCount)
  return (
    <div className="tableCard">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">REBALANCE</div>
          <p className="recommendationMeta">
            {recommendation?.date ? recommendationMeta : '等待通用策略买入清单生成后查看调仓计划；链路为数据更新 -> 因子截面 -> 买入清单 -> 条件价执行'}
          </p>
        </div>
        <div className="tableHeaderRight">
          <button className="secondaryButton rebalanceButton" onClick={onRebalance} disabled={rebalanceDisabled}>
            {saving ? '执行中...' : executableCount > 0 ? `执行已触发 ${executableCount} 笔` : '等待条件价'}
          </button>
        </div>
      </div>
      <div className={`productionReadinessBanner positionExecutionBanner ${executableCount > 0 ? 'ready' : recommendation?.date ? 'running' : 'blocked'}`}>
        <div>
          <span>通用策略调仓门禁</span>
          <b>{executableCount > 0 ? `可执行 ${executableCount} 笔` : recommendation?.date ? '等待条件价触发' : '等待买入清单'}</b>
          <em>{recommendation?.date ? `只执行已达到买入价/卖出价/止损价的订单；未触发的 ${waitingCount} 笔不会下单` : '请先完成数据更新、因子快照和通用策略推理'}</em>
        </div>
        <div className="productionReadinessSteps">
          <span className={recommendation?.date ? 'pass' : 'wait'}>清单 {recommendation?.date || '等待'}</span>
          <span className={plannedStats.buyCount > 0 ? 'pass' : 'wait'}>计划买 {plannedStats.buyCount}</span>
          <span className={plannedStats.sellCount > 0 ? 'pass' : 'wait'}>计划卖 {plannedStats.sellCount}</span>
          <span className={executableCount > 0 ? 'pass' : 'run'}>已触发 {executableCount}</span>
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
              <th>来源模型</th>
              <th>行业</th>
              <th>现持股</th>
              <th>目标股</th>
              <th>交易股数</th>
              <th>触发状态</th>
              <th>条件价</th>
              <th>当前/成交价</th>
              <th>交易金额</th>
              <th>仓位变化</th>
            </tr>
          </thead>
          <tbody>
            {plan.map((item) => (
              <tr key={`${item.action}-${item.ts_code}`}>
                <td><span className={`actionBadge ${actionClass(item.action)}`}>{item.action}</span></td>
                <td className="mono">{item.ts_code}</td>
                <td><StockLink tsCode={item.ts_code} onOpenResearch={onOpenResearch}>{item.name || '—'}</StockLink></td>
                <td>{sourceText(item.sources)}</td>
                <td>{item.industry || '—'}</td>
                <td>{item.current_shares.toLocaleString('zh-CN')}</td>
                <td>{item.target_shares.toLocaleString('zh-CN')}</td>
                <td className={item.tradeAction === 'BUY' ? 'positive' : 'negative'}>{item.tradeAction === 'BUY' ? '+' : '-'}{item.trade_shares.toLocaleString('zh-CN')}</td>
                <td>
                  <span className={`badge ${item.triggered ? 'success' : 'running'}`}>{item.triggered ? '已触发' : '等待触发'}</span>
                  <div className="recommendationMeta">{item.trigger_label}</div>
                </td>
                <td>{triggerPriceText(item)}</td>
                <td>{money(item.price)}</td>
                <td>¥{money(item.amount)}</td>
                <td>{percent(item.from_weight)} → {percent(item.to_weight)}</td>
              </tr>
            ))}
            {!loading && plan.length === 0 ? <tr><td colSpan={13} className="emptyCell">暂无通用策略调仓计划；请先确认买入清单已生成，且持仓页已刷新最新实时价</td></tr> : null}
            {loading ? <tr><td colSpan={13} className="emptyCell">加载中...</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function triggerPriceText(item: RebalancePlanRow) {
  if (item.tradeAction === 'BUY') {
    return item.buy_trigger_price > 0 ? `买入 ≤ ¥${money(item.buy_trigger_price)}` : '无买入条件'
  }
  const parts: string[] = []
  if (item.sell_target_price > 0) parts.push(`卖出 ≥ ¥${money(item.sell_target_price)}`)
  if (item.stop_price > 0) parts.push(`止损 ≤ ¥${money(item.stop_price)}`)
  return parts.length > 0 ? parts.join(' / ') : '无卖出条件'
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

function profitArenaRecommendationMetaText(metadata?: Record<string, unknown>) {
  const arena = metadata && typeof metadata.profit_arena === 'object' && !Array.isArray(metadata.profit_arena)
    ? metadata.profit_arena as Record<string, unknown>
    : {}
  if (!Object.keys(arena).length) return ''
  const status = String(arena.status || '')
  const selected = Number(arena.selected_count || 0)
  const topN = Number(arena.top_n || 0)
  const fail = Number(arena.capacity_fail_count || 0)
  const unknown = Number(arena.capacity_unknown_count || 0)
  const portfolioRisk = String(arena.portfolio_risk_status || '')
  const buyPlanStatus = String(arena.buy_plan_status || status)
  const buyPlanReason = profitArenaBuyPlanReasonLabel(String(arena.buy_plan_reason || ''))
  const capitalText = profitArenaCapitalMetaText(arena)
  if (status === 'missing_prediction_date') return '通用策略买入截面日期缺失，今日不生成买入计划'
  if (status === 'stale_predictions') return `通用策略买入截面过期：${String(arena.date || '-')} < 市场 ${String(arena.market_date || '-')}`
  if (buyPlanStatus === 'blocked_by_portfolio_risk') return `通用策略组合风险阻断：${buyPlanReason || portfolioRisk || 'fail'}${capitalText}`
  if (buyPlanStatus === 'blocked_by_capacity') return `通用策略容量阻断：可买 0/${topN || '-'}，剔除 ${fail}${capitalText}`
  if (buyPlanStatus === 'partial_capacity') return `通用策略容量不足：可买 ${selected}/${topN || '-'}，剔除 ${fail}${capitalText}`
  if (status === 'blocked_by_portfolio_risk') return `通用策略组合风险阻断：${portfolioRisk || 'fail'}`
  if (status === 'blocked_by_capacity') return `通用策略容量阻断：可买 0/${topN || '-'}，剔除 ${fail}`
  if (status === 'partial_capacity') return `通用策略容量不足：可买 ${selected}/${topN || '-'}，剔除 ${fail}`
  if (status === 'no_predictions') return '通用策略暂无最新买入清单'
  if (status === 'missing') return '通用策略暂无可用冠军版本'
  if (unknown > 0) return `通用策略容量摘要不完整：未知 ${unknown}`
  const warn = Number(arena.capacity_warn_count || 0)
  if (warn > 0) return `通用策略容量警告：warn ${warn}，可买 ${selected}/${topN || '-'}${capitalText}`
  if (topN > 0) return `通用策略容量后可买 ${selected}/${topN}${capitalText}`
  return ''
}

function profitArenaCapitalMetaText(arena: Record<string, unknown>) {
  const planned = Number(arena.planned_notional || 0)
  const effective = Number(arena.effective_capital || 0)
  if (planned > 0) return `，计划 ¥${money(planned)}`
  if (effective > 0) return `，资金 ¥${money(effective)}`
  return ''
}

function profitArenaBuyPlanReasonLabel(reason: string) {
  if (reason === 'portfolio_risk_gate_failed') return '组合风险预算失败'
  if (reason === 'no_capacity_tradable_candidates') return '无容量可交易买入项'
  if (reason === 'capacity_tradable_candidates_below_top_n') return '容量可交易数不足TopN'
  if (reason === 'missing_target_count') return '目标数量缺失'
  return reason
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
