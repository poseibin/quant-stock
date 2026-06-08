import { useEffect, useMemo, useState } from 'react'
import {
  getLimitBreakoutModelRunStatus,
  getLimitUpModelRunStatus,
  listLimitBreakoutModelFeatures,
  listLimitBreakoutModelPredictions,
  listLimitBreakoutModelRuns,
  listLimitBreakoutModelTimeMachineSlices,
  listLimitUpModelFeatures,
  listLimitUpModelPredictions,
  listLimitUpModelRuns,
  listLimitUpModelTimeMachineSlices,
  runLimitBreakoutModelTraining,
  runLimitUpModelTraining,
  type LimitUpModelFeature,
  type LimitUpModelPrediction,
  type LimitUpModelRunSummary,
  type LimitUpModelTimeMachineSlice,
  type RunStatus
} from '../services/app'

type TabKey = 'momentum' | 'breakout'
type SignalView = 'recommend' | 'training' | 'evaluation'
type LimitUpTierMetric = {
  top_k: number
  count: number
  avg_return: number
  excess_return: number
  avg_max_return: number
  hit_rate: number
  limit_up_hit_rate: number
  avg_drawdown: number
}
type LimitUpYearMetric = {
  year: number
  rows: number
  baseline_return: number
  top_return: number
  top_excess_return: number
  top_limit_up_rate: number
  top_drawdown: number
  roc_auc: number
  avg_precision: number
  tiers?: LimitUpTierMetric[]
}
type LimitUpTradingYearMetric = {
  year: number
  trade_count: number
  avg_return: number
  win_rate: number
  compound_return: number
  max_drawdown: number
}
type LimitUpTradingValidation = {
  name: string
  top_n: number
  hold_days: number
  signal_count: number
  trade_count: number
  fill_rate: number
  avg_return: number
  win_rate: number
  compound_return: number
  max_drawdown: number
  yearly?: LimitUpTradingYearMetric[]
}
type EvaluationQualitySummary = {
  universe_note?: string
  path_assumption?: string
  sample_rows?: number
  prediction_rows?: number
  sample_years?: number[]
  fold_years?: number[]
  fold_count?: number
  missing_fold_years?: number[]
  overall_positive_rate?: number
  tested_positive_rate?: number
  min_fold_rows?: number
  max_fold_rows?: number
}
type LimitUpRunSummaryPayload = {
  tiers?: LimitUpTierMetric[]
  folds?: LimitUpYearMetric[]
  trading_validation?: LimitUpTradingValidation[]
  evaluation_quality?: EvaluationQualitySummary
  test_start?: string
  test_end?: string
  top_k?: number
}

function pct(value: number) {
  if (!Number.isFinite(value)) return '—'
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
}

function pctNoSign(value: number) {
  if (!Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}

function n(value: number, digits = 1) {
  return Number.isFinite(value) ? value.toFixed(digits) : '—'
}

function money(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '—'
  return `¥${value.toFixed(2)}`
}

function roundLotShares(price: number, cash: number) {
  if (!Number.isFinite(price) || price <= 0 || !Number.isFinite(cash) || cash <= 0) return 0
  return Math.floor(cash / price / 100) * 100
}

function dateLabel(value: string) {
  if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
  return value || '—'
}

function dateTimeLabel(value: string) {
  if (!value) return '暂无'
  if (/^\d{8}$/.test(value)) return dateLabel(value)
  return value.replace('T', ' ').replace(/\.\d+Z?$/, '').slice(0, 16) || value
}

function compactYears(values?: number[]) {
  const years = (values || []).filter(Number.isFinite).sort((a, b) => a - b)
  if (years.length === 0) return '—'
  if (years.length <= 4) return years.join(' / ')
  return `${years[0]}-${years[years.length - 1]}`
}

function featureLabel(value: string) {
  const labels: Record<string, string> = {
    industry_heat_score: '热点强度',
    industry_limit_up_count: '行业涨停数',
    industry_limit_up_ratio: '行业涨停占比',
    industry_up_ratio: '行业上涨占比',
    industry_ret3: '行业3日强度',
    industry_ret5: '行业5日强度',
    industry_amount_chg5: '行业成交放大',
    market_limit_up_count: '市场涨停数',
    market_up_ratio: '市场上涨占比',
    market_limit_up_ratio: '市场涨停占比',
    pct_chg: '当日涨幅',
    flat_score: '横盘结构分',
    startup_score: '启动确认分',
    base_ratio_250: '250日箱体高低比',
    base_ratio_500: '500日箱体高低比',
    base_return_250: '250日箱体收益',
    base_return_500: '500日箱体收益',
    base_volatility_120: '120日波动',
    ret3: '近3日收益',
    ret5: '近5日收益',
    ret10: '近10日收益',
    ret20: '近20日收益',
    drawdown60: '60日回撤',
    distance_high250: '距250日高点',
    breakout_ratio250: '突破250日高点',
    amount_chg5: '5日成交放大',
    turnover_rate: '换手率',
    volume_ratio: '量比',
    amount_chg20: '20日成交放大',
    volume_surge_120: '120日量能放大',
    limit_up_count10: '10日涨停数',
    circ_mv_log: '流通市值',
    roe: 'ROE',
    netprofit_margin: '净利率',
    debt_to_assets: '资产负债率',
    industry_ret20: '行业20日强度',
    drawdown20: '20日回撤',
    distance_high60: '距60日高点'
  }
  return labels[value] || value
}

function parseLimitUpRunSummary(run?: LimitUpModelRunSummary): LimitUpRunSummaryPayload {
  if (!run?.summary_json) return {}
  try {
    const parsed = JSON.parse(run.summary_json) as LimitUpRunSummaryPayload
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function bestTradingValidation(run?: LimitUpModelRunSummary) {
  const rows = parseLimitUpRunSummary(run).trading_validation || []
  return rows.reduce<LimitUpTradingValidation | null>((best, item) => !best || item.compound_return > best.compound_return ? item : best, null)
}

function tradeLayerPass(run: LimitUpModelRunSummary | undefined, variant: 'momentum' | 'breakout') {
  if (!run || run.top_return <= 0 || run.top_excess_return <= 0) return false
  const trading = bestTradingValidation(run)
  if (!trading || trading.avg_return <= 0 || trading.compound_return <= 0) return false
  if (variant === 'momentum') return trading.max_drawdown > -0.35
  return true
}

function avg(values: number[]) {
  const valid = values.filter((value) => Number.isFinite(value))
  if (valid.length === 0) return 0
  return valid.reduce((sum, value) => sum + value, 0) / valid.length
}

function marketTone(value: number) {
  if (!Number.isFinite(value) || value === 0) return ''
  return value > 0 ? 'marketUpText' : 'marketDownText'
}

function drawdownTone(value: number) {
  if (!Number.isFinite(value) || value === 0) return ''
  return value < 0 ? 'marketDownText' : 'marketUpText'
}

function rateTone(value: number, good = 0.5, caution = good * 0.7) {
  if (!Number.isFinite(value) || value === 0) return ''
  if (value >= good) return 'positiveText'
  if (value >= caution) return 'warningText'
  return 'negativeText'
}

function icTone(value: number) {
  if (!Number.isFinite(value) || value === 0) return ''
  if (value > 0.02) return 'positiveText'
  if (value > -0.02) return 'warningText'
  return 'negativeText'
}

function aucTone(value: number) {
  if (!Number.isFinite(value) || value === 0) return ''
  if (value >= 0.62) return 'positiveText'
  if (value >= 0.55) return 'warningText'
  return 'negativeText'
}

function predictionTradeAction(item: LimitUpModelPrediction, variant: 'momentum' | 'breakout', run?: LimitUpModelRunSummary) {
  const score = Number(item.model_score || 0)
  const prob = Number(item.prob || 0)
  const tradePass = tradeLayerPass(run, variant)
  if (variant === 'breakout') {
    if (!tradePass) {
      if (prob >= 0.48 && score >= 60) return { label: '观察', badge: 'running', stage: '交易层未过' }
      return { label: '放弃', badge: 'created', stage: '结构不够强' }
    }
    if (prob >= 0.58 && score >= 72) return { label: '可试仓', badge: 'success', stage: '等回踩确认' }
    if (prob >= 0.48 && score >= 60) return { label: '观察', badge: 'running', stage: '等突破回踩' }
    return { label: '放弃', badge: 'created', stage: '结构不够强' }
  }
  if (!tradePass) {
    if (prob >= 0.50 && score >= 60) return { label: '观察', badge: 'running', stage: '交易层未过' }
    return { label: '放弃', badge: 'created', stage: '赔率不足' }
  }
  if (prob >= 0.62 && score >= 72) return { label: '可试仓', badge: 'success', stage: '等换手承接' }
  if (prob >= 0.50 && score >= 60) return { label: '观察', badge: 'running', stage: '等回封/分歧转强' }
  return { label: '放弃', badge: 'created', stage: '赔率不足' }
}

function predictionTradePlan(item: LimitUpModelPrediction, variant: 'momentum' | 'breakout', run?: LimitUpModelRunSummary) {
  const price = Number(item.price || 0)
  const action = predictionTradeAction(item, variant, run)
  const executable = action.badge === 'success'
  const watchable = action.badge === 'running'
  const cash = executable ? 10000 : watchable ? 5000 : 0
  if (variant === 'breakout') {
    const entry = price > 0 ? price * 0.985 : 0
    const add = price > 0 ? price * 1.025 : 0
    const target = price > 0 ? price * 1.08 : 0
    const stop = price > 0 ? price * 0.95 : 0
    return {
      entryText: '突破后回踩不破',
      addText: '放量再上攻才加',
      targetText: '前高/8%分批',
      stopText: '跌回箱体停手',
      entry,
      add,
      target,
      stop,
      shares: roundLotShares(entry || price, cash),
      invalid: item.max_drawdown_5d < -0.08 ? '历史回撤偏大' : '破位即失效',
    }
  }
  const entry = price > 0 ? price * 1.015 : 0
  const add = price > 0 ? price * 1.055 : 0
  const target = price > 0 ? price * 1.10 : 0
  const stop = price > 0 ? price * 0.95 : 0
  return {
    entryText: '低开/平开承接',
    addText: '回封再确认',
    targetText: '冲高/涨停分批',
    stopText: '跌破-5%停手',
    entry,
    add,
    target,
    stop,
    shares: roundLotShares(entry || price, cash),
    invalid: item.max_drawdown_5d < -0.08 ? '历史回撤偏大' : '高开过大不追',
  }
}

function summarizePredictions(predictions: LimitUpModelPrediction[], run: LimitUpModelRunSummary | undefined, variant: 'momentum' | 'breakout') {
  const count = predictions.length
  const executable = predictions.filter((item) => predictionTradeAction(item, variant, run).badge === 'success').length
  const watch = predictions.filter((item) => predictionTradeAction(item, variant, run).badge === 'running').length
  const avgProb = count ? avg(predictions.map((item) => item.prob)) : 0
  const avgScore = count ? avg(predictions.map((item) => item.model_score)) : 0
  const latestCount = predictions.filter((item) => item.is_latest).length
  return {
    count,
    executable,
    watch,
    avgProb,
    avgScore,
    latestCount,
    verdict: run && run.top_excess_return > 0 && run.top_return > 0 ? '可观察' : run ? '谨慎' : '未更新',
  }
}

function tierActionConclusion(tier: LimitUpTierMetric, variant: 'momentum' | 'breakout', tradePass: boolean) {
  if (variant === 'momentum') {
    if (!tradePass) return '观察，不给试仓'
    if (tier.top_k <= 3 && tier.avg_return > 0.04 && tier.limit_up_hit_rate > 0.5) return '可极小仓验证'
    if (tier.avg_return > 0.02) return '观察池'
    return '停用'
  }
  if (!tradePass) return tier.top_k <= 3 && tier.avg_return > 0 ? '只等回踩观察' : '停用'
  if (tier.top_k <= 3 && tier.avg_return > 0 && tier.excess_return > 0) return '回踩条件单'
  if (tier.avg_return > 0) return '观察'
  return '停用'
}

function TopTierExecutionSummary({ run, variant }: { run?: LimitUpModelRunSummary; variant: 'momentum' | 'breakout' }) {
  const summary = parseLimitUpRunSummary(run)
  const tiers = summary.tiers || []
  if (!run || tiers.length === 0) return null
  const tradePass = tradeLayerPass(run, variant)
  return (
    <div className="metricStrip signalTierStrip">
      {tiers.map((tier) => (
        <div className={`metricCard ${tradePass && tier.avg_return > 0 ? 'good' : ''}`} key={`${variant}-${tier.top_k}`}>
          <span>Top{tier.top_k}</span>
          <b className={marketTone(tier.avg_return)}>{pct(tier.avg_return)}</b>
          <em>{tierActionConclusion(tier, variant, tradePass)} · 超额 {pct(tier.excess_return)} · 再板 {pctNoSign(tier.limit_up_hit_rate)}</em>
        </div>
      ))}
    </div>
  )
}

function runStatusPercent(status: RunStatus) {
  if (status.total > 0) return Math.max(0, Math.min(100, (status.idx / status.total) * 100))
  if (status.state === 'running') return 5
  if (status.state === 'done') return 100
  return 0
}

function RunStatusProgress({ status }: { status: RunStatus | null }) {
  if (!status || (status.state !== 'running' && status.state !== 'error')) return null
  const progress = runStatusPercent(status)
  const label = status.name || status.stage || (status.state === 'error' ? '任务失败' : '任务运行中')
  const detail = status.total > 0 ? `${status.idx}/${status.total}` : status.state
  return (
    <div className="signalProgress breakoutRefreshProgress">
      <div className="signalProgressHeader">
        <span>{label}</span>
        <span>{Math.round(progress)}% · {detail}</span>
      </div>
      <div className="signalProgressBar"><div className="signalProgressBarFill" style={{ width: `${progress}%` }} /></div>
      {status.message && <div className={status.state === 'error' ? 'errorText' : 'cardHint'}>{status.message}</div>}
    </div>
  )
}

function SignalSummaryPanel({
  predictions,
  run,
  variant,
  error = '',
  loading = false,
  onRefresh,
}: {
  predictions: LimitUpModelPrediction[]
  run?: LimitUpModelRunSummary
  variant: 'momentum' | 'breakout'
  error?: string
  loading?: boolean
  onRefresh?: () => void
}) {
  const summary = summarizePredictions(predictions, run, variant)
  const title = variant === 'breakout' ? '横盘爆点观察总览' : '涨停接力动作总览'
  const subtitle = variant === 'breakout' ? '先找结构，再等回踩确认；交易层不通过时只观察不追入。' : '先看模型概率，再看开盘承接；高开过大和买不到板都不追。'
  return (
    <section className="detailCard signalTradeSummaryCard">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">{variant === 'breakout' ? 'BREAKOUT WORKFLOW' : 'LIMIT-UP WORKFLOW'}</div>
          <h2>{title}</h2>
          <p className="recommendationMeta">{subtitle}</p>
          {error && <p className="errorText">{error}</p>}
        </div>
        {onRefresh && (
          <div className="tableHeaderRight">
            <button className="secondaryButton startButton" onClick={onRefresh} disabled={loading}>{loading ? '更新中...' : '更新推荐'}</button>
          </div>
        )}
      </div>
      <div className="metricStrip">
        <div className={`metricCard ${summary.verdict === '可观察' ? 'good' : ''}`}>
          <span>模型结论</span>
          <b>{summary.verdict}</b>
          <em>{run ? `${dateLabel(run.start_date)} - ${dateLabel(run.end_date)}` : '先更新模型'}</em>
        </div>
        <div className="metricCard">
          <span>今日候选</span>
          <b>{summary.count}</b>
          <em>{summary.latestCount || summary.count} 只最新截面</em>
        </div>
        <div className={`metricCard ${summary.executable > 0 ? 'good' : ''}`}>
          <span>可试仓</span>
          <b>{summary.executable}</b>
          <em>{variant === 'breakout' ? '结构和概率同时通过' : '概率和接力评分同时通过'}</em>
        </div>
        <div className="metricCard">
          <span>观察池</span>
          <b>{summary.watch}</b>
          <em>{variant === 'breakout' ? '等待突破回踩' : '等待分歧转强'}</em>
        </div>
      </div>
      <div className="metricStrip">
        <div className="metricCard">
          <span>平均概率</span>
          <b>{pctNoSign(summary.avgProb)}</b>
          <em>模型截面置信度</em>
        </div>
        <div className="metricCard">
          <span>平均评分</span>
          <b>{n(summary.avgScore, 1)}</b>
          <em>{variant === 'breakout' ? '横盘结构和启动强度' : '热点接力和个股强度'}</em>
        </div>
        <div className={`metricCard ${run && run.top_return > 0 ? 'good' : ''}`}>
          <span>{variant === 'breakout' ? 'Top3收益' : 'Top10收益'}</span>
          <b className={run ? marketTone(run.top_return) : ''}>{run ? pct(run.top_return) : '—'}</b>
          <em>模型页更新验证结果</em>
        </div>
        <div className="metricCard">
          <span>再涨停率</span>
          <b>{run ? pctNoSign(run.top_limit_up_rate) : '—'}</b>
          <em>实验页看分年和交易层</em>
        </div>
      </div>
    </section>
  )
}

function SignalActionList({
  predictions,
  run,
  variant,
  onOpenResearch,
  selectedCode,
  onSelect,
}: {
  predictions: LimitUpModelPrediction[]
  run?: LimitUpModelRunSummary
  variant: 'momentum' | 'breakout'
  onOpenResearch?: OpenResearch
  selectedCode: string
  onSelect: (tsCode: string) => void
}) {
  const title = variant === 'breakout' ? '横盘爆点观察清单' : '涨停接力动作清单'
  const hint = variant === 'breakout'
    ? '按模型概率和结构分给出观察、试仓、失效条件；不是突破就追，必须等回踩承接。'
    : '按模型概率和接力分给出可试仓、观察、放弃；高开过大、买不到板或承接差都直接放弃。'
  return (
    <section className="modelRecommendCard signalActionCard">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">{variant === 'breakout' ? 'WATCH LIST' : 'ACTION LIST'}</div>
          <div className="dashboardPanelTitle">{title}</div>
          <div className="cardHint">{hint}</div>
        </div>
      </div>
      <TopTierExecutionSummary run={run} variant={variant} />
      {predictions.length === 0 ? (
        <div className="taskGridEmpty compactEmpty">暂无模型推荐，先去模型训练页更新模型</div>
      ) : (
        <div className="modelRecommendViewport">
          <div className="modelRecommendTableWrap">
            <table className="modelRecommendTable signalActionTable">
              <thead>
                <tr>
                  <th>排名</th>
                  <th>股票</th>
                  <th>动作</th>
                  <th>解释</th>
                  <th>条件买入</th>
                  <th>股数</th>
                  <th>确认/加仓</th>
                  <th>条件卖出</th>
                  <th>止损</th>
                  <th>验证</th>
                </tr>
              </thead>
              <tbody>
                {predictions.map((item, index) => {
                  const action = predictionTradeAction(item, variant, run)
                  const plan = predictionTradePlan(item, variant, run)
                  return (
                    <tr key={`action-${item.ts_code}`} className={selectedCode === item.ts_code ? 'active' : ''} onClick={() => onSelect(item.ts_code)}>
                      <td><strong>{index + 1}</strong></td>
                      <td className="t0StockCell">
                        <button
                          className="tableActionButton"
                          title="查看个股研究"
                          onClick={(event) => {
                            event.stopPropagation()
                            onSelect(item.ts_code)
                            onOpenResearch?.(item.ts_code, { projection: variant === 'momentum' })
                          }}
                        >
                          {item.name}
                        </button>
                        <div className="mono">{item.ts_code}</div>
                        <div className="recommendationMeta">{item.industry || '未分类'} · {dateLabel(item.trade_date)}</div>
                        <div className="recommendationMeta">首次推荐 {dateLabel(item.first_seen_date)} · 观察 {item.observation_days || 0} 天 · 保留 {item.seen_count || 0} 次</div>
                        <div className="recommendationMeta">{item.observation_result || '观察中'}</div>
                      </td>
                      <td>
                        <span className={`badge ${action.badge}`}>{action.label}</span>
                        <div className="cardHint">{action.stage}</div>
                        <div className="cardHint">保留原因：{item.observation_reason || '模型推荐'}</div>
                      </td>
                      <td>
                        <strong>{n(item.model_score, 1)}</strong>
                        <div className="cardHint">概率 {pctNoSign(item.prob)}</div>
                      </td>
                      <td>
                        <strong>{money(plan.entry)}</strong>
                        <div className="cardHint">{plan.entryText}</div>
                        <div className="cardHint">现价 {money(item.price)}</div>
                      </td>
                      <td>
                        <strong>{plan.shares > 0 ? `${plan.shares} 股` : '不下单'}</strong>
                        <div className="cardHint">{plan.shares > 0 ? '按试仓资金估算，100股取整' : '只观察/放弃'}</div>
                      </td>
                      <td>
                        <strong>{money(plan.add)}</strong>
                        <div className="cardHint">{plan.addText}</div>
                      </td>
                      <td>
                        <strong>{money(plan.target)}</strong>
                        <div className="cardHint">{plan.targetText}</div>
                      </td>
                      <td>
                        <strong className="negativeText">{money(plan.stop)}</strong>
                        <div className="cardHint">{plan.stopText}</div>
                        <div className="cardHint">{plan.invalid}</div>
                      </td>
                      <td>
                        {item.is_latest ? <span className="cardHint">待验证</span> : <strong className={marketTone(item.fwd5_return)}>{pct(item.fwd5_return)}</strong>}
                        <div className="cardHint">{item.is_latest ? '最新截面' : `最高 ${pct(item.fwd5_max_return)} · 回撤 ${pct(item.max_drawdown_5d)}`}</div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}

function ValidationGatePanel({
  run,
  trading,
  variant,
}: {
  run?: LimitUpModelRunSummary
  trading: LimitUpTradingValidation | null
  variant: 'momentum' | 'breakout'
}) {
  const signalPass = Boolean(run && run.top_return > 0 && run.top_excess_return > 0)
  const tradePass = Boolean(trading && trading.compound_return > 0 && trading.max_drawdown > -0.18)
  const signalLabel = signalPass ? '信号有效' : run ? '信号谨慎' : '未更新'
  const tradeLabel = tradePass ? '交易可做' : trading ? '交易未过' : '待验证'
  return (
    <div className="limitValidationGates">
      <div className={`metricCard ${signalPass ? 'good' : ''}`}>
        <span>第一关 信号有效</span>
        <b>{signalLabel}</b>
        <em>{run ? `${variant === 'breakout' ? 'Top3' : 'Top10'}收益 ${pct(run.top_return)} · 超额 ${pct(run.top_excess_return)}` : '先更新模型'}</em>
      </div>
      <div className={`metricCard ${tradePass ? 'good' : ''}`}>
        <span>第二关 交易可做</span>
        <b>{tradeLabel}</b>
        <em>{trading ? `复利 ${pct(trading.compound_return)} · 回撤 ${pct(trading.max_drawdown)} · 成交率 ${pctNoSign(trading.fill_rate)}` : '缺交易层验证'}</em>
      </div>
      <div className="metricCard">
        <span>推荐动作</span>
        <b>{signalPass && tradePass ? '可试仓验证' : signalPass ? '观察不自动买' : '先停用推荐'}</b>
        <em>{signalPass && !tradePass ? '模型能找票，但交易规则还没证明能赚钱' : variant === 'breakout' ? '横盘必须等回踩承接' : '涨停必须看开盘承接'}</em>
      </div>
    </div>
  )
}

function StrategyAssumptionPanel({
  quality,
  trading,
  variant,
}: {
  quality?: EvaluationQualitySummary
  trading: LimitUpTradingValidation | null
  variant: 'momentum' | 'breakout'
}) {
  const copy = variant === 'breakout'
    ? {
        title: '横盘策略假设',
        label: '横盘爆点',
        target: '标签用未来 5 日最高收益或 5 日内涨停命中，并约束最大回撤；推荐页只做预警，机械交易必须等回踩确认。',
        trade: '交易层按突破后回踩/确认近似，日线只能确认是否触价，不能还原真实盘口排队和日内先后。',
      }
    : {
        title: '涨停策略假设',
        label: '涨停接力',
        target: '标签用未来 5 日最高收益、再涨停命中和回撤控制；推荐页按模型分层给观察/试仓，不代表开盘无条件追。',
        trade: '交易层按次日开盘买入、高开过阈值不追、涨停买不到跳过、止盈止损和交易成本近似。',
      }
  return (
    <div className="limitModelNote">
      <b>{copy.title}</b>
      <span>{copy.target}</span>
      <b>当前交易参数</b>
      <span>{trading ? `${trading.name}：Top${trading.top_n}，持有 ${trading.hold_days} 日，成交率 ${pctNoSign(trading.fill_rate)}，复利 ${pct(trading.compound_return)}。` : copy.trade}</span>
      <b>样本口径</b>
      <span>{quality?.universe_note || `${copy.label} 使用可获取日线、行业、财务与事件数据生成候选池；ST/退市样本默认排除。`}</span>
      <b>路径假设</b>
      <span>{quality?.path_assumption || copy.trade}</span>
    </div>
  )
}

type OpenResearch = (tsCode: string, options?: { projection?: boolean }) => void

export function LimitBreakoutPage({ mode = 'momentum', onOpenResearch }: { mode?: TabKey; onOpenResearch?: OpenResearch }) {
  const [activeView, setActiveView] = useState<SignalView>('recommend')
  const [dataUpdatedAt, setDataUpdatedAt] = useState('')

  const recommendLabel = mode === 'momentum' ? '推荐列表' : '预警列表'
  const tabs: Array<{ key: SignalView; label: string }> = [
    { key: 'recommend', label: recommendLabel },
    { key: 'training', label: '模型训练' },
    { key: 'evaluation', label: '模型评估' }
  ]

  return (
    <div className="breakoutPage">
      <div className="pageTabsHeader">
        <div className="inlineTabs evaluationModeTabs signalViewTabs">
          {tabs.map((tab) => (
            <button key={tab.key} className={activeView === tab.key ? 'active' : ''} onClick={() => setActiveView(tab.key)}>{tab.label}</button>
          ))}
        </div>
        <div className="dataUpdatedPill">数据更新：{dateTimeLabel(dataUpdatedAt)}</div>
      </div>

      {activeView === 'evaluation' ? (
        mode === 'momentum' ? (
          <MomentumPanel view="evaluation" onOpenResearch={onOpenResearch} onDataUpdated={setDataUpdatedAt} />
        ) : (
          <BreakoutPanel view="evaluation" onOpenResearch={onOpenResearch} onDataUpdated={setDataUpdatedAt} />
        )
      ) : activeView === 'training' ? (
        mode === 'momentum' ? (
        <MomentumPanel view="training" onOpenResearch={onOpenResearch} onDataUpdated={setDataUpdatedAt} />
        ) : (
          <BreakoutPanel view="training" onOpenResearch={onOpenResearch} onDataUpdated={setDataUpdatedAt} />
        )
      ) : mode === 'momentum' ? (
        <MomentumPanel view="recommend" onOpenResearch={onOpenResearch} onDataUpdated={setDataUpdatedAt} />
      ) : (
        <BreakoutPanel view="recommend" onOpenResearch={onOpenResearch} onDataUpdated={setDataUpdatedAt} />
      )}
    </div>
  )
}

function MomentumPanel({ view, onOpenResearch, onDataUpdated }: { view: SignalView; onOpenResearch?: OpenResearch; onDataUpdated?: (value: string) => void }) {
  const [selectedCode, setSelectedCode] = useState('')
  const [modelStatus, setModelStatus] = useState<RunStatus | null>(null)
  const [modelRuns, setModelRuns] = useState<LimitUpModelRunSummary[]>([])
  const [modelPredictions, setModelPredictions] = useState<LimitUpModelPrediction[]>([])
  const [modelSlices, setModelSlices] = useState<LimitUpModelTimeMachineSlice[]>([])
  const [modelFeatures, setModelFeatures] = useState<LimitUpModelFeature[]>([])
  const [modelError, setModelError] = useState('')
  const [modelLoading, setModelLoading] = useState(false)

  const loadModel = async () => {
    try {
      const [runs, status] = await Promise.all([
        listLimitUpModelRuns(5),
        getLimitUpModelRunStatus()
      ])
      setModelRuns(runs)
      setModelStatus(status)
      const runID = runs[0]?.run_id || ''
      const [predictions, slices, features] = await Promise.all([
        listLimitUpModelPredictions(runID, 10),
        listLimitUpModelTimeMachineSlices(runID, 20),
        listLimitUpModelFeatures(runID, 8)
      ])
      setModelPredictions(predictions)
      setModelSlices(slices)
      setModelFeatures(features)
      onDataUpdated?.(predictions[0]?.updated_at || runs[0]?.updated_at || status.updated_at || '')
    } catch (err) {
      setModelError(err instanceof Error ? err.message : String(err))
    }
  }

  const trainModel = async () => {
    setModelLoading(true)
    setModelError('')
    setModelStatus({
      task: 'limit_up_model',
      task_type: 'model_training',
      state: 'running',
      idx: 0,
      total: 5,
      stage: 'prepare',
      name: '启动涨停模型更新',
      message: '正在启动 Python worker',
      worker_pid: 0,
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      finished_at: ''
    })
    try {
      await runLimitUpModelTraining()
      await loadModel()
    } catch (err) {
      setModelError(err instanceof Error ? err.message : String(err))
    } finally {
      setModelLoading(false)
    }
  }

  useEffect(() => {
    loadModel().catch((error) => console.error('[limit-up-model] load failed', error))
  }, [])

  useEffect(() => {
    loadModel().catch((error) => console.error('[limit-up-model] poll failed', error))
    const modelTimer = window.setInterval(loadModel, modelStatus?.state === 'running' ? 1200 : 8000)
    return () => {
      window.clearInterval(modelTimer)
    }
  }, [modelStatus?.state])

  return (
    <>
      {view === 'recommend' && <RunStatusProgress status={modelStatus} />}

      {view === 'recommend' && (
        <SignalSummaryPanel
          predictions={modelPredictions}
          run={modelRuns[0]}
          variant="momentum"
          error={modelError}
          loading={modelLoading || modelStatus?.state === 'running'}
          onRefresh={trainModel}
        />
      )}

      {view === 'recommend' && (
        <SignalActionList
          predictions={modelPredictions}
          run={modelRuns[0]}
          variant="momentum"
          onOpenResearch={onOpenResearch}
          selectedCode={selectedCode}
          onSelect={setSelectedCode}
        />
      )}

      {view === 'training' && (
        <LimitUpModelTrainingPanel
          run={modelRuns[0]}
          status={modelStatus}
          features={modelFeatures}
          error={modelError}
          loading={modelLoading}
          onTrain={trainModel}
          variant="momentum"
        />
      )}

      {view === 'evaluation' && (
        <LimitUpModelEvaluationPanel
          run={modelRuns[0]}
          status={modelStatus}
          slices={modelSlices}
          features={modelFeatures}
          error={modelError}
          variant="momentum"
        />
      )}

    </>
  )
}

function LimitUpModelTrainingPanel({
  run,
  status,
  features,
  error,
  loading,
  onTrain,
  variant = 'momentum'
}: {
  run?: LimitUpModelRunSummary
  status: RunStatus | null
  features: LimitUpModelFeature[]
  error: string
  loading: boolean
  onTrain: () => void
  variant?: 'momentum' | 'breakout'
}) {
  const running = status?.state === 'running'
  const copy = variant === 'breakout'
    ? {
        section: 'FLAT BREAKOUT MODEL',
        title: '横盘预警模型',
        hint: '基于长期箱体、低波动、近期启动、市场热度和财务质量训练 LightGBM；按年份 walk-forward 验证，重点看 Top1/Top3 的爆发命中。',
        empty: '还没有横盘预警模型结果。先更新模型，完成后才有模型推荐和时光机评测。',
        good: 'Top3 平均收益',
        train: '更新模型',
        target: '未来5日最高收益或再涨停命中，且5日回撤可控；辅助统计再涨停率和 Rank IC。'
      }
    : {
        section: 'LIMIT-UP MODEL',
        title: '涨停接力模型',
        hint: '基于热点强度、个股强度、拥挤度和风险特征训练 LightGBM；按年份 walk-forward 验证，Rank IC 作为排序辅助指标。',
        empty: '还没有涨停模型结果。先更新模型，完成后才有股票 Top10 和时光机评测。',
        good: 'Top10 平均收益',
        train: '更新模型',
        target: '未来5日最高收益达到阈值且回撤可控，辅助统计再涨停率和 Rank IC。'
      }
  const verdict = !run
    ? { tone: 'warningText', label: '未更新', text: copy.empty }
    : run.top_return <= 0 || run.top_excess_return <= 0
      ? { tone: 'negativeText', label: '谨慎', text: `${variant === 'breakout' ? 'Top3' : 'Top10'} 超额 ${pct(run.top_excess_return)}，最近年份可能失效，不能直接作为实盘入口。` }
      : { tone: 'positiveText', label: '可观察', text: `${variant === 'breakout' ? 'Top3' : 'Top10'} 平均收益 ${pct(run.top_return)}，相对候选池超额 ${pct(run.top_excess_return)}，但仍需看最近切面稳定性。` }
  const summary = parseLimitUpRunSummary(run)
  const bestTrading = (summary.trading_validation || []).reduce<LimitUpTradingValidation | null>((best, item) => !best || item.compound_return > best.compound_return ? item : best, null)

  return (
    <section className="limitModelPanel">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">{copy.section}</div>
          <div className="dashboardPanelTitle">{copy.title}</div>
          <div className="cardHint">{copy.hint}</div>
        </div>
        <button className="primaryButton" onClick={onTrain} disabled={loading || running}>{running ? '模型更新中…' : copy.train}</button>
      </div>
      {(error || status?.message) && <div className={error ? 'errorBox' : 'cardHint'}>{error || status?.message}</div>}
      <RunStatusProgress status={status} />
      <div className="limitModelVerdict">
        <div>
          <span className={verdict.tone}>{verdict.label}</span>
          <b>{run ? `${dateLabel(run.start_date)} - ${dateLabel(run.end_date)}` : '等待更新'}</b>
          <p>{verdict.text}</p>
        </div>
        <div className="limitModelMetrics">
          <Mini label="样本" value={run ? `${run.rows}/${run.candidate_rows}` : '—'} />
          <Mini label={`${variant === 'breakout' ? 'Top3' : 'Top10'}收益`} value={run ? pct(run.top_return) : '—'} valueClassName={run ? marketTone(run.top_return) : ''} />
          <Mini label="候选池收益" value={run ? pct(run.baseline_return) : '—'} valueClassName={run ? marketTone(run.baseline_return) : ''} />
          <Mini label="再涨停率" value={run ? pctNoSign(run.top_limit_up_rate) : '—'} valueClassName={run ? rateTone(run.top_limit_up_rate, variant === 'breakout' ? 0.35 : 0.45) : ''} />
          <Mini label="最大回撤" value={run ? pct(run.top_drawdown) : '—'} valueClassName={run ? drawdownTone(run.top_drawdown) : ''} />
          <Mini label="Rank IC" value={run ? run.rank_ic.toFixed(3) : '—'} valueClassName={run ? icTone(run.rank_ic) : ''} />
        </div>
      </div>
      <div className="metricStrip signalTierStrip">
        <div className="metricCard">
          <span>评估样本</span>
          <b>{summary.evaluation_quality?.sample_rows ? summary.evaluation_quality.sample_rows.toLocaleString('zh-CN') : run ? run.rows.toLocaleString('zh-CN') : '—'}</b>
          <em>预测 {summary.evaluation_quality?.prediction_rows ? summary.evaluation_quality.prediction_rows.toLocaleString('zh-CN') : '—'} 行</em>
        </div>
        <div className="metricCard">
          <span>Walk-forward</span>
          <b>{summary.evaluation_quality?.fold_count || summary.folds?.length || '—'}</b>
          <em>{compactYears(summary.evaluation_quality?.fold_years)}</em>
        </div>
        <div className="metricCard">
          <span>正样本率</span>
          <b>{pctNoSign(summary.evaluation_quality?.tested_positive_rate ?? Number.NaN)}</b>
          <em>整体 {pctNoSign(summary.evaluation_quality?.overall_positive_rate ?? Number.NaN)}</em>
        </div>
        <div className="metricCard">
          <span>交易参数</span>
          <b>{bestTrading ? `Top${bestTrading.top_n}` : '—'}</b>
          <em>{bestTrading ? `持有 ${bestTrading.hold_days} 日 · 成交 ${pctNoSign(bestTrading.fill_rate)}` : '模型评估后生成'}</em>
        </div>
      </div>
      <StrategyAssumptionPanel quality={summary.evaluation_quality} trading={bestTrading} variant={variant} />
      <div className="limitModelColumns twoColumns">
        <div>
          <div className="formTitle">重要特征</div>
          <div className="limitModelFeatureList">
            {features.length === 0 ? <div className="taskGridEmpty compactEmpty">暂无特征重要性</div> : features.map((item) => (
              <span key={item.feature}>{item.rank_no}. {featureLabel(item.feature)}</span>
            ))}
          </div>
        </div>
        <div>
          <div className="formTitle">训练说明</div>
          <div className="limitModelNote">
            <b>训练方式</b>
            <span>按年份 walk-forward：只用测试年份之前的数据训练，避免未来函数。</span>
            <b>目标标签</b>
            <span>{copy.target}</span>
          </div>
        </div>
      </div>
    </section>
  )
}

function LimitUpModelEvaluationPanel({
  run,
  status,
  slices,
  features,
  error,
  variant = 'momentum'
}: {
  run?: LimitUpModelRunSummary
  status: RunStatus | null
  slices: LimitUpModelTimeMachineSlice[]
  features: LimitUpModelFeature[]
  error: string
  variant?: 'momentum' | 'breakout'
}) {
  const recentSlices = slices.slice(0, 12)
  const summary = parseLimitUpRunSummary(run)
  const tiers = summary.tiers?.length ? summary.tiers : run ? [{
    top_k: 10,
    count: run.rows,
    avg_return: run.top_return,
    excess_return: run.top_excess_return,
    avg_max_return: 0,
    hit_rate: run.top_hit_rate,
    limit_up_hit_rate: run.top_limit_up_rate,
    avg_drawdown: run.top_drawdown
  }] : []
  const yearMetrics = summary.folds || []
  const tradingRows = summary.trading_validation || []
  const bestTrading = tradingRows.reduce<LimitUpTradingValidation | null>((best, item) => !best || item.compound_return > best.compound_return ? item : best, null)
  const recentYears = yearMetrics.slice(-3)
  const recentTopReturn = avg(recentYears.map((item) => item.top_return))
  const recentExcessReturn = avg(recentYears.map((item) => item.top_excess_return))
  const worstDrawdown = yearMetrics.reduce<LimitUpYearMetric | null>((worst, item) => !worst || item.top_drawdown < worst.top_drawdown ? item : worst, null)
  const decayWarning = Boolean(run && yearMetrics.length >= 4 && recentTopReturn < run.top_return * 0.75)
  const verdict = !run
    ? { tone: 'warningText', label: '未更新', text: '还没有模型评估结果。先去模型训练页更新模型。' }
    : run.top_return <= 0 || run.top_excess_return <= 0
      ? { tone: 'negativeText', label: '不通过', text: `${variant === 'breakout' ? 'Top3' : 'Top10'} 超额 ${pct(run.top_excess_return)}，模型暂不适合作为推荐入口。` }
      : { tone: 'positiveText', label: '可观察', text: `${variant === 'breakout' ? 'Top3' : 'Top10'} 平均收益 ${pct(run.top_return)}，候选池收益 ${pct(run.baseline_return)}，再涨停率 ${pctNoSign(run.top_limit_up_rate)}。` }
  return (
    <section className="limitModelPanel">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">MODEL EVALUATION</div>
          <div className="dashboardPanelTitle">{variant === 'breakout' ? '横盘模型评估' : '涨停模型评估'}</div>
          <div className="cardHint">{variant === 'breakout' ? '这里看横盘模型固定后的时光机表现、Top1/Top3/Top10收益、回撤、再涨停率和 Rank IC，不展示旧规则评估。' : '这里看模型固定后的时光机表现、Top10收益、回撤、再涨停率和 Rank IC，不展示旧规则评估。'}</div>
        </div>
      </div>
      {(error || status?.message) && <div className={error ? 'errorBox' : 'cardHint'}>{error || status?.message}</div>}
      <RunStatusProgress status={status} />
      <div className="limitModelVerdict">
        <div>
          <span className={verdict.tone}>{verdict.label}</span>
          <b>{run ? `${dateLabel(run.start_date)} - ${dateLabel(run.end_date)}` : '等待更新'}</b>
          <p>{verdict.text}</p>
        </div>
        <div className="limitModelMetrics">
          <Mini label="样本" value={run ? `${run.rows}/${run.candidate_rows}` : '—'} />
          <Mini label={`${variant === 'breakout' ? 'Top3' : 'Top10'}收益`} value={run ? pct(run.top_return) : '—'} valueClassName={run ? marketTone(run.top_return) : ''} />
          <Mini label="超额收益" value={run ? pct(run.top_excess_return) : '—'} valueClassName={run ? marketTone(run.top_excess_return) : ''} />
          <Mini label="再涨停率" value={run ? pctNoSign(run.top_limit_up_rate) : '—'} valueClassName={run ? rateTone(run.top_limit_up_rate, variant === 'breakout' ? 0.35 : 0.45) : ''} />
          <Mini label="最大回撤" value={run ? pct(run.top_drawdown) : '—'} valueClassName={run ? drawdownTone(run.top_drawdown) : ''} />
          <Mini label="Rank IC" value={run ? run.rank_ic.toFixed(3) : '—'} valueClassName={run ? icTone(run.rank_ic) : ''} />
        </div>
      </div>
      <ValidationGatePanel run={run} trading={bestTrading} variant={variant} />
      <div className="metricStrip signalTierStrip">
        <div className="metricCard">
          <span>评估样本</span>
          <b>{summary.evaluation_quality?.sample_rows ? summary.evaluation_quality.sample_rows.toLocaleString('zh-CN') : run ? run.rows.toLocaleString('zh-CN') : '—'}</b>
          <em>预测 {summary.evaluation_quality?.prediction_rows ? summary.evaluation_quality.prediction_rows.toLocaleString('zh-CN') : '—'} 行</em>
        </div>
        <div className="metricCard">
          <span>Fold覆盖</span>
          <b>{summary.evaluation_quality?.fold_count || yearMetrics.length || '—'}</b>
          <em>{compactYears(summary.evaluation_quality?.fold_years)}</em>
        </div>
        <div className="metricCard">
          <span>正样本率</span>
          <b>{pctNoSign(summary.evaluation_quality?.tested_positive_rate ?? Number.NaN)}</b>
          <em>最小/最大fold {summary.evaluation_quality?.min_fold_rows || '—'} / {summary.evaluation_quality?.max_fold_rows || '—'}</em>
        </div>
        <div className="metricCard">
          <span>缺失年份</span>
          <b>{summary.evaluation_quality?.missing_fold_years?.length || 0}</b>
          <em>{compactYears(summary.evaluation_quality?.missing_fold_years)}</em>
        </div>
      </div>
      <StrategyAssumptionPanel quality={summary.evaluation_quality} trading={bestTrading} variant={variant} />
      {run && yearMetrics.length > 0 && (
        <div className="limitModelNote">
          <b>近年稳定性</b>
          <span>
            最近{recentYears.length}年 {variant === 'breakout' ? 'Top3' : 'Top10'} 平均 {pct(recentTopReturn)}，超额 {pct(recentExcessReturn)}
            {decayWarning ? '，低于全周期均值，说明模型有衰减，需要看最近切面。' : '，仍高于候选池，暂未出现明显失效。'}
          </span>
          <b>最大压力年</b>
          <span>{worstDrawdown ? `${worstDrawdown.year} 年 ${variant === 'breakout' ? 'Top3' : 'Top10'} 回撤 ${pct(worstDrawdown.top_drawdown)}，收益 ${pct(worstDrawdown.top_return)}。` : '暂无分年压力数据。'}</span>
          <b>交易验证</b>
          <span>{bestTrading ? `当前保守买卖规则最优为 ${bestTrading.name}，复利收益 ${pct(bestTrading.compound_return)}，成交率 ${pctNoSign(bestTrading.fill_rate)}。${bestTrading.compound_return <= 0 ? '交易层暂不通过，不能自动实盘。' : '交易层可继续小仓验证。'}` : '暂无交易层验证，更新模型后生成。'}</span>
        </div>
      )}
      <div className="limitModelEvalGrid">
        <div>
          <div className="formTitle">Top 分层表现</div>
          <div className="modelEvalTableWrap">
            <table className="modelEvalTable">
              <thead>
                <tr>
                  <th>层级</th>
                  <th>5日收益</th>
                  <th>超额</th>
                  <th>5日最高</th>
                  <th>命中率</th>
                  <th>再涨停率</th>
                  <th>回撤</th>
                </tr>
              </thead>
              <tbody>
                {tiers.length === 0 ? (
                  <tr><td colSpan={7}>暂无分层评估，更新模型后生成</td></tr>
                ) : tiers.map((item) => (
                  <tr key={item.top_k}>
                    <td>Top{item.top_k}</td>
                    <td className={marketTone(item.avg_return)}>{pct(item.avg_return)}</td>
                    <td className={marketTone(item.excess_return)}>{pct(item.excess_return)}</td>
                    <td className={marketTone(item.avg_max_return)}>{pct(item.avg_max_return)}</td>
                    <td className={rateTone(item.hit_rate, 0.58)}>{pctNoSign(item.hit_rate)}</td>
                    <td className={rateTone(item.limit_up_hit_rate, variant === 'breakout' ? 0.35 : 0.45)}>{pctNoSign(item.limit_up_hit_rate)}</td>
                    <td className={drawdownTone(item.avg_drawdown)}>{pct(item.avg_drawdown)}</td>
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
                  <th>{variant === 'breakout' ? 'Top3' : 'Top10'}</th>
                  <th>超额</th>
                  <th>再涨停</th>
                  <th>回撤</th>
                  <th>AUC</th>
                </tr>
              </thead>
              <tbody>
                {yearMetrics.length === 0 ? (
                  <tr><td colSpan={6}>暂无分年评估，更新模型后生成</td></tr>
                ) : yearMetrics.map((item) => (
                  <tr key={item.year}>
                    <td>{item.year}</td>
                    <td className={marketTone(item.top_return)}>{pct(item.top_return)}</td>
                    <td className={marketTone(item.top_excess_return)}>{pct(item.top_excess_return)}</td>
                    <td className={rateTone(item.top_limit_up_rate, variant === 'breakout' ? 0.35 : 0.45)}>{pctNoSign(item.top_limit_up_rate)}</td>
                    <td className={drawdownTone(item.top_drawdown)}>{pct(item.top_drawdown)}</td>
                    <td className={aucTone(item.roc_auc)}>{item.roc_auc ? item.roc_auc.toFixed(3) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <div>
        <div className="formTitle">交易层验证</div>
        <div className="cardHint">{variant === 'breakout' ? '这里验证模型信号后次日追买是否可行；若交易层为负，说明它更适合做爆点预警和人工观察，不适合机械追入。' : '次日开盘买；高开超过 7% 不追；次日涨停买不到跳过；止盈 10%、止损 5%；含滑点、佣金和印花税。'}</div>
        <div className="modelEvalTableWrap">
          <table className="modelEvalTable tradingEvalTable">
            <thead>
              <tr>
                <th>规则</th>
                <th>成交/信号</th>
                <th>成交率</th>
                <th>单笔均值</th>
                <th>胜率</th>
                <th>复利收益</th>
                <th>最大回撤</th>
              </tr>
            </thead>
            <tbody>
              {tradingRows.length === 0 ? (
                <tr><td colSpan={7}>暂无交易验证，更新模型后生成</td></tr>
              ) : tradingRows.map((item) => (
                <tr key={`${item.top_n}-${item.hold_days}`}>
                  <td>{item.name}</td>
                  <td>{item.trade_count}/{item.signal_count}</td>
                  <td className={rateTone(item.fill_rate, 0.25)}>{pctNoSign(item.fill_rate)}</td>
                  <td className={marketTone(item.avg_return)}>{pct(item.avg_return)}</td>
                  <td className={rateTone(item.win_rate, 0.5)}>{pctNoSign(item.win_rate)}</td>
                  <td className={marketTone(item.compound_return)}>{pct(item.compound_return)}</td>
                  <td className={drawdownTone(item.max_drawdown)}>{pct(item.max_drawdown)}</td>
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
              <div className="limitModelSliceRow" key={item.trade_date}>
                <b>{dateLabel(item.trade_date)}</b>
                <span>候选 {item.candidate_count} · Top{item.top_count} {pct(item.avg_return)} · 涨停 {pctNoSign(item.limit_up_hit_rate)} · IC {item.rank_ic.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <div className="formTitle">重要特征</div>
          <div className="limitModelFeatureList">
            {features.length === 0 ? <div className="taskGridEmpty compactEmpty">暂无特征重要性</div> : features.map((item) => (
              <span key={item.feature}>{item.rank_no}. {featureLabel(item.feature)}</span>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

function BreakoutPanel({ view, onOpenResearch, onDataUpdated }: { view: SignalView; onOpenResearch?: OpenResearch; onDataUpdated?: (value: string) => void }) {
  const [selectedCode, setSelectedCode] = useState('')
  const [modelStatus, setModelStatus] = useState<RunStatus | null>(null)
  const [modelRuns, setModelRuns] = useState<LimitUpModelRunSummary[]>([])
  const [modelPredictions, setModelPredictions] = useState<LimitUpModelPrediction[]>([])
  const [modelSlices, setModelSlices] = useState<LimitUpModelTimeMachineSlice[]>([])
  const [modelFeatures, setModelFeatures] = useState<LimitUpModelFeature[]>([])
  const [modelError, setModelError] = useState('')
  const [modelLoading, setModelLoading] = useState(false)

  const loadModel = async () => {
    try {
      const [runs, status] = await Promise.all([
        listLimitBreakoutModelRuns(5),
        getLimitBreakoutModelRunStatus()
      ])
      setModelRuns(runs)
      setModelStatus(status)
      const runID = runs[0]?.run_id || ''
      const [predictions, slices, features] = await Promise.all([
        listLimitBreakoutModelPredictions(runID, 10),
        listLimitBreakoutModelTimeMachineSlices(runID, 20),
        listLimitBreakoutModelFeatures(runID, 8)
      ])
      setModelPredictions(predictions)
      setModelSlices(slices)
      setModelFeatures(features)
      onDataUpdated?.(predictions[0]?.updated_at || runs[0]?.updated_at || status.updated_at || '')
    } catch (err) {
      setModelError(err instanceof Error ? err.message : String(err))
    }
  }

  const trainModel = async () => {
    setModelLoading(true)
    setModelError('')
    setModelStatus({
      task: 'limit_breakout_model',
      task_type: 'model_training',
      state: 'running',
      idx: 0,
      total: 5,
      stage: 'prepare',
      name: '启动横盘预警模型更新',
      message: '正在启动 Python worker',
      worker_pid: 0,
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      finished_at: ''
    })
    try {
      await runLimitBreakoutModelTraining()
      await loadModel()
    } catch (err) {
      setModelError(err instanceof Error ? err.message : String(err))
    } finally {
      setModelLoading(false)
    }
  }

  useEffect(() => {
    loadModel().catch((error) => console.error('[breakout-model] load failed', error))
  }, [])

  useEffect(() => {
    loadModel().catch((error) => console.error('[breakout-model] poll failed', error))
    const modelTimer = window.setInterval(loadModel, modelStatus?.state === 'running' ? 1200 : 8000)
    return () => window.clearInterval(modelTimer)
  }, [modelStatus?.state])

  return (
    <>
      {view === 'training' && (
        <LimitUpModelTrainingPanel
          run={modelRuns[0]}
          status={modelStatus}
          features={modelFeatures}
          error={modelError}
          loading={modelLoading}
          onTrain={trainModel}
          variant="breakout"
        />
      )}

      {view === 'evaluation' && (
        <LimitUpModelEvaluationPanel
          run={modelRuns[0]}
          status={modelStatus}
          slices={modelSlices}
          features={modelFeatures}
          error={modelError}
          variant="breakout"
        />
      )}

      {view === 'recommend' && <RunStatusProgress status={modelStatus} />}

      {view === 'recommend' && (
        <SignalSummaryPanel
          predictions={modelPredictions}
          run={modelRuns[0]}
          variant="breakout"
          error={modelError}
          loading={modelLoading || modelStatus?.state === 'running'}
          onRefresh={trainModel}
        />
      )}

      {view === 'recommend' && (
        <SignalActionList
          predictions={modelPredictions}
          run={modelRuns[0]}
          variant="breakout"
          onOpenResearch={onOpenResearch}
          selectedCode={selectedCode}
          onSelect={setSelectedCode}
        />
      )}

    </>
  )
}

function Mini({ label, value, valueClassName = '' }: { label: string; value: string; valueClassName?: string }) {
  return <div className="miniMetric compact"><span>{label}</span><b className={valueClassName}>{value}</b></div>
}

function ReasonBlocks({ reasons, risks }: { reasons: string[]; risks: string[] }) {
  return (
    <div className="breakoutNarrative">
      <div>
        <span>推荐理由</span>
        <p>{reasons.length ? reasons.join('，') + '。' : '暂无明显优势特征。'}</p>
      </div>
      <div>
        <span>风险提示</span>
        <p>{risks.length ? risks.join('，') + '。' : '仍需关注开板波动、滑点和次日承接。'}</p>
      </div>
    </div>
  )
}
