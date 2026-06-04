import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, Play, RefreshCw, Sparkles, Square, Trash2 } from 'lucide-react'
import { DataGrid, type Column } from 'react-data-grid'
import * as echarts from 'echarts/core'
import { DataZoomComponent, GridComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import { LineChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { analyzePortfolioTask, applyPortfolioCandidate, cancelTask, createTask, deleteTask, getSettings, getTimeMachineDetail, listTasks, listValidationEvidence, refreshTaskStatus, startTask, type TaskDTO, type TimeMachineDetail, type ValidationEvidence } from '../services/app'
import { formatDate } from '../components/format'

const evaluationTaskTypes = new Set(['evaluation_time_machine', 'strategy_evaluation', 'portfolio_optimization', 'walk_forward_evaluation', 'parameter_experiment'])
const evaluationHorizon = {
  fullCycleStartDate: '20100101',
  portfolioYears: 6,
  parameterYears: 6,
  walkForwardWindowCount: 8
}

echarts.use([CanvasRenderer, DataZoomComponent, GridComponent, LineChart, TitleComponent, TooltipComponent])

export function TaskCenterPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [tasks, setTasks] = useState<TaskDTO[]>([])
  const [selectedTask, setSelectedTask] = useState<TaskDTO | null>(null)
  const [detail, setDetail] = useState<TimeMachineDetail | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [aiAnalyzing, setAiAnalyzing] = useState(false)
  const [nextEvalCreating, setNextEvalCreating] = useState(false)
  const name = '时光机'
  const admissionStartDate = evaluationHorizon.fullCycleStartDate
  const portfolioStartDate = useMemo(() => formatYYYYMMDD(addYears(new Date(), -evaluationHorizon.portfolioYears)), [])
  const parameterStartDate = useMemo(() => formatYYYYMMDD(addYears(new Date(), -evaluationHorizon.parameterYears)), [])
  const walkForwardStartDate = evaluationHorizon.fullCycleStartDate
  const endDate = useMemo(() => formatYYYYMMDD(new Date()), [])
  const initialCash = 500000
  const rebalanceFreq = 5
  const [exitEnabled, setExitEnabled] = useState(false)
  const [stopLossPct, setStopLossPct] = useState(-12)
  const [trailingStopPct, setTrailingStopPct] = useState(-8)
  const [trailingExec, setTrailingExec] = useState('next_open')
  const [slippageBp, setSlippageBp] = useState(30)
  const optimizationObjective = '平衡'
  const topN = 40

  const refresh = async () => {
    const items = (await listTasks({ limit: 500 })).filter((item) => evaluationTaskTypes.has(item.task_type))
    setTasks(items)
    if (selectedTask) {
      const latest = items.find((item) => item.id === selectedTask.id)
      if (latest) setSelectedTask(latest)
    }
  }

  const showDetail = async (id: string) => {
    const task = await refreshTaskStatus(id)
    const tm = task.task_type === 'strategy_evaluation' || task.task_type === 'portfolio_optimization' || task.task_type === 'walk_forward_evaluation' || task.task_type === 'parameter_experiment' ? null : await getTimeMachineDetail(id).catch(() => null)
    setSelectedTask(task)
    setDetail(tm)
    await refresh()
  }

  useEffect(() => {
    refresh()
    getSettings().then((response) => {
      const exitRules = response.settings.exit_rules || {}
      setExitEnabled(Boolean(exitRules.enabled))
      setStopLossPct(Number(exitRules.stop_loss ?? -0.12) * 100)
      setTrailingStopPct(Number(exitRules.trailing_stop ?? -0.08) * 100)
      setTrailingExec(String(exitRules.trailing_exec || 'next_open'))
      setSlippageBp(Number(exitRules.slippage ?? 0.003) * 10000)
    })
  }, [])

  const onCreate = async () => {
    setError('')
    try {
      await createTask({
        name,
        task_type: 'portfolio_optimization',
        params: {
          start_date: portfolioStartDate,
          end_date: endDate,
          strategies: 'enabled',
          objective: optimizationObjective,
          top_n: topN,
          benchmark: '000905.SH',
          slippage: slippageBp / 10000
        }
      })
      await refresh()
      setNotice('已创建时光机，策略池会优先使用最近一次策略准入结果')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const onCreateStrategyAdmission = async () => {
    setError('')
    try {
      await createTask({
        name: `策略准入-${admissionStartDate}-${endDate}`,
        task_type: 'strategy_evaluation',
        params: {
          start_date: admissionStartDate,
          end_date: endDate,
          strategies: 'all',
          baseline: 'small_cap_quality',
          benchmark: '000905.SH',
          slippage: slippageBp / 10000
        }
      })
      await refresh()
      setNotice('已创建策略准入评估，运行完成后会影响下一次时光机策略池')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const onCreateWalkForward = async () => {
    setError('')
    try {
      await createTask({
        name: `Walk-forward-${walkForwardStartDate}-${endDate}`,
        task_type: 'walk_forward_evaluation',
        params: {
          start_date: walkForwardStartDate,
          end_date: endDate,
          strategies: 'all',
          baseline: 'small_cap_quality',
          benchmark: '000905.SH',
          slippage: slippageBp / 10000,
          window_count: evaluationHorizon.walkForwardWindowCount,
          strategy_version_mode: 'latest'
        }
      })
      await refresh()
      setNotice('已创建 Walk-forward 样本外稳定性评估')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const onCreateParameterExperiment = async () => {
    setError('')
    try {
      await createTask({
        name: `参数实验-${parameterStartDate}-${endDate}`,
        task_type: 'parameter_experiment',
        params: {
          start_date: parameterStartDate,
          end_date: endDate,
          strategies: 'all',
          baseline: 'small_cap_quality',
          benchmark: '000905.SH',
          slippage: slippageBp / 10000,
          strategy_version_mode: 'latest'
        }
      })
      await refresh()
      setNotice('已创建策略参数网格实验，结果会写入治理表')
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

  const onAnalyzePortfolio = async (id: string) => {
    setError('')
    setAiAnalyzing(true)
    try {
      const updated = await analyzePortfolioTask(id)
      setSelectedTask(updated)
      setNotice('量化优化分析已生成')
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      const updated = await refreshTaskStatus(id).catch(() => null)
      if (updated) setSelectedTask(updated)
    } finally {
      setAiAnalyzing(false)
    }
  }

  const applyCandidate = async (task: TaskDTO, row: Record<string, unknown>) => {
    const candidateId = String(row.candidate_id || '')
    if (!candidateId) return
    await applyPortfolioCandidate({ run_id: task.external_run_id, candidate_id: candidateId })
    setNotice(`已应用方案入场权重：${String(row.name || candidateId)}`)
  }

  const createReviewTask = async (task: TaskDTO, row: Record<string, unknown>) => {
    await applyCandidate(task, row)
    const strategies = String(row.strategies || '').split(',').map((item) => item.trim()).filter(Boolean)
    const exitArchitecture = asRecord(row.exit_architecture) || asRecord(asRecord(row.scheme)?.exit_architecture)
    const rebalance = numberOf(row.rebalance_freq, rebalanceFreq)
    await createTask({
      name: `复核-${String(row.name || '方案')}`,
      task_type: 'evaluation_time_machine',
      params: {
        start_date: task.params.start_date || task.summary.start,
        end_date: task.params.end_date || task.summary.end,
        initial_cash: initialCash,
        rebalance_freq: rebalance,
        use_signal_cache: true,
        strategies_filter: strategies,
        exit_rules_cfg: exitArchitecture || {
          enabled: exitEnabled,
          stop_loss: stopLossPct / 100,
          trailing_stop: trailingStopPct / 100,
          trailing_exec: trailingExec,
          slippage: slippageBp / 10000
        }
      }
    })
    setSelectedTask(null)
    setDetail(null)
    setNotice(`已创建方案复核时光机：${String(row.name || '')}`)
    await refresh()
  }

  const createNextPortfolioEvaluation = async (task: TaskDTO) => {
    const nextConfig = asRecord(task.summary.ai_next_eval_config) || asRecord(asRecord(task.summary.ai_recommendation)?.next_eval_config)
    const params = asRecord(nextConfig?.params)
    if (!nextConfig || !params) {
      setError('优化器还没有给出可创建的下一轮评估配置，请先运行量化优化')
      return
    }
    setError('')
    setNextEvalCreating(true)
    try {
      const created = await createTask({
        name: String(nextConfig.name || `${task.name} - 下一轮`),
        task_type: String(nextConfig.task_type || 'portfolio_optimization'),
        params
      })
      setNotice(`已创建下一轮评估：${created.name}`)
      setSelectedTask(null)
      setDetail(null)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setNextEvalCreating(false)
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
      key: 'status',
      name: '状态',
      width: 96,
      renderCell: ({ row }) => <span className={`badge ${row.status}`}>{row.status}</span>
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
      key: 'actions',
      name: '操作',
      width: 220,
      cellClass: 'taskGridActionsCell',
      headerCellClass: 'taskGridActionsCell',
      renderCell: ({ row }) => (
        <div className="taskActions">
          <button className="secondaryButton quietButton" onClick={() => showDetail(row.id)}>详情</button>
          {row.task_type !== 'data_update' && row.task_type !== 'daily_signal' && row.status !== 'running' && (
            <button className="secondaryButton startButton" onClick={() => onStart(row.id)}><Play size={15} />启动</button>
          )}
          {row.task_type !== 'data_update' && row.task_type !== 'daily_signal' && row.status === 'running' && (
            <button className="secondaryButton dangerButton" onClick={async () => { await cancelTask(row.id); await refresh() }}><Square size={15} />取消</button>
          )}
          <button className="iconButton dangerIconButton" onClick={async () => { await deleteTask(row.id); await refresh() }}><Trash2 size={16} /></button>
        </div>
      )
    }
  ], [onStart, refresh, showDetail])

  const tableRows = useMemo(() => tasks.filter((item) => !item.parent_id), [tasks])

  if (selectedTask) {
    if (selectedTask.task_type === 'portfolio_optimization') {
      return (
        <PortfolioOptimizationDetail
          task={selectedTask}
          childTasks={tasks.filter((item) => item.parent_id === selectedTask.id)}
          onBack={() => { setSelectedTask(null); setDetail(null) }}
          onRefresh={() => showDetail(selectedTask.id)}
          onStart={() => onStart(selectedTask.id)}
          onCancel={async () => { await cancelTask(selectedTask.id); await showDetail(selectedTask.id) }}
          onAnalyze={() => onAnalyzePortfolio(selectedTask.id)}
          aiAnalyzing={aiAnalyzing}
          onCreateNext={() => createNextPortfolioEvaluation(selectedTask)}
          nextEvalCreating={nextEvalCreating}
          onApply={(row) => applyCandidate(selectedTask, row)}
          onReview={(row) => createReviewTask(selectedTask, row)}
        />
      )
    }
    if (selectedTask.task_type === 'strategy_evaluation' || selectedTask.task_type === 'walk_forward_evaluation' || selectedTask.task_type === 'parameter_experiment') {
      return (
        <StrategyEvaluationDetail
          task={selectedTask}
          childTasks={tasks.filter((item) => item.parent_id === selectedTask.id)}
          onBack={() => { setSelectedTask(null); setDetail(null) }}
          onRefresh={() => showDetail(selectedTask.id)}
          onStart={() => onStart(selectedTask.id)}
          onCancel={async () => { await cancelTask(selectedTask.id); await showDetail(selectedTask.id) }}
        />
      )
    }
    if (selectedTask.task_type === 'evaluation_time_machine') {
      return (
        <EvaluationDetail
          task={selectedTask}
          detail={detail}
          onOpenResearch={onOpenResearch}
          onBack={() => { setSelectedTask(null); setDetail(null) }}
          onRefresh={() => showDetail(selectedTask.id)}
          onStart={() => onStart(selectedTask.id)}
          onCancel={async () => { await cancelTask(selectedTask.id); await showDetail(selectedTask.id) }}
        />
      )
    }
    return (
      <div className="emptyState">
        <h2>非评估任务</h2>
        <p>该任务属于其他业务模块，不在评估中心展示详情。</p>
        <button className="secondaryButton quietButton" onClick={() => { setSelectedTask(null); setDetail(null) }}>返回评估中心</button>
      </div>
    )
  }

  return (
    <div className="taskPage">
      <div className="taskModeTabs">
        <button className="active">时光机</button>
      </div>
      <div className="formCard taskFormCard">
        <div className="taskAutoPanel">
          <div>
            <div className="formTitle">一键研究评估</div>
            <p className="recommendationMeta">系统自动选择评估区间、交易成本、样本外验证和推荐规模，先跑策略准入，再进入时光机闭环。</p>
          </div>
          <div className="formActionsBottom taskActionsField">
            <button className="secondaryButton quietButton" onClick={onCreateStrategyAdmission}>创建策略准入</button>
            <button className="secondaryButton quietButton" onClick={onCreateWalkForward}>创建 Walk-forward</button>
            <button className="secondaryButton quietButton" onClick={onCreateParameterExperiment}>创建参数实验</button>
            <button className="primaryButton" onClick={onCreate}>创建时光机</button>
          </div>
        </div>
      </div>

      <div className="tableCard taskTableCard">
        <div className="tableHeader">
          <div className="formTitle">评估记录</div>
          <button className="secondaryButton quietButton" onClick={refresh}><RefreshCw size={15} />刷新</button>
        </div>
        {error && <div className="errorBox">{error}</div>}
        {notice && <div className="saveHint">{notice}</div>}
        <div className="taskGridShell">
          <DataGrid
            className="taskGrid rdg-dark"
            columns={columns}
            rows={tableRows}
            rowKeyGetter={(row) => row.id}
            rowHeight={58}
            headerRowHeight={48}
            defaultColumnOptions={{ resizable: true }}
            enableVirtualization={false}
            onCellDoubleClick={({ row }) => showDetail(row.id)}
          />
          {tableRows.length === 0 && <div className="taskGridEmpty">暂无评估</div>}
        </div>
      </div>
    </div>
  )
}

function EvaluationDetail({ task, detail, onOpenResearch, onBack, onRefresh, onStart, onCancel }: {
  task: TaskDTO
  detail: TimeMachineDetail | null
  onOpenResearch?: (tsCode: string) => void
  onBack: () => void
  onRefresh: () => void
  onStart: () => void
  onCancel: () => void
}) {
  useEffect(() => {
    if (task.status !== 'running') return
    const timer = window.setInterval(onRefresh, 3000)
    return () => window.clearInterval(timer)
  }, [task.status, onRefresh])

  const summary = detail?.summary || task.summary || {}
  const snapshots = detail?.snapshots || []
  const trades = detail?.trades || []
  const positions = detail?.positions || []
  const latest = snapshots[snapshots.length - 1]
  const todayTrades = latest ? trades.filter((trade) => trade.date === latest.date) : []
  const initialCash = numberOf(summary.initial_cash, numberOf(task.params.initial_cash, latest ? latest.equity / (1 + latest.cum_return) : 500000))
  const totalReturn = numberOf(summary.total_return, latest?.cum_return || 0)
  const totalPnl = numberOf(summary.total_pnl, numberOf(summary.final_equity, latest?.equity || initialCash) - initialCash)
  const strategies = Array.isArray(summary.strategies) ? summary.strategies as Array<Record<string, unknown>> : []
  const progress = progressOf(summary)
  const isRunning = task.status === 'running'
  const isUserCancelled = task.status === 'cancelled' && task.error_message
  const isErrorStatus = (task.status === 'failed' || task.status === 'interrupted') && task.error_message
  const latestDate = latest?.date || progress.date || ''
  const runningTrades = latestDate ? trades.filter((trade) => trade.date === latestDate) : []
  const todayTradeByCode = new Map(todayTrades.filter((trade) => trade.action === 'BUY' || trade.action === 'ADD').map((trade) => [trade.ts_code, trade]))
  const positionPct = latest && latest.equity > 0 ? latest.market_value / latest.equity : 0
  const modeText = String(summary.mode || (strategies.length > 1 ? 'combo' : 'single')) === 'combo' ? '组合' : '单策略'
  const evalName = String(summary.eval_name || task.name || '').trim()
  const nDays = numberOf(summary.n_days, snapshots.length)
  const [tradePage, setTradePage] = useState(1)
  const [snapshotPage, setSnapshotPage] = useState(1)
  const pageSize = 10
  const tradeRows = isRunning ? runningTrades : trades.slice(-200)
  const sortedTradeRows = tradeRows.slice().reverse()
  const tradePageCount = Math.max(1, Math.ceil(sortedTradeRows.length / pageSize))
  const visibleTradeRows = sortedTradeRows.slice((Math.min(tradePage, tradePageCount) - 1) * pageSize, Math.min(tradePage, tradePageCount) * pageSize)
  const sortedSnapshotRows = snapshots.slice().reverse()
  const snapshotPageCount = Math.max(1, Math.ceil(sortedSnapshotRows.length / pageSize))
  const visibleSnapshotRows = sortedSnapshotRows.slice((Math.min(snapshotPage, snapshotPageCount) - 1) * pageSize, Math.min(snapshotPage, snapshotPageCount) * pageSize)

  useEffect(() => {
    setTradePage(1)
    setSnapshotPage(1)
  }, [detail?.run_id, task.id])

  return (
    <div className="evaluationDetailPage">
      <div className="detailHero">
        <div>
          <div className="sectionLabel">TIME MACHINE</div>
          <h2>{task.name}</h2>
          <p>
            {task.external_run_id || task.id}
            {isUserCancelled && <span className="inlineRunStatus">（{task.error_message}）</span>}
            {isErrorStatus && <span className="inlineRunStatus error">（{task.error_message}）</span>}
          </p>
        </div>
        <div className="detailHeroActions">
          <button className="secondaryButton quietButton" onClick={onBack}><ArrowLeft size={15} />返回</button>
          <button className="secondaryButton quietButton" onClick={onRefresh}><RefreshCw size={15} />刷新</button>
          {task.status === 'running' ? <button className="secondaryButton dangerButton" onClick={onCancel}><Square size={15} />取消</button> : <button className="secondaryButton startButton heroStartButton" onClick={onStart}><Play size={15} />启动评估</button>}
        </div>
      </div>

      {isRunning && (
        <div className="liveRunPanel">
          <div className="runStatus">
            <span className="pulse" />
            <span className="runStatusLabel">TIME MACHINE</span>
            <b>{latestDate || '准备中'}</b>
            <span>{stageText(progress.stage)} · {progressText(task.progress, progress)} · {etaText(progress.eta_sec)}</span>
          </div>
          <div className="liveKpiGrid">
            <Metric label="当前日期" value={latestDate || '—'} hint={progress.total_days ? `第 ${progress.cur_day || 0}/${progress.total_days} 天` : '等待首个快照'} />
            <Metric label="当前权益" value={latest ? money(latest.equity) : money(initialCash)} hint={`本金 ${money(initialCash)}`} />
            <Metric label="累计收益" value={signedMoney((latest?.equity || initialCash) - initialCash)} hint={percent(latest?.cum_return || 0, true)} tone={(latest?.cum_return || 0) >= 0 ? 'positive' : 'negative'} />
            <Metric label="仓位率" value={percent(positionPct)} hint={`${latest?.n_holdings || 0} 只 · ${trades.length} 笔`} />
          </div>
          <div className="accountDetailCard">
            <div className="formTitle">账户明细</div>
            <div className="accountDetailGrid">
              <AccountRow label="初始本金" value={money(initialCash, 2)} />
              <AccountRow label="当前总权益" value={money(latest?.equity || initialCash, 2)} />
              <AccountRow label="已投入（持仓市值）" value={money(latest?.market_value || 0, 2)} />
              <AccountRow label="可用现金" value={money(latest?.cash || initialCash, 2)} />
              <AccountRow label="浮动盈亏（持仓未平）" value={signedMoney(latest?.unrealized_pnl || 0, 2)} tone={(latest?.unrealized_pnl || 0) >= 0 ? 'positive' : 'negative'} />
              <AccountRow label="已实现盈亏（卖出落袋）" value={signedMoney(latest?.realized_pnl || 0, 2)} tone={(latest?.realized_pnl || 0) >= 0 ? 'positive' : 'negative'} />
              <AccountRow label="总盈亏" value={`${signedMoney((latest?.equity || initialCash) - initialCash, 2)}（${percent(latest?.cum_return || 0, true)}）`} tone={(latest?.cum_return || 0) >= 0 ? 'positive' : 'negative'} strong />
              <AccountRow label="仓位率 / 持仓数" value={`${percent(positionPct)} · ${latest?.n_holdings || 0} 只`} />
            </div>
            <div className="accountNote">注：本工具采用复利滚动模式，每次调仓均按当前总权益重新计算目标仓位。</div>
          </div>
        </div>
      )}

      <div className="detailGrid">
        <div><span>状态</span><b>{statusText(task.status)}</b></div>
        <div><span>进度</span><b>{Math.round(task.progress * 100)}%</b></div>
        <div><span>最终权益</span><b>{money(numberOf(summary.final_equity, latest?.equity || 0))}</b></div>
        <div><span>累计收益</span><b className={totalReturn >= 0 ? 'positive' : 'negative'}>{percent(totalReturn, true)}</b></div>
      </div>

      <div className="metricGrid">
        <Metric label="总收益" value={signedMoney(totalPnl)} hint={`${percent(totalReturn, true)} 累计`} tone={totalReturn >= 0 ? 'positive' : 'negative'} />
        <Metric label="年化收益" value={percent(numberOf(summary.annual_return, 0), true)} hint={nDays ? `基于 ${nDays} 个交易日` : ''} tone={numberOf(summary.annual_return, 0) >= 0 ? 'positive' : 'negative'} />
        <Metric label="最大回撤" value={percent(numberOf(summary.max_drawdown, 0))} tone="negative" />
        <Metric label="夏普" value={numberOf(summary.sharpe, 0).toFixed(2)} />
        <Metric label="胜率" value={percent(numberOf(summary.win_rate, 0))} hint="盈利交易日占比" />
        <Metric label="成交笔数" value={String(numberOf(summary.n_trades, trades.length))} />
        <Metric label="最终权益" value={money(numberOf(summary.final_equity, latest?.equity || initialCash))} hint={`本金 ${money(initialCash)}`} />
        <Metric label="已实现/浮动" value={`${signedMoney(numberOf(summary.realized_pnl, latest?.realized_pnl || 0))} / ${signedMoney(numberOf(summary.unrealized_pnl, latest?.unrealized_pnl || 0))}`} hint="拆分" />
      </div>

      {(evalName || strategies.length > 0) && (
        <div className="strategySummaryCard">
          {evalName && <div><span>评估名字</span><b>{evalName}</b></div>}
          {strategies.length > 0 && (
            <div>
              <span>本次评估策略（{modeText} · {strategies.length} 个）</span>
              <div className="strategyChips">
                {strategies.map((strategy) => <span key={String(strategy.name)}>{String(strategy.label || strategy.name)} · {percent(numberOf(strategy.weight, 0))}</span>)}
              </div>
            </div>
          )}
        </div>
      )}

      {latest && (
        <div className="accountStrip">
          <div><span>当前日期</span><b>{latest.date}</b></div>
          <div><span>现金</span><b>{money(latest.cash)}</b></div>
          <div><span>持仓市值</span><b>{money(latest.market_value)}</b></div>
          <div><span>仓位</span><b>{percent(latest.equity > 0 ? latest.market_value / latest.equity : 0)}</b></div>
          <div><span>当日成交</span><b>{todayTrades.length} 笔</b></div>
        </div>
      )}

      <div className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="formTitle">净值回放</div>
            <div className="mutedText">{summary.start as string || task.params.start_date as string} → {summary.end as string || task.params.end_date as string}</div>
          </div>
        </div>
        <TimeMachineCharts snapshots={snapshots} initialCash={initialCash} />
      </div>

      <div className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="formTitle">当日收盘后仓池快照</div>
            <div className="mutedText">{latest?.date || '—'} · {positions.length} 只</div>
          </div>
        </div>
        <table>
          <thead><tr><th>名称</th><th>代码</th><th>持仓天数</th><th>数量</th><th>成本 / 现价</th><th>市值</th><th>持仓盈亏</th><th>今日盈亏</th><th>仓位</th></tr></thead>
          <tbody>
            {positions.map((position) => (
              <tr key={position.ts_code}>
                <td>
                  <span className="nameWithBadge">
                    <StockLink tsCode={position.ts_code} onOpenResearch={onOpenResearch}>{position.name || '—'}</StockLink>
                    <PositionTradeBadge trade={todayTradeByCode.get(position.ts_code)} />
                  </span>
                </td>
                <td className="mono">{position.ts_code}</td>
                <td>{position.hold_days} 天</td>
                <td>{position.shares.toLocaleString('zh-CN')}</td>
                <td><div className="pricePair"><span>{price(position.avg_cost)}</span><i>/</i><span>{price(position.price)}</span></div></td>
                <td>{money(position.market_value)}</td>
                <td className={position.unrealized_pnl >= 0 ? 'positive' : 'negative'}>{money(position.unrealized_pnl)} / {percent(position.unrealized_pct)}</td>
                <td className={position.today_pnl >= 0 ? 'positive' : 'negative'}>{money(position.today_pnl)} / {percent(position.today_pct)}</td>
                <td><div className="weightCell"><i style={{ width: `${Math.max(2, position.weight * 100)}%` }} /><span>{percent(position.weight)}</span></div></td>
              </tr>
            ))}
            {positions.length === 0 && <tr><td colSpan={9} className="emptyCell">暂无持仓快照</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="detailTwoCol">
        <div className="detailCard">
          <div className="tableHeader">
            <div className="formTitle">{isRunning ? '当日成交流水' : `成交流水 (${trades.length} 笔)`}</div>
          </div>
          <table>
            <thead><tr><th>日期</th><th>代码</th><th>名称</th><th>数量</th><th>价格</th><th>金额</th><th>持仓</th><th>该笔盈亏</th></tr></thead>
            <tbody>
              {visibleTradeRows.map((trade, idx) => (
                <tr key={`${trade.date}-${trade.ts_code}-${idx}`}>
                  <td>{trade.date}</td>
                  <td className="mono">{trade.ts_code}</td>
                  <td>
                    <span className="nameWithBadge">
                      <StockLink tsCode={trade.ts_code} onOpenResearch={onOpenResearch}>{trade.name || '—'}</StockLink>
                      <TradeBadge trade={trade} />
                    </span>
                  </td>
                  <td>{trade.shares.toLocaleString('zh-CN')}</td>
                  <td>{price(trade.price)}</td>
                  <td>{money(trade.amount)}</td>
                  <td>{trade.hold_days} 天</td>
                  <td className={trade.realized_pnl >= 0 ? 'positive' : 'negative'}>{trade.realized_pnl ? money(trade.realized_pnl) : '—'}</td>
                </tr>
              ))}
              {tradeRows.length === 0 && <tr><td colSpan={8} className="emptyCell">{isRunning ? '当日无成交（HOLD）' : '暂无成交流水'}</td></tr>}
            </tbody>
          </table>
          <Pager page={tradePage} pageCount={tradePageCount} onPageChange={setTradePage} />
        </div>
        <div className="detailCard">
          <div className="tableHeader">
            <div className="formTitle">每日快照</div>
          </div>
          <table>
            <thead><tr><th>日期</th><th>权益</th><th>现金</th><th>市值</th><th>收益</th></tr></thead>
            <tbody>
              {visibleSnapshotRows.map((snap) => (
                <tr key={snap.date}>
                  <td>{snap.date}</td>
                  <td>{money(snap.equity)}</td>
                  <td>{money(snap.cash)}</td>
                  <td>{money(snap.market_value)}</td>
                  <td className={snap.cum_return >= 0 ? 'positive' : 'negative'}>{percent(snap.cum_return)}</td>
                </tr>
              ))}
              {snapshots.length === 0 && <tr><td colSpan={5} className="emptyCell">暂无快照数据</td></tr>}
            </tbody>
          </table>
          <Pager page={snapshotPage} pageCount={snapshotPageCount} onPageChange={setSnapshotPage} />
        </div>
      </div>
    </div>
  )
}

function StrategyEvaluationDetail({ task, childTasks, onBack, onRefresh, onStart, onCancel }: {
  task: TaskDTO
  childTasks: TaskDTO[]
  onBack: () => void
  onRefresh: () => void
  onStart: () => void
  onCancel: () => void
}) {
  const [evidence, setEvidence] = useState<ValidationEvidence>({ reviews: [], reports: [], snapshots: [] })

  useEffect(() => {
    if (task.status !== 'running') return
    const timer = window.setInterval(onRefresh, 3000)
    return () => window.clearInterval(timer)
  }, [task.status, onRefresh])

  useEffect(() => {
    if (!task.external_run_id) {
      setEvidence({ reviews: [], reports: [], snapshots: [] })
      return
    }
    listValidationEvidence({ source_run_id: task.external_run_id, limit: 120 })
      .then(setEvidence)
      .catch(() => setEvidence({ reviews: [], reports: [], snapshots: [] }))
  }, [task.external_run_id, task.updated_at])

  const rows = Array.isArray(task.summary.rows) ? task.summary.rows as Array<Record<string, unknown>> : []
  const strategyRows = buildStrategyAdmissionRows(childTasks, rows)
  const successCount = numberOf(task.summary.success_count, strategyRows.filter((row) => row.evalStatus === 'ok').length)
  const emptyCount = numberOf(task.summary.empty_count, strategyRows.filter((row) => row.evalStatus === 'empty').length)
  const failedCount = Math.max(
    numberOf(task.summary.failed_count, 0),
    numberOf(task.summary.failed_task_count, 0),
    strategyRows.filter((row) => row.taskStatus === 'failed' || (row.evalStatus && row.evalStatus !== 'ok' && row.evalStatus !== 'empty')).length
  )
  const admitCount = numberOf(task.summary.admit_count, strategyRows.filter((row) => row.admission === '可启用').length)
  const limitedCount = numberOf(task.summary.limited_count, strategyRows.filter((row) => row.admission === '限制启用').length)
  const watchCount = numberOf(task.summary.watch_count, strategyRows.filter((row) => row.admission === '继续观察').length)
  const rejectCount = numberOf(task.summary.reject_count, strategyRows.filter((row) => row.admission === '暂不启用').length)
  const isRunning = task.status === 'running'
  const isRunnable = task.status !== 'running' && task.status !== 'success'
  const mode = strategyDetailMode(task)

  return (
    <div className="taskDetailPage strategyEvalDetail">
      <div className="detailHero">
        <div>
          <div className="sectionLabel">{mode.kicker}</div>
          <h2>{task.name}</h2>
          <p>{task.params.start_date as string} - {task.params.end_date as string} · {statusText(task.status)}</p>
        </div>
        <div className="detailHeroActions">
          <button className="secondaryButton quietButton" onClick={onBack}><ArrowLeft size={15} />返回</button>
          <button className="secondaryButton quietButton" onClick={onRefresh}><RefreshCw size={15} />刷新</button>
          {isRunnable && <button className="secondaryButton startButton" onClick={onStart}><Play size={15} />启动</button>}
          {isRunning && <button className="secondaryButton dangerButton" onClick={onCancel}><Square size={15} />取消</button>}
        </div>
      </div>

      {task.error_message && <div className="errorBox">{task.error_message}</div>}

      <div className="metricGrid">
        <Metric label={mode.countLabel} value={`${numberOf(task.summary.planned_count, numberOf(task.summary.strategy_count, strategyRows.length))}`} />
        <Metric label="成功" value={`${successCount}`} />
        <Metric label="空仓" value={`${emptyCount}`} />
        <Metric label="失败" value={`${failedCount}`} tone={failedCount > 0 ? 'negative' : ''} />
        <Metric label={mode.passLabel} value={`${admitCount}`} tone={admitCount > 0 ? 'positive' : ''} />
        <Metric label={mode.limitedLabel} value={`${limitedCount}`} />
        <Metric label={mode.watchLabel} value={`${watchCount}`} />
        <Metric label={mode.rejectLabel} value={`${rejectCount}`} tone={rejectCount > 0 ? 'negative' : ''} />
        <Metric label="结果目录" value={resultPathText(task)} hint={task.result_path} className="pathMetric" />
      </div>

      <ValidationEvidencePanel evidence={evidence} title={mode.evidenceTitle} emptyText={mode.evidenceEmpty} />

      <div className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="formTitle">{mode.tableTitle}</div>
            <p className="recommendationMeta">{mode.tableHint}</p>
          </div>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>序号</th>
                <th>{mode.rowLabel}</th>
                <th>建议</th>
                <th>准入分</th>
                <th>任务</th>
                <th>进度</th>
                <th>评估</th>
                <th>启用</th>
                <th>收益分</th>
                <th>风调分</th>
                <th>回撤分</th>
                <th>成本分</th>
                <th>容量分</th>
                <th>稳定分</th>
                <th>独立分</th>
                <th>总收益</th>
                <th>年化</th>
                <th>最大回撤</th>
                <th>夏普</th>
                <th>Calmar</th>
                <th>换手</th>
                <th>持仓</th>
                <th>平均市值</th>
                <th>平均成交额</th>
                <th>月胜率</th>
                <th>最差月</th>
                <th>重合度</th>
                <th>相关性</th>
                <th>尝试</th>
                <th>错误</th>
              </tr>
            </thead>
            <tbody>
              {strategyRows.map((row) => (
                <tr key={row.key}>
                  <td>{row.sequence}/{row.total}</td>
                  <td>{row.label}</td>
                  <td>
                    <span className={`admissionBadge ${admissionClass(row.admission)}`} title={row.reason}>
                      {row.admission || '—'}
                    </span>
                  </td>
                  <td>{scoreText(row.admission_score)}</td>
                  <td><span className={`badge ${row.taskStatus}`}>{row.taskStatus}</span></td>
                  <td>{Math.round(row.progress * 100)}%</td>
                  <td><span className={`badge ${row.evalStatus || 'created'}`}>{row.evalStatus || '—'}</span></td>
                  <td>{row.enabled ? '是' : '否'}</td>
                  <td>{scoreText(row.return_score)}</td>
                  <td>{scoreText(row.risk_adjusted_score)}</td>
                  <td>{scoreText(row.drawdown_score)}</td>
                  <td>{scoreText(row.cost_score)}</td>
                  <td>{scoreText(row.capacity_score)}</td>
                  <td>{scoreText(row.stability_score)}</td>
                  <td>{scoreText(row.independence_score)}</td>
                  <td className={toneOf(numberOf(row.total_return, 0))}>{percent(numberOf(row.total_return, 0), true)}</td>
                  <td className={toneOf(numberOf(row.annual_return, 0))}>{percent(numberOf(row.annual_return, 0), true)}</td>
                  <td className="negative">{percent(numberOf(row.max_drawdown, 0))}</td>
                  <td>{numberOf(row.sharpe, 0).toFixed(2)}</td>
                  <td>{numberOf(row.calmar, 0).toFixed(2)}</td>
                  <td>{percent(numberOf(row.avg_turnover, 0))}</td>
                  <td>{numberOf(row.avg_holdings, 0).toFixed(1)}</td>
                  <td>{money(numberOf(row.avg_total_mv, 0) / 100000000, 1)}亿</td>
                  <td>{money(numberOf(row.avg_amount, 0) / 100000000, 1)}亿</td>
                  <td>{row.monthly_win_rate == null ? '—' : percent(numberOf(row.monthly_win_rate, 0))}</td>
                  <td>{row.worst_month_return == null ? '—' : percent(numberOf(row.worst_month_return, 0), true)}</td>
                  <td>{row.overlap_with_baseline == null ? '—' : percent(numberOf(row.overlap_with_baseline, 0))}</td>
                  <td>{row.corr_with_baseline == null ? '—' : numberOf(row.corr_with_baseline, 0).toFixed(2)}</td>
                  <td>{row.attempt}/{row.maxAttempts}</td>
                  <td>{row.error || '—'}</td>
                </tr>
              ))}
              {!isRunning && strategyRows.length === 0 && <tr><td colSpan={30} className="emptyCell">{mode.emptyText}</td></tr>}
              {isRunning && strategyRows.length === 0 && <tr><td colSpan={30} className="emptyCell">评估运行中...</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function PortfolioOptimizationDetail({ task, childTasks, onBack, onRefresh, onStart, onCancel, onAnalyze, aiAnalyzing, onCreateNext, nextEvalCreating, onApply, onReview }: {
  task: TaskDTO
  childTasks: TaskDTO[]
  onBack: () => void
  onRefresh: () => void
  onStart: () => void
  onCancel: () => void
  onAnalyze: () => void
  aiAnalyzing: boolean
  onCreateNext: () => void
  nextEvalCreating: boolean
  onApply: (row: Record<string, unknown>) => void
  onReview: (row: Record<string, unknown>) => void
}) {
  const [evidence, setEvidence] = useState<ValidationEvidence>({ reviews: [], reports: [], snapshots: [] })

  useEffect(() => {
    if (task.status !== 'running') return
    const timer = window.setInterval(onRefresh, 3000)
    return () => window.clearInterval(timer)
  }, [task.status, onRefresh])

  useEffect(() => {
    if (!task.external_run_id) {
      setEvidence({ reviews: [], reports: [], snapshots: [] })
      return
    }
    listValidationEvidence({ subject_type: 'portfolio_optimization', subject_id: task.external_run_id, limit: 80 })
      .then(setEvidence)
      .catch(() => setEvidence({ reviews: [], reports: [], snapshots: [] }))
  }, [task.external_run_id, task.updated_at])

  const rows = Array.isArray(task.summary.rows) ? task.summary.rows as Array<Record<string, unknown>> : []
  const isRunning = task.status === 'running'
  const isRunnable = task.status !== 'running' && task.status !== 'success'
  const [schemeSort, setSchemeSort] = useState('sequence')
  const canAnalyze = task.status === 'success' && rows.length > 0
  const aiAnalysis = String(task.summary.ai_analysis || '')
  const aiAnalysisError = String(task.summary.ai_analysis_error || '')
  const aiRecommendation = asRecord(task.summary.ai_recommendation) || {}
  const nextEvalConfig = asRecord(task.summary.ai_next_eval_config) || asRecord(aiRecommendation.next_eval_config)
  const nextParams = asRecord(nextEvalConfig?.params) || {}
  const hasNextEvalConfig = Boolean(nextEvalConfig && Object.keys(nextParams).length > 0)
  const schemeRows = buildSchemeRows(childTasks, rows, schemeSort)

  return (
    <div className="taskDetailPage strategyEvalDetail">
      <div className="detailHero">
        <div>
          <div className="sectionLabel">TRADING SCHEME EVALUATION</div>
          <h2>{task.name}</h2>
          <p>{task.params.start_date as string} - {task.params.end_date as string} · {String(task.summary.objective || task.params.objective || '平衡')} · {statusText(task.status)}</p>
        </div>
        <div className="detailHeroActions">
          <button className="secondaryButton quietButton" onClick={onBack}><ArrowLeft size={15} />返回</button>
          <button className="secondaryButton quietButton" onClick={onRefresh}><RefreshCw size={15} />刷新</button>
          <button className="secondaryButton startButton" onClick={onAnalyze} disabled={aiAnalyzing || !canAnalyze}>
            <Sparkles size={15} />{aiAnalyzing ? '优化中' : '量化优化'}
          </button>
          {isRunnable && <button className="secondaryButton startButton" onClick={onStart}><Play size={15} />启动</button>}
          {isRunning && <button className="secondaryButton dangerButton" onClick={onCancel}><Square size={15} />取消</button>}
        </div>
      </div>

      {task.error_message && <div className="errorBox">{task.error_message}</div>}
      {aiAnalysisError && <div className="errorBox">{aiAnalysisError}</div>}

      <div className="metricGrid">
        <Metric label="候选方案" value={`${numberOf(task.summary.candidate_count, childTasks.length || rows.length)}`} />
        <Metric label="已完成" value={`${numberOf(task.summary.completed_count, childTasks.filter((item) => item.status === 'success').length)}`} tone="positive" />
        <Metric label="失败/中断" value={`${numberOf(task.summary.failed_count, childTasks.filter((item) => ['failed', 'cancelled', 'interrupted'].includes(item.status)).length)}`} tone="negative" />
        <Metric label="入场策略池" value={`${numberOf(task.summary.strategy_count, 0)}`} />
        <Metric label="最佳方案" value={String(task.summary.best_name || '—')} />
        <Metric label="最佳评分" value={numberOf(task.summary.best_score, 0).toFixed(3)} tone="positive" />
        <Metric label="最佳年化" value={percent(numberOf(task.summary.best_annual_return, 0), true)} tone={toneOf(numberOf(task.summary.best_annual_return, 0))} />
        <Metric label="最佳回撤" value={percent(numberOf(task.summary.best_max_drawdown, 0))} tone="negative" />
        <Metric label="结果目录" value={resultPathText(task)} hint={task.result_path} className="pathMetric" />
      </div>

      <ValidationEvidencePanel evidence={evidence} title="方案可信度证据" emptyText="暂无方案分析报告，任务成功后点击量化优化生成" />

      <div className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="formTitle">量化实验迭代</div>
            <p className="recommendationMeta">根据回测指标、风险惩罚、策略贡献和参数邻域生成下一轮可回测配置；LLM 只作为解释辅助，不直接优化参数</p>
          </div>
          <button className="secondaryButton startButton" onClick={onCreateNext} disabled={!hasNextEvalConfig || nextEvalCreating}>
            {nextEvalCreating ? '创建中' : '创建下一轮评估'}
          </button>
        </div>
        {aiAnalysis ? (
          <div className="aiLoopPanel">
            <pre className="aiAnalysisBox">{aiAnalysis}</pre>
            <div className="aiLoopGrid">
              <AISuggestionList title="诊断" items={asStringArray(aiRecommendation.diagnosis)} />
              <AISuggestionList title="保留" items={asStringArray(aiRecommendation.keep)} />
              <AISuggestionList title="调整" items={asStringArray(aiRecommendation.change)} />
              <AISuggestionList title="剔除/降权" items={asStringArray(aiRecommendation.remove)} />
              <AISuggestionList title="验证计划" items={asStringArray(aiRecommendation.validation_plan)} wide />
              <div className="aiNextEvalCard">
                <div className="miniCardTitle">下一轮评估配置</div>
                {hasNextEvalConfig ? (
                  <div className="configDiffGrid">
                    <div><span>名称</span><b>{String(nextEvalConfig?.name || `${task.name} - 下一轮`)}</b></div>
                    <div><span>区间</span><b>{String(nextParams.start_date || task.params.start_date)} - {String(nextParams.end_date || task.params.end_date)}</b></div>
                    <div><span>目标</span><b>{String(nextParams.objective || task.params.objective || '平衡')}</b></div>
                    <div><span>候选/Top</span><b>全量 / {String(nextParams.top_n || task.params.top_n || 40)}</b></div>
                    <div><span>策略</span><b>{formatStrategies(nextParams.strategies || task.params.strategies)}</b></div>
                    <div><span>滑点</span><b>{percent(numberOf(nextParams.slippage, numberOf(task.params.slippage, 0.003)))}</b></div>
                  </div>
                ) : (
                  <div className="emptyCell compactEmpty">优化器返回了分析，但没有可创建的下一轮配置</div>
                )}
              </div>
            </div>
          </div>
        ) : <div className="emptyCell">暂无量化优化分析，时光机成功并产生结果后点击量化优化</div>}
      </div>

      <div className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="formTitle">方案列表</div>
            <p className="recommendationMeta">每一行对应一个交易方案，Go 负责编排，Python 实时写回进度和指标；完成后可按评分、收益、回撤等排序</p>
          </div>
          <select className="selectInput schemeSortSelect" value={schemeSort} onChange={(event) => setSchemeSort(event.target.value)}>
            <option value="sequence">按执行顺序</option>
            <option value="status">按运行状态</option>
            <option value="score">按评分</option>
            <option value="annual_return">按年化</option>
            <option value="total_return">按累计收益</option>
            <option value="excess_annual_return">按超额年化</option>
            <option value="max_drawdown">按回撤</option>
            <option value="sharpe">按夏普</option>
          </select>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>序号</th>
                <th>排名</th>
                <th>方案</th>
                <th>状态</th>
                <th>进度</th>
                <th>评分</th>
                <th>策略权重</th>
                <th>出场架构</th>
                <th>调仓</th>
                <th>累计收益</th>
                <th>年化</th>
                <th>超额年化</th>
                <th>胜率</th>
                <th>回撤</th>
                <th>夏普</th>
                <th>Calmar</th>
                <th>年化波动</th>
                <th>平均持仓</th>
                <th>卖出分布</th>
                <th>换手</th>
                <th>持仓</th>
                <th>平均市值</th>
                <th>原因</th>
                <th>尝试</th>
                <th>错误</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {schemeRows.map((item) => (
                <tr key={item.key}>
                  <td>{item.sequence}/{item.total}</td>
                  <td>{item.rank > 0 ? item.rank : '—'}</td>
                  <td>{item.name}</td>
                  <td><span className={`badge ${item.status}`}>{item.status}</span></td>
                  <td>{Math.round(item.progress * 100)}%</td>
                  <td>{Number.isFinite(item.score) ? item.score.toFixed(3) : '—'}</td>
                  <td className="mono">{formatWeights(item.weights)}</td>
                  <td>{item.exitLabel}</td>
                  <td>{rebalanceLabel(item.rebalanceFreq)}</td>
                  <td className={toneOf(item.totalReturn)}>{Number.isFinite(item.totalReturn) ? percent(item.totalReturn, true) : '—'}</td>
                  <td className={toneOf(item.annualReturn)}>{Number.isFinite(item.annualReturn) ? percent(item.annualReturn, true) : '—'}</td>
                  <td className={toneOf(item.excessAnnualReturn)}>{Number.isFinite(item.excessAnnualReturn) ? percent(item.excessAnnualReturn, true) : '—'}</td>
                  <td>{Number.isFinite(item.winRate) ? percent(item.winRate) : '—'}</td>
                  <td className="negative">{Number.isFinite(item.maxDrawdown) ? percent(item.maxDrawdown) : '—'}</td>
                  <td>{Number.isFinite(item.sharpe) ? item.sharpe.toFixed(2) : '—'}</td>
                  <td>{Number.isFinite(item.calmar) ? item.calmar.toFixed(2) : '—'}</td>
                  <td>{Number.isFinite(item.annualVolatility) ? percent(item.annualVolatility) : '—'}</td>
                  <td>{Number.isFinite(item.avgHoldingDays) ? `${item.avgHoldingDays.toFixed(1)} 天` : '—'}</td>
                  <td>{formatExitDistribution(item.exitDistribution)}</td>
                  <td>{Number.isFinite(item.avgTurnover) ? percent(item.avgTurnover) : '—'}</td>
                  <td>{Number.isFinite(item.avgHoldings) ? item.avgHoldings.toFixed(1) : '—'}</td>
                  <td>{Number.isFinite(item.avgTotalMV) ? `${money(item.avgTotalMV / 100000000, 1)}亿` : '—'}</td>
                  <td>{item.reason}</td>
                  <td>{item.attempt}/{item.maxAttempts}</td>
                  <td>{item.error || '—'}</td>
                  <td>
                    {item.result ? (
                      <div className="taskActions compactActions">
                        <button className="secondaryButton quietButton" onClick={() => onApply(item.result as Record<string, unknown>)}>应用入场</button>
                        <button className="secondaryButton startButton" onClick={() => onReview(item.result as Record<string, unknown>)}>复核</button>
                      </div>
                    ) : '—'}
                  </td>
                </tr>
              ))}
              {schemeRows.length === 0 && <tr><td colSpan={26} className="emptyCell">暂无方案，创建时光机后会初始化候选方案</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function Pager({ page, pageCount, onPageChange }: { page: number; pageCount: number; onPageChange: (page: number) => void }) {
  const current = Math.min(page, pageCount)
  return (
    <div className="miniPager">
      <button className="secondaryButton quietButton" disabled={current <= 1} onClick={() => onPageChange(current - 1)}>上一页</button>
      <span>{current} / {pageCount}</span>
      <button className="secondaryButton quietButton" disabled={current >= pageCount} onClick={() => onPageChange(current + 1)}>下一页</button>
    </div>
  )
}

function AISuggestionList({ title, items, wide = false }: { title: string; items: string[]; wide?: boolean }) {
  return (
    <div className={`aiSuggestionCard ${wide ? 'wide' : ''}`}>
      <div className="miniCardTitle">{title}</div>
      {items.length > 0 ? (
        <ul>
          {items.map((item, index) => <li key={`${title}-${index}`}>{item}</li>)}
        </ul>
      ) : <div className="mutedText">暂无</div>}
    </div>
  )
}

function ValidationEvidencePanel({ evidence, title, emptyText }: { evidence: ValidationEvidence; title: string; emptyText: string }) {
  const latestSnapshot = evidence.snapshots[0]
  const latestReport = evidence.reports[0]
  const hasEvidence = evidence.reviews.length > 0 || evidence.reports.length > 0 || evidence.snapshots.length > 0
  return (
    <div className="detailCard evidencePanel">
      <div className="tableHeader">
        <div>
          <div className="formTitle">{title}</div>
          <p className="recommendationMeta">复核记录、研究报告和数据快照都来自 SQLite，用来判断结论是否能进入模拟盘或下一轮评估</p>
        </div>
      </div>
      {!hasEvidence ? <div className="emptyCell compactEmpty">{emptyText}</div> : null}
      {hasEvidence ? (
        <div className="evidenceGrid">
          <div className="evidenceBlock">
            <div className="miniCardTitle">复核记录</div>
            {evidence.reviews.length ? evidence.reviews.slice(0, 6).map((review) => (
              <div className="evidenceRow" key={review.id}>
                <div>
                  <b>{review.strategy || review.subject_id}</b>
                  <span>{review.recommendation || review.status}</span>
                </div>
                <strong className={review.status === 'promotable' ? 'positive' : review.status === 'rejected' ? 'negative' : ''}>{statusText(review.status)} · {scoreText(review.score)}</strong>
              </div>
            )) : <div className="mutedText">暂无复核</div>}
          </div>
          <div className="evidenceBlock">
            <div className="miniCardTitle">研究报告</div>
            {latestReport ? (
              <div className="evidenceReport">
                <b>{latestReport.title || latestReport.report_type}</b>
                <span>{latestReport.model || 'quant'} · {latestReport.created_at}</span>
                <p>{truncateText(latestReport.content_md || latestReport.report_type, 180)}</p>
              </div>
            ) : <div className="mutedText">暂无报告</div>}
          </div>
          <div className="evidenceBlock">
            <div className="miniCardTitle">数据快照</div>
            {latestSnapshot ? (
              <div className="snapshotSummary">
                <span>{latestSnapshot.created_at}</span>
                {snapshotDataTypes(latestSnapshot.snapshot).slice(0, 6).map((item) => (
                  <div key={item.name}>
                    <b>{item.name}</b>
                    <em>{item.files} 文件 · {item.rows.toLocaleString('zh-CN')} 行</em>
                  </div>
                ))}
              </div>
            ) : <div className="mutedText">暂无快照</div>}
          </div>
        </div>
      ) : null}
    </div>
  )
}

type StrategyAdmissionRow = Record<string, unknown> & {
  key: string
  label: string
  admission: string
  reason: string
  taskStatus: string
  evalStatus: string
  progress: number
  sequence: number
  total: number
  enabled?: unknown
  attempt: number
  maxAttempts: number
  error: string
}

function buildStrategyAdmissionRows(childTasks: TaskDTO[], resultRows: Array<Record<string, unknown>>): StrategyAdmissionRow[] {
  if (childTasks.length === 0) {
    return resultRows.map((row, index) => ({
      ...row,
      key: String(row.strategy || index),
      label: String(row.label || row.strategy || '—'),
      admission: String(row.admission || ''),
      reason: String(row.reason || ''),
      taskStatus: String(row.status || 'success'),
      evalStatus: String(row.status || ''),
      progress: 1,
      sequence: index + 1,
      total: resultRows.length,
      attempt: 1,
      maxAttempts: 1,
      error: String(row.error || '')
    }))
  }
  const resultByStrategy = new Map<string, Record<string, unknown>>()
  const resultByCompound = new Map<string, Record<string, unknown>>()
  for (const row of resultRows) {
    const strategy = String(row.strategy || '')
    if (strategy) resultByStrategy.set(strategy, row)
    const windowName = String(row.walk_window || row.window_name || '')
    const paramSet = String(row.param_set || '')
    if (strategy && windowName) resultByCompound.set(`${strategy}:${windowName}`, row)
    if (strategy && paramSet) resultByCompound.set(`${strategy}:${paramSet}`, row)
  }
  return childTasks.map((child) => {
    const strategy = String(child.params.strategy || String(child.subtask_key || '').split(':')[0] || '')
    const walkWindow = String(child.params.walk_window || '')
    const paramSet = String(child.params.param_set || '')
    const compoundKey = walkWindow ? `${strategy}:${walkWindow}` : paramSet ? `${strategy}:${paramSet}` : ''
    const fallbackResult = (compoundKey ? resultByCompound.get(compoundKey) : null) || resultByStrategy.get(strategy)
    const childSummaryHasEvalResult = child.summary && (
      child.summary.status != null ||
      child.summary.admission_score != null ||
      child.summary.score != null ||
      child.summary.admission != null
    )
    const result = childSummaryHasEvalResult ? child.summary : fallbackResult || child.summary || {}
    return {
      ...result,
      key: child.id,
      strategy,
      label: String(result.label || child.subtask_name || child.name || strategy || '—'),
      admission: String(result.admission || ''),
      reason: String(result.reason || child.error_message || ''),
      taskStatus: child.status,
      evalStatus: String(result.status || ''),
      progress: child.progress,
      sequence: child.sequence,
      total: child.total,
      enabled: result.enabled ?? child.params.enabled,
      attempt: child.attempt,
      maxAttempts: child.max_attempts || 1,
      error: child.error_message || String(result.error || '')
    }
  })
}

function buildSchemeRows(childTasks: TaskDTO[], resultRows: Array<Record<string, unknown>>, sortKey: string) {
  const resultByID = new Map<string, Record<string, unknown>>()
  for (const row of resultRows) {
    const id = String(row.candidate_id || '')
    if (id) resultByID.set(id, row)
  }
  const rows = childTasks.map((child) => {
    const candidateID = String(child.params.candidate_id || child.subtask_key || '')
    const result = resultByID.get(candidateID) || null
    const merged = { ...child.params, ...child.summary, ...(result || {}) } as Record<string, unknown>
    const exitArchitecture = asRecord(merged.exit_architecture) || asRecord(child.params.exit_architecture) || {}
    return {
      key: child.id,
      candidateID,
      result,
      sequence: child.sequence,
      total: child.total,
      rank: numberOf(merged.rank, 0),
      name: String(merged.name || child.subtask_name || child.name || '—'),
      status: child.status,
      progress: child.progress,
      score: numberOf(merged.score, NaN),
      weights: merged.weights,
      exitLabel: String(merged.exit_architecture_label || exitArchitecture.label || '—'),
      rebalanceFreq: numberOf(merged.rebalance_freq, numberOf(child.params.rebalance_freq, 5)),
      totalReturn: numberOf(merged.total_return, NaN),
      annualReturn: numberOf(merged.annual_return, NaN),
      excessAnnualReturn: numberOf(merged.excess_annual_return, NaN),
      winRate: numberOf(merged.win_rate, NaN),
      maxDrawdown: numberOf(merged.max_drawdown, NaN),
      sharpe: numberOf(merged.sharpe, NaN),
      calmar: numberOf(merged.calmar, NaN),
      annualVolatility: numberOf(merged.annual_volatility, NaN),
      avgHoldingDays: numberOf(merged.avg_holding_days, NaN),
      exitDistribution: merged.exit_reason_distribution,
      avgTurnover: numberOf(merged.avg_turnover, NaN),
      avgHoldings: numberOf(merged.avg_holdings, NaN),
      avgTotalMV: numberOf(merged.avg_total_mv, NaN),
      reason: String(merged.reason || ''),
      attempt: child.attempt,
      maxAttempts: child.max_attempts || 1,
      error: child.error_message
    }
  })
  const statusOrder = { running: 0, queued: 1, created: 2, failed: 3, interrupted: 4, cancelled: 5, success: 6 } as Record<string, number>
  const sorted = rows.slice()
  sorted.sort((left, right) => {
    if (sortKey === 'sequence') return left.sequence - right.sequence
    if (sortKey === 'status') {
      const statusDiff = (statusOrder[left.status] ?? 9) - (statusOrder[right.status] ?? 9)
      return statusDiff || left.sequence - right.sequence
    }
    const accessors = {
      score: (row: typeof left) => row.score,
      annual_return: (row: typeof left) => row.annualReturn,
      total_return: (row: typeof left) => row.totalReturn,
      excess_annual_return: (row: typeof left) => row.excessAnnualReturn,
      max_drawdown: (row: typeof left) => row.maxDrawdown,
      sharpe: (row: typeof left) => row.sharpe
    } as Record<string, (row: typeof left) => number>
    const accessor = accessors[sortKey] || accessors.score
    const leftValue = accessor(left)
    const rightValue = accessor(right)
    const leftRank = Number.isFinite(leftValue) ? leftValue : -Infinity
    const rightRank = Number.isFinite(rightValue) ? rightValue : -Infinity
    return rightRank - leftRank || left.sequence - right.sequence
  })
  return sorted
}

function TimeMachineCharts({ snapshots, initialCash }: { snapshots: TimeMachineDetail['snapshots']; initialCash: number }) {
  if (snapshots.length === 0) return <div className="emptyState">暂无净值数据</div>
  return (
    <div className="tmEchartStack">
      <EChartLine
        title="净值曲线"
        dates={snapshots.map((row) => row.date)}
        values={snapshots.map((row) => row.equity)}
        valueFormatter={(value) => money(value)}
        yFormatter={(value) => money(value)}
      />
      <EChartLine
        title="累计收益率"
        dates={snapshots.map((row) => row.date)}
        values={snapshots.map((row) => initialCash > 0 ? row.equity / initialCash - 1 : row.cum_return)}
        valueFormatter={(value) => percent(value, true)}
        yFormatter={(value) => `${(value * 100).toFixed(1)}%`}
        positiveNegative
      />
    </div>
  )
}

function EChartLine({ title, dates, values, valueFormatter, yFormatter, positiveNegative = false }: {
  title: string
  dates: string[]
  values: number[]
  valueFormatter: (value: number) => string
  yFormatter: (value: number) => string
  positiveNegative?: boolean
}) {
  const elRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!elRef.current) return
    const chart = echarts.init(elRef.current, 'dark')
    const latest = values[values.length - 1] || 0
    const lineColor = positiveNegative && latest < 0 ? '#26c281' : '#ffb000'
    const areaColor = positiveNegative && latest < 0 ? 'rgba(38, 194, 129, 0.16)' : 'rgba(255, 176, 0, 0.18)'

    chart.setOption({
      backgroundColor: 'transparent',
      animationDuration: 420,
      color: [lineColor],
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(10, 15, 24, 0.96)',
        borderColor: 'rgba(255, 176, 0, 0.35)',
        textStyle: { color: '#eef2ff', fontFamily: 'JetBrains Mono, Menlo, monospace' },
        axisPointer: { type: 'line', lineStyle: { color: 'rgba(255, 176, 0, 0.5)', width: 1 } },
        valueFormatter
      },
      grid: { left: 58, right: 24, top: 44, bottom: 42 },
      title: {
        text: title,
        left: 8,
        top: 4,
        textStyle: { color: '#eef2ff', fontSize: 13, fontWeight: 800 }
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: dates,
        axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.16)' } },
        axisTick: { show: false },
        axisLabel: { color: '#8f9ab3', hideOverlap: true }
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { color: '#8f9ab3', formatter: yFormatter },
        splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.07)' } }
      },
      dataZoom: [
        { type: 'inside', throttle: 60 },
        {
          type: 'slider',
          height: 18,
          bottom: 8,
          borderColor: 'rgba(255, 255, 255, 0.08)',
          fillerColor: 'rgba(255, 176, 0, 0.16)',
          handleStyle: { color: '#ffb000' },
          textStyle: { color: '#8f9ab3' },
          brushSelect: false
        }
      ],
      series: [{
        name: title,
        type: 'line',
        data: values,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 3, color: lineColor },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: areaColor },
            { offset: 1, color: 'rgba(255, 176, 0, 0)' }
          ])
        },
        emphasis: { focus: 'series' }
      }]
    })

    const resize = () => chart.resize()
    const observer = new ResizeObserver(resize)
    observer.observe(elRef.current)
    return () => {
      observer.disconnect()
      chart.dispose()
    }
  }, [dates, positiveNegative, title, valueFormatter, values, yFormatter])

  return <div className="tmEchartPanel"><div ref={elRef} className="tmEchart" /></div>
}

function Metric({ label, value, tone = '', hint = '', className = '' }: { label: string; value: string; tone?: string; hint?: string; className?: string }) {
  return <div className={`metricCard ${className}`.trim()}><span>{label}</span><strong className={tone}>{value}</strong>{hint && <em title={hint}>{hint}</em>}</div>
}

function StockLink({ tsCode, children, onOpenResearch }: { tsCode: string; children: string; onOpenResearch?: (tsCode: string) => void }) {
  return (
    <button className="stockLink" onClick={() => onOpenResearch?.(tsCode)} title="查看个股研究">
      {children}
    </button>
  )
}

function AccountRow({ label, value, tone = '', strong = false }: { label: string; value: string; tone?: string; strong?: boolean }) {
  return <div className={strong ? 'accountRow total' : 'accountRow'}><span>{label}</span><b className={tone}>{value}</b></div>
}

function PositionTradeBadge({ trade }: { trade?: TimeMachineDetail['trades'][number] }) {
  if (!trade) return null
  return trade.is_new || trade.action === 'BUY' ? <span className="trdBadge new">新</span> : <span className="trdBadge add">加</span>
}

function TradeBadge({ trade }: { trade: TimeMachineDetail['trades'][number] }) {
  if (trade.exit_reason === 'feb_clear') return <span className="trdBadge febclear">清</span>
  if (trade.exit_reason === 'stop_loss') return <span className="trdBadge stoploss">损</span>
  if (trade.exit_reason === 'trailing_stop') return <span className="trdBadge takeprofit">盈</span>
  if (trade.is_new) return <span className="trdBadge new">新</span>
  if (trade.action === 'SELL' || trade.action === 'TRIM') return <span className="trdBadge close">平</span>
  if (trade.action === 'BUY' || trade.action === 'ADD') return <span className="trdBadge add">加</span>
  return null
}

function numberOf(value: unknown, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function money(value: number, fractionDigits = 0) {
  return `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits })}`
}

function signedMoney(value: number, fractionDigits = 0) {
  const sign = value >= 0 ? '+' : ''
  return `¥${sign}${value.toLocaleString('zh-CN', { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits })}`
}

function price(value: number) {
  return value.toFixed(2)
}

function percent(value: number, signed = false) {
  const pct = value * 100
  const sign = signed && pct >= 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
}

function toneOf(value: number) {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return ''
}

function admissionClass(value: string) {
  if (value === '可启用') return 'admit'
  if (value === '限制启用') return 'limited'
  if (value === '暂不启用') return 'reject'
  if (value === '继续观察') return 'watch'
  return ''
}

function scoreText(value: unknown) {
  const score = numberOf(value, NaN)
  return Number.isFinite(score) ? score.toFixed(1) : '—'
}

function formatWeights(value: unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return '—'
  return Object.entries(value as Record<string, unknown>)
    .map(([name, weight]) => `${name}:${percent(numberOf(weight, 0))}`)
    .join(' · ')
}

function formatStrategies(value: unknown) {
  if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean).join(' · ') || '—'
  if (typeof value === 'string' && value.trim()) return value
  return '—'
}

function formatExitDistribution(value: unknown) {
  const record = asRecord(value)
  if (!record) return '—'
  const text = Object.entries(record)
    .filter(([, count]) => numberOf(count, 0) > 0)
    .map(([reason, count]) => `${exitReasonLabel(reason)} ${numberOf(count, 0)}`)
    .join(' · ')
  return text || '—'
}

function exitReasonLabel(reason: string) {
  return ({
    signal_rebalance: '调仓',
    stop_loss: '止损',
    trailing_stop: '移动止盈',
    stop_loss_trailing: '止损/止盈',
    tight_risk: '稳健风控',
    wide_risk: '进攻风控'
  } as Record<string, string>)[reason] || reason
}

function rebalanceLabel(freq: number) {
  if (freq === 1) return '日调仓'
  if (freq === 20) return '月调仓'
  return '周调仓'
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function asStringArray(value: unknown) {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item).trim()).filter(Boolean)
}

function truncateText(value: string, maxLength: number) {
  const text = value.replace(/\s+/g, ' ').trim()
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text
}

function snapshotDataTypes(snapshot: Record<string, unknown>) {
  const files = asRecord(snapshot.market_data_files) || {}
  return Object.entries(files).map(([name, raw]) => {
    const item = asRecord(raw) || {}
    return {
      name,
      files: numberOf(item.files, 0),
      rows: numberOf(item.rows, 0)
    }
  }).filter((item) => item.files > 0 || item.rows > 0)
}

function taskProgressLabel(task: TaskDTO) {
  if (task.parent_id) return `${task.sequence}/${task.total} · ${Math.round(task.progress * 100)}%`
  if (task.task_type === 'portfolio_optimization' && task.total) {
    const done = numberOf(task.summary.completed_count, 0)
    const failed = numberOf(task.summary.failed_count, 0)
    return `${done}/${task.total}${failed ? ` · 异常 ${failed}` : ''}`
  }
  return `${Math.round(task.progress * 100)}%`
}

function taskMetric(task: TaskDTO, key: string) {
  if (task.task_type === 'portfolio_optimization' && !task.parent_id) {
    if (key === 'annual_return') return numberOf(task.summary.best_annual_return, NaN)
    if (key === 'max_drawdown') return numberOf(task.summary.best_max_drawdown, NaN)
    const rows = Array.isArray(task.summary.rows) ? task.summary.rows as Array<Record<string, unknown>> : []
    const top = rows[0] || {}
    return numberOf(top[key], NaN)
  }
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
  if (task.task_type === 'portfolio_optimization') return task.parent_id ? '方案子任务' : '时光机'
  if (task.task_type === 'walk_forward_evaluation') return task.parent_id ? '窗口子任务' : 'Walk-forward'
  if (task.task_type === 'parameter_experiment') return task.parent_id ? '参数子任务' : '参数实验'
  if (task.task_type === 'strategy_evaluation') return '策略准入'
  if (task.task_type === 'evaluation_time_machine') return '时光机'
  return task.task_type
}

function strategyDetailMode(task: TaskDTO) {
  if (task.task_type === 'walk_forward_evaluation') {
    return {
      kicker: 'WALK-FORWARD',
      countLabel: '窗口任务',
      passLabel: '通过',
      limitedLabel: '边界',
      watchLabel: '观察',
      rejectLabel: '失败',
      evidenceTitle: '样本外稳定性证据',
      evidenceEmpty: '暂无 Walk-forward 复核证据，运行完成后会写入治理面板',
      tableTitle: '窗口评估表',
      tableHint: '按策略在多个时间窗口的收益、回撤、夏普、换手和容量表现跟踪样本外稳定性',
      rowLabel: '策略 / 窗口',
      emptyText: '暂无窗口子任务，创建 Walk-forward 后会初始化策略 × 时间窗口'
    }
  }
  if (task.task_type === 'parameter_experiment') {
    return {
      kicker: 'PARAMETER EXPERIMENT',
      countLabel: '参数任务',
      passLabel: '稳定',
      limitedLabel: '研究',
      watchLabel: '观察',
      rejectLabel: '不稳定',
      evidenceTitle: '参数稳健性证据',
      evidenceEmpty: '暂无参数实验复核证据，运行完成后会写入治理面板',
      tableTitle: '参数实验表',
      tableHint: '按策略 × 参数组回测，观察硬阈值附近是否存在稳定区间，而不是只保留单点参数',
      rowLabel: '策略 / 参数组',
      emptyText: '暂无参数子任务，创建参数实验后会初始化策略 × 参数网格'
    }
  }
  return {
    kicker: 'STRATEGY ADMISSION',
    countLabel: '策略数',
    passLabel: '可启用',
    limitedLabel: '限制启用',
    watchLabel: '观察',
    rejectLabel: '暂不启用',
    evidenceTitle: '策略可信度证据',
    evidenceEmpty: '暂无策略版本复核记录，完成策略准入后可在设置页复核版本',
    tableTitle: '策略准入表',
    tableHint: '按收益质量、风险调整、回撤控制、换手成本、容量、稳定性与组合独立性综合评分',
    rowLabel: '策略',
    emptyText: '暂无策略子任务，创建策略准入后会初始化候选策略'
  }
}

function statusText(status: string) {
  return ({ created: '待启动', queued: '排队中', running: '评估中', success: '已完成', failed: '失败', cancelled: '已取消', interrupted: '异常中断', promotable: '可模拟', research: '研究中', rejected: '拒绝', paper: '模拟中', active: '生效' } as Record<string, string>)[status] || status
}

function resultPathText(task: TaskDTO) {
  if (!task.result_path) return '—'
  if (task.status === 'success') return '已生成'
  if (task.status === 'running' || task.status === 'queued') return '生成中'
  if (task.status === 'failed' || task.status === 'cancelled' || task.status === 'interrupted') return '未完成'
  return '待生成'
}

function stageText(stage: string) {
  return ({ init: '初始化', signal: '生成信号', trade: '撮合成交', snapshot: '落快照', day_done: '调仓日完成', done: '完成' } as Record<string, string>)[stage] || stage || '运行中'
}

function etaText(seconds: number) {
  if (seconds > 60) return `剩余约 ${(seconds / 60).toFixed(1)} 分钟`
  if (seconds > 0) return `剩余约 ${Math.round(seconds)} 秒`
  return '估算中'
}

function progressText(taskProgress: number, progress: { cur_day: number; total_days: number; pct: number }) {
  const pct = progress.pct || taskProgress * 100
  if (progress.total_days) return `第 ${progress.cur_day}/${progress.total_days} 天 · ${pct.toFixed(1)}%`
  return `${Math.round(taskProgress * 100)}%`
}

function progressOf(summary: Record<string, unknown>) {
  const raw = summary.progress && typeof summary.progress === 'object' ? summary.progress as Record<string, unknown> : {}
  const pctRaw = numberOf(raw.pct, 0)
  return {
    cur_day: numberOf(raw.cur_day, 0),
    total_days: numberOf(raw.total_days, 0),
    pct: pctRaw > 1 ? pctRaw : pctRaw * 100,
    stage: String(raw.stage || ''),
    eta_sec: numberOf(raw.eta_sec, 0),
    date: String(raw.date || '')
  }
}

function addYears(date: Date, years: number) {
  const copy = new Date(date)
  copy.setFullYear(copy.getFullYear() + years)
  return copy
}

function formatYYYYMMDD(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}${month}${day}`
}
