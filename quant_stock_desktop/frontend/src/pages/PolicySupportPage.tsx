import { useEffect, useMemo, useState } from 'react'
import { Play, Radar, RefreshCw } from 'lucide-react'
import {
  getLatestPolicySupportSignal,
  getPolicySupportAnalysisStatus,
  listPolicySupportCandidates,
  runPolicySupportAnalysis,
  type PolicySupportCandidate,
  type PolicySupportSignal,
  type RunStatus
} from '../services/app'

export function PolicySupportPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [signal, setSignal] = useState<PolicySupportSignal | null>(null)
  const [candidates, setCandidates] = useState<PolicySupportCandidate[]>([])
  const [status, setStatus] = useState<RunStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [nextSignal, nextCandidates, nextStatus] = await Promise.all([
        getLatestPolicySupportSignal(),
        listPolicySupportCandidates(80),
        getPolicySupportAnalysisStatus()
      ])
      setSignal(nextSignal)
      setCandidates(nextCandidates)
      setStatus(nextStatus)
      if (nextStatus.state === 'error' && nextStatus.message) setError(nextStatus.message)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载托底监测失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    const timer = window.setInterval(load, status?.state === 'running' ? 1000 : 5000)
    return () => window.clearInterval(timer)
  }, [status?.state])

  const run = async () => {
    setError('')
    try {
      await runPolicySupportAnalysis()
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '运行托底监测失败')
    }
  }

  const evidence = useMemo(() => parseEvidence(signal?.evidence_json), [signal?.evidence_json])
  const running = status?.state === 'running'

  return (
    <div className="policySupportPage">
      <section className="detailHero policyHero">
        <div>
          <div className="eyebrow">POLICY SUPPORT RADAR</div>
          <h2>政策资金托底监测</h2>
          <p>用公开行情、权重股承接和龙虎榜机构痕迹，识别疑似托底环境。这里输出的是概率雷达，不是账户确认。</p>
        </div>
        <div className="detailHeroActions">
          <button className="secondaryButton startButton policyRunButton" onClick={run} disabled={running || loading}>
            <Play size={15} />{running ? '分析中' : '运行监测'}
          </button>
          <button className="secondaryButton quietButton" onClick={load} disabled={loading}>
            <RefreshCw size={15} />{loading ? '刷新中' : '刷新'}
          </button>
        </div>
      </section>

      <PolicyProgress status={status} />

      <div className="policyOverview">
        <div className={`policyScoreCard ${signal?.signal_level || 'empty'}`}>
          <span>疑似托底强度</span>
          <b>{signal ? levelText(signal.signal_level) : '—'}</b>
          <strong>{signal ? signal.total_score.toFixed(1) : '0.0'}</strong>
          <em>{signal?.trade_date || '暂无分析结果'}</em>
        </div>
        <Metric label="市场压力" value={signal?.market_stress_score ?? 0} />
        <Metric label="承接强度" value={signal?.support_score ?? 0} />
        <Metric label="机构痕迹" value={signal?.institution_score ?? 0} />
        <Metric label="权重承接" value={signal?.weight_support_score ?? 0} />
      </div>

      {signal ? (
        <section className="tableCard policySignalCard">
          <div className="tableHeader">
            <div>
              <h3>信号解释</h3>
              <span>疑似方向：{signal.direction || '—'}</span>
            </div>
            <div className="policySignalDate">更新 {signal.updated_at || '—'}</div>
          </div>
          <div className="policyReason">{signal.reason || '暂无解释'}</div>
          <div className="policyEvidenceGrid">
            <Evidence label="全市场均涨跌" value={`${fmt(evidence.avg_pct)}%`} />
            <Evidence label="权重股均涨跌" value={`${fmt(evidence.weighted_avg_pct)}%`} />
            <Evidence label="弱势占比" value={`${fmt((evidence.weak_ratio || 0) * 100)}%`} />
            <Evidence label="强承接占比" value={`${fmt((evidence.recover_ratio || 0) * 100)}%`} />
          </div>
        </section>
      ) : null}

      <section className="tableCard policyCandidatesCard">
        <div className="tableHeader">
          <div>
            <h3>候选方向</h3>
            <span>优先看 ETF/指数权重/金融央企方向；个股只作为观察样本，不是直接买入指令。</span>
          </div>
          <div className="policyCandidateCount">{candidates.length} 条</div>
        </div>

        {error ? <div className="errorBox">{error}</div> : null}

        <div className="dataTable policyTable">
          <div className="dataTableHead">
            <span>股票</span>
            <span>行业</span>
            <span>类型</span>
            <span>分数</span>
            <span>涨跌</span>
            <span>量能</span>
            <span>机构净买</span>
            <span>说明</span>
          </div>
          {candidates.map((item) => (
            <button key={`${item.trade_date}-${item.ts_code}`} className="dataTableRow policyRow" onClick={() => onOpenResearch?.(item.ts_code)}>
              <span><b>{item.name || item.ts_code}</b><em>{item.ts_code}</em></span>
              <span>{item.industry || '—'}</span>
              <span><i>{item.candidate_type || '—'}</i></span>
              <span>{item.score.toFixed(1)}</span>
              <span className={item.pct_chg >= 0 ? 'positiveText' : 'negativeText'}>{item.pct_chg.toFixed(2)}%</span>
              <span>{item.amount_ratio.toFixed(2)}x</span>
              <span>{formatMoney(item.institution_net_buy)}</span>
              <span>{item.reason || '—'}</span>
            </button>
          ))}
          {!candidates.length ? (
            <div className="emptyTableRow">暂无托底监测结果。先运行分析，或先在数据管理更新 daily / daily_basic / top_inst。</div>
          ) : null}
        </div>
      </section>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="policyMetric">
      <span>{label}</span>
      <b>{value.toFixed(1)}</b>
      <div><i style={{ width: `${Math.max(4, Math.min(100, value))}%` }} /></div>
    </div>
  )
}

function Evidence({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  )
}

function PolicyProgress({ status }: { status: RunStatus | null }) {
  if (!status || (status.state !== 'running' && status.state !== 'error')) return null
  const pct = status.total > 0 ? Math.round((status.idx / status.total) * 100) : 0
  return (
    <div className={`stateTeamProgress ${status.state === 'error' ? 'error' : ''}`}>
      <div className="stateTeamProgressTop">
        <span>{status.stage || '分析进度'}</span>
        <b>{status.state === 'running' ? `${pct}% · ${status.idx}/${status.total}` : '失败'}</b>
      </div>
      <div className="stateTeamProgressBar"><i style={{ width: `${Math.max(4, pct)}%` }} /></div>
      <p>{status.state === 'error' ? status.message : status.name || status.message || '正在分析政策资金托底信号'}</p>
    </div>
  )
}

function levelText(level: string) {
  if (level === 'high') return '高'
  if (level === 'medium') return '中'
  if (level === 'low') return '低'
  return '—'
}

function parseEvidence(raw?: string): Record<string, number> {
  if (!raw) return {}
  try {
    return JSON.parse(raw)
  } catch {
    return {}
  }
}

function fmt(value: unknown) {
  const num = typeof value === 'number' ? value : Number(value || 0)
  return Number.isFinite(num) ? num.toFixed(2) : '0.00'
}

function formatMoney(value: number) {
  if (!value) return '—'
  const abs = Math.abs(value)
  if (abs >= 100000000) return `${(value / 100000000).toFixed(2)}亿`
  return `${(value / 10000).toFixed(0)}万`
}
