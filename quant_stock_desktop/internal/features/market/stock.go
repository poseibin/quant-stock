package market

import "strings"

type StockBasic struct {
	TSCode     string `json:"ts_code"`
	Symbol     string `json:"symbol"`
	Name       string `json:"name"`
	Area       string `json:"area"`
	Industry   string `json:"industry"`
	Market     string `json:"market"`
	ListDate   string `json:"list_date"`
	ListStatus string `json:"list_status"`
}

type StockBasicQuery struct {
	Keyword string `json:"keyword"`
	Limit   int    `json:"limit"`
}

func (service *Service) ListStockBasic(dataPath string, query StockBasicQuery) ([]StockBasic, error) {
	if service == nil || service.repo == nil || service.repo.db == nil {
		return []StockBasic{}, nil
	}
	limit := query.Limit
	if limit <= 0 || limit > 5000 {
		limit = 5000
	}
	keyword := strings.TrimSpace(query.Keyword)
	args := []any{}
	where := ""
	if keyword != "" {
		like := "%" + strings.ToLower(keyword) + "%"
		where = `WHERE LOWER(ts_code) LIKE ? OR LOWER(symbol) LIKE ? OR LOWER(name) LIKE ? OR LOWER(industry) LIKE ?`
		args = append(args, like, like, like, like)
	}
	args = append(args, limit)
	rows, err := service.repo.db.Conn().Query(`SELECT ts_code, symbol, name, area, industry, market, list_date, list_status
		FROM data_stock_basic `+where+` ORDER BY ts_code LIMIT ?`, args...)
	if isMissingDataTable(err) {
		return []StockBasic{}, nil
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []StockBasic{}
	for rows.Next() {
		var item StockBasic
		if err := rows.Scan(&item.TSCode, &item.Symbol, &item.Name, &item.Area, &item.Industry, &item.Market, &item.ListDate, &item.ListStatus); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}
