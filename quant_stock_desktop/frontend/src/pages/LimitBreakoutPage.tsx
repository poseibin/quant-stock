import { useEffect, useMemo, useRef, useState } from 'react'
import { DataGrid, type Column, type SortColumn } from 'react-data-grid'
import * as echarts from 'echarts/core'
import { CandlestickChart } from 'echarts/charts'
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import {
  listDailyBars,
  listLimitBreakoutCandidates,
  listLimitUpMomentumCandidates,
  refreshLimitBreakoutCandidates,
  refreshLimitUpMomentumCandidates,
  type BreakoutBar,
  type DailyBar,
  type LimitBreakoutCandidate,
  type LimitUpMomentumCandidate
} from '../services/app'

echarts.use([CanvasRenderer, CandlestickChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent])

type TabKey = 'momentum' | 'breakout'

function pct(value: number) {
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
}

function n(value: number, digits = 1) {
  return Number.isFinite(value) ? value.toFixed(digits) : '—'
}

function moneyYi(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '—'
  return `${(value / 10000).toFixed(1)}亿`
}

function timeLabel() {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function LimitBreakoutPage({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [activeTab, setActiveTab] = useState<TabKey>('momentum')

  return (
    <div className="breakoutPage">
      <section className="breakoutHero">
        <div>
          <div className="sectionLabel">LIMIT-UP RADAR</div>
          <div className="dashboardPanelTitle">涨停研究</div>
          <p>涨停板推荐是短线事件概率模型；横盘突发预警是长期形态扫描。两个模型独立缓存，手动刷新才重新计算。</p>
        </div>
      </section>

      <div className="inlineTabs breakoutTabs">
        <button className={activeTab === 'momentum' ? 'active' : ''} onClick={() => setActiveTab('momentum')}>涨停板推荐</button>
        <button className={activeTab === 'breakout' ? 'active' : ''} onClick={() => setActiveTab('breakout')}>横盘突发预警</button>
      </div>

      {activeTab === 'momentum' ? (
        <MomentumPanel onOpenResearch={onOpenResearch} />
      ) : (
        <BreakoutPanel onOpenResearch={onOpenResearch} />
      )}
    </div>
  )
}

function MomentumPanel({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [items, setItems] = useState<LimitUpMomentumCandidate[]>([])
  const [selectedCode, setSelectedCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [refreshInfo, setRefreshInfo] = useState('')
  const [error, setError] = useState('')
  const [sortColumns, setSortColumns] = useState<readonly SortColumn[]>([])
  const selected = items.find((item) => item.ts_code === selectedCode) || items[0] || null
  const topItems = items.slice(0, 3)
  const query = { limit: 50, lookback: 20, history_days: 760 }

  const load = async (refresh = false) => {
    setLoading(true)
    setError('')
    try {
      const previousTop = items[0]?.ts_code || ''
      const next = refresh ? await refreshLimitUpMomentumCandidates(query) : await listLimitUpMomentumCandidates(query)
      setItems(next)
      setSelectedCode((prev) => prev || next[0]?.ts_code || '')
      if (refresh) {
        const unchanged = previousTop && previousTop === next[0]?.ts_code
        setRefreshInfo(`已重新计算 ${timeLabel()} · 候选 ${next.length} 个${unchanged ? ' · 排名首位未变化' : ''}`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  const sortedItems = useMemo(() => sortMomentumItems(items, sortColumns), [items, sortColumns])

  useEffect(() => {
    load().catch((error) => console.error('[limit-up-momentum] load failed', error))
  }, [])

  const columns = useMemo<Column<LimitUpMomentumCandidate>[]>(() => [
    {
      key: 'stock',
      name: '股票',
      width: 170,
      frozen: true,
      renderCell: ({ row }) => (
        <button className="stockLink" onClick={() => setSelectedCode(row.ts_code)}>
          {row.name}<span className="mono">{row.ts_code}</span>
        </button>
      ),
      sortable: true
    },
    { key: 'industry', name: '分类', width: 110, renderCell: ({ row }) => row.industry || '未知行业', sortable: true },
    { key: 'recommendation', name: '建议', width: 112, renderCell: ({ row }) => <span className={`breakoutRankBadge ${momentumTone(row.recommendation)}`}>{row.recommendation}</span>, sortable: true },
    { key: 'stage', name: '阶段', width: 78, renderCell: ({ row }) => row.stage, sortable: true },
    { key: 'score', name: '总分', width: 78, renderCell: ({ row }) => n(row.score, 0), sortable: true },
    { key: 'chain', name: '连板潜力', width: 96, renderCell: ({ row }) => n(row.chain_potential, 0), sortable: true },
    { key: 'risk', name: '末端风险', width: 96, renderCell: ({ row }) => n(row.end_risk, 0), sortable: true },
    { key: 'fund', name: '资金确认', width: 96, renderCell: ({ row }) => n(row.fund_confirmation, 0), sortable: true },
    { key: 'ret20', name: '近20日', width: 92, renderCell: ({ row }) => pct(row.recent_20_return), sortable: true },
    { key: 'turnover', name: '换手', width: 78, renderCell: ({ row }) => `${n(row.turnover_rate, 1)}%`, sortable: true },
    { key: 'volume', name: '量比', width: 76, renderCell: ({ row }) => n(row.volume_ratio, 1), sortable: true },
    { key: 'mv', name: '流通市值', width: 104, renderCell: ({ row }) => moneyYi(row.circ_mv), sortable: true }
  ], [])

  return (
    <>
      <section className="breakoutHero compactHero">
        <div>
          <div className="dashboardPanelTitle">涨停板推荐</div>
          <p>基于 daily、daily_basic、stock_basic、龙虎榜数据，按首板/二板事件提取位置、量能、趋势、流动性和资金确认特征。</p>
          {(refreshInfo || error) && <p className={error ? 'errorText' : 'cardHint'}>{error || refreshInfo}</p>}
        </div>
        <button className="primaryButton" onClick={() => load(true)} disabled={loading}>{loading ? '计算中…' : '刷新推荐'}</button>
      </section>

      {topItems.length > 0 && (
        <section className="breakoutRecommendPanel">
          <div className="breakoutRecommendHeader">
            <div>
              <div className="sectionLabel">RECOMMEND</div>
              <div className="dashboardPanelTitle">今日短线候选</div>
            </div>
            <div className="breakoutRecommendCount">{items.length} 个候选</div>
          </div>
          <div className="breakoutRecommendGrid">
            {topItems.map((item, index) => (
              <button
                key={item.ts_code}
                className={selected?.ts_code === item.ts_code ? 'breakoutRecommendCard active' : 'breakoutRecommendCard'}
                onClick={() => setSelectedCode(item.ts_code)}
              >
                <span>Top {index + 1} · {item.stage}</span>
                <b>{item.name}</b>
                <em>{item.ts_code} · {item.industry || '未知行业'}</em>
                <strong className={momentumTone(item.recommendation)}>{item.recommendation}</strong>
                <i>连板潜力 {n(item.chain_potential, 0)} · 末端风险 {n(item.end_risk, 0)}</i>
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="breakoutLayout">
        <section className="tableCard breakoutListCard">
          <div className="tableHeader">
            <div>
              <div className="formTitle">推荐列表</div>
              <div className="cardHint">按连板潜力、末端风险、流动性风险和资金确认综合排序</div>
            </div>
          </div>
          <div className="taskGridShell breakoutGridShell">
            <DataGrid
              className="taskGrid rdg-dark"
              columns={columns}
              rows={sortedItems}
              rowKeyGetter={(row) => row.ts_code}
              rowHeight={58}
              headerRowHeight={44}
              sortColumns={sortColumns}
              onSortColumnsChange={setSortColumns}
              defaultColumnOptions={{ resizable: true }}
              enableVirtualization={false}
              onCellClick={({ row }) => setSelectedCode(row.ts_code)}
            />
            {items.length === 0 && <div className="taskGridEmpty">{loading ? '正在计算...' : '暂无推荐缓存，点击刷新推荐'}</div>}
          </div>
        </section>

        {selected && (
          <section className="dashboardPanel breakoutDetail">
            <div className="breakoutDetailHeader">
              <div>
                <div className="sectionLabel">SELECTED</div>
                <div className="dashboardPanelTitle">{selected.name} <span>{selected.ts_code}</span></div>
              </div>
              <button className="secondaryButton quietButton" onClick={() => onOpenResearch?.(selected.ts_code)}>个股研究</button>
            </div>
            <div className="breakoutDecision">
              <div>
                <span>推荐建议</span>
                <b className={momentumTone(selected.recommendation)}>{selected.recommendation}</b>
                <em>{momentumDecision(selected)}</em>
              </div>
              <div>
                <span>历史标签</span>
                <b>{pct(selected.return_5d)}</b>
                <em>首板后5日收益 · 最大回撤 {pct(selected.max_drawdown_5d)}</em>
              </div>
            </div>
            <div className="breakoutMetricGrid">
              <Mini label="连板潜力" value={n(selected.chain_potential, 0)} />
              <Mini label="末端风险" value={n(selected.end_risk, 0)} />
              <Mini label="流动性风险" value={n(selected.liquidity_risk, 0)} />
              <Mini label="资金确认" value={n(selected.fund_confirmation, 0)} />
              <Mini label="阶段" value={selected.stage} />
              <Mini label="近60日涨幅" value={pct(selected.recent_60_return)} />
              <Mini label="换手率" value={`${n(selected.turnover_rate, 1)}%`} />
              <Mini label="流通市值" value={moneyYi(selected.circ_mv)} />
              <Mini label="龙虎榜净买" value={moneyYi(selected.dragon_tiger_net_buy)} />
            </div>
            <ReasonBlocks reasons={selected.reasons} risks={selected.risks} />
            <ProjectedLimitChart candidate={selected} />
          </section>
        )}
      </div>
    </>
  )
}

function BreakoutPanel({ onOpenResearch }: { onOpenResearch?: (tsCode: string) => void }) {
  const [items, setItems] = useState<LimitBreakoutCandidate[]>([])
  const [selectedCode, setSelectedCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [refreshInfo, setRefreshInfo] = useState('')
  const [error, setError] = useState('')
  const selected = items.find((item) => item.ts_code === selectedCode) || items[0] || null
  const query = { limit: 40, lookback: 1250, recent_days: 20 }

  const load = async (refresh = false) => {
    setLoading(true)
    setError('')
    try {
      const previousTop = items[0]?.ts_code || ''
      const next = refresh ? await refreshLimitBreakoutCandidates(query) : await listLimitBreakoutCandidates(query)
      setItems(next)
      setSelectedCode((prev) => prev || next[0]?.ts_code || '')
      if (refresh) {
        const unchanged = previousTop && previousTop === next[0]?.ts_code
        setRefreshInfo(`已重新扫描 ${timeLabel()} · 候选 ${next.length} 个${unchanged ? ' · 排名首位未变化' : ''}`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load().catch((error) => console.error('[breakout] load failed', error))
  }, [])

  const columns = useMemo<Column<LimitBreakoutCandidate>[]>(() => [
    {
      key: 'stock',
      name: '股票',
      width: 170,
      frozen: true,
      renderCell: ({ row }) => (
        <button className="stockLink" onClick={() => setSelectedCode(row.ts_code)}>
          {row.name}<span className="mono">{row.ts_code}</span>
        </button>
      )
    },
    { key: 'score', name: '总分', width: 86, renderCell: ({ row }) => n(row.score, 0) },
    { key: 'industry', name: '行业', width: 110, renderCell: ({ row }) => row.industry || '—' },
    { key: 'flat', name: '横盘分', width: 96, renderCell: ({ row }) => n(row.flat_score, 0) },
    { key: 'breakout', name: '启动分', width: 96, renderCell: ({ row }) => n(row.breakout_score, 0) },
    { key: 'quality', name: '经营分', width: 96, renderCell: ({ row }) => n(row.quality_score, 0) },
    { key: 'recent', name: '近20日', width: 96, renderCell: ({ row }) => pct(row.recent_return) },
    { key: 'limits', name: '涨停数', width: 86, renderCell: ({ row }) => `${row.limit_up_count}` },
    { key: 'base', name: '箱体高低比', width: 120, renderCell: ({ row }) => n(row.base_ratio, 2) }
  ], [])

  return (
    <>
      <section className="breakoutHero compactHero">
        <div>
          <div className="dashboardPanelTitle">横盘突发预警</div>
          <p>扫描长期低波动箱体、近期突然放量拉升，并结合 ROE、净利率、资产负债率给出经营质量分。</p>
          {(refreshInfo || error) && <p className={error ? 'errorText' : 'cardHint'}>{error || refreshInfo}</p>}
        </div>
        <button className="primaryButton" onClick={() => load(true)} disabled={loading}>{loading ? '扫描中…' : '重新扫描'}</button>
      </section>

      <div className="breakoutLayout">
        <section className="tableCard breakoutListCard">
          <div className="tableHeader">
            <div>
              <div className="formTitle">形态候选</div>
              <div className="cardHint">按横盘、启动、经营三类评分综合排序</div>
            </div>
          </div>
          <div className="taskGridShell breakoutGridShell">
            <DataGrid
              className="taskGrid rdg-dark"
              columns={columns}
              rows={items}
              rowKeyGetter={(row) => row.ts_code}
              rowHeight={58}
              headerRowHeight={44}
              defaultColumnOptions={{ resizable: true }}
              enableVirtualization={false}
              onCellClick={({ row }) => setSelectedCode(row.ts_code)}
            />
            {items.length === 0 && <div className="taskGridEmpty">{loading ? '正在扫描...' : '暂无扫描缓存，点击重新扫描'}</div>}
          </div>
        </section>

        {selected && (
          <section className="dashboardPanel breakoutDetail">
            <div className="breakoutDetailHeader">
              <div>
                <div className="sectionLabel">SELECTED</div>
                <div className="dashboardPanelTitle">{selected.name} <span>{selected.ts_code}</span></div>
              </div>
              <button className="secondaryButton quietButton" onClick={() => onOpenResearch?.(selected.ts_code)}>个股研究</button>
            </div>
            <div className="breakoutMetricGrid">
              <Mini label="总分" value={n(selected.score, 0)} />
              <Mini label="近20日涨幅" value={pct(selected.recent_return)} />
              <Mini label="涨停数" value={`${selected.limit_up_count}`} />
              <Mini label="量能放大" value={`${n(selected.volume_surge, 1)}x`} />
              <Mini label="箱体高低比" value={n(selected.base_ratio, 2)} />
              <Mini label="ROE" value={`${n(selected.roe, 1)}%`} />
            </div>
            <div className="breakoutReasons">
              {selected.reasons.map((reason) => <span key={reason}>{reason}</span>)}
            </div>
            <ProjectedLimitChart candidate={selected} />
          </section>
        )}
      </div>
    </>
  )
}

function Mini({ label, value }: { label: string; value: string }) {
  return <div className="miniMetric compact"><span>{label}</span><b>{value}</b></div>
}

function ReasonBlocks({ reasons, risks }: { reasons: string[]; risks: string[] }) {
  return (
    <div className="breakoutNarrative">
      <div>
        <span>推荐理由</span>
        <p>{reasons.length ? reasons.join('，') + '。' : '暂无明显优势特征。'}</p>
      </div>
      <div>
        <span>风险提示</span>
        <p>{risks.length ? risks.join('，') + '。' : '仍需关注开板波动、滑点和次日承接。'}</p>
      </div>
    </div>
  )
}

function sortMomentumItems(items: LimitUpMomentumCandidate[], sortColumns: readonly SortColumn[]) {
  if (sortColumns.length === 0) return items
  return [...items].sort((a, b) => {
    for (const sort of sortColumns) {
      const diff = compareMomentumValue(a, b, sort.columnKey)
      if (diff !== 0) {
        return sort.direction === 'ASC' ? diff : -diff
      }
    }
    return 0
  })
}

function compareMomentumValue(a: LimitUpMomentumCandidate, b: LimitUpMomentumCandidate, key: string) {
  switch (key) {
    case 'stock':
      return compareText(a.name || a.ts_code, b.name || b.ts_code)
    case 'industry':
      return compareText(a.industry || '未知行业', b.industry || '未知行业')
    case 'recommendation':
      return recommendationRank(a.recommendation) - recommendationRank(b.recommendation)
    case 'stage':
      return stageRank(a.stage) - stageRank(b.stage)
    case 'score':
      return compareNumber(a.score, b.score)
    case 'chain':
      return compareNumber(a.chain_potential, b.chain_potential)
    case 'risk':
      return compareNumber(a.end_risk, b.end_risk)
    case 'fund':
      return compareNumber(a.fund_confirmation, b.fund_confirmation)
    case 'ret20':
      return compareNumber(a.recent_20_return, b.recent_20_return)
    case 'turnover':
      return compareNumber(a.turnover_rate, b.turnover_rate)
    case 'volume':
      return compareNumber(a.volume_ratio, b.volume_ratio)
    case 'mv':
      return compareNumber(a.circ_mv, b.circ_mv)
    default:
      return 0
  }
}

function compareText(a: string, b: string) {
  return a.localeCompare(b, 'zh-Hans-CN')
}

function compareNumber(a: number, b: number) {
  const av = Number.isFinite(a) ? a : Number.NEGATIVE_INFINITY
  const bv = Number.isFinite(b) ? b : Number.NEGATIVE_INFINITY
  return av - bv
}

function recommendationRank(value: string) {
  if (value === '二板确认') return 4
  if (value === '首板观察') return 3
  if (value === '高风险加速') return 2
  if (value === '不追') return 1
  return 0
}

function stageRank(value: string) {
  if (value === '二板') return 2
  if (value === '首板') return 1
  return 0
}

function momentumTone(value: string) {
  if (value === '首板观察' || value === '二板确认') return 'positive'
  if (value === '高风险加速' || value === '不追') return 'negative'
  return 'watch'
}

function momentumDecision(item: LimitUpMomentumCandidate) {
  if (item.recommendation === '二板确认') return '连板确认度较高，但需要控制开板回撤和追高滑点。'
  if (item.recommendation === '首板观察') return '适合观察次日竞价、承接和封板强度，不是无脑追板。'
  if (item.recommendation === '高风险加速') return '已经进入高波动末端，偏交易型机会，仓位要轻。'
  return '综合评分不足，暂不追。'
}

type ProjectedCandidate = {
  ts_code: string
  name?: string
  close: number
  latest_date?: string
  trade_date?: string
  bars?: BreakoutBar[]
  projected_bars?: BreakoutBar[]
}

function ProjectedLimitChart({ candidate }: { candidate: ProjectedCandidate }) {
  const chartRef = useRef<HTMLDivElement | null>(null)
  const [loadedBars, setLoadedBars] = useState<BreakoutBar[]>([])
  const baseBars = loadedBars.length > (candidate.bars?.length || 0) ? loadedBars : candidate.bars || []
  const bars = useMemo(() => displayBars(candidate, baseBars), [candidate, baseBars])

  useEffect(() => {
    let cancelled = false
    const existing = candidate.bars || []
    if (existing.length >= 420) {
      setLoadedBars([])
      return
    }
    const endDate = candidate.latest_date || candidate.trade_date || ''
    const startDate = twoYearsBefore(endDate)
    listDailyBars({ ts_code: candidate.ts_code, start_date: startDate, end_date: endDate, limit: 620 })
      .then((rows) => {
        if (!cancelled) setLoadedBars(rows.map(dailyToBreakoutBar))
      })
      .catch(() => {
        if (!cancelled) setLoadedBars([])
      })
    return () => {
      cancelled = true
    }
  }, [candidate.ts_code, candidate.latest_date, candidate.trade_date])

  useEffect(() => {
    if (!chartRef.current || bars.length === 0) return
    const chart = echarts.init(chartRef.current, 'dark')
    const dates = bars.map((bar) => fmtDate(bar.trade_date))
    chart.setOption({
      backgroundColor: 'transparent',
      animationDuration: 360,
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(10, 15, 24, 0.96)',
        borderColor: 'rgba(255, 176, 0, 0.35)',
        textStyle: { color: '#eef2ff', fontFamily: 'JetBrains Mono, Menlo, monospace' },
        formatter: (params: unknown) => {
          const items = Array.isArray(params) ? params as Array<{ dataIndex: number }> : []
          const bar = bars[items[0]?.dataIndex ?? 0]
          if (!bar) return ''
          return [
            `<b>${fmtDate(bar.trade_date)}${bar.projected ? '  未来涨停推演' : ''}</b>`,
            `开 ${bar.open.toFixed(2)} 高 ${bar.high.toFixed(2)}`,
            `低 ${bar.low.toFixed(2)} 收 ${bar.close.toFixed(2)}`,
            `涨跌 ${bar.pct_chg.toFixed(2)}%`
          ].join('<br/>')
        }
      },
      legend: { top: 0, right: 6, textStyle: { color: '#8f9ab3' } },
      grid: { left: 54, right: 26, top: 38, bottom: 34 },
      xAxis: { type: 'category', data: dates, axisLabel: { color: '#8f9ab3' }, axisTick: { show: false } },
      yAxis: { scale: true, axisLabel: { color: '#8f9ab3' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.07)' } } },
      series: [
        {
          type: 'candlestick',
          name: 'K线 + 5日涨停推演',
          data: bars.map((bar) => [bar.open, bar.close, bar.low, bar.high]),
          itemStyle: {
            color: '#ef5350',
            color0: '#26c281',
            borderColor: '#ef5350',
            borderColor0: '#26c281'
          },
          markLine: {
            symbol: 'none',
            lineStyle: { color: 'rgba(255, 176, 0, 0.55)', type: 'dashed' },
            data: [{ xAxis: fmtDate(bars.find((bar) => bar.projected)?.trade_date || candidate.latest_date || candidate.trade_date || '') }]
          }
        }
      ]
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [bars, candidate.latest_date, candidate.trade_date, candidate.ts_code])

  return (
    <div className="projectedLimitBlock">
      <div className="projectedLimitTitle">
        <span>最近2年K线</span>
        <b>未来5天涨停推演</b>
      </div>
      <div ref={chartRef} className="projectedLimitChart" />
    </div>
  )
}

function displayBars(candidate: ProjectedCandidate, actual: BreakoutBar[]) {
  const projected = candidate.projected_bars?.length ? candidate.projected_bars : projectFallbackBars(candidate)
  if (actual.length > 0) return [...actual, ...projected]
  const date = candidate.latest_date || candidate.trade_date || ''
  return [
    { trade_date: date, open: candidate.close, high: candidate.close, low: candidate.close, close: candidate.close, pct_chg: 0, projected: false },
    ...projected
  ]
}

function dailyToBreakoutBar(bar: DailyBar): BreakoutBar {
  return {
    trade_date: bar.trade_date,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    pct_chg: bar.pct_chg,
    projected: false
  }
}

function twoYearsBefore(value: string) {
  const date = /^\d{8}$/.test(value)
    ? new Date(Number(value.slice(0, 4)), Number(value.slice(4, 6)) - 1, Number(value.slice(6, 8)))
    : new Date()
  date.setFullYear(date.getFullYear() - 2)
  return `${date.getFullYear()}${String(date.getMonth() + 1).padStart(2, '0')}${String(date.getDate()).padStart(2, '0')}`
}

function projectFallbackBars(candidate: ProjectedCandidate) {
  const rate = limitRate(candidate.ts_code, candidate.name || '')
  const out: BreakoutBar[] = []
  let date = candidate.latest_date || candidate.trade_date || ''
  let prev = candidate.close
  for (let i = 0; i < 5; i++) {
    date = nextTradeDate(date)
    const close = Math.round(prev * (1 + rate) * 100) / 100
    out.push({ trade_date: date, open: prev, low: prev, high: close, close, pct_chg: rate * 100, projected: true })
    prev = close
  }
  return out
}

function limitRate(tsCode: string, name: string) {
  if (name.toUpperCase().includes('ST')) return 0.05
  if (tsCode.startsWith('688') || tsCode.startsWith('300')) return 0.20
  if (tsCode.startsWith('8') || tsCode.startsWith('4') || tsCode.includes('.BJ')) return 0.30
  return 0.10
}

function nextTradeDate(value: string) {
  const date = /^\d{8}$/.test(value)
    ? new Date(Number(value.slice(0, 4)), Number(value.slice(4, 6)) - 1, Number(value.slice(6, 8)))
    : new Date()
  date.setDate(date.getDate() + 1)
  while (date.getDay() === 0 || date.getDay() === 6) {
    date.setDate(date.getDate() + 1)
  }
  return `${date.getFullYear()}${String(date.getMonth() + 1).padStart(2, '0')}${String(date.getDate()).padStart(2, '0')}`
}

function fmtDate(value: string) {
  return /^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : value
}
