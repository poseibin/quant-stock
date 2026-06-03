import type { DailyBar, StockBasic } from '../../services/app'
import { KLineChart } from './KLineChart'

export function StockDailyPanel({ stock, bars, startDate, setStartDate, endDate, setEndDate, refresh, close }: { stock: StockBasic; bars: DailyBar[]; startDate: string; setStartDate: (value: string) => void; endDate: string; setEndDate: (value: string) => void; refresh: () => void; close: () => void }) {
  return (
    <div className="stockDailyPanel">
      <div className="tableHeader">
        <div>
          <div className="formTitle">{stock.name} 日线行情</div>
          <div className="cardHint">{stock.ts_code} / {stock.industry || '未知行业'} / 最近展示 {bars.length} 条 K 线</div>
        </div>
        <div className="taskActions">
          <input value={startDate} onChange={(event) => setStartDate(event.target.value)} />
          <input value={endDate} onChange={(event) => setEndDate(event.target.value)} />
          <button className="secondaryButton" onClick={refresh}>刷新行情</button>
          <button className="secondaryButton" onClick={close}>关闭</button>
        </div>
      </div>
      <KLineChart bars={bars} />
    </div>
  )
}
