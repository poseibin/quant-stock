package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
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
	if settings.DataPath == "" && settings.WorkspacePath != "" {
		settings.DataPath = filepath.Join(settings.WorkspacePath, "data_store")
	}
	previousWorkspace := app.settings.WorkspacePath
	app.settings = settings
	if settings.WorkspacePath != previousWorkspace {
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

func enrichStrategyEvaluationSummary(payload map[string]any) {
	rows, _ := payload["rows"].([]any)
	success := 0
	empty := 0
	failed := 0
	admit := 0
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
	rows, err := db.Query(`SELECT payload_json FROM portfolio_optimization_candidates
		WHERE run_id = ? ORDER BY rank`, runID)
	if err != nil {
		return ""
	}
	defer rows.Close()
	items := make([]any, 0)
	for rows.Next() {
		var payloadJSON string
		if err := rows.Scan(&payloadJSON); err != nil {
			return ""
		}
		var item map[string]any
		if err := json.Unmarshal([]byte(payloadJSON), &item); err == nil {
			items = append(items, item)
		}
	}
	if err := rows.Err(); err != nil {
		return ""
	}
	payload["rows"] = items
	payload["candidate_count"] = len(items)
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
	return app.taskService.Create(req)
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
	runID := t.ExternalRunID
	if runID == "" {
		runID = "se_" + strings.ReplaceAll(t.ID, "-", "")
	}
	runPath := filepath.Join(app.settings.DataPath, "backtest_results", runID)
	logPath := filepath.Join(runPath, "worker.log")
	if err := os.MkdirAll(runPath, 0o755); err != nil {
		return task.DTO{}, err
	}
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return task.DTO{}, err
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	params := task.ToDTO(t).Params
	startDate := stringParam(params, "start_date", "")
	endDate := stringParam(params, "end_date", "")
	if startDate == "" || endDate == "" {
		_ = logFile.Close()
		return task.DTO{}, errors.New("strategy evaluation requires start_date and end_date")
	}
	args := []string{
		"scripts/evaluate_strategies.py",
		"--start", startDate,
		"--end", endDate,
		"--strategies", strategyParam(params["strategies"]),
		"--baseline", stringParam(params, "baseline", "small_cap_quality"),
		"--benchmark", stringParam(params, "benchmark", "000905.SH"),
		"--save", runID,
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
		return task.DTO{}, err
	}
	now := time.Now()
	t.Status = task.StatusRunning
	t.Progress = 0
	t.ResultPath = runPath
	t.LogPath = logPath
	t.WorkerPID = cmd.Process.Pid
	t.ExternalRunID = runID
	t.ErrorMessage = ""
	t.StartedAt = now
	t.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(t); err != nil {
		_ = logFile.Close()
		return task.DTO{}, err
	}
	go app.waitStrategyEvaluation(cmd, logFile, t)
	return task.ToDTO(t), nil
}

func (app *App) waitStrategyEvaluation(cmd *exec.Cmd, logFile *os.File, t task.Task) {
	err := cmd.Wait()
	_ = logFile.Close()
	finishedAt := time.Now()
	t.WorkerPID = 0
	t.Progress = 1
	t.UpdatedAt = finishedAt
	t.FinishedAt = finishedAt
	if err != nil {
		t.Status = task.StatusFailed
		t.ErrorMessage = err.Error()
		_ = app.taskService.Repository().UpdateRuntime(t)
		return
	}
	t.Status = task.StatusSuccess
	t.SummaryJSON = readStrategyEvaluationSummaryFromDB(app.database.Conn(), t.ExternalRunID)
	if t.SummaryJSON == "" {
		t.SummaryJSON = readStrategyEvaluationSummaryFromFile(t.ResultPath)
	}
	if t.SummaryJSON != "" {
		_ = app.taskService.Repository().UpdateStatus(t)
	}
	_ = app.taskService.Repository().UpdateRuntime(t)
}

func (app *App) startPortfolioOptimizationTask(t task.Task) (task.DTO, error) {
	runID := t.ExternalRunID
	if runID == "" {
		runID = "po_" + strings.ReplaceAll(t.ID, "-", "")
	}
	runPath := filepath.Join(app.settings.DataPath, "backtest_results", runID)
	logPath := filepath.Join(runPath, "worker.log")
	if err := os.MkdirAll(runPath, 0o755); err != nil {
		return task.DTO{}, err
	}
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return task.DTO{}, err
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	params := task.ToDTO(t).Params
	startDate := stringParam(params, "start_date", "")
	endDate := stringParam(params, "end_date", "")
	if startDate == "" || endDate == "" {
		_ = logFile.Close()
		return task.DTO{}, errors.New("portfolio optimization requires start_date and end_date")
	}
	args := []string{
		"scripts/optimize_portfolio.py",
		"--start", startDate,
		"--end", endDate,
		"--strategies", strategyParam(params["strategies"]),
		"--benchmark", stringParam(params, "benchmark", "000905.SH"),
		"--objective", stringParam(params, "objective", "平衡"),
		"--max-candidates", trimFloat(numberParam(params, "max_candidates", 40)),
		"--top-n", trimFloat(numberParam(params, "top_n", 10)),
		"--save", runID,
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
		return task.DTO{}, err
	}
	now := time.Now()
	t.Status = task.StatusRunning
	t.Progress = 0
	t.ResultPath = runPath
	t.LogPath = logPath
	t.WorkerPID = cmd.Process.Pid
	t.ExternalRunID = runID
	t.ErrorMessage = ""
	t.StartedAt = now
	t.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(t); err != nil {
		_ = logFile.Close()
		return task.DTO{}, err
	}
	go app.waitPortfolioOptimization(cmd, logFile, t)
	return task.ToDTO(t), nil
}

func (app *App) waitPortfolioOptimization(cmd *exec.Cmd, logFile *os.File, t task.Task) {
	err := cmd.Wait()
	_ = logFile.Close()
	finishedAt := time.Now()
	t.WorkerPID = 0
	t.Progress = 1
	t.UpdatedAt = finishedAt
	t.FinishedAt = finishedAt
	if err != nil {
		t.Status = task.StatusFailed
		t.ErrorMessage = err.Error()
		_ = app.taskService.Repository().UpdateRuntime(t)
		return
	}
	t.Status = task.StatusSuccess
	t.SummaryJSON = readPortfolioOptimizationSummaryFromDB(app.database.Conn(), t.ExternalRunID)
	if t.SummaryJSON != "" {
		_ = app.taskService.Repository().UpdateStatus(t)
	}
	_ = app.taskService.Repository().UpdateRuntime(t)
}

func (app *App) CancelTask(id string) (task.DTO, error) {
	if err := app.ensureTaskService(); err != nil {
		return task.DTO{}, err
	}
	t, err := app.taskService.Repository().Get(id)
	if err != nil {
		return task.DTO{}, err
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
		filepath.Join(filepath.Dir(app.settings.WorkspacePath), "quant_stock_core"),
		filepath.Join(app.settings.WorkspacePath, "..", "quant_stock_core"),
		filepath.Join(filepath.Dir(app.settings.DataPath), "quant_stock_core"),
	}
	for _, candidate := range candidates {
		clean := filepath.Clean(candidate)
		if info, err := os.Stat(filepath.Join(clean, "trading", "execution", "time_machine.py")); err == nil && !info.IsDir() {
			return clean
		}
	}
	return filepath.Clean(filepath.Join(filepath.Dir(app.settings.WorkspacePath), "quant_stock_core"))
}

func pythonPathForCore(quantRoot string) string {
	candidate := filepath.Join(quantRoot, ".venv", "bin", "python")
	if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
		return candidate
	}
	return "python3"
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
