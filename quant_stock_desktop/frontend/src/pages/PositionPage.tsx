import { useEffect, useMemo, useRef, useState } from 'react'
import {
  cancelPositionSignal,
  clearPositionPool,
  confirmPositionTrades,
  generatePositionSignal,
  getPositionRecommendation,
  getSignalPortfolioContext,
  getPositionSummary,
  getSignalRunStatus,
  type PositionRecommendation,
  type PositionSummary,
  type RunStatus,
  type SignalPortfolioCandidate,
  type SignalPortfolioContext,
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

type PositionTab = 'signal' | 'holdings' | 'rebalance'

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
  const [cancellingSignal, setCancellingSignal] = useState(false)
  const [activeTab, setActiveTab] = useState<PositionTab>('holdings')
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [portfolioContext, setPortfolioContext] = useState<SignalPortfolioContext | null>(null)
  const [selectedCandidate, setSelectedCandidate] = useState<SignalPortfolioCandidate | null>(null)
  const [error, setError] = useState('')
  const [confirmReset, setConfirmReset] = useState(false)
  const prevStateRef = useRef<string>('')

  const load = () => {
    setLoading(true)
    setError('')
    Promise.all([getPositionSummary(), getPositionRecommendation(), getSignalPortfolioContext()])
      .then(([nextSummary, nextRecommendation, nextPortfolioContext]) => {
        setSummary(nextSummary)
        setRecommendation(nextRecommendation)
        setPortfolioContext(nextPortfolioContext)
      })
      .catch((err: Error) => setError(err.message || '加载持仓失败'))
      .finally(() => setLoading(false))
  }

  const generate = () => {
    if (!selectedCandidate) {
      setError('请先在生成信号页选择一个时光机组合方案')
      return
    }
    setError('')
    generatePositionSignal({
      portfolio_run_id: selectedCandidate.run_id,
      portfolio_candidate_id: selectedCandidate.candidate_id,
      rebalance_freq: selectedCandidate.rebalance_freq || undefined
    })
      .then((res) => {
        if (res.success && res.output?.includes('复用缓存')) {
          load()
        }
      })
      .catch((err: Error) => setError(err.message || '触发信号失败'))
  }

  const selectSignalCandidate = (item: SignalPortfolioCandidate) => {
    setSelectedCandidate(item)
    setError('')
  }

  const cancelSignal = () => {
    setCancellingSignal(true)
    setError('')
    cancelPositionSignal()
      .then((status) => setRunStatus(status))
      .catch((err: Error) => setError(err.message || '取消信号生成失败'))
      .finally(() => setCancellingSignal(false))
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

  useEffect(() => {
    let cancelled = false
    const tick = () => {
      getSignalRunStatus()
        .then((s) => {
          if (cancelled) return
          setRunStatus(s)
          const prev = prevStateRef.current
          prevStateRef.current = s.state
          if (s.state === 'done' && prev !== 'done') {
            setError('')
            Promise.all([getPositionRecommendation(), getPositionSummary()])
              .then(([nextRec, nextSummary]) => {
                setRecommendation(nextRec)
                setSummary(nextSummary)
                return getSignalPortfolioContext()
              })
              .then(setPortfolioContext)
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
  const rebalancePlan = useMemo(
    () => summary && recommendation ? buildRebalancePlan(recommendation, summary) : [],
    [summary, recommendation]
  )
  const rebalanceCount = rebalancePlan.length
  const rebalanceStats = useMemo(() => buildRebalanceStats(rebalancePlan), [rebalancePlan])
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

      {isRunning ? (
        <div className="signalProgress signalProgressStandalone">
          <div className="signalProgressHeader">
            <span>{total > 0 ? `${stage || '处理中'} · ${name || ''}` : '正在启动 Python...'}</span>
            <span>{total > 0 ? `${idx}/${total} (${pct}%)` : (heartbeat ? `心跳 ${heartbeat}` : '')}</span>
          </div>
          <div className="signalProgressBar"><div className="signalProgressBarFill" style={{ width: total > 0 ? `${pct}%` : '15%' }} /></div>
        </div>
      ) : null}

      <div className="positionTabs" role="tablist" aria-label="持仓管理页签">
        <button className={activeTab === 'holdings' ? 'active' : ''} onClick={() => setActiveTab('holdings')}>当前持仓</button>
        <button className={activeTab === 'signal' ? 'active' : ''} onClick={() => setActiveTab('signal')}>生成信号</button>
        <button className={activeTab === 'rebalance' ? 'active' : ''} onClick={() => setActiveTab('rebalance')}>一键调仓</button>
      </div>

      {activeTab === 'signal' ? <SignalPanel
        recommendation={recommendation}
        loading={loading}
        isRunning={isRunning}
        cancellingSignal={cancellingSignal}
        recommendationMeta={recommendationMeta}
        onGenerate={generate}
        onCancelSignal={cancelSignal}
        portfolioContext={portfolioContext}
        selectedCandidate={selectedCandidate}
        onSelectCandidate={selectSignalCandidate}
        onOpenResearch={onOpenResearch}
      /> : null}

      {activeTab === 'holdings' ? <HoldingsPanel
        summary={summary}
        loading={loading}
        clearing={clearing}
        confirmReset={confirmReset}
        clearDisabled={clearDisabled}
        onClear={clearPositions}
        onOpenResearch={onOpenResearch}
      /> : null}

      {activeTab === 'rebalance' ? <RebalancePanel
        recommendation={recommendation}
        loading={loading}
        saving={saving}
        rebalanced={rebalanced}
        rebalanceDisabled={rebalanceDisabled}
        plan={rebalancePlan}
        stats={rebalanceStats}
        onRebalance={rebalancePositions}
        onOpenResearch={onOpenResearch}
      /> : null}
    </div>
  )
}

function SignalPanel({ recommendation, loading, isRunning, cancellingSignal, recommendationMeta, onGenerate, onCancelSignal, portfolioContext, selectedCandidate, onSelectCandidate, onOpenResearch }: {
  recommendation: PositionRecommendation | null
  loading: boolean
  isRunning: boolean
  cancellingSignal: boolean
  recommendationMeta: string
  onGenerate: () => void
  onCancelSignal: () => void
  portfolioContext: SignalPortfolioContext | null
  selectedCandidate: SignalPortfolioCandidate | null
  onSelectCandidate: (item: SignalPortfolioCandidate) => void
  onOpenResearch?: (tsCode: string) => void
}) {
  const hasCandidates = portfolioContext?.can_generate ?? false
  const mockMode = (portfolioContext?.candidates.length ?? 0) === 0 && !portfolioContext?.active
  const displayContext = mockMode ? mockSignalPortfolioContext() : portfolioContext
  const candidates = displayContext?.candidates || []
  const selectedExists = Boolean(selectedCandidate && candidates.some((candidate) => selectedCandidateKey(candidate) === selectedCandidateKey(selectedCandidate)))
  const canGenerate = Boolean(selectedExists && !mockMode)
  const selectValue = selectedCandidateKey(selectedCandidate)
  const handleSelect = (value: string) => {
    const item = candidates.find((candidate) => selectedCandidateKey(candidate) === value)
    if (item) onSelectCandidate(item)
  }
  return (
    <div className="tableCard">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">SIGNAL</div>
          <p className="recommendationMeta">{recommendationMeta || '生成最新交易日的目标持仓信号'}</p>
        </div>
        <div className="tableHeaderRight signalHeaderActions">
          {isRunning ? (
            <button className="secondaryButton dangerButton" onClick={onCancelSignal} disabled={cancellingSignal}>{cancellingSignal ? '取消中...' : '取消生成'}</button>
          ) : (
            <button className="primaryButton" onClick={onGenerate} disabled={!canGenerate}>生成信号</button>
          )}
        </div>
      </div>
      <div className="signalFormPanel">
        <div className="signalFormRow">
          <div className="signalFormField">
            <label htmlFor="signal-portfolio">信号组合</label>
            <div className="signalFormControl">
              <select id="signal-portfolio" value={selectValue} onChange={(event) => handleSelect(event.target.value)} disabled={candidates.length === 0 || isRunning}>
                <option value="">{mockMode ? '请选择预览组合' : '请选择评估通过的组合'}</option>
                {candidates.map((item) => (
                  <option key={selectedCandidateKey(item)} value={selectedCandidateKey(item)}>
                    {item.rank > 0 ? `${item.rank}. ` : ''}{item.name || item.candidate_id} · score {item.score.toFixed(1)}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
        {!canGenerate && !mockMode ? (
          <div className="signalGatePanel">
            <strong>{hasCandidates ? '请选择本次信号组合' : '需要先完成评估'}</strong>
            <span>{hasCandidates ? '从上方下拉框选择一个候选组合后再生成信号。' : (portfolioContext?.blocked_reason || '请先到评估中心完成组合优化/时光机评估，再从候选方案中选择一个信号组合。')}</span>
          </div>
        ) : null}
        <PortfolioSelectionPanel
          context={displayContext}
          mockMode={mockMode}
          selectedCandidate={selectedCandidate}
        />
      </div>
      <SignalTable recommendation={recommendation} loading={loading} onOpenResearch={onOpenResearch} />
    </div>
  )
}

function PortfolioSelectionPanel({ context, mockMode, selectedCandidate }: {
  context: SignalPortfolioContext | null
  mockMode: boolean
  selectedCandidate: SignalPortfolioCandidate | null
}) {
  const candidates = context?.candidates || []
  const active = selectedCandidate || context?.active || null
  const activeWeights = active?.weights ? Object.entries(active.weights).sort((a, b) => b[1] - a[1]) : []
  return (
    <div className="signalPortfolioPanel">
      <div className="signalPortfolioActive">
        <div className="signalPortfolioBody">
          <h3>{active?.name || '未选择信号组合'}</h3>
          <p>{active ? `run ${active.run_id} · ${active.candidate_id} · score ${active.score.toFixed(2)}${mockMode ? ' · MOCK' : ''}` : '生成信号前先从评估候选中选择一个组合。'}</p>
          {active ? (
            <div className="signalPortfolioMetrics">
              <span><b>{metricPercentValue('annual_return' in active ? active.annual_return : null)}</b> 年化</span>
              <span><b className="negative">{metricPercentValue('max_drawdown' in active ? active.max_drawdown : null)}</b> 最大回撤</span>
              <span><b>{metricNumberValue('sharpe' in active ? active.sharpe : null)}</b> 夏普</span>
              <span><b>{'rebalance_freq' in active && active.rebalance_freq > 0 ? `${active.rebalance_freq}日` : '—'}</b> 调仓</span>
            </div>
          ) : null}
          <div className="strategyWeightChips">
            {activeWeights.slice(0, 8).map(([name, weight]) => (
              <span key={name}>{strategyLabel(name)} {percent(weight)}</span>
            ))}
            {activeWeights.length === 0 ? <span>无生效权重</span> : null}
          </div>
        </div>
      </div>
    </div>
  )
}

function HoldingsPanel({ summary, loading, clearing, confirmReset, clearDisabled, onClear, onOpenResearch }: {
  summary: PositionSummary | null
  loading: boolean
  clearing: boolean
  confirmReset: boolean
  clearDisabled: boolean
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
            {!loading && (summary?.positions.length ?? 0) === 0 ? <tr><td colSpan={11} className="emptyCell">暂无持仓</td></tr> : null}
            {loading ? <tr><td colSpan={11} className="emptyCell">加载中...</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function RebalancePanel({ recommendation, loading, saving, rebalanced, rebalanceDisabled, plan, stats, onRebalance, onOpenResearch }: {
  recommendation: PositionRecommendation | null
  loading: boolean
  saving: boolean
  rebalanced: boolean
  rebalanceDisabled: boolean
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
            {recommendation?.date ? `信号日 ${recommendation.date} · ${rebalanced ? `已调仓 ${recommendation.rebalance_trades || 0} 笔` : `待执行 ${plan.length} 笔`}` : '先生成信号，再查看调仓计划'}
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
              <th>价格</th>
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

function SignalTable({ recommendation, loading, onOpenResearch }: {
  recommendation: PositionRecommendation | null
  loading: boolean
  onOpenResearch?: (tsCode: string) => void
}) {
  return (
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

function actionShortLabel(action: string) {
  if (action === '新建') return '新'
  if (action === '加仓') return '加'
  if (action === '减仓') return '减'
  if (action === '清仓') return '清'
  return '持'
}

function metricPercentValue(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return percent(value)
}

function metricNumberValue(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toFixed(2)
}

function formatWeights(weights: Record<string, number> | null | undefined) {
  const entries = Object.entries(weights || {}).filter(([, weight]) => weight > 0).sort((a, b) => b[1] - a[1])
  if (entries.length === 0) return '—'
  return entries.slice(0, 4).map(([name, weight]) => `${strategyLabel(name)} ${percent(weight)}`).join(' / ')
}

function selectedCandidateKey(item: SignalPortfolioCandidate | null) {
  return item ? `${item.run_id}:${item.candidate_id}` : ''
}

function mockSignalPortfolioContext(): SignalPortfolioContext {
  const candidates: SignalPortfolioCandidate[] = [
    {
      run_id: 'mock_portfolio_202606',
      candidate_id: 'scheme_001',
      rank: 1,
      name: '稳健质量趋势组合',
      objective: 'balanced',
      status: 'ok',
      score: 91.8,
      strategies: 'small_cap_quality,trend_pullback,dividend_quality,industry_prosperity',
      weights: { small_cap_quality: 0.34, trend_pullback: 0.26, dividend_quality: 0.22, industry_prosperity: 0.18 },
      annual_return: 0.286,
      max_drawdown: -0.128,
      sharpe: 1.42,
      calmar: 2.24,
      avg_turnover: 0.118,
      avg_holdings: 34,
      rebalance_freq: 5,
      validation_status: 'mock',
      reason: '收益质量、回撤和换手较均衡',
      updated_at: '2026-06-06T12:00:00+08:00',
      is_active: true
    },
    {
      run_id: 'mock_portfolio_202606',
      candidate_id: 'scheme_002',
      rank: 2,
      name: '进攻成长事件组合',
      objective: 'growth',
      status: 'ok',
      score: 87.3,
      strategies: 'earnings_revision,insider_buy,lhb_follow,turtle_breakout',
      weights: { earnings_revision: 0.3, insider_buy: 0.24, lhb_follow: 0.2, turtle_breakout: 0.26 },
      annual_return: 0.342,
      max_drawdown: -0.214,
      sharpe: 1.18,
      calmar: 1.6,
      avg_turnover: 0.236,
      avg_holdings: 27,
      rebalance_freq: 1,
      validation_status: 'mock',
      reason: '收益更高，但回撤和换手压力更大',
      updated_at: '2026-06-06T12:00:00+08:00',
      is_active: false
    },
    {
      run_id: 'mock_portfolio_202606',
      candidate_id: 'scheme_003',
      rank: 3,
      name: '低波防守组合',
      objective: 'low_drawdown',
      status: 'ok',
      score: 84.6,
      strategies: 'dividend_quality,market_regime_timing,low_crowding_reversal',
      weights: { dividend_quality: 0.42, market_regime_timing: 0.28, low_crowding_reversal: 0.3 },
      annual_return: 0.198,
      max_drawdown: -0.082,
      sharpe: 1.35,
      calmar: 2.41,
      avg_turnover: 0.072,
      avg_holdings: 31,
      rebalance_freq: 20,
      validation_status: 'mock',
      reason: '低回撤、低换手，适合弱市观察',
      updated_at: '2026-06-06T12:00:00+08:00',
      is_active: false
    }
  ]
  return {
    active: {
      run_id: candidates[0].run_id,
      candidate_id: candidates[0].candidate_id,
      name: candidates[0].name,
      status: 'ok',
      score: candidates[0].score,
      weights: candidates[0].weights,
      validation_status: 'mock',
      applied_at: '2026-06-06T12:00:00+08:00'
    },
    candidates,
    can_generate: false,
    blocked_reason: 'MOCK 预览：真实生成仍需先完成评估并选择候选组合'
  }
}
