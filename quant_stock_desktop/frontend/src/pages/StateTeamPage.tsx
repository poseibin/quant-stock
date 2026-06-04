import { useEffect, useMemo, useState } from 'react'
import { Play, RefreshCw, Search } from 'lucide-react'
import {
  getStateTeamAnalysisStatus,
  listStateTeamHolderChanges,
  runStateTeamAnalysis,
  type RunStatus,
  type StateTeamChange
} from '../services/app'

const ACTIONS = [
  { value: 'ALL', label: '全部' },
  { value: 'NEW', label: '新进' },
  { value: 'ADD', label: '加仓' },
  { value: 'TRIM', label: '减仓' },
  { value: 'EXIT', label: '退出' },
]

export function StateTeamPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [rows, setRows] = useState<StateTeamChange[]>([])
  const [loading, setLoading] = useState(false)
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [error, setError] = useState('')
  const [action, setAction] = useState('ALL')
  const [keyword, setKeyword] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      setRows(await listStateTeamHolderChanges({ action, keyword, limit: 500 }))
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载国家队跟踪失败')
      setRows([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [action])

  const refreshRunStatus = async () => {
    try {
      const status = await getStateTeamAnalysisStatus()
      setRunStatus(status)
      if (status.state === 'done' || status.state === 'success') {
        setRows(await listStateTeamHolderChanges({ action, keyword, limit: 500 }))
      }
      if (status.state === 'error' && status.message) {
        setError(status.message)
      }
    } catch (err) {
      console.error('[state-team] load run status failed', err)
    }
  }

  useEffect(() => {
    refreshRunStatus()
    const timer = window.setInterval(refreshRunStatus, runStatus?.state === 'running' ? 1000 : 3000)
    return () => window.clearInterval(timer)
  }, [runStatus?.state, action, keyword])

  const analyze = async () => {
    setError('')
    try {
      await runStateTeamAnalysis()
      await refreshRunStatus()
    } catch (err) {
      setError(err instanceof Error ? err.message : '运行国家队分析失败')
    }
  }

  const stats = useMemo(() => summarize(rows), [rows])
  const currentPeriod = rows[0]?.current_period || ''
  const previousPeriod = rows[0]?.previous_period || ''
  const analyzing = runStatus?.state === 'running'

  return (
    <div className="stateTeamPage">
      <section className="detailHero">
        <div>
          <div className="eyebrow">STATE TEAM TRACKER</div>
          <h2>国家队调仓跟踪</h2>
          <p>基于 Python 分析落库结果，展示前十大股东中匹配国家队账户的两期变化。</p>
        </div>
        <div className="detailHeroActions">
          <button className="secondaryButton startButton stateTeamAnalyzeButton" onClick={analyze} disabled={analyzing || loading}>
            <Play size={15} />{analyzing ? '分析中' : '运行分析'}
          </button>
          <button className="secondaryButton quietButton" onClick={load} disabled={loading || analyzing}>
            <RefreshCw size={15} />{loading ? '刷新中' : '刷新'}
          </button>
        </div>
      </section>

      <div className="metricGrid">
        <Metric label="本期 / 上期" value={currentPeriod ? `${currentPeriod} / ${previousPeriod}` : '—'} />
        <Metric label="新进" value={`${stats.NEW}`} tone={stats.NEW > 0 ? 'positive' : ''} />
        <Metric label="加仓" value={`${stats.ADD}`} tone={stats.ADD > 0 ? 'positive' : ''} />
        <Metric label="减仓 / 退出" value={`${stats.TRIM} / ${stats.EXIT}`} tone={(stats.TRIM + stats.EXIT) > 0 ? 'negative' : ''} />
      </div>

      <StateTeamRunProgress status={runStatus} />

      <section className="tableCard">
        <div className="tableHeader">
          <div>
            <h3>调仓信号</h3>
            <span>NEW/ADD 适合作为买入候选，TRIM/EXIT 适合作为减仓或观察候选。</span>
          </div>
          <div className="tableHeaderRight stateTeamFilters">
            <div className="searchBox">
              <Search size={15} />
              <input value={keyword} onChange={(event) => setKeyword(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') load() }} placeholder="代码 / 名称 / 行业 / 持有人" />
            </div>
            <select className="stateTeamSelect" value={action} onChange={(event) => setAction(event.target.value)}>
              {ACTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <button className="secondaryButton stateTeamQueryButton" onClick={load}>查询</button>
          </div>
        </div>
        {error && <div className="errorText">{friendlyError(error)}</div>}
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>动作</th>
                <th>股票</th>
                <th>行业</th>
                <th>本期%</th>
                <th>上期%</th>
                <th>变化</th>
                <th>账户数</th>
                <th>当前持有人</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.ts_code}-${row.current_period}-${row.previous_period}`}>
                  <td><span className={`stateTeamBadge ${row.action.toLowerCase()}`}>{actionLabel(row.action)}</span></td>
                  <td>
                    <button className="tableActionButton codeButton" onClick={() => onOpenResearch?.(row.ts_code)}>
                      <strong>{row.name || row.ts_code}</strong>
                      <span>{row.ts_code}</span>
                    </button>
                  </td>
                  <td>{row.industry || '—'}</td>
                  <td>{pct(row.current_hold_ratio)}</td>
                  <td>{pct(row.previous_hold_ratio)}</td>
                  <td className={row.hold_ratio_delta >= 0 ? 'positive' : 'negative'}>{signedPct(row.hold_ratio_delta)}</td>
                  <td>{row.current_holder_count} / {row.previous_holder_count}</td>
                  <td className="holdersCell" title={row.current_holders || row.previous_holders}>{row.current_holders || row.previous_holders || '—'}</td>
                  <td className="noteCell">{row.note || '—'}</td>
                </tr>
              ))}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={9} className="emptyCell">暂无国家队调仓分析结果。先运行 Python 分析脚本写入 SQLite。</td></tr>
              )}
              {loading && (
                <tr><td colSpan={9} className="emptyCell">加载中...</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function summarize(rows: StateTeamChange[]) {
  return rows.reduce((acc, row) => {
    acc[row.action] = (acc[row.action] || 0) + 1
    return acc
  }, { NEW: 0, ADD: 0, TRIM: 0, EXIT: 0 } as Record<string, number>)
}

function StateTeamRunProgress({ status, taskLabel = '分析' }: { status: RunStatus | null; taskLabel?: string }) {
  if (!status || (status.state !== 'running' && status.state !== 'error')) return null
  const total = status.total || 0
  const pct = total > 0 ? Math.max(0, Math.min(100, (status.idx / total) * 100)) : status.state === 'running' ? 8 : 100
  const label = status.name || status.stage || (status.state === 'error' ? `${taskLabel}失败` : `${taskLabel}中`)
  const detail = total > 0 ? `${status.idx}/${total}` : status.state
  return (
    <div className="signalProgress stateTeamProgress">
      <div className="signalProgressHeader">
        <span>{label}</span>
        <span>{Math.round(pct)}% · {detail}</span>
      </div>
      <div className="signalProgressBar"><div className="signalProgressBarFill" style={{ width: `${pct}%` }} /></div>
      {status.message && <div className={status.state === 'error' ? 'errorText' : 'cardHint'}>{status.message}</div>}
    </div>
  )
}

function Metric({ label, value, tone = '' }: { label: string; value: string; tone?: string }) {
  return <div className="metricCard"><span>{label}</span><strong className={tone}>{value}</strong></div>
}

function actionLabel(action: string) {
  return ({ NEW: '新进', ADD: '加仓', TRIM: '减仓', EXIT: '退出' } as Record<string, string>)[action] || action
}

function friendlyError(message: string) {
  if (message.includes('top10_holders')) {
    return '缺少 top10_holders 数据，请到「数据管理」更新「前十大股东」数据集后再运行分析。'
  }
  return message
}

function pct(value: number) {
  return `${(value || 0).toFixed(2)}%`
}

function signedPct(value: number) {
  const num = value || 0
  return `${num >= 0 ? '+' : ''}${num.toFixed(2)}%`
}
