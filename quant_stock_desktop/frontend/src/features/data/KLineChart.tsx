import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, CandlestickChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { DailyBar } from '../../services/app'

echarts.use([BarChart, CandlestickChart, CanvasRenderer, DataZoomComponent, GridComponent, TooltipComponent])

export function KLineChart({ bars, showVolume = true }: { bars: DailyBar[]; showVolume?: boolean }) {
  const chartRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!chartRef.current || bars.length === 0) return

    const chart = echarts.init(chartRef.current, 'dark')
    const dates = bars.map((bar) => bar.trade_date)
    const candles = bars.map((bar) => [bar.open, bar.close, bar.low, bar.high])
    const volumes = bars.map((bar) => ({
      value: bar.vol || 0,
      itemStyle: { color: bar.close >= bar.open ? 'rgba(239, 83, 80, 0.72)' : 'rgba(38, 194, 129, 0.72)' }
    }))

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
          const items = Array.isArray(params) ? params as Array<{ dataIndex: number }> : []
          const index = items[0]?.dataIndex ?? 0
          const bar = bars[index]
          if (!bar) return ''
          return [
            `<b>${bar.trade_date}</b>`,
            `开 ${bar.open.toFixed(2)}　高 ${bar.high.toFixed(2)}`,
            `低 ${bar.low.toFixed(2)}　收 ${bar.close.toFixed(2)}`,
            `涨跌 ${bar.pct_chg.toFixed(2)}%`,
            `成交量 ${Math.round(bar.vol || 0).toLocaleString('zh-CN')}`
          ].join('<br/>')
        }
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: showVolume
        ? [
            { left: 58, right: 24, top: 18, height: 280 },
            { left: 58, right: 24, top: 318, height: 88 }
          ]
        : [{ left: 58, right: 24, top: 18, bottom: 40 }],
      xAxis: [
        {
          type: 'category',
          data: dates,
          boundaryGap: true,
          axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.16)' } },
          axisTick: { show: false },
          axisLabel: { show: false },
          min: 'dataMin',
          max: 'dataMax'
        },
        {
          type: 'category',
          data: dates,
          gridIndex: 1,
          boundaryGap: true,
          axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.16)' } },
          axisTick: { show: false },
          axisLabel: { show: false },
          min: 'dataMin',
          max: 'dataMax'
        }
      ],
      yAxis: [
        {
          scale: true,
          axisLabel: { color: '#8f9ab3' },
          splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.07)' } }
        },
        {
          scale: true,
          gridIndex: 1,
          axisLabel: {
            color: '#8f9ab3',
            formatter: (value: number) => `${Math.round(value / 10000)}万`
          },
          splitLine: { show: false }
        }
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: showVolume ? [0, 1] : [0], start: 0, end: 100, throttle: 60 },
        {
          type: 'slider',
          xAxisIndex: showVolume ? [0, 1] : [0],
          height: 18,
          bottom: 8,
          borderColor: 'rgba(255, 255, 255, 0.08)',
          fillerColor: 'rgba(255, 176, 0, 0.16)',
          handleStyle: { color: '#ffb000' },
          textStyle: { color: '#8f9ab3' },
          brushSelect: false
        }
      ],
      series: [
        {
          type: 'candlestick',
          name: 'K线',
          data: candles,
          itemStyle: {
            color: '#ef5350',
            color0: '#26c281',
            borderColor: '#ef5350',
            borderColor0: '#26c281'
          }
        },
        ...(showVolume ? [{
          type: 'bar',
          name: '成交量',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
          barWidth: '60%'
        }] : [])
      ]
    })

    const resize = () => chart.resize()
    const observer = new ResizeObserver(resize)
    observer.observe(chartRef.current)
    return () => {
      observer.disconnect()
      chart.dispose()
    }
  }, [bars, showVolume])

  if (bars.length === 0) {
    return <div className="emptyState">暂无日线行情</div>
  }

  const latest = bars[bars.length - 1]
  return (
    <div className="chartWrap">
      <div className="chartMeta">
        <span>最新收盘 {latest.close?.toFixed(2)}</span>
        <span>涨跌幅 {latest.pct_chg?.toFixed(2)}%</span>
        <span>成交量 {Math.round(latest.vol || 0).toLocaleString()}</span>
      </div>
      <div ref={chartRef} className={showVolume ? 'klineEchart withVolume' : 'klineEchart'} />
    </div>
  )
}
