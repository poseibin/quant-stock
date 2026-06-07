import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import * as echarts from 'echarts/core'
import { CandlestickChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { getStockValuation, listDailyBars, listFinancialIndicators, listStockBasic, type DailyBar, type FinancialIndicator, type StockBasic, type StockValuation } from '../services/app'
import { KLineChart } from '../features/data/KLineChart'

echarts.use([CanvasRenderer, CandlestickChart, GridComponent, LegendComponent, LineChart, MarkLineComponent, TooltipComponent])

const periods = [
  { label: '3M', days: 60 },
  { label: '6M', days: 120 },
  { label: '1Y', days: 240 },
  { label: 'ALL', days: 5000 }
]

export function StockResearchPage({ initialTsCode = '', returnLabel = '', showLimitProjection = false, onBack }: { initialTsCode?: string; returnLabel?: string; showLimitProjection?: boolean; onBack?: () => void }) {
  const [stocks, setStocks] = useState<StockBasic[]>([])
  const [stockKeyword, setStockKeyword] = useState('')
  const [selectedCode, setSelectedCode] = useState('')
  const [period, setPeriod] = useState('1Y')
  const [activeTab, setActiveTab] = useState<'finance' | 'events' | 'strategy'>('finance')
  const [showVolume, setShowVolume] = useState(true)
  const [bars, setBars] = useState<DailyBar[]>([])
  const [financials, setFinancials] = useState<FinancialIndicator[]>([])
  const [valuation, setValuation] = useState<StockValuation | null>(null)

  const selectedStock = stocks.find((stock) => stock.ts_code === selectedCode) || (!selectedCode ? stocks[0] : null)
  const matchedStocks = useMemo(() => matchStocks(stocks, stockKeyword).slice(0, 8), [stocks, stockKeyword])
  const periodDays = periods.find((item) => item.label === period)?.days || 240
  const visibleBars = useMemo(() => bars.slice(-periodDays), [bars, periodDays])
  const summary = useMemo(() => buildSummary(visibleBars), [visibleBars])
  const latestFinancial = financials[financials.length - 1]

  const loadStocks = async (preferredCode = initialTsCode) => {
    const items = await listStockBasic({ limit: 5000 })
    const merged = preferredCode ? await ensureStockInList(items, preferredCode) : items
    setStocks(merged)
    if (preferredCode) {
      setSelectedCode(preferredCode)
      return
    }
    if (!selectedCode && merged.length > 0) {
      setSelectedCode(merged[0].ts_code)
    }
  }

  const openStock = async (tsCode: string) => {
    const code = tsCode.trim()
    if (!code) return
    setSelectedCode(code)
    setStockKeyword('')
    if (!stocks.some((stock) => stock.ts_code === code)) {
      const exact = await listStockBasic({ keyword: code, limit: 20 })
      setStocks((prev) => mergeStocks(prev, exact.filter((stock) => stock.ts_code === code)))
    }
  }

  const loadBars = async (tsCode: string) => {
    if (!tsCode) return
    const [nextBars, nextFinancials, nextValuation] = await Promise.all([
      listDailyBars({ ts_code: tsCode, start_date: defaultStartDate(), end_date: defaultEndDate(), limit: 260 }),
      listFinancialIndicators({ ts_code: tsCode, limit: 40 }),
      getStockValuation({ ts_code: tsCode })
    ])
    setBars(nextBars)
    setFinancials(nextFinancials)
    setValuation(nextValuation)
  }

  useEffect(() => {
    loadStocks()
  }, [])

  useEffect(() => {
    if (initialTsCode) openStock(initialTsCode)
  }, [initialTsCode])

  useEffect(() => {
    if (selectedStock) loadBars(selectedStock.ts_code)
  }, [selectedStock?.ts_code])

  if (!selectedStock) {
    return <div className="emptyState">正在加载股票...</div>
  }

  return (
    <div className="researchPage">
      {onBack && (
        <button className="researchBackButton" onClick={onBack}>
          <ArrowLeft size={16} />
          返回{returnLabel}
        </button>
      )}
      <div className="researchHero">
        <div>
          <div className="researchEyebrow">STOCK RESEARCH</div>
          <h2 className="researchTitle">{selectedStock.name}</h2>
          <div className="researchMeta">
            <span>{selectedStock.ts_code}</span>
            <span>{selectedStock.industry || '未知行业'}</span>
            <span>{selectedStock.market || '—'}</span>
          </div>
        </div>
        <div className="researchControls">
          <div className="stockSearchControl">
            <label>
              <span>搜索股票</span>
              <input value={stockKeyword} onChange={(event) => setStockKeyword(event.target.value)} placeholder="代码 / 名称 / 行业" />
            </label>
            {stockKeyword && (
              <div className="stockSearchResults">
                {matchedStocks.map((stock) => (
                  <button key={stock.ts_code} onClick={() => {
                    setSelectedCode(stock.ts_code)
                    setStockKeyword('')
                  }}>
                    <b>{stock.ts_code}</b>
                    <span>{stock.name}</span>
                    <em>{stock.industry || '—'}</em>
                  </button>
                ))}
                {matchedStocks.length === 0 && <div className="stockSearchEmpty">无匹配股票</div>}
              </div>
            )}
          </div>
          <div className="periodControl">
            <span>回溯</span>
            <div className="periodSegment" role="group" aria-label="选择回溯周期">
              {periods.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  className={period === item.label ? 'active' : ''}
                  onClick={() => setPeriod(item.label)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <label className="checkControl">
            <input type="checkbox" checked={showVolume} onChange={(event) => setShowVolume(event.target.checked)} />
            <span>成交量</span>
          </label>
        </div>
      </div>

      <div className="metricStrip">
        <MetricCard label="最新收盘" value={summary.latestClose} hint={summary.latestHint} tone="good" />
        <MetricCard label="区间涨跌" value={summary.changePct} hint={`${period} 累计`} tone={summary.changePct.startsWith('-') ? 'bad' : 'good'} />
        <MetricCard label="区间高 / 低" value={summary.highLow} hint="High / Low" />
        <MetricCard label="交易日数" value={String(visibleBars.length)} hint="Bars" />
      </div>

      <ValuationPanel valuation={valuation} />

      <div className="researchChartCard">
        <div className="sectionHeader">
          <div>
            <b>{showLimitProjection ? '涨停路径推演' : '价格走势'}</b>
            <span>{showLimitProjection ? '历史K线 + 未来10日连续涨停投影' : `${period} · K线 / 成交量`}</span>
          </div>
        </div>
        {showLimitProjection ? (
          <LimitProjectionChart bars={visibleBars} stock={selectedStock} />
        ) : (
          <KLineChart bars={visibleBars} showVolume={showVolume} />
        )}
      </div>

      <div className="researchTabs">
        <button className={activeTab === 'finance' ? 'active' : ''} onClick={() => setActiveTab('finance')}>财务指标</button>
        <button className={activeTab === 'events' ? 'active' : ''} onClick={() => setActiveTab('events')}>公告事件</button>
        <button className={activeTab === 'strategy' ? 'active' : ''} onClick={() => setActiveTab('strategy')}>策略覆盖</button>
      </div>

      {activeTab === 'finance' && (
        <>
          <div className="financeGrid">
            <MetricCard label="EPS" value={formatMetric(latestFinancial?.eps)} hint={latestFinancial?.end_date || '—'} />
            <MetricCard label="ROE" value={formatMetric(latestFinancial?.roe, '%')} hint="净资产收益率" tone={(latestFinancial?.roe || 0) >= 0 ? 'good' : 'bad'} />
            <MetricCard label="毛利率" value={formatMetric(latestFinancial?.gross_margin, '%')} hint="Gross Margin" />
            <MetricCard label="资产负债率" value={formatMetric(latestFinancial?.debt_to_assets, '%')} hint="Debt / Assets" tone={(latestFinancial?.debt_to_assets || 0) > 70 ? 'bad' : undefined} />
          </div>

          <div className="financeChartCard">
            <div className="sectionHeader">
              <div>
                <b>财务趋势</b>
                <span>ROE / 毛利率 · 最近 12 期</span>
              </div>
            </div>
            <FinancialChart items={financials.slice(-12)} />
          </div>
        </>
      )}

      {activeTab === 'events' && <EventsPanel />}
      {activeTab === 'strategy' && <StrategyPanel />}

      <div className="tableCard">
        <table>
          <thead>
            <tr>
              <th>trade_date</th>
              <th>open</th>
              <th>high</th>
              <th>low</th>
              <th>close</th>
              <th>pct_chg</th>
              <th>vol</th>
            </tr>
          </thead>
          <tbody>
            {visibleBars.slice(-8).reverse().map((bar) => (
              <tr key={bar.trade_date}>
                <td>{bar.trade_date}</td>
                <td>{bar.open.toFixed(2)}</td>
                <td>{bar.high.toFixed(2)}</td>
                <td>{bar.low.toFixed(2)}</td>
                <td>{bar.close.toFixed(2)}</td>
                <td>{bar.pct_chg.toFixed(2)}%</td>
                <td>{Math.round(bar.vol).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function MetricCard({ label, value, hint, tone }: { label: string; value: string; hint: string; tone?: 'good' | 'bad' }) {
  return (
    <div className={`metricCard ${tone || ''}`}>
      <span>{label}</span>
      <b>{value}</b>
      <em>{hint}</em>
    </div>
  )
}

type ProjectionBar = DailyBar & { projected?: boolean }

function LimitProjectionChart({ bars, stock }: { bars: DailyBar[]; stock: StockBasic }) {
  const chartRef = useRef<HTMLDivElement | null>(null)
  const projectedBars = useMemo(() => buildLimitProjectionBars(bars, stock), [bars, stock])
  const latestActual = bars[bars.length - 1]
  const target = projectedBars[projectedBars.length - 1]
  const projectionStart = projectedBars.find((bar) => bar.projected)?.trade_date || ''

  useEffect(() => {
    if (!chartRef.current || projectedBars.length === 0) return
    const chart = echarts.init(chartRef.current, 'dark')
    const dates = projectedBars.map((bar) => projectionDateLabel(bar.trade_date))
    chart.setOption({
      backgroundColor: 'transparent',
      animationDuration: 360,
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(10, 15, 24, 0.96)',
        borderColor: 'rgba(255, 176, 0, 0.35)',
        textStyle: { color: '#eef2ff', fontFamily: 'JetBrains Mono, Menlo, monospace' },
        axisPointer: { type: 'cross', lineStyle: { color: 'rgba(255, 176, 0, 0.45)' } },
        formatter: (params: unknown) => {
          const rows = Array.isArray(params) ? params as Array<{ dataIndex: number }> : []
          const bar = projectedBars[rows[0]?.dataIndex ?? 0]
          if (!bar) return ''
          return [
            `<b>${projectionDateLabel(bar.trade_date)}${bar.projected ? ' · 涨停投影' : ''}</b>`,
            `开 ${bar.open.toFixed(2)}　高 ${bar.high.toFixed(2)}`,
            `低 ${bar.low.toFixed(2)}　收 ${bar.close.toFixed(2)}`,
            `涨跌 ${bar.pct_chg.toFixed(2)}%`
          ].join('<br/>')
        }
      },
      grid: { left: 58, right: 24, top: 24, bottom: 42 },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.16)' } },
        axisTick: { show: false },
        axisLabel: { color: '#8f9ab3', hideOverlap: true }
      },
      yAxis: {
        scale: true,
        axisLabel: { color: '#8f9ab3' },
        splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.07)' } }
      },
      series: [
        {
          type: 'candlestick',
          name: '历史K线 + 涨停投影',
          data: projectedBars.map((bar) => ({
            value: [bar.open, bar.close, bar.low, bar.high],
            itemStyle: bar.projected
              ? { color: '#ff5f6d', borderColor: '#ffdf7e', borderWidth: 2 }
              : undefined
          })),
          itemStyle: {
            color: '#ef5350',
            color0: '#26c281',
            borderColor: '#ef5350',
            borderColor0: '#26c281'
          },
          markLine: {
            symbol: 'none',
            lineStyle: { color: 'rgba(255, 176, 0, 0.62)', type: 'dashed' },
            label: { color: '#ffdf7e', formatter: '投影起点' },
            data: projectionStart ? [{ xAxis: projectionDateLabel(projectionStart) }] : []
          }
        }
      ]
    })

    const resize = () => chart.resize()
    const observer = new ResizeObserver(resize)
    observer.observe(chartRef.current)
    return () => {
      observer.disconnect()
      chart.dispose()
    }
  }, [projectedBars, projectionStart])

  if (bars.length === 0) {
    return <div className="emptyState">暂无日线行情，无法生成涨停投影</div>
  }

  return (
    <div className="projectionChartWrap">
      <div className="projectionMeta">
        <span>当前收盘 {latestActual.close.toFixed(2)}</span>
        <span>10板价 {target.close.toFixed(2)}</span>
        <span>投影收益 {signedPercent((target.close - latestActual.close) / latestActual.close)}</span>
        <span>制度上限 {formatPercent(limitRateForStock(stock))}</span>
      </div>
      <div className="projectionHint">按当前交易制度连续涨停模拟价格路径，用来观察空间和卖出分批区间，不代表预测一定发生。</div>
      <div ref={chartRef} className="limitProjectionEchart" />
    </div>
  )
}

function ValuationPanel({ valuation }: { valuation: StockValuation | null }) {
  if (!valuation || !valuation.trade_date) {
    return (
      <div className="valuationPanel">
        <div className="valuationVerdict neutral">
          <span>估值判断</span>
          <b>暂无数据</b>
          <em>等待 daily_basic / 财务指标</em>
        </div>
      </div>
    )
  }

  const tone = valuation.verdict === '低估' ? 'good' : valuation.verdict === '虚高' ? 'bad' : 'neutral'
  return (
    <div className="valuationPanel">
      <div className={`valuationVerdict ${tone}`}>
        <span>估值判断</span>
        <b>{valuation.verdict}</b>
        <em>{valuation.trade_date} · {valuation.peer_count} 家同业</em>
      </div>
      <div className="valuationBody">
        <div className="valuationMetrics">
          <MiniMetric label="总市值" value={formatYi(valuation.total_mv)} hint={`分位 ${formatPercent(valuation.market_cap_percentile)}`} />
          <MiniMetric label="PE_TTM" value={formatNumber(valuation.pe_ttm)} hint={`PB ${formatNumber(valuation.pb)}`} />
          <MiniMetric label="PS_TTM" value={formatNumber(valuation.ps_ttm)} hint={`估值分位 ${formatPercent(valuation.valuation_percentile)}`} />
          <MiniMetric label="理论市值" value={formatYi(valuation.implied_mv)} hint={`偏离 ${signedPercent(valuation.mispricing_pct)}`} />
          <MiniMetric label="质量" value={`${Math.round(valuation.score)}`} hint={`ROE ${formatPercent(valuation.roe / 100)} · 负债 ${formatPercent(valuation.debt_to_assets / 100)}`} />
        </div>
        <div className="valuationReason">
          <span>{valuation.reason}</span>
          <div>
            {valuation.tags.map((tag) => <i key={tag}>{tag}</i>)}
          </div>
        </div>
      </div>
    </div>
  )
}

function MiniMetric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="miniMetric">
      <span>{label}</span>
      <b>{value}</b>
      <em>{hint}</em>
    </div>
  )
}

function buildLimitProjectionBars(bars: DailyBar[], stock: StockBasic): ProjectionBar[] {
  const actual: ProjectionBar[] = bars.slice(-120).map((bar) => ({ ...bar, projected: false }))
  const latest = actual[actual.length - 1]
  if (!latest) return []
  const rate = limitRateForStock(stock)
  let prevClose = latest.close
  let date = latest.trade_date
  const projected: ProjectionBar[] = []
  for (let i = 0; i < 10; i++) {
    date = nextTradeDate(date)
    const close = roundPrice(prevClose * (1 + rate))
    projected.push({
      ts_code: stock.ts_code,
      trade_date: date,
      open: prevClose,
      high: close,
      low: prevClose,
      close,
      pre_close: prevClose,
      change: close - prevClose,
      pct_chg: rate * 100,
      vol: 0,
      amount: 0,
      projected: true
    })
    prevClose = close
  }
  return [...actual, ...projected]
}

function limitRateForStock(stock: StockBasic) {
  const name = (stock.name || '').toUpperCase()
  const code = stock.ts_code || ''
  if (name.includes('ST')) return 0.05
  if (code.startsWith('688') || code.startsWith('300')) return 0.20
  if (code.startsWith('8') || code.startsWith('4') || code.includes('.BJ')) return 0.30
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

function roundPrice(value: number) {
  return Math.round(value * 100) / 100
}

function projectionDateLabel(value: string) {
  return /^\d{8}$/.test(value) ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : value
}

function matchStocks(stocks: StockBasic[], keyword: string) {
  const query = keyword.trim().toLowerCase()
  if (!query) return []
  return stocks.filter((stock) =>
    stock.ts_code.toLowerCase().includes(query) ||
    stock.symbol.toLowerCase().includes(query) ||
    stock.name.toLowerCase().includes(query) ||
    (stock.industry || '').toLowerCase().includes(query)
  )
}

async function ensureStockInList(stocks: StockBasic[], tsCode: string) {
  const code = tsCode.trim()
  if (!code || stocks.some((stock) => stock.ts_code === code)) return stocks
  const exact = await listStockBasic({ keyword: code, limit: 20 })
  return mergeStocks(stocks, exact.filter((stock) => stock.ts_code === code))
}

function mergeStocks(base: StockBasic[], extra: StockBasic[]) {
  if (extra.length === 0) return base
  const seen = new Set<string>()
  const merged = [...extra, ...base].filter((stock) => {
    if (seen.has(stock.ts_code)) return false
    seen.add(stock.ts_code)
    return true
  })
  return merged
}

function EventsPanel() {
  return (
    <div className="eventsGrid">
      <InfoBlock title="股东增减持" value="无" />
      <InfoBlock title="龙虎榜" value="无" />
      <InfoBlock title="业绩预告" value="无" />
    </div>
  )
}

function StrategyPanel() {
  return (
    <div className="eventsGrid">
      <InfoBlock title="策略信号" value="暂无覆盖" />
      <InfoBlock title="最近回测" value="暂无记录" />
      <InfoBlock title="风险标签" value="暂无标签" />
    </div>
  )
}

function InfoBlock({ title, value }: { title: string; value: string }) {
  return (
    <div className="infoBlock">
      <b>{title}</b>
      <span>{value}</span>
    </div>
  )
}

function FinancialChart({ items }: { items: FinancialIndicator[] }) {
  const chartRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!chartRef.current || items.length === 0) return

    const chart = echarts.init(chartRef.current, 'dark')
    const periods = items.map((item) => formatReportPeriod(item.end_date))

    chart.setOption({
      backgroundColor: 'transparent',
      animationDuration: 360,
      color: ['#26c281', '#ffb000'],
      grid: { left: 56, right: 28, top: 48, bottom: 36 },
      legend: {
        top: 8,
        right: 20,
        itemWidth: 18,
        itemHeight: 8,
        textStyle: { color: '#9aa7bd', fontSize: 12 }
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(10, 15, 24, 0.96)',
        borderColor: 'rgba(255, 176, 0, 0.35)',
        textStyle: { color: '#eef2ff', fontFamily: 'JetBrains Mono, Menlo, monospace' },
        axisPointer: { type: 'line', lineStyle: { color: 'rgba(255, 176, 0, 0.45)' } },
        formatter: (params: unknown) => {
          const rows = Array.isArray(params) ? params as Array<{ dataIndex: number; marker: string; seriesName: string; value: number }> : []
          const item = items[rows[0]?.dataIndex ?? 0]
          if (!item) return ''
          const lines = [
            `<b>${formatReportPeriod(item.end_date)} · ${formatDate(item.end_date)}</b>`,
            ...rows.map((row) => `${row.marker}${row.seriesName} ${formatMetric(row.value, '%')}`),
            `EPS ${formatMetric(item.eps)}`,
            `资产负债率 ${formatMetric(item.debt_to_assets, '%')}`
          ]
          return lines.join('<br/>')
        }
      },
      xAxis: {
        type: 'category',
        data: periods,
        axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.16)' } },
        axisTick: { show: false },
        axisLabel: { color: '#8f9ab3', interval: 0 }
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#8f9ab3',
          formatter: (value: number) => `${value}%`
        },
        splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.07)' } }
      },
      series: [
        {
          name: 'ROE',
          type: 'line',
          smooth: true,
          symbol: 'circle',
          symbolSize: 7,
          lineStyle: { width: 3 },
          data: items.map((item) => roundMetric(item.roe))
        },
        {
          name: '毛利率',
          type: 'line',
          smooth: true,
          symbol: 'circle',
          symbolSize: 7,
          lineStyle: { width: 3 },
          data: items.map((item) => roundMetric(item.gross_margin))
        }
      ]
    })

    const resize = () => chart.resize()
    const observer = new ResizeObserver(resize)
    observer.observe(chartRef.current)
    return () => {
      observer.disconnect()
      chart.dispose()
    }
  }, [items])

  if (items.length === 0) {
    return <div className="emptyState">暂无财务指标</div>
  }
  return <div ref={chartRef} className="financeEchart" />
}

function formatMetric(value?: number, suffix = '') {
  if (value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(2)}${suffix}`
}

function formatNumber(value?: number) {
  if (value === undefined || Number.isNaN(value) || value <= 0) return '—'
  return value.toFixed(2)
}

function formatPercent(value?: number) {
  if (value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}

function signedPercent(value?: number) {
  if (value === undefined || Number.isNaN(value)) return '—'
  return `${value >= 0 ? '+' : ''}${formatPercent(value)}`
}

function formatYi(value?: number) {
  if (value === undefined || Number.isNaN(value) || value <= 0) return '—'
  return `${(value / 10000).toFixed(1)}亿`
}

function roundMetric(value?: number) {
  if (value === undefined || Number.isNaN(value)) return null
  return Number(value.toFixed(2))
}

function formatReportPeriod(value: string) {
  const digits = String(value || '').replace(/\D/g, '')
  if (digits.length >= 8) {
    const year = digits.slice(0, 4)
    const month = Number(digits.slice(4, 6))
    const quarter = Math.max(1, Math.ceil(month / 3))
    return `${year}Q${quarter}`
  }
  if (digits.length >= 6) return `${digits.slice(0, 4)}-${digits.slice(4, 6)}`
  return value || '—'
}

function formatDate(value: string) {
  const digits = String(value || '').replace(/\D/g, '')
  if (digits.length >= 8) return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`
  return value || '—'
}

function defaultEndDate() {
  const value = new Date()
  return formatYYYYMMDD(value)
}

function defaultStartDate() {
  const value = new Date()
  value.setFullYear(value.getFullYear() - 1)
  return formatYYYYMMDD(value)
}

function formatYYYYMMDD(value: Date) {
  const year = value.getFullYear()
  const month = `${value.getMonth() + 1}`.padStart(2, '0')
  const day = `${value.getDate()}`.padStart(2, '0')
  return `${year}${month}${day}`
}

function buildSummary(bars: DailyBar[]) {
  if (bars.length === 0) {
    return { latestClose: '—', latestHint: '—', changePct: '—', highLow: '—' }
  }
  const first = bars[0]
  const latest = bars[bars.length - 1]
  const high = Math.max(...bars.map((bar) => bar.high))
  const low = Math.min(...bars.map((bar) => bar.low))
  const pct = first.close ? ((latest.close - first.close) / first.close) * 100 : 0
  return {
    latestClose: latest.close.toFixed(2),
    latestHint: `${latest.pct_chg.toFixed(2)}% · ${latest.trade_date}`,
    changePct: `${pct.toFixed(2)}%`,
    highLow: `${high.toFixed(2)} / ${low.toFixed(2)}`
  }
}
