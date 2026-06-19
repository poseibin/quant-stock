package position

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"quant_stock_desktop/internal/common/database"
	"quant_stock_desktop/internal/features/market"
)

const initialCash = 500000.0
const lotSize = 100

type Service struct {
	marketService *market.Service
	db            *database.DB
	dbBackend     string
	dbDSN         string
}

func NewService(marketService *market.Service, db *database.DB) *Service {
	return &Service{marketService: marketService, db: db}
}

func (service *Service) SetRuntimeDatabaseConfig(backend string, dsn string) {
	service.dbBackend = strings.TrimSpace(backend)
	service.dbDSN = strings.TrimSpace(dsn)
}

func normalizeTradeDate(value string) string {
	text := strings.TrimSpace(value)
	if text == "" {
		return ""
	}
	text = strings.ReplaceAll(text, "-", "")
	if len(text) > 8 {
		return text[:8]
	}
	return text
}

func (service *Service) GetSummary(dataPath string) (Summary, error) {
	if service.db == nil {
		return Summary{}, errors.New("database is not initialized")
	}
	row := service.db.Conn().QueryRow(`SELECT initial_cash, current_cash, market_value, total_assets,
	    COALESCE(total_cost,0), COALESCE(total_fee,0), total_pnl, today_pnl, COALESCE(today_pct,0),
	    COALESCE(unrealized_pnl,0), COALESCE(unrealized_pct,0),
	    COALESCE(realized_pnl,0), COALESCE(cum_return,0), COALESCE(n_closed,0),
	    COALESCE(updated_at,'') FROM portfolio_pool_summary WHERE id = 1`)
	var s Summary
	if err := row.Scan(&s.InitialCash, &s.Cash, &s.MarketValue, &s.TotalAssets,
		&s.TotalCost, &s.TotalFee, &s.TotalPnL, &s.TodayPnL, &s.TodayPct,
		&s.UnrealizedPnL, &s.UnrealizedPct, &s.RealizedPnL, &s.CumReturn, &s.NClosed,
		&s.UpdatedAt); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return Summary{InitialCash: initialCash, Cash: initialCash, TotalAssets: initialCash, Positions: []Position{}}, nil
		}
		return Summary{}, err
	}
	positions, err := service.GetHoldings()
	if err != nil {
		return Summary{}, err
	}
	trades, err := service.GetTrades(80)
	if err != nil {
		return Summary{}, err
	}
	s.Positions = positions
	s.Trades = trades
	s.NHoldings = len(positions)
	return s, nil
}

func (service *Service) GetTrades(limit int) ([]TradeRecord, error) {
	if service.db == nil {
		return nil, errors.New("database is not initialized")
	}
	if limit <= 0 || limit > 500 {
		limit = 80
	}
	rows, err := service.db.Conn().Query(`SELECT t.id, t.ts_code, COALESCE(h.name, s.name, ''), t.side, t.shares, t.price, t.amount,
	    t.trade_date, COALESCE(t.pnl,0), COALESCE(t.fee,0), COALESCE(t.net_amount,0),
	    COALESCE(t.cash_after,0), COALESCE(t.position_pnl,0), COALESCE(t.exit_reason,'')
	    FROM portfolio_pool_trades t
	    LEFT JOIN portfolio_pool_holdings h ON h.ts_code = t.ts_code
	    LEFT JOIN data_stock_basic s ON s.ts_code = t.ts_code
	    ORDER BY t.id DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]TradeRecord, 0)
	for rows.Next() {
		var item TradeRecord
		if err := rows.Scan(&item.ID, &item.TSCode, &item.Name, &item.Action, &item.Shares, &item.Price, &item.Amount,
			&item.Date, &item.RealizedPnL, &item.Fee, &item.NetAmount, &item.CashAfter, &item.PositionPnL, &item.ExitReason); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (service *Service) GetHoldings() ([]Position, error) {
	if service.db == nil {
		return nil, errors.New("database is not initialized")
	}
	rows, err := service.db.Conn().Query(`SELECT ts_code, COALESCE(name,''), COALESCE(industry,''),
	    shares, avg_cost, last_price, market_value, weight, pnl, pnl_pct,
	    COALESCE(open_date,''), COALESCE(updated_at,'')
	    FROM portfolio_pool_holdings WHERE shares > 0 ORDER BY weight DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]Position, 0)
	for rows.Next() {
		var p Position
		if err := rows.Scan(&p.TSCode, &p.Name, &p.Industry, &p.Shares, &p.AvgCost,
			&p.Price, &p.MarketValue, &p.Weight, &p.UnrealizedPnL, &p.UnrealizedPct,
			&p.FirstEntryDate, &p.LastActionDate); err != nil {
			return nil, err
		}
		p.Cost = p.AvgCost * float64(p.Shares)
		out = append(out, p)
	}
	return out, rows.Err()
}

func (service *Service) RefreshValuationWithPrices(prices map[string]float64, valuationDate string) (Summary, error) {
	if service.db == nil {
		return Summary{}, errors.New("database is not initialized")
	}
	positions, err := service.GetHoldings()
	if err != nil {
		return Summary{}, err
	}
	if len(positions) == 0 {
		return service.GetSummary("")
	}
	valuationDate = normalizeTradeDate(valuationDate)
	if valuationDate == "" {
		valuationDate = time.Now().Format("20060102")
	}
	now := time.Now().Format(time.RFC3339)
	tx, err := service.db.Conn().Begin()
	if err != nil {
		return Summary{}, err
	}
	defer tx.Rollback()

	var currentCash, initialCash float64
	if err := tx.QueryRow(`SELECT current_cash, initial_cash FROM portfolio_pool_summary WHERE id = 1`).Scan(&currentCash, &initialCash); err != nil {
		return Summary{}, err
	}

	preClose := map[string]float64{}
	for _, p := range positions {
		var tradeDate string
		var closeValue, preCloseValue float64
		err := tx.QueryRow(`
			SELECT trade_date, COALESCE(close,0), COALESCE(pre_close,0)
			FROM data_daily_bars
			WHERE ts_code = ?
			ORDER BY trade_date DESC
			LIMIT 1`, p.TSCode).Scan(&tradeDate, &closeValue, &preCloseValue)
		if err == nil {
			if normalizeTradeDate(tradeDate) == valuationDate && preCloseValue > 0 {
				preClose[p.TSCode] = preCloseValue
			} else if closeValue > 0 {
				preClose[p.TSCode] = closeValue
			}
		}
	}

	todayBuyShares := map[string]float64{}
	todayBuyAmount := map[string]float64{}
	rows, err := tx.Query(`
		SELECT ts_code, COALESCE(SUM(shares),0), COALESCE(SUM(amount),0)
		FROM portfolio_pool_trades
		WHERE side = 'buy' AND REPLACE(trade_date, '-', '') = ?
		GROUP BY ts_code`, valuationDate)
	if err != nil {
		return Summary{}, err
	}
	for rows.Next() {
		var tsCode string
		var shares, amount float64
		if err := rows.Scan(&tsCode, &shares, &amount); err != nil {
			rows.Close()
			return Summary{}, err
		}
		todayBuyShares[tsCode] = shares
		todayBuyAmount[tsCode] = amount
	}
	if err := rows.Err(); err != nil {
		rows.Close()
		return Summary{}, err
	}
	rows.Close()

	totalMarketValue := 0.0
	totalTodayPnL := 0.0
	totalUnrealizedPnL := 0.0
	totalCost := 0.0
	for _, p := range positions {
		price := p.Price
		if nextPrice := prices[p.TSCode]; nextPrice > 0 {
			price = nextPrice
		}
		if price <= 0 {
			price = p.AvgCost
		}
		shares := float64(p.Shares)
		marketValue := price * shares
		cost := p.AvgCost * shares
		pnl := marketValue - cost
		pnlPct := 0.0
		if p.AvgCost > 0 {
			pnlPct = (price/p.AvgCost - 1) * 100
		}
		todayShares := math.Min(shares, todayBuyShares[p.TSCode])
		overnightShares := math.Max(0, shares-todayShares)
		todayPnL := 0.0
		if overnightShares > 0 && preClose[p.TSCode] > 0 {
			todayPnL += (price - preClose[p.TSCode]) * overnightShares
		}
		if todayShares > 0 {
			todayAvg := p.AvgCost
			if todayBuyAmount[p.TSCode] > 0 {
				todayAvg = todayBuyAmount[p.TSCode] / todayShares
			}
			todayPnL += (price - todayAvg) * todayShares
		}
		if _, err := tx.Exec(`
			UPDATE portfolio_pool_holdings
			SET last_price = ?, market_value = ?, pnl = ?, pnl_pct = ?, updated_at = ?
			WHERE ts_code = ?`, price, marketValue, pnl, pnlPct, now, p.TSCode); err != nil {
			return Summary{}, err
		}
		totalMarketValue += marketValue
		totalTodayPnL += todayPnL
		totalUnrealizedPnL += pnl
		totalCost += cost
	}
	totalAssets := currentCash + totalMarketValue
	if totalAssets > 0 {
		if _, err := tx.Exec(`UPDATE portfolio_pool_holdings SET weight = market_value / ? WHERE shares > 0`, totalAssets); err != nil {
			return Summary{}, err
		}
	}
	var realizedTotal float64
	if err := tx.QueryRow(`SELECT COALESCE(SUM(pnl),0) FROM portfolio_pool_trades WHERE side = 'sell'`).Scan(&realizedTotal); err != nil {
		return Summary{}, err
	}
	var nClosed int
	if err := tx.QueryRow(`SELECT COUNT(DISTINCT ts_code) FROM portfolio_pool_trades WHERE side = 'sell'`).Scan(&nClosed); err != nil {
		return Summary{}, err
	}
	unrealizedPct := 0.0
	if totalCost > 0 {
		unrealizedPct = totalUnrealizedPnL / totalCost
	}
	todayBase := totalMarketValue - totalTodayPnL
	todayPct := 0.0
	if todayBase > 0 {
		todayPct = totalTodayPnL / todayBase
	}
	totalPnL := realizedTotal + totalUnrealizedPnL
	cumReturn := 0.0
	if initialCash > 0 {
		cumReturn = totalPnL / initialCash
	}
	if _, err := tx.Exec(`
		UPDATE portfolio_pool_summary
		SET market_value = ?, total_assets = ?, total_cost = ?,
		    today_pnl = ?, today_pct = ?, unrealized_pnl = ?, unrealized_pct = ?,
		    realized_pnl = ?, total_pnl = ?, cum_return = ?, n_closed = ?, updated_at = ?
		WHERE id = 1`,
		totalMarketValue, totalAssets, totalCost,
		totalTodayPnL, todayPct, totalUnrealizedPnL, unrealizedPct,
		realizedTotal, totalPnL, cumReturn, nClosed, now,
	); err != nil {
		return Summary{}, err
	}
	if err := tx.Commit(); err != nil {
		return Summary{}, err
	}
	return service.GetSummary("")
}

func (service *Service) ConfirmTrades(dataPath string, trades []TradeRequest) (Summary, error) {
	if len(trades) == 0 {
		return service.GetSummary(dataPath)
	}
	tradeData := make([]map[string]any, 0, len(trades))
	for _, t := range trades {
		side := strings.ToLower(strings.TrimSpace(t.Action))
		if side != "buy" && side != "sell" {
			return Summary{}, fmt.Errorf("invalid trade action: %s", t.Action)
		}
		tradeData = append(tradeData, map[string]any{
			"ts_code":     t.TSCode,
			"side":        side,
			"shares":      t.Shares,
			"price":       t.Price,
			"trade_date":  t.Date,
			"exit_reason": t.ExitReason,
			"exit_pct":    t.ExitPct,
		})
	}
	tmpFile, err := os.CreateTemp("", "trades-*.json")
	if err != nil {
		return Summary{}, err
	}
	defer os.Remove(tmpFile.Name())
	if err := json.NewEncoder(tmpFile).Encode(tradeData); err != nil {
		tmpFile.Close()
		return Summary{}, err
	}
	tmpFile.Close()

	projectRoot := quantStockRoot(dataPath)
	scriptPath := filepath.Join(projectRoot, "scripts", "pool_confirm.py")
	python := quantCorePython(projectRoot)
	cmd := exec.Command(python, "-u", scriptPath, "--trades-json", tmpFile.Name())
	cmd.Dir = projectRoot
	cmd.Env = service.quantCoreEnv(dataPath)
	var stdout, stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return Summary{}, fmt.Errorf("pool_confirm failed: %v stderr=%s", err, stderr.String())
	}
	return service.GetSummary(dataPath)
}

func (service *Service) ClearPool(dataPath string, initialCashValue float64) (Summary, error) {
	if service.db == nil {
		return Summary{}, errors.New("database is not initialized")
	}
	if initialCashValue <= 0 {
		initialCashValue = initialCash
	}
	now := time.Now().Format(time.RFC3339)
	tx, err := service.db.Conn().Begin()
	if err != nil {
		return Summary{}, err
	}
	defer tx.Rollback()
	if _, err := tx.Exec(`DELETE FROM portfolio_pool_holdings`); err != nil {
		return Summary{}, err
	}
	if _, err := tx.Exec(`DELETE FROM portfolio_pool_trades`); err != nil {
		return Summary{}, err
	}
	if _, err := tx.Exec(`DELETE FROM rec_daily_recommendations`); err != nil {
		return Summary{}, err
	}
	if _, err := tx.Exec(
		service.db.UpsertSQL(
			"portfolio_pool_summary",
			[]string{
				"id", "initial_cash", "current_cash", "market_value", "total_assets", "total_cost", "total_fee",
				"total_pnl", "today_pnl", "today_pct", "unrealized_pnl", "unrealized_pct", "realized_pnl",
				"cum_return", "n_closed", "updated_at",
			},
			[]string{"id"},
			[]string{
				"initial_cash", "current_cash", "market_value", "total_assets", "total_cost", "total_fee",
				"total_pnl", "today_pnl", "today_pct", "unrealized_pnl", "unrealized_pct", "realized_pnl",
				"cum_return", "n_closed", "updated_at",
			},
		),
		1, initialCashValue, initialCashValue, 0, initialCashValue, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, now,
	); err != nil {
		return Summary{}, err
	}
	if err := tx.Commit(); err != nil {
		return Summary{}, err
	}
	legacyPoolPath := filepath.Join(dataPath, "positions", "pool.json")
	if err := os.Remove(legacyPoolPath); err != nil && !errors.Is(err, os.ErrNotExist) {
		return Summary{}, err
	}
	return service.GetSummary(dataPath)
}

func (service *Service) GetRecommendation(dataPath string) (Recommendation, error) {
	if service.db == nil {
		return Recommendation{}, errors.New("database is not initialized")
	}
	row := service.db.Conn().QueryRow(`SELECT payload_json FROM rec_daily_recommendations ORDER BY date DESC LIMIT 1`)
	var payload string
	if err := row.Scan(&payload); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return Recommendation{
				Date:                   "",
				GeneratedAt:            "",
				Rows:                   []RecommendationItem{},
				ActiveStrategyVersions: service.activeStrategyVersions(),
			}, nil
		}
		return Recommendation{}, err
	}
	var rec Recommendation
	if err := json.Unmarshal([]byte(payload), &rec); err != nil {
		return Recommendation{}, err
	}
	rec.ActiveStrategyVersions = filterProfitArenaStrategyVersions(rec.ActiveStrategyVersions)
	if len(rec.ActiveStrategyVersions) == 0 {
		rec.ActiveStrategyVersions = service.activeStrategyVersions()
	}
	if rec.Date != "" {
		var count int
		err := service.db.Conn().QueryRow(`SELECT COUNT(*) FROM portfolio_pool_trades WHERE trade_date = ?`, rec.Date).Scan(&count)
		if err != nil {
			return Recommendation{}, err
		}
		rec.Rebalanced = count > 0
		rec.RebalanceTrades = count
	}
	return rec, nil
}

func filterProfitArenaStrategyVersions(items []RecommendationStrategyVersion) []RecommendationStrategyVersion {
	out := make([]RecommendationStrategyVersion, 0, len(items))
	for _, item := range items {
		strategy := strings.TrimSpace(item.Strategy)
		if strategy != "profit_arena_model" && strategy != "profit_arena" {
			continue
		}
		if item.Label == "" {
			item.Label = "收益擂台"
		}
		out = append(out, item)
	}
	return out
}

func (service *Service) activeStrategyVersions() []RecommendationStrategyVersion {
	if service.db == nil {
		return nil
	}
	rows, err := service.db.Conn().Query(`SELECT strategy, version, label, config_json
		FROM strategy_config_versions
		WHERE is_active = 1 AND strategy IN ('profit_arena_model', 'profit_arena')
		ORDER BY strategy`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	out := []RecommendationStrategyVersion{}
	for rows.Next() {
		var item RecommendationStrategyVersion
		var configJSON string
		if err := rows.Scan(&item.Strategy, &item.Version, &item.Label, &configJSON); err != nil {
			continue
		}
		var cfg struct {
			Weight float64 `json:"weight"`
			Label  string  `json:"label"`
		}
		_ = json.Unmarshal([]byte(configJSON), &cfg)
		if item.Label == "" {
			item.Label = cfg.Label
		}
		if item.Label == "" {
			item.Label = "收益擂台"
		}
		item.Weight = cfg.Weight
		item.Mode = "active"
		out = append(out, item)
	}
	return out
}

func (service *Service) GetRunStatus(task string) (RunStatus, error) {
	if service.db == nil {
		return RunStatus{Task: task, State: "idle"}, nil
	}
	row := service.db.Conn().QueryRow(
		`SELECT task, COALESCE(task_type,''), state, idx, total, COALESCE(stage,''), COALESCE(name,''), COALESCE(message,''),
		COALESCE(worker_pid,0), COALESCE(started_at,''), updated_at, COALESCE(finished_at,'') FROM task_run_status WHERE task = ?`,
		task,
	)
	var s RunStatus
	if err := row.Scan(&s.Task, &s.TaskType, &s.State, &s.Idx, &s.Total, &s.Stage, &s.Name, &s.Message, &s.WorkerPID, &s.StartedAt, &s.UpdatedAt, &s.FinishedAt); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return RunStatus{Task: task, TaskType: inferRunStatusTaskType(task), State: "idle"}, nil
		}
		return RunStatus{}, err
	}
	if task == "profit_arena_rebalance" {
		s.Task = "profit_arena_rebalance"
		s.TaskType = "profit_arena_rebalance"
	}
	if s.TaskType == "" {
		s.TaskType = inferRunStatusTaskType(task)
	}
	return s, nil
}

func inferRunStatusTaskType(task string) string {
	switch task {
	case "data_update":
		return "data_update"
	case "profit_arena_rebalance":
		return "profit_arena_rebalance"
	case "profit_arena_model":
		return "model_training"
	case "factor_snapshot":
		return "factor_snapshot"
	default:
		return "python"
	}
}

func (service *Service) quantCoreEnv(dataPath string) []string {
	backend := service.dbBackend
	if backend == "" && service.db != nil {
		backend = string(service.db.Backend())
	}
	if backend == "" {
		backend = "mysql"
	}
	env := []string{
		"DATA_ROOT=" + dataPath,
		"DESKTOP_DB_BACKEND=" + backend,
		fmt.Sprintf("INITIAL_CASH=%.2f", initialCash),
		"REBALANCE_FREQ=5",
	}
	if service.dbDSN != "" {
		env = append(env, "DESKTOP_DB_DSN="+service.dbDSN)
	}
	return env
}

func quantStockRoot(dataPath string) string {
	parent := filepath.Dir(dataPath)
	grandparent := filepath.Dir(parent)
	candidates := []string{
		filepath.Join(parent, "quant_stock_core"),
		filepath.Join(grandparent, "quant_stock_core"),
		filepath.Join(parent, "quant_core"),
	}
	for _, candidate := range candidates {
		if info, err := os.Stat(filepath.Join(candidate, "scripts", "pool_confirm.py")); err == nil && !info.IsDir() {
			return candidate
		}
	}
	return ""
}

func quantCorePython(projectRoot string) string {
	if w := bundledWorkerPath(); w != "" {
		return w
	}
	parent := filepath.Dir(projectRoot) // .../lh
	candidates := []string{
		filepath.Join(projectRoot, ".venv", "bin", "python"),
		filepath.Join(parent, ".venv", "bin", "python"),
	}
	for _, candidate := range candidates {
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate
		}
	}
	return "python3"
}

func bundledWorkerPath() string {
	exe, err := os.Executable()
	if err != nil {
		return ""
	}
	exe, err = filepath.EvalSymlinks(exe)
	if err != nil {
		return ""
	}
	macosDir := filepath.Dir(exe)
	contentsDir := filepath.Dir(macosDir)
	candidate := filepath.Join(contentsDir, "Resources", "quant_worker", "quant_worker")
	if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
		return candidate
	}
	return ""
}


func headString(value string, limit int) string {
	if len(value) <= limit {
		return value
	}
	return value[:limit]
}

func tailString(value string, limit int) string {
	if len(value) <= limit {
		return value
	}
	return value[len(value)-limit:]
}
