import { useEffect, useState } from 'react'
import {
  getLimitSignalEvaluationRunStatus,
  listLimitSignalEvaluationSummary,
  listLimitSignalTimeMachineSlices,
  runLimitSignalEvaluation,
  type LimitSignalEvaluationSummary,
  type LimitSignalTimeMachineSlice,
  type RunStatus
} from '../services/app'

type SignalEvaluationTab = 'limit_up_momentum' | 'limit_breakout'

const signalEvaluationTabs: Array<{ key: SignalEvaluationTab; label: string; empty: string }> = [
  {
    key: 'limit_up_momentum',
    label: '涨停板推荐评估',
    empty: '暂无涨停板推荐回看结果，先在涨停预警里刷新涨停板推荐，再点击评估验证'
  },
  {
    key: 'limit_breakout',
    label: '横盘突发预警评估',
    empty: '暂无横盘突发预警回看结果，先在涨停预警里刷新横盘突发预警，再点击评估验证'
  }
]

function pct(value: number) {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
}

function pctPlain(value: number) {
  return `${(value * 100).toFixed(1)}%`
}

function dateText(value: string) {
  if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
  return value || '—'
}

function parseJSON<T>(value: string, fallback: T): T {
  try {
    const parsed = JSON.parse(value || '')
    return parsed ?? fallback
  } catch {
    return fallback
  }
}

function hotTags(item: LimitSignalTimeMachineSlice) {
  return parseJSON<string[]>(item.hot_tags_json, []).filter(Boolean)
}

function topIndustryText(item: LimitSignalTimeMachineSlice) {
  const industries = parseJSON<Array<{ industry?: string; candidate_count?: number }>>(item.top_industries_json, [])
  return industries
    .slice(0, 3)
    .map((industry) => `${industry.industry || '未分类'}${industry.candidate_count ? `(${industry.candidate_count})` : ''}`)
    .join(' / ') || '—'
}

function weightedAverage(
  slices: LimitSignalTimeMachineSlice[],
  field: keyof Pick<LimitSignalTimeMachineSlice, 'limit_up_hit_rate' | 'slice_score' | 'avg_target_return'>
) {
  const mature = slices.filter((item) => item.evaluated_count > 0)
  const total = mature.reduce((sum, item) => sum + item.evaluated_count, 0)
  if (total <= 0) return 0
  return mature.reduce((sum, item) => sum + Number(item[field]) * item.evaluated_count, 0) / total
}

function buildVerdict(item: LimitSignalEvaluationSummary | undefined, slices: LimitSignalTimeMachineSlice[], activeTab: { empty: string }) {
  if (!item) {
    return {
      tone: 'neutral',
      badge: '无结果',
      title: '当前没有这类预警的评估数据',
      summary: activeTab.empty,
      action: '先回到预警列表刷新候选，再跑评估',
      limitUpHitRate: 0,
      sliceScore: 0,
      sampleTotal: 0
    }
  }
  const sampleTotal = item.sample_count + item.pending_count
  const limitUpHitRate = weightedAverage(slices, 'limit_up_hit_rate')
  const sliceScore = weightedAverage(slices, 'slice_score')
  const weak = item.sample_count < 30
  const failed = item.hit_rate <= 0 || item.avg_return_5d <= 0 || item.recommendation === 'tighten'
  const watch = !failed && (item.hit_rate < 0.45 || item.avg_return_5d < 0.03 || item.recommendation === 'tune')
  if (weak) {
    return {
      tone: 'warning',
      badge: '样本不足',
      title: '样本还不够，不能拿来指导实盘',
      summary: `成熟样本只有 ${item.sample_count} 个，至少等到 30 个以上再判断稳定性。`,
      action: '只记录，不下单',
      limitUpHitRate,
      sliceScore,
      sampleTotal
    }
  }
  if (failed) {
    return {
      tone: 'bad',
      badge: '暂停',
      title: '当前涨停预警评估效果不通过',
      summary: `成熟样本 ${item.sample_count}/${sampleTotal} 个，目标命中 ${pctPlain(item.hit_rate)}，T+5 平均收益 ${pct(item.avg_return_5d)}，5日回撤 ${pct(item.avg_max_drawdown_5d)}。这组结果没有稳定盈利证据。`,
      action: '不要作为买入入口，只保留观察',
      limitUpHitRate,
      sliceScore,
      sampleTotal
    }
  }
  if (watch) {
    return {
      tone: 'warning',
      badge: '观察',
      title: '有一点信号，但还达不到稳定启用',
      summary: `成熟样本 ${item.sample_count}/${sampleTotal} 个，目标命中 ${pctPlain(item.hit_rate)}，T+5 平均收益 ${pct(item.avg_return_5d)}，需要继续看分市场环境的稳定性。`,
      action: '小仓观察，继续评估',
      limitUpHitRate,
      sliceScore,
      sampleTotal
    }
  }
  return {
    tone: 'good',
    badge: '可用',
    title: '当前涨停预警可以进入观察启用',
    summary: `成熟样本 ${item.sample_count}/${sampleTotal} 个，目标命中 ${pctPlain(item.hit_rate)}，T+5 平均收益 ${pct(item.avg_return_5d)}，回撤可控。`,
    action: '进入候选池，但仍需仓位限制',
    limitUpHitRate,
    sliceScore,
    sampleTotal
  }
}

function runStatusPercent(status: RunStatus) {
  if (status.state === 'done') return 100
  if (status.state === 'success') return 100
  if (status.total > 0) return Math.max(0, Math.min(100, (status.idx / status.total) * 100))
  if (status.state === 'running') return 5
  return 0
}

function RunStatusProgress({ status }: { status: RunStatus | null }) {
  if (!status || status.state === 'idle') return null
  const progress = runStatusPercent(status)
  const done = status.state === 'done' || status.state === 'success'
  const failed = status.state === 'error' || status.state === 'failed'
  const label = status.name || status.stage || (failed ? '任务失败' : done ? '评估完成' : '任务运行中')
  const detail = done ? '完成' : status.total > 0 ? `${status.idx}/${status.total}` : status.state
  return (
    <div className="signalProgress breakoutRefreshProgress">
      <div className="signalProgressHeader">
        <span>{label}</span>
        <span>{Math.round(progress)}% · {detail}</span>
      </div>
      <div className="signalProgressBar"><div className="signalProgressBarFill" style={{ width: `${progress}%` }} /></div>
      {status.message && <div className={failed ? 'errorText' : 'cardHint'}>{status.message}</div>}
    </div>
  )
}

export function LimitSignalEvaluationPanel({ activeSignal, onOpenList }: { activeSignal: SignalEvaluationTab; onOpenList?: () => void }) {
  const [items, setItems] = useState<LimitSignalEvaluationSummary[]>([])
  const [slices, setSlices] = useState<LimitSignalTimeMachineSlice[]>([])
  const [status, setStatus] = useState<RunStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const refresh = async () => {
    try {
      const [nextItems, nextSlices, nextStatus] = await Promise.all([
        listLimitSignalEvaluationSummary(),
        listLimitSignalTimeMachineSlices(120),
        getLimitSignalEvaluationRunStatus()
      ])
      setItems(nextItems)
      setSlices(nextSlices)
      setStatus(nextStatus)
      if (nextStatus.state === 'running') {
        setNotice('')
      } else if (nextStatus.state === 'done' || nextStatus.state === 'success') {
        setNotice(nextStatus.message || '评估已结束；如果仍暂无结果，请先刷新涨停推荐或横盘突发预警生成预测快照。')
      }
      return nextStatus
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      return null
    }
  }

  const run = async () => {
    setLoading(true)
    setError('')
    setNotice('')
    setStatus({
      task: 'limit_signal_evaluation',
      task_type: 'evaluation',
      state: 'running',
      idx: 1,
      total: 100,
      stage: 'prepare',
      name: '提交评估验证',
      message: '已提交评估任务，正在启动 worker',
      worker_pid: 0,
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      finished_at: ''
    })
    try {
      await runLimitSignalEvaluation()
      const nextStatus = await refresh()
      if (!nextStatus || nextStatus.state === 'idle') {
        setNotice('评估任务已提交；如果没有进度，请确认已刷新推荐生成预测快照，或稍后刷新页面。')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    const timer = window.setInterval(refresh, status?.state === 'running' ? 1000 : 5000)
    return () => window.clearInterval(timer)
  }, [status?.state])

  const running = status?.state === 'running'
  const activeTab = signalEvaluationTabs.find((tab) => tab.key === activeSignal) ?? signalEvaluationTabs[0]
  const visibleItems = items.filter((item) => item.signal_type === activeSignal)
  const visibleSlices = slices.filter((item) => item.signal_type === activeSignal).slice(0, 12)
  const primaryItem = visibleItems[0]
  const verdict = buildVerdict(primaryItem, visibleSlices, activeTab)
  const activeStatusMessage = primaryItem || running || error ? notice : ''

  return (
    <section className="dashboardPanel limitEvaluationPanel">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">LIMIT SIGNAL EVALUATION</div>
          <div className="dashboardPanelTitle">{activeTab.label}</div>
          <div className="cardHint">从历史切面回看当时热点、涨停板和横盘突发候选，验证 T+1/T+3/T+5/T+10 收益、5日回撤和涨停命中，再给参数版本建议。</div>
        </div>
        <button className="secondaryButton" onClick={run} disabled={loading || running}>{running ? '评估中...' : '评估验证'}</button>
      </div>
      {(error || activeStatusMessage || visibleItems.length === 0) && (
        <div className={error ? 'errorBox' : 'cardHint'}>{error || activeStatusMessage || activeTab.empty}</div>
      )}
      <RunStatusProgress status={status} />
      <div className={`limitSignalVerdict limitSignalVerdict-${verdict.tone}`}>
        <div className="limitSignalVerdictMain">
          <span>{verdict.badge}</span>
          <h3>{verdict.title}</h3>
          <p>{verdict.summary}</p>
          <b>实盘处理：{verdict.action}</b>
          {!primaryItem && onOpenList && (
            <button className="secondaryButton limitSignalVerdictAction" onClick={onOpenList}>回到预警列表</button>
          )}
        </div>
        <div className="limitSignalVerdictMetrics">
          <Mini label="成熟样本" value={primaryItem ? `${primaryItem.sample_count}/${verdict.sampleTotal}` : '—'} />
          <Mini label="目标命中" value={primaryItem ? pctPlain(primaryItem.hit_rate) : '—'} />
          <Mini label="5日涨停命中" value={primaryItem ? pctPlain(verdict.limitUpHitRate) : '—'} />
          <Mini label="T+5收益" value={primaryItem ? pct(primaryItem.avg_return_5d) : '—'} />
          <Mini label="5日回撤" value={primaryItem ? pct(primaryItem.avg_max_drawdown_5d) : '—'} />
          <Mini label="切面分" value={primaryItem ? verdict.sliceScore.toFixed(1) : '—'} />
        </div>
      </div>
      {visibleItems.length > 0 && (
        <div className="limitEvaluationGrid limitSummaryGrid">
          {visibleItems.map((item) => (
          <div className="limitEvaluationCard limitSummaryCard" key={`${item.signal_type}-${item.strategy_version}-${item.parameter_key}`}>
            <div className="limitEvaluationTopline">
              <span>{signalLabel(item.signal_type)} · {item.strategy_version}</span>
              <b className={evaluationTone(item.recommendation)}>{evaluationLabel(item.recommendation)}</b>
            </div>
            <div className="limitEvaluationMetrics">
              <Mini label="样本" value={`${item.sample_count}`} />
              <Mini label="待成熟" value={`${item.pending_count}`} />
              <Mini label="命中率" value={pctPlain(item.hit_rate)} />
              <Mini label="T+5" value={pct(item.avg_return_5d)} />
              <Mini label="T+10" value={pct(item.avg_return_10d)} />
              <Mini label="5日回撤" value={pct(item.avg_max_drawdown_5d)} />
            </div>
            <p>{item.parameter_hint || '等待更多样本生成参数建议。'}</p>
            <code>{item.parameter_key}</code>
          </div>
          ))}
        </div>
      )}
      <div className="tableHeader limitSliceHeader">
        <div>
          <div className="formTitle">历史切面时光机</div>
          <div className="cardHint">按某一历史交易日的候选池聚合，观察当时整批信号的收益、涨停命中和回撤。</div>
        </div>
      </div>
      <div className="limitEvaluationGrid">
        {visibleSlices.length === 0 ? (
          <div className="limitEvaluationEmpty">暂无历史切面结果，先点击评估验证生成切片统计</div>
        ) : visibleSlices.map((item) => (
          <div className="limitEvaluationCard" key={`${item.signal_type}-${item.parameter_key}-${item.signal_date}`}>
            <div className="limitEvaluationTopline">
              <span>{dateText(item.signal_date)} · {signalLabel(item.signal_type)}</span>
              <b className={evaluationTone(item.recommendation)}>{evaluationLabel(item.recommendation)}</b>
            </div>
            <div className="limitEvaluationMetrics">
              <Mini label="候选" value={`${item.candidate_count}`} />
              <Mini label="成熟" value={`${item.evaluated_count}`} />
              <Mini label="切面分" value={item.slice_score.toFixed(1)} />
              <Mini label="热度" value={item.market_heat_score.toFixed(1)} />
              <Mini label="涨停数" value={`${item.limit_up_count}`} />
              <Mini label="上涨占比" value={pctPlain(item.up_ratio)} />
              <Mini label="目标收益" value={pct(item.avg_target_return)} />
              <Mini label="目标命中" value={pctPlain(item.hit_rate)} />
              <Mini label="涨停命中" value={pctPlain(item.limit_up_hit_rate)} />
              <Mini label="5日回撤" value={pct(item.avg_max_drawdown_5d)} />
              <Mini label="题材" value={topIndustryText(item)} />
            </div>
            {hotTags(item).length > 0 && (
              <div className="limitSliceTags">
                {hotTags(item).map((tag) => <span key={tag}>{tag}</span>)}
              </div>
            )}
            <code>{item.parameter_key}</code>
          </div>
        ))}
      </div>
    </section>
  )
}

function Mini({ label, value }: { label: string; value: string }) {
  return <div className="miniMetric compact"><span>{label}</span><b>{value}</b></div>
}

function signalLabel(value: string) {
  if (value === 'limit_up_momentum') return '涨停板推荐'
  if (value === 'limit_breakout') return '横盘突发预警'
  return value || '未知模型'
}

function evaluationLabel(value: string) {
  if (value === 'keep') return '保留'
  if (value === 'tune') return '调参'
  if (value === 'tighten') return '收紧'
  if (value === 'collecting') return '样本累积'
  return value || '待评估'
}

function evaluationTone(value: string) {
  if (value === 'keep') return 'positiveText'
  if (value === 'tighten') return 'negativeText'
  return 'warningText'
}
