import type { StockBasic } from '../../services/app'

export function StockBasicPanel({ stocks, page, setPage, keyword, setKeyword, loadStocks, openDaily }: { stocks: StockBasic[]; page: number; setPage: (value: number) => void; keyword: string; setKeyword: (value: string) => void; loadStocks: () => void; openDaily: (stock: StockBasic) => void }) {
  const pageSize = 10
  const totalPages = Math.max(1, Math.ceil(stocks.length / pageSize))
  const safePage = Math.min(page, totalPages)
  const visibleStocks = stocks.slice((safePage - 1) * pageSize, safePage * pageSize)

  return (
    <>
      <div className="stockSearchBar">
        <div>
          <div className="searchTitle">按代码、名称或行业检索</div>
          <div className="cardHint">每页 10 条，股票选择以搜索为主</div>
        </div>
        <div className="searchControls">
          <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索股票" />
          <button className="secondaryButton" onClick={loadStocks}>查询</button>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>代码</th>
            <th>名称</th>
            <th>行业</th>
            <th>地区</th>
            <th>市场</th>
            <th>上市日期</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {visibleStocks.map((stock) => (
            <tr key={stock.ts_code}>
              <td className="mono">{stock.ts_code}</td>
              <td>{stock.name}</td>
              <td>{stock.industry || '—'}</td>
              <td>{stock.area || '—'}</td>
              <td>{stock.market || '—'}</td>
              <td>{stock.list_date || '—'}</td>
              <td>{stock.list_status || '—'}</td>
              <td><button className="secondaryButton" onClick={() => openDaily(stock)}>日线</button></td>
            </tr>
          ))}
          {stocks.length === 0 && <tr><td colSpan={8} className="emptyCell">暂无股票基础信息</td></tr>}
        </tbody>
      </table>
      <div className="paginationBar">
        <span>共 {stocks.length} 条 / 第 {safePage} 页 / 共 {totalPages} 页</span>
        <div className="taskActions">
          <button className="secondaryButton" disabled={safePage <= 1} onClick={() => setPage(safePage - 1)}>上一页</button>
          <button className="secondaryButton" disabled={safePage >= totalPages} onClick={() => setPage(safePage + 1)}>下一页</button>
        </div>
      </div>
    </>
  )
}
