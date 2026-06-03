import { useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import {
  getDataUpdateStatus,
  getPositionHistory,
  getPositionRecommendation,
  getPositionSummary,
  listDatasetUpdateStatus,
  listTasks,
  type AppInfo,
  type DatasetUpdateStatus,
  type PositionHistoryPoint,
  type PositionRecommendation,
  type PositionSummary,
  type RunStatus,
  type TaskDTO
} from '../services/app'
import { formatDate } from '../components/format'

echarts.use([CanvasRenderer, GridComponent, LegendComponent, LineChart, TooltipComponent])

const evaluationTaskTypes = new Set(['evaluation_time_machine', 'strategy_evaluation', 'portfolio_optimization'])

function money(value: number) {
  return value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function percent(value: number) {
  return `${(value * 100).toFixed(2)}%`
}

function signedPercent(value: number) {
  return `${value >= 0 ? '+' : ''}${percent(value)}`
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    created: '待启动',
    queued: '排队中',
    running: '运行中',
    success: '已完成',
    failed: '失败',
    interrupted: '已中断',
    cancelled: '已取消',
    done: '已完成',
    idle: '空闲',
    error: '异常'
  }
  return labels[status] || status || '—'
}

function tone(value: number) {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return ''
}

export function DashboardPage({ appInfo }: { appInfo: AppInfo }) {
  const [summary, setSummary] = useState<PositionSummary | null>(null)
  const [history, setHistory] = useState<PositionHistoryPoint[]>([])
  const [recommendation, setRecommendation] = useState<PositionRecommendation | null>(null)
  const [tasks, setTasks] = useState<TaskDTO[]>([])
  const [dataStatus, setDataStatus] = useState<RunStatus | null>(null)
  const [datasetStatus, setDatasetStatus] = useState<DatasetUpdateStatus[]>([])

  useEffect(() => {
    Promise.all([
      getPositionSummary(),
      getPositionHistory(),
      getPositionRecommendation().catch(() => null),
      listTasks({ limit: 200 }),
      getDataUpdateStatus(),
      listDatasetUpdateStatus()
    ]).then(([nextSummary, nextHistory, nextRecommendation, nextTasks, nextDataStatus, nextDatasetStatus]) => {
      setSummary(nextSummary)
      setHistory(nextHistory)
      setRecommendation(nextRecommendation)
      setTasks(nextTasks)
      setDataStatus(nextDataStatus)
      setDatasetStatus(nextDatasetStatus)
    }).catch(() => {})
  }, [])

  const topLevelTasks = tasks.filter((task) => !task.parent_id)
  const activeTasks = topLevelTasks.filter((task) => task.status === 'running' || task.status === 'queued')
  const pendingTasks = topLevelTasks.filter((task) => task.status === 'created')
  const runningTask = activeTasks.find((task) => task.status === 'running') || activeTasks[0]
  const completedTasks = topLevelTasks.filter((task) => task.status === 'success')
  const failedTasks = topLevelTasks.filter((task) => task.status === 'failed' || task.status === 'interrupted' || task.status === 'cancelled')
  const evaluations = topLevelTasks.filter((task) => evaluationTaskTypes.has(task.task_type))
  const completedEvaluations = evaluations.filter((task) => task.status === 'success')
  const dataFinished = datasetStatus.filter((item) => item.state === 'done' || item.state === 'success').length
  const dataFailed = datasetStatus.filter((item) => item.state === 'failed' || item.state === 'error').length
  const dataRunning = datasetStatus.filter((item) => item.state === 'running').length
  const dataTotal = datasetStatus.length
  const risk = buildRisk(summary)
  const returnStats = useMemo(() => buildReturnStats(history, summary), [history, summary])
  const signalStats = buildSignalStats(recommendation)
  const events = buildEvents({ recommendation, summary, tasks: topLevelTasks, dataStatus, datasetStatus })
  const currentTaskLabel = runningTask ? `${runningTask.name} · ${Math.round(runningTask.progress * 100)}%` : '无'

  return (
    <div className="dashboardPage">
      <section className="dashboardAssetPanel returnPanel">
        <div className="returnPanelIntro">
          <div>
            <div className="sectionLabel">PORTFOLIO</div>
            <div className="dashboardPanelTitle">收益与资金状态</div>
          </div>
          <div className="returnHeadline">
            <span>累计收益率</span>
            <b className={summary ? tone(summary.cum_return) : ''}>{summary ? signedPercent(summary.cum_return) : '—'}</b>
            <em>
              区间收益 {returnStats ? signedPercent(returnStats.periodReturn) : '—'}
              {summary ? ` · 持仓 ${summary.n_holdings} 只` : ''}
            </em>
          </div>
        </div>
        <div className="returnPanelBody">
          <div className="assetGrid returnMetricGrid">
            <AssetBlock label="总资产" value={summary ? money(summary.total_assets) : '—'} hint={summary ? `累计 ${signedPercent(summary.cum_return)}` : ''} tone={summary ? tone(summary.cum_return) : ''} />
            <AssetBlock label="持仓市值" value={summary ? money(summary.market_value) : '—'} hint={summary ? `仓位 ${percent(risk.positionWeight)}` : ''} />
            <AssetBlock label="可用现金" value={summary ? money(summary.cash) : '—'} hint={summary ? `占比 ${percent(risk.cashWeight)}` : ''} />
            <AssetBlock label="今日收益率" value={summary ? signedPercent(summary.today_pct) : '—'} hint={summary ? `盈亏 ${money(summary.today_pnl)}` : ''} tone={summary ? tone(summary.today_pct) : ''} />
            <AssetBlock label="年化收益率" value={returnStats ? signedPercent(returnStats.annualReturn) : '—'} hint={returnStats ? `${returnStats.days} 个自然日` : '暂无历史'} tone={returnStats ? tone(returnStats.annualReturn) : ''} />
            <AssetBlock label="最大回撤" value={returnStats ? signedPercent(returnStats.maxDrawdown) : '—'} hint={summary ? `累计盈亏 ${money(summary.total_pnl)}` : ''} tone={returnStats ? tone(returnStats.maxDrawdown) : ''} />
            <AssetBlock label="浮动盈亏" value={summary ? money(summary.unrealized_pnl) : '—'} hint={summary ? signedPercent(summary.unrealized_pct) : ''} tone={summary ? tone(summary.unrealized_pnl) : ''} />
            <AssetBlock label="已实现盈亏" value={summary ? money(summary.realized_pnl) : '—'} hint={summary ? `已平仓 ${summary.n_closed} 只` : ''} tone={summary ? tone(summary.realized_pnl) : ''} />
          </div>
          <ReturnChart history={history} />
        </div>
      </section>

      <div className="dashboardGrid">
        <section className="dashboardPanel">
          <div className="sectionLabel">SIGNAL</div>
          <div className="dashboardPanelTitle">最新信号</div>
          <div className="dashboardRows">
            <Row label="信号日" value={recommendation?.date || '—'} />
            <Row label="目标仓位" value={recommendation ? percent(recommendation.total_weight) : '—'} />
            <Row label="目标只数" value={recommendation ? `${recommendation.n_holdings} 只` : '—'} />
            <Row label="调仓状态" value={recommendation?.rebalanced ? `今日已调仓 ${recommendation.rebalance_trades} 笔` : '待调仓'} />
            <Row label="买入 / 卖出" value={recommendation ? `${signalStats.buy} / ${signalStats.sell}` : '—'} />
          </div>
        </section>

        <section className="dashboardPanel">
          <div className="sectionLabel">SYSTEM</div>
          <div className="dashboardPanelTitle">系统任务</div>
          <div className="dashboardRows">
            <Row label="当前运行" value={currentTaskLabel} />
            <Row label="待处理任务" value={`${activeTasks.length + pendingTasks.length} 个`} />
            <Row label="今日完成" value={`${completedTasks.length} 个`} />
            <Row label="异常 / 取消" value={`${failedTasks.length} 个`} tone={failedTasks.length ? 'negative' : ''} />
            <Row label="评估任务" value={`${completedEvaluations.length}/${evaluations.length}`} />
          </div>
        </section>

        <section className="dashboardPanel">
          <div className="sectionLabel">DATA</div>
          <div className="dashboardPanelTitle">数据状态</div>
          <div className="dashboardRows">
            <Row label="更新任务" value={statusLabel(dataStatus?.state || '')} />
            <Row label="当前阶段" value={dataStatus?.stage || '—'} />
            <Row label="数据集" value={dataTotal ? `${dataFinished}/${dataTotal}` : '—'} />
            <Row label="运行 / 异常" value={`${dataRunning} / ${dataFailed}`} tone={dataFailed ? 'negative' : ''} />
            <Row label="更新时间" value={dataStatus?.updated_at ? formatDate(dataStatus.updated_at) : '—'} />
          </div>
        </section>
      </div>

      <div className="dashboardBottomGrid">
        <section className="dashboardPanel">
          <div className="sectionLabel">RISK</div>
          <div className="dashboardPanelTitle">持仓风险概览</div>
          <div className="dashboardRows">
            <Row label="最大单票权重" value={risk.topPosition ? `${risk.topPosition.name} ${percent(risk.topPosition.weight)}` : '—'} />
            <Row label="行业集中 Top 1" value={risk.topIndustry ? `${risk.topIndustry.name} ${percent(risk.topIndustry.weight)}` : '—'} />
            <Row label="今日上涨 / 下跌" value={`${risk.upCount} / ${risk.downCount}`} tone={risk.downCount > risk.upCount ? 'negative' : ''} />
            <Row label="盈利 / 亏损持仓" value={`${risk.winCount} / ${risk.lossCount}`} tone={risk.lossCount > risk.winCount ? 'negative' : ''} />
            <Row label="现金缓冲" value={percent(risk.cashWeight)} />
          </div>
        </section>

        <section className="dashboardPanel eventPanel">
          <div className="sectionLabel">TIMELINE</div>
          <div className="dashboardPanelTitle">最近事件</div>
          <div className="eventList">
            {events.map((event) => (
              <div className="eventItem" key={`${event.time}-${event.title}`}>
                <span className={event.tone} />
                <div>
                  <b>{event.title}</b>
                  <em>{event.detail}</em>
                </div>
                <time>{event.time}</time>
              </div>
            ))}
            {events.length === 0 && <div className="emptyEvent">暂无系统事件</div>}
          </div>
        </section>
      </div>
    </div>
  )
}

function Row({ label, value, tone = '' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="dashboardRow">
      <span>{label}</span>
      <b className={tone}>{value}</b>
    </div>
  )
}

function AssetBlock({ label, value, hint, tone = '' }: { label: string; value: string; hint: string; tone?: string }) {
  return (
    <div className="assetBlock">
      <span>{label}</span>
      <b className={tone}>{value}</b>
      <em>{hint}</em>
    </div>
  )
}

function ReturnChart({ history }: { history: PositionHistoryPoint[] }) {
  const chartRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!chartRef.current) return
    const chart = echarts.init(chartRef.current, 'dark')
    const rows = history.filter((item) => item.equity > 0).sort((left, right) => left.date.localeCompare(right.date))
    if (rows.length === 0) {
      chart.clear()
      return () => chart.dispose()
    }
    const dates = rows.map((item) => formatCompactDate(item.date))
    const equity = rows.map((item) => Number(item.equity.toFixed(2)))
    const returns = rows.map((item) => Number((item.cum_return * 100).toFixed(2)))
    chart.setOption({
      backgroundColor: 'transparent',
      animationDuration: 360,
      color: ['#ffb000', '#26c281'],
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(10, 15, 24, 0.96)',
        borderColor: 'rgba(255, 176, 0, 0.35)',
        textStyle: { color: '#eef2ff', fontFamily: 'JetBrains Mono, Menlo, monospace' },
        formatter: (params: unknown) => {
          const items = Array.isArray(params) ? params as Array<{ dataIndex: number }> : []
          const row = rows[items[0]?.dataIndex ?? 0]
          if (!row) return ''
          return [
            `<b>${formatCompactDate(row.date)}</b>`,
            `总资产 ${money(row.equity)}`,
            `累计收益 ${signedPercent(row.cum_return)}`,
            `日收益 ${signedPercent(row.daily_return)}`
          ].join('<br/>')
        }
      },
      legend: {
        top: 0,
        right: 6,
        textStyle: { color: '#8f9ab3' },
        itemWidth: 14,
        itemHeight: 8
      },
      grid: { left: 62, right: 58, top: 38, bottom: 34 },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.16)' } },
        axisTick: { show: false },
        axisLabel: { color: '#8f9ab3' }
      },
      yAxis: [
        {
          type: 'value',
          scale: true,
          axisLabel: { color: '#8f9ab3', formatter: (value: number) => `${Math.round(value / 10000)}万` },
          splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.07)' } }
        },
        {
          type: 'value',
          scale: true,
          axisLabel: { color: '#8f9ab3', formatter: (value: number) => `${value.toFixed(0)}%` },
          splitLine: { show: false }
        }
      ],
      series: [
        {
          type: 'line',
          name: '总资产',
          data: equity,
          smooth: true,
          symbol: rows.length <= 12 ? 'circle' : 'none',
          lineStyle: { width: 3 },
          areaStyle: { color: 'rgba(255, 176, 0, 0.10)' }
        },
        {
          type: 'line',
          name: '累计收益率',
          yAxisIndex: 1,
          data: returns,
          smooth: true,
          symbol: rows.length <= 12 ? 'circle' : 'none',
          lineStyle: { width: 2 }
        }
      ]
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [history])

  if (history.length === 0) {
    return <div className="returnChart emptyReturnChart">暂无历史快照</div>
  }
  return <div ref={chartRef} className="returnChart" />
}

function buildReturnStats(history: PositionHistoryPoint[], summary: PositionSummary | null) {
  const rows = history.filter((item) => item.equity > 0).sort((left, right) => left.date.localeCompare(right.date))
  if (rows.length === 0) return null
  const first = rows[0]
  const last = rows[rows.length - 1]
  const periodReturn = first.equity > 0 ? last.equity / first.equity - 1 : (summary?.cum_return || 0)
  const days = Math.max(1, daysBetween(first.date, last.date))
  const annualReturn = days > 0 ? Math.pow(1 + periodReturn, 365 / days) - 1 : periodReturn
  let peak = first.equity
  let maxDrawdown = 0
  for (const row of rows) {
    peak = Math.max(peak, row.equity)
    if (peak > 0) {
      maxDrawdown = Math.min(maxDrawdown, row.equity / peak - 1)
    }
  }
  return { periodReturn, annualReturn, maxDrawdown, days }
}

function daysBetween(start: string, end: string) {
  const s = parseCompactDate(start)
  const e = parseCompactDate(end)
  if (!s || !e) return 1
  return Math.max(1, Math.round((e.getTime() - s.getTime()) / 86400000))
}

function parseCompactDate(value: string) {
  if (!/^\d{8}$/.test(value)) return null
  return new Date(Number(value.slice(0, 4)), Number(value.slice(4, 6)) - 1, Number(value.slice(6, 8)))
}

function formatCompactDate(value: string) {
  if (/^\d{8}$/.test(value)) {
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
  }
  return value || '—'
}

function buildSignalStats(recommendation: PositionRecommendation | null) {
  const rows = recommendation?.rows || []
  return rows.reduce((stats, row) => {
    if (row.action === 'BUY' || row.action === 'ADD') stats.buy += 1
    if (row.action === 'SELL' || row.action === 'TRIM') stats.sell += 1
    return stats
  }, { buy: 0, sell: 0 })
}

function buildRisk(summary: PositionSummary | null) {
  const positions = summary?.positions || []
  const totalAssets = Math.max(summary?.total_assets || 0, 0)
  const marketValue = Math.max(summary?.market_value || 0, 0)
  const cash = Math.max(summary?.cash || 0, 0)
  const topPosition = positions.reduce<typeof positions[number] | null>((best, item) => {
    if (!best || item.weight > best.weight) return item
    return best
  }, null)
  const industryWeights = new Map<string, number>()
  positions.forEach((item) => {
    const name = item.industry || '未知行业'
    industryWeights.set(name, (industryWeights.get(name) || 0) + item.weight)
  })
  const topIndustry = [...industryWeights.entries()]
    .map(([name, weight]) => ({ name, weight }))
    .sort((left, right) => right.weight - left.weight)[0] || null
  return {
    positionWeight: totalAssets > 0 ? marketValue / totalAssets : 0,
    cashWeight: totalAssets > 0 ? cash / totalAssets : 0,
    topPosition,
    topIndustry,
    upCount: positions.filter((item) => item.today_pnl > 0).length,
    downCount: positions.filter((item) => item.today_pnl < 0).length,
    winCount: positions.filter((item) => item.unrealized_pnl > 0).length,
    lossCount: positions.filter((item) => item.unrealized_pnl < 0).length
  }
}

function buildEvents({ recommendation, summary, tasks, dataStatus, datasetStatus }: {
  recommendation: PositionRecommendation | null
  summary: PositionSummary | null
  tasks: TaskDTO[]
  dataStatus: RunStatus | null
  datasetStatus: DatasetUpdateStatus[]
}) {
  const events: Array<{ title: string; detail: string; time: string; tone: string; sortTime: string }> = []
  if (recommendation?.generated_at) {
    events.push({
      title: '今日信号已生成',
      detail: `${recommendation.n_holdings} 只目标持仓，${recommendation.rebalanced ? `已调仓 ${recommendation.rebalance_trades} 笔` : '待调仓'}`,
      time: formatDate(recommendation.generated_at),
      tone: recommendation.rebalanced ? 'good' : 'warn',
      sortTime: recommendation.generated_at
    })
  }
  if (summary?.updated_at) {
    events.push({
      title: '持仓收益已刷新',
      detail: `今日盈亏 ${money(summary.today_pnl)}，当前持仓 ${summary.n_holdings} 只`,
      time: formatDate(summary.updated_at),
      tone: summary.today_pnl >= 0 ? 'good' : 'bad',
      sortTime: summary.updated_at
    })
  }
  if (dataStatus?.updated_at) {
    events.push({
      title: `数据更新${statusLabel(dataStatus.state)}`,
      detail: dataStatus.stage || dataStatus.message || '数据任务状态已更新',
      time: formatDate(dataStatus.updated_at),
      tone: dataStatus.state === 'error' || dataStatus.state === 'failed' ? 'bad' : dataStatus.state === 'running' ? 'warn' : 'good',
      sortTime: dataStatus.updated_at
    })
  }
  datasetStatus
    .filter((item) => item.state === 'failed' || item.state === 'error' || item.state === 'running')
    .slice(0, 3)
    .forEach((item) => {
      events.push({
        title: `${item.dataset} ${statusLabel(item.state)}`,
        detail: item.message || item.error_message || `${item.progress_done}/${item.progress_total}`,
        time: formatDate(item.updated_at),
        tone: item.state === 'running' ? 'warn' : 'bad',
        sortTime: item.updated_at
      })
    })
  tasks.slice(0, 6).forEach((task) => {
    if (task.status !== 'running' && task.status !== 'failed' && task.status !== 'interrupted' && task.status !== 'success') return
    events.push({
      title: `${task.name} ${statusLabel(task.status)}`,
      detail: task.error_message || task.task_type,
      time: formatDate(task.updated_at),
      tone: task.status === 'running' ? 'warn' : task.status === 'success' ? 'good' : 'bad',
      sortTime: task.updated_at
    })
  })
  return events
    .filter((event) => event.sortTime)
    .sort((left, right) => right.sortTime.localeCompare(left.sortTime))
    .slice(0, 6)
}
