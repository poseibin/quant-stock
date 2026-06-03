package result

import (
	"database/sql"
	"encoding/json"
)

type SnapshotRow struct {
	Date          string  `json:"date"`
	Cash          float64 `json:"cash"`
	MarketValue   float64 `json:"market_value"`
	Equity        float64 `json:"equity"`
	NHoldings     int64   `json:"n_holdings"`
	UnrealizedPnL float64 `json:"unrealized_pnl"`
	RealizedPnL   float64 `json:"realized_pnl"`
	CumReturn     float64 `json:"cum_return"`
}

type TradeRow struct {
	Date        string  `json:"date"`
	TSCode      string  `json:"ts_code"`
	Name        string  `json:"name"`
	Action      string  `json:"action"`
	Shares      int64   `json:"shares"`
	Price       float64 `json:"price"`
	Amount      float64 `json:"amount"`
	HoldDays    int64   `json:"hold_days"`
	RealizedPnL float64 `json:"realized_pnl"`
	ExitReason  string  `json:"exit_reason"`
	ExecDate    string  `json:"exec_date"`
	IsNew       bool    `json:"is_new"`
}

type PositionRow struct {
	Date          string  `json:"date"`
	TSCode        string  `json:"ts_code"`
	Name          string  `json:"name"`
	Shares        int64   `json:"shares"`
	AvgCost       float64 `json:"avg_cost"`
	Price         float64 `json:"price"`
	MarketValue   float64 `json:"market_value"`
	UnrealizedPnL float64 `json:"unrealized_pnl"`
	UnrealizedPct float64 `json:"unrealized_pct"`
	TodayPnL      float64 `json:"today_pnl"`
	TodayPct      float64 `json:"today_pct"`
	Weight        float64 `json:"weight"`
	HoldDays      int64   `json:"hold_days"`
}

type TimeMachineDetail struct {
	RunID     string         `json:"run_id"`
	Summary   map[string]any `json:"summary"`
	Snapshots []SnapshotRow  `json:"snapshots"`
	Trades    []TradeRow     `json:"trades"`
	Positions []PositionRow  `json:"positions"`
}

func ReadTimeMachineDetail(db *sql.DB, runID string) (TimeMachineDetail, error) {
	detail := TimeMachineDetail{
		RunID:     runID,
		Summary:   map[string]any{},
		Snapshots: []SnapshotRow{},
		Trades:    []TradeRow{},
		Positions: []PositionRow{},
	}

	var summaryJSON string
	_ = db.QueryRow(`SELECT COALESCE(summary_json, '') FROM evaluation_tasks WHERE external_run_id = ?`, runID).Scan(&summaryJSON)
	if summaryJSON != "" {
		_ = json.Unmarshal([]byte(summaryJSON), &detail.Summary)
	}

	snapRows, err := db.Query(`SELECT trade_date, cash, market_value, equity, n_holdings,
		unrealized_pnl, realized_pnl, cum_return
		FROM time_machine_snapshots WHERE run_id = ? ORDER BY trade_date`, runID)
	if err != nil {
		return TimeMachineDetail{}, err
	}
	defer snapRows.Close()
	for snapRows.Next() {
		var row SnapshotRow
		if err := snapRows.Scan(&row.Date, &row.Cash, &row.MarketValue, &row.Equity, &row.NHoldings, &row.UnrealizedPnL, &row.RealizedPnL, &row.CumReturn); err != nil {
			return TimeMachineDetail{}, err
		}
		detail.Snapshots = append(detail.Snapshots, row)
	}
	if err := snapRows.Err(); err != nil {
		return TimeMachineDetail{}, err
	}

	tradeRows, err := db.Query(`SELECT trade_date, ts_code, name, action, shares, price, amount,
		hold_days, realized_pnl, exit_reason, exec_date, COALESCE(is_new, 0)
		FROM time_machine_trades WHERE run_id = ? ORDER BY trade_date, id`, runID)
	if err != nil {
		return TimeMachineDetail{}, err
	}
	defer tradeRows.Close()
	for tradeRows.Next() {
		var row TradeRow
		var isNew int
		if err := tradeRows.Scan(&row.Date, &row.TSCode, &row.Name, &row.Action, &row.Shares, &row.Price, &row.Amount, &row.HoldDays, &row.RealizedPnL, &row.ExitReason, &row.ExecDate, &isNew); err != nil {
			return TimeMachineDetail{}, err
		}
		row.IsNew = isNew != 0
		detail.Trades = append(detail.Trades, row)
	}
	if err := tradeRows.Err(); err != nil {
		return TimeMachineDetail{}, err
	}

	positionRows, err := db.Query(`SELECT trade_date, ts_code, name, shares, avg_cost, price,
		market_value, unrealized_pnl, unrealized_pct, today_pnl, today_pct, weight, hold_days
		FROM time_machine_positions
		WHERE run_id = ? AND trade_date = (
			SELECT MAX(trade_date) FROM time_machine_positions WHERE run_id = ?
		)
		ORDER BY market_value DESC`, runID, runID)
	if err != nil {
		return TimeMachineDetail{}, err
	}
	defer positionRows.Close()
	for positionRows.Next() {
		var row PositionRow
		if err := positionRows.Scan(&row.Date, &row.TSCode, &row.Name, &row.Shares, &row.AvgCost, &row.Price, &row.MarketValue, &row.UnrealizedPnL, &row.UnrealizedPct, &row.TodayPnL, &row.TodayPct, &row.Weight, &row.HoldDays); err != nil {
			return TimeMachineDetail{}, err
		}
		detail.Positions = append(detail.Positions, row)
	}
	return detail, positionRows.Err()
}
