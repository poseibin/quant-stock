package main

import (
	"bufio"
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"

	"quant_stock_desktop/internal/common/config"
	"quant_stock_desktop/internal/common/database"
	"quant_stock_desktop/internal/features/datafetch"
	"quant_stock_desktop/internal/features/market"
	"quant_stock_desktop/internal/features/position"
	"quant_stock_desktop/internal/runtime/result"
	"quant_stock_desktop/internal/runtime/task"
	"quant_stock_desktop/internal/runtime/worker"
)

type App struct {
	ctx              context.Context
	configService    *config.Service
	settings         config.Settings
	database         *database.DB
	taskService      *task.Service
	marketService    *market.Service
	positionService  *position.Service
	datafetchService *datafetch.Service
}

func NewApp() *App {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		homeDir = mustGetwd()
	}
	defaultSettings := config.DefaultSettings(homeDir)
	configService := config.NewService()
	settings, _ := configService.Load(defaultSettings)

	return &App{
		configService: configService,
		settings:      settings,
	}
}

func (app *App) startup(ctx context.Context) {
	app.ctx = ctx
	_ = app.ensureDatabase()
	if settings, err := app.configService.Load(app.settings); err == nil {
		app.settings = settings
	}
}

func (app *App) shutdown(ctx context.Context) {
	_ = app.database.Close()
}

type AppInfo struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

type SettingsResponse struct {
	Settings config.Settings          `json:"settings"`
	Issues   []config.ValidationIssue `json:"issues"`
}

type ApplyPortfolioCandidateRequest struct {
	RunID       string `json:"run_id"`
	CandidateID string `json:"candidate_id"`
}

func (app *App) GetAppInfo() AppInfo {
	return AppInfo{
		Name:    "Quant Stock Desktop",
		Version: "0.1.0",
	}
}

func (app *App) GetSettings() SettingsResponse {
	if app.database != nil {
		app.configService.WithDB(app.database.Conn())
	}
	settings, err := app.configService.Load(app.settings)
	if err == nil {
		app.settings = settings
	}
	return SettingsResponse{
		Settings: app.settings,
		Issues:   app.configService.Validate(app.settings),
	}
}

func (app *App) SaveSettings(settings config.Settings) SettingsResponse {
	if strings.TrimSpace(settings.DataPath) == "" {
		if homeDir, err := os.UserHomeDir(); err == nil {
			settings.DataPath = config.DefaultSettings(homeDir).DataPath
		} else {
			settings.DataPath = app.settings.DataPath
		}
	}
	issues := app.configService.Validate(settings)
	if len(issues) > 0 {
		return SettingsResponse{
			Settings: settings,
			Issues:   issues,
		}
	}
	previousDataPath := app.settings.DataPath
	app.settings = settings
	if settings.DataPath != previousDataPath {
		_ = app.reopenDatabase()
	} else {
		_ = app.ensureDatabase()
	}
	if app.database != nil {
		app.configService.WithDB(app.database.Conn())
	}
	if err := app.configService.Save(settings); err == nil {
		app.settings = settings
	}
	if app.datafetchService != nil {
		app.datafetchService.SetDataPath(app.settings.DataPath)
	}
	return SettingsResponse{
		Settings: app.settings,
		Issues:   app.configService.Validate(app.settings),
	}
}

func (app *App) ApplyPortfolioCandidate(req ApplyPortfolioCandidateRequest) (SettingsResponse, error) {
	if err := app.ensureDatabase(); err != nil {
		return SettingsResponse{}, err
	}
	runID := strings.TrimSpace(req.RunID)
	candidateID := strings.TrimSpace(req.CandidateID)
	if runID == "" || candidateID == "" {
		return SettingsResponse{}, errors.New("run_id and candidate_id are required")
	}
	var weightsJSON string
	row := app.database.Conn().QueryRow(
		`SELECT weights_json FROM portfolio_optimization_candidates WHERE run_id = ? AND candidate_id = ?`,
		runID,
		candidateID,
	)
	if err := row.Scan(&weightsJSON); err != nil {
		return SettingsResponse{}, err
	}
	var weights map[string]float64
	if err := json.Unmarshal([]byte(weightsJSON), &weights); err != nil {
		return SettingsResponse{}, err
	}
	if len(weights) == 0 {
		return SettingsResponse{}, errors.New("candidate has no strategy weights")
	}
	if app.database != nil {
		app.configService.WithDB(app.database.Conn())
	}
	settings, err := app.configService.Load(app.settings)
	if err != nil {
		return SettingsResponse{}, err
	}
	total := 0.0
	for _, weight := range weights {
		if weight > 0 {
			total += weight
		}
	}
	if total <= 0 {
		return SettingsResponse{}, errors.New("candidate weights are invalid")
	}
	for name, strategy := range settings.Strategies {
		weight, ok := weights[name]
		if ok && weight > 0 {
			strategy.Enabled = true
			strategy.Weight = weight / total
		} else {
			strategy.Enabled = false
			strategy.Weight = 0
		}
		settings.Strategies[name] = strategy
	}
	if err := app.configService.Save(settings); err != nil {
		return SettingsResponse{}, err
	}
	app.settings = settings
	return SettingsResponse{
		Settings: app.settings,
		Issues:   app.configService.Validate(app.settings),
	}, nil
}

func (app *App) ScanMarketDataFiles() ([]market.DataFileDTO, error) {
	if err := app.ensureMarketService(); err != nil {
		return nil, err
	}
	return app.marketService.Scan(app.settings.DataPath)
}

func (app *App) ListMarketDataFiles() ([]market.DataFileDTO, error) {
	if err := app.ensureMarketService(); err != nil {
		return nil, err
	}
	return app.marketService.List()
}

func (app *App) ListStockBasic(query market.StockBasicQuery) ([]market.StockBasic, error) {
	if err := app.ensureMarketService(); err != nil {
		return nil, err
	}
	return app.marketService.ListStockBasic(app.settings.DataPath, query)
}

func (app *App) ListDailyBars(query market.DailyQuery) ([]market.DailyBar, error) {
	if err := app.ensureMarketService(); err != nil {
		return nil, err
	}
	return app.marketService.ListDailyBars(app.settings.DataPath, query)
}

func (app *App) ListFinancialIndicators(query market.FinancialQuery) ([]market.FinancialIndicator, error) {
	if err := app.ensureMarketService(); err != nil {
		return nil, err
	}
	return app.marketService.ListFinancialIndicators(app.settings.DataPath, query)
}

func (app *App) GetStockValuation(query market.ValuationQuery) (market.StockValuation, error) {
	if err := app.ensureMarketService(); err != nil {
		return market.StockValuation{}, err
	}
	return app.marketService.GetStockValuation(app.settings.DataPath, query)
}

func (app *App) ListLimitBreakoutCandidates(query market.BreakoutQuery) ([]market.LimitBreakoutCandidate, error) {
	if err := app.ensureMarketService(); err != nil {
		return nil, err
	}
	return app.marketService.ListLimitBreakoutCandidates(app.settings.DataPath, query)
}

func (app *App) RefreshLimitBreakoutCandidates(query market.BreakoutQuery) ([]market.LimitBreakoutCandidate, error) {
	if err := app.ensureMarketService(); err != nil {
		return nil, err
	}
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return nil, errors.New("数据路径未设置")
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	dbPath := filepath.Join(dataPath, "meta.db")
	logDir := filepath.Join(dataPath, "logs", "limit_breakout")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return nil, err
	}
	logPath := filepath.Join(logDir, time.Now().Format("20060102_150405")+".log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return nil, err
	}
	defer logFile.Close()
	query = market.NormalizeBreakoutQuery(query)
	scanLimit := query.Limit
	if scanLimit < 100 {
		scanLimit = 100
	}
	args := []string{
		"scripts/limit_breakout_worker.py",
		"--data-path", dataPath,
		"--db-path", dbPath,
		"--cache-key", market.BreakoutCacheKey(query),
		"--limit", strconv.Itoa(scanLimit),
		"--lookback", strconv.Itoa(query.Lookback),
		"--recent-days", strconv.Itoa(query.RecentDays),
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(),
		"DATA_ROOT="+dataPath,
		"DESKTOP_DB_PATH="+dbPath,
		"DESKTOP_CONFIG_DB_PATH="+dbPath,
	)
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("涨停预警扫描失败: %w，请查看日志 %s", err, logPath)
	}
	return app.marketService.ListLimitBreakoutCandidates(dataPath, query)
}

func (app *App) ListLimitUpMomentumCandidates(query market.LimitUpMomentumQuery) ([]market.LimitUpMomentumCandidate, error) {
	if err := app.ensureMarketService(); err != nil {
		return nil, err
	}
	return app.marketService.ListLimitUpMomentumCandidates(app.settings.DataPath, query)
}

func (app *App) RefreshLimitUpMomentumCandidates(query market.LimitUpMomentumQuery) ([]market.LimitUpMomentumCandidate, error) {
	if err := app.ensureMarketService(); err != nil {
		return nil, err
	}
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return nil, errors.New("数据路径未设置")
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	dbPath := filepath.Join(dataPath, "meta.db")
	logDir := filepath.Join(dataPath, "logs", "limit_up_momentum")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return nil, err
	}
	logPath := filepath.Join(logDir, time.Now().Format("20060102_150405")+".log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return nil, err
	}
	defer logFile.Close()
	query = market.NormalizeLimitUpMomentumQuery(query)
	scanLimit := query.Limit
	if scanLimit < 100 {
		scanLimit = 100
	}
	args := []string{
		"scripts/limit_up_momentum_worker.py",
		"--data-path", dataPath,
		"--db-path", dbPath,
		"--cache-key", market.LimitUpMomentumCacheKey(query),
		"--limit", strconv.Itoa(scanLimit),
		"--lookback", strconv.Itoa(query.Lookback),
		"--history-days", strconv.Itoa(query.HistoryDays),
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(),
		"DATA_ROOT="+dataPath,
		"DESKTOP_DB_PATH="+dbPath,
		"DESKTOP_CONFIG_DB_PATH="+dbPath,
	)
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("涨停板推荐扫描失败: %w，请查看日志 %s", err, logPath)
	}
	return app.marketService.ListLimitUpMomentumCandidates(dataPath, query)
}

func (app *App) GetPositionSummary() (position.Summary, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.Summary{}, err
	}
	return app.positionService.GetSummary(app.settings.DataPath)
}

func (app *App) GetPositionHistory() ([]position.HistoryPoint, error) {
	if err := app.ensurePositionService(); err != nil {
		return nil, err
	}
	return app.positionService.GetHistory(app.settings.DataPath)
}

func (app *App) GetPositionHoldings() ([]position.Position, error) {
	if err := app.ensurePositionService(); err != nil {
		return nil, err
	}
	return app.positionService.GetHoldings()
}

func (app *App) ConfirmPositionTrades(trades []position.TradeRequest) (position.Summary, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.Summary{}, err
	}
	return app.positionService.ConfirmTrades(app.settings.DataPath, trades)
}

func (app *App) GetPositionRecommendation() (position.Recommendation, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.Recommendation{}, err
	}
	recommendation, err := app.positionService.GetRecommendation(app.settings.DataPath)
	if err == nil {
		return recommendation, nil
	}
	go app.runPositionSignalTask(position.GenerateSignalRequest{InitialCash: app.settings.DefaultInitialCash, RebalanceFreq: app.settings.DefaultRebalanceFreq})
	return position.Recommendation{}, err
}

func (app *App) GeneratePositionSignal(req position.GenerateSignalRequest) (position.GenerateSignalResponse, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.GenerateSignalResponse{}, err
	}
	if req.InitialCash <= 0 {
		req.InitialCash = app.settings.DefaultInitialCash
	}
	if req.RebalanceFreq <= 0 {
		req.RebalanceFreq = app.settings.DefaultRebalanceFreq
	}
	go app.runPositionSignalTask(req)
	return position.GenerateSignalResponse{Success: true}, nil
}

func (app *App) runPositionSignalTask(req position.GenerateSignalRequest) {
	if app.database == nil || app.positionService == nil {
		return
	}
	repo := task.NewRepository(app.database.Conn())
	now := time.Now()
	t := task.Task{
		ID:         task.NewID(),
		Name:       "当日信号生成",
		TaskType:   task.TypeDailySignal,
		Status:     task.StatusRunning,
		Progress:   0,
		WorkerType: "python",
		CreatedAt:  now,
		StartedAt:  now,
		UpdatedAt:  now,
	}
	if err := repo.Create(t); err != nil {
		return
	}
	_, err := app.positionService.GenerateSignalWithProgress(app.settings.DataPath, req, func(ev position.ProgressEvent) {
		progress := 0.0
		if ev.Total > 0 {
			progress = float64(ev.Idx) / float64(ev.Total)
			if ev.Stage == "done" {
				progress = float64(ev.Idx+1) / float64(ev.Total)
			}
		}
		_ = repo.UpdateRuntime(task.Task{
			ID:        t.ID,
			Status:    task.StatusRunning,
			Progress:  progress,
			UpdatedAt: time.Now(),
		})
	})
	if err == nil {
		if _, recErr := app.positionService.GetRecommendation(app.settings.DataPath); recErr != nil {
			err = recErr
		}
	}
	finishedAt := time.Now()
	if err != nil {
		_ = repo.UpdateRuntime(task.Task{
			ID:           t.ID,
			Status:       task.StatusFailed,
			Progress:     1,
			ErrorMessage: err.Error(),
			StartedAt:    t.StartedAt,
			UpdatedAt:    finishedAt,
			FinishedAt:   finishedAt,
		})
		return
	}
	_ = repo.UpdateRuntime(task.Task{
		ID:         t.ID,
		Status:     task.StatusSuccess,
		Progress:   1,
		StartedAt:  t.StartedAt,
		UpdatedAt:  finishedAt,
		FinishedAt: finishedAt,
	})
}

func (app *App) GetSignalRunStatus() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	status, err := app.positionService.GetRunStatus("daily_signal")
	if err != nil || status.State == "running" {
		return status, err
	}
	if app.database != nil {
		latestTask, taskErr := latestRunningTask(app.database.Conn(), task.TypeDailySignal)
		if taskErr == nil {
			return latestTask, nil
		}
	}
	return status, err
}

func latestRunningTask(db *sql.DB, taskType task.Type) (position.RunStatus, error) {
	row := db.QueryRow(`SELECT name, progress, created_at, COALESCE(started_at,''), updated_at
		FROM evaluation_tasks
		WHERE task_type = ? AND status = 'running'
		ORDER BY created_at DESC LIMIT 1`, string(taskType))
	var name string
	var progress float64
	var createdAt string
	var startedAt string
	var updatedAt string
	if err := row.Scan(&name, &progress, &createdAt, &startedAt, &updatedAt); err != nil {
		return position.RunStatus{}, err
	}
	idx := int(progress * 100)
	return position.RunStatus{
		Task:      "daily_signal",
		State:     "running",
		Idx:       idx,
		Total:     100,
		Stage:     "running",
		Name:      name,
		StartedAt: firstNonEmpty(startedAt, createdAt),
		UpdatedAt: updatedAt,
	}, nil
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

func stringParam(params map[string]any, key string, fallback string) string {
	if value, ok := params[key].(string); ok && strings.TrimSpace(value) != "" {
		return strings.TrimSpace(value)
	}
	return fallback
}

func numberParam(params map[string]any, key string, fallback float64) float64 {
	switch value := params[key].(type) {
	case float64:
		return value
	case float32:
		return float64(value)
	case int:
		return float64(value)
	case int64:
		return float64(value)
	default:
		return fallback
	}
}

func strategyParam(value any) string {
	switch items := value.(type) {
	case []any:
		out := make([]string, 0, len(items))
		for _, item := range items {
			if text, ok := item.(string); ok && strings.TrimSpace(text) != "" {
				out = append(out, strings.TrimSpace(text))
			}
		}
		if len(out) > 0 {
			return strings.Join(out, ",")
		}
	case []string:
		if len(items) > 0 {
			return strings.Join(items, ",")
		}
	case string:
		if strings.TrimSpace(items) != "" {
			return strings.TrimSpace(items)
		}
	}
	return "all"
}

func trimFloat(value float64) string {
	data, _ := json.Marshal(value)
	return string(data)
}

func readStrategyEvaluationSummaryFromDB(db *sql.DB, runID string) string {
	rows, err := db.Query(`SELECT payload_json, start_date, end_date, benchmark, baseline
		FROM strategy_evaluation WHERE run_id = ? ORDER BY strategy`, runID)
	if err != nil {
		return ""
	}
	defer rows.Close()

	payload := map[string]any{
		"rows": []any{},
	}
	items := make([]any, 0)
	for rows.Next() {
		var payloadJSON string
		var startDate string
		var endDate string
		var benchmark string
		var baseline string
		if err := rows.Scan(&payloadJSON, &startDate, &endDate, &benchmark, &baseline); err != nil {
			return ""
		}
		var row map[string]any
		if err := json.Unmarshal([]byte(payloadJSON), &row); err != nil {
			continue
		}
		items = append(items, row)
		if payload["start"] == nil {
			payload["start"] = startDate
			payload["end"] = endDate
			payload["benchmark"] = benchmark
			payload["baseline"] = baseline
		}
	}
	if err := rows.Err(); err != nil || len(items) == 0 {
		return ""
	}
	payload["rows"] = items
	enrichStrategyEvaluationSummary(payload)
	summary, err := json.Marshal(payload)
	if err != nil {
		return ""
	}
	return string(summary)
}

func readStrategyEvaluationSummaryFromFile(resultPath string) string {
	data, err := os.ReadFile(filepath.Join(resultPath, "strategy_evaluation.json"))
	if err != nil {
		return ""
	}
	var payload map[string]any
	if err := json.Unmarshal(data, &payload); err != nil {
		return ""
	}
	enrichStrategyEvaluationSummary(payload)
	summary, err := json.Marshal(payload)
	if err != nil {
		return ""
	}
	return string(summary)
}

func readStrategyEvaluationRowSummaryFromDB(db *sql.DB, runID string, strategyName string) string {
	row := db.QueryRow(`SELECT payload_json FROM strategy_evaluation WHERE run_id = ? AND strategy = ?`, runID, strategyName)
	var payloadJSON string
	if err := row.Scan(&payloadJSON); err != nil {
		return ""
	}
	return payloadJSON
}

func enrichStrategyEvaluationSummary(payload map[string]any) {
	rows, _ := payload["rows"].([]any)
	success := 0
	empty := 0
	failed := 0
	admit := 0
	limited := 0
	watch := 0
	reject := 0
	for _, item := range rows {
		row, _ := item.(map[string]any)
		switch row["status"] {
		case "ok":
			success++
		case "empty":
			empty++
		default:
			failed++
		}
		switch row["admission"] {
		case "可启用":
			admit++
		case "限制启用":
			limited++
		case "继续观察":
			watch++
		case "暂不启用":
			reject++
		}
	}
	payload["strategy_count"] = len(rows)
	payload["success_count"] = success
	payload["empty_count"] = empty
	payload["failed_count"] = failed
	payload["admit_count"] = admit
	payload["limited_count"] = limited
	payload["watch_count"] = watch
	payload["reject_count"] = reject
}

func readPortfolioOptimizationSummaryFromDB(db *sql.DB, runID string) string {
	row := db.QueryRow(`SELECT summary_json FROM portfolio_optimization_runs WHERE run_id = ?`, runID)
	var summaryJSON string
	if err := row.Scan(&summaryJSON); err != nil {
		return ""
	}
	var payload map[string]any
	if err := json.Unmarshal([]byte(summaryJSON), &payload); err != nil {
		payload = map[string]any{}
	}
	rows, err := db.Query(`SELECT rank, score, annual_return, max_drawdown, sharpe, calmar, avg_turnover, avg_holdings, avg_total_mv, avg_amount, payload_json FROM portfolio_optimization_candidates
		WHERE run_id = ? ORDER BY CASE WHEN rank > 0 THEN 0 ELSE 1 END, rank, score DESC`, runID)
	if err != nil {
		return ""
	}
	defer rows.Close()
	topN := int(numberParam(payload, "top_n", 40))
	if topN <= 0 {
		topN = 40
	}
	items := make([]any, 0)
	finishedCount := 0
	for rows.Next() {
		var rank int
		var score float64
		var annualReturn, maxDrawdown, sharpe, calmar, avgTurnover, avgHoldings, avgTotalMV, avgAmount sql.NullFloat64
		var payloadJSON string
		if err := rows.Scan(&rank, &score, &annualReturn, &maxDrawdown, &sharpe, &calmar, &avgTurnover, &avgHoldings, &avgTotalMV, &avgAmount, &payloadJSON); err != nil {
			return ""
		}
		var item map[string]any
		if err := json.Unmarshal([]byte(payloadJSON), &item); err == nil {
			finishedCount++
			item["rank"] = rank
			item["score"] = score
			overlayNullableFloat(item, "annual_return", annualReturn)
			overlayNullableFloat(item, "max_drawdown", maxDrawdown)
			overlayNullableFloat(item, "sharpe", sharpe)
			overlayNullableFloat(item, "calmar", calmar)
			overlayNullableFloat(item, "avg_turnover", avgTurnover)
			overlayNullableFloat(item, "avg_holdings", avgHoldings)
			overlayNullableFloat(item, "avg_total_mv", avgTotalMV)
			overlayNullableFloat(item, "avg_amount", avgAmount)
			if len(items) < topN {
				items = append(items, item)
			}
		}
	}
	if err := rows.Err(); err != nil {
		return ""
	}
	payload["rows"] = items
	payload["finished_candidate_count"] = finishedCount
	if _, ok := payload["candidate_count"]; !ok {
		payload["candidate_count"] = len(items)
	}
	if len(items) > 0 {
		if top, ok := items[0].(map[string]any); ok {
			payload["best_name"] = top["name"]
			payload["best_score"] = top["score"]
			payload["best_annual_return"] = top["annual_return"]
			payload["best_max_drawdown"] = top["max_drawdown"]
		}
	}
	out, err := json.Marshal(payload)
	if err != nil {
		return ""
	}
	return string(out)
}

func (app *App) RunDataUpdate(req datafetch.UpdateRequest) error {
	if err := app.ensureDatafetchService(); err != nil {
		return err
	}
	if status, err := app.datafetchService.GetStatus(); err == nil {
		status, _ = app.reconcileDataUpdateStatus(status)
		if status.State == "running" {
			return datafetch.ErrAlreadyRunning
		}
	}
	token := strings.TrimSpace(app.settings.TushareToken)
	if token == "" {
		return errors.New("Tushare Token 未设置，请在设置页填写")
	}
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return errors.New("数据路径未设置")
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	dbPath := filepath.Join(dataPath, "meta.db")
	logDir := filepath.Join(dataPath, "logs", "data_update")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return err
	}
	logPath := filepath.Join(logDir, time.Now().Format("20060102_150405")+".log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	args := []string{
		"scripts/data_update_worker.py",
		"--phase", strings.TrimSpace(req.Phase),
		"--start-date", strings.TrimSpace(req.StartDate),
		"--dataset", strings.TrimSpace(req.Dataset),
		"--token", token,
		"--data-path", dataPath,
		"--db-path", dbPath,
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(),
		"DATA_ROOT="+dataPath,
		"DESKTOP_DB_PATH="+dbPath,
		"DESKTOP_CONFIG_DB_PATH="+dbPath,
		"TUSHARE_TOKEN="+token,
	)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		return err
	}
	go app.waitDataUpdate(cmd, logFile, logPath)
	return nil
}

func (app *App) GetDataUpdateStatus() (datafetch.RunStatus, error) {
	if err := app.ensureDatafetchService(); err != nil {
		return datafetch.RunStatus{}, err
	}
	status, err := app.datafetchService.GetStatus()
	if err != nil {
		return status, err
	}
	return app.reconcileDataUpdateStatus(status)
}

func (app *App) waitDataUpdate(cmd *exec.Cmd, logFile *os.File, logPath string) {
	err := cmd.Wait()
	_ = logFile.Close()
	if app.database == nil {
		return
	}
	status, statusErr := app.datafetchService.GetStatus()
	if statusErr != nil || status.State != "running" {
		return
	}
	if err != nil {
		app.markDataUpdateError("更新进程已退出: " + err.Error() + "，日志: " + logPath)
		return
	}
	app.markDataUpdateError("更新进程已退出但未写入完成状态，日志: " + logPath)
}

func (app *App) reconcileDataUpdateStatus(status datafetch.RunStatus) (datafetch.RunStatus, error) {
	if status.State != "running" {
		return status, nil
	}
	updatedAt, ok := parseRunStatusTime(status.UpdatedAt)
	if !ok || time.Since(updatedAt) <= 10*time.Minute {
		return status, nil
	}
	app.markDataUpdateError("更新进程超过 10 分钟没有进度，已自动标记为异常")
	return app.datafetchService.GetStatus()
}

func parseRunStatusTime(value string) (time.Time, bool) {
	value = strings.TrimSpace(value)
	if value == "" {
		return time.Time{}, false
	}
	layouts := []string{
		time.RFC3339,
		"2006-01-02T15:04:05",
		"2006-01-02 15:04:05",
	}
	for _, layout := range layouts {
		if t, err := time.Parse(layout, value); err == nil {
			return t, true
		}
		if t, err := time.ParseInLocation(layout, value, time.Local); err == nil {
			return t, true
		}
	}
	return time.Time{}, false
}

func (app *App) markDataUpdateError(message string) {
	if app.database == nil {
		return
	}
	now := time.Now().Format(time.RFC3339)
	db := app.database.Conn()
	_, _ = db.Exec(
		`UPDATE py_run_status
		 SET state='error', message=?, updated_at=?, finished_at=?
		 WHERE task='data_update' AND state='running'`,
		message, now, now,
	)
	_, _ = db.Exec(
		`UPDATE dataset_update_status
		 SET state='failed', message=?, error_message=?, finished_at=?, updated_at=?
		 WHERE state IN ('running','pending')`,
		message, message, now, now,
	)
}

func (app *App) ListDatasetUpdateStatus() ([]datafetch.DatasetStatus, error) {
	if err := app.ensureDatafetchService(); err != nil {
		return []datafetch.DatasetStatus{}, err
	}
	items, err := app.datafetchService.ListDatasetStatus()
	if items == nil {
		items = []datafetch.DatasetStatus{}
	}
	return items, err
}

// DataFetchJob 暴露给前端用来渲染数据集列表（无函数指针）。
type DataFetchJob struct {
	Name     string `json:"name"`
	Category string `json:"category"`
}

func (app *App) ListDataFetchJobs() []DataFetchJob {
	jobs := datafetch.AllJobs()
	out := make([]DataFetchJob, 0, len(jobs))
	for _, j := range jobs {
		out = append(out, DataFetchJob{Name: j.Name, Category: j.Category})
	}
	return out
}

func (app *App) ensureDatafetchService() error {
	if app.datafetchService != nil {
		return nil
	}
	if err := app.ensureDatabase(); err != nil {
		return err
	}
	var sqlDB *sql.DB
	if app.database != nil {
		sqlDB = app.database.Conn()
	}
	svc := datafetch.New(
		sqlDB,
		app.settings.DataPath,
		func() string { return app.settings.TushareToken },
	)
	svc.SetContext(app.ctx)
	app.datafetchService = svc
	return nil
}

func (app *App) PreviewDataset(query market.DatasetPreviewQuery) (market.DatasetPreview, error) {
	if err := app.ensureMarketService(); err != nil {
		return market.DatasetPreview{}, err
	}
	return app.marketService.PreviewDataset(app.settings.DataPath, query)
}

func (app *App) CreateTask(req task.CreateRequest) (task.DTO, error) {
	if err := app.ensureTaskService(); err != nil {
		return task.DTO{}, err
	}
	dto, err := app.taskService.Create(req)
	if err != nil {
		return task.DTO{}, err
	}
	if req.TaskType == task.TypePortfolioOptimization {
		parent, err := app.taskService.Repository().Get(dto.ID)
		if err != nil {
			return task.DTO{}, err
		}
		if err := app.initializePortfolioEvaluation(parent); err != nil {
			return task.DTO{}, err
		}
		parent, err = app.taskService.Repository().Get(dto.ID)
		if err != nil {
			return task.DTO{}, err
		}
		return task.ToDTO(parent), nil
	}
	if req.TaskType == task.TypeStrategyEvaluation {
		parent, err := app.taskService.Repository().Get(dto.ID)
		if err != nil {
			return task.DTO{}, err
		}
		if err := app.initializeStrategyEvaluation(parent); err != nil {
			return task.DTO{}, err
		}
		parent, err = app.taskService.Repository().Get(dto.ID)
		if err != nil {
			return task.DTO{}, err
		}
		return task.ToDTO(parent), nil
	}
	return dto, nil
}

func (app *App) initializeStrategyEvaluation(parent task.Task) error {
	if app.database == nil {
		if err := app.ensureDatabase(); err != nil {
			return err
		}
	}
	params := task.ToDTO(parent).Params
	startDate := stringParam(params, "start_date", "")
	endDate := stringParam(params, "end_date", "")
	if startDate == "" || endDate == "" {
		return errors.New("strategy evaluation requires start_date and end_date")
	}
	strategyNames := app.resolveStrategyAdmissionNames(params["strategies"])
	if len(strategyNames) == 0 {
		return errors.New("no strategy candidates generated")
	}
	children, err := app.taskService.Repository().ListChildren(parent.ID)
	if err != nil {
		return err
	}
	if len(children) > 0 {
		return nil
	}
	now := time.Now()
	runID := parent.ExternalRunID
	if runID == "" {
		runID = "se_" + strings.ReplaceAll(parent.ID, "-", "")
	}
	parent.ExternalRunID = runID
	parent.Total = len(strategyNames)
	parent.Progress = 0
	parent.ResultPath = filepath.Join(app.settings.DataPath, "backtest_results", runID)
	parent.SummaryJSON = mustJSON(map[string]any{
		"start":          startDate,
		"end":            endDate,
		"benchmark":      stringParam(params, "benchmark", "000905.SH"),
		"baseline":       stringParam(params, "baseline", "small_cap_quality"),
		"strategy_count": len(strategyNames),
		"planned_count":  len(strategyNames),
		"success_count":  0,
		"empty_count":    0,
		"failed_count":   0,
		"admit_count":    0,
		"limited_count":  0,
		"watch_count":    0,
		"reject_count":   0,
		"rows":           []any{},
	})
	parent.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(parent); err != nil {
		return err
	}
	if err := app.taskService.Repository().UpdateStatus(parent); err != nil {
		return err
	}
	for idx, strategyName := range strategyNames {
		childParams := map[string]any{
			"start_date": startDate,
			"end_date":   endDate,
			"strategies": strategyName,
			"strategy":   strategyName,
			"baseline":   stringParam(params, "baseline", "small_cap_quality"),
			"benchmark":  stringParam(params, "benchmark", "000905.SH"),
			"slippage":   numberParam(params, "slippage", 0.002),
		}
		paramsData, err := json.Marshal(childParams)
		if err != nil {
			return err
		}
		child := task.Task{
			ID:            task.NewID(),
			Name:          app.strategyDisplayName(strategyName),
			TaskType:      task.TypeStrategyEvaluation,
			Status:        task.StatusCreated,
			Progress:      0,
			ParamsJSON:    string(paramsData),
			WorkerType:    "python",
			ExternalRunID: runID,
			ParentID:      parent.ID,
			GroupRunID:    runID,
			SubtaskKey:    strategyName,
			SubtaskName:   app.strategyDisplayName(strategyName),
			Sequence:      idx + 1,
			Total:         len(strategyNames),
			MaxAttempts:   2,
			CreatedAt:     now.Add(time.Duration(idx) * time.Millisecond),
			UpdatedAt:     now,
		}
		if err := app.taskService.Repository().Create(child); err != nil {
			return err
		}
	}
	return nil
}

type portfolioCandidatePlan struct {
	ID               string             `json:"candidate_id"`
	Name             string             `json:"name"`
	Weights          map[string]float64 `json:"weights"`
	ExitArchitecture map[string]any     `json:"exit_architecture"`
	PositionRule     map[string]any     `json:"position_rule"`
	RebalanceFreq    int                `json:"rebalance_freq"`
	RiskRule         map[string]any     `json:"risk_rule"`
}

type portfolioBaseGroup struct {
	Name  string
	Items []portfolioCandidatePlan
}

var researchStrategyUniverse = []string{
	"market_regime_timing",
	"multi_factor_composite",
	"small_cap_quality",
	"trend_pullback",
	"dividend_quality",
	"earnings_revision",
	"industry_prosperity",
	"low_crowding_reversal",
	"event_enhanced",
	"beijing_satellite",
}

func (app *App) initializePortfolioEvaluation(parent task.Task) error {
	if app.database == nil {
		if err := app.ensureDatabase(); err != nil {
			return err
		}
	}
	params := task.ToDTO(parent).Params
	startDate := stringParam(params, "start_date", "")
	endDate := stringParam(params, "end_date", "")
	if startDate == "" || endDate == "" {
		return errors.New("portfolio evaluation requires start_date and end_date")
	}
	objective := stringParam(params, "objective", "平衡")
	benchmark := stringParam(params, "benchmark", "000905.SH")
	topN := int(numberParam(params, "top_n", 40))
	maxCandidates := int(numberParam(params, "max_candidates", 0))
	strategyNames := app.resolvePortfolioStrategyNames(params["strategies"])
	admissionFiltered := false
	if admittedNames, ok := app.admittedPortfolioStrategyNames(strategyNames); ok {
		strategyNames = admittedNames
		admissionFiltered = true
	}
	candidates := app.generatePortfolioCandidatesFromNames(strategyNames, objective, maxCandidates)
	if len(candidates) == 0 {
		return errors.New("no portfolio candidates generated")
	}

	now := time.Now()
	parent.Total = len(candidates)
	parent.Progress = 0
	parent.SummaryJSON = mustJSON(map[string]any{
		"start":           startDate,
		"end":             endDate,
		"objective":       objective,
		"benchmark":       benchmark,
		"strategy_count":  len(strategyNames),
		"candidate_count": len(candidates),
		"planned_count":   len(candidates),
		"completed_count": 0,
		"failed_count":    0,
		"top_n":           topN,
		"admission_used":  admissionFiltered,
		"rows":            []any{},
	})
	parent.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(parent); err != nil {
		return err
	}
	if err := app.taskService.Repository().UpdateStatus(parent); err != nil {
		return err
	}
	if err := app.writePortfolioRunPlan(parent.ExternalRunID, startDate, endDate, objective, benchmark, len(strategyNames), topN, candidates); err != nil {
		return err
	}

	for idx, candidate := range candidates {
		childParams := map[string]any{
			"start_date":        startDate,
			"end_date":          endDate,
			"candidate_id":      candidate.ID,
			"candidate_name":    candidate.Name,
			"weights":           candidate.Weights,
			"entry":             map[string]any{"type": "strategy_weight_mix", "weights": candidate.Weights},
			"exit_architecture": candidate.ExitArchitecture,
			"position_rule":     candidate.PositionRule,
			"rebalance_freq":    candidate.RebalanceFreq,
			"risk_rule":         candidate.RiskRule,
			"scheme":            candidate.toSchemePayload(),
			"objective":         objective,
			"benchmark":         benchmark,
			"slippage":          numberParam(params, "slippage", 0.002),
		}
		paramsData, err := json.Marshal(childParams)
		if err != nil {
			return err
		}
		child := task.Task{
			ID:            task.NewID(),
			Name:          candidate.Name,
			TaskType:      task.TypePortfolioOptimization,
			Status:        task.StatusCreated,
			Progress:      0,
			ParamsJSON:    string(paramsData),
			WorkerType:    "python",
			ExternalRunID: parent.ExternalRunID,
			ParentID:      parent.ID,
			GroupRunID:    parent.ExternalRunID,
			SubtaskKey:    candidate.ID,
			SubtaskName:   candidate.Name,
			Sequence:      idx + 1,
			Total:         len(candidates),
			MaxAttempts:   2,
			CreatedAt:     now.Add(time.Duration(idx) * time.Millisecond),
			UpdatedAt:     now,
		}
		if err := app.taskService.Repository().Create(child); err != nil {
			return err
		}
	}
	return nil
}

func (app *App) writePortfolioRunPlan(runID string, startDate string, endDate string, objective string, benchmark string, strategyCount int, topN int, candidates []portfolioCandidatePlan) error {
	if runID == "" {
		return errors.New("portfolio run id is required")
	}
	summary := mustJSON(map[string]any{
		"start":           startDate,
		"end":             endDate,
		"objective":       objective,
		"benchmark":       benchmark,
		"strategy_count":  strategyCount,
		"candidate_count": len(candidates),
		"planned_count":   len(candidates),
		"completed_count": 0,
		"failed_count":    0,
		"top_n":           topN,
		"rows":            []any{},
	})
	_, err := app.database.Conn().Exec(`INSERT INTO portfolio_optimization_runs(
		run_id, start_date, end_date, objective, benchmark, strategy_count,
		viable_count, candidate_count, top_n, generated_at, summary_json,
		created_at, updated_at
	) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, datetime('now'), datetime('now'))
	ON CONFLICT(run_id) DO UPDATE SET
		start_date = excluded.start_date,
		end_date = excluded.end_date,
		objective = excluded.objective,
		benchmark = excluded.benchmark,
		strategy_count = excluded.strategy_count,
		candidate_count = excluded.candidate_count,
		top_n = excluded.top_n,
		generated_at = excluded.generated_at,
		summary_json = excluded.summary_json,
		updated_at = excluded.updated_at`,
		runID, startDate, endDate, objective, benchmark, strategyCount, len(candidates), topN, time.Now().Format(time.RFC3339), summary)
	return err
}

func (app *App) generatePortfolioCandidates(value any, objective string, maxCandidates int) []portfolioCandidatePlan {
	names := app.resolvePortfolioStrategyNames(value)
	if admittedNames, ok := app.admittedPortfolioStrategyNames(names); ok {
		names = admittedNames
	}
	return app.generatePortfolioCandidatesFromNames(names, objective, maxCandidates)
}

func (app *App) generatePortfolioCandidatesFromNames(names []string, objective string, maxCandidates int) []portfolioCandidatePlan {
	labels := func(name string) string {
		if strategy, ok := app.settings.Strategies[name]; ok && strings.TrimSpace(strategy.Label) != "" {
			return strategy.Label
		}
		return name
	}
	candidates := make([]portfolioCandidatePlan, 0)
	baseGroups := []portfolioBaseGroup{
		{Name: "single"},
		{Name: "core"},
		{Name: "pair"},
		{Name: "triple"},
		{Name: "objective"},
	}
	seenWeights := map[string]bool{}
	addBase := func(groupName string, name string, weights map[string]float64) {
		weights = normalizeWeights(weights)
		if len(weights) == 0 {
			return
		}
		keyData, _ := json.Marshal(weights)
		key := string(keyData)
		if seenWeights[key] {
			return
		}
		seenWeights[key] = true
		item := portfolioCandidatePlan{
			Name:    name,
			Weights: weights,
		}
		for idx := range baseGroups {
			if baseGroups[idx].Name == groupName {
				baseGroups[idx].Items = append(baseGroups[idx].Items, item)
				return
			}
		}
	}
	for _, name := range names {
		addBase("single", "单策略-"+labels(name), map[string]float64{name: 1})
	}
	core := ""
	for _, name := range names {
		if name == "small_cap_quality" {
			core = name
			break
		}
	}
	if core == "" && len(names) > 0 {
		core = names[0]
	}
	if core != "" {
		for _, other := range names {
			if other != core {
				addBase("core", "核心增强-"+labels(core)+"+"+labels(other), map[string]float64{core: 0.65, other: 0.35})
			}
		}
	}
	for i := 0; i < len(names); i++ {
		for j := i + 1; j < len(names); j++ {
			addBase("pair", "双策略等权-"+labels(names[i])+"+"+labels(names[j]), map[string]float64{names[i]: 1, names[j]: 1})
		}
	}
	for i := 0; i < len(names); i++ {
		for j := i + 1; j < len(names); j++ {
			for k := j + 1; k < len(names); k++ {
				addBase("triple", "三策略等权-"+labels(names[i])+"+"+labels(names[j])+"+"+labels(names[k]), map[string]float64{names[i]: 1, names[j]: 1, names[k]: 1})
			}
		}
	}
	objectiveSets := map[string][]string{
		"稳健": {"market_regime_timing", "dividend_quality", "multi_factor_composite", "small_cap_quality"},
		"进攻": {"trend_pullback", "earnings_revision", "industry_prosperity", "low_crowding_reversal"},
		"平衡": {"multi_factor_composite", "small_cap_quality", "trend_pullback", "dividend_quality"},
	}
	if preferred, ok := objectiveSets[objective]; ok {
		weights := map[string]float64{}
		for _, name := range preferred {
			if containsString(names, name) {
				weights[name] = 1
			}
		}
		addBase("objective", objective+"核心方案", weights)
	}
	baseCandidates := interleaveBaseGroups(baseGroups)
	exitPlans := app.portfolioExitPlans(objective)
	rebalanceFreqs := []int{1, 5, 20}
	riskPlans := app.portfolioRiskPlans(objective)
	positionPlans := app.portfolioPositionPlans(objective)
	seenScheme := map[string]bool{}
	for _, exitPlan := range exitPlans {
		for _, rebalanceFreq := range rebalanceFreqs {
			for _, riskPlan := range riskPlans {
				for _, positionPlan := range positionPlans {
					for _, base := range baseCandidates {
						if maxCandidates > 0 && len(candidates) >= maxCandidates {
							return candidates
						}
						candidate := base
						candidate.RebalanceFreq = rebalanceFreq
						candidate.ExitArchitecture = cloneMap(exitPlan)
						candidate.PositionRule = cloneMap(positionPlan)
						candidate.RiskRule = cloneMap(riskPlan)
						keyData, _ := json.Marshal(candidate.toSchemePayload())
						key := string(keyData)
						if seenScheme[key] {
							continue
						}
						seenScheme[key] = true
						candidate.ID = fmt.Sprintf("scheme_%03d", len(candidates)+1)
						candidate.Name = fmt.Sprintf("%s / %s / %s / %s / %s", base.Name, rebalanceLabel(rebalanceFreq), exitLabel(exitPlan), riskLabel(riskPlan), positionLabel(positionPlan))
						candidates = append(candidates, candidate)
					}
				}
			}
		}
	}
	return candidates
}

func interleaveBaseGroups(groups []portfolioBaseGroup) []portfolioCandidatePlan {
	out := make([]portfolioCandidatePlan, 0)
	maxLen := 0
	for _, group := range groups {
		if len(group.Items) > maxLen {
			maxLen = len(group.Items)
		}
	}
	for index := 0; index < maxLen; index++ {
		for _, group := range groups {
			if index < len(group.Items) {
				out = append(out, group.Items[index])
			}
		}
	}
	return out
}

func (candidate portfolioCandidatePlan) toSchemePayload() map[string]any {
	return map[string]any{
		"scheme_type":       "trading_scheme",
		"name":              candidate.Name,
		"entry":             map[string]any{"type": "strategy_weight_mix", "weights": candidate.Weights},
		"exit_architecture": candidate.ExitArchitecture,
		"position_rule":     candidate.PositionRule,
		"rebalance_freq":    candidate.RebalanceFreq,
		"risk_rule":         candidate.RiskRule,
		"research_space":    portfolioResearchSpace(),
	}
}

func portfolioResearchSpace() map[string]any {
	return map[string]any{
		"strategy":            researchStrategyUniverse,
		"exit_rule":           []string{"rebalance_only", "stop_loss", "trailing_stop", "stop_loss_trailing"},
		"rebalance_freq":      []int{1, 5, 20},
		"market_regime":       []string{"off", "breadth_trend_filter"},
		"position_max_weight": []float64{0.05, 0.08, 0.10},
		"parameter_ranges": map[string]any{
			"max_20d_return": []float64{0.20, 0.25, 0.30, 0.35},
			"min_roe":        []float64{0.05, 0.06, 0.07, 0.08, 0.10},
			"holding_days":   []int{7, 10, 20, 35, 60},
			"max_total_mv":   []float64{50000000000, 80000000000, 120000000000},
			"stop_loss":      []float64{-0.08, -0.10, -0.12, -0.16},
			"trailing_stop":  []float64{-0.06, -0.08, -0.10},
		},
	}
}

func (app *App) portfolioExitPlans(objective string) []map[string]any {
	baseSlippage := 0.003
	if value, ok := app.settings.ExitRules["slippage"]; ok {
		baseSlippage = numberParam(map[string]any{"slippage": value}, "slippage", baseSlippage)
	}
	plans := []map[string]any{
		{"type": "rebalance_only", "label": "跌出目标池卖出", "enabled": false, "slippage": baseSlippage},
		{"type": "stop_loss", "label": "跌出目标池+固定止损", "enabled": true, "stop_loss": -0.12, "slippage": baseSlippage},
		{"type": "trailing_stop", "label": "跌出目标池+移动止盈", "enabled": true, "trailing_stop": -0.08, "trailing_exec": "next_open", "slippage": baseSlippage},
		{"type": "stop_loss_trailing", "label": "跌出目标池+止损+移动止盈", "enabled": true, "stop_loss": -0.12, "trailing_stop": -0.08, "trailing_exec": "next_open", "slippage": baseSlippage},
	}
	if objective == "稳健" {
		plans = append(plans, map[string]any{"type": "tight_risk", "label": "稳健止损+移动止盈", "enabled": true, "stop_loss": -0.08, "trailing_stop": -0.06, "trailing_exec": "next_open", "slippage": baseSlippage})
	}
	if objective == "进攻" {
		plans = append(plans, map[string]any{"type": "wide_risk", "label": "进攻宽止损+移动止盈", "enabled": true, "stop_loss": -0.16, "trailing_stop": -0.1, "trailing_exec": "next_open", "slippage": baseSlippage})
	}
	return plans
}

func (app *App) portfolioRiskPlans(objective string) []map[string]any {
	base := cloneMap(app.settings.PortfolioRisk)
	plain := map[string]any{"label": "无市场过滤", "portfolio_risk": base}
	filteredRisk := cloneMap(app.settings.PortfolioRisk)
	filteredRisk["market_regime"] = map[string]any{
		"enabled":         true,
		"trend_window":    60,
		"breadth_window":  20,
		"min_breadth":     0.45,
		"normal_exposure": 1.0,
		"weak_exposure":   0.50,
		"bear_exposure":   0.25,
	}
	if objective == "进攻" {
		filteredRisk["market_regime"] = map[string]any{"enabled": true, "trend_window": 60, "breadth_window": 20, "min_breadth": 0.40, "normal_exposure": 1.0, "weak_exposure": 0.65, "bear_exposure": 0.35}
	}
	return []map[string]any{
		plain,
		{"label": "市场状态过滤", "portfolio_risk": filteredRisk},
	}
}

func (app *App) portfolioPositionPlans(objective string) []map[string]any {
	if objective == "稳健" {
		return []map[string]any{
			{"type": "score_weighted_equal_cap", "label": "单票5%", "max_weight": 0.05, "min_position_count": 5},
			{"type": "score_weighted_equal_cap", "label": "单票8%", "max_weight": 0.08, "min_position_count": 4},
		}
	}
	return []map[string]any{
		{"type": "score_weighted_equal_cap", "label": "单票5%", "max_weight": 0.05, "min_position_count": 5},
		{"type": "score_weighted_equal_cap", "label": "单票8%", "max_weight": 0.08, "min_position_count": 4},
		{"type": "score_weighted_equal_cap", "label": "单票10%", "max_weight": 0.10, "min_position_count": 3},
	}
}

func cloneMap(value map[string]any) map[string]any {
	out := make(map[string]any, len(value))
	for key, item := range value {
		out[key] = item
	}
	return out
}

func rebalanceLabel(freq int) string {
	switch freq {
	case 1:
		return "日调仓"
	case 20:
		return "月调仓"
	default:
		return "周调仓"
	}
}

func exitLabel(plan map[string]any) string {
	if label := strings.TrimSpace(fmt.Sprint(plan["label"])); label != "" && label != "<nil>" {
		return label
	}
	return strings.TrimSpace(fmt.Sprint(plan["type"]))
}

func riskLabel(plan map[string]any) string {
	if label := strings.TrimSpace(fmt.Sprint(plan["label"])); label != "" && label != "<nil>" {
		return label
	}
	return "风险默认"
}

func positionLabel(plan map[string]any) string {
	if label := strings.TrimSpace(fmt.Sprint(plan["label"])); label != "" && label != "<nil>" {
		return label
	}
	if value, ok := plan["max_weight"]; ok {
		return fmt.Sprintf("单票%.0f%%", numberParam(map[string]any{"v": value}, "v", 0.1)*100)
	}
	return "仓位默认"
}

func (app *App) resolvePortfolioStrategyNames(value any) []string {
	selected := strategyParam(value)
	names := make([]string, 0)
	if selected == "all" || selected == "enabled" {
		for _, name := range researchStrategyUniverse {
			strategy, ok := app.settings.Strategies[name]
			if !ok {
				continue
			}
			if selected == "all" || strategy.Enabled {
				names = append(names, name)
			}
		}
	} else {
		for _, item := range strings.Split(selected, ",") {
			item = strings.TrimSpace(item)
			if item != "" {
				names = append(names, item)
			}
		}
	}
	sort.Strings(names)
	return names
}

func (app *App) resolveStrategyAdmissionNames(value any) []string {
	selected := strategyParam(value)
	if selected == "" || selected == "enabled" {
		selected = "all"
	}
	return app.resolvePortfolioStrategyNames(selected)
}

func (app *App) strategyDisplayName(name string) string {
	if strategy, ok := app.settings.Strategies[name]; ok && strings.TrimSpace(strategy.Label) != "" {
		return strings.TrimSpace(strategy.Label)
	}
	return name
}

func (app *App) admittedPortfolioStrategyNames(names []string) ([]string, bool) {
	if len(names) == 0 || app.database == nil || app.database.Conn() == nil {
		return names, false
	}
	rows, err := app.database.Conn().Query(`
		SELECT strategy, admission
		FROM strategy_evaluation
		WHERE run_id = (
			SELECT run_id
			FROM strategy_evaluation
			ORDER BY datetime(generated_at) DESC, datetime(updated_at) DESC
			LIMIT 1
		)`)
	if err != nil {
		return names, false
	}
	defer rows.Close()

	allowed := map[string]bool{}
	seen := false
	for rows.Next() {
		var strategyName string
		var admission string
		if err := rows.Scan(&strategyName, &admission); err != nil {
			return names, false
		}
		seen = true
		if strings.TrimSpace(admission) == "可启用" {
			allowed[strategyName] = true
		}
	}
	if err := rows.Err(); err != nil || !seen {
		return names, false
	}
	out := make([]string, 0, len(names))
	for _, name := range names {
		if allowed[name] {
			out = append(out, name)
		}
	}
	return out, true
}

func normalizeWeights(weights map[string]float64) map[string]float64 {
	total := 0.0
	for _, weight := range weights {
		if weight > 0 {
			total += weight
		}
	}
	if total <= 0 {
		return map[string]float64{}
	}
	out := make(map[string]float64, len(weights))
	for name, weight := range weights {
		if weight > 0 {
			out[name] = weight / total
		}
	}
	return out
}

func containsString(items []string, value string) bool {
	for _, item := range items {
		if item == value {
			return true
		}
	}
	return false
}

func mustJSON(value any) string {
	data, _ := json.Marshal(value)
	return string(data)
}

func (app *App) ListTasks(query task.Query) ([]task.DTO, error) {
	if err := app.ensureTaskService(); err != nil {
		return nil, err
	}
	return app.taskService.List(query)
}

func (app *App) GetTask(id string) (task.DTO, error) {
	if err := app.ensureTaskService(); err != nil {
		return task.DTO{}, err
	}
	return app.taskService.Get(id)
}

func (app *App) RefreshTaskStatus(id string) (task.DTO, error) {
	if err := app.ensureTaskService(); err != nil {
		return task.DTO{}, err
	}
	t, err := app.taskService.Repository().Get(id)
	if err != nil {
		return task.DTO{}, err
	}
	t = app.reconcileTaskStatus(t)
	return task.ToDTO(t), nil
}

func (app *App) reconcileTaskStatus(t task.Task) task.Task {
	if t.Status != task.StatusRunning && t.Status != task.StatusQueued {
		return t
	}

	now := time.Now()
	if t.TaskType == task.TypePortfolioOptimization && t.ParentID == "" {
		children, err := app.taskService.Repository().ListChildren(t.ID)
		if err == nil && len(children) > 0 {
			status := portfolioParentStatus(children)
			t.Progress = portfolioParentProgress(children)
			t.SummaryJSON = app.portfolioSummaryForParent(t, children)
			t.UpdatedAt = now
			if status != task.StatusRunning {
				t.Status = status
				t.FinishedAt = now
			}
			_ = app.taskService.Repository().UpdateStatus(t)
			_ = app.taskService.Repository().UpdateRuntime(t)
			return t
		}
	}
	if t.TaskType == task.TypeStrategyEvaluation && t.ParentID == "" {
		children, err := app.taskService.Repository().ListChildren(t.ID)
		if err == nil && len(children) > 0 {
			t.Progress = portfolioParentProgress(children)
			t.SummaryJSON = app.strategyEvaluationSummaryForParent(t, children)
			t.UpdatedAt = now
			if t.Status == task.StatusRunning {
				status := portfolioParentStatus(children)
				if status != task.StatusRunning {
					t.Status = status
					t.FinishedAt = now
				}
			}
			_ = app.taskService.Repository().UpdateStatus(t)
			_ = app.taskService.Repository().UpdateRuntime(t)
			return t
		}
	}
	if app.database != nil && t.ExternalRunID != "" {
		var summary string
		switch t.TaskType {
		case task.TypeStrategyEvaluation:
			summary = readStrategyEvaluationSummaryFromDB(app.database.Conn(), t.ExternalRunID)
		case task.TypePortfolioOptimization:
			summary = readPortfolioOptimizationSummaryFromDB(app.database.Conn(), t.ExternalRunID)
		}
		if summary != "" {
			t.Status = task.StatusSuccess
			t.Progress = 1
			t.SummaryJSON = summary
			t.WorkerPID = 0
			t.ErrorMessage = ""
			t.FinishedAt = now
			t.UpdatedAt = now
			_ = app.taskService.Repository().UpdateStatus(t)
			_ = app.taskService.Repository().UpdateRuntime(t)
			return t
		}
	}

	if t.WorkerPID > 0 && !processExists(t.WorkerPID) {
		t.Status = task.StatusInterrupted
		t.WorkerPID = 0
		t.ErrorMessage = "worker process is no longer running"
		t.FinishedAt = now
		t.UpdatedAt = now
		_ = app.taskService.Repository().UpdateStatus(t)
		_ = app.taskService.Repository().UpdateRuntime(t)
	}
	return t
}

func processExists(pid int) bool {
	if pid <= 0 {
		return false
	}
	err := syscall.Kill(pid, 0)
	return err == nil || err == syscall.EPERM
}

func (app *App) GetTimeMachineDetail(id string) (result.TimeMachineDetail, error) {
	if err := app.ensureTaskService(); err != nil {
		return result.TimeMachineDetail{}, err
	}
	t, err := app.taskService.Repository().Get(id)
	if err != nil {
		return result.TimeMachineDetail{}, err
	}
	if t.ExternalRunID == "" {
		return result.TimeMachineDetail{}, errors.New("task has no time machine run id")
	}
	return result.ReadTimeMachineDetail(app.database.Conn(), t.ExternalRunID)
}

func (app *App) GetTaskLog(id string, tailBytes int) (string, error) {
	if err := app.ensureTaskService(); err != nil {
		return "", err
	}
	t, err := app.taskService.Repository().Get(id)
	if err != nil {
		return "", err
	}
	if t.LogPath == "" {
		return "", nil
	}
	data, err := os.ReadFile(t.LogPath)
	if err != nil {
		return "", err
	}
	if tailBytes <= 0 {
		tailBytes = 20000
	}
	if len(data) > tailBytes {
		data = data[len(data)-tailBytes:]
	}
	return string(data), nil
}

func (app *App) AnalyzePortfolioTask(id string) (task.DTO, error) {
	if err := app.ensureTaskService(); err != nil {
		return task.DTO{}, err
	}
	t, err := app.taskService.Repository().Get(id)
	if err != nil {
		return task.DTO{}, err
	}
	if t.TaskType != task.TypePortfolioOptimization || t.ParentID != "" {
		return task.DTO{}, errors.New("只能分析方案评估父任务")
	}
	children, err := app.taskService.Repository().ListChildren(t.ID)
	if err != nil {
		return task.DTO{}, err
	}
	planned, succeeded, running, failed := portfolioAnalysisCoverage(children)
	if planned == 0 {
		return task.DTO{}, errors.New("方案评估还没有初始化子任务")
	}
	if running > 0 {
		return task.DTO{}, errors.New("方案评估还在运行，等全部子任务完成后再做 AI 分析")
	}
	if succeeded != planned {
		return task.DTO{}, fmt.Errorf("方案评估结果不完整：计划 %d 个，成功 %d 个，失败/取消 %d 个。请先重跑失败子任务，否则模型无法判断完整方案效果", planned, succeeded, failed)
	}
	token := strings.TrimSpace(app.settings.DeepSeekToken)
	if token == "" {
		return task.DTO{}, errors.New("请先在设置里填写 DeepSeek Token")
	}
	contextPayload, err := app.buildPortfolioAnalysisContext(t, children)
	if err != nil {
		return task.DTO{}, err
	}
	analysis, recommendation, err := app.callDeepSeekForPortfolioAnalysis(contextPayload)
	now := time.Now()
	summary := map[string]any{}
	if t.SummaryJSON != "" {
		_ = json.Unmarshal([]byte(t.SummaryJSON), &summary)
	}
	if err != nil {
		summary["ai_analysis_error"] = err.Error()
	} else {
		summary["ai_analysis"] = analysis
		summary["ai_recommendation"] = recommendation
		if nextEval, ok := recommendation["next_eval_config"].(map[string]any); ok {
			summary["ai_next_eval_config"] = normalizeNextEvalConfig(t, nextEval)
		}
		summary["ai_analysis_error"] = ""
		summary["ai_analysis_model"] = app.deepSeekModel()
		summary["ai_analysis_at"] = now.Format(time.RFC3339)
	}
	data, _ := json.Marshal(summary)
	t.SummaryJSON = string(data)
	t.UpdatedAt = now
	_ = app.taskService.Repository().UpdateStatus(t)
	if t.ExternalRunID != "" {
		_, _ = app.database.Conn().Exec(`UPDATE portfolio_optimization_runs SET summary_json = ?, updated_at = datetime('now') WHERE run_id = ?`, string(data), t.ExternalRunID)
	}
	if err != nil {
		return task.ToDTO(t), err
	}
	return task.ToDTO(t), nil
}

func portfolioAnalysisCoverage(children []task.Task) (planned int, succeeded int, running int, failed int) {
	planned = len(children)
	for _, child := range children {
		switch child.Status {
		case task.StatusSuccess:
			succeeded++
		case task.StatusRunning, task.StatusQueued, task.StatusCreated:
			running++
		case task.StatusFailed, task.StatusCancelled, task.StatusInterrupted:
			failed++
		}
	}
	return planned, succeeded, running, failed
}

func (app *App) buildPortfolioAnalysisContext(parent task.Task, children []task.Task) (map[string]any, error) {
	params := task.ToDTO(parent).Params
	runID := parent.ExternalRunID
	topN := int(numberParam(params, "top_n", 40))
	if topN <= 0 {
		topN = 40
	}
	rows := make([]map[string]any, 0)
	if app.database != nil && runID != "" {
		dbRows, err := app.database.Conn().Query(`SELECT rank, score, annual_return, max_drawdown, sharpe, calmar, avg_turnover, avg_holdings, avg_total_mv, avg_amount, payload_json
			FROM portfolio_optimization_candidates
			WHERE run_id = ?
			ORDER BY CASE WHEN rank > 0 THEN rank ELSE 999999 END ASC, score DESC
			LIMIT ?`, runID, topN)
		if err != nil {
			return nil, err
		}
		defer dbRows.Close()
		for dbRows.Next() {
			var rank int
			var score float64
			var annualReturn, maxDrawdown, sharpe, calmar, avgTurnover, avgHoldings, avgTotalMV, avgAmount sql.NullFloat64
			var payloadJSON string
			if err := dbRows.Scan(&rank, &score, &annualReturn, &maxDrawdown, &sharpe, &calmar, &avgTurnover, &avgHoldings, &avgTotalMV, &avgAmount, &payloadJSON); err != nil {
				return nil, err
			}
			item := map[string]any{}
			if err := json.Unmarshal([]byte(payloadJSON), &item); err != nil {
				continue
			}
			item["rank"] = rank
			item["score"] = score
			overlayNullableFloat(item, "annual_return", annualReturn)
			overlayNullableFloat(item, "max_drawdown", maxDrawdown)
			overlayNullableFloat(item, "sharpe", sharpe)
			overlayNullableFloat(item, "calmar", calmar)
			overlayNullableFloat(item, "avg_turnover", avgTurnover)
			overlayNullableFloat(item, "avg_holdings", avgHoldings)
			overlayNullableFloat(item, "avg_total_mv", avgTotalMV)
			overlayNullableFloat(item, "avg_amount", avgAmount)
			rows = append(rows, item)
		}
		if err := dbRows.Err(); err != nil {
			return nil, err
		}
	}
	childItems := make([]map[string]any, 0, len(children))
	for _, child := range children {
		childItems = append(childItems, map[string]any{
			"sequence":      child.Sequence,
			"total":         child.Total,
			"candidate_id":  child.SubtaskKey,
			"name":          child.SubtaskName,
			"status":        child.Status,
			"progress":      child.Progress,
			"attempt":       child.Attempt,
			"max_attempts":  child.MaxAttempts,
			"error_message": child.ErrorMessage,
		})
	}
	strategyNames := map[string]bool{}
	for _, row := range rows {
		if weights, ok := row["weights"].(map[string]any); ok {
			for name := range weights {
				strategyNames[name] = true
			}
		}
	}
	selected := strategyParam(params["strategies"])
	if selected == "all" || selected == "enabled" || selected == "" {
		for name := range app.settings.Strategies {
			strategyNames[name] = true
		}
	} else {
		for _, name := range strings.Split(selected, ",") {
			name = strings.TrimSpace(name)
			if name != "" {
				strategyNames[name] = true
			}
		}
	}
	strategies := make([]map[string]any, 0, len(strategyNames))
	for name := range strategyNames {
		if strategy, ok := app.settings.Strategies[name]; ok {
			strategies = append(strategies, map[string]any{
				"name":      name,
				"label":     strategy.Label,
				"enabled":   strategy.Enabled,
				"weight":    strategy.Weight,
				"rebalance": strategy.Rebalance,
				"universe":  strategy.Universe,
				"filters":   strategy.Filters,
				"selection": strategy.Selection,
				"position":  strategy.Position,
			})
		}
	}
	sort.Slice(strategies, func(i, j int) bool {
		return fmt.Sprint(strategies[i]["name"]) < fmt.Sprint(strategies[j]["name"])
	})
	parentSummary := map[string]any{}
	if parent.SummaryJSON != "" {
		_ = json.Unmarshal([]byte(parent.SummaryJSON), &parentSummary)
	}
	planned, succeeded, running, failed := portfolioAnalysisCoverage(children)
	return map[string]any{
		"task": map[string]any{
			"id":       parent.ID,
			"name":     parent.Name,
			"run_id":   runID,
			"status":   parent.Status,
			"progress": parent.Progress,
			"params":   params,
			"summary":  parentSummary,
		},
		"coverage": map[string]any{
			"planned":   planned,
			"succeeded": succeeded,
			"running":   running,
			"failed":    failed,
		},
		"candidate_results":           rows,
		"strategy_contribution_stats": buildStrategyContributionStats(rows),
		"subtasks":                    childItems,
		"strategy_rules":              strategies,
		"portfolio_risk":              app.settings.PortfolioRisk,
		"exit_rules":                  app.settings.ExitRules,
	}, nil
}

func (app *App) callDeepSeekForPortfolioAnalysis(contextPayload map[string]any) (string, map[string]any, error) {
	data, err := json.Marshal(contextPayload)
	if err != nil {
		return "", nil, err
	}
	userPrompt := `下面是一个量化方案评估任务的完整结构化结果和策略规则。candidate_results 是本轮全量候选交易方案结果，包含 entry、exit_architecture、position_rule、rebalance_freq、risk_rule；strategy_contribution_stats 是按入场策略聚合后的贡献统计。

请只输出一个 JSON 对象，不要 Markdown 代码块，不要额外解释。格式如下：
{
  "analysis_md": "中文分析摘要，控制在 800 字以内，必须引用输入指标",
  "diagnosis": ["为什么这轮表现好/不好"],
  "keep": ["下一轮应保留的策略或规则"],
  "change": ["下一轮应调整的策略、权重、过滤条件、调仓频率或风控"],
  "remove": ["暂时剔除或降低权重的策略/规则"],
  "validation_plan": ["必须通过新回测验证的假设"],
  "next_eval_config": {
    "name": "下一轮评估名称",
    "task_type": "portfolio_optimization",
    "params": {
      "start_date": "YYYYMMDD",
      "end_date": "YYYYMMDD",
      "strategies": ["strategy_name"],
      "objective": "稳健|平衡|进攻",
      "max_candidates": 40,
			"top_n": 40,
      "benchmark": "000905.SH",
      "slippage": 0.003
    }
  }
}

要求：
1. 哪些完整交易方案盈利性最好，必须同时引用入场策略、出场架构、调仓频率，并优先引用 total_return、annual_return、excess_annual_return、win_rate；
2. 哪些规则拖累收益或风险，必须结合 max_drawdown、annual_volatility、sharpe、calmar、avg_turnover 判断；
3. next_eval_config 必须是可以直接创建下一轮方案评估的参数；
4. 不要编造数据，必须引用输入里的指标；如果 coverage 不是全成功，请在 diagnosis 中说明缺口，并不要给激进结论。

JSON:
` + string(data)
	body := map[string]any{
		"model": app.deepSeekModel(),
		"messages": []map[string]string{
			{"role": "system", "content": "你是量化策略研究员，擅长根据回测指标和策略规则做归因、风险诊断和下一轮实验设计。输出要简洁、具体、可验证。"},
			{"role": "user", "content": userPrompt},
		},
		"thinking":         map[string]string{"type": "enabled"},
		"reasoning_effort": "high",
		"stream":           false,
	}
	requestBody, err := json.Marshal(body)
	if err != nil {
		return "", nil, err
	}
	req, err := http.NewRequestWithContext(app.ctx, http.MethodPost, "https://api.deepseek.com/chat/completions", bytes.NewReader(requestBody))
	if err != nil {
		return "", nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+strings.TrimSpace(app.settings.DeepSeekToken))
	client := &http.Client{Timeout: 90 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", nil, err
	}
	defer resp.Body.Close()
	respBody, _ := io.ReadAll(io.LimitReader(resp.Body, 4*1024*1024))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", nil, fmt.Errorf("DeepSeek 请求失败：HTTP %d %s", resp.StatusCode, strings.TrimSpace(string(respBody)))
	}
	var parsed struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(respBody, &parsed); err != nil {
		return "", nil, err
	}
	if len(parsed.Choices) == 0 || strings.TrimSpace(parsed.Choices[0].Message.Content) == "" {
		return "", nil, errors.New("DeepSeek 返回为空")
	}
	raw := strings.TrimSpace(parsed.Choices[0].Message.Content)
	recommendation, err := parseDeepSeekJSON(raw)
	if err != nil {
		return raw, map[string]any{"analysis_md": raw}, nil
	}
	analysis := strings.TrimSpace(fmt.Sprint(recommendation["analysis_md"]))
	if analysis == "" {
		analysis = raw
	}
	return analysis, recommendation, nil
}

func parseDeepSeekJSON(raw string) (map[string]any, error) {
	text := strings.TrimSpace(raw)
	text = strings.TrimPrefix(text, "```json")
	text = strings.TrimPrefix(text, "```")
	text = strings.TrimSuffix(text, "```")
	text = strings.TrimSpace(text)
	start := strings.Index(text, "{")
	end := strings.LastIndex(text, "}")
	if start >= 0 && end > start {
		text = text[start : end+1]
	}
	out := map[string]any{}
	if err := json.Unmarshal([]byte(text), &out); err != nil {
		return nil, err
	}
	return out, nil
}

func normalizeNextEvalConfig(parent task.Task, config map[string]any) map[string]any {
	params := task.ToDTO(parent).Params
	nextParams := map[string]any{}
	if raw, ok := config["params"].(map[string]any); ok {
		for key, value := range raw {
			nextParams[key] = value
		}
	}
	defaults := map[string]any{
		"start_date":     params["start_date"],
		"end_date":       params["end_date"],
		"strategies":     params["strategies"],
		"objective":      params["objective"],
		"max_candidates": params["max_candidates"],
		"top_n":          params["top_n"],
		"benchmark":      params["benchmark"],
		"slippage":       params["slippage"],
	}
	for key, value := range defaults {
		if nextParams[key] == nil || fmt.Sprint(nextParams[key]) == "" {
			nextParams[key] = value
		}
	}
	if nextParams["objective"] == nil || fmt.Sprint(nextParams["objective"]) == "" {
		nextParams["objective"] = "平衡"
	}
	if nextParams["max_candidates"] == nil {
		nextParams["max_candidates"] = 40
	}
	if nextParams["top_n"] == nil {
		nextParams["top_n"] = 40
	}
	if nextParams["benchmark"] == nil || fmt.Sprint(nextParams["benchmark"]) == "" {
		nextParams["benchmark"] = "000905.SH"
	}
	if nextParams["slippage"] == nil {
		nextParams["slippage"] = 0.003
	}
	name := strings.TrimSpace(fmt.Sprint(config["name"]))
	if name == "" || name == "<nil>" {
		name = parent.Name + " - 下一轮"
	}
	return map[string]any{
		"name":      name,
		"task_type": "portfolio_optimization",
		"params":    nextParams,
	}
}

func buildStrategyContributionStats(rows []map[string]any) []map[string]any {
	type agg struct {
		Name                string
		Count               int
		BestRank            int
		BestCandidate       string
		BestScore           float64
		ScoreSum            float64
		TotalReturnSum      float64
		TotalReturnCount    int
		AnnualSum           float64
		AnnualCount         int
		VolatilitySum       float64
		VolatilityCount     int
		DrawdownSum         float64
		DrawdownCount       int
		SharpeSum           float64
		SharpeCount         int
		WinRateSum          float64
		WinRateCount        int
		ExcessAnnualSum     float64
		ExcessAnnualCount   int
		SingleCandidateName string
		SingleScore         float64
		SingleTotalReturn   any
		SingleAnnual        any
		SingleDrawdown      any
		SingleWinRate       any
	}
	stats := map[string]*agg{}
	for _, row := range rows {
		weights, ok := row["weights"].(map[string]any)
		if !ok {
			continue
		}
		score, _ := numericAny(row["score"])
		rank := intNumericAny(row["rank"])
		name := fmt.Sprint(row["name"])
		for strategy, rawWeight := range weights {
			weight, ok := numericAny(rawWeight)
			if !ok || weight <= 0 {
				continue
			}
			item := stats[strategy]
			if item == nil {
				item = &agg{Name: strategy, BestRank: 1 << 30}
				stats[strategy] = item
			}
			item.Count++
			item.ScoreSum += score
			if rank > 0 && rank < item.BestRank {
				item.BestRank = rank
				item.BestCandidate = name
				item.BestScore = score
			}
			if annual, ok := numericAny(row["annual_return"]); ok {
				item.AnnualSum += annual
				item.AnnualCount++
			}
			if totalReturn, ok := numericAny(row["total_return"]); ok {
				item.TotalReturnSum += totalReturn
				item.TotalReturnCount++
			}
			if volatility, ok := numericAny(row["annual_volatility"]); ok {
				item.VolatilitySum += volatility
				item.VolatilityCount++
			}
			if drawdown, ok := numericAny(row["max_drawdown"]); ok {
				item.DrawdownSum += drawdown
				item.DrawdownCount++
			}
			if sharpe, ok := numericAny(row["sharpe"]); ok {
				item.SharpeSum += sharpe
				item.SharpeCount++
			}
			if winRate, ok := numericAny(row["win_rate"]); ok {
				item.WinRateSum += winRate
				item.WinRateCount++
			}
			if excessAnnual, ok := numericAny(row["excess_annual_return"]); ok {
				item.ExcessAnnualSum += excessAnnual
				item.ExcessAnnualCount++
			}
			if len(weights) == 1 && weight > 0.99 {
				item.SingleCandidateName = name
				item.SingleScore = score
				item.SingleTotalReturn = row["total_return"]
				item.SingleAnnual = row["annual_return"]
				item.SingleDrawdown = row["max_drawdown"]
				item.SingleWinRate = row["win_rate"]
			}
		}
	}
	names := make([]string, 0, len(stats))
	for name := range stats {
		names = append(names, name)
	}
	sort.Strings(names)
	out := make([]map[string]any, 0, len(names))
	for _, name := range names {
		item := stats[name]
		bestRank := any(nil)
		if item.BestRank < 1<<30 {
			bestRank = item.BestRank
		}
		out = append(out, map[string]any{
			"strategy":                 item.Name,
			"candidate_count":          item.Count,
			"avg_score":                safeAvg(item.ScoreSum, item.Count),
			"avg_total_return":         safeAvgAny(item.TotalReturnSum, item.TotalReturnCount),
			"best_rank":                bestRank,
			"best_candidate":           item.BestCandidate,
			"best_score":               item.BestScore,
			"avg_annual_return":        safeAvgAny(item.AnnualSum, item.AnnualCount),
			"avg_annual_volatility":    safeAvgAny(item.VolatilitySum, item.VolatilityCount),
			"avg_max_drawdown":         safeAvgAny(item.DrawdownSum, item.DrawdownCount),
			"avg_sharpe":               safeAvgAny(item.SharpeSum, item.SharpeCount),
			"avg_win_rate":             safeAvgAny(item.WinRateSum, item.WinRateCount),
			"avg_excess_annual_return": safeAvgAny(item.ExcessAnnualSum, item.ExcessAnnualCount),
			"single_candidate":         item.SingleCandidateName,
			"single_score":             item.SingleScore,
			"single_total_return":      item.SingleTotalReturn,
			"single_annual_return":     item.SingleAnnual,
			"single_max_drawdown":      item.SingleDrawdown,
			"single_win_rate":          item.SingleWinRate,
		})
	}
	return out
}

func numericAny(value any) (float64, bool) {
	switch typed := value.(type) {
	case float64:
		return typed, true
	case float32:
		return float64(typed), true
	case int:
		return float64(typed), true
	case int64:
		return float64(typed), true
	case json.Number:
		next, err := typed.Float64()
		return next, err == nil
	default:
		return 0, false
	}
}

func intNumericAny(value any) int {
	if number, ok := numericAny(value); ok {
		return int(number)
	}
	return 0
}

func safeAvg(sum float64, count int) float64 {
	if count <= 0 {
		return 0
	}
	return sum / float64(count)
}

func safeAvgAny(sum float64, count int) any {
	if count <= 0 {
		return nil
	}
	return sum / float64(count)
}

func (app *App) deepSeekModel() string {
	model := strings.TrimSpace(app.settings.DeepSeekModel)
	if model == "" {
		return "deepseek-v4-pro"
	}
	return model
}

func nullableFloat(value sql.NullFloat64) any {
	if value.Valid {
		return value.Float64
	}
	return nil
}

func overlayNullableFloat(item map[string]any, key string, value sql.NullFloat64) {
	if value.Valid {
		item[key] = value.Float64
	}
}

func (app *App) DeleteTask(id string) error {
	if err := app.ensureTaskService(); err != nil {
		return err
	}
	return app.taskService.Delete(id)
}

func (app *App) StartTask(id string) (task.DTO, error) {
	if err := app.ensureTaskService(); err != nil {
		return task.DTO{}, err
	}
	t, err := app.taskService.Repository().Get(id)
	if err != nil {
		return task.DTO{}, err
	}
	if t.Status == task.StatusRunning {
		return task.ToDTO(t), nil
	}
	if t.Status != task.StatusCreated && t.Status != task.StatusQueued && t.Status != task.StatusInterrupted && t.Status != task.StatusFailed && t.Status != task.StatusCancelled {
		return task.DTO{}, errors.New("task cannot be started in current status")
	}
	if t.TaskType != task.TypeEvaluationTimeMachine && t.TaskType != task.TypeStrategyEvaluation && t.TaskType != task.TypePortfolioOptimization {
		return task.DTO{}, errors.New("only evaluation tasks can be started")
	}
	running, err := app.taskService.Repository().HasRunningEvaluation(t.ID)
	if err != nil {
		return task.DTO{}, err
	}
	if running {
		return task.DTO{}, errors.New("已有评估任务正在运行，同一时间只能运行一个评估")
	}
	if t.TaskType == task.TypeStrategyEvaluation {
		return app.startStrategyEvaluationTask(t)
	}
	if t.TaskType == task.TypePortfolioOptimization {
		if t.ParentID != "" {
			return app.startPortfolioCandidateTask(t)
		}
		return app.startPortfolioOptimizationTask(t)
	}
	runID := t.ExternalRunID
	if runID == "" {
		runID = "tm_" + strings.ReplaceAll(t.ID, "-", "")
	}
	runPath := filepath.Join(app.settings.DataPath, "positions", "timemachine", runID)
	logPath := filepath.Join(runPath, "worker.log")
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	params := task.ToDTO(t).Params
	params["eval_name"] = t.Name

	info, err := worker.NewManager().Start(worker.StartRequest{
		PythonPath:     pythonPath,
		QuantStockPath: quantRoot,
		DataPath:       app.settings.DataPath,
		DBPath:         filepath.Join(app.settings.DataPath, "meta.db"),
		ConfigDBPath:   filepath.Join(app.settings.DataPath, "meta.db"),
		TaskID:         t.ID,
		RunID:          runID,
		LogPath:        logPath,
		Params:         params,
	})
	if err != nil {
		return task.DTO{}, err
	}
	now := time.Now()
	t.Status = task.StatusRunning
	t.Progress = 0
	t.ResultPath = runPath
	t.LogPath = logPath
	t.WorkerPID = info.PID
	t.ExternalRunID = runID
	t.ErrorMessage = ""
	t.StartedAt = now
	t.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(t); err != nil {
		return task.DTO{}, err
	}
	return task.ToDTO(t), nil
}

func (app *App) startStrategyEvaluationTask(t task.Task) (task.DTO, error) {
	if t.ParentID != "" {
		go func() {
			updated, err := app.startStrategyEvaluationChildTaskSync(t)
			if err != nil && updated.WorkerPID == 0 && updated.Status != task.StatusFailed {
				now := time.Now()
				updated.Status = task.StatusFailed
				updated.Progress = 1
				updated.ErrorMessage = err.Error()
				updated.FinishedAt = now
				updated.UpdatedAt = now
				_ = app.taskService.Repository().UpdateRuntime(updated)
			}
		}()
		deadline := time.Now().Add(750 * time.Millisecond)
		for {
			latest, err := app.taskService.Repository().Get(t.ID)
			if err != nil {
				return task.DTO{}, err
			}
			if latest.Status == task.StatusRunning || latest.Status == task.StatusFailed || latest.Status == task.StatusSuccess {
				return task.ToDTO(latest), nil
			}
			if time.Now().After(deadline) {
				return task.ToDTO(latest), nil
			}
			time.Sleep(50 * time.Millisecond)
		}
	}
	children, err := app.taskService.Repository().ListChildren(t.ID)
	if err != nil {
		return task.DTO{}, err
	}
	if len(children) == 0 {
		if err := app.initializeStrategyEvaluation(t); err != nil {
			return task.DTO{}, err
		}
		children, err = app.taskService.Repository().ListChildren(t.ID)
		if err != nil {
			return task.DTO{}, err
		}
	}
	now := time.Now()
	for _, child := range children {
		if child.Status == task.StatusCancelled || child.Status == task.StatusInterrupted {
			child.Status = task.StatusCreated
			child.Progress = 0
			child.WorkerPID = 0
			child.ErrorMessage = ""
			child.StartedAt = time.Time{}
			child.FinishedAt = time.Time{}
			child.UpdatedAt = now
			_ = app.taskService.Repository().UpdateRuntime(child)
		}
	}
	children, err = app.taskService.Repository().ListChildren(t.ID)
	if err != nil {
		return task.DTO{}, err
	}
	t.Status = task.StatusRunning
	t.Progress = portfolioParentProgress(children)
	t.WorkerPID = 0
	t.ErrorMessage = ""
	t.Total = len(children)
	t.StartedAt = now
	t.FinishedAt = time.Time{}
	t.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(t); err != nil {
		return task.DTO{}, err
	}
	go app.runStrategyEvaluationChildren(t)
	return task.ToDTO(t), nil
}

func (app *App) runStrategyEvaluationChildren(parent task.Task) {
	for {
		latestParent, err := app.taskService.Repository().Get(parent.ID)
		if err != nil {
			app.finishStrategyEvaluationParent(parent, task.StatusFailed, err.Error(), nil)
			return
		}
		if latestParent.Status != task.StatusRunning {
			return
		}
		parent = latestParent
		children, err := app.taskService.Repository().ListChildren(parent.ID)
		if err != nil {
			app.finishStrategyEvaluationParent(parent, task.StatusFailed, err.Error(), children)
			return
		}
		next := firstRunnablePortfolioChild(children)
		if next == nil {
			app.finishStrategyEvaluationParent(parent, portfolioParentStatus(children), "", children)
			return
		}
		child, err := app.startStrategyEvaluationChildTaskSync(*next)
		if err != nil {
			if child.ID == "" {
				child = *next
			}
			if child.Status != task.StatusFailed && child.Status != task.StatusCancelled {
				child.Status = task.StatusFailed
				child.ErrorMessage = err.Error()
				child.Progress = 1
				child.WorkerPID = 0
				child.FinishedAt = time.Now()
				child.UpdatedAt = child.FinishedAt
				_ = app.taskService.Repository().UpdateRuntime(child)
			}
		}
		children, _ = app.taskService.Repository().ListChildren(parent.ID)
		parent.Progress = portfolioParentProgress(children)
		parent.SummaryJSON = app.strategyEvaluationSummaryForParent(parent, children)
		parent.UpdatedAt = time.Now()
		_ = app.taskService.Repository().UpdateStatus(parent)
		_ = app.taskService.Repository().UpdateRuntime(parent)
	}
}

func (app *App) startStrategyEvaluationChildTaskSync(t task.Task) (task.Task, error) {
	runID := t.GroupRunID
	if runID == "" {
		runID = t.ExternalRunID
	}
	if runID == "" {
		return t, errors.New("strategy evaluation child requires group run id")
	}
	params := task.ToDTO(t).Params
	startDate := stringParam(params, "start_date", "")
	endDate := stringParam(params, "end_date", "")
	strategyName := stringParam(params, "strategy", t.SubtaskKey)
	if startDate == "" || endDate == "" || strategyName == "" {
		return t, errors.New("strategy evaluation child requires start_date, end_date and strategy")
	}
	runPath := filepath.Join(app.settings.DataPath, "backtest_results", runID, strategyName)
	logPath := filepath.Join(runPath, "worker.log")
	if err := os.MkdirAll(runPath, 0o755); err != nil {
		return t, err
	}
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return t, err
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	args := []string{
		"scripts/evaluate_strategies.py",
		"--start", startDate,
		"--end", endDate,
		"--strategies", strategyName,
		"--baseline", stringParam(params, "baseline", "small_cap_quality"),
		"--benchmark", stringParam(params, "benchmark", "000905.SH"),
		"--save", runID,
		"--append-save",
		"--db-path", filepath.Join(app.settings.DataPath, "meta.db"),
		"--json",
	}
	if slippage := numberParam(params, "slippage", 0.002); slippage > 0 {
		args = append(args, "--slippage", trimFloat(slippage))
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(),
		"DATA_ROOT="+app.settings.DataPath,
		"DESKTOP_DB_PATH="+filepath.Join(app.settings.DataPath, "meta.db"),
		"DESKTOP_CONFIG_DB_PATH="+filepath.Join(app.settings.DataPath, "meta.db"),
	)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		return t, err
	}
	now := time.Now()
	t.Status = task.StatusRunning
	t.Progress = 0
	t.ResultPath = runPath
	t.LogPath = logPath
	t.WorkerPID = cmd.Process.Pid
	t.ExternalRunID = runID
	t.GroupRunID = runID
	t.ErrorMessage = ""
	t.Attempt++
	t.StartedAt = now
	t.FinishedAt = time.Time{}
	t.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(t); err != nil {
		_ = logFile.Close()
		return t, err
	}
	waitErr := cmd.Wait()
	_ = logFile.Close()
	finishedAt := time.Now()
	latest, latestErr := app.taskService.Repository().Get(t.ID)
	if latestErr == nil && latest.Status == task.StatusCancelled {
		return latest, nil
	}
	t.WorkerPID = 0
	t.Progress = 1
	t.UpdatedAt = finishedAt
	t.FinishedAt = finishedAt
	if waitErr != nil {
		t.Status = task.StatusFailed
		t.ErrorMessage = waitErr.Error()
		_ = app.taskService.Repository().UpdateRuntime(t)
		return t, waitErr
	}
	t.Status = task.StatusSuccess
	t.SummaryJSON = readStrategyEvaluationRowSummaryFromDB(app.database.Conn(), runID, strategyName)
	_ = app.taskService.Repository().UpdateRuntime(t)
	if t.SummaryJSON != "" {
		_ = app.taskService.Repository().UpdateStatus(t)
	}
	return t, nil
}

func (app *App) finishStrategyEvaluationParent(parent task.Task, status task.Status, message string, children []task.Task) {
	now := time.Now()
	parent.Status = status
	parent.Progress = portfolioParentProgress(children)
	if status == task.StatusSuccess {
		parent.Progress = 1
	}
	parent.WorkerPID = 0
	parent.ErrorMessage = message
	parent.SummaryJSON = app.strategyEvaluationSummaryForParent(parent, children)
	parent.FinishedAt = now
	parent.UpdatedAt = now
	_ = app.taskService.Repository().UpdateStatus(parent)
	_ = app.taskService.Repository().UpdateRuntime(parent)
}

func (app *App) strategyEvaluationSummaryForParent(parent task.Task, children []task.Task) string {
	summary := readStrategyEvaluationSummaryFromDB(app.database.Conn(), parent.ExternalRunID)
	payload := map[string]any{}
	if summary != "" {
		_ = json.Unmarshal([]byte(summary), &payload)
	} else if parent.SummaryJSON != "" {
		_ = json.Unmarshal([]byte(parent.SummaryJSON), &payload)
	}
	successChildren := 0
	failedChildren := 0
	runningChildren := 0
	for _, child := range children {
		switch child.Status {
		case task.StatusSuccess:
			successChildren++
		case task.StatusFailed, task.StatusCancelled, task.StatusInterrupted:
			failedChildren++
		case task.StatusRunning:
			runningChildren++
		}
	}
	payload["planned_count"] = len(children)
	payload["completed_count"] = successChildren
	payload["failed_task_count"] = failedChildren
	payload["running_count"] = runningChildren
	payload["progress"] = portfolioParentProgress(children)
	if _, ok := payload["strategy_count"]; !ok {
		payload["strategy_count"] = len(children)
	}
	if _, ok := payload["rows"]; !ok {
		payload["rows"] = []any{}
	}
	out, err := json.Marshal(payload)
	if err != nil {
		return parent.SummaryJSON
	}
	return string(out)
}

func (app *App) startPortfolioOptimizationTask(t task.Task) (task.DTO, error) {
	children, err := app.taskService.Repository().ListChildren(t.ID)
	if err != nil {
		return task.DTO{}, err
	}
	if len(children) == 0 {
		if err := app.initializePortfolioEvaluation(t); err != nil {
			return task.DTO{}, err
		}
		children, err = app.taskService.Repository().ListChildren(t.ID)
		if err != nil {
			return task.DTO{}, err
		}
	}
	now := time.Now()
	for _, child := range children {
		if child.Status == task.StatusCancelled || child.Status == task.StatusInterrupted {
			child.Status = task.StatusCreated
			child.Progress = 0
			child.WorkerPID = 0
			child.ErrorMessage = ""
			child.StartedAt = time.Time{}
			child.FinishedAt = time.Time{}
			child.UpdatedAt = now
			_ = app.taskService.Repository().UpdateRuntime(child)
		}
	}
	children, err = app.taskService.Repository().ListChildren(t.ID)
	if err != nil {
		return task.DTO{}, err
	}
	t.Status = task.StatusRunning
	t.Progress = portfolioParentProgress(children)
	t.WorkerPID = 0
	t.ErrorMessage = ""
	t.Total = len(children)
	t.StartedAt = now
	t.FinishedAt = time.Time{}
	t.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(t); err != nil {
		return task.DTO{}, err
	}
	go app.runPortfolioOptimizationChildren(t)
	return task.ToDTO(t), nil
}

func (app *App) runPortfolioOptimizationChildren(parent task.Task) {
	for {
		latestParent, err := app.taskService.Repository().Get(parent.ID)
		if err != nil {
			app.finishPortfolioParent(parent, task.StatusFailed, err.Error(), nil)
			return
		}
		if latestParent.Status != task.StatusRunning {
			return
		}
		parent = latestParent
		children, err := app.taskService.Repository().ListChildren(parent.ID)
		if err != nil {
			app.finishPortfolioParent(parent, task.StatusFailed, err.Error(), children)
			return
		}
		next := firstRunnablePortfolioChild(children)
		if next == nil {
			app.finishPortfolioParent(parent, portfolioParentStatus(children), "", children)
			return
		}
		child, err := app.startPortfolioCandidateTaskSync(*next)
		if err != nil {
			if child.ID == "" {
				child = *next
			}
			if child.Status != task.StatusFailed && child.Status != task.StatusCancelled {
				child.Status = task.StatusFailed
				child.ErrorMessage = err.Error()
				child.Progress = 1
				child.WorkerPID = 0
				child.FinishedAt = time.Now()
				child.UpdatedAt = child.FinishedAt
				_ = app.taskService.Repository().UpdateRuntime(child)
			}
		}
		children, _ = app.taskService.Repository().ListChildren(parent.ID)
		parent.Progress = portfolioParentProgress(children)
		parent.SummaryJSON = app.portfolioSummaryForParent(parent, children)
		parent.UpdatedAt = time.Now()
		_ = app.taskService.Repository().UpdateStatus(parent)
		_ = app.taskService.Repository().UpdateRuntime(parent)
	}
}

func (app *App) startPortfolioCandidateTask(t task.Task) (task.DTO, error) {
	go func() {
		updated, err := app.startPortfolioCandidateTaskSync(t)
		if err != nil && updated.WorkerPID == 0 && updated.Status != task.StatusFailed {
			now := time.Now()
			updated.Status = task.StatusFailed
			updated.Progress = 1
			updated.ErrorMessage = err.Error()
			updated.FinishedAt = now
			updated.UpdatedAt = now
			_ = app.taskService.Repository().UpdateRuntime(updated)
		}
	}()
	deadline := time.Now().Add(750 * time.Millisecond)
	for {
		latest, err := app.taskService.Repository().Get(t.ID)
		if err != nil {
			return task.DTO{}, err
		}
		if latest.Status == task.StatusRunning || latest.Status == task.StatusFailed || latest.Status == task.StatusSuccess {
			return task.ToDTO(latest), nil
		}
		if time.Now().After(deadline) {
			return task.ToDTO(latest), nil
		}
		time.Sleep(50 * time.Millisecond)
	}
}

func (app *App) startPortfolioCandidateTaskSync(t task.Task) (task.Task, error) {
	runID := t.GroupRunID
	if runID == "" {
		runID = t.ExternalRunID
	}
	if runID == "" {
		return t, errors.New("portfolio candidate requires group run id")
	}
	params := task.ToDTO(t).Params
	startDate := stringParam(params, "start_date", "")
	endDate := stringParam(params, "end_date", "")
	candidateID := stringParam(params, "candidate_id", t.SubtaskKey)
	candidateName := stringParam(params, "candidate_name", t.SubtaskName)
	if startDate == "" || endDate == "" || candidateID == "" {
		return t, errors.New("portfolio candidate requires start_date, end_date and candidate_id")
	}
	weightsJSON, err := json.Marshal(params["weights"])
	if err != nil {
		return t, err
	}
	schemeJSON, err := json.Marshal(params["scheme"])
	if err != nil {
		return t, err
	}
	exitJSON, err := json.Marshal(params["exit_architecture"])
	if err != nil {
		return t, err
	}
	runPath := filepath.Join(app.settings.DataPath, "backtest_results", runID, candidateID)
	logPath := filepath.Join(runPath, "worker.log")
	if err := os.MkdirAll(runPath, 0o755); err != nil {
		return t, err
	}
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return t, err
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	args := []string{
		"scripts/run_portfolio_candidate.py",
		"--start", startDate,
		"--end", endDate,
		"--candidate-id", candidateID,
		"--candidate-name", candidateName,
		"--weights-json", string(weightsJSON),
		"--scheme-json", string(schemeJSON),
		"--exit-json", string(exitJSON),
		"--rebalance-freq", strconv.Itoa(int(numberParam(params, "rebalance_freq", 5))),
		"--run-id", runID,
		"--benchmark", stringParam(params, "benchmark", "000905.SH"),
		"--objective", stringParam(params, "objective", "平衡"),
		"--db-path", filepath.Join(app.settings.DataPath, "meta.db"),
	}
	if slippage := numberParam(params, "slippage", 0.002); slippage > 0 {
		args = append(args, "--slippage", trimFloat(slippage))
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		_ = logFile.Close()
		return t, err
	}
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(),
		"DATA_ROOT="+app.settings.DataPath,
		"DESKTOP_DB_PATH="+filepath.Join(app.settings.DataPath, "meta.db"),
		"DESKTOP_CONFIG_DB_PATH="+filepath.Join(app.settings.DataPath, "meta.db"),
	)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		return t, err
	}
	now := time.Now()
	t.Status = task.StatusRunning
	t.Progress = 0
	t.ResultPath = runPath
	t.LogPath = logPath
	t.WorkerPID = cmd.Process.Pid
	t.ExternalRunID = runID
	t.GroupRunID = runID
	t.ErrorMessage = ""
	t.Attempt++
	t.StartedAt = now
	t.FinishedAt = time.Time{}
	t.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(t); err != nil {
		_ = logFile.Close()
		return t, err
	}
	scanner := bufio.NewScanner(stdout)
	for scanner.Scan() {
		line := scanner.Text()
		_, _ = logFile.WriteString(line + "\n")
		if event := parseWorkerEvent(line); event != nil {
			if progress, ok := event["progress"].(float64); ok {
				t.Progress = clamp(progress, 0, 1)
				t.UpdatedAt = time.Now()
				_ = app.taskService.Repository().UpdateRuntime(t)
			}
		}
	}
	scanErr := scanner.Err()
	waitErr := cmd.Wait()
	_ = logFile.Close()
	finishedAt := time.Now()
	latest, latestErr := app.taskService.Repository().Get(t.ID)
	if latestErr == nil && latest.Status == task.StatusCancelled {
		return latest, nil
	}
	t.WorkerPID = 0
	t.Progress = 1
	t.UpdatedAt = finishedAt
	t.FinishedAt = finishedAt
	if scanErr != nil {
		t.Status = task.StatusFailed
		t.ErrorMessage = scanErr.Error()
		_ = app.taskService.Repository().UpdateRuntime(t)
		return t, scanErr
	}
	if waitErr != nil {
		t.Status = task.StatusFailed
		t.ErrorMessage = waitErr.Error()
		_ = app.taskService.Repository().UpdateRuntime(t)
		return t, waitErr
	}
	t.Status = task.StatusSuccess
	t.SummaryJSON = readPortfolioCandidateSummaryFromDB(app.database.Conn(), runID, candidateID)
	_ = app.taskService.Repository().UpdateRuntime(t)
	if t.SummaryJSON != "" {
		_ = app.taskService.Repository().UpdateStatus(t)
	}
	_ = app.reRankPortfolioCandidates(runID)
	return t, nil
}

func firstRunnablePortfolioChild(children []task.Task) *task.Task {
	for idx := range children {
		child := children[idx]
		if child.Status == task.StatusSuccess || child.Status == task.StatusRunning || child.Status == task.StatusCancelled || child.Status == task.StatusInterrupted {
			continue
		}
		if child.MaxAttempts > 0 && child.Attempt >= child.MaxAttempts && child.Status == task.StatusFailed {
			continue
		}
		return &child
	}
	return nil
}

func portfolioParentProgress(children []task.Task) float64 {
	if len(children) == 0 {
		return 0
	}
	done := 0.0
	for _, child := range children {
		if child.Status == task.StatusSuccess || child.Status == task.StatusFailed || child.Status == task.StatusCancelled || child.Status == task.StatusInterrupted {
			done += 1
		} else if child.Status == task.StatusRunning {
			done += clamp(child.Progress, 0, 1)
		}
	}
	return clamp(done/float64(len(children)), 0, 1)
}

func portfolioParentStatus(children []task.Task) task.Status {
	if len(children) == 0 {
		return task.StatusFailed
	}
	failed := 0
	for _, child := range children {
		switch child.Status {
		case task.StatusCreated, task.StatusQueued, task.StatusRunning:
			return task.StatusRunning
		case task.StatusFailed, task.StatusCancelled, task.StatusInterrupted:
			failed++
		}
	}
	if failed > 0 {
		return task.StatusFailed
	}
	return task.StatusSuccess
}

func (app *App) finishPortfolioParent(parent task.Task, status task.Status, message string, children []task.Task) {
	now := time.Now()
	parent.Status = status
	parent.Progress = portfolioParentProgress(children)
	if status == task.StatusSuccess {
		parent.Progress = 1
	}
	parent.WorkerPID = 0
	parent.ErrorMessage = message
	parent.SummaryJSON = app.portfolioSummaryForParent(parent, children)
	parent.FinishedAt = now
	parent.UpdatedAt = now
	_ = app.taskService.Repository().UpdateStatus(parent)
	_ = app.taskService.Repository().UpdateRuntime(parent)
}

func (app *App) portfolioSummaryForParent(parent task.Task, children []task.Task) string {
	summary := readPortfolioOptimizationSummaryFromDB(app.database.Conn(), parent.ExternalRunID)
	payload := map[string]any{}
	if summary != "" {
		_ = json.Unmarshal([]byte(summary), &payload)
	} else if parent.SummaryJSON != "" {
		_ = json.Unmarshal([]byte(parent.SummaryJSON), &payload)
	}
	parentPayload := map[string]any{}
	if parent.SummaryJSON != "" {
		_ = json.Unmarshal([]byte(parent.SummaryJSON), &parentPayload)
		copyAISummaryFields(payload, parentPayload)
	}
	completed := 0
	failed := 0
	running := 0
	for _, child := range children {
		switch child.Status {
		case task.StatusSuccess:
			completed++
		case task.StatusFailed, task.StatusCancelled, task.StatusInterrupted:
			failed++
		case task.StatusRunning:
			running++
		}
	}
	payload["planned_count"] = len(children)
	payload["completed_count"] = completed
	payload["failed_count"] = failed
	payload["running_count"] = running
	payload["progress"] = portfolioParentProgress(children)
	out, err := json.Marshal(payload)
	if err != nil {
		return parent.SummaryJSON
	}
	_, _ = app.database.Conn().Exec(`UPDATE portfolio_optimization_runs SET summary_json = ?, updated_at = datetime('now') WHERE run_id = ?`, string(out), parent.ExternalRunID)
	return string(out)
}

func copyAISummaryFields(dst map[string]any, src map[string]any) {
	for _, key := range []string{
		"ai_analysis",
		"ai_recommendation",
		"ai_next_eval_config",
		"ai_analysis_error",
		"ai_analysis_model",
		"ai_analysis_at",
	} {
		if value, ok := src[key]; ok {
			dst[key] = value
		}
	}
}

func (app *App) reRankPortfolioCandidates(runID string) error {
	rows, err := app.database.Conn().Query(`SELECT candidate_id, score FROM portfolio_optimization_candidates WHERE run_id = ? AND status = 'ok' ORDER BY score DESC`, runID)
	if err != nil {
		return err
	}
	defer rows.Close()
	type candidateScore struct {
		ID    string
		Score float64
	}
	items := make([]candidateScore, 0)
	for rows.Next() {
		var item candidateScore
		if err := rows.Scan(&item.ID, &item.Score); err != nil {
			return err
		}
		items = append(items, item)
	}
	if err := rows.Err(); err != nil {
		return err
	}
	for idx, item := range items {
		if _, err := app.database.Conn().Exec(`UPDATE portfolio_optimization_candidates SET rank = ?, updated_at = datetime('now') WHERE run_id = ? AND candidate_id = ?`, idx+1, runID, item.ID); err != nil {
			return err
		}
	}
	return nil
}

func readPortfolioCandidateSummaryFromDB(db *sql.DB, runID string, candidateID string) string {
	row := db.QueryRow(`SELECT payload_json FROM portfolio_optimization_candidates WHERE run_id = ? AND candidate_id = ?`, runID, candidateID)
	var payloadJSON string
	if err := row.Scan(&payloadJSON); err != nil {
		return ""
	}
	return payloadJSON
}

func parseWorkerEvent(line string) map[string]any {
	line = strings.TrimSpace(line)
	if line == "" || !strings.HasPrefix(line, "{") {
		return nil
	}
	var event map[string]any
	if err := json.Unmarshal([]byte(line), &event); err != nil {
		return nil
	}
	return event
}

func clamp(value float64, min float64, max float64) float64 {
	if value < min {
		return min
	}
	if value > max {
		return max
	}
	return value
}

func (app *App) CancelTask(id string) (task.DTO, error) {
	if err := app.ensureTaskService(); err != nil {
		return task.DTO{}, err
	}
	t, err := app.taskService.Repository().Get(id)
	if err != nil {
		return task.DTO{}, err
	}
	if t.TaskType == task.TypePortfolioOptimization && t.ParentID == "" {
		children, _ := app.taskService.Repository().ListChildren(t.ID)
		for _, child := range children {
			if child.Status == task.StatusRunning && child.WorkerPID > 0 {
				_ = worker.NewManager().Cancel(child.WorkerPID)
				child.Status = task.StatusCancelled
				child.WorkerPID = 0
				child.ErrorMessage = "parent task cancelled"
				child.FinishedAt = time.Now()
				child.UpdatedAt = child.FinishedAt
				_ = app.taskService.Repository().UpdateRuntime(child)
			}
		}
		t.Status = task.StatusCancelled
		t.WorkerPID = 0
		t.ErrorMessage = "task cancelled"
		t.Progress = portfolioParentProgress(children)
		t.FinishedAt = time.Now()
		t.UpdatedAt = t.FinishedAt
		_ = app.taskService.Repository().UpdateRuntime(t)
		return task.ToDTO(t), nil
	}
	if t.TaskType == task.TypeStrategyEvaluation && t.ParentID == "" {
		children, _ := app.taskService.Repository().ListChildren(t.ID)
		for _, child := range children {
			if child.Status == task.StatusRunning && child.WorkerPID > 0 {
				_ = worker.NewManager().Cancel(child.WorkerPID)
				child.Status = task.StatusCancelled
				child.WorkerPID = 0
				child.ErrorMessage = "parent task cancelled"
				child.FinishedAt = time.Now()
				child.UpdatedAt = child.FinishedAt
				_ = app.taskService.Repository().UpdateRuntime(child)
			}
		}
		t.Status = task.StatusCancelled
		t.WorkerPID = 0
		t.ErrorMessage = "task cancelled"
		t.Progress = portfolioParentProgress(children)
		t.FinishedAt = time.Now()
		t.UpdatedAt = t.FinishedAt
		t.SummaryJSON = app.strategyEvaluationSummaryForParent(t, children)
		_ = app.taskService.Repository().UpdateStatus(t)
		_ = app.taskService.Repository().UpdateRuntime(t)
		return task.ToDTO(t), nil
	}
	if t.WorkerPID > 0 {
		_ = worker.NewManager().Cancel(t.WorkerPID)
	}

	// 取消状态由 Python SIGTERM handler 写入 SQLite。Go 只负责发取消信号。
	for i := 0; i < 10; i++ {
		time.Sleep(200 * time.Millisecond)
		latest, getErr := app.taskService.Repository().Get(id)
		if getErr != nil {
			return task.DTO{}, getErr
		}
		if latest.Status == task.StatusCancelled || latest.Status == task.StatusInterrupted || latest.Status == task.StatusFailed || latest.Status == task.StatusSuccess {
			return task.ToDTO(latest), nil
		}
	}
	latest, err := app.taskService.Repository().Get(id)
	if err != nil {
		return task.DTO{}, err
	}
	return task.ToDTO(latest), nil
}

func (app *App) quantStockCorePath() string {
	candidates := []string{
		filepath.Join(filepath.Dir(app.settings.DataPath), "quant_stock_core"),
		filepath.Join(mustGetwd(), "..", "quant_stock_core"),
	}
	for _, candidate := range candidates {
		clean := filepath.Clean(candidate)
		if info, err := os.Stat(filepath.Join(clean, "trading", "execution", "time_machine.py")); err == nil && !info.IsDir() {
			return clean
		}
	}
	return filepath.Clean(filepath.Join(filepath.Dir(app.settings.DataPath), "quant_stock_core"))
}

func pythonPathForCore(quantRoot string) string {
	if w := bundledWorkerPath(); w != "" {
		return w
	}
	candidate := filepath.Join(quantRoot, ".venv", "bin", "python")
	if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
		return candidate
	}
	return "python3"
}

// bundledWorkerPath returns the path to the embedded quant_worker binary
// when running inside a macOS .app bundle, or an empty string otherwise.
func bundledWorkerPath() string {
	exe, err := os.Executable()
	if err != nil {
		return ""
	}
	exe, err = filepath.EvalSymlinks(exe)
	if err != nil {
		return ""
	}
	// Inside .app: .../QuantStockDesktop.app/Contents/MacOS/QuantStockDesktop
	// Resources is sibling of MacOS:  .../Contents/Resources/quant_worker/quant_worker
	macosDir := filepath.Dir(exe)
	contentsDir := filepath.Dir(macosDir)
	candidate := filepath.Join(contentsDir, "Resources", "quant_worker", "quant_worker")
	if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
		return candidate
	}
	return ""
}

func (app *App) ensureTaskService() error {
	if app.taskService != nil {
		return nil
	}
	if err := app.ensureDatabase(); err != nil {
		return err
	}
	if app.database == nil {
		return errors.New("database is not initialized")
	}
	app.taskService = task.NewService(task.NewRepository(app.database.Conn()))
	return nil
}

func (app *App) ensureMarketService() error {
	if app.marketService != nil {
		return nil
	}
	if err := app.ensureDatabase(); err != nil {
		return err
	}
	if app.database == nil {
		return errors.New("database is not initialized")
	}
	app.marketService = market.NewService(market.NewRepository(app.database.Conn()))
	return nil
}

func (app *App) ensurePositionService() error {
	if app.positionService != nil {
		return nil
	}
	if err := app.ensureMarketService(); err != nil {
		return err
	}
	app.positionService = position.NewService(app.marketService, app.database.Conn())
	return nil
}

func (app *App) reopenDatabase() error {
	if app.database != nil {
		_ = app.database.Close()
		app.database = nil
		app.taskService = nil
		app.marketService = nil
		app.positionService = nil
		app.datafetchService = nil
	}
	return app.ensureDatabase()
}

func (app *App) ensureDatabase() error {
	if app.settings.DataPath == "" {
		return nil
	}
	if app.database != nil {
		return nil
	}
	dbPath := filepath.Join(app.settings.DataPath, "meta.db")
	if err := os.MkdirAll(filepath.Dir(dbPath), 0o755); err != nil {
		return err
	}
	db, err := database.Open(dbPath)
	if err != nil {
		return err
	}
	app.database = db
	app.configService.WithDB(db.Conn())
	if settings, err := app.configService.Load(app.settings); err == nil {
		app.settings = settings
	}
	app.taskService = task.NewService(task.NewRepository(db.Conn()))
	app.marketService = market.NewService(market.NewRepository(db.Conn()))
	app.positionService = position.NewService(app.marketService, app.database.Conn())
	return nil
}

func mustGetwd() string {
	wd, err := os.Getwd()
	if err != nil {
		return "."
	}
	return wd
}
