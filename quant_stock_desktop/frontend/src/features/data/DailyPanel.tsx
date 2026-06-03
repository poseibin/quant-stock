import type { DailyBar, StockBasic } from '../../services/app'
import { KLineChart } from './KLineChart'

export function DailyPanel({ bars, dailyCode, setDailyCode, startDate, setStartDate, endDate, setEndDate, selectedStock, loadDailyBars }: { bars: DailyBar[]; dailyCode: string; setDailyCode: (value: string) => void; startDate: string; setStartDate: (value: string) => void; endDate: string; setEndDate: (value: string) => void; selectedStock: StockBasic | null; loadDailyBars: () => void }) {
  return (
    <>
      <div className="panelActions">
        <input value={dailyCode} onChange={(event) => setDailyCode(event.target.value)} placeholder="股票代码" />
        <input value={startDate} onChange={(event) => setStartDate(event.target.value)} />
        <input value={endDate} onChange={(event) => setEndDate(event.target.value)} />
        <button className="secondaryButton" onClick={loadDailyBars}>查询日线</button>
      </div>
      <div className="cardHint">{selectedStock ? `${selectedStock.name} / ${selectedStock.industry || '未知行业'}` : dailyCode} / 最近展示 {bars.length} 条 K 线</div>
      <KLineChart bars={bars} />
    </>
  )
}
