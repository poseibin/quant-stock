import { useEffect, useState } from 'react'
import {
  getDataUpdateStatus,
  getLimitBreakoutModelRunStatus,
  getLimitUpModelRunStatus,
  getSettings,
  getT0DailyResearchStatus,
  listStrategyScheduleReports,
  listTasks,
  runStrategyScheduleNow,
  type RunStatus,
  type Settings,
  type StrategyScheduleReport,
  type TaskDTO
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
    try {
      const report = await runStrategyScheduleNow()
      setActiveReport(report)
      await refreshReports()
      setProgress(await fetchScheduleProgress())
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
            <p className="recommendationMeta">推送当前推荐版本；如果本版本已刷新过，直接复用调仓计划发送微信消息。</p>
          </div>
          <div className="settingsActions scheduleNotifyActions">
            <button className="primaryButton settingsButton" onClick={pushUpdate} disabled={running}>
              {running ? '推送中' : '推送更新'}
            </button>
          </div>
        </div>

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
            <span>策略模块</span>
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
            <p className="recommendationMeta">每次推送、策略刷新、调仓计划和微信通知都会记录在独立执行表。</p>
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
          <div className="emptyState inlineEmpty">暂无执行记录，点击“推送更新”开始一次任务。</div>
        )}
      </div>
    </div>
  )
}

const scheduleTargets = [
  { key: 't0', label: '做T助手' },
  { key: 'limit_up', label: '涨停预警' },
  { key: 'breakout', label: '横盘预警' },
  { key: 'factor', label: '通用策略' }
]

async function fetchScheduleProgress(): Promise<ScheduleProgressRow[]> {
  const [dataStatus, t0Status, limitStatus, breakoutStatus, tasks] = await Promise.all([
    getDataUpdateStatus().catch(() => null),
    getT0DailyResearchStatus().catch(() => null),
    getLimitUpModelRunStatus().catch(() => null),
    getLimitBreakoutModelRunStatus().catch(() => null),
    listTasks({ limit: 60 }).catch(() => [])
  ])
  const factorTask = latestFactorTask(tasks)
  return [
    statusRow('data', '股票数据', dataStatus),
    statusRow('t0', '做T助手', t0Status),
    statusRow('limit', '涨停预警', limitStatus),
    statusRow('breakout', '横盘预警', breakoutStatus),
    taskRow('factor', '通用策略', factorTask)
  ]
}

function latestFactorTask(tasks: TaskDTO[]) {
  return tasks
    .filter((task) => task.task_type === 'factor_research')
    .sort((a, b) => String(b.updated_at || b.started_at || '').localeCompare(String(a.updated_at || a.started_at || '')))[0]
}

function statusRow(key: string, label: string, status: RunStatus | null): ScheduleProgressRow {
  if (!status) return { key, label, status: '未知', message: '读取失败', tone: 'error' }
  const state = String(status.state || 'idle').toLowerCase()
  const total = Number(status.total || 0)
  const progress = total > 0 ? `${status.idx || 0}/${total}` : ''
  const message = status.message || status.name || status.stage || '等待执行'
  return {
    key,
    label,
    status: `${stateLabel(state)}${progress ? ` · ${progress}` : ''}`,
    message,
    tone: state === 'error' || state === 'failed' ? 'error' : state === 'done' || state === 'success' ? 'success' : ''
  }
}

function taskRow(key: string, label: string, task?: TaskDTO): ScheduleProgressRow {
  if (!task) return { key, label, status: '等待', message: '暂无通用策略任务', tone: '' }
  const state = String(task.status || '').toLowerCase()
  const percent = Number.isFinite(Number(task.progress)) ? `${Math.round(Number(task.progress) * 100)}%` : ''
  return {
    key,
    label,
    status: `${stateLabel(state)}${percent ? ` · ${percent}` : ''}`,
    message: task.name || task.id || '-',
    tone: state === 'failed' || state === 'cancelled' || state === 'interrupted' ? 'error' : state === 'success' ? 'success' : ''
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
      return '完成'
    case 'error':
    case 'failed':
      return '失败'
    case 'cancelled':
      return '已取消'
    case 'interrupted':
      return '已中断'
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
