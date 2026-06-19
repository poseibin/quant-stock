import { useEffect, useMemo, useState } from 'react'
import { ArrowLeft, Play, RefreshCw, Square } from 'lucide-react'
import { DataGrid, type Column } from 'react-data-grid'
import { cancelTask, getArenaStrategyDefinitions, getFactorSnapshotStatus, getFactorStoreGovernance, listTasks, refreshTaskStatus, runProfitArenaTraining, startTask, type ArenaStrategyDefinition, type FactorStoreGovernance, type RunStatus, type TaskDTO } from '../services/app'
import { formatDate } from '../components/format'

export function TaskCenterPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  void onOpenResearch
  const [tasks, setTasks] = useState<TaskDTO[]>([])
  const [selectedTask, setSelectedTask] = useState<TaskDTO | null>(null)
  const [factorSnapshotStatus, setFactorSnapshotStatus] = useState<RunStatus | null>(null)
  const [factorGovernance, setFactorGovernance] = useState<FactorStoreGovernance>({})
  const [arenaDefinitions, setArenaDefinitions] = useState<ArenaStrategyDefinition[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [refreshedAt, setRefreshedAt] = useState('')
  const refresh = async () => {
    const [taskItems, snapshotStatus, governance, definitions] = await Promise.all([
      listTasks({ limit: 500 }),
      getFactorSnapshotStatus().catch(() => null),
      getFactorStoreGovernance('stock_factor_base_v1').catch(() => ({})),
      getArenaStrategyDefinitions().catch(() => [])
    ])
    const items = taskItems.filter(isTaskCenterProductionTask)
    setTasks(items)
    setFactorSnapshotStatus(snapshotStatus)
    setFactorGovernance(governance || {})
    setArenaDefinitions(definitions || [])
    if (selectedTask) {
      const latest = items.find((item) => item.id === selectedTask.id)
      if (latest) setSelectedTask(latest)
    }
    setRefreshedAt(new Date().toISOString())
  }

  const showDetail = async (id: string) => {
    const task = await refreshTaskStatus(id)
    if (!isTaskCenterProductionTask(task)) {
      setError('非生产任务不在任务中心展开；当前只展示数据更新、因子快照、通用策略训练/推理和调仓链路')
      setSelectedTask(null)
      await refresh()
      return
    }
    setSelectedTask(task)
    await refresh()
  }

  useEffect(() => {
    refresh()
  }, [])

  useEffect(() => {
    const hasLiveTask = tasks.some((task) => task.status === 'running' || task.status === 'queued' || task.status === 'created')
    if (!hasLiveTask || selectedTask) return
    const timer = window.setInterval(() => {
      refresh().catch((err) => {
        setError(err instanceof Error ? err.message : String(err))
      })
    }, 5000)
    return () => window.clearInterval(timer)
  }, [tasks, selectedTask])

  const onCreate = async () => {
    setError('')
    try {
      await runProfitArenaTraining()
      await refresh()
      setNotice('已创建通用策略训练任务，列表会持续展示进度、阶段、收益和失败原因')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const onStart = async (id: string) => {
    setError('')
    try {
      await startTask(id)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const columns = useMemo<Column<TaskDTO>[]>(() => [
    {
      key: 'name',
      name: '名称',
      minWidth: 170,
      resizable: true,
      renderCell: ({ row }) => row.name
    },
    {
      key: 'task_type',
      name: '类型',
      width: 120,
      resizable: true,
      renderCell: ({ row }) => taskTypeLabel(row)
    },
    {
      key: 'subtask',
      name: '子任务/进度',
      width: 140,
      resizable: true,
      renderCell: ({ row }) => taskProgressLabel(row)
    },
    {
      key: 'stage',
      name: '阶段',
      width: 150,
      resizable: true,
      renderCell: ({ row }) => taskStageLabel(row)
    },
    {
      key: 'message',
      name: '最新消息',
      minWidth: 220,
      resizable: true,
      renderCell: ({ row }) => <span className={row.status === 'failed' || row.status === 'interrupted' ? 'gridErrorText' : 'mutedText'} title={taskObserverMessage(row)}>{taskObserverMessage(row) || '—'}</span>
    },
    {
      key: 'status',
      name: '状态',
      width: 96,
      renderCell: ({ row }) => {
        const heartbeat = taskHeartbeatRisk(row)
        return <span className={`badge ${heartbeat.stale ? 'failed' : statusBadgeClass(row.status)}`}>{heartbeat.stale ? '疑似卡住' : statusText(row.status)}</span>
      }
    },
    {
      key: 'total_return',
      name: '累计收益',
      width: 110,
      cellClass: (row) => toneOf(taskMetric(row, 'total_return')),
      renderCell: ({ row }) => metricPercent(row, 'total_return', true)
    },
    {
      key: 'annual_return',
      name: '年化',
      width: 100,
      cellClass: (row) => toneOf(taskMetric(row, 'annual_return')),
      renderCell: ({ row }) => metricPercent(row, 'annual_return', true)
    },
    {
      key: 'excess_annual_return',
      name: '超额',
      width: 100,
      cellClass: (row) => toneOf(taskMetric(row, 'excess_annual_return')),
      renderCell: ({ row }) => metricPercent(row, 'excess_annual_return', true)
    },
    {
      key: 'win_rate',
      name: '胜率',
      width: 92,
      renderCell: ({ row }) => metricPercent(row, 'win_rate')
    },
    {
      key: 'max_drawdown',
      name: '回撤',
      width: 92,
      cellClass: 'negative',
      renderCell: ({ row }) => metricPercent(row, 'max_drawdown')
    },
    {
      key: 'sharpe',
      name: '夏普',
      width: 82,
      renderCell: ({ row }) => metricNumber(row, 'sharpe')
    },
    {
      key: 'updated_at',
      name: '更新时间',
      width: 142,
      renderCell: ({ row }) => compactDateTime(row.updated_at)
    },
    {
      key: 'actions',
      name: '操作',
      width: 220,
      cellClass: 'taskGridActionsCell',
      headerCellClass: 'taskGridActionsCell',
      renderCell: ({ row }) => (
        <div className="taskActions">
          <button className="secondaryButton quietButton" onClick={() => showDetail(row.id)}>详情</button>
          {!isTaskCenterRunnableTask(row) ? <span className="mutedText">{taskCenterReadOnlyLabel(row)}</span> : null}
          {isTaskCenterRunnableTask(row) && row.status !== 'running' && (
            <button className="secondaryButton startButton" onClick={() => onStart(row.id)}><Play size={15} />启动</button>
          )}
          {isTaskCenterRunnableTask(row) && row.status === 'running' && (
            <button className="secondaryButton dangerButton" onClick={async () => { await cancelTask(row.id); await refresh() }}><Square size={15} />取消</button>
          )}
        </div>
      )
    }
  ], [onStart, refresh, showDetail])

  const tableRows = useMemo(() => tasks.filter((item) => !item.parent_id), [tasks])
  const productionRows = tableRows.filter(isTaskCenterProductionTask)
  const visibleRunning = productionRows.filter((item) => item.status === 'running').length
  const staleRunning = productionRows.filter((item) => taskHeartbeatRisk(item).stale).length
  const visibleQueued = productionRows.filter((item) => item.status === 'queued' || item.status === 'created').length
  const visibleFailed = productionRows.filter((item) => item.status === 'failed' || item.status === 'interrupted').length
  const visibleSnapshots = productionRows.filter((item) => item.task_type === 'factor_snapshot').length
  const visibleDataUpdates = productionRows.filter((item) => item.task_type === 'data_update').length
  const activeProfitArenaRuns = productionRows.filter((item) => isProfitArenaTask(item) && (item.status === 'running' || item.status === 'queued' || item.status === 'created'))
  const registeredTableCount = arenaDefinitions.reduce((sum, item) => sum + Object.values(item.tables || {}).filter(Boolean).length, 0)
  const factorReady = factorSnapshotReady(factorGovernance)
  const factorReadiness = factorReadinessSummary(factorGovernance, factorSnapshotStatus)
  const canCreateTraining = factorReady && activeProfitArenaRuns.length === 0
  const createTrainingTitle = !factorReady
    ? factorReadiness.hint
    : activeProfitArenaRuns.length > 0
      ? `已有 ${activeProfitArenaRuns.length} 个通用策略训练/推理任务未完成，请等待完成或到任务中心处理后再创建`
      : '基于当前因子快照创建通用策略训练任务'

  if (selectedTask) {
    if (isTaskCenterProductionTask(selectedTask)) {
      return (
        <ProductionTaskDetail
          task={selectedTask}
          onBack={() => { setSelectedTask(null) }}
          onRefresh={() => showDetail(selectedTask.id)}
          onStart={() => onStart(selectedTask.id)}
          onCancel={async () => { await cancelTask(selectedTask.id); await showDetail(selectedTask.id) }}
        />
      )
    }
    return (
      <div className="emptyState">
        <h2>生产任务</h2>
        <p>该任务不属于当前生产链路，任务中心只展示数据更新、因子快照、通用策略训练/推理和调仓链路。</p>
        <button className="secondaryButton quietButton" onClick={() => { setSelectedTask(null) }}>返回任务中心</button>
      </div>
    )
  }

  return (
    <div className="taskPage">
      <div className="taskModeTabs">
        <button className="active">生产任务</button>
      </div>
      <div className="formCard taskFormCard">
        <div className="taskAutoPanel">
          <div>
            <div className="formTitle">通用策略生产训练</div>
            <p className="recommendationMeta">当前生产口径只新建通用策略训练/推理任务；因子截面由数据更新后置任务生成，其他策略任务不进入本页。</p>
          </div>
          <div className="formActionsBottom taskActionsField">
            <button className="primaryButton" onClick={onCreate} disabled={!canCreateTraining} title={createTrainingTitle}>
              {!factorReady ? '等待因子快照' : activeProfitArenaRuns.length > 0 ? '训练任务进行中' : '创建通用策略训练'}
            </button>
          </div>
        </div>
        <div className={`productionReadinessBanner ${factorReady ? 'ready' : factorSnapshotStatus?.state === 'running' ? 'running' : 'blocked'}`}>
          <div>
            <span>生产前置门禁</span>
            <b>{factorReadiness.title}</b>
            <em>{factorReadiness.hint}</em>
          </div>
          <div className="productionReadinessSteps">
            <span className={factorReadiness.qualityOk ? 'pass' : 'wait'}>因子质量 {factorReadiness.qualityLabel}</span>
            <span className={factorReadiness.specOk ? 'pass' : 'wait'}>策略签名 {factorReadiness.specLabel}</span>
            <span className={factorSnapshotStatus?.state === 'running' ? 'run' : factorReady ? 'pass' : 'wait'}>快照任务 {statusText(factorSnapshotStatus?.state || 'idle')}</span>
          </div>
        </div>
        <div className="metricStrip compactMetrics taskObserverStrip">
          <div className="metricCard good"><span>运行中</span><b>{numberText(visibleRunning)}</b><em>正在执行的离线任务</em></div>
          <div className="metricCard bad"><span>心跳过期</span><b>{numberText(staleRunning)}</b><em>running 但 5 分钟未上报</em></div>
          <div className="metricCard"><span>通用策略活跃</span><b>{numberText(activeProfitArenaRuns.length)}</b><em>训练/推理互斥保护</em></div>
          <div className="metricCard"><span>排队/待启动</span><b>{numberText(visibleQueued)}</b><em>created / queued</em></div>
          <div className="metricCard bad"><span>失败/中断</span><b>{numberText(visibleFailed)}</b><em>需要查看详情里的失败原因</em></div>
          <div className="metricCard"><span>数据更新</span><b>{numberText(visibleDataUpdates)}</b><em>原子数据刷新任务</em></div>
          <div className="metricCard"><span>因子截面</span><b>{numberText(visibleSnapshots)}</b><em>数据更新后的后置任务</em></div>
          <div className="metricCard"><span>训练策略</span><b>{numberText(arenaDefinitions.length)}</b><em>{registeredTableCount ? `${registeredTableCount}张业务底表已登记` : '等待注册中心同步'}</em></div>
        </div>
      </div>

      <div className="tableCard taskTableCard">
        <div className="tableHeader">
          <div className="formTitle">生产任务记录</div>
          <div className="taskActions">
            <span className="mutedText">最近刷新 {refreshedAt ? compactDateTime(refreshedAt) : '—'}</span>
            <button className="secondaryButton quietButton" onClick={refresh}><RefreshCw size={15} />刷新</button>
          </div>
        </div>
        {error && <div className="errorBox">{error}</div>}
        {notice && <div className="saveHint">{notice}</div>}
        <div className="taskGridShell">
          <DataGrid
            className="taskGrid rdg-dark"
            columns={columns}
            rows={productionRows}
            rowKeyGetter={(row) => row.id}
            rowHeight={58}
            headerRowHeight={48}
            defaultColumnOptions={{ resizable: true }}
            enableVirtualization={false}
            onCellDoubleClick={({ row }) => showDetail(row.id)}
          />
          {productionRows.length === 0 && <div className="taskGridEmpty">暂无通用策略生产任务</div>}
        </div>
      </div>
    </div>
  )
}

function ProductionTaskDetail({ task, onBack, onRefresh, onStart, onCancel }: {
  task: TaskDTO
  onBack: () => void
  onRefresh: () => void
  onStart: () => void
  onCancel: () => void
}) {
  useEffect(() => {
    if (task.status !== 'running') return
    const timer = window.setInterval(onRefresh, 1200)
    return () => window.clearInterval(timer)
  }, [task.status, onRefresh])

  const stage = String(task.summary.stage || '')
  const name = String(task.summary.name || '')
  const message = humanRunStatusMessage(String(task.summary.message || task.error_message || ''))
  const idx = numberOf(task.summary.idx, 0)
  const total = numberOf(task.summary.total, 0)
  const progressPct = taskProgressPct(task)
  const progressText = total > 0 ? `${idx}/${total}` : `${progressPct}%`
  const factorSnapshotSummary = task.task_type === 'factor_snapshot' ? factorSnapshotDetailSummary(task) : null
  const evaluationGridSummary = task.task_type === 'model_training' && isProfitArenaTask(task) ? evaluationGridDetailSummary(task) : null
  const arenaStrategy = arenaStrategySummary(task)
  const detailKicker = realtimeTaskDetailKicker(task)
  const detailHint = realtimeTaskDetailHint(task)
  const heartbeat = taskHeartbeatRisk(task)
  const canStart = isTaskCenterRunnableTask(task) && (task.status === 'created' || task.status === 'queued' || task.status === 'failed' || task.status === 'interrupted' || task.status === 'cancelled')
  return (
    <div className="taskDetailPage">
      <button className="secondaryButton quietButton" onClick={onBack}><ArrowLeft size={15} />返回任务列表</button>
      <section className="dashboardPanel">
        <div className="tableHeader">
          <div>
            <div className="sectionLabel">{detailKicker}</div>
            <div className="dashboardPanelTitle">{task.name}</div>
            <div className="cardHint">{arenaStrategy?.label || detailHint} · {taskTypeLabel(task)} · {statusText(task.status)} · {arenaStrategy?.runId || task.external_run_id || task.id}</div>
          </div>
          <div className="taskActions">
            <button className="secondaryButton quietButton" onClick={onRefresh}><RefreshCw size={15} />刷新</button>
            {canStart && <button className="primaryButton" onClick={onStart}><Play size={15} />启动</button>}
            {isTaskCenterRunnableTask(task) && task.status === 'running' && <button className="secondaryButton quietButton" onClick={onCancel}><Square size={15} />取消</button>}
          </div>
        </div>
        <div className="signalProgress taskRefreshProgress">
          <div className="signalProgressHeader">
            <span>{stage || name || '等待进度'}</span>
            <span>{progressText}</span>
          </div>
          <div className="signalProgressBar"><div className="signalProgressBarFill" style={{ width: `${progressPct}%` }} /></div>
          {message && <div className={task.status === 'failed' || task.status === 'interrupted' ? 'errorText' : 'cardHint'}>{message}</div>}
        </div>
        {heartbeat.stale ? (
          <div className="productionReadinessBanner blocked">
            <div>
              <span>心跳过期</span>
              <b>任务疑似卡住</b>
              <em>{heartbeat.message}</em>
            </div>
            <div className="productionReadinessSteps">
              <span className="wait">最近上报 {heartbeat.ageText}</span>
              <span className="wait">建议 刷新 / 查看日志 / 取消后重跑</span>
            </div>
          </div>
        ) : null}
        {arenaStrategy ? (
          <div className="metricStrip compactMetrics">
            <Metric label="策略" value={arenaStrategy.displayName} hint={arenaStrategy.strategyId || undefined} />
            <Metric label="策略" value={arenaStrategy.arenaName || '—'} hint={arenaStrategy.taskKey || undefined} />
            <Metric label="Run" value={arenaStrategy.runShort || '—'} hint={arenaStrategy.runId || undefined} />
            <Metric label="链路" value={arenaStrategy.label || '版本训练'} />
            <Metric label="底表" value={arenaStrategy.tableSummary || '—'} hint={arenaStrategy.tableHint || undefined} />
          </div>
        ) : null}
        <div className="metricStrip compactMetrics">
          <Metric label="状态" value={statusText(task.status)} />
          <Metric label="进度" value={`${progressPct}%`} hint={progressText} />
          <Metric label="阶段" value={stage || '—'} hint={name || undefined} />
          <Metric label="日志" value={task.log_path ? '已写入' : '—'} hint={task.log_path || undefined} />
          <Metric label="进程" value={task.worker_pid ? `PID ${task.worker_pid}` : '—'} hint={task.worker_type || undefined} />
          <Metric label="结果" value={resultPathText(task)} hint={task.result_path || undefined} />
          <Metric label="更新时间" value={compactDateTime(task.updated_at) || '—'} hint={task.finished_at ? `完成 ${compactDateTime(task.finished_at)}` : task.started_at ? `启动 ${compactDateTime(task.started_at)}` : undefined} />
        </div>
        {factorSnapshotSummary ? (
          <div className="metricStrip compactMetrics">
            <Metric label="快照规模" value={factorSnapshotSummary.size} hint="rows / factors" />
            <Metric label="质量门禁" value={gateLabel(factorSnapshotSummary.quality || '')} />
            <Metric label="漂移状态" value={gateLabel(factorSnapshotSummary.drift || '')} />
            <Metric label="Manifest" value={factorSnapshotSummary.manifest ? '已生成' : '—'} hint={factorSnapshotSummary.manifest || undefined} />
          </div>
        ) : null}
        {evaluationGridSummary ? (
          <div className="metricStrip compactMetrics">
            <Metric label="评估网格" value={evaluationGridSummary.progress} hint="done / total" />
            <Metric label="预计剩余" value={evaluationGridSummary.eta} />
            <Metric label="门禁通过" value={evaluationGridSummary.gatePass} hint="hard gate pass" />
            <Metric label="当前最佳分" value={evaluationGridSummary.bestScore} tone={evaluationGridSummary.bestScoreTone} />
          </div>
        ) : null}
      </section>
    </div>
  )
}

function Metric({ label, value, tone = '', hint = '', className = '' }: { label: string; value: string; tone?: string; hint?: string; className?: string }) {
  return <div className={`metricCard ${className}`.trim()}><span>{label}</span><strong className={tone}>{value}</strong>{hint && <em title={hint}>{hint}</em>}</div>
}

function numberOf(value: unknown, fallback: number) {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function numberText(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  return Number(value).toFixed(digits)
}

function taskProgressPct(task: TaskDTO) {
  const pct = Number(task.progress) * 100
  if (!Number.isFinite(pct)) return 0
  return Math.max(0, Math.min(100, Math.round(pct)))
}

function percent(value: number, signed = false) {
  if (!Number.isFinite(value)) return '—'
  const pct = value * 100
  const sign = signed && pct >= 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
}

function metricPercentValue(value: number | null | undefined, signed = false) {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  return percent(Number(value), signed)
}

function toneOf(value: number) {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return ''
}

function scoreText(value: unknown) {
  const score = numberOf(value, NaN)
  return Number.isFinite(score) ? score.toFixed(1) : '—'
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function taskProgressLabel(task: TaskDTO) {
  if (task.parent_id) return `${task.sequence}/${task.total} · ${taskProgressPct(task)}%`
  if (task.task_type === 'factor_snapshot') {
    const snapshot = factorSnapshotTaskSummary(task)
    if (snapshot) return snapshot
  }
  if (task.task_type === 'model_training') {
    const grid = evaluationGridDetailSummary(task)
    if (grid) return `网格 ${grid.progress} · ${taskProgressPct(task)}%`
    const stage = realtimeTaskProgressStage(task)
    const pct = `${taskProgressPct(task)}%`
    return stage ? `${stage} · ${pct}` : pct
  }
  return `${taskProgressPct(task)}%`
}

function taskStageLabel(task: TaskDTO) {
  if (task.task_type === 'profit_arena_rebalance') return '调仓计划'
  if (task.task_type === 'data_update') return realtimeTaskProgressStage(task) || '原子数据'
  if (task.task_type === 'factor_snapshot') return realtimeTaskProgressStage(task) || '因子截面'
  if (task.task_type === 'model_training' && isProfitArenaTask(task)) return realtimeTaskProgressStage(task) || '训练/推理'
  return realtimeTaskProgressStage(task) || '—'
}

function taskObserverMessage(task: TaskDTO) {
  const message = humanRunStatusMessage(String(task.summary.message || task.error_message || '').trim())
  if (message) return message
  const stage = String(task.summary.stage || task.summary.name || '').trim()
  if (stage) return stage
  if (task.status === 'created' || task.status === 'queued') return '等待执行'
  if (task.status === 'running') return '运行中，等待下一次进度上报'
  if (task.status === 'success') return '已完成'
  if (task.status === 'cancelled') return '已取消'
  return ''
}

function arenaStrategySummary(task: TaskDTO) {
  const direct = asRecord(task.summary.arena_strategy)
  const observability = asRecord(task.summary.observability)
  const nested = asRecord(observability?.arena_strategy)
  const strategy = direct || nested
  if (!strategy) return null
  const displayName = String(strategy.display_name || '').trim() || (isProfitArenaTask(task) ? '通用策略' : String(task.name || '策略任务'))
  const label = String(strategy.task_label || '').trim()
  const strategyId = String(strategy.strategy_id || '').trim()
  const arenaName = String(strategy.arena_name || '').trim()
  const taskKey = String(strategy.task_key || '').trim()
  const runId = String(strategy.run_id || task.external_run_id || '').trim()
  const tables = asRecord(strategy.tables)
  const tableEntries = tables ? Object.entries(tables).map(([key, value]) => `${key}:${String(value || '').trim()}`).filter((item) => !item.endsWith(':')) : []
  return {
    displayName,
    label,
    strategyId,
    arenaName,
    taskKey,
    runId,
    runShort: runId ? compactRunId(runId) : '',
    tableSummary: tableEntries.length ? `${tableEntries.length}张` : '',
    tableHint: tableEntries.join(' · ')
  }
}

function compactRunId(runId: string) {
  const text = String(runId || '').trim()
  if (!text) return ''
  if (text.length <= 24) return text
  return `${text.slice(0, 11)}…${text.slice(-8)}`
}

function humanRunStatusMessage(message: string) {
  const parts = String(message || '').split('|').map((item) => item.trim()).filter(Boolean)
  if (parts.length > 1 && parts[0].includes('strategy_id=') && parts[0].includes('task_key=')) {
    return parts.slice(1).join(' | ')
  }
  return message
}

function factorSnapshotTaskSummary(task: TaskDTO) {
  const observability = asRecord(task.summary.observability)
  const snapshot = asRecord(observability?.factor_snapshot)
  const message = String(task.summary.message || task.error_message || '')
  const rows = numberOf(snapshot?.row_count, numberToken(message, 'rows'))
  const factors = numberOf(snapshot?.factor_count, numberToken(message, 'factors'))
  const quality = String(snapshot?.quality_status || valueToken(message, 'quality') || '')
  const drift = String(snapshot?.drift_status || valueToken(message, 'drift') || '')
  const parts = [
    rows > 0 ? `${rows}行` : '',
    factors > 0 ? `${factors}因子` : '',
    quality ? `质量${gateLabel(quality)}` : '',
    drift ? `漂移${gateLabel(drift)}` : '',
  ].filter(Boolean)
  return parts.length ? parts.join(' · ') : message
}

function compactDateTime(value: string) {
  const text = String(value || '').trim()
  if (!text) return '—'
  return formatDate(text).replace(/^\d{4}-/, '').replace('T', ' ').slice(0, 16)
}

const TASK_HEARTBEAT_STALE_MS = 5 * 60 * 1000

function taskHeartbeatRisk(task: TaskDTO) {
  if (task.status !== 'running') {
    return { stale: false, ageMs: 0, ageText: '', message: '' }
  }
  const timestamp = Date.parse(String(task.updated_at || task.started_at || ''))
  if (!Number.isFinite(timestamp)) {
    return {
      stale: true,
      ageMs: Number.POSITIVE_INFINITY,
      ageText: '未知',
      message: '任务处于运行中，但没有有效的更新时间；请刷新任务或查看日志确认 worker 是否仍在上报。'
    }
  }
  const ageMs = Date.now() - timestamp
  const stale = ageMs > TASK_HEARTBEAT_STALE_MS
  const ageSeconds = ageMs / 1000
  return {
    stale,
    ageMs,
    ageText: durationText(ageSeconds),
    message: stale
      ? `任务处于运行中，但最近 ${durationText(ageSeconds)} 没有新的阶段/进度上报；可能是 worker 卡住、进程退出但状态未回写，或底层数据源长时间阻塞。`
      : ''
  }
}

function realtimeTaskDetailKicker(task: TaskDTO) {
  if (task.task_type === 'factor_snapshot') return 'FACTOR SNAPSHOT TASK'
  if (task.task_type === 'data_update') return 'DATA UPDATE TASK'
  if (task.task_type === 'model_training' && isProfitArenaTask(task)) return 'PROFIT ARENA TASK'
  return 'REALTIME TASK'
}

function realtimeTaskDetailHint(task: TaskDTO) {
  if (task.task_type === 'factor_snapshot') return '数据更新后的后置因子截面任务'
  if (task.task_type === 'data_update') return '原子数据更新任务，成功后会按阶段自动触发通用策略因子快照'
  if (task.task_type === 'model_training' && isProfitArenaTask(task)) return '通用策略训练/推理任务'
  return '实时进度任务'
}

function realtimeTaskProgressStage(task: TaskDTO) {
  const direct = String(task.summary.name || task.summary.stage || task.subtask_name || task.subtask_key || '').trim()
  if (direct) return direct
  const message = String(task.summary.message || task.error_message || '')
  if (valueToken(message, 'buy_plan')) return `买入计划${buyPlanLabel(valueToken(message, 'buy_plan'))}`
  if (valueToken(message, 'portfolio_status')) return `组合预算${gateLabel(valueToken(message, 'portfolio_status'))}`
  if (valueToken(message, 'status')) return `门禁${gateLabel(valueToken(message, 'status'))}`
  if (valueToken(message, 'quality')) return `因子质量${gateLabel(valueToken(message, 'quality'))}`
  if (valueToken(message, 'drift')) return `因子漂移${gateLabel(valueToken(message, 'drift'))}`
  if (message.includes('capacity_pass') || message.includes('capacity_fail')) return '容量门禁'
  if (message.includes('gate_pass') || message.includes('gate_fail')) return '硬门禁'
  if (message.includes('rows=') || message.includes('factors=')) return '快照摘要'
  return ''
}

function buyPlanLabel(status: string) {
  if (status === 'ready') return '就绪'
  if (status === 'partial_capacity') return '容量部分可用'
  if (status === 'blocked_by_capacity') return '容量阻断'
  if (status === 'blocked_by_portfolio_risk') return '组合风险阻断'
  if (status === 'missing') return '等待'
  return status
}

function factorSnapshotDetailSummary(task: TaskDTO) {
  const observability = asRecord(task.summary.observability)
  const snapshot = asRecord(observability?.factor_snapshot)
  const message = String(task.summary.message || task.error_message || '')
  const rows = numberOf(snapshot?.row_count, numberToken(message, 'rows'))
  const factors = numberOf(snapshot?.factor_count, numberToken(message, 'factors'))
  const quality = String(snapshot?.quality_status || valueToken(message, 'quality') || '')
  const drift = String(snapshot?.drift_status || valueToken(message, 'drift') || '')
  const manifest = String(snapshot?.manifest_path || valueToken(message, 'manifest') || '')
  if (!rows && !factors && !quality && !drift && !manifest) return null
  return {
    size: rows || factors ? `${rows || '—'} / ${factors || '—'}` : '—',
    quality,
    drift,
    manifest,
  }
}

function evaluationGridDetailSummary(task: TaskDTO) {
  const observability = asRecord(task.summary.observability)
  const grid = asRecord(observability?.evaluation_grid)
  const message = String(task.summary.message || task.error_message || '')
  const done = numberOf(grid?.done, numberToken(message, 'done'))
  const total = numberOf(grid?.total, numberToken(message, 'total'))
  const eta = numberOf(grid?.eta_seconds, numberToken(message, 'eta'))
  const gatePass = numberOf(grid?.gate_pass_count, numberToken(message, 'gate_pass'))
  const bestScore = numberOf(grid?.best_arena_score, Number(valueToken(message, 'best_score')))
  if (!done && !total && !eta && !gatePass && !Number.isFinite(bestScore)) return null
  return {
    progress: total > 0 ? `${done}/${total}` : done > 0 ? String(done) : '—',
    eta: eta > 0 ? durationText(eta) : '—',
    gatePass: String(gatePass || 0),
    bestScore: Number.isFinite(bestScore) ? bestScore.toFixed(1) : '—',
    bestScoreTone: Number.isFinite(bestScore) && bestScore > 0 ? 'positive' : ''
  }
}

function valueToken(message: string, key: string) {
  const match = new RegExp(`${key}=([^\\s,;]+)`).exec(message)
  return match ? match[1].trim() : ''
}

function numberToken(message: string, key: string) {
  const value = Number(valueToken(message, key))
  return Number.isFinite(value) ? value : 0
}

function gateLabel(status: string) {
  if (status === 'pass') return '通过'
  if (status === 'warn') return '警告'
  if (status === 'fail') return '失败'
  if (status === 'missing') return '等待'
  return status
}

function durationText(seconds: number) {
  if (!Number.isFinite(seconds) || seconds <= 0) return '—'
  if (seconds < 60) return `${Math.round(seconds)}秒`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  if (minutes < 60) return rest > 0 ? `${minutes}分${rest}秒` : `${minutes}分钟`
  const hours = Math.floor(minutes / 60)
  const minuteRest = minutes % 60
  return minuteRest > 0 ? `${hours}小时${minuteRest}分` : `${hours}小时`
}

function taskMetric(task: TaskDTO, key: string) {
  return numberOf(task.summary[key], NaN)
}

function metricPercent(task: TaskDTO, key: string, signed = false) {
  const value = taskMetric(task, key)
  return Number.isFinite(value) ? percent(value, signed) : '—'
}

function metricNumber(task: TaskDTO, key: string) {
  const value = taskMetric(task, key)
  return Number.isFinite(value) ? value.toFixed(2) : '—'
}

function taskTypeLabel(task: TaskDTO) {
  if (task.task_type === 'data_update') return '数据更新'
  if (task.task_type === 'factor_snapshot') return '因子快照'
  if (task.task_type === 'model_training' && isProfitArenaTask(task)) return '通用策略'
  return task.task_type
}

function isHistoricalOfflineTask(task: TaskDTO) {
  if (task.task_type === 'model_training' && !isProfitArenaTask(task)) return true
  return false
}

function isTaskCenterProductionTask(task: TaskDTO) {
  if (task.parent_id) return false
  if (task.task_type === 'data_update') return true
  if (task.task_type === 'model_training') return isProfitArenaTask(task)
  if (task.task_type === 'factor_snapshot') return true
  if (task.task_type === 'profit_arena_rebalance') return true
  return false
}

function isTaskCenterRunnableTask(task: TaskDTO) {
  if (isHistoricalOfflineTask(task)) return false
  if (task.task_type === 'data_update') return false
  if (task.task_type === 'profit_arena_rebalance') return false
  if (task.task_type === 'factor_snapshot') return false
  return true
}

function taskCenterReadOnlyLabel(task: TaskDTO) {
  if (task.task_type === 'data_update') return '数据页触发'
  if (task.task_type === 'profit_arena_rebalance') return '通用策略调仓'
  if (task.task_type === 'factor_snapshot') return '回数据页重跑数据更新触发'
  return '只读'
}

function isProfitArenaTask(task: TaskDTO) {
  const strategy = String(task.params.strategy || '')
  const name = String(task.name || '')
  const external = String(task.external_run_id || '')
  return strategy.includes('profit_arena') || name.includes('通用策略') || external.includes('profit_arena')
}

function factorSnapshotReady(governance: FactorStoreGovernance) {
  const gate = parseJSONRecord(governance.quality_gate)
  const spec = parseJSONRecord(governance.profit_arena_spec)
  const gateStatus = String(gate.status || governance.status || 'missing').toLowerCase()
  const specStatus = String(spec.status || governance.snapshot_fresh_status || 'missing').toLowerCase()
  return (gateStatus === 'pass' || gateStatus === 'warn') && specStatus === 'pass'
}

function factorReadinessSummary(governance: FactorStoreGovernance, status: RunStatus | null) {
  const gate = parseJSONRecord(governance.quality_gate)
  const spec = parseJSONRecord(governance.profit_arena_spec)
  const gateStatus = String(gate.status || governance.status || 'missing').toLowerCase()
  const specStatus = String(spec.status || governance.snapshot_fresh_status || 'missing').toLowerCase()
  const qualityOk = gateStatus === 'pass' || gateStatus === 'warn'
  const specOk = specStatus === 'pass'
  if (status?.state === 'running') {
    return {
      title: '因子快照生成中',
      hint: runStatusMessage(status) || '等待数据更新后的因子截面任务完成',
      qualityOk,
      specOk,
      qualityLabel: gateLabel(gateStatus),
      specLabel: gateLabel(specStatus)
    }
  }
  if (qualityOk && specOk) {
    return {
      title: '可以创建通用策略训练',
      hint: '当前因子快照质量和通用策略签名均满足生产训练要求',
      qualityOk,
      specOk,
      qualityLabel: gateLabel(gateStatus),
      specLabel: gateLabel(specStatus)
    }
  }
  return {
    title: '先更新数据并抽取因子',
    hint: '请到数据管理运行全部/基础/行情更新；成功后会自动生成因子快照并解锁训练',
    qualityOk,
    specOk,
    qualityLabel: gateLabel(gateStatus),
    specLabel: gateLabel(specStatus)
  }
}

function parseJSONRecord(value?: unknown): Record<string, unknown> {
  if (!value) return {}
  if (typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
  try {
    const parsed = JSON.parse(String(value))
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {}
  } catch {
    return {}
  }
}

function runStatusMessage(status: RunStatus | null | undefined) {
  if (!status) return '等待任务状态上报'
  const parts = [status.stage, status.name, status.message].map((item) => String(item || '').trim()).filter(Boolean)
  if (parts.length) return parts.join(' · ')
  if (status.state === 'idle' || status.state === '') return '等待数据更新成功后自动触发'
  if (status.state === 'running') return '任务已启动，等待阶段进度上报'
  return '等待任务进度上报'
}

function statusText(status: string) {
  return ({ created: '待启动', queued: '排队中', running: '运行中', success: '已完成', done: '已完成', failed: '失败', error: '失败', cancelled: '已取消', interrupted: '异常中断', skipped: '已跳过', historical_offline: '已归档', promotable: '可观察', research: '研究中', rejected: '拒绝', paper: '观察中', active: '生效', idle: '空闲' } as Record<string, string>)[status] || status
}

function statusBadgeClass(status: string) {
  if (status === 'success' || status === 'done' || status === 'active' || status === 'promotable') return 'success'
  if (status === 'running' || status === 'queued' || status === 'research' || status === 'paper') return 'running'
  if (status === 'skipped') return 'created'
  if (status === 'failed' || status === 'error' || status === 'interrupted' || status === 'cancelled' || status === 'rejected' || status === 'historical_offline') return 'failed'
  return 'created'
}

function resultPathText(task: TaskDTO) {
  if (!task.result_path) return '—'
  if (task.status === 'success') return '已生成'
  if (task.status === 'running' || task.status === 'queued') return '生成中'
  if (task.status === 'failed' || task.status === 'cancelled' || task.status === 'interrupted') return '未完成'
  return '待生成'
}
