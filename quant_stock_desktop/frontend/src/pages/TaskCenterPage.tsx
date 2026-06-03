import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, Play, RefreshCw, Square, Trash2 } from 'lucide-react'
import { DataGrid, type Column } from 'react-data-grid'
import * as echarts from 'echarts/core'
import { DataZoomComponent, GridComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import { LineChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { applyPortfolioCandidate, cancelTask, createTask, deleteTask, getSettings, getTimeMachineDetail, listTasks, refreshTaskStatus, startTask, type Settings, type TaskDTO, type TimeMachineDetail } from '../services/app'
import { Field } from '../components/Field'
import { formatDate } from '../components/format'

const strategyOrder = ['forecast_revision', 'dividend_low_vol', 'trend_quality', 'garp_quality', 'moneyflow_pullback', 'small_cap_quality', 'reversal', 'insider_buy', 'lhb_follow', 'industry_rotation', 'beijing_se']
const evaluationTaskTypes = new Set(['evaluation_time_machine', 'strategy_evaluation', 'portfolio_optimization'])

echarts.use([CanvasRenderer, DataZoomComponent, GridComponent, LineChart, TitleComponent, TooltipComponent])

export function TaskCenterPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [tasks, setTasks] = useState<TaskDTO[]>([])
  const [selectedTask, setSelectedTask] = useState<TaskDTO | null>(null)
  const [detail, setDetail] = useState<TimeMachineDetail | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [evalMode, setEvalMode] = useState<'time_machine' | 'strategy_evaluation' | 'portfolio_optimization'>('time_machine')
  const [name, setName] = useState('时光机评估')
  const [startDate, setStartDate] = useState(() => formatYYYYMMDD(addYears(new Date(), -1)))
  const [endDate, setEndDate] = useState(() => formatYYYYMMDD(new Date()))
  const [initialCash, setInitialCash] = useState(500000)
  const [rebalanceFreq, setRebalanceFreq] = useState(5)
  const [exitEnabled, setExitEnabled] = useState(false)
  const [stopLossPct, setStopLossPct] = useState(-12)
  const [trailingStopPct, setTrailingStopPct] = useState(-8)
  const [trailingExec, setTrailingExec] = useState('next_open')
  const [slippageBp, setSlippageBp] = useState(30)
  const [optimizationObjective, setOptimizationObjective] = useState('平衡')
  const [maxCandidates, setMaxCandidates] = useState(40)
  const [topN, setTopN] = useState(10)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [strategyOptions, setStrategyOptions] = useState<Array<{ name: string; label: string; enabled: boolean }>>([])
  const [defaultStrategyNames, setDefaultStrategyNames] = useState<string[]>([])
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([])
  const [strategiesOpen, setStrategiesOpen] = useState(false)

  const refresh = async () => {
    const items = (await listTasks({ limit: 100 })).filter((item) => evaluationTaskTypes.has(item.task_type))
    setTasks(items)
    if (selectedTask) {
      const latest = items.find((item) => item.id === selectedTask.id)
      if (latest) setSelectedTask(latest)
    }
  }

  const showDetail = async (id: string) => {
    const task = await refreshTaskStatus(id)
    const tm = task.task_type === 'strategy_evaluation' || task.task_type === 'portfolio_optimization' ? null : await getTimeMachineDetail(id).catch(() => null)
    setSelectedTask(task)
    setDetail(tm)
    await refresh()
  }

  useEffect(() => {
    refresh()
    getSettings().then((response) => {
      setSettings(response.settings)
      const strategies = response.settings.strategies || {}
      const names = strategyOrder.filter((name) => strategies[name]).concat(Object.keys(strategies).filter((name) => !strategyOrder.includes(name)))
      const options = names.map((name) => ({ name, label: strategies[name]?.label || name, enabled: Boolean(strategies[name]?.enabled) }))
      const enabled = options.filter((item) => item.enabled).map((item) => item.name)
      setStrategyOptions(options)
      setDefaultStrategyNames(enabled)
      setSelectedStrategies(enabled)
      const exitRules = response.settings.exit_rules || {}
      setExitEnabled(Boolean(exitRules.enabled))
      setStopLossPct(Number(exitRules.stop_loss ?? -0.12) * 100)
      setTrailingStopPct(Number(exitRules.trailing_stop ?? -0.08) * 100)
      setTrailingExec(String(exitRules.trailing_exec || 'next_open'))
      setSlippageBp(Number(exitRules.slippage ?? 0.003) * 10000)
    })
  }, [])

  const onCreate = async () => {
    const strategiesFilter = settings && sameSet(selectedStrategies, defaultStrategyNames) ? null : selectedStrategies
    if (evalMode === 'strategy_evaluation') {
      await createTask({
        name,
        task_type: 'strategy_evaluation',
        params: {
          start_date: startDate,
          end_date: endDate,
          strategies: selectedStrategies.length === strategyOptions.length ? 'all' : selectedStrategies,
          baseline: 'small_cap_quality',
          benchmark: '000905.SH',
          slippage: slippageBp / 10000
        }
      })
      await refresh()
      return
    }
    if (evalMode === 'portfolio_optimization') {
      await createTask({
        name,
        task_type: 'portfolio_optimization',
        params: {
          start_date: startDate,
          end_date: endDate,
          strategies: selectedStrategies.length === strategyOptions.length ? 'all' : selectedStrategies,
          objective: optimizationObjective,
          max_candidates: maxCandidates,
          top_n: topN,
          benchmark: '000905.SH',
          slippage: slippageBp / 10000
        }
      })
      await refresh()
      return
    }
    await createTask({
      name,
      task_type: 'evaluation_time_machine',
      params: {
        start_date: startDate,
        end_date: endDate,
        initial_cash: initialCash,
        rebalance_freq: rebalanceFreq,
        use_signal_cache: true,
        strategies_filter: strategiesFilter,
        exit_rules_cfg: {
          enabled: exitEnabled,
          stop_loss: stopLossPct / 100,
          trailing_stop: trailingStopPct / 100,
          trailing_exec: trailingExec,
          slippage: slippageBp / 10000
        }
      }
    })
    await refresh()
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

  const applyCandidate = async (task: TaskDTO, row: Record<string, unknown>) => {
    const candidateId = String(row.candidate_id || '')
    if (!candidateId) return
    const response = await applyPortfolioCandidate({ run_id: task.external_run_id, candidate_id: candidateId })
    setSettings(response.settings)
    const strategies = response.settings.strategies || {}
    const enabled = Object.entries(strategies).filter(([, strategy]) => strategy.enabled).map(([name]) => name)
    setDefaultStrategyNames(enabled)
    setSelectedStrategies(enabled)
    setNotice(`已应用组合：${String(row.name || candidateId)}`)
  }

  const createReviewTask = async (task: TaskDTO, row: Record<string, unknown>) => {
    await applyCandidate(task, row)
    const strategies = String(row.strategies || '').split(',').map((item) => item.trim()).filter(Boolean)
    await createTask({
      name: `复核-${String(row.name || '组合')}`,
      task_type: 'evaluation_time_machine',
      params: {
        start_date: task.params.start_date || task.summary.start,
        end_date: task.params.end_date || task.summary.end,
        initial_cash: initialCash,
        rebalance_freq: rebalanceFreq,
        use_signal_cache: true,
        strategies_filter: strategies,
        exit_rules_cfg: {
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
    setNotice(`已创建复核时光机：${String(row.name || '')}`)
    await refresh()
  }

  const columns = useMemo<Column<TaskDTO>[]>(() => [
    {
      key: 'name',
      name: '名称',
      minWidth: 150,
      resizable: true,
      renderCell: ({ row }) => row.name
    },
    {
      key: 'task_type',
      name: '类型',
      width: 230,
      resizable: true,
      renderCell: ({ row }) => row.task_type
    },
    {
      key: 'status',
      name: '状态',
      width: 130,
      renderCell: ({ row }) => <span className={`badge ${row.status}`}>{row.status}</span>
    },
    {
      key: 'progress',
      name: '进度',
      width: 90,
      renderCell: ({ row }) => `${Math.round(row.progress * 100)}%`
    },
    {
      key: 'external_run_id',
      name: 'Run ID',
      minWidth: 300,
      resizable: true,
      cellClass: 'mono',
      renderCell: ({ row }) => row.external_run_id || '-'
    },
    {
      key: 'created_at',
      name: '创建时间',
      width: 220,
      resizable: true,
      renderCell: ({ row }) => formatDate(row.created_at)
    },
    {
      key: 'actions',
      name: '操作',
      width: 260,
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

  if (selectedTask) {
    if (selectedTask.task_type === 'portfolio_optimization') {
      return (
        <PortfolioOptimizationDetail
          task={selectedTask}
          onBack={() => { setSelectedTask(null); setDetail(null) }}
          onRefresh={() => showDetail(selectedTask.id)}
          onStart={() => onStart(selectedTask.id)}
          onCancel={async () => { await cancelTask(selectedTask.id); await showDetail(selectedTask.id) }}
          onApply={(row) => applyCandidate(selectedTask, row)}
          onReview={(row) => createReviewTask(selectedTask, row)}
        />
      )
    }
    if (selectedTask.task_type === 'strategy_evaluation') {
      return (
        <StrategyEvaluationDetail
          task={selectedTask}
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
        <button className={evalMode === 'time_machine' ? 'active' : ''} onClick={() => { setEvalMode('time_machine'); setName('时光机评估'); setSelectedStrategies(defaultStrategyNames) }}>时光机</button>
        <button className={evalMode === 'strategy_evaluation' ? 'active' : ''} onClick={() => { setEvalMode('strategy_evaluation'); setName('策略准入评估'); setSelectedStrategies(strategyOptions.map((item) => item.name)) }}>策略准入</button>
        <button className={evalMode === 'portfolio_optimization' ? 'active' : ''} onClick={() => { setEvalMode('portfolio_optimization'); setName('一键组合优化'); setSelectedStrategies(strategyOptions.map((item) => item.name)) }}>组合优化</button>
      </div>
      <div className="formCard">
        <div className="formGrid">
          <Field label="评估名称"><input value={name} onChange={(event) => setName(event.target.value)} /></Field>
          {evalMode === 'time_machine' && <Field label="初始资金"><input type="number" value={initialCash} onChange={(event) => setInitialCash(Number(event.target.value))} /></Field>}
          <Field label="开始日期"><input value={startDate} onChange={(event) => setStartDate(event.target.value)} /></Field>
          <Field label="结束日期"><input value={endDate} onChange={(event) => setEndDate(event.target.value)} /></Field>
          {evalMode === 'time_machine' && <Field label="调仓频率">
            <select value={rebalanceFreq} onChange={(event) => setRebalanceFreq(Number(event.target.value))}>
              <option value={5}>每周（推荐）</option>
              <option value={20}>每月</option>
              <option value={1}>每天</option>
            </select>
          </Field>}
          {(evalMode === 'strategy_evaluation' || evalMode === 'portfolio_optimization') && <Field label="滑点 bp"><input type="number" value={slippageBp} onChange={(event) => setSlippageBp(Number(event.target.value))} /></Field>}
          {evalMode === 'portfolio_optimization' && <Field label="优化目标">
            <select value={optimizationObjective} onChange={(event) => setOptimizationObjective(event.target.value)}>
              <option value="稳健">稳健</option>
              <option value="平衡">平衡</option>
              <option value="进攻">进攻</option>
            </select>
          </Field>}
          {evalMode === 'portfolio_optimization' && <Field label="候选组合数"><input type="number" value={maxCandidates} onChange={(event) => setMaxCandidates(Number(event.target.value))} /></Field>}
          {evalMode === 'portfolio_optimization' && <Field label="展示 Top N"><input type="number" value={topN} onChange={(event) => setTopN(Number(event.target.value))} /></Field>}
        </div>

        {evalMode === 'time_machine' && <div className={`riskPanel ${exitEnabled ? 'open' : ''}`}>
          <div className="riskPanelHeader">
            <div>
              <div className="fieldLabel">风控规则</div>
              <span>{exitEnabled ? '止损 / 移动止盈 / 滑点已启用' : '关闭后本次评估不执行硬性卖出规则'}</span>
            </div>
            <label className="toggleField compact">
              <input type="checkbox" checked={exitEnabled} onChange={(event) => setExitEnabled(event.target.checked)} />
              <span>{exitEnabled ? '已启用' : '已关闭'}</span>
              <i />
            </label>
          </div>
          {exitEnabled && (
            <div className="riskGrid">
              <Field label="移动止盈成交">
                <select value={trailingExec} onChange={(event) => setTrailingExec(event.target.value)}>
                  <option value="next_open">次日开盘价</option>
                  <option value="close">当日收盘价</option>
                </select>
              </Field>
              <Field label="成本止损 %"><input type="number" value={stopLossPct} onChange={(event) => setStopLossPct(Number(event.target.value))} /></Field>
              <Field label="移动止盈 %"><input type="number" value={trailingStopPct} onChange={(event) => setTrailingStopPct(Number(event.target.value))} /></Field>
              <Field label="滑点 bp"><input type="number" value={slippageBp} onChange={(event) => setSlippageBp(Number(event.target.value))} /></Field>
            </div>
          )}
        </div>}

        <div className={`strategyPanel ${strategiesOpen ? 'open' : ''}`}>
          <button className="foldHeader" onClick={() => setStrategiesOpen((open) => !open)}>
            <div>
              <div className="fieldLabel">{evalMode === 'strategy_evaluation' ? '参与准入评估的策略插件' : evalMode === 'portfolio_optimization' ? '参与组合搜索的策略插件' : '参与评估的策略插件'}</div>
              <span>已选择 {selectedStrategies.length} / {strategyOptions.length} 个策略</span>
            </div>
            <i>{strategiesOpen ? '收起' : '展开'}</i>
          </button>
          {strategiesOpen && (
            <div className="strategyOptionGrid">
              {strategyOptions.map((strategy) => (
                <label key={strategy.name} className="strategyOption">
                  <input
                    type="checkbox"
                    checked={selectedStrategies.includes(strategy.name)}
                    onChange={(event) => {
                      setSelectedStrategies((prev) => event.target.checked
                        ? [...prev, strategy.name]
                        : prev.filter((name) => name !== strategy.name))
                    }}
                  />
                  <i />
                  <span>{strategy.label}</span>
                  <em>{strategy.name}</em>
                </label>
              ))}
            </div>
          )}
        </div>
        <div className="formActionsBottom">
          <button className="primaryButton" onClick={onCreate}>{evalMode === 'strategy_evaluation' ? '创建策略准入评估' : evalMode === 'portfolio_optimization' ? '创建组合优化' : '创建评估'}</button>
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
            rows={tasks}
            rowKeyGetter={(row) => row.id}
            rowHeight={58}
            headerRowHeight={48}
            defaultColumnOptions={{ resizable: true }}
            enableVirtualization={false}
          />
          {tasks.length === 0 && <div className="taskGridEmpty">暂无评估</div>}
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

function StrategyEvaluationDetail({ task, onBack, onRefresh, onStart, onCancel }: {
  task: TaskDTO
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

  const rows = Array.isArray(task.summary.rows) ? task.summary.rows as Array<Record<string, unknown>> : []
  const successCount = numberOf(task.summary.success_count, rows.filter((row) => row.status === 'ok').length)
  const emptyCount = numberOf(task.summary.empty_count, rows.filter((row) => row.status === 'empty').length)
  const failedCount = numberOf(task.summary.failed_count, rows.filter((row) => row.status !== 'ok' && row.status !== 'empty').length)
  const admitCount = numberOf(task.summary.admit_count, rows.filter((row) => row.admission === '可启用').length)
  const watchCount = numberOf(task.summary.watch_count, rows.filter((row) => row.admission === '继续观察').length)
  const rejectCount = numberOf(task.summary.reject_count, rows.filter((row) => row.admission === '暂不启用').length)
  const isRunning = task.status === 'running'
  const isRunnable = task.status !== 'running' && task.status !== 'success'

  return (
    <div className="taskDetailPage strategyEvalDetail">
      <div className="detailHero">
        <div>
          <div className="sectionLabel">STRATEGY ADMISSION</div>
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
        <Metric label="策略数" value={`${numberOf(task.summary.strategy_count, rows.length)}`} />
        <Metric label="成功" value={`${successCount}`} />
        <Metric label="空仓" value={`${emptyCount}`} />
        <Metric label="失败" value={`${failedCount}`} tone={failedCount > 0 ? 'negative' : ''} />
        <Metric label="可启用" value={`${admitCount}`} tone={admitCount > 0 ? 'positive' : ''} />
        <Metric label="观察" value={`${watchCount}`} />
        <Metric label="暂不启用" value={`${rejectCount}`} tone={rejectCount > 0 ? 'negative' : ''} />
        <Metric label="结果目录" value={resultPathText(task)} hint={task.result_path} />
      </div>

      <div className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="formTitle">策略准入表</div>
            <p className="recommendationMeta">收益、回撤、换手、容量暴露与小盘质量重合度</p>
          </div>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>策略</th>
                <th>建议</th>
                <th>状态</th>
                <th>启用</th>
                <th>总收益</th>
                <th>年化</th>
                <th>最大回撤</th>
                <th>夏普</th>
                <th>Calmar</th>
                <th>换手</th>
                <th>持仓</th>
                <th>平均市值</th>
                <th>平均成交额</th>
                <th>重合度</th>
                <th>相关性</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={String(row.strategy)}>
                  <td>{String(row.label || row.strategy)}</td>
                  <td>
                    <span className={`admissionBadge ${admissionClass(String(row.admission || ''))}`} title={String(row.reason || '')}>
                      {String(row.admission || '—')}
                    </span>
                  </td>
                  <td><span className={`badge ${String(row.status)}`}>{String(row.status || '-')}</span></td>
                  <td>{row.enabled ? '是' : '否'}</td>
                  <td className={toneOf(numberOf(row.total_return, 0))}>{percent(numberOf(row.total_return, 0), true)}</td>
                  <td className={toneOf(numberOf(row.annual_return, 0))}>{percent(numberOf(row.annual_return, 0), true)}</td>
                  <td className="negative">{percent(numberOf(row.max_drawdown, 0))}</td>
                  <td>{numberOf(row.sharpe, 0).toFixed(2)}</td>
                  <td>{numberOf(row.calmar, 0).toFixed(2)}</td>
                  <td>{percent(numberOf(row.avg_turnover, 0))}</td>
                  <td>{numberOf(row.avg_holdings, 0).toFixed(1)}</td>
                  <td>{money(numberOf(row.avg_total_mv, 0) / 100000000, 1)}亿</td>
                  <td>{money(numberOf(row.avg_amount, 0) / 100000000, 1)}亿</td>
                  <td>{row.overlap_with_baseline == null ? '—' : percent(numberOf(row.overlap_with_baseline, 0))}</td>
                  <td>{row.corr_with_baseline == null ? '—' : numberOf(row.corr_with_baseline, 0).toFixed(2)}</td>
                </tr>
              ))}
              {!isRunning && rows.length === 0 && <tr><td colSpan={15} className="emptyCell">暂无评估结果，启动任务后生成准入表</td></tr>}
              {isRunning && rows.length === 0 && <tr><td colSpan={15} className="emptyCell">评估运行中...</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function PortfolioOptimizationDetail({ task, onBack, onRefresh, onStart, onCancel, onApply, onReview }: {
  task: TaskDTO
  onBack: () => void
  onRefresh: () => void
  onStart: () => void
  onCancel: () => void
  onApply: (row: Record<string, unknown>) => void
  onReview: (row: Record<string, unknown>) => void
}) {
  useEffect(() => {
    if (task.status !== 'running') return
    const timer = window.setInterval(onRefresh, 3000)
    return () => window.clearInterval(timer)
  }, [task.status, onRefresh])

  const rows = Array.isArray(task.summary.rows) ? task.summary.rows as Array<Record<string, unknown>> : []
  const isRunning = task.status === 'running'
  const isRunnable = task.status !== 'running' && task.status !== 'success'

  return (
    <div className="taskDetailPage strategyEvalDetail">
      <div className="detailHero">
        <div>
          <div className="sectionLabel">PORTFOLIO OPTIMIZATION</div>
          <h2>{task.name}</h2>
          <p>{task.params.start_date as string} - {task.params.end_date as string} · {String(task.summary.objective || task.params.objective || '平衡')} · {statusText(task.status)}</p>
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
        <Metric label="候选组合" value={`${numberOf(task.summary.candidate_count, rows.length)}`} />
        <Metric label="可用策略" value={`${numberOf(task.summary.viable_count, 0)}`} />
        <Metric label="策略池" value={`${numberOf(task.summary.strategy_count, 0)}`} />
        <Metric label="最佳组合" value={String(task.summary.best_name || '—')} />
        <Metric label="最佳评分" value={numberOf(task.summary.best_score, 0).toFixed(3)} tone="positive" />
        <Metric label="最佳年化" value={percent(numberOf(task.summary.best_annual_return, 0), true)} tone={toneOf(numberOf(task.summary.best_annual_return, 0))} />
        <Metric label="最佳回撤" value={percent(numberOf(task.summary.best_max_drawdown, 0))} tone="negative" />
        <Metric label="结果目录" value={resultPathText(task)} hint={task.result_path} />
      </div>

      <div className="detailCard">
        <div className="tableHeader">
          <div>
            <div className="formTitle">推荐组合 Top {rows.length || ''}</div>
            <p className="recommendationMeta">自动生成候选组合，按收益、回撤、夏普、Calmar、换手与持仓分散度评分</p>
          </div>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>排名</th>
                <th>组合</th>
                <th>评分</th>
                <th>策略权重</th>
                <th>年化</th>
                <th>最大回撤</th>
                <th>夏普</th>
                <th>Calmar</th>
                <th>换手</th>
                <th>持仓</th>
                <th>平均市值</th>
                <th>平均成交额</th>
                <th>原因</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={String(row.candidate_id || row.rank)}>
                  <td>{numberOf(row.rank, 0)}</td>
                  <td>{String(row.name || '—')}</td>
                  <td>{numberOf(row.score, 0).toFixed(3)}</td>
                  <td className="mono">{formatWeights(row.weights)}</td>
                  <td className={toneOf(numberOf(row.annual_return, 0))}>{percent(numberOf(row.annual_return, 0), true)}</td>
                  <td className="negative">{percent(numberOf(row.max_drawdown, 0))}</td>
                  <td>{numberOf(row.sharpe, 0).toFixed(2)}</td>
                  <td>{numberOf(row.calmar, 0).toFixed(2)}</td>
                  <td>{percent(numberOf(row.avg_turnover, 0))}</td>
                  <td>{numberOf(row.avg_holdings, 0).toFixed(1)}</td>
                  <td>{money(numberOf(row.avg_total_mv, 0) / 100000000, 1)}亿</td>
                  <td>{money(numberOf(row.avg_amount, 0) / 100000000, 1)}亿</td>
                  <td>{String(row.reason || '')}</td>
                  <td>
                    <div className="taskActions compactActions">
                      <button className="secondaryButton quietButton" onClick={() => onApply(row)}>应用</button>
                      <button className="secondaryButton startButton" onClick={() => onReview(row)}>复核</button>
                    </div>
                  </td>
                </tr>
              ))}
              {!isRunning && rows.length === 0 && <tr><td colSpan={14} className="emptyCell">暂无组合优化结果，启动任务后生成推荐组合</td></tr>}
              {isRunning && rows.length === 0 && <tr><td colSpan={14} className="emptyCell">组合优化运行中...</td></tr>}
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

function Metric({ label, value, tone = '', hint = '' }: { label: string; value: string; tone?: string; hint?: string }) {
  return <div className="metricCard"><span>{label}</span><strong className={tone}>{value}</strong>{hint && <em>{hint}</em>}</div>
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
  if (value === '暂不启用') return 'reject'
  if (value === '继续观察') return 'watch'
  return ''
}

function formatWeights(value: unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return '—'
  return Object.entries(value as Record<string, unknown>)
    .map(([name, weight]) => `${name}:${percent(numberOf(weight, 0))}`)
    .join(' · ')
}

function statusText(status: string) {
  return ({ created: '待启动', queued: '排队中', running: '评估中', success: '已完成', failed: '失败', cancelled: '已取消', interrupted: '异常中断' } as Record<string, string>)[status] || status
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

function sameSet(left: string[], right: string[]) {
  return left.length === right.length && left.every((item) => right.includes(item))
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
