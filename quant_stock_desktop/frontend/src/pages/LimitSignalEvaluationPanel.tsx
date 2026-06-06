import { useEffect, useState } from 'react'
import {
  getLimitSignalEvaluationRunStatus,
  listLimitSignalEvaluationSummary,
  runLimitSignalEvaluation,
  type LimitSignalEvaluationSummary,
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

export function LimitSignalEvaluationPanel() {
  const [items, setItems] = useState<LimitSignalEvaluationSummary[]>([])
  const [activeSignal, setActiveSignal] = useState<SignalEvaluationTab>('limit_up_momentum')
  const [status, setStatus] = useState<RunStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const refresh = async () => {
    try {
      const [nextItems, nextStatus] = await Promise.all([
        listLimitSignalEvaluationSummary(),
        getLimitSignalEvaluationRunStatus()
      ])
      setItems(nextItems)
      setStatus(nextStatus)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const run = async () => {
    setLoading(true)
    setError('')
    try {
      await runLimitSignalEvaluation()
      await refresh()
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

  return (
    <section className="dashboardPanel limitEvaluationPanel">
      <div className="tableHeader">
        <div>
          <div className="sectionLabel">LIMIT SIGNAL EVALUATION</div>
          <div className="dashboardPanelTitle">{activeTab.label}</div>
          <div className="cardHint">候选生成时写入预测快照，回看 T+1/T+3/T+5/T+10 收益、5日回撤和涨停命中，再给参数版本建议。</div>
        </div>
        <button className="secondaryButton" onClick={run} disabled={loading || running}>{running ? '评估中...' : '评估验证'}</button>
      </div>
      <div className="inlineTabs limitEvaluationTabs">
        {signalEvaluationTabs.map((tab) => (
          <button
            key={tab.key}
            className={activeSignal === tab.key ? 'active' : ''}
            onClick={() => setActiveSignal(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {(error || status?.message) && <div className={error || status?.state === 'error' ? 'errorBox' : 'cardHint'}>{error || status?.message}</div>}
      <RunStatusProgress status={status} />
      <div className="limitEvaluationGrid">
        {visibleItems.length === 0 ? (
          <div className="taskGridEmpty">{activeTab.empty}</div>
        ) : visibleItems.map((item) => (
          <div className="limitEvaluationCard" key={`${item.signal_type}-${item.strategy_version}-${item.parameter_key}`}>
            <div className="limitEvaluationTopline">
              <span>{signalLabel(item.signal_type)} · {item.strategy_version}</span>
              <b className={evaluationTone(item.recommendation)}>{evaluationLabel(item.recommendation)}</b>
            </div>
            <div className="limitEvaluationMetrics">
              <Mini label="样本" value={`${item.sample_count}`} />
              <Mini label="待成熟" value={`${item.pending_count}`} />
              <Mini label="命中率" value={pct(item.hit_rate)} />
              <Mini label="T+5" value={pct(item.avg_return_5d)} />
              <Mini label="T+10" value={pct(item.avg_return_10d)} />
              <Mini label="5日回撤" value={pct(item.avg_max_drawdown_5d)} />
            </div>
            <p>{item.parameter_hint || '等待更多样本生成参数建议。'}</p>
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
