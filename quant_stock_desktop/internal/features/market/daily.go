package market

import (
	"sort"
	"strings"
)

type DailyBar struct {
	TSCode    string  `json:"ts_code"`
	TradeDate string  `json:"trade_date"`
	Open      float64 `json:"open"`
	High      float64 `json:"high"`
	Low       float64 `json:"low"`
	Close     float64 `json:"close"`
	PreClose  float64 `json:"pre_close"`
	Change    float64 `json:"change"`
	PctChg    float64 `json:"pct_chg"`
	Vol       float64 `json:"vol"`
	Amount    float64 `json:"amount"`
}

type DailyQuery struct {
	TSCode    string `json:"ts_code"`
	StartDate string `json:"start_date"`
	EndDate   string `json:"end_date"`
	Limit     int    `json:"limit"`
}

func (service *Service) ListDailyBars(dataPath string, query DailyQuery) ([]DailyBar, error) {
	if service == nil || service.repo == nil || service.repo.db == nil {
		return []DailyBar{}, nil
	}
	tsCode := strings.TrimSpace(query.TSCode)
	if tsCode == "" {
		return []DailyBar{}, nil
	}
	limit := query.Limit
	if limit <= 0 || limit > 5000 {
		limit = 5000
	}
	args := []any{tsCode}
	where := "WHERE ts_code = ?"
	if query.StartDate != "" {
		where += " AND trade_date >= ?"
		args = append(args, query.StartDate)
	}
	if query.EndDate != "" {
		where += " AND trade_date <= ?"
		args = append(args, query.EndDate)
	}
	args = append(args, limit)
	rows, err := service.repo.db.Conn().Query(`SELECT ts_code, trade_date, open, high, low, close, pre_close, change_amount, pct_chg, vol, amount
		FROM data_daily_bars `+where+` ORDER BY trade_date DESC LIMIT ?`, args...)
	if isMissingDataTable(err) {
		return []DailyBar{}, nil
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []DailyBar{}
	for rows.Next() {
		var item DailyBar
		if err := rows.Scan(&item.TSCode, &item.TradeDate, &item.Open, &item.High, &item.Low, &item.Close, &item.PreClose, &item.Change, &item.PctChg, &item.Vol, &item.Amount); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	sort.Slice(out, func(i, j int) bool { return out[i].TradeDate < out[j].TradeDate })
	return out, nil
}
