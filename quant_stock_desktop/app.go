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
	"math"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
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
		settings.DataPath = app.fixedDataPath()
		app.settings = settings
		_ = app.configService.Save(app.settings)
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

type StrategyVersionDTO struct {
	Strategy        string         `json:"strategy"`
	Version         int            `json:"version"`
	Label           string         `json:"label"`
	Config          map[string]any `json:"config"`
	IsActive        bool           `json:"is_active"`
	PromotionStatus string         `json:"promotion_status"`
	Validation      map[string]any `json:"validation"`
	Source          string         `json:"source"`
	Note            string         `json:"note"`
	CreatedAt       string         `json:"created_at"`
	ActivatedAt     string         `json:"activated_at"`
}

type StrategyVersionActivateRequest struct {
	Strategy string `json:"strategy"`
	Version  int    `json:"version"`
}

type StrategyVersionStatusRequest struct {
	Strategy string `json:"strategy"`
	Version  int    `json:"version"`
	Status   string `json:"status"`
}

type ValidationReviewDTO struct {
	ID              string         `json:"id"`
	SubjectType     string         `json:"subject_type"`
	SubjectID       string         `json:"subject_id"`
	Strategy        string         `json:"strategy"`
	StrategyVersion int            `json:"strategy_version"`
	SourceRunID     string         `json:"source_run_id"`
	Status          string         `json:"status"`
	Score           float64        `json:"score"`
	Gates           map[string]any `json:"gates"`
	Metrics         map[string]any `json:"metrics"`
	Recommendation  string         `json:"recommendation"`
	CreatedAt       string         `json:"created_at"`
	UpdatedAt       string         `json:"updated_at"`
}

type ResearchReportDTO struct {
	ID          string         `json:"id"`
	SubjectType string         `json:"subject_type"`
	SubjectID   string         `json:"subject_id"`
	ReportType  string         `json:"report_type"`
	Title       string         `json:"title"`
	Model       string         `json:"model"`
	ContentMD   string         `json:"content_md"`
	Payload     map[string]any `json:"payload"`
	CreatedAt   string         `json:"created_at"`
}

type DataSnapshotDTO struct {
	ID          string         `json:"id"`
	SubjectType string         `json:"subject_type"`
	SubjectID   string         `json:"subject_id"`
	Snapshot    map[string]any `json:"snapshot"`
	CreatedAt   string         `json:"created_at"`
}

type ValidationEvidenceQuery struct {
	SubjectType string `json:"subject_type"`
	SubjectID   string `json:"subject_id"`
	SourceRunID string `json:"source_run_id"`
	Limit       int    `json:"limit"`
}

type ValidationEvidenceDTO struct {
	Reviews   []ValidationReviewDTO `json:"reviews"`
	Reports   []ResearchReportDTO   `json:"reports"`
	Snapshots []DataSnapshotDTO     `json:"snapshots"`
}

type RecommendationHindsightDTO struct {
	ID                 string         `json:"id"`
	RecommendationDate string         `json:"recommendation_date"`
	HorizonDays        int            `json:"horizon_days"`
	NextDate           string         `json:"next_date"`
	NHoldings          int            `json:"n_holdings"`
	NEval              int            `json:"n_eval"`
	WeightedReturn     *float64       `json:"weighted_return"`
	EqualWeightReturn  *float64       `json:"equal_weight_return"`
	HitRate            *float64       `json:"hit_rate"`
	Payload            map[string]any `json:"payload"`
	CreatedAt          string         `json:"created_at"`
	UpdatedAt          string         `json:"updated_at"`
}

type RiskExposureDTO struct {
	ID              string         `json:"id"`
	SubjectType     string         `json:"subject_type"`
	SubjectID       string         `json:"subject_id"`
	AsOfDate        string         `json:"as_of_date"`
	NHoldings       int            `json:"n_holdings"`
	TotalWeight     float64        `json:"total_weight"`
	MaxSingleWeight float64        `json:"max_single_weight"`
	Top5Weight      float64        `json:"top5_weight"`
	Industry        map[string]any `json:"industry"`
	Strategy        map[string]any `json:"strategy"`
	Payload         map[string]any `json:"payload"`
	CreatedAt       string         `json:"created_at"`
}

type PaperTradingLogDTO struct {
	ID           string         `json:"id"`
	SignalDate   string         `json:"signal_date"`
	TSCode       string         `json:"ts_code"`
	Name         string         `json:"name"`
	Action       string         `json:"action"`
	TargetWeight float64        `json:"target_weight"`
	ActualWeight *float64       `json:"actual_weight"`
	Status       string         `json:"status"`
	Reason       string         `json:"reason"`
	Payload      map[string]any `json:"payload"`
	CreatedAt    string         `json:"created_at"`
	UpdatedAt    string         `json:"updated_at"`
}

type PromotionDecisionDTO struct {
	ID                string         `json:"id"`
	Strategy          string         `json:"strategy"`
	StrategyVersion   int            `json:"strategy_version"`
	CurrentStatus     string         `json:"current_status"`
	RecommendedStatus string         `json:"recommended_status"`
	Score             float64        `json:"score"`
	Reason            string         `json:"reason"`
	Payload           map[string]any `json:"payload"`
	CreatedAt         string         `json:"created_at"`
	UpdatedAt         string         `json:"updated_at"`
}

type WalkForwardWindowDTO struct {
	ID          string         `json:"id"`
	SubjectType string         `json:"subject_type"`
	SubjectID   string         `json:"subject_id"`
	WindowName  string         `json:"window_name"`
	StartDate   string         `json:"start_date"`
	EndDate     string         `json:"end_date"`
	Status      string         `json:"status"`
	Score       float64        `json:"score"`
	Metrics     map[string]any `json:"metrics"`
	CreatedAt   string         `json:"created_at"`
	UpdatedAt   string         `json:"updated_at"`
}

type ParameterExperimentDTO struct {
	ID              string         `json:"id"`
	Strategy        string         `json:"strategy"`
	StrategyVersion int            `json:"strategy_version"`
	ParamSet        string         `json:"param_set"`
	Status          string         `json:"status"`
	Score           float64        `json:"score"`
	Params          map[string]any `json:"params"`
	Metrics         map[string]any `json:"metrics"`
	CreatedAt       string         `json:"created_at"`
	UpdatedAt       string         `json:"updated_at"`
}

type GovernanceDashboardDTO struct {
	Hindsight                []RecommendationHindsightDTO `json:"hindsight"`
	Risk                     []RiskExposureDTO            `json:"risk"`
	Paper                    []PaperTradingLogDTO         `json:"paper"`
	Promotion                []PromotionDecisionDTO       `json:"promotion"`
	Walk                     []WalkForwardWindowDTO       `json:"walk"`
	Params                   []ParameterExperimentDTO     `json:"params"`
	DataQuality              map[string]any               `json:"data_quality"`
	ParameterRecommendations []map[string]any             `json:"parameter_recommendations"`
	Retirement               []map[string]any             `json:"retirement"`
	PortfolioAttribution     []map[string]any             `json:"portfolio_attribution"`
	Recovery                 map[string]any               `json:"recovery"`
	Reports                  []ResearchReportDTO          `json:"reports"`
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
		settings.DataPath = app.fixedDataPath()
		app.settings = settings
		_ = app.configService.Save(app.settings)
	}
	return SettingsResponse{
		Settings: app.settings,
		Issues:   app.configService.Validate(app.settings),
	}
}

func (app *App) SaveSettings(settings config.Settings) SettingsResponse {
	settings.DataPath = app.fixedDataPath()
	issues := app.configService.Validate(settings)
	if len(issues) > 0 {
		return SettingsResponse{
			Settings: settings,
			Issues:   issues,
		}
	}
	app.settings = settings
	_ = app.ensureDatabase()
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

func (app *App) ListStrategyVersions(strategy string) ([]StrategyVersionDTO, error) {
	if err := app.ensureDatabase(); err != nil {
		return nil, err
	}
	query := `SELECT strategy, version, label, config_json, is_active, COALESCE(promotion_status,'research'),
		COALESCE(validation_json,'{}'), COALESCE(source,''), COALESCE(note,''), created_at, COALESCE(activated_at,'')
		FROM strategy_settings_versions`
	args := []any{}
	if strings.TrimSpace(strategy) != "" {
		query += ` WHERE strategy = ?`
		args = append(args, strings.TrimSpace(strategy))
	}
	query += ` ORDER BY strategy, version DESC`
	rows, err := app.database.Conn().Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []StrategyVersionDTO{}
	for rows.Next() {
		var item StrategyVersionDTO
		var configJSON string
		var active int
		var validationJSON string
		if err := rows.Scan(&item.Strategy, &item.Version, &item.Label, &configJSON, &active, &item.PromotionStatus, &validationJSON, &item.Source, &item.Note, &item.CreatedAt, &item.ActivatedAt); err != nil {
			return nil, err
		}
		item.IsActive = active == 1
		item.Config = map[string]any{}
		item.Validation = map[string]any{}
		_ = json.Unmarshal([]byte(configJSON), &item.Config)
		_ = json.Unmarshal([]byte(validationJSON), &item.Validation)
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ActivateStrategyVersion(req StrategyVersionActivateRequest) (SettingsResponse, error) {
	if err := app.ensureDatabase(); err != nil {
		return SettingsResponse{}, err
	}
	strategyName := strings.TrimSpace(req.Strategy)
	if strategyName == "" || req.Version <= 0 {
		return SettingsResponse{}, errors.New("strategy and version are required")
	}
	row := app.database.Conn().QueryRow(`SELECT config_json FROM strategy_settings_versions WHERE strategy = ? AND version = ?`, strategyName, req.Version)
	var configJSON string
	if err := row.Scan(&configJSON); err != nil {
		return SettingsResponse{}, err
	}
	var strategyCfg config.StrategySettings
	if err := json.Unmarshal([]byte(configJSON), &strategyCfg); err != nil {
		return SettingsResponse{}, err
	}
	if app.database != nil {
		app.configService.WithDB(app.database.Conn())
	}
	settings, err := app.configService.Load(app.settings)
	if err != nil {
		return SettingsResponse{}, err
	}
	if settings.Strategies == nil {
		settings.Strategies = map[string]config.StrategySettings{}
	}
	settings.Strategies[strategyName] = strategyCfg
	settingsData, err := json.Marshal(settings)
	if err != nil {
		return SettingsResponse{}, err
	}
	now := time.Now().Format("2006-01-02T15:04:05")
	tx, err := app.database.Conn().Begin()
	if err != nil {
		return SettingsResponse{}, err
	}
	if _, err := tx.Exec(`UPDATE strategy_settings_versions SET is_active = 0 WHERE strategy = ?`, strategyName); err != nil {
		_ = tx.Rollback()
		return SettingsResponse{}, err
	}
	if _, err := tx.Exec(`UPDATE strategy_settings_versions SET is_active = 1, promotion_status = 'active', activated_at = ? WHERE strategy = ? AND version = ?`, now, strategyName, req.Version); err != nil {
		_ = tx.Rollback()
		return SettingsResponse{}, err
	}
	if _, err := tx.Exec(`INSERT INTO app_settings(key, value, updated_at) VALUES('settings', ?, ?)
		ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`, string(settingsData), now); err != nil {
		_ = tx.Rollback()
		return SettingsResponse{}, err
	}
	if err := tx.Commit(); err != nil {
		return SettingsResponse{}, err
	}
	app.settings = settings
	return SettingsResponse{Settings: app.settings, Issues: app.configService.Validate(app.settings)}, nil
}

func (app *App) SetStrategyVersionStatus(req StrategyVersionStatusRequest) ([]StrategyVersionDTO, error) {
	if err := app.ensureDatabase(); err != nil {
		return nil, err
	}
	strategyName := strings.TrimSpace(req.Strategy)
	status := strings.TrimSpace(req.Status)
	if strategyName == "" || req.Version <= 0 {
		return nil, errors.New("strategy and version are required")
	}
	allowed := map[string]bool{"research": true, "paper": true, "promotable": true, "rejected": true}
	if !allowed[status] {
		return nil, errors.New("unsupported strategy version status")
	}
	if status == "paper" {
		if _, err := app.database.Conn().Exec(`UPDATE strategy_settings_versions SET promotion_status = CASE WHEN version = ? THEN 'paper' WHEN promotion_status = 'paper' THEN 'research' ELSE promotion_status END WHERE strategy = ?`, req.Version, strategyName); err != nil {
			return nil, err
		}
	} else {
		if _, err := app.database.Conn().Exec(`UPDATE strategy_settings_versions SET promotion_status = ? WHERE strategy = ? AND version = ?`, status, strategyName, req.Version); err != nil {
			return nil, err
		}
	}
	return app.ListStrategyVersions(strategyName)
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

func (app *App) ClearPositionPool() (position.Summary, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.Summary{}, err
	}
	return app.positionService.ClearPool(app.settings.DataPath, app.settings.DefaultInitialCash)
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

func boolParam(params map[string]any, key string, fallback bool) bool {
	switch value := params[key].(type) {
	case bool:
		return value
	case string:
		parsed, err := strconv.ParseBool(strings.TrimSpace(value))
		if err == nil {
			return parsed
		}
	}
	return fallback
}

func mapParam(params map[string]any, key string) map[string]any {
	value, ok := params[key]
	if !ok || value == nil {
		return map[string]any{}
	}
	switch typed := value.(type) {
	case map[string]any:
		return cloneAnyMap(typed)
	case string:
		text := strings.TrimSpace(typed)
		if text == "" {
			return map[string]any{}
		}
		out := map[string]any{}
		if err := json.Unmarshal([]byte(text), &out); err == nil {
			return out
		}
	}
	return map[string]any{}
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
	if req.TaskType == task.TypeWalkForwardEvaluation {
		parent, err := app.taskService.Repository().Get(dto.ID)
		if err != nil {
			return task.DTO{}, err
		}
		if err := app.initializeWalkForwardEvaluation(parent); err != nil {
			return task.DTO{}, err
		}
		parent, err = app.taskService.Repository().Get(dto.ID)
		if err != nil {
			return task.DTO{}, err
		}
		return task.ToDTO(parent), nil
	}
	if req.TaskType == task.TypeParameterExperiment {
		parent, err := app.taskService.Repository().Get(dto.ID)
		if err != nil {
			return task.DTO{}, err
		}
		if err := app.initializeParameterExperiment(parent); err != nil {
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
		"start":                 startDate,
		"end":                   endDate,
		"benchmark":             stringParam(params, "benchmark", "000905.SH"),
		"baseline":              stringParam(params, "baseline", "small_cap_quality"),
		"strategy_version_mode": stringParam(params, "strategy_version_mode", "latest"),
		"strategy_count":        len(strategyNames),
		"planned_count":         len(strategyNames),
		"success_count":         0,
		"empty_count":           0,
		"failed_count":          0,
		"admit_count":           0,
		"limited_count":         0,
		"watch_count":           0,
		"reject_count":          0,
		"rows":                  []any{},
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
			"start_date":            startDate,
			"end_date":              endDate,
			"strategies":            strategyName,
			"strategy":              strategyName,
			"baseline":              stringParam(params, "baseline", "small_cap_quality"),
			"benchmark":             stringParam(params, "benchmark", "000905.SH"),
			"slippage":              numberParam(params, "slippage", 0.002),
			"strategy_version_mode": stringParam(params, "strategy_version_mode", "latest"),
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

func (app *App) initializeWalkForwardEvaluation(parent task.Task) error {
	if app.database == nil {
		if err := app.ensureDatabase(); err != nil {
			return err
		}
	}
	params := task.ToDTO(parent).Params
	startDate := stringParam(params, "start_date", "")
	endDate := stringParam(params, "end_date", "")
	if startDate == "" || endDate == "" {
		return errors.New("walk-forward requires start_date and end_date")
	}
	strategyNames := app.resolveStrategyAdmissionNames(params["strategies"])
	if len(strategyNames) == 0 {
		return errors.New("no strategy candidates generated")
	}
	windows := walkForwardWindows(startDate, endDate, int(numberParam(params, "window_count", 4)))
	if len(windows) == 0 {
		return errors.New("no walk-forward windows generated")
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
		runID = "wf_" + strings.ReplaceAll(parent.ID, "-", "")
	}
	parent.ExternalRunID = runID
	parent.Total = len(strategyNames) * len(windows)
	parent.Progress = 0
	parent.ResultPath = filepath.Join(app.settings.DataPath, "backtest_results", runID)
	parent.SummaryJSON = mustJSON(map[string]any{"start": startDate, "end": endDate, "windows": windows, "strategy_count": len(strategyNames), "planned_count": parent.Total, "rows": []any{}})
	parent.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(parent); err != nil {
		return err
	}
	seq := 0
	for _, window := range windows {
		for _, strategyName := range strategyNames {
			seq++
			childParams := map[string]any{
				"start_date":            window["start_date"],
				"end_date":              window["end_date"],
				"strategies":            strategyName,
				"strategy":              strategyName,
				"baseline":              stringParam(params, "baseline", "small_cap_quality"),
				"benchmark":             stringParam(params, "benchmark", "000905.SH"),
				"slippage":              numberParam(params, "slippage", 0.002),
				"strategy_version_mode": stringParam(params, "strategy_version_mode", "latest"),
				"walk_window":           window["name"],
			}
			paramsData, _ := json.Marshal(childParams)
			childRunID := fmt.Sprintf("%s_%s_%03d", runID, strings.ToLower(fmt.Sprint(window["name"])), seq)
			child := task.Task{ID: task.NewID(), Name: fmt.Sprintf("%s %s", app.strategyDisplayName(strategyName), window["name"]), TaskType: task.TypeStrategyEvaluation, Status: task.StatusCreated, ParamsJSON: string(paramsData), WorkerType: "python", ExternalRunID: childRunID, ParentID: parent.ID, GroupRunID: runID, SubtaskKey: fmt.Sprintf("%s:%s", strategyName, window["name"]), SubtaskName: fmt.Sprintf("%s %s", app.strategyDisplayName(strategyName), window["name"]), Sequence: seq, Total: parent.Total, MaxAttempts: 2, CreatedAt: now.Add(time.Duration(seq) * time.Millisecond), UpdatedAt: now}
			if err := app.taskService.Repository().Create(child); err != nil {
				return err
			}
		}
	}
	return nil
}

func (app *App) initializeParameterExperiment(parent task.Task) error {
	if app.database == nil {
		if err := app.ensureDatabase(); err != nil {
			return err
		}
	}
	params := task.ToDTO(parent).Params
	startDate := stringParam(params, "start_date", "")
	endDate := stringParam(params, "end_date", "")
	if startDate == "" || endDate == "" {
		return errors.New("parameter experiment requires start_date and end_date")
	}
	strategyNames := app.resolveStrategyAdmissionNames(params["strategies"])
	if len(strategyNames) == 0 {
		return errors.New("no strategy candidates generated")
	}
	experiments := parameterExperimentGrid()
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
		runID = "px_" + strings.ReplaceAll(parent.ID, "-", "")
	}
	parent.ExternalRunID = runID
	parent.Total = len(strategyNames) * len(experiments)
	parent.Progress = 0
	parent.ResultPath = filepath.Join(app.settings.DataPath, "backtest_results", runID)
	parent.SummaryJSON = mustJSON(map[string]any{"start": startDate, "end": endDate, "experiments": experiments, "strategy_count": len(strategyNames), "planned_count": parent.Total, "rows": []any{}})
	parent.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(parent); err != nil {
		return err
	}
	seq := 0
	for _, strategyName := range strategyNames {
		for _, experiment := range experiments {
			seq++
			childParams := map[string]any{
				"start_date":            startDate,
				"end_date":              endDate,
				"strategies":            strategyName,
				"strategy":              strategyName,
				"baseline":              stringParam(params, "baseline", "small_cap_quality"),
				"benchmark":             stringParam(params, "benchmark", "000905.SH"),
				"slippage":              numberParam(params, "slippage", 0.002),
				"strategy_version_mode": stringParam(params, "strategy_version_mode", "latest"),
				"strategy_overrides":    map[string]any{strategyName: experiment["override"]},
				"param_set":             experiment["name"],
			}
			paramsData, _ := json.Marshal(childParams)
			childRunID := fmt.Sprintf("%s_px_%03d", runID, seq)
			child := task.Task{ID: task.NewID(), Name: fmt.Sprintf("%s %s", app.strategyDisplayName(strategyName), experiment["name"]), TaskType: task.TypeStrategyEvaluation, Status: task.StatusCreated, ParamsJSON: string(paramsData), WorkerType: "python", ExternalRunID: childRunID, ParentID: parent.ID, GroupRunID: runID, SubtaskKey: fmt.Sprintf("%s:%s", strategyName, experiment["name"]), SubtaskName: fmt.Sprintf("%s %s", app.strategyDisplayName(strategyName), experiment["name"]), Sequence: seq, Total: parent.Total, MaxAttempts: 2, CreatedAt: now.Add(time.Duration(seq) * time.Millisecond), UpdatedAt: now}
			if err := app.taskService.Repository().Create(child); err != nil {
				return err
			}
		}
	}
	return nil
}

type portfolioCandidatePlan struct {
	ID                string             `json:"candidate_id"`
	Name              string             `json:"name"`
	Weights           map[string]float64 `json:"weights"`
	ExitArchitecture  map[string]any     `json:"exit_architecture"`
	PositionRule      map[string]any     `json:"position_rule"`
	RebalanceFreq     int                `json:"rebalance_freq"`
	RiskRule          map[string]any     `json:"risk_rule"`
	StrategyOverrides map[string]any     `json:"strategy_overrides,omitempty"`
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
	strategyOverrides := mapParam(params, "strategy_overrides")
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
	for idx := range candidates {
		candidates[idx].StrategyOverrides = cloneAnyMap(strategyOverrides)
	}

	now := time.Now()
	parent.Total = len(candidates)
	parent.Progress = 0
	parent.SummaryJSON = mustJSON(map[string]any{
		"start":                 startDate,
		"end":                   endDate,
		"objective":             objective,
		"benchmark":             benchmark,
		"strategy_count":        len(strategyNames),
		"candidate_count":       len(candidates),
		"planned_count":         len(candidates),
		"completed_count":       0,
		"failed_count":          0,
		"top_n":                 topN,
		"admission_used":        admissionFiltered,
		"strategy_overrides":    strategyOverrides,
		"strategy_version_mode": stringParam(params, "strategy_version_mode", "latest"),
		"rows":                  []any{},
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
			"start_date":            startDate,
			"end_date":              endDate,
			"candidate_id":          candidate.ID,
			"candidate_name":        candidate.Name,
			"weights":               candidate.Weights,
			"entry":                 map[string]any{"type": "strategy_weight_mix", "weights": candidate.Weights},
			"exit_architecture":     candidate.ExitArchitecture,
			"position_rule":         candidate.PositionRule,
			"rebalance_freq":        candidate.RebalanceFreq,
			"risk_rule":             candidate.RiskRule,
			"strategy_overrides":    candidate.StrategyOverrides,
			"strategy_version_mode": stringParam(params, "strategy_version_mode", "latest"),
			"scheme":                candidate.toSchemePayload(),
			"objective":             objective,
			"benchmark":             benchmark,
			"slippage":              numberParam(params, "slippage", 0.002),
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
		"scheme_type":        "trading_scheme",
		"name":               candidate.Name,
		"entry":              map[string]any{"type": "strategy_weight_mix", "weights": candidate.Weights},
		"exit_architecture":  candidate.ExitArchitecture,
		"position_rule":      candidate.PositionRule,
		"rebalance_freq":     candidate.RebalanceFreq,
		"risk_rule":          candidate.RiskRule,
		"strategy_overrides": candidate.StrategyOverrides,
		"research_space":     portfolioResearchSpace(),
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

func cloneAnyMap(value map[string]any) map[string]any {
	if len(value) == 0 {
		return map[string]any{}
	}
	data, err := json.Marshal(value)
	if err != nil {
		return cloneMap(value)
	}
	out := map[string]any{}
	if err := json.Unmarshal(data, &out); err != nil {
		return cloneMap(value)
	}
	return out
}

func (app *App) governanceRules() map[string]any {
	rules := defaultGovernanceRules()
	for key, value := range app.settings.GovernanceRules {
		rules[key] = value
	}
	return rules
}

func defaultGovernanceRules() map[string]any {
	return map[string]any{
		"min_promotable_score":          0.85,
		"min_research_score":            0.55,
		"min_paper_score":               0.85,
		"min_active_candidate_score":    0.85,
		"max_drawdown":                  0.22,
		"min_sharpe":                    0.30,
		"min_calmar":                    0.25,
		"max_turnover":                  0.45,
		"min_stability_rate":            0.45,
		"min_walk_forward_pass_rate":    0.50,
		"min_walk_forward_windows":      1,
		"min_parameter_stable_rate":     0.50,
		"require_positive_return":       true,
		"allow_missing_parameter_tests": true,
	}
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
		switch strings.TrimSpace(admission) {
		case "可启用", "限制启用":
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
	items, err := app.taskService.List(query)
	if err != nil {
		return nil, err
	}
	if app.database == nil || app.database.Conn() == nil {
		return items, nil
	}
	for index := range items {
		if items[index].TaskType != task.TypeStrategyEvaluation || items[index].ParentID == "" || items[index].GroupRunID == "" {
			continue
		}
		strategyName := stringParam(items[index].Params, "strategy", items[index].SubtaskKey)
		if strategyName == "" {
			continue
		}
		summaryJSON := readStrategyEvaluationRowSummaryFromDB(app.database.Conn(), items[index].GroupRunID, strategyName)
		if summaryJSON == "" {
			continue
		}
		var summary map[string]any
		if err := json.Unmarshal([]byte(summaryJSON), &summary); err == nil {
			items[index].Summary = summary
		}
	}
	return items, nil
}

func (app *App) GetTask(id string) (task.DTO, error) {
	if err := app.ensureTaskService(); err != nil {
		return task.DTO{}, err
	}
	t, err := app.taskService.Repository().Get(id)
	if err != nil {
		return task.DTO{}, err
	}
	if t.TaskType == task.TypeStrategyEvaluation && t.ParentID == "" {
		children, childErr := app.taskService.Repository().ListChildren(t.ID)
		if childErr == nil && len(children) > 0 {
			t.SummaryJSON = app.strategyEvaluationSummaryForParent(t, children)
			t.Progress = portfolioParentProgress(children)
			t.UpdatedAt = time.Now()
			_ = app.taskService.Repository().UpdateStatus(t)
			_ = app.taskService.Repository().UpdateRuntime(t)
		}
	}
	return task.ToDTO(t), nil
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
		return task.DTO{}, errors.New("方案评估还在运行，等全部子任务完成后再做量化优化分析")
	}
	if succeeded != planned {
		return task.DTO{}, fmt.Errorf("方案评估结果不完整：计划 %d 个，成功 %d 个，失败/取消 %d 个。请先重跑失败子任务，否则优化器不会基于残缺结果给出下一轮配置", planned, succeeded, failed)
	}
	contextPayload, err := app.buildPortfolioAnalysisContext(t, children)
	if err != nil {
		return task.DTO{}, err
	}
	analysis, recommendation := app.buildQuantPortfolioRecommendation(t, contextPayload)
	now := time.Now()
	summary := map[string]any{}
	if t.SummaryJSON != "" {
		_ = json.Unmarshal([]byte(t.SummaryJSON), &summary)
	}
	summary["ai_analysis"] = analysis
	summary["ai_recommendation"] = recommendation
	if nextEval, ok := recommendation["next_eval_config"].(map[string]any); ok {
		summary["ai_next_eval_config"] = normalizeNextEvalConfig(t, nextEval)
	}
	summary["ai_analysis_error"] = ""
	summary["ai_analysis_model"] = "quant_robust_rules_v1"
	summary["ai_analysis_at"] = now.Format(time.RFC3339)
	summary["quant_optimizer"] = "quant_robust_rules_v1"
	data, _ := json.Marshal(summary)
	t.SummaryJSON = string(data)
	t.UpdatedAt = now
	_ = app.taskService.Repository().UpdateStatus(t)
	if t.ExternalRunID != "" {
		validationJSON, _ := json.Marshal(map[string]any{
			"status":                "analyzed",
			"optimizer":             "quant_robust_rules_v1",
			"multiple_test_penalty": recommendation["multiple_test_penalty"],
			"data_snapshot":         app.captureDataSnapshot("portfolio_optimization", t.ExternalRunID),
			"analyzed_at":           now.Format(time.RFC3339),
		})
		_, _ = app.database.Conn().Exec(`UPDATE portfolio_optimization_runs SET summary_json = ?, validation_status = 'analyzed', validation_json = ?, updated_at = datetime('now') WHERE run_id = ?`, string(data), string(validationJSON), t.ExternalRunID)
	}
	app.saveResearchReport("portfolio_optimization", t.ExternalRunID, "optimizer_analysis", "方案评估优化分析", analysis, recommendation)
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

func (app *App) ReviewStrategyVersion(req StrategyVersionActivateRequest) (ValidationReviewDTO, error) {
	if err := app.ensureDatabase(); err != nil {
		return ValidationReviewDTO{}, err
	}
	strategyName := strings.TrimSpace(req.Strategy)
	if strategyName == "" {
		return ValidationReviewDTO{}, errors.New("strategy is required")
	}
	version := req.Version
	if version <= 0 {
		row := app.database.Conn().QueryRow(`SELECT version FROM strategy_settings_versions WHERE strategy = ? ORDER BY version DESC LIMIT 1`, strategyName)
		if err := row.Scan(&version); err != nil {
			return ValidationReviewDTO{}, err
		}
	}
	row := app.database.Conn().QueryRow(`SELECT run_id, annual_return, max_drawdown, sharpe, calmar, avg_turnover, monthly_win_rate, positive_3m_rate, payload_json
		FROM strategy_evaluation
		WHERE strategy = ? AND COALESCE(strategy_version, 0) = ?
		ORDER BY datetime(generated_at) DESC LIMIT 1`, strategyName, version)
	review := ValidationReviewDTO{
		ID:              "svr_" + strings.ReplaceAll(task.NewID(), "-", ""),
		SubjectType:     "strategy_version",
		SubjectID:       fmt.Sprintf("%s@%d", strategyName, version),
		Strategy:        strategyName,
		StrategyVersion: version,
		CreatedAt:       time.Now().Format(time.RFC3339),
		UpdatedAt:       time.Now().Format(time.RFC3339),
	}
	var payloadJSON string
	var annual, drawdown, sharpe, calmar, turnover, monthlyWin, positive3m sql.NullFloat64
	if err := row.Scan(&review.SourceRunID, &annual, &drawdown, &sharpe, &calmar, &turnover, &monthlyWin, &positive3m, &payloadJSON); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			review.Status = "research"
			review.Recommendation = "暂无对应版本的策略准入结果，先运行策略准入评估"
			review.Gates = map[string]any{"has_evaluation": false}
			review.Metrics = map[string]any{"data_snapshot": app.captureDataSnapshot("strategy_version", review.SubjectID)}
			return app.persistValidationReview(review)
		}
		return ValidationReviewDTO{}, err
	}
	metrics := map[string]any{}
	overlayNullableFloat(metrics, "annual_return", annual)
	overlayNullableFloat(metrics, "max_drawdown", drawdown)
	overlayNullableFloat(metrics, "sharpe", sharpe)
	overlayNullableFloat(metrics, "calmar", calmar)
	overlayNullableFloat(metrics, "avg_turnover", turnover)
	overlayNullableFloat(metrics, "monthly_win_rate", monthlyWin)
	overlayNullableFloat(metrics, "positive_3m_rate", positive3m)
	var payload map[string]any
	_ = json.Unmarshal([]byte(payloadJSON), &payload)
	if payload != nil {
		metrics["admission"] = payload["admission"]
		metrics["admission_score"] = payload["admission_score"]
	}
	walkForward, neighborhood := app.strategyValidationEvidence(strategyName, version)
	metrics["walk_forward"] = walkForward
	metrics["parameter_neighborhood"] = neighborhood
	metrics["multiple_test_penalty"] = app.multipleTestPenalty(review.SourceRunID)
	metrics["data_snapshot"] = app.captureDataSnapshot("strategy_version", review.SubjectID)
	rules := app.governanceRules()
	review.Metrics = metrics
	review.Gates = map[string]any{
		"annual_return_positive": !boolParam(rules, "require_positive_return", true) || floatValue(metrics["annual_return"], 0) > 0,
		"drawdown_control":       absFloat(floatValue(metrics["max_drawdown"], 0)) <= numberParam(rules, "max_drawdown", 0.22),
		"sharpe_positive":        floatValue(metrics["sharpe"], 0) >= numberParam(rules, "min_sharpe", 0.30),
		"calmar_positive":        floatValue(metrics["calmar"], 0) >= numberParam(rules, "min_calmar", 0.25),
		"turnover_acceptable":    floatValue(metrics["avg_turnover"], 0) <= numberParam(rules, "max_turnover", 0.45),
		"stability_acceptable":   floatValue(metrics["monthly_win_rate"], 0) >= numberParam(rules, "min_stability_rate", 0.45) || floatValue(metrics["positive_3m_rate"], 0) >= numberParam(rules, "min_stability_rate", 0.45),
		"walk_forward_ok":        floatValue(walkForward["pass_rate"], 0) >= numberParam(rules, "min_walk_forward_pass_rate", 0.50) && floatValue(walkForward["window_count"], 0) >= numberParam(rules, "min_walk_forward_windows", 1),
		"neighborhood_stable":    (boolParam(rules, "allow_missing_parameter_tests", true) && floatValue(neighborhood["checked_versions"], 0) == 0) || floatValue(neighborhood["pass_rate"], 0) >= numberParam(rules, "min_parameter_stable_rate", 0.50),
	}
	passed := 0
	for _, value := range review.Gates {
		if ok, _ := value.(bool); ok {
			passed++
		}
	}
	review.Score = float64(passed)/float64(len(review.Gates)) - floatValue(metrics["multiple_test_penalty"], 0)
	if review.Score < 0 {
		review.Score = 0
	}
	metrics["governance_rules"] = rules
	if review.Score >= numberParam(rules, "min_promotable_score", 0.85) {
		review.Status = "promotable"
		review.Recommendation = "通过主要晋级门槛，可进入模拟盘；模拟盘稳定后再设为生效版本"
	} else if review.Score >= numberParam(rules, "min_research_score", 0.55) {
		review.Status = "research"
		review.Recommendation = "部分指标通过，建议继续 walk-forward 或参数邻域验证"
	} else {
		review.Status = "rejected"
		review.Recommendation = "未通过核心晋级门槛，不建议生效"
	}
	return app.persistValidationReview(review)
}

func (app *App) RefreshRecommendationHindsight() ([]RecommendationHindsightDTO, error) {
	if err := app.ensureDatabase(); err != nil {
		return nil, err
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	dbPath := filepath.Join(app.settings.DataPath, "meta.db")
	scriptPath := filepath.Join(quantRoot, "trading", "execution", "validation.py")
	cmd := exec.Command(pythonPath, scriptPath, "--persist", "--db-path", dbPath, "--horizons", "1,3,5,10,20")
	cmd.Dir = quantRoot
	cmd.Env = append(os.Environ(), "DESKTOP_DB_PATH="+dbPath)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if output, err := cmd.Output(); err != nil {
		return nil, fmt.Errorf("刷新推荐回看失败：%v %s", err, strings.TrimSpace(stderr.String()+string(output)))
	}
	app.saveResearchReport("daily_recommendation", "hindsight", "recommendation_hindsight", "推荐结果回看", "已刷新推荐信号与次日表现回看。", map[string]any{"refreshed_at": time.Now().Format(time.RFC3339)})
	return app.ListRecommendationHindsight()
}

func (app *App) RefreshGovernanceAudit() (GovernanceDashboardDTO, error) {
	if _, err := app.RefreshRecommendationHindsight(); err != nil {
		return GovernanceDashboardDTO{}, err
	}
	if err := app.refreshRiskExposureSnapshots(); err != nil {
		return GovernanceDashboardDTO{}, err
	}
	if err := app.refreshPaperTradingLog(); err != nil {
		return GovernanceDashboardDTO{}, err
	}
	if err := app.refreshPromotionDecisions(); err != nil {
		return GovernanceDashboardDTO{}, err
	}
	if err := app.refreshWalkForwardAndParameterExperiments(); err != nil {
		return GovernanceDashboardDTO{}, err
	}
	dashboard, err := app.ListGovernanceDashboard()
	if err != nil {
		return GovernanceDashboardDTO{}, err
	}
	report := app.buildGovernanceAuditReport(dashboard)
	app.saveResearchReport("governance", "latest", "governance_audit", "量化治理审计", report, map[string]any{"refreshed_at": time.Now().Format(time.RFC3339), "dashboard": dashboard})
	dashboard.Reports, _ = app.listResearchReports("governance", "latest", 6)
	return dashboard, nil
}

func (app *App) ListRecommendationHindsight() ([]RecommendationHindsightDTO, error) {
	if err := app.ensureDatabase(); err != nil {
		return nil, err
	}
	rows, err := app.database.Conn().Query(`SELECT id, recommendation_date, horizon_days, next_date, n_holdings, n_eval, weighted_return, equal_weight_return, hit_rate, COALESCE(payload_json, '{}'), created_at, updated_at
		FROM recommendation_hindsight
		ORDER BY recommendation_date DESC, horizon_days ASC
		LIMIT 200`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []RecommendationHindsightDTO{}
	for rows.Next() {
		var item RecommendationHindsightDTO
		var weighted, equal, hit sql.NullFloat64
		var payloadJSON string
		if err := rows.Scan(&item.ID, &item.RecommendationDate, &item.HorizonDays, &item.NextDate, &item.NHoldings, &item.NEval, &weighted, &equal, &hit, &payloadJSON, &item.CreatedAt, &item.UpdatedAt); err != nil {
			return nil, err
		}
		item.WeightedReturn = nullableFloatPtr(weighted)
		item.EqualWeightReturn = nullableFloatPtr(equal)
		item.HitRate = nullableFloatPtr(hit)
		item.Payload = map[string]any{}
		_ = json.Unmarshal([]byte(payloadJSON), &item.Payload)
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListGovernanceDashboard() (GovernanceDashboardDTO, error) {
	if err := app.ensureDatabase(); err != nil {
		return GovernanceDashboardDTO{}, err
	}
	hindsight, err := app.ListRecommendationHindsight()
	if err != nil {
		return GovernanceDashboardDTO{}, err
	}
	risk, err := app.listRiskExposureSnapshots()
	if err != nil {
		return GovernanceDashboardDTO{}, err
	}
	paper, err := app.listPaperTradingLog()
	if err != nil {
		return GovernanceDashboardDTO{}, err
	}
	promotion, err := app.listPromotionDecisions()
	if err != nil {
		return GovernanceDashboardDTO{}, err
	}
	walk, err := app.listWalkForwardWindows()
	if err != nil {
		return GovernanceDashboardDTO{}, err
	}
	params, err := app.listParameterExperiments()
	if err != nil {
		return GovernanceDashboardDTO{}, err
	}
	dataQuality, err := app.dataQualitySummary()
	if err != nil {
		return GovernanceDashboardDTO{}, err
	}
	reports, _ := app.listResearchReports("governance", "latest", 6)
	return GovernanceDashboardDTO{
		Hindsight:                hindsight,
		Risk:                     risk,
		Paper:                    paper,
		Promotion:                promotion,
		Walk:                     walk,
		Params:                   params,
		DataQuality:              dataQuality,
		ParameterRecommendations: app.parameterRecommendations(params),
		Retirement:               app.retirementDecisions(promotion, walk, params),
		PortfolioAttribution:     app.portfolioAttribution(risk),
		Recovery:                 app.recoverySummary(),
		Reports:                  reports,
	}, nil
}

func (app *App) ListValidationEvidence(query ValidationEvidenceQuery) (ValidationEvidenceDTO, error) {
	if err := app.ensureDatabase(); err != nil {
		return ValidationEvidenceDTO{}, err
	}
	limit := query.Limit
	if limit <= 0 || limit > 200 {
		limit = 80
	}
	subjectType := strings.TrimSpace(query.SubjectType)
	subjectID := strings.TrimSpace(query.SubjectID)
	sourceRunID := strings.TrimSpace(query.SourceRunID)
	out := ValidationEvidenceDTO{
		Reviews:   []ValidationReviewDTO{},
		Reports:   []ResearchReportDTO{},
		Snapshots: []DataSnapshotDTO{},
	}
	reviewSQL := `SELECT id, subject_type, subject_id, strategy, COALESCE(strategy_version, 0), source_run_id, status, score, COALESCE(gates_json, '{}'), COALESCE(metrics_json, '{}'), recommendation, created_at, updated_at
		FROM strategy_validation_reviews`
	reviewWhere := []string{}
	args := []any{}
	if subjectType != "" {
		reviewWhere = append(reviewWhere, "subject_type = ?")
		args = append(args, subjectType)
	}
	if subjectID != "" {
		reviewWhere = append(reviewWhere, "subject_id = ?")
		args = append(args, subjectID)
	}
	if sourceRunID != "" {
		reviewWhere = append(reviewWhere, "source_run_id = ?")
		args = append(args, sourceRunID)
	}
	if len(reviewWhere) > 0 {
		reviewSQL += " WHERE " + strings.Join(reviewWhere, " AND ")
	}
	reviewSQL += " ORDER BY datetime(updated_at) DESC LIMIT ?"
	args = append(args, limit)
	if rows, err := app.database.Conn().Query(reviewSQL, args...); err == nil {
		defer rows.Close()
		for rows.Next() {
			var item ValidationReviewDTO
			var gatesJSON, metricsJSON string
			if err := rows.Scan(&item.ID, &item.SubjectType, &item.SubjectID, &item.Strategy, &item.StrategyVersion, &item.SourceRunID, &item.Status, &item.Score, &gatesJSON, &metricsJSON, &item.Recommendation, &item.CreatedAt, &item.UpdatedAt); err == nil {
				item.Gates = map[string]any{}
				item.Metrics = map[string]any{}
				_ = json.Unmarshal([]byte(gatesJSON), &item.Gates)
				_ = json.Unmarshal([]byte(metricsJSON), &item.Metrics)
				out.Reviews = append(out.Reviews, item)
			}
		}
	}
	reportSQL := `SELECT id, subject_type, subject_id, report_type, title, model, content_md, COALESCE(payload_json, '{}'), created_at FROM research_reports`
	reportWhere := []string{}
	args = []any{}
	if subjectType != "" {
		reportWhere = append(reportWhere, "subject_type = ?")
		args = append(args, subjectType)
	}
	if subjectID != "" {
		reportWhere = append(reportWhere, "subject_id = ?")
		args = append(args, subjectID)
	}
	if len(reportWhere) > 0 {
		reportSQL += " WHERE " + strings.Join(reportWhere, " AND ")
	}
	reportSQL += " ORDER BY datetime(created_at) DESC LIMIT ?"
	args = append(args, limit)
	if rows, err := app.database.Conn().Query(reportSQL, args...); err == nil {
		defer rows.Close()
		for rows.Next() {
			var item ResearchReportDTO
			var payloadJSON string
			if err := rows.Scan(&item.ID, &item.SubjectType, &item.SubjectID, &item.ReportType, &item.Title, &item.Model, &item.ContentMD, &payloadJSON, &item.CreatedAt); err == nil {
				item.Payload = map[string]any{}
				_ = json.Unmarshal([]byte(payloadJSON), &item.Payload)
				out.Reports = append(out.Reports, item)
			}
		}
	}
	snapshotSQL := `SELECT id, subject_type, subject_id, COALESCE(snapshot_json, '{}'), created_at FROM evaluation_data_snapshots`
	snapshotWhere := []string{}
	args = []any{}
	if subjectType != "" {
		snapshotWhere = append(snapshotWhere, "subject_type = ?")
		args = append(args, subjectType)
	}
	if subjectID != "" {
		snapshotWhere = append(snapshotWhere, "subject_id = ?")
		args = append(args, subjectID)
	}
	if len(snapshotWhere) > 0 {
		snapshotSQL += " WHERE " + strings.Join(snapshotWhere, " AND ")
	}
	snapshotSQL += " ORDER BY datetime(created_at) DESC LIMIT ?"
	args = append(args, limit)
	if rows, err := app.database.Conn().Query(snapshotSQL, args...); err == nil {
		defer rows.Close()
		for rows.Next() {
			var item DataSnapshotDTO
			var snapshotJSON string
			if err := rows.Scan(&item.ID, &item.SubjectType, &item.SubjectID, &snapshotJSON, &item.CreatedAt); err == nil {
				item.Snapshot = map[string]any{}
				_ = json.Unmarshal([]byte(snapshotJSON), &item.Snapshot)
				out.Snapshots = append(out.Snapshots, item)
			}
		}
	}
	return out, nil
}

func (app *App) refreshRiskExposureSnapshots() error {
	row := app.database.Conn().QueryRow(`SELECT date, payload_json FROM daily_recommendation ORDER BY date DESC LIMIT 1`)
	var date string
	var payloadJSON string
	if err := row.Scan(&date, &payloadJSON); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil
		}
		return err
	}
	var payload map[string]any
	_ = json.Unmarshal([]byte(payloadJSON), &payload)
	rows, _ := payload["rows"].([]any)
	industryWeights := map[string]float64{}
	strategyWeights := map[string]float64{}
	weights := []float64{}
	totalWeight := 0.0
	for _, raw := range rows {
		item, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		weight := floatValue(item["to_weight"], 0)
		if weight <= 0 {
			continue
		}
		totalWeight += weight
		weights = append(weights, weight)
		industry := strings.TrimSpace(fmt.Sprint(item["industry"]))
		if industry == "" {
			industry = "未分类"
		}
		industryWeights[industry] += weight
		if sources, ok := item["sources"].([]any); ok {
			for _, sourceRaw := range sources {
				source, ok := sourceRaw.(map[string]any)
				if !ok {
					continue
				}
				strategy := strings.TrimSpace(fmt.Sprint(source["strategy"]))
				if strategy != "" {
					strategyWeights[strategy] += floatValue(source["weight"], 0) * weight
				}
			}
		}
	}
	sort.Sort(sort.Reverse(sort.Float64Slice(weights)))
	maxSingle := 0.0
	top5 := 0.0
	for idx, weight := range weights {
		if idx == 0 {
			maxSingle = weight
		}
		if idx < 5 {
			top5 += weight
		}
	}
	industryJSON, _ := json.Marshal(floatMapToAny(industryWeights))
	strategyJSON, _ := json.Marshal(floatMapToAny(strategyWeights))
	auditPayload := map[string]any{
		"concentration": map[string]any{"max_single_weight": maxSingle, "top5_weight": top5},
		"risk_flags":    riskExposureFlags(maxSingle, top5, industryWeights),
	}
	auditJSON, _ := json.Marshal(auditPayload)
	_, err := app.database.Conn().Exec(`INSERT INTO risk_exposure_snapshots(
		id, subject_type, subject_id, as_of_date, n_holdings, total_weight, max_single_weight, top5_weight, industry_json, strategy_json, payload_json, created_at
	) VALUES (?, 'daily_recommendation', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		"res_"+strings.ReplaceAll(task.NewID(), "-", ""), date, date, len(weights), totalWeight, maxSingle, top5, string(industryJSON), string(strategyJSON), string(auditJSON), time.Now().Format(time.RFC3339))
	return err
}

func (app *App) refreshPaperTradingLog() error {
	rows, err := app.database.Conn().Query(`SELECT date, payload_json FROM daily_recommendation ORDER BY date DESC LIMIT 120`)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var date, payloadJSON string
		if err := rows.Scan(&date, &payloadJSON); err != nil {
			continue
		}
		var payload map[string]any
		_ = json.Unmarshal([]byte(payloadJSON), &payload)
		recRows, _ := payload["rows"].([]any)
		for _, raw := range recRows {
			item, ok := raw.(map[string]any)
			if !ok {
				continue
			}
			code := strings.TrimSpace(fmt.Sprint(item["ts_code"]))
			action := strings.TrimSpace(fmt.Sprint(item["action"]))
			if code == "" || action == "" || action == "持有" {
				continue
			}
			name := strings.TrimSpace(fmt.Sprint(item["name"]))
			targetWeight := floatValue(item["to_weight"], 0)
			status := "signal_recorded"
			reason := "已记录信号，等待模拟盘成交确认"
			var actual sql.NullFloat64
			_ = app.database.Conn().QueryRow(`SELECT weight FROM pool_holdings WHERE ts_code = ?`, code).Scan(&actual)
			if actual.Valid {
				status = "tracked"
				reason = "已匹配当前持仓权重"
			}
			itemJSON, _ := json.Marshal(item)
			_, _ = app.database.Conn().Exec(`INSERT INTO paper_trading_log(
				id, signal_date, ts_code, name, action, target_weight, actual_weight, status, reason, payload_json, created_at, updated_at
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			ON CONFLICT(signal_date, ts_code, action) DO UPDATE SET
				target_weight = excluded.target_weight,
				actual_weight = excluded.actual_weight,
				status = excluded.status,
				reason = excluded.reason,
				payload_json = excluded.payload_json,
				updated_at = excluded.updated_at`,
				"pt_"+strings.ReplaceAll(task.NewID(), "-", ""), date, code, name, action, targetWeight, nullableSQLValue(actual), status, reason, string(itemJSON), time.Now().Format(time.RFC3339), time.Now().Format(time.RFC3339))
		}
	}
	return rows.Err()
}

func (app *App) refreshPromotionDecisions() error {
	rows, err := app.database.Conn().Query(`SELECT strategy, version, COALESCE(promotion_status, 'research'), COALESCE(validation_json, '{}') FROM strategy_settings_versions ORDER BY strategy, version DESC`)
	if err != nil {
		return err
	}
	defer rows.Close()
	rules := app.governanceRules()
	now := time.Now().Format(time.RFC3339)
	for rows.Next() {
		var strategy, status, validationJSON string
		var version int
		if err := rows.Scan(&strategy, &version, &status, &validationJSON); err != nil {
			continue
		}
		var validation map[string]any
		_ = json.Unmarshal([]byte(validationJSON), &validation)
		score := floatValue(validation["score"], 0)
		recommended := "research"
		reason := "缺少足够复核证据，保持研究状态"
		if score >= numberParam(rules, "min_paper_score", 0.85) {
			recommended = "paper"
			reason = "可信度分数达到模拟盘门槛，建议进入 paper trading"
		}
		if status == "paper" && score >= numberParam(rules, "min_active_candidate_score", 0.85) {
			recommended = "active_candidate"
			reason = "已处于模拟盘且可信度达标，可人工确认后生效"
		}
		if score > 0 && score < numberParam(rules, "min_research_score", 0.55) {
			recommended = "rejected"
			reason = "可信度不足，不建议启用"
		}
		payloadJSON, _ := json.Marshal(map[string]any{"validation": validation, "governance_rules": rules})
		_, _ = app.database.Conn().Exec(`INSERT INTO promotion_decisions(
			id, strategy, strategy_version, current_status, recommended_status, score, reason, payload_json, created_at, updated_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(strategy, strategy_version) DO UPDATE SET
			current_status = excluded.current_status,
			recommended_status = excluded.recommended_status,
			score = excluded.score,
			reason = excluded.reason,
			payload_json = excluded.payload_json,
			updated_at = excluded.updated_at`,
			"pd_"+strings.ReplaceAll(task.NewID(), "-", ""), strategy, version, status, recommended, score, reason, string(payloadJSON), now, now)
	}
	return rows.Err()
}

func (app *App) refreshWalkForwardAndParameterExperiments() error {
	rows, err := app.database.Conn().Query(`SELECT run_id, strategy, COALESCE(strategy_version, 0), start_date, end_date, annual_return, max_drawdown, sharpe, calmar, avg_turnover, COALESCE(payload_json, '{}')
		FROM strategy_evaluation ORDER BY strategy, start_date`)
	if err != nil {
		return err
	}
	defer rows.Close()
	now := time.Now().Format(time.RFC3339)
	for rows.Next() {
		var runID, strategy, startDate, endDate, payloadJSON string
		var version int
		var annual, drawdown, sharpe, calmar, turnover sql.NullFloat64
		if err := rows.Scan(&runID, &strategy, &version, &startDate, &endDate, &annual, &drawdown, &sharpe, &calmar, &turnover, &payloadJSON); err != nil {
			continue
		}
		subjectID := fmt.Sprintf("%s@%d", strategy, version)
		score := strategyWindowScore(nullableFloatValue(annual, 0), nullableFloatValue(drawdown, 0), nullableFloatValue(sharpe, 0), nullableFloatValue(calmar, 0), nullableFloatValue(turnover, 0))
		status := "research"
		if score >= 0.75 {
			status = "pass"
		} else if score < 0.45 {
			status = "fail"
		}
		metricsJSON, _ := json.Marshal(map[string]any{"run_id": runID, "annual_return": nullableFloatPtr(annual), "max_drawdown": nullableFloatPtr(drawdown), "sharpe": nullableFloatPtr(sharpe), "calmar": nullableFloatPtr(calmar), "avg_turnover": nullableFloatPtr(turnover), "payload": jsonRawMap(payloadJSON)})
		_, _ = app.database.Conn().Exec(`INSERT INTO walk_forward_windows(
			id, subject_type, subject_id, window_name, start_date, end_date, status, score, metrics_json, created_at, updated_at
		) VALUES (?, 'strategy_version', ?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(subject_type, subject_id, window_name) DO UPDATE SET
			status = excluded.status,
			score = excluded.score,
			metrics_json = excluded.metrics_json,
			updated_at = excluded.updated_at`,
			"wfw_"+strings.ReplaceAll(task.NewID(), "-", ""), subjectID, runID, startDate, endDate, status, score, string(metricsJSON), now, now)
	}
	versionRows, err := app.database.Conn().Query(`SELECT strategy, version, config_json, COALESCE(validation_json, '{}') FROM strategy_settings_versions ORDER BY strategy, version DESC`)
	if err != nil {
		return err
	}
	defer versionRows.Close()
	for versionRows.Next() {
		var strategy, configJSON, validationJSON string
		var version int
		if err := versionRows.Scan(&strategy, &version, &configJSON, &validationJSON); err != nil {
			continue
		}
		var validation map[string]any
		_ = json.Unmarshal([]byte(validationJSON), &validation)
		score := floatValue(validation["score"], 0)
		status := "research"
		if score >= 0.85 {
			status = "stable"
		} else if score > 0 && score < 0.55 {
			status = "unstable"
		}
		_, _ = app.database.Conn().Exec(`INSERT INTO parameter_experiments(
			id, strategy, strategy_version, param_set, status, score, params_json, metrics_json, created_at, updated_at
		) VALUES (?, ?, ?, 'version_config', ?, ?, ?, ?, ?, ?)
		ON CONFLICT(strategy, strategy_version, param_set) DO UPDATE SET
			status = excluded.status,
			score = excluded.score,
			params_json = excluded.params_json,
			metrics_json = excluded.metrics_json,
			updated_at = excluded.updated_at`,
			"pe_"+strings.ReplaceAll(task.NewID(), "-", ""), strategy, version, status, score, configJSON, validationJSON, now, now)
	}
	return nil
}

func (app *App) listRiskExposureSnapshots() ([]RiskExposureDTO, error) {
	rows, err := app.database.Conn().Query(`SELECT id, subject_type, subject_id, as_of_date, n_holdings, total_weight, max_single_weight, top5_weight, COALESCE(industry_json, '{}'), COALESCE(strategy_json, '{}'), COALESCE(payload_json, '{}'), created_at
		FROM risk_exposure_snapshots ORDER BY datetime(created_at) DESC LIMIT 30`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []RiskExposureDTO{}
	for rows.Next() {
		var item RiskExposureDTO
		var industryJSON, strategyJSON, payloadJSON string
		if err := rows.Scan(&item.ID, &item.SubjectType, &item.SubjectID, &item.AsOfDate, &item.NHoldings, &item.TotalWeight, &item.MaxSingleWeight, &item.Top5Weight, &industryJSON, &strategyJSON, &payloadJSON, &item.CreatedAt); err != nil {
			return nil, err
		}
		item.Industry = map[string]any{}
		item.Strategy = map[string]any{}
		item.Payload = map[string]any{}
		_ = json.Unmarshal([]byte(industryJSON), &item.Industry)
		_ = json.Unmarshal([]byte(strategyJSON), &item.Strategy)
		_ = json.Unmarshal([]byte(payloadJSON), &item.Payload)
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) listWalkForwardWindows() ([]WalkForwardWindowDTO, error) {
	rows, err := app.database.Conn().Query(`SELECT id, subject_type, subject_id, window_name, start_date, end_date, status, score, COALESCE(metrics_json, '{}'), created_at, updated_at
		FROM walk_forward_windows ORDER BY datetime(updated_at) DESC LIMIT 200`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []WalkForwardWindowDTO{}
	for rows.Next() {
		var item WalkForwardWindowDTO
		var metricsJSON string
		if err := rows.Scan(&item.ID, &item.SubjectType, &item.SubjectID, &item.WindowName, &item.StartDate, &item.EndDate, &item.Status, &item.Score, &metricsJSON, &item.CreatedAt, &item.UpdatedAt); err != nil {
			return nil, err
		}
		item.Metrics = map[string]any{}
		_ = json.Unmarshal([]byte(metricsJSON), &item.Metrics)
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) listParameterExperiments() ([]ParameterExperimentDTO, error) {
	rows, err := app.database.Conn().Query(`SELECT id, strategy, strategy_version, param_set, status, score, COALESCE(params_json, '{}'), COALESCE(metrics_json, '{}'), created_at, updated_at
		FROM parameter_experiments ORDER BY strategy, strategy_version DESC LIMIT 200`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []ParameterExperimentDTO{}
	for rows.Next() {
		var item ParameterExperimentDTO
		var paramsJSON, metricsJSON string
		if err := rows.Scan(&item.ID, &item.Strategy, &item.StrategyVersion, &item.ParamSet, &item.Status, &item.Score, &paramsJSON, &metricsJSON, &item.CreatedAt, &item.UpdatedAt); err != nil {
			return nil, err
		}
		item.Params = map[string]any{}
		item.Metrics = map[string]any{}
		_ = json.Unmarshal([]byte(paramsJSON), &item.Params)
		_ = json.Unmarshal([]byte(metricsJSON), &item.Metrics)
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) listPaperTradingLog() ([]PaperTradingLogDTO, error) {
	rows, err := app.database.Conn().Query(`SELECT id, signal_date, ts_code, name, action, target_weight, actual_weight, status, reason, COALESCE(payload_json, '{}'), created_at, updated_at
		FROM paper_trading_log ORDER BY signal_date DESC, updated_at DESC LIMIT 200`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []PaperTradingLogDTO{}
	for rows.Next() {
		var item PaperTradingLogDTO
		var actual sql.NullFloat64
		var payloadJSON string
		if err := rows.Scan(&item.ID, &item.SignalDate, &item.TSCode, &item.Name, &item.Action, &item.TargetWeight, &actual, &item.Status, &item.Reason, &payloadJSON, &item.CreatedAt, &item.UpdatedAt); err != nil {
			return nil, err
		}
		item.ActualWeight = nullableFloatPtr(actual)
		item.Payload = map[string]any{}
		_ = json.Unmarshal([]byte(payloadJSON), &item.Payload)
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) listPromotionDecisions() ([]PromotionDecisionDTO, error) {
	rows, err := app.database.Conn().Query(`SELECT id, strategy, strategy_version, current_status, recommended_status, score, reason, COALESCE(payload_json, '{}'), created_at, updated_at
		FROM promotion_decisions ORDER BY strategy, strategy_version DESC LIMIT 200`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []PromotionDecisionDTO{}
	for rows.Next() {
		var item PromotionDecisionDTO
		var payloadJSON string
		if err := rows.Scan(&item.ID, &item.Strategy, &item.StrategyVersion, &item.CurrentStatus, &item.RecommendedStatus, &item.Score, &item.Reason, &payloadJSON, &item.CreatedAt, &item.UpdatedAt); err != nil {
			return nil, err
		}
		item.Payload = map[string]any{}
		_ = json.Unmarshal([]byte(payloadJSON), &item.Payload)
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) dataQualitySummary() (map[string]any, error) {
	rows, err := app.database.Conn().Query(`SELECT data_type, COUNT(*), COALESCE(SUM(row_count), 0), COALESCE(MAX(updated_at), '') FROM market_data_files GROUP BY data_type ORDER BY data_type`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	datasets := map[string]any{}
	for rows.Next() {
		var dataType, updatedAt string
		var files int
		var rowCount int64
		if err := rows.Scan(&dataType, &files, &rowCount, &updatedAt); err != nil {
			return nil, err
		}
		datasets[dataType] = map[string]any{"files": files, "rows": rowCount, "updated_at": updatedAt}
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	required := stringListFromAny(app.governanceRules()["data_quality_required"])
	if len(required) == 0 {
		required = []string{"stock_basic", "daily"}
	}
	missing := []string{}
	for _, name := range required {
		item, ok := datasets[name].(map[string]any)
		if !ok || (int64(floatValue(item["rows"], 0)) <= 0 && int(floatValue(item["files"], 0)) <= 0) {
			missing = append(missing, name)
		}
	}
	status := "pass"
	if len(missing) > 0 {
		status = "blocked"
	}
	return map[string]any{"status": status, "required": required, "missing": missing, "datasets": datasets, "checked_at": time.Now().Format(time.RFC3339)}, nil
}

func (app *App) parameterRecommendations(params []ParameterExperimentDTO) []map[string]any {
	type agg struct {
		Strategy string
		Total    int
		Stable   int
		Best     ParameterExperimentDTO
		HasBest  bool
		Values   map[string][]float64
	}
	groups := map[string]*agg{}
	for _, item := range params {
		group := groups[item.Strategy]
		if group == nil {
			group = &agg{Strategy: item.Strategy, Values: map[string][]float64{}}
			groups[item.Strategy] = group
		}
		group.Total++
		if !group.HasBest || item.Score > group.Best.Score {
			group.Best = item
			group.HasBest = true
		}
		if item.Status != "stable" && item.Status != "pass" {
			continue
		}
		group.Stable++
		flattenNumericParams("", item.Params, group.Values)
	}
	out := make([]map[string]any, 0, len(groups))
	for _, group := range groups {
		ranges := []map[string]any{}
		for key, values := range group.Values {
			if len(values) == 0 {
				continue
			}
			sort.Float64s(values)
			ranges = append(ranges, map[string]any{"path": key, "min": values[0], "max": values[len(values)-1], "samples": len(values)})
		}
		sort.Slice(ranges, func(i, j int) bool { return fmt.Sprint(ranges[i]["path"]) < fmt.Sprint(ranges[j]["path"]) })
		recommendation := "继续研究"
		if group.Total > 0 && float64(group.Stable)/float64(group.Total) >= numberParam(app.governanceRules(), "min_parameter_stable_rate", 0.5) {
			recommendation = "参数区间稳定，可进入下一轮样本外验证"
		}
		out = append(out, map[string]any{"strategy": group.Strategy, "total": group.Total, "stable": group.Stable, "stable_rate": safeRatio(group.Stable, group.Total), "best_param_set": group.Best.ParamSet, "best_score": group.Best.Score, "ranges": ranges, "recommendation": recommendation})
	}
	sort.Slice(out, func(i, j int) bool {
		return floatValue(out[i]["stable_rate"], 0) > floatValue(out[j]["stable_rate"], 0)
	})
	return out
}

func (app *App) retirementDecisions(promotions []PromotionDecisionDTO, walk []WalkForwardWindowDTO, params []ParameterExperimentDTO) []map[string]any {
	walkStats := statusRatesByStrategyFromWalk(walk)
	paramStats := statusRatesByStrategyFromParams(params)
	out := []map[string]any{}
	for _, item := range promotions {
		walkRate := floatValue(walkStats[item.Strategy]["pass_rate"], 0)
		paramRate := floatValue(paramStats[item.Strategy]["stable_rate"], 0)
		action := "保留观察"
		reason := item.Reason
		if item.RecommendedStatus == "rejected" || (item.Score > 0 && item.Score < numberParam(app.governanceRules(), "min_research_score", 0.55)) {
			action = "建议退役"
			reason = "晋级分低于研究门槛"
		} else if floatValue(walkStats[item.Strategy]["total"], 0) >= 2 && walkRate < 0.34 {
			action = "降权复核"
			reason = "walk-forward 多窗口通过率偏低"
		} else if floatValue(paramStats[item.Strategy]["total"], 0) >= 3 && paramRate < 0.34 {
			action = "冻结参数"
			reason = "参数邻域稳定性不足"
		}
		out = append(out, map[string]any{"strategy": item.Strategy, "version": item.StrategyVersion, "action": action, "score": item.Score, "walk_pass_rate": walkRate, "parameter_stable_rate": paramRate, "reason": reason})
	}
	sort.Slice(out, func(i, j int) bool { return fmt.Sprint(out[i]["action"]) > fmt.Sprint(out[j]["action"]) })
	return out
}

func (app *App) portfolioAttribution(risk []RiskExposureDTO) []map[string]any {
	if len(risk) == 0 {
		return []map[string]any{}
	}
	out := []map[string]any{}
	for name, raw := range risk[0].Strategy {
		weight := floatValue(raw, 0)
		if weight == 0 {
			continue
		}
		out = append(out, map[string]any{"strategy": name, "weight": weight, "as_of_date": risk[0].AsOfDate})
	}
	sort.Slice(out, func(i, j int) bool { return floatValue(out[i]["weight"], 0) > floatValue(out[j]["weight"], 0) })
	return out
}

func (app *App) recoverySummary() map[string]any {
	statuses := map[string]int{}
	total := 0
	retryable := 0
	blocked := 0
	rows, err := app.database.Conn().Query(`SELECT status, attempt, max_attempts FROM evaluation_tasks WHERE task_type IN (?, ?, ?, ?, ?)`,
		string(task.TypeEvaluationTimeMachine), string(task.TypeStrategyEvaluation), string(task.TypePortfolioOptimization), string(task.TypeWalkForwardEvaluation), string(task.TypeParameterExperiment))
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var status string
			var attempt, maxAttempts int
			if err := rows.Scan(&status, &attempt, &maxAttempts); err != nil {
				continue
			}
			total++
			statuses[status]++
			if status == string(task.StatusFailed) && (maxAttempts <= 0 || attempt < maxAttempts) {
				retryable++
			}
			if status == string(task.StatusFailed) && maxAttempts > 0 && attempt >= maxAttempts {
				blocked++
			}
		}
	}
	return map[string]any{"total": total, "statuses": statuses, "retryable_failed": retryable, "blocked_failed": blocked, "checked_at": time.Now().Format(time.RFC3339)}
}

func (app *App) listResearchReports(subjectType string, subjectID string, limit int) ([]ResearchReportDTO, error) {
	if limit <= 0 {
		limit = 6
	}
	query := `SELECT id, subject_type, subject_id, report_type, title, model, content_md, COALESCE(payload_json, '{}'), created_at FROM research_reports`
	where := []string{}
	args := []any{}
	if subjectType != "" {
		where = append(where, "subject_type = ?")
		args = append(args, subjectType)
	}
	if subjectID != "" {
		where = append(where, "subject_id = ?")
		args = append(args, subjectID)
	}
	if len(where) > 0 {
		query += " WHERE " + strings.Join(where, " AND ")
	}
	query += " ORDER BY datetime(created_at) DESC LIMIT ?"
	args = append(args, limit)
	rows, err := app.database.Conn().Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []ResearchReportDTO{}
	for rows.Next() {
		var item ResearchReportDTO
		var payloadJSON string
		if err := rows.Scan(&item.ID, &item.SubjectType, &item.SubjectID, &item.ReportType, &item.Title, &item.Model, &item.ContentMD, &payloadJSON, &item.CreatedAt); err != nil {
			return nil, err
		}
		item.Payload = map[string]any{}
		_ = json.Unmarshal([]byte(payloadJSON), &item.Payload)
		out = append(out, item)
	}
	return out, rows.Err()
}

func flattenNumericParams(prefix string, value any, out map[string][]float64) {
	switch typed := value.(type) {
	case map[string]any:
		for key, item := range typed {
			next := key
			if prefix != "" {
				next = prefix + "." + key
			}
			flattenNumericParams(next, item, out)
		}
	case float64, float32, int, int64, json.Number:
		if prefix != "" {
			out[prefix] = append(out[prefix], floatValue(typed, 0))
		}
	}
}

func statusRatesByStrategyFromWalk(rows []WalkForwardWindowDTO) map[string]map[string]any {
	stats := map[string]map[string]any{}
	for _, row := range rows {
		strategy := strings.Split(row.SubjectID, "@")[0]
		if strategy == "" {
			strategy = row.SubjectID
		}
		item := stats[strategy]
		if item == nil {
			item = map[string]any{"total": 0, "pass": 0}
			stats[strategy] = item
		}
		item["total"] = int(floatValue(item["total"], 0)) + 1
		if row.Status == "pass" {
			item["pass"] = int(floatValue(item["pass"], 0)) + 1
		}
		item["pass_rate"] = safeRatio(int(floatValue(item["pass"], 0)), int(floatValue(item["total"], 0)))
	}
	return stats
}

func statusRatesByStrategyFromParams(rows []ParameterExperimentDTO) map[string]map[string]any {
	stats := map[string]map[string]any{}
	for _, row := range rows {
		item := stats[row.Strategy]
		if item == nil {
			item = map[string]any{"total": 0, "stable": 0}
			stats[row.Strategy] = item
		}
		item["total"] = int(floatValue(item["total"], 0)) + 1
		if row.Status == "stable" || row.Status == "pass" {
			item["stable"] = int(floatValue(item["stable"], 0)) + 1
		}
		item["stable_rate"] = safeRatio(int(floatValue(item["stable"], 0)), int(floatValue(item["total"], 0)))
	}
	return stats
}

func safeRatio(numerator int, denominator int) any {
	if denominator <= 0 {
		return nil
	}
	return float64(numerator) / float64(denominator)
}

func stringListFromAny(value any) []string {
	switch typed := value.(type) {
	case []string:
		return typed
	case []any:
		out := make([]string, 0, len(typed))
		for _, item := range typed {
			text := strings.TrimSpace(fmt.Sprint(item))
			if text != "" && text != "<nil>" {
				out = append(out, text)
			}
		}
		return out
	case string:
		parts := strings.Split(typed, ",")
		out := []string{}
		for _, part := range parts {
			text := strings.TrimSpace(part)
			if text != "" {
				out = append(out, text)
			}
		}
		return out
	default:
		return nil
	}
}

func (app *App) buildGovernanceAuditReport(dashboard GovernanceDashboardDTO) string {
	lines := []string{"治理审计已完成。"}
	if status := fmt.Sprint(dashboard.DataQuality["status"]); status != "" {
		lines = append(lines, fmt.Sprintf("数据质量：%s，缺失 %v。", status, dashboard.DataQuality["missing"]))
	}
	lines = append(lines, fmt.Sprintf("策略晋级：%d 条建议；退役/降权：%d 条；参数推荐：%d 条。", len(dashboard.Promotion), len(dashboard.Retirement), len(dashboard.ParameterRecommendations)))
	if len(dashboard.PortfolioAttribution) > 0 {
		top := dashboard.PortfolioAttribution[0]
		lines = append(lines, fmt.Sprintf("组合归因：当前最大策略暴露为 %s，权重 %.2f%%。", fmt.Sprint(top["strategy"]), floatValue(top["weight"], 0)*100))
	}
	if retryable := int(floatValue(dashboard.Recovery["retryable_failed"], 0)); retryable > 0 {
		lines = append(lines, fmt.Sprintf("任务恢复：存在 %d 个失败任务仍可重跑。", retryable))
	}
	lines = append(lines, "下一步建议：优先处理数据缺口、重跑可恢复失败任务，再根据参数区间推荐创建下一轮 walk-forward。")
	return strings.Join(lines, "\n")
}

func (app *App) ensureDataQualityForEvaluation() error {
	summary, err := app.dataQualitySummary()
	if err != nil {
		return err
	}
	if fmt.Sprint(summary["status"]) == "pass" {
		return nil
	}
	missing := stringListFromAny(summary["missing"])
	if len(missing) == 0 {
		return errors.New("数据质量闸门未通过，请先刷新数据")
	}
	return fmt.Errorf("数据质量闸门未通过，缺少必要数据集：%s。请先在数据管理更新数据", strings.Join(missing, ", "))
}

func (app *App) persistValidationReview(review ValidationReviewDTO) (ValidationReviewDTO, error) {
	if review.ID == "" {
		review.ID = "vr_" + strings.ReplaceAll(task.NewID(), "-", "")
	}
	now := time.Now().Format(time.RFC3339)
	if review.CreatedAt == "" {
		review.CreatedAt = now
	}
	review.UpdatedAt = now
	gatesJSON, _ := json.Marshal(review.Gates)
	metricsJSON, _ := json.Marshal(review.Metrics)
	if _, err := app.database.Conn().Exec(`INSERT INTO strategy_validation_reviews(
		id, subject_type, subject_id, strategy, strategy_version, source_run_id, status, score, gates_json, metrics_json, recommendation, created_at, updated_at
	) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	ON CONFLICT(id) DO UPDATE SET
		status = excluded.status,
		score = excluded.score,
		gates_json = excluded.gates_json,
		metrics_json = excluded.metrics_json,
		recommendation = excluded.recommendation,
		updated_at = excluded.updated_at`,
		review.ID, review.SubjectType, review.SubjectID, review.Strategy, review.StrategyVersion, review.SourceRunID, review.Status, review.Score, string(gatesJSON), string(metricsJSON), review.Recommendation, review.CreatedAt, review.UpdatedAt); err != nil {
		return ValidationReviewDTO{}, err
	}
	validationJSON, _ := json.Marshal(map[string]any{"review_id": review.ID, "status": review.Status, "score": review.Score, "gates": review.Gates, "metrics": review.Metrics, "recommendation": review.Recommendation, "updated_at": review.UpdatedAt})
	if review.SubjectType == "strategy_version" && review.Strategy != "" && review.StrategyVersion > 0 {
		_, _ = app.database.Conn().Exec(`UPDATE strategy_settings_versions SET promotion_status = ?, validation_json = ? WHERE strategy = ? AND version = ?`,
			review.Status, string(validationJSON), review.Strategy, review.StrategyVersion)
	}
	app.saveResearchReport(review.SubjectType, review.SubjectID, "validation_review", "策略版本复核", review.Recommendation, map[string]any{
		"review_id": review.ID,
		"status":    review.Status,
		"score":     review.Score,
		"gates":     review.Gates,
		"metrics":   review.Metrics,
	})
	return review, nil
}

func (app *App) strategyValidationEvidence(strategyName string, version int) (map[string]any, map[string]any) {
	walkForward := map[string]any{"window_count": 0, "pass_rate": 0.0, "avg_annual_return": nil, "worst_drawdown": nil}
	rows, err := app.database.Conn().Query(`SELECT annual_return, max_drawdown, sharpe, calmar, avg_turnover, monthly_win_rate, positive_3m_rate
		FROM strategy_evaluation
		WHERE strategy = ? AND COALESCE(strategy_version, 0) = ?`, strategyName, version)
	if err == nil {
		defer rows.Close()
		count := 0
		pass := 0
		annualSum := 0.0
		worstDrawdown := 0.0
		for rows.Next() {
			var annual, drawdown, sharpe, calmar, turnover, monthlyWin, positive3m sql.NullFloat64
			if err := rows.Scan(&annual, &drawdown, &sharpe, &calmar, &turnover, &monthlyWin, &positive3m); err != nil {
				continue
			}
			count++
			annualValue := nullableFloatValue(annual, 0)
			drawdownValue := absFloat(nullableFloatValue(drawdown, 0))
			annualSum += annualValue
			if drawdownValue > worstDrawdown {
				worstDrawdown = drawdownValue
			}
			if annualValue > 0 && drawdownValue <= 0.22 && nullableFloatValue(sharpe, 0) >= 0.3 && nullableFloatValue(calmar, 0) >= 0.25 && nullableFloatValue(turnover, 0) <= 0.45 && (nullableFloatValue(monthlyWin, 0) >= 0.45 || nullableFloatValue(positive3m, 0) >= 0.45) {
				pass++
			}
		}
		if count > 0 {
			walkForward["window_count"] = count
			walkForward["pass_rate"] = float64(pass) / float64(count)
			walkForward["avg_annual_return"] = annualSum / float64(count)
			walkForward["worst_drawdown"] = worstDrawdown
		}
	}
	neighborhood := map[string]any{"checked_versions": 0, "pass_rate": 0.0}
	rows, err = app.database.Conn().Query(`SELECT COALESCE(validation_json, '{}')
		FROM strategy_settings_versions
		WHERE strategy = ? AND version <> ? AND ABS(version - ?) <= 2`, strategyName, version, version)
	if err == nil {
		defer rows.Close()
		count := 0
		pass := 0
		for rows.Next() {
			var validationJSON string
			if err := rows.Scan(&validationJSON); err != nil {
				continue
			}
			var validation map[string]any
			_ = json.Unmarshal([]byte(validationJSON), &validation)
			if len(validation) == 0 {
				continue
			}
			count++
			if floatValue(validation["score"], 0) >= 0.55 {
				pass++
			}
		}
		neighborhood["checked_versions"] = count
		if count > 0 {
			neighborhood["pass_rate"] = float64(pass) / float64(count)
		}
	}
	return walkForward, neighborhood
}

func (app *App) multipleTestPenalty(runID string) float64 {
	runID = strings.TrimSpace(runID)
	if runID == "" || app.database == nil {
		return 0
	}
	var strategyTests int
	_ = app.database.Conn().QueryRow(`SELECT COUNT(*) FROM strategy_evaluation WHERE run_id = ?`, runID).Scan(&strategyTests)
	var candidateTests int
	_ = app.database.Conn().QueryRow(`SELECT COUNT(*) FROM portfolio_optimization_candidates WHERE run_id = ?`, runID).Scan(&candidateTests)
	tests := strategyTests + candidateTests
	if tests <= 1 {
		return 0
	}
	penalty := math.Log10(float64(tests)) * 0.035
	if penalty > 0.18 {
		return 0.18
	}
	return penalty
}

func (app *App) captureDataSnapshot(subjectType string, subjectID string) map[string]any {
	if app.database == nil {
		return map[string]any{}
	}
	snapshot := map[string]any{
		"captured_at": time.Now().Format(time.RFC3339),
	}
	typeCount := map[string]any{}
	rows, err := app.database.Conn().Query(`SELECT data_type, COUNT(*), COALESCE(SUM(row_count), 0), COALESCE(MAX(updated_at), '') FROM market_data_files GROUP BY data_type ORDER BY data_type`)
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var dataType string
			var files int
			var rowsCount int64
			var updatedAt string
			if err := rows.Scan(&dataType, &files, &rowsCount, &updatedAt); err == nil {
				typeCount[dataType] = map[string]any{"files": files, "rows": rowsCount, "updated_at": updatedAt}
			}
		}
	}
	datasetStatus := []map[string]any{}
	rows, err = app.database.Conn().Query(`SELECT dataset, category, state, progress_done, progress_total, updated_at FROM dataset_update_status ORDER BY category, dataset LIMIT 200`)
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var dataset, category, state, updatedAt string
			var done, total int
			if err := rows.Scan(&dataset, &category, &state, &done, &total, &updatedAt); err == nil {
				datasetStatus = append(datasetStatus, map[string]any{"dataset": dataset, "category": category, "state": state, "done": done, "total": total, "updated_at": updatedAt})
			}
		}
	}
	snapshot["market_data_files"] = typeCount
	snapshot["dataset_status"] = datasetStatus
	app.saveDataSnapshot(subjectType, subjectID, snapshot)
	return snapshot
}

func (app *App) saveDataSnapshot(subjectType string, subjectID string, snapshot map[string]any) {
	if app.database == nil || strings.TrimSpace(subjectType) == "" || strings.TrimSpace(subjectID) == "" {
		return
	}
	data, _ := json.Marshal(snapshot)
	_, _ = app.database.Conn().Exec(`INSERT INTO evaluation_data_snapshots(id, subject_type, subject_id, snapshot_json, created_at) VALUES(?, ?, ?, ?, ?)`,
		"eds_"+strings.ReplaceAll(task.NewID(), "-", ""), subjectType, subjectID, string(data), time.Now().Format(time.RFC3339))
}

func (app *App) saveResearchReport(subjectType string, subjectID string, reportType string, title string, content string, payload map[string]any) {
	if app.database == nil || strings.TrimSpace(subjectType) == "" || strings.TrimSpace(subjectID) == "" {
		return
	}
	data, _ := json.Marshal(payload)
	_, _ = app.database.Conn().Exec(`INSERT INTO research_reports(id, subject_type, subject_id, report_type, title, model, content_md, payload_json, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		"rr_"+strings.ReplaceAll(task.NewID(), "-", ""), subjectType, subjectID, reportType, title, "quant_robust_rules_v1", content, string(data), time.Now().Format(time.RFC3339))
}

func nullableFloatValue(value sql.NullFloat64, fallback float64) float64 {
	if value.Valid {
		return value.Float64
	}
	return fallback
}

func nullableFloatPtr(value sql.NullFloat64) *float64 {
	if !value.Valid {
		return nil
	}
	out := value.Float64
	return &out
}

func nullableSQLValue(value sql.NullFloat64) any {
	if value.Valid {
		return value.Float64
	}
	return nil
}

func floatMapToAny(value map[string]float64) map[string]any {
	out := map[string]any{}
	for key, item := range value {
		out[key] = item
	}
	return out
}

func riskExposureFlags(maxSingle float64, top5 float64, industries map[string]float64) []string {
	flags := []string{}
	if maxSingle > 0.08 {
		flags = append(flags, "单票权重超过 8%")
	}
	if top5 > 0.35 {
		flags = append(flags, "前五持仓集中度超过 35%")
	}
	for industry, weight := range industries {
		if weight > 0.30 {
			flags = append(flags, fmt.Sprintf("%s 行业权重超过 30%%", industry))
		}
	}
	if len(flags) == 0 {
		flags = append(flags, "未触发集中度红线")
	}
	return flags
}

func strategyWindowScore(annual float64, drawdown float64, sharpe float64, calmar float64, turnover float64) float64 {
	score := 0.0
	if annual > 0 {
		score += 0.25
	}
	if absFloat(drawdown) <= 0.22 {
		score += 0.20
	}
	if sharpe >= 0.3 {
		score += 0.20
	}
	if calmar >= 0.25 {
		score += 0.20
	}
	if turnover <= 0.45 {
		score += 0.15
	}
	return score
}

func jsonRawMap(data string) map[string]any {
	out := map[string]any{}
	_ = json.Unmarshal([]byte(data), &out)
	return out
}

func walkForwardWindows(startDate string, endDate string, count int) []map[string]any {
	if count <= 0 {
		count = 4
	}
	start, okStart := parseYYYYMMDD(startDate)
	end, okEnd := parseYYYYMMDD(endDate)
	if !okStart || !okEnd || !end.After(start) {
		return nil
	}
	totalDays := int(end.Sub(start).Hours() / 24)
	if totalDays < count {
		count = 1
	}
	step := totalDays / count
	if step <= 0 {
		step = totalDays
	}
	out := []map[string]any{}
	for idx := 0; idx < count; idx++ {
		wStart := start.AddDate(0, 0, idx*step)
		wEnd := start.AddDate(0, 0, (idx+1)*step-1)
		if idx == count-1 || wEnd.After(end) {
			wEnd = end
		}
		if !wEnd.Before(wStart) {
			out = append(out, map[string]any{"name": fmt.Sprintf("WF%02d", idx+1), "start_date": wStart.Format("20060102"), "end_date": wEnd.Format("20060102")})
		}
	}
	return out
}

func parameterExperimentGrid() []map[string]any {
	return []map[string]any{
		{"name": "base", "override": map[string]any{}},
		{"name": "risk_tight", "override": map[string]any{"filters": map[string]any{"max_20d_return": 0.20, "max_short_return": 0.10}, "position": map[string]any{"max_single_weight": 0.035}}},
		{"name": "risk_mid", "override": map[string]any{"filters": map[string]any{"max_20d_return": 0.28, "max_short_return": 0.15}, "position": map[string]any{"max_single_weight": 0.045}}},
		{"name": "risk_loose", "override": map[string]any{"filters": map[string]any{"max_20d_return": 0.35, "max_short_return": 0.20}, "position": map[string]any{"max_single_weight": 0.055}}},
		{"name": "hold_short", "override": map[string]any{"filters": map[string]any{"holding_days": 20}}},
		{"name": "hold_mid", "override": map[string]any{"filters": map[string]any{"holding_days": 45}}},
		{"name": "quality_strict", "override": map[string]any{"filters": map[string]any{"min_roe": 0.08, "min_gross_margin": 0.20}}},
	}
}

func parseYYYYMMDD(value string) (time.Time, bool) {
	t, err := time.Parse("20060102", strings.TrimSpace(value))
	if err != nil {
		return time.Time{}, false
	}
	return t, true
}

func (app *App) buildPortfolioAnalysisContext(parent task.Task, children []task.Task) (map[string]any, error) {
	params := task.ToDTO(parent).Params
	runID := parent.ExternalRunID
	topN := int(numberParam(params, "top_n", 40))
	if topN <= 0 {
		topN = 40
	}
	analysisLimit := topN
	if analysisLimit < 200 {
		analysisLimit = 200
	}
	if analysisLimit > 500 {
		analysisLimit = 500
	}
	rows := make([]map[string]any, 0)
	if app.database != nil && runID != "" {
		dbRows, err := app.database.Conn().Query(`SELECT rank, score, annual_return, max_drawdown, sharpe, calmar, avg_turnover, avg_holdings, avg_total_mv, avg_amount, payload_json
			FROM portfolio_optimization_candidates
			WHERE run_id = ?
			ORDER BY CASE WHEN rank > 0 THEN rank ELSE 999999 END ASC, score DESC
			LIMIT ?`, runID, analysisLimit)
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

type quantCandidateScore struct {
	Row    map[string]any
	Score  float64
	Reason string
}

func (app *App) buildQuantPortfolioRecommendation(parent task.Task, contextPayload map[string]any) (string, map[string]any) {
	params := task.ToDTO(parent).Params
	rows := rowsFromContext(contextPayload["candidate_results"])
	scored := make([]quantCandidateScore, 0, len(rows))
	multiplePenalty := app.candidateSetPenalty(len(rows))
	for _, row := range rows {
		if strings.TrimSpace(fmt.Sprint(row["status"])) != "ok" {
			continue
		}
		score, reason := robustCandidateScore(row)
		score -= multiplePenalty
		if score < 0 {
			score = 0
		}
		scored = append(scored, quantCandidateScore{Row: row, Score: score, Reason: reason})
	}
	sort.Slice(scored, func(i, j int) bool {
		return scored[i].Score > scored[j].Score
	})
	topWindow := 20
	if len(scored) < topWindow {
		topWindow = len(scored)
	}
	selectedStrategies := app.selectStrategiesForNextRound(scored, topWindow)
	if len(selectedStrategies) == 0 {
		selectedStrategies = app.resolvePortfolioStrategyNames(params["strategies"])
	}
	overrides := app.quantStrategyOverrides(scored, topWindow)
	best := map[string]any{}
	if len(scored) > 0 {
		best = scored[0].Row
	}
	nextParams := map[string]any{
		"start_date":            params["start_date"],
		"end_date":              params["end_date"],
		"strategies":            selectedStrategies,
		"objective":             stringParam(params, "objective", "平衡"),
		"max_candidates":        0,
		"top_n":                 params["top_n"],
		"benchmark":             params["benchmark"],
		"slippage":              params["slippage"],
		"strategy_overrides":    overrides,
		"strategy_version_mode": "latest",
		"optimizer":             map[string]any{"type": "quant_robust_rules_v1", "llm_role": "research_assistant_only"},
		"validation":            []string{"全量候选回测", "样本外滚动验证", "参数邻域稳定性检查", "交易成本和滑点压力测试"},
	}
	nextConfig := map[string]any{
		"name":      parent.Name + " - 量化优化下一轮",
		"task_type": "portfolio_optimization",
		"params":    nextParams,
	}
	diagnosis, keep, change, remove, validation := app.quantRecommendationText(scored, topWindow, selectedStrategies, overrides)
	analysis := app.quantAnalysisMarkdown(parent, scored, topWindow, selectedStrategies, overrides)
	recommendation := map[string]any{
		"analysis_md":           analysis,
		"diagnosis":             diagnosis,
		"keep":                  keep,
		"change":                change,
		"remove":                remove,
		"validation_plan":       validation,
		"next_eval_config":      nextConfig,
		"optimizer_type":        "quant_robust_rules_v1",
		"llm_role":              "LLM 不直接优化参数，只用于后续报告解释、研报/公告解析和代码审查",
		"best_candidate":        summarizeCandidate(best),
		"candidate_coverage":    contextPayload["coverage"],
		"multiple_test_penalty": multiplePenalty,
	}
	return analysis, recommendation
}

func (app *App) candidateSetPenalty(count int) float64 {
	if count <= 1 {
		return 0
	}
	penalty := math.Log10(float64(count)) * 0.025
	if penalty > 0.16 {
		return 0.16
	}
	return penalty
}

func robustCandidateScore(row map[string]any) (float64, string) {
	rawScore := floatValue(row["score"], 0)
	annual := floatValue(row["annual_return"], 0)
	excess := floatValue(row["excess_annual_return"], 0)
	drawdown := floatValue(row["max_drawdown"], 0)
	sharpe := floatValue(row["sharpe"], 0)
	calmar := floatValue(row["calmar"], 0)
	turnover := floatValue(row["avg_turnover"], 0)
	holdings := floatValue(row["avg_holdings"], 0)
	score := rawScore + annual*0.8 + excess*0.5 + sharpe*0.08 + calmar*0.05
	score -= absFloat(drawdown) * 0.7
	if turnover > 0.30 {
		score -= (turnover - 0.30) * 0.8
	}
	if holdings > 0 && holdings < 8 {
		score -= (8 - holdings) * 0.03
	}
	reason := fmt.Sprintf("年化 %.2f%%，回撤 %.2f%%，夏普 %.2f，换手 %.2f%%", annual*100, drawdown*100, sharpe, turnover*100)
	return score, reason
}

func (app *App) selectStrategiesForNextRound(scored []quantCandidateScore, topWindow int) []string {
	type agg struct {
		Name      string
		Count     int
		WeightSum float64
		ScoreSum  float64
		AnnualSum float64
		BestScore float64
	}
	stats := map[string]*agg{}
	for idx := 0; idx < topWindow; idx++ {
		item := scored[idx]
		weights := mapFromAny(item.Row["weights"])
		for name, weightAny := range weights {
			weight := floatValue(weightAny, 0)
			if weight <= 0 {
				continue
			}
			stat := stats[name]
			if stat == nil {
				stat = &agg{Name: name, BestScore: item.Score}
				stats[name] = stat
			}
			stat.Count++
			stat.WeightSum += weight
			stat.ScoreSum += item.Score * weight
			stat.AnnualSum += floatValue(item.Row["annual_return"], 0)
			if item.Score > stat.BestScore {
				stat.BestScore = item.Score
			}
		}
	}
	items := make([]*agg, 0, len(stats))
	for _, stat := range stats {
		items = append(items, stat)
	}
	sort.Slice(items, func(i, j int) bool {
		left := items[i].ScoreSum + float64(items[i].Count)*0.05
		right := items[j].ScoreSum + float64(items[j].Count)*0.05
		if left == right {
			return items[i].Name < items[j].Name
		}
		return left > right
	})
	limit := 6
	if len(items) < limit {
		limit = len(items)
	}
	out := make([]string, 0, limit)
	for idx := 0; idx < limit; idx++ {
		if items[idx].Count > 0 {
			out = append(out, items[idx].Name)
		}
	}
	sort.Strings(out)
	return out
}

func (app *App) quantStrategyOverrides(scored []quantCandidateScore, topWindow int) map[string]any {
	overrides := map[string]any{}
	if topWindow == 0 {
		return overrides
	}
	avgDrawdown := 0.0
	avgTurnover := 0.0
	avgHoldings := 0.0
	for idx := 0; idx < topWindow; idx++ {
		row := scored[idx].Row
		avgDrawdown += absFloat(floatValue(row["max_drawdown"], 0))
		avgTurnover += floatValue(row["avg_turnover"], 0)
		avgHoldings += floatValue(row["avg_holdings"], 0)
	}
	avgDrawdown /= float64(topWindow)
	avgTurnover /= float64(topWindow)
	avgHoldings /= float64(topWindow)
	if avgTurnover > 0.30 {
		overrides["event_enhanced"] = map[string]any{"filters": map[string]any{"holding_days": 20}, "position": map[string]any{"max_single_weight": 0.025}}
		overrides["earnings_revision"] = map[string]any{"filters": map[string]any{"holding_days": 45}}
	}
	if avgDrawdown > 0.18 {
		mergeOverride(overrides, "trend_pullback", map[string]any{"filters": map[string]any{"max_short_return": 0.15, "max_20d_return": 0.25}, "position": map[string]any{"max_single_weight": 0.04}})
		mergeOverride(overrides, "small_cap_quality", map[string]any{"universe": map[string]any{"max_20d_return": 0.25}, "position": map[string]any{"max_single_weight": 0.04}})
	}
	if avgHoldings > 0 && avgHoldings < 10 {
		mergeOverride(overrides, "multi_factor_composite", map[string]any{"position": map[string]any{"n_holdings": 35, "max_single_weight": 0.04}})
		mergeOverride(overrides, "industry_prosperity", map[string]any{"selection": map[string]any{"top_n_industries": 5}})
	}
	return overrides
}

func (app *App) quantRecommendationText(scored []quantCandidateScore, topWindow int, selected []string, overrides map[string]any) ([]string, []string, []string, []string, []string) {
	diagnosis := []string{"优化器按稳健分排序：原始评分 + 年化/超额/夏普/Calmar，扣减回撤、过高换手和过低持仓分散度。"}
	keep := []string{"下一轮只收窄策略池，不收窄出场、调仓、市场过滤和仓位上限矩阵，继续由回测全量验证。"}
	change := []string{"参数只做邻域调整，并通过 strategy_overrides 注入到单次实验，不写回全局策略配置。"}
	remove := []string{"不根据单次最高收益永久删除策略；低贡献策略只在下一轮降权或暂不进入收窄策略池。"}
	validation := []string{"必须比较本轮 Top 方案与下一轮 Top 方案的样本外表现，不能只看训练区间。", "对新增参数做邻域稳定性检查：相邻阈值表现不能断崖式下降。", "所有结论需要带手续费、滑点、停牌/涨跌停约束后再进入模拟盘。"}
	if len(scored) > 0 {
		best := scored[0].Row
		diagnosis = append(diagnosis, fmt.Sprintf("当前稳健分第一：%s，%s。", fmt.Sprint(best["name"]), scored[0].Reason))
	}
	if topWindow > 0 {
		diagnosis = append(diagnosis, fmt.Sprintf("本次归因窗口使用前 %d 个成功候选，降低只看冠军方案造成的选择偏差。", topWindow))
	}
	if len(selected) > 0 {
		keep = append(keep, "下一轮策略池："+strings.Join(app.strategyLabels(selected), "、"))
	}
	if len(overrides) > 0 {
		change = append(change, fmt.Sprintf("生成 %d 个策略参数覆盖，重点约束追高、换手、单票权重和持仓分散度。", len(overrides)))
	}
	return diagnosis, keep, change, remove, validation
}

func (app *App) quantAnalysisMarkdown(parent task.Task, scored []quantCandidateScore, topWindow int, selected []string, overrides map[string]any) string {
	var builder strings.Builder
	builder.WriteString("### 量化优化结论\n")
	builder.WriteString("本轮没有把参数优化交给大模型；优化器只使用回测指标、风险惩罚和候选贡献归因生成下一轮实验配置。")
	if len(scored) == 0 {
		builder.WriteString("\n\n没有可用的成功候选，不能生成有效优化结论。")
		return builder.String()
	}
	best := scored[0].Row
	builder.WriteString(fmt.Sprintf("\n\n最佳稳健候选：%s；年化 %.2f%%，累计 %.2f%%，最大回撤 %.2f%%，夏普 %.2f，Calmar %.2f。",
		fmt.Sprint(best["name"]),
		floatValue(best["annual_return"], 0)*100,
		floatValue(best["total_return"], 0)*100,
		floatValue(best["max_drawdown"], 0)*100,
		floatValue(best["sharpe"], 0),
		floatValue(best["calmar"], 0),
	))
	builder.WriteString(fmt.Sprintf("\n\n归因窗口：前 %d 个成功候选。下一轮保留策略池：%s。", topWindow, strings.Join(app.strategyLabels(selected), "、")))
	if len(overrides) > 0 {
		builder.WriteString(fmt.Sprintf("\n\n参数改进：生成 %d 组实验覆盖，只用于下一轮回测；这些覆盖需要通过样本外、walk-forward 和参数邻域稳定性验证后，才允许考虑固化。", len(overrides)))
	} else {
		builder.WriteString("\n\n参数改进：本轮未发现足够明确的风险/换手/分散度问题，下一轮优先验证策略组合与出场架构。")
	}
	builder.WriteString("\n\n过拟合控制：不采用 LLM 直接挑参数；不因单次冠军方案下结论；不把单点阈值当长期最优。")
	return builder.String()
}

func rowsFromContext(value any) []map[string]any {
	items, ok := value.([]map[string]any)
	if ok {
		return items
	}
	rawItems, ok := value.([]any)
	if !ok {
		return nil
	}
	out := make([]map[string]any, 0, len(rawItems))
	for _, item := range rawItems {
		if row, ok := item.(map[string]any); ok {
			out = append(out, row)
		}
	}
	return out
}

func mapFromAny(value any) map[string]any {
	if out, ok := value.(map[string]any); ok {
		return out
	}
	return map[string]any{}
}

func floatValue(value any, fallback float64) float64 {
	switch typed := value.(type) {
	case float64:
		return typed
	case float32:
		return float64(typed)
	case int:
		return float64(typed)
	case int64:
		return float64(typed)
	case json.Number:
		if parsed, err := typed.Float64(); err == nil {
			return parsed
		}
	case string:
		if parsed, err := strconv.ParseFloat(strings.TrimSpace(typed), 64); err == nil {
			return parsed
		}
	}
	return fallback
}

func absFloat(value float64) float64 {
	if value < 0 {
		return -value
	}
	return value
}

func mergeOverride(overrides map[string]any, name string, patch map[string]any) {
	current, _ := overrides[name].(map[string]any)
	if current == nil {
		overrides[name] = patch
		return
	}
	overrides[name] = deepMergeAny(current, patch)
}

func deepMergeAny(base map[string]any, patch map[string]any) map[string]any {
	out := cloneAnyMap(base)
	for key, value := range patch {
		if valueMap, ok := value.(map[string]any); ok {
			if existing, ok := out[key].(map[string]any); ok {
				out[key] = deepMergeAny(existing, valueMap)
				continue
			}
		}
		out[key] = value
	}
	return out
}

func summarizeCandidate(row map[string]any) map[string]any {
	if len(row) == 0 {
		return map[string]any{}
	}
	return map[string]any{
		"name":                 row["name"],
		"score":                row["score"],
		"annual_return":        row["annual_return"],
		"total_return":         row["total_return"],
		"excess_annual_return": row["excess_annual_return"],
		"max_drawdown":         row["max_drawdown"],
		"sharpe":               row["sharpe"],
		"calmar":               row["calmar"],
		"avg_turnover":         row["avg_turnover"],
		"avg_holdings":         row["avg_holdings"],
		"weights":              row["weights"],
		"exit_architecture":    row["exit_architecture"],
		"rebalance_freq":       row["rebalance_freq"],
		"risk_rule":            row["risk_rule"],
		"position_rule":        row["position_rule"],
	}
}

func (app *App) strategyLabels(names []string) []string {
	out := make([]string, 0, len(names))
	for _, name := range names {
		out = append(out, app.strategyDisplayName(name))
	}
	return out
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
		"start_date":            params["start_date"],
		"end_date":              params["end_date"],
		"strategies":            params["strategies"],
		"objective":             params["objective"],
		"max_candidates":        params["max_candidates"],
		"top_n":                 params["top_n"],
		"benchmark":             params["benchmark"],
		"slippage":              params["slippage"],
		"strategy_overrides":    params["strategy_overrides"],
		"strategy_version_mode": params["strategy_version_mode"],
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
	if nextParams["strategy_version_mode"] == nil || fmt.Sprint(nextParams["strategy_version_mode"]) == "" {
		nextParams["strategy_version_mode"] = "latest"
	}
	if optimizer, ok := config["optimizer"]; ok && nextParams["optimizer"] == nil {
		nextParams["optimizer"] = optimizer
	}
	if validation, ok := config["validation"]; ok && nextParams["validation"] == nil {
		nextParams["validation"] = validation
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
	if t.TaskType != task.TypeEvaluationTimeMachine && t.TaskType != task.TypeStrategyEvaluation && t.TaskType != task.TypePortfolioOptimization && t.TaskType != task.TypeWalkForwardEvaluation && t.TaskType != task.TypeParameterExperiment {
		return task.DTO{}, errors.New("only evaluation tasks can be started")
	}
	if err := app.ensureDataQualityForEvaluation(); err != nil {
		return task.DTO{}, err
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
	if t.TaskType == task.TypeWalkForwardEvaluation || t.TaskType == task.TypeParameterExperiment {
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
		var initErr error
		switch t.TaskType {
		case task.TypeWalkForwardEvaluation:
			initErr = app.initializeWalkForwardEvaluation(t)
		case task.TypeParameterExperiment:
			initErr = app.initializeParameterExperiment(t)
		default:
			initErr = app.initializeStrategyEvaluation(t)
		}
		if initErr != nil {
			return task.DTO{}, initErr
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
		next := runnablePortfolioChildren(children, app.taskConcurrency())
		if len(next) == 0 {
			app.finishStrategyEvaluationParent(parent, portfolioParentStatus(children), "", children)
			return
		}
		app.runChildTaskBatch(next, app.startStrategyEvaluationChildTaskSync)
		children, _ = app.taskService.Repository().ListChildren(parent.ID)
		parent.Progress = portfolioParentProgress(children)
		parent.SummaryJSON = app.strategyEvaluationSummaryForParent(parent, children)
		parent.UpdatedAt = time.Now()
		_ = app.taskService.Repository().UpdateStatus(parent)
		_ = app.taskService.Repository().UpdateRuntime(parent)
	}
}

func (app *App) startStrategyEvaluationChildTaskSync(t task.Task) (task.Task, error) {
	runID := t.ExternalRunID
	if runID == "" {
		runID = t.GroupRunID
	}
	groupRunID := t.GroupRunID
	if groupRunID == "" {
		groupRunID = runID
	}
	if runID == "" {
		return t, errors.New("strategy evaluation child requires run id")
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
		"--strategy-version-mode", stringParam(params, "strategy_version_mode", "latest"),
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
	if overrides := mapParam(params, "strategy_overrides"); len(overrides) > 0 {
		if data, err := json.Marshal(overrides); err == nil {
			cmd.Env = append(cmd.Env, "QUANT_STRATEGY_OVERRIDES_JSON="+string(data))
		}
	}
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
	t.GroupRunID = groupRunID
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
	app.persistStrategyExperimentArtifacts(t, strategyName)
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

func (app *App) persistStrategyExperimentArtifacts(child task.Task, strategyName string) {
	params := task.ToDTO(child).Params
	summary := map[string]any{}
	if child.SummaryJSON != "" {
		_ = json.Unmarshal([]byte(child.SummaryJSON), &summary)
	}
	score := strategyWindowScore(floatValue(summary["annual_return"], 0), floatValue(summary["max_drawdown"], 0), floatValue(summary["sharpe"], 0), floatValue(summary["calmar"], 0), floatValue(summary["avg_turnover"], 0))
	status := "research"
	if score >= 0.75 {
		status = "pass"
	} else if score < 0.45 {
		status = "fail"
	}
	now := time.Now().Format(time.RFC3339)
	if windowName := strings.TrimSpace(fmt.Sprint(params["walk_window"])); windowName != "" && windowName != "<nil>" {
		metricsJSON, _ := json.Marshal(summary)
		subjectID := fmt.Sprintf("%s@%d", strategyName, int(numberParam(params, "strategy_version", 0)))
		_, _ = app.database.Conn().Exec(`INSERT INTO walk_forward_windows(
			id, subject_type, subject_id, window_name, start_date, end_date, status, score, metrics_json, created_at, updated_at
		) VALUES (?, 'strategy', ?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(subject_type, subject_id, window_name) DO UPDATE SET
			status = excluded.status,
			score = excluded.score,
			metrics_json = excluded.metrics_json,
			updated_at = excluded.updated_at`,
			"wfw_"+strings.ReplaceAll(task.NewID(), "-", ""), subjectID, windowName, stringParam(params, "start_date", ""), stringParam(params, "end_date", ""), status, score, string(metricsJSON), now, now)
	}
	if paramSet := strings.TrimSpace(fmt.Sprint(params["param_set"])); paramSet != "" && paramSet != "<nil>" {
		metricsJSON, _ := json.Marshal(summary)
		overridesJSON, _ := json.Marshal(mapParam(params, "strategy_overrides"))
		expStatus := "research"
		if score >= 0.75 {
			expStatus = "stable"
		} else if score < 0.45 {
			expStatus = "unstable"
		}
		_, _ = app.database.Conn().Exec(`INSERT INTO parameter_experiments(
			id, strategy, strategy_version, param_set, status, score, params_json, metrics_json, created_at, updated_at
		) VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(strategy, strategy_version, param_set) DO UPDATE SET
			status = excluded.status,
			score = excluded.score,
			params_json = excluded.params_json,
			metrics_json = excluded.metrics_json,
			updated_at = excluded.updated_at`,
			"pe_"+strings.ReplaceAll(task.NewID(), "-", ""), strategyName, paramSet, expStatus, score, string(overridesJSON), string(metricsJSON), now, now)
	}
}

func (app *App) strategyEvaluationSummaryForParent(parent task.Task, children []task.Task) string {
	summary := ""
	if app.database != nil && app.database.Conn() != nil && parent.ExternalRunID != "" {
		summary = readStrategyEvaluationSummaryFromDB(app.database.Conn(), parent.ExternalRunID)
	}
	payload := map[string]any{}
	if summary != "" {
		_ = json.Unmarshal([]byte(summary), &payload)
	} else if parent.SummaryJSON != "" {
		_ = json.Unmarshal([]byte(parent.SummaryJSON), &payload)
	}
	if rows, ok := payload["rows"].([]any); !ok || len(rows) == 0 {
		childRows := make([]any, 0, len(children))
		for _, child := range children {
			if child.SummaryJSON == "" {
				continue
			}
			var row map[string]any
			if err := json.Unmarshal([]byte(child.SummaryJSON), &row); err != nil {
				continue
			}
			params := task.ToDTO(child).Params
			if windowName := stringParam(params, "walk_window", ""); windowName != "" {
				row["walk_window"] = windowName
				row["window_name"] = windowName
			}
			if paramSet := stringParam(params, "param_set", ""); paramSet != "" {
				row["param_set"] = paramSet
			}
			row["subtask_key"] = child.SubtaskKey
			row["subtask_name"] = child.SubtaskName
			childRows = append(childRows, row)
		}
		if len(childRows) > 0 {
			payload["rows"] = childRows
			enrichStrategyEvaluationSummary(payload)
		}
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
		next := runnablePortfolioChildren(children, app.taskConcurrency())
		if len(next) == 0 {
			app.finishPortfolioParent(parent, portfolioParentStatus(children), "", children)
			return
		}
		app.runChildTaskBatch(next, app.startPortfolioCandidateTaskSync)
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
	strategyOverridesJSON, err := json.Marshal(mapParam(params, "strategy_overrides"))
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
		"--strategy-overrides-json", string(strategyOverridesJSON),
		"--strategy-version-mode", stringParam(params, "strategy_version_mode", "latest"),
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

func runnablePortfolioChildren(children []task.Task, limit int) []task.Task {
	if limit <= 0 {
		limit = 1
	}
	out := make([]task.Task, 0, limit)
	for idx := range children {
		child := children[idx]
		if child.Status == task.StatusSuccess || child.Status == task.StatusRunning || child.Status == task.StatusCancelled || child.Status == task.StatusInterrupted {
			continue
		}
		if child.MaxAttempts > 0 && child.Attempt >= child.MaxAttempts && child.Status == task.StatusFailed {
			continue
		}
		out = append(out, child)
		if len(out) >= limit {
			break
		}
	}
	return out
}

func (app *App) runChildTaskBatch(children []task.Task, runner func(task.Task) (task.Task, error)) {
	var wg sync.WaitGroup
	for _, child := range children {
		child := child
		wg.Add(1)
		go func() {
			defer wg.Done()
			updated, err := runner(child)
			if err != nil {
				if updated.ID == "" {
					updated = child
				}
				app.markChildTaskFailed(updated, err)
			}
		}()
	}
	wg.Wait()
}

func (app *App) markChildTaskFailed(child task.Task, err error) {
	if err == nil || child.Status == task.StatusFailed || child.Status == task.StatusCancelled {
		return
	}
	now := time.Now()
	child.Status = task.StatusFailed
	child.ErrorMessage = err.Error()
	child.Progress = 1
	child.WorkerPID = 0
	child.FinishedAt = now
	child.UpdatedAt = now
	_ = app.taskService.Repository().UpdateRuntime(child)
}

func (app *App) taskConcurrency() int {
	value := app.settings.TaskConcurrency
	if value < 1 {
		return 1
	}
	if value > 8 {
		return 8
	}
	return value
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
	candidate := filepath.Join(quantRoot, ".venv", "bin", "python")
	if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
		return candidate
	}
	if w := bundledWorkerPath(); w != "" {
		return w
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
	app.settings.DataPath = app.fixedDataPath()
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
		settings.DataPath = app.fixedDataPath()
		app.settings = settings
		_ = app.configService.Save(app.settings)
	}
	app.taskService = task.NewService(task.NewRepository(db.Conn()))
	app.marketService = market.NewService(market.NewRepository(db.Conn()))
	app.positionService = position.NewService(app.marketService, app.database.Conn())
	return nil
}

func (app *App) fixedDataPath() string {
	if homeDir, err := os.UserHomeDir(); err == nil {
		return config.DefaultSettings(homeDir).DataPath
	}
	if app.settings.DataPath != "" {
		return app.settings.DataPath
	}
	return filepath.Join("data_store")
}

func mustGetwd() string {
	wd, err := os.Getwd()
	if err != nil {
		return "."
	}
	return wd
}
