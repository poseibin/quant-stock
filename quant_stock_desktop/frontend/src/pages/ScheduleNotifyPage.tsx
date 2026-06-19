import { useEffect, useState } from 'react'
import {
  getDataUpdateStatus,
  getFactorSnapshotStatus,
  getSettings,
  listStrategyScheduleReports,
  getProfitArenaRunStatus,
  getProfitArenaRebalanceStatus,
  runStrategyScheduleNow,
  type RunStatus,
  type Settings,
  type StrategyScheduleReport
} from '../services/app'

type ScheduleProgressRow = {
  key: string
  label: string
  status: string
  message: string
  tone: 'success' | 'error' | ''
}

export function ScheduleNotifyPage() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [reports, setReports] = useState<StrategyScheduleReport[]>([])
  const [activeReport, setActiveReport] = useState<StrategyScheduleReport | null>(null)
  const [progress, setProgress] = useState<ScheduleProgressRow[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const refreshReports = async () => {
    setReports(await listStrategyScheduleReports())
  }

  useEffect(() => {
    getSettings().then((response) => setSettings(response.settings))
    refreshReports()
  }, [])

  useEffect(() => {
    if (!running) return
    let cancelled = false
    const refresh = async () => {
      const rows = await fetchScheduleProgress()
      if (!cancelled) setProgress(rows)
    }
    refresh()
    const timer = window.setInterval(refresh, 3000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [running])

  const pushUpdate = async () => {
    setRunning(true)
    setActiveReport(null)
    setError('')
    setProgress(initialScheduleProgress())
    try {
      const report = await runStrategyScheduleNow()
      setActiveReport(report)
      if (!report.success) {
        setError(report.message || '手动执行完成，但通用策略生产链路存在异常')
      }
      await refreshReports()
      setProgress(await fetchScheduleProgress())
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err || '手动执行失败')
      setError(message)
      setProgress(markScheduleProgressError(initialScheduleProgress(), message))
    } finally {
      setRunning(false)
    }
  }

  const schedule = settings?.strategy_schedule
  const enabledTargets = scheduleTargets.filter((target) => schedule?.targets?.[target.key]).map((target) => target.label)

  return (
    <div className="settingsPage">
      <div className="formCard schedulerCard">
        <div className="schedulerCardHeader">
          <div>
            <div className="formTitle">定时通知</div>
            <p className="recommendationMeta">推送当前通用策略买入清单；如果本版本已刷新过，直接复用调仓计划发送微信消息。</p>
          </div>
          <div className="settingsActions scheduleNotifyActions">
            <button className="primaryButton settingsButton" onClick={pushUpdate} disabled={running}>
              {running ? '执行中' : '手动执行'}
            </button>
          </div>
        </div>

        {error && <div className="errorBox">{error}</div>}

        <div className="schedulerSummaryBar">
          <div>
            <span>定时状态</span>
            <b>{schedule?.enabled ? '已启用' : '未启用'}</b>
          </div>
          <div>
            <span>触发时间</span>
            <b>{schedule?.time_of_day || '22:00'}</b>
          </div>
          <div>
            <span>模型模块</span>
            <b>{enabledTargets.length ? enabledTargets.join(' / ') : '未选择'}</b>
          </div>
          <div>
            <span>微信</span>
            <b>{schedule?.wechat_webhook ? '已配置' : '未配置'}</b>
          </div>
        </div>

        {(running || progress.length > 0) && (
          <div className="scheduleLiveProgress">
            <div className="schedulerPanelTitle">运行进度</div>
            <div className="scheduleStepGrid">
              {progress.map((row) => (
                <div className={`scheduleStep ${row.tone}`} key={row.key}>
                  <span>{row.label}</span>
                  <b>{row.status}</b>
                  <em>{row.message}</em>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeReport && <ScheduleReportCard report={activeReport} compact={false} />}
      </div>

      <div className="formCard scheduleHistory">
        <div className="schedulerCardHeader">
          <div>
            <div className="formTitle">任务运行列表</div>
            <p className="recommendationMeta">每次推送、通用策略刷新、调仓计划和微信通知都会记录在独立执行表。</p>
          </div>
          <button className="secondaryButton settingsButton" onClick={refreshReports}>刷新列表</button>
        </div>
        {reports.length ? (
          <div className="scheduleHistoryList">
            {reports.map((report, index) => (
              <ScheduleReportCard key={`${report.started_at}-${index}`} report={report} compact={index > 0} />
            ))}
          </div>
        ) : (
          <div className="emptyState inlineEmpty">暂无执行记录，点击“手动执行”开始一次任务。</div>
        )}
      </div>
    </div>
  )
}

const scheduleTargets = [
  { key: 'arena', label: '通用策略' }
]

function initialScheduleProgress(): ScheduleProgressRow[] {
  return [
    { key: 'data', label: '股票数据', status: '准备中', message: '已提交手动执行，等待数据更新状态上报', tone: '' },
    { key: 'factor_snapshot', label: '通用策略因子截面', status: '等待', message: '数据更新成功后自动抽取本次因子截面', tone: '' },
    { key: 'arena', label: '通用策略买入清单', status: '等待', message: '因子截面完成后刷新最新买入清单', tone: '' },
    { key: 'rebalance', label: '通用策略调仓计划', status: '等待', message: '买入清单生成后输出调仓计划并发送通知', tone: '' }
  ]
}

function markScheduleProgressError(rows: ScheduleProgressRow[], message: string): ScheduleProgressRow[] {
  if (rows.length === 0) return [{ key: 'schedule', label: '手动执行', status: '异常', message, tone: 'error' }]
  return rows.map((row, index) => index === 0 ? { ...row, status: '异常', message, tone: 'error' } : row)
}

async function fetchScheduleProgress(): Promise<ScheduleProgressRow[]> {
  const [dataStatus, factorSnapshotStatus, arenaStatus, rebalanceStatus] = await Promise.all([
    getDataUpdateStatus().catch(() => null),
    getFactorSnapshotStatus().catch(() => null),
    getProfitArenaRunStatus().catch(() => null),
    getProfitArenaRebalanceStatus().catch(() => null)
  ])
  return [
    statusRow('data', '股票数据', dataStatus),
    statusRow('factor_snapshot', '通用策略因子截面', factorSnapshotStatus),
    statusRow('arena', '通用策略买入清单', arenaStatus),
    statusRow('rebalance', '通用策略调仓计划', rebalanceStatus)
  ]
}

function statusRow(key: string, label: string, status: RunStatus | null): ScheduleProgressRow {
  if (!status) return { key, label, status: '未知', message: '读取失败', tone: 'error' }
  const state = String(status.state || 'idle').toLowerCase()
  const isErrorState = state === 'error' || state === 'failed' || state === 'cancelled' || state === 'interrupted' || state === 'historical_offline' || state === 'missing'
  const isSuccessState = state === 'done' || state === 'success' || state === 'pass'
  const isNeutralState = state === 'skipped'
  const total = Math.max(0, Number(status.total || 0))
  const shouldShowProgress = total > 0 && (state === 'running' || isSuccessState || isErrorState)
  const idx = Math.max(0, Math.min(total, Number(status.idx || 0)))
  const progress = shouldShowProgress ? `${idx}/${total}` : ''
  const message = status.message || status.name || status.stage || '等待执行'
  return {
    key,
    label,
    status: `${stateLabel(state)}${progress ? ` · ${progress}` : ''}`,
    message,
    tone: isErrorState ? 'error' : isSuccessState ? 'success' : isNeutralState ? '' : ''
  }
}


function ScheduleReportCard({ report, compact }: { report: StrategyScheduleReport; compact: boolean }) {
  const rows = report.rows || []
  const rec = report.recommendation
  return (
    <div className={`scheduleReport ${report.success ? 'success' : 'error'} ${compact ? 'compact' : ''}`}>
      <div className="scheduleReportHead">
        <div>
          <strong>{report.message || (report.success ? '执行成功' : '执行失败')}</strong>
          <span>{formatTime(report.started_at)} → {formatTime(report.finished_at)}</span>
        </div>
        <span className={`scheduleStatusPill ${report.success ? 'success' : 'error'}`}>{report.success ? '成功' : '异常'}</span>
      </div>
      {rec && (
        <div className="scheduleSummaryTiles">
          <div><span>买入</span><b>{rec.n_buy || 0}</b></div>
          <div><span>卖出</span><b>{rec.n_sell || 0}</b></div>
          <div><span>计划</span><b>{rec.rows?.length || 0}</b></div>
        </div>
      )}
      <div className="scheduleStepGrid">
        {rows.map((row) => (
          <div className={`scheduleStep ${row.status === 'success' ? 'success' : 'error'}`} key={`${row.target}-${row.label}`}>
            <span>{row.label}</span>
            <b>{row.status === 'success' ? '成功' : '异常'}</b>
            <em>{row.message || '-'}</em>
          </div>
        ))}
      </div>
      {report.wechat_content && (
        <details className="scheduleWechatPreview">
          <summary>查看微信推送内容</summary>
          <pre>{report.wechat_content}</pre>
        </details>
      )}
    </div>
  )
}

function stateLabel(state: string) {
  switch (state) {
    case 'running':
      return '运行中'
    case 'queued':
    case 'created':
      return '排队'
    case 'done':
    case 'success':
    case 'pass':
      return '完成'
    case 'warn':
      return '警告'
    case 'missing':
      return '缺失'
    case 'skipped':
      return '已跳过'
    case 'error':
    case 'failed':
      return '失败'
    case 'cancelled':
      return '已取消'
    case 'interrupted':
      return '已中断'
    case 'historical_offline':
      return '已归档'
    case 'idle':
      return '空闲'
    default:
      return state || '未知'
  }
}

function formatTime(value?: string) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}
