package main

import (
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
	"quant_stock_desktop/internal/runtime/task"
	"quant_stock_desktop/internal/runtime/worker"
)

const (
	profitArenaStrategyID           = "profit_arena_model"
	factorResearchArchiveStrategyID = "ml_factor_ranker"
	profitArenaRebalanceTaskType    = task.Type("profit_arena_rebalance")
	profitArenaDefaultArenaName     = "profit_nolev_rankic_sharpe_dd20_ann45"
	productionBundleIdentifier      = "com.quantstock.productionworkspace"
)

type App struct {
	ctx               context.Context
	configService     *config.Service
	settings          config.Settings
	database          *database.DB
	taskService       *task.Service
	marketService     *market.Service
	positionService   *position.Service
	datafetchService  *datafetch.Service
	schedulerMu       sync.Mutex
	signalMu          sync.Mutex
	scheduleMu        sync.Mutex
	scheduleCancel    context.CancelFunc
	scheduleLastRun   string
	scheduleRunMu     sync.Mutex
	profitArenaTaskMu sync.Mutex
	dataUpdateMu      sync.Mutex
	factorSnapshotMu  sync.Mutex
	startedAt         time.Time
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
		startedAt:     time.Now(),
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
	app.restartStrategySchedule()
}

func (app *App) shutdown(ctx context.Context) {
	app.stopStrategySchedule()
	_ = app.database.Close()
}

type AppInfo struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

type ArenaStrategyDefinitionDTO struct {
	StrategyID       string         `json:"strategy_id"`
	DisplayName      string         `json:"display_name"`
	DefaultArenaName string         `json:"default_arena_name"`
	ArtifactDirName  string         `json:"artifact_dir_name"`
	TaskLabel        string         `json:"task_label"`
	Tables           map[string]any `json:"tables"`
	Metadata         map[string]any `json:"metadata"`
	UpdatedAt        string         `json:"updated_at"`
}

type ExternalDependencyStatus struct {
	Key       string `json:"key"`
	Name      string `json:"name"`
	Category  string `json:"category"`
	State     string `json:"state"`
	LatencyMS int64  `json:"latency_ms"`
	Message   string `json:"message"`
	CheckedAt string `json:"checked_at"`
}

type FactorResearchRunSummary struct {
	RunID       string  `json:"run_id"`
	StartDate   string  `json:"start_date"`
	EndDate     string  `json:"end_date"`
	Freq        string  `json:"freq"`
	Label       string  `json:"label"`
	Status      string  `json:"status"`
	FactorCount int     `json:"factor_count"`
	SampleDates int     `json:"sample_dates"`
	SampleRows  int     `json:"sample_rows"`
	PanelPath   string  `json:"panel_path"`
	UpdatedAt   string  `json:"updated_at"`
	ModelStatus string  `json:"model_status"`
	RankIC      float64 `json:"rank_ic"`
}

type FactorICResult struct {
	RunID           string  `json:"run_id"`
	Factor          string  `json:"factor"`
	Family          string  `json:"family"`
	Variant         string  `json:"variant"`
	Horizon         string  `json:"horizon"`
	ICMean          float64 `json:"ic_mean"`
	RankICMean      float64 `json:"rank_ic_mean"`
	ICWinRate       float64 `json:"ic_win_rate"`
	ICIR            float64 `json:"icir"`
	Status          string  `json:"status"`
	LongShortReturn float64 `json:"long_short_return"`
	MonotonicScore  float64 `json:"monotonic_score"`
}

type FactorStateICResult struct {
	RunID       string  `json:"run_id"`
	Factor      string  `json:"factor"`
	Family      string  `json:"family"`
	Variant     string  `json:"variant"`
	Horizon     string  `json:"horizon"`
	MarketState string  `json:"market_state"`
	RankICMean  float64 `json:"rank_ic_mean"`
	ICWinRate   float64 `json:"ic_win_rate"`
	ICIR        float64 `json:"icir"`
	NPeriods    int     `json:"n_periods"`
	NObs        int     `json:"n_obs"`
	Status      string  `json:"status"`
	SummaryJSON string  `json:"summary_json"`
}

type FactorModelRun struct {
	RunID        string  `json:"run_id"`
	ModelType    string  `json:"model_type"`
	Label        string  `json:"label"`
	FeatureCount int     `json:"feature_count"`
	Status       string  `json:"status"`
	ModelPath    string  `json:"model_path"`
	RankIC       float64 `json:"rank_ic"`
	TopBottom    float64 `json:"top_bottom_spread"`
	SummaryJSON  string  `json:"summary_json"`
	UpdatedAt    string  `json:"updated_at"`
}

type FactorModelFeature struct {
	RunID       string  `json:"run_id"`
	Feature     string  `json:"feature"`
	Importance  float64 `json:"importance"`
	RankNo      int     `json:"rank_no"`
	SummaryJSON string  `json:"summary_json"`
}

type FactorModelPrediction struct {
	RunID          string  `json:"run_id"`
	TradeDate      string  `json:"trade_date"`
	TsCode         string  `json:"ts_code"`
	PredScore      float64 `json:"pred_score"`
	RealizedReturn float64 `json:"realized_return"`
	PredRank       float64 `json:"pred_rank"`
	TestYear       int     `json:"test_year"`
}

type FactorCorrelationResult struct {
	RunID          string  `json:"run_id"`
	FeatureA       string  `json:"feature_a"`
	FeatureB       string  `json:"feature_b"`
	Correlation    float64 `json:"correlation"`
	AbsCorrelation float64 `json:"abs_correlation"`
	FamilyA        string  `json:"family_a"`
	FamilyB        string  `json:"family_b"`
	KeepFeature    string  `json:"keep_feature"`
	DropFeature    string  `json:"drop_feature"`
	Reason         string  `json:"reason"`
}

type FactorStressResult struct {
	RunID          string  `json:"run_id"`
	BucketType     string  `json:"bucket_type"`
	BucketKey      string  `json:"bucket_key"`
	BucketLabel    string  `json:"bucket_label"`
	StartDate      string  `json:"start_date"`
	EndDate        string  `json:"end_date"`
	NDays          int     `json:"n_days"`
	TotalReturn    float64 `json:"total_return"`
	AnnualReturn   float64 `json:"annual_return"`
	MaxDrawdown    float64 `json:"max_drawdown"`
	Sharpe         float64 `json:"sharpe"`
	WinRate        float64 `json:"win_rate"`
	AvgDailyReturn float64 `json:"avg_daily_return"`
	Volatility     float64 `json:"volatility"`
	SummaryJSON    string  `json:"summary_json"`
}

type FactorLatestPrediction struct {
	RunID             string  `json:"run_id"`
	TradeDate         string  `json:"trade_date"`
	TsCode            string  `json:"ts_code"`
	Name              string  `json:"name"`
	Industry          string  `json:"industry"`
	Price             float64 `json:"price"`
	PctChg            float64 `json:"pct_chg"`
	PredScore         float64 `json:"pred_score"`
	PredRank          float64 `json:"pred_rank"`
	IsTop20           bool    `json:"is_top20"`
	ModelPath         string  `json:"model_path"`
	FirstSeenDate     string  `json:"first_seen_date"`
	LastSeenDate      string  `json:"last_seen_date"`
	SeenCount         int     `json:"seen_count"`
	ObservationDays   int     `json:"observation_days"`
	ObservationStatus string  `json:"observation_status"`
	ObservationReason string  `json:"observation_reason"`
	ObservationResult string  `json:"observation_result"`
}

type FactorObservationEvent struct {
	Strategy          string  `json:"strategy"`
	RunID             string  `json:"run_id"`
	TradeDate         string  `json:"trade_date"`
	TsCode            string  `json:"ts_code"`
	Name              string  `json:"name"`
	Industry          string  `json:"industry"`
	EventType         string  `json:"event_type"`
	RankNo            int     `json:"rank_no"`
	Score             float64 `json:"score"`
	RankPct           float64 `json:"rank_pct"`
	Reason            string  `json:"reason"`
	FirstSeenDate     string  `json:"first_seen_date"`
	LastSeenDate      string  `json:"last_seen_date"`
	SeenCount         int     `json:"seen_count"`
	ObservationStatus string  `json:"observation_status"`
	CreatedAt         string  `json:"created_at"`
}

type strategyObservationCandidate struct {
	Strategy  string
	RunID     string
	TradeDate string
	TSCode    string
	Name      string
	Industry  string
	RankNo    int
	Score     float64
	RankPct   float64
	Price     float64
	PctChg    float64
	Reason    string
}

type strategyObservationInfo struct {
	FirstSeenDate     string
	LastSeenDate      string
	SeenCount         int
	ObservationDays   int
	ObservationStatus string
	ObservationReason string
	ObservationResult string
}

type FactorAdmissionComparison struct {
	RunID                    string  `json:"run_id"`
	Strategy                 string  `json:"strategy"`
	Admission                string  `json:"admission"`
	AdmissionScore           float64 `json:"admission_score"`
	Reason                   string  `json:"reason"`
	AnnualReturn             float64 `json:"annual_return"`
	TotalReturn              float64 `json:"total_return"`
	MaxDrawdown              float64 `json:"max_drawdown"`
	Sharpe                   float64 `json:"sharpe"`
	AvgTurnover              float64 `json:"avg_turnover"`
	EffectiveStart           string  `json:"effective_start"`
	EffectiveEnd             string  `json:"effective_end"`
	StressPenalty            float64 `json:"stress_penalty"`
	StressBadEventCount      int     `json:"stress_bad_event_count"`
	StressCrashStateFailed   bool    `json:"stress_crash_state_failed"`
	StressWeakDrawdownFailed bool    `json:"stress_weak_drawdown_failed"`
	GeneratedAt              string  `json:"generated_at"`
}

type ProfitArenaRunSummary struct {
	RunID              string  `json:"run_id"`
	StartDate          string  `json:"start_date"`
	EndDate            string  `json:"end_date"`
	TrainMode          string  `json:"train_mode"`
	ModelType          string  `json:"model_type"`
	FeatureCount       int     `json:"feature_count"`
	Status             string  `json:"status"`
	BestScope          string  `json:"best_scope"`
	BestHorizon        int     `json:"best_horizon"`
	BestTopN           int     `json:"best_top_n"`
	BestCompoundReturn float64 `json:"best_compound_return"`
	SummaryJSON        string  `json:"summary_json"`
	ModelPath          string  `json:"model_path"`
	UpdatedAt          string  `json:"updated_at"`
}

type ProfitArenaEvaluation struct {
	RunID                 string  `json:"run_id"`
	Scope                 string  `json:"scope"`
	Horizon               int     `json:"horizon"`
	TopN                  int     `json:"top_n"`
	MinPredReturn         float64 `json:"min_pred_return"`
	MinMarketUpRatio      float64 `json:"min_market_up_ratio"`
	MinMarketRet5         float64 `json:"min_market_ret5"`
	MinMarketAmountChg5   float64 `json:"min_market_amount_chg5"`
	MinIndustryUpRatio    float64 `json:"min_industry_up_ratio"`
	Segment               string  `json:"segment"`
	TradeCount            int     `json:"trade_count"`
	TradeDays             int     `json:"trade_days"`
	AvgReturn             float64 `json:"avg_return"`
	WinRate               float64 `json:"win_rate"`
	CompoundReturn        float64 `json:"compound_return"`
	AnnualReturn          float64 `json:"annual_return"`
	MaxDrawdown           float64 `json:"max_drawdown"`
	Sharpe                float64 `json:"sharpe"`
	CapitalCompoundReturn float64 `json:"capital_compound_return"`
	CapitalAnnualReturn   float64 `json:"capital_annual_return"`
	CapitalMaxDrawdown    float64 `json:"capital_max_drawdown"`
	CapitalSharpe         float64 `json:"capital_sharpe"`
	CapitalFinalEquity    float64 `json:"capital_final_equity"`
	SummaryJSON           string  `json:"summary_json"`
	UpdatedAt             string  `json:"updated_at"`
}

type ProfitArenaPrediction struct {
	RunID           string  `json:"run_id"`
	Scope           string  `json:"scope"`
	Horizon         int     `json:"horizon"`
	TradeDate       string  `json:"trade_date"`
	TSCode          string  `json:"ts_code"`
	Name            string  `json:"name"`
	Industry        string  `json:"industry"`
	SizeBucket      string  `json:"size_bucket"`
	Price           float64 `json:"price"`
	Amount          float64 `json:"amount"`
	PredReturn      float64 `json:"pred_return"`
	ModelScore      float64 `json:"model_score"`
	RealizedReturn  float64 `json:"realized_return"`
	FutureReturn    float64 `json:"future_return"`
	FutureMaxReturn float64 `json:"future_max_return"`
	FutureDrawdown  float64 `json:"future_drawdown"`
	CrashProb       float64 `json:"crash_prob"`
	ExitDate        string  `json:"exit_date"`
	IsLatest        bool    `json:"is_latest"`
	SummaryJSON     string  `json:"summary_json"`
	UpdatedAt       string  `json:"updated_at"`
}

type ProfitArenaFeature struct {
	RunID      string  `json:"run_id"`
	Scope      string  `json:"scope"`
	Horizon    int     `json:"horizon"`
	Feature    string  `json:"feature"`
	Importance float64 `json:"importance"`
	RankNo     int     `json:"rank_no"`
}

type SettingsResponse struct {
	Settings config.Settings          `json:"settings"`
	Issues   []config.ValidationIssue `json:"issues"`
}

type ApplyPortfolioCandidateRequest struct {
	RunID       string `json:"run_id"`
	CandidateID string `json:"candidate_id"`
}

type activePortfolioCandidateRecord struct {
	RunID            string             `json:"run_id"`
	CandidateID      string             `json:"candidate_id"`
	Name             string             `json:"name"`
	Status           string             `json:"status"`
	Score            float64            `json:"score"`
	Weights          map[string]float64 `json:"weights"`
	ValidationStatus string             `json:"validation_status"`
	AppliedAt        string             `json:"applied_at"`
}

func (app *App) GetAppInfo() AppInfo {
	return AppInfo{
		Name:    "Quant Stock 生产工作台",
		Version: "production-profit-arena",
	}
}

func fallbackArenaStrategyDefinitions() []ArenaStrategyDefinitionDTO {
	tables := map[string]any{
		"run":        "profit_arena_runs",
		"evaluation": "profit_arena_evaluations",
		"prediction": "profit_arena_predictions",
		"feature":    "profit_arena_features",
	}
	metadata := map[string]any{
		"strategy_id":        profitArenaStrategyID,
		"display_name":       "通用策略",
		"default_arena_name": profitArenaDefaultArenaName,
		"arena_name":         profitArenaDefaultArenaName,
		"artifact_dir_name":  "profit_arena",
		"task_key":           "arena:" + profitArenaStrategyID + ":" + profitArenaDefaultArenaName,
		"task_label":         "通用策略 · 版本训练",
		"tables":             tables,
	}
	return []ArenaStrategyDefinitionDTO{{
		StrategyID:       profitArenaStrategyID,
		DisplayName:      "通用策略",
		DefaultArenaName: profitArenaDefaultArenaName,
		ArtifactDirName:  "profit_arena",
		TaskLabel:        "通用策略 · 版本训练",
		Tables:           tables,
		Metadata:         metadata,
		UpdatedAt:        time.Now().Format(time.RFC3339),
	}}
}

func (app *App) ensureArenaStrategyDefinitionsColumns() {
	if app.database == nil || app.database.Conn() == nil || !app.database.TableExists("strategy_arena_definitions") {
		return
	}
	columns := map[string]string{
		"display_name":       "VARCHAR(128) NOT NULL DEFAULT ''",
		"default_arena_name": "VARCHAR(128) NOT NULL DEFAULT ''",
		"artifact_dir_name":  "VARCHAR(128) NOT NULL DEFAULT ''",
		"task_label":         "VARCHAR(128) NOT NULL DEFAULT ''",
		"tables_json":        "LONGTEXT",
		"metadata_json":      "LONGTEXT",
		"updated_at":         "VARCHAR(64) NOT NULL DEFAULT ''",
	}
	for name, ddl := range columns {
		if app.mysqlColumnExists("strategy_arena_definitions", name) {
			continue
		}
		_, _ = app.database.Conn().Exec(fmt.Sprintf("ALTER TABLE strategy_arena_definitions ADD COLUMN %s %s", name, ddl))
	}
}

func (app *App) GetArenaStrategyDefinitions() ([]ArenaStrategyDefinitionDTO, error) {
	if err := app.ensureDatabase(); err != nil {
		return []ArenaStrategyDefinitionDTO{}, err
	}
	if app.database == nil || !app.database.TableExists("strategy_arena_definitions") {
		return fallbackArenaStrategyDefinitions(), nil
	}
	app.ensureArenaStrategyDefinitionsColumns()
	rows, err := app.database.Conn().Query(`
		SELECT strategy_id, display_name, default_arena_name, artifact_dir_name, task_label,
		       COALESCE(tables_json, ''), COALESCE(metadata_json, ''), updated_at
		FROM strategy_arena_definitions
		ORDER BY display_name, strategy_id`)
	if err != nil {
		return []ArenaStrategyDefinitionDTO{}, err
	}
	defer rows.Close()
	out := []ArenaStrategyDefinitionDTO{}
	for rows.Next() {
		var item ArenaStrategyDefinitionDTO
		var tablesJSON, metadataJSON string
		if err := rows.Scan(
			&item.StrategyID,
			&item.DisplayName,
			&item.DefaultArenaName,
			&item.ArtifactDirName,
			&item.TaskLabel,
			&tablesJSON,
			&metadataJSON,
			&item.UpdatedAt,
		); err != nil {
			return out, err
		}
		item.Tables = map[string]any{}
		_ = json.Unmarshal([]byte(tablesJSON), &item.Tables)
		item.Metadata = map[string]any{}
		_ = json.Unmarshal([]byte(metadataJSON), &item.Metadata)
		out = append(out, item)
	}
	if err := rows.Err(); err != nil {
		return out, err
	}
	if len(out) == 0 {
		return fallbackArenaStrategyDefinitions(), nil
	}
	return out, nil
}

func (app *App) GetProductionDiagnostics() (map[string]any, error) {
	dataPath, dataPathSource := app.fixedDataPathWithSource()
	out := map[string]any{
		"data_path":                 dataPath,
		"data_path_source":          dataPathSource,
		"expected_database_backend": "mysql",
		"runtime":                   app.runtimeIdentity(),
		"legacy_user_sqlite_state":  legacyUserSQLiteStateExists(),
	}
	if err := app.ensureDatabase(); err != nil {
		out["status"] = "error"
		out["message"] = err.Error()
		out["database_backend"] = app.settings.DatabaseBackend
		out["mysql_dsn"] = redactDSN(app.settings.MySQLDSN)
		return out, nil
	}
	out["status"] = "ok"
	out["database_backend"] = string(app.database.Backend())
	out["mysql_dsn"] = redactDSN(app.settings.MySQLDSN)
	out["retired_strategy_version_count"] = app.retiredStrategyVersionCount()
	out["retired_strategy_task_count"] = app.retiredStrategyTaskCount()
	out["retired_strategy_status_count"] = app.retiredStrategyStatusCount()
	out["retired_active_model_count"] = app.retiredActiveModelCount()
	out["retired_validation_result_count"] = app.retiredValidationResultCount()
	out["retired_observation_count"] = app.retiredObservationCount()
	out["retired_mysql_table_count"] = app.retiredMySQLTableCount()
	out["retired_data_artifact_count"] = app.retiredDataArtifactCount()
	for key, value := range app.profitArenaProductionHealth() {
		out[key] = value
	}
	out["tables"] = map[string]any{
		"data_daily_bars":          app.database.TableExists("data_daily_bars"),
		"data_stock_basic":         app.database.TableExists("data_stock_basic"),
		"profit_arena_runs":        app.database.TableExists("profit_arena_runs"),
		"profit_arena_predictions": app.database.TableExists("profit_arena_predictions"),
		"task_jobs":                app.database.TableExists("task_jobs"),
		"task_run_status":          app.database.TableExists("task_run_status"),
	}
	out["counts"] = map[string]any{
		"data_daily_bars":          app.tableCount("data_daily_bars"),
		"data_stock_basic":         app.tableCount("data_stock_basic"),
		"profit_arena_runs":        app.tableCount("profit_arena_runs"),
		"profit_arena_predictions": app.tableCount("profit_arena_predictions"),
		"task_jobs":                app.tableCount("task_jobs"),
	}
	out["latest_trade_date"] = app.latestDailyBarTradeDateOrToday()
	return out, nil
}

func (app *App) runtimeIdentity() map[string]any {
	identity := map[string]any{
		"app_name":           "Quant Stock 生产工作台",
		"app_version":        "production-profit-arena",
		"production_app":     true,
		"process_pid":        os.Getpid(),
		"process_started_at": app.startedAt.Format(time.RFC3339),
	}
	if wd, err := os.Getwd(); err == nil {
		identity["working_dir"] = filepath.Clean(wd)
	}
	if exe, err := os.Executable(); err == nil {
		identity["executable_path"] = filepath.Clean(exe)
		if info, err := os.Stat(exe); err == nil {
			identity["executable_modified_at"] = info.ModTime().Format(time.RFC3339)
		}
		if realExe, err := filepath.EvalSymlinks(exe); err == nil {
			identity["real_executable_path"] = filepath.Clean(realExe)
			if info, err := os.Stat(realExe); err == nil {
				identity["real_executable_modified_at"] = info.ModTime().Format(time.RFC3339)
			}
			if bundlePath, ok := inferMacOSBundlePath(realExe); ok {
				identity["bundle_path"] = bundlePath
				identity["bundle_name"] = filepath.Base(bundlePath)
				identity["expected_bundle"] = filepath.Base(bundlePath) == "quant-stock-desktop.app"
				if bundleIdentifier := readMacOSBundleIdentifier(bundlePath); bundleIdentifier != "" {
					identity["bundle_identifier"] = bundleIdentifier
					identity["expected_bundle_identifier"] = bundleIdentifier == productionBundleIdentifier
				}
			}
		}
	}
	if workerPath := bundledWorkerPath(); workerPath != "" {
		identity["worker_path"] = workerPath
		identity["worker_mode"] = "bundled"
	} else {
		identity["worker_path"] = "python3"
		identity["worker_mode"] = "system-python"
	}
	return identity
}

func inferMacOSBundlePath(exePath string) (string, bool) {
	clean := filepath.Clean(exePath)
	parts := strings.Split(clean, string(os.PathSeparator))
	for i := len(parts) - 1; i >= 0; i-- {
		if strings.HasSuffix(parts[i], ".app") {
			if strings.HasPrefix(clean, string(os.PathSeparator)) {
				return string(os.PathSeparator) + filepath.Join(parts[1:i+1]...), true
			}
			return filepath.Join(parts[:i+1]...), true
		}
	}
	return "", false
}

func readMacOSBundleIdentifier(bundlePath string) string {
	data, err := os.ReadFile(filepath.Join(bundlePath, "Contents", "Info.plist"))
	if err != nil {
		return ""
	}
	text := string(data)
	marker := "<key>CFBundleIdentifier</key>"
	idx := strings.Index(text, marker)
	if idx < 0 {
		return ""
	}
	rest := text[idx+len(marker):]
	open := strings.Index(rest, "<string>")
	close := strings.Index(rest, "</string>")
	if open < 0 || close < 0 || close <= open+len("<string>") {
		return ""
	}
	return strings.TrimSpace(rest[open+len("<string>") : close])
}

func (app *App) tableCount(tableName string) int64 {
	if app.database == nil || !app.database.TableExists(tableName) {
		return 0
	}
	var count int64
	if err := app.database.Conn().QueryRow(fmt.Sprintf("SELECT COUNT(*) FROM %s", tableName)).Scan(&count); err != nil {
		return 0
	}
	return count
}

func (app *App) GetSettings() SettingsResponse {
	var issues []config.ValidationIssue
	if app.database != nil {
		app.configService.WithDatabase(app.database)
	}
	settings, err := app.configService.Load(app.settings)
	if err == nil {
		settings.DataPath = app.fixedDataPath()
		app.settings = settings
		if err := app.configService.Save(app.settings); err != nil {
			issues = append(issues, config.ValidationIssue{Field: "settings", Message: "保存配置失败：" + err.Error()})
		}
	} else {
		issues = append(issues, config.ValidationIssue{Field: "settings", Message: "读取配置失败：" + err.Error()})
	}
	issues = append(issues, app.configService.Validate(app.settings)...)
	return SettingsResponse{
		Settings: app.settings,
		Issues:   issues,
	}
}

func (app *App) SaveSettings(settings config.Settings) SettingsResponse {
	settings.DataPath = app.fixedDataPath()
	backend, packagedDSN := config.PackagedDatabaseConfig()
	settings.DatabaseBackend = backend
	settings.MySQLDSN = packagedDSN
	issues := app.configService.Validate(settings)
	if len(issues) > 0 {
		return SettingsResponse{
			Settings: settings,
			Issues:   issues,
		}
	}
	if err := app.ensureDatabase(); err != nil {
		issues = append(issues, config.ValidationIssue{Field: "database_backend", Message: "初始化数据库失败：" + err.Error()})
		return SettingsResponse{
			Settings: settings,
			Issues:   issues,
		}
	}
	if app.database != nil {
		app.configService.WithDatabase(app.database)
	}
	if err := app.configService.Save(settings); err != nil {
		issues = append(issues, config.ValidationIssue{Field: "settings", Message: "保存配置失败：" + err.Error()})
		return SettingsResponse{
			Settings: settings,
			Issues:   issues,
		}
	}
	savedSettings, err := app.configService.Load(settings)
	if err != nil {
		issues = append(issues, config.ValidationIssue{Field: "settings", Message: "读取已保存配置失败：" + err.Error()})
		app.settings = settings
	} else {
		savedSettings.DataPath = app.fixedDataPath()
		app.settings = savedSettings
	}
	if app.datafetchService != nil {
		app.datafetchService.SetDataPath(app.settings.DataPath)
	}
	app.restartStrategySchedule()
	issues = append(issues, app.configService.Validate(app.settings)...)
	return SettingsResponse{
		Settings: app.settings,
		Issues:   issues,
	}
}

type StrategyScheduleReport struct {
	StartedAt      string                      `json:"started_at"`
	FinishedAt     string                      `json:"finished_at"`
	Success        bool                        `json:"success"`
	Message        string                      `json:"message"`
	WechatContent  string                      `json:"wechat_content"`
	Rows           []StrategyScheduleReportRow `json:"rows"`
	Recommendation position.Recommendation     `json:"recommendation"`
}

type StrategyScheduleReportRow struct {
	Target  string `json:"target"`
	Label   string `json:"label"`
	Status  string `json:"status"`
	Message string `json:"message"`
}

func (app *App) RunStrategyScheduleNow() (StrategyScheduleReport, error) {
	schedule := app.settings.StrategySchedule
	report, _ := app.runScheduledStrategyRefresh(schedule)
	if strings.TrimSpace(schedule.WechatWebhook) != "" {
		content, notifyErr := app.sendStrategyScheduleWechat(schedule, report)
		report.WechatContent = content
		if notifyErr != nil {
			report.Success = false
			if report.Message == "" || report.Message == "策略定时刷新已提交" {
				report.Message = "通用策略已提交，微信通知失败"
			}
			report.Rows = append(report.Rows, StrategyScheduleReportRow{Target: "wechat", Label: "微信通知", Status: "error", Message: notifyErr.Error()})
			app.recordStrategyScheduleReport(report)
			return report, nil
		}
		report.Rows = append(report.Rows, StrategyScheduleReportRow{Target: "wechat", Label: "微信通知", Status: "success", Message: "已发送企业微信通知"})
	}
	app.recordStrategyScheduleReport(report)
	return report, nil
}

func (app *App) TestStrategyScheduleWechat() (StrategyScheduleReport, error) {
	schedule := app.settings.StrategySchedule
	report := StrategyScheduleReport{
		StartedAt:  time.Now().Format(time.RFC3339),
		FinishedAt: time.Now().Format(time.RFC3339),
		Rows:       []StrategyScheduleReportRow{},
	}
	if strings.TrimSpace(schedule.WechatWebhook) == "" {
		report.Success = false
		report.Message = "企业微信 Webhook 未配置"
		return report, nil
	}
	content := strings.Join([]string{
		"## Quant Stock 微信通路测试",
		"",
		"- 时间: " + report.StartedAt,
		"- 结果: 如果看到这条消息，定时器微信通路已连通。",
	}, "\n")
	if err := app.sendWechatMarkdown(schedule.WechatWebhook, content); err != nil {
		report.Success = false
		report.Message = "微信通路测试失败"
		report.WechatContent = content
		report.Rows = append(report.Rows, StrategyScheduleReportRow{Target: "wechat", Label: "微信通知", Status: "error", Message: err.Error()})
		return report, nil
	}
	report.Success = true
	report.Message = "微信通路测试成功"
	report.WechatContent = content
	report.Rows = append(report.Rows, StrategyScheduleReportRow{Target: "wechat", Label: "微信通知", Status: "success", Message: "测试消息已发送"})
	return report, nil
}

func (app *App) ListStrategyScheduleReports() ([]StrategyScheduleReport, error) {
	if err := app.ensureDatabase(); err != nil {
		return []StrategyScheduleReport{}, err
	}
	if err := app.ensureStrategyScheduleRunsTable(); err != nil {
		return []StrategyScheduleReport{}, err
	}
	reports, err := app.listStrategyScheduleReportsFromTable(30)
	if err != nil {
		return []StrategyScheduleReport{}, err
	}
	if len(reports) > 0 {
		return reports, nil
	}
	legacyReports := app.migrateLegacyStrategyScheduleReports()
	if len(legacyReports) > 0 {
		return legacyReports, nil
	}
	return []StrategyScheduleReport{}, nil
}

func (app *App) restartStrategySchedule() {
	app.stopStrategySchedule()
	schedule := app.settings.StrategySchedule
	if !schedule.Enabled {
		return
	}
	baseCtx := app.ctx
	if baseCtx == nil {
		baseCtx = context.Background()
	}
	ctx, cancel := context.WithCancel(baseCtx)
	app.scheduleMu.Lock()
	app.scheduleCancel = cancel
	app.scheduleMu.Unlock()
	go app.strategyScheduleLoop(ctx)
}

func (app *App) stopStrategySchedule() {
	app.scheduleMu.Lock()
	cancel := app.scheduleCancel
	app.scheduleCancel = nil
	app.scheduleMu.Unlock()
	if cancel != nil {
		cancel()
	}
}

func (app *App) strategyScheduleLoop(ctx context.Context) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	app.maybeRunStrategySchedule()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			app.maybeRunStrategySchedule()
		}
	}
}

func (app *App) maybeRunStrategySchedule() {
	schedule := app.settings.StrategySchedule
	if !schedule.Enabled || !strategyScheduleWeekdayEnabled(schedule, time.Now()) {
		return
	}
	now := time.Now()
	if now.Format("15:04") != schedule.TimeOfDay {
		return
	}
	runKey := now.Format("2006-01-02") + " " + schedule.TimeOfDay
	app.scheduleMu.Lock()
	if app.scheduleLastRun == runKey {
		app.scheduleMu.Unlock()
		return
	}
	app.scheduleLastRun = runKey
	app.scheduleMu.Unlock()
	go func() {
		report, _ := app.runScheduledStrategyRefresh(schedule)
		if strings.TrimSpace(schedule.WechatWebhook) != "" {
			content, err := app.sendStrategyScheduleWechat(schedule, report)
			report.WechatContent = content
			if err != nil {
				report.Success = false
				report.Rows = append(report.Rows, StrategyScheduleReportRow{Target: "wechat", Label: "微信通知", Status: "error", Message: err.Error()})
			} else {
				report.Rows = append(report.Rows, StrategyScheduleReportRow{Target: "wechat", Label: "微信通知", Status: "success", Message: "已发送企业微信通知"})
			}
		}
		app.recordStrategyScheduleReport(report)
	}()
}

func strategyScheduleWeekdayEnabled(schedule config.StrategyScheduleSettings, now time.Time) bool {
	weekday := int(now.Weekday())
	if weekday == 0 {
		weekday = 7
	}
	for _, item := range schedule.Weekdays {
		if item == weekday {
			return true
		}
	}
	return false
}

func (app *App) runScheduledStrategyRefresh(schedule config.StrategyScheduleSettings) (StrategyScheduleReport, error) {
	app.scheduleRunMu.Lock()
	defer app.scheduleRunMu.Unlock()
	started := time.Now()
	report := StrategyScheduleReport{
		StartedAt: started.Format(time.RFC3339),
		Rows:      []StrategyScheduleReportRow{},
	}
	add := func(target, label string, err error, message string) {
		status := "success"
		if err != nil {
			status = "error"
			message = err.Error()
		}
		report.Rows = append(report.Rows, StrategyScheduleReportRow{Target: target, Label: label, Status: status, Message: message})
	}
	if rec, reused, sourceAt, err := app.currentVersionRecommendation(); reused {
		report.Recommendation = rec
		app.markProfitArenaRebalanceReady(rec, "schedule_reuse", "已复用当前通用策略调仓计划")
		add("reuse", "买入清单版本", nil, "已检测到当前通用策略买入清单，无需重复刷新，来源 "+sourceAt)
		add("rebalance", "一键调仓", nil, fmt.Sprintf("已复用 %s 调仓计划，买入 %d，卖出 %d", firstNonEmpty(rec.Date, "今日"), rec.NBuy, rec.NSell))
		report.FinishedAt = time.Now().Format(time.RFC3339)
		report.Success = true
		report.Message = "当前买入清单版本已存在，直接发送微信消息"
		return report, nil
	} else if err != nil {
		add("reuse", "买入清单版本", err, "")
	}
	if err := app.runDataUpdateAndWait(); err != nil {
		add("data_update", "股票数据", err, "")
		app.markProfitArenaRebalanceError("schedule_blocked_data", "股票数据更新失败，未生成本次通用策略调仓计划: "+err.Error())
		report.FinishedAt = time.Now().Format(time.RFC3339)
		report.Success = false
		report.Message = "股票数据更新失败，已停止买入清单刷新"
		return report, err
	}
	add("data_update", "股票数据", nil, "已拉取最新股票数据")
	if err := app.waitFreshRunStatus(app.GetFactorSnapshotStatus, "通用策略因子截面", started, 45*time.Minute, true); err != nil {
		add("factor_snapshot", "通用策略因子截面", err, "")
		app.markProfitArenaRebalanceError("schedule_blocked_factor_snapshot", "通用策略因子截面生成失败，未生成本次调仓计划: "+err.Error())
		report.FinishedAt = time.Now().Format(time.RFC3339)
		report.Success = false
		report.Message = "通用策略因子截面生成失败，已停止买入清单刷新"
		return report, err
	}
	add("factor_snapshot", "通用策略因子截面", nil, "已生成本次通用策略因子截面")
	// 一键调仓计划完全依赖通用策略最新截面预测，因此无论是否单独勾选 arena，
	// 都强制先刷新最新截面，避免使用过期的 is_latest 数据导致 0 条或陈旧买入清单。
	var arenaErr error
	{
		taskDTO, err := app.RunProfitArenaLatestInference()
		message := "已完成通用策略最新截面推理"
		if err == nil && taskDTO.ID != "" {
			err = app.waitTaskSuccess(taskDTO.ID, 45*time.Minute)
			message = "已完成通用策略最新截面推理，任务 " + taskDTO.ID
		}
		arenaErr = err
		add("arena", "通用策略", err, message)
	}
	if arenaErr != nil {
		rebalanceErr := errors.New("通用策略买入清单刷新失败，未生成本次调仓计划")
		app.markProfitArenaRebalanceError("schedule_blocked_arena", rebalanceErr.Error()+": "+arenaErr.Error())
		add("rebalance", "一键调仓", rebalanceErr, "")
		report.FinishedAt = time.Now().Format(time.RFC3339)
		report.Success = false
		report.Message = "通用策略买入清单刷新失败，已停止调仓计划生成"
		return report, arenaErr
	}
	app.markProfitArenaRebalanceRunning("schedule_prepare", "正在生成通用策略调仓计划")
	rec, recErr := app.GetPositionRecommendation()
	if recErr != nil {
		app.markProfitArenaRebalanceError("schedule_error", "通用策略调仓计划生成失败: "+recErr.Error())
		add("rebalance", "一键调仓", recErr, "")
	} else {
		report.Recommendation = rec
		app.markProfitArenaRebalanceReady(rec, "schedule_ready", "已生成通用策略调仓计划")
		add("rebalance", "一键调仓", nil, fmt.Sprintf("已生成 %d 条调仓计划，买入 %d，卖出 %d", len(rec.Rows), rec.NBuy, rec.NSell))
	}
	report.FinishedAt = time.Now().Format(time.RFC3339)
	success := true
	for _, row := range report.Rows {
		if row.Status != "success" {
			success = false
			break
		}
	}
	report.Success = success
	if len(report.Rows) == 0 {
		report.Success = false
		report.Message = "没有勾选通用策略模型"
		return report, errors.New(report.Message)
	}
	if success {
		report.Message = "通用策略买入清单与一键调仓已更新"
		return report, nil
	}
	report.Message = "部分通用策略任务提交失败"
	return report, errors.New(report.Message)
}

func (app *App) currentVersionRecommendation() (position.Recommendation, bool, string, error) {
	if app.database == nil || app.database.Conn() == nil {
		return position.Recommendation{}, false, "", nil
	}
	start, end := currentRecommendationVersionWindow(time.Now())
	reports, err := app.ListStrategyScheduleReports()
	if err != nil {
		return position.Recommendation{}, false, "", err
	}
	for _, report := range reports {
		if !reportHasSuccessfulRecommendation(report) {
			continue
		}
		reportAt, ok := parseScheduleReportTime(firstNonEmpty(report.FinishedAt, report.StartedAt))
		if !ok || reportAt.Before(start) || !reportAt.Before(end) {
			continue
		}
		return report.Recommendation, true, reportAt.Format(time.RFC3339), nil
	}
	return position.Recommendation{}, false, "", nil
}

func reportHasSuccessfulRecommendation(report StrategyScheduleReport) bool {
	if len(report.Recommendation.Rows) == 0 {
		return false
	}
	for _, row := range report.Rows {
		if row.Target == "rebalance" && row.Status == "success" {
			return true
		}
	}
	return false
}

func currentRecommendationVersionWindow(now time.Time) (time.Time, time.Time) {
	loc, err := time.LoadLocation("Asia/Shanghai")
	if err != nil {
		loc = time.Local
	}
	n := now.In(loc)
	today15 := time.Date(n.Year(), n.Month(), n.Day(), 15, 0, 0, 0, loc)
	if n.Before(today15) {
		start := time.Date(n.Year(), n.Month(), n.Day(), 22, 0, 0, 0, loc).AddDate(0, 0, -1)
		return start, today15
	}
	return today15, today15.Add(24 * time.Hour)
}

func parseScheduleReportTime(value string) (time.Time, bool) {
	value = strings.TrimSpace(value)
	if value == "" {
		return time.Time{}, false
	}
	layouts := []string{time.RFC3339, "2006-01-02T15:04:05", "2006-01-02 15:04:05", "20060102"}
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

func (app *App) runDataUpdateAndWait() error {
	started := time.Now()
	allowExisting := false
	if err := app.RunDataUpdate(datafetch.UpdateRequest{Phase: "all", StartDate: "", Dataset: "", ExcludeDatasets: []string{"top10_holders"}}); err != nil {
		if !errors.Is(err, datafetch.ErrAlreadyRunning) {
			return err
		}
		allowExisting = true
	}
	return app.waitFreshDataUpdateStatus(started, 60*time.Minute, allowExisting)
}

func (app *App) waitFreshDataUpdateStatus(notBefore time.Time, timeout time.Duration, allowExisting bool) error {
	deadline := time.Now().Add(timeout)
	sawRunning := false
	for {
		status, err := app.GetDataUpdateStatus()
		if err != nil {
			return err
		}
		state := strings.ToLower(status.State)
		updatedAt, updatedOK := parseRunStatusTime(status.UpdatedAt)
		startedAt, startedOK := parseRunStatusTime(status.StartedAt)
		fresh := (updatedOK && !updatedAt.Before(notBefore.Add(-2*time.Second))) || (startedOK && !startedAt.Before(notBefore.Add(-2*time.Second)))
		if allowExisting && (state == "running" || state == "queued" || state == "created") {
			fresh = true
		}
		switch state {
		case "running", "queued", "created":
			if fresh {
				sawRunning = true
			}
		case "done", "success":
			if fresh || sawRunning {
				return nil
			}
		case "error", "failed":
			if fresh || sawRunning {
				if strings.TrimSpace(status.Message) != "" {
					return errors.New(status.Message)
				}
				return errors.New("数据更新失败")
			}
		case "idle":
			if sawRunning && fresh {
				return nil
			}
		}
		if time.Now().After(deadline) {
			return errors.New("数据更新超时")
		}
		time.Sleep(3 * time.Second)
	}
}

func (app *App) waitPositionRunStatus(getStatus func() (position.RunStatus, error), timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	sawRunning := false
	for {
		status, err := getStatus()
		if err != nil {
			return err
		}
		state := strings.ToLower(status.State)
		switch state {
		case "running", "queued":
			sawRunning = true
		case "done", "success":
			return nil
		case "error", "failed":
			if strings.TrimSpace(status.Message) != "" {
				return errors.New(status.Message)
			}
			return errors.New(status.Name + "失败")
		case "idle":
			if sawRunning {
				return nil
			}
		}
		if time.Now().After(deadline) {
			return errors.New("任务等待超时")
		}
		time.Sleep(3 * time.Second)
	}
}

func (app *App) waitFreshRunStatus(getStatus func() (position.RunStatus, error), taskName string, notBefore time.Time, timeout time.Duration, allowExisting bool) error {
	deadline := time.Now().Add(timeout)
	sawRunning := false
	for {
		status, err := getStatus()
		if err != nil {
			return err
		}
		state := strings.ToLower(status.State)
		updatedAt, updatedOK := parseRunStatusTime(status.UpdatedAt)
		fresh := updatedOK && !updatedAt.Before(notBefore.Add(-2*time.Second))
		if allowExisting && (state == "running" || state == "queued" || state == "created") {
			fresh = true
		}
		switch state {
		case "running", "queued", "created":
			if fresh {
				sawRunning = true
			}
		case "done", "success":
			if fresh || sawRunning {
				return nil
			}
		case "error", "failed", "cancelled", "interrupted":
			if fresh || sawRunning {
				if strings.TrimSpace(status.Message) != "" {
					return errors.New(status.Message)
				}
				return fmt.Errorf("%s失败", taskName)
			}
		case "idle":
			if sawRunning && fresh {
				return nil
			}
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("%s等待超时", taskName)
		}
		time.Sleep(3 * time.Second)
	}
}

func (app *App) waitTaskSuccess(id string, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for {
		dto, err := app.RefreshTaskStatus(id)
		if err != nil {
			return err
		}
		switch dto.Status {
		case task.StatusSuccess:
			return nil
		case task.StatusFailed, task.StatusCancelled, task.StatusInterrupted:
			if strings.TrimSpace(dto.ErrorMessage) != "" {
				return errors.New(dto.ErrorMessage)
			}
			return fmt.Errorf("任务 %s %s", id, dto.Status)
		}
		if time.Now().After(deadline) {
			return errors.New("因子研究推理等待超时")
		}
		time.Sleep(3 * time.Second)
	}
}

func (app *App) recordStrategyScheduleReport(report StrategyScheduleReport) {
	if app.database == nil || app.database.Conn() == nil {
		return
	}
	_ = app.ensureStrategyScheduleRunsTable()
	data, err := json.Marshal(report)
	if err != nil {
		return
	}
	now := time.Now().Format(time.RFC3339)
	success := 0
	if report.Success {
		success = 1
	}
	_, _ = app.database.Conn().Exec(
		`INSERT INTO strategy_schedule_runs (started_at, finished_at, success, message, report_json, created_at)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		report.StartedAt, report.FinishedAt, success, report.Message, string(data), now,
	)
}

func (app *App) ensureStrategyScheduleRunsTable() error {
	if app.database == nil || app.database.Conn() == nil {
		return errors.New("database is not initialized")
	}
	_, err := app.database.Conn().Exec(`CREATE TABLE IF NOT EXISTS strategy_schedule_runs (
		id BIGINT PRIMARY KEY AUTO_INCREMENT,
		started_at VARCHAR(191) NOT NULL,
		finished_at VARCHAR(191) NOT NULL,
		success BIGINT NOT NULL DEFAULT 0,
		message LONGTEXT NOT NULL,
		report_json LONGTEXT NOT NULL,
		created_at VARCHAR(191) NOT NULL
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`)
	return err
}

func (app *App) listStrategyScheduleReportsFromTable(limit int) ([]StrategyScheduleReport, error) {
	if limit <= 0 {
		limit = 30
	}
	rows, err := app.database.Conn().Query(`SELECT report_json FROM strategy_schedule_runs ORDER BY id DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	reports := []StrategyScheduleReport{}
	for rows.Next() {
		var payload string
		if err := rows.Scan(&payload); err != nil {
			return nil, err
		}
		var report StrategyScheduleReport
		if err := json.Unmarshal([]byte(payload), &report); err == nil {
			if isWechatConnectivityReport(report) {
				continue
			}
			reports = append(reports, report)
		}
	}
	return reports, rows.Err()
}

func isWechatConnectivityReport(report StrategyScheduleReport) bool {
	if strings.Contains(report.Message, "微信通路测试") {
		return true
	}
	if strings.Contains(report.WechatContent, "微信通路测试") {
		return true
	}
	return len(report.Rows) == 1 &&
		report.Rows[0].Target == "wechat" &&
		strings.Contains(report.Rows[0].Message, "测试消息")
}

func (app *App) migrateLegacyStrategyScheduleReports() []StrategyScheduleReport {
	var payload string
	err := app.database.Conn().QueryRow(fmt.Sprintf(`SELECT value FROM cfg_app_settings WHERE %s = ?`, app.cfgAppSettingsKeyColumn()), "strategy_schedule_reports").Scan(&payload)
	if err != nil {
		return []StrategyScheduleReport{}
	}
	var reports []StrategyScheduleReport
	if err := json.Unmarshal([]byte(payload), &reports); err != nil {
		return []StrategyScheduleReport{}
	}
	for i := len(reports) - 1; i >= 0; i-- {
		if isWechatConnectivityReport(reports[i]) {
			continue
		}
		app.recordStrategyScheduleReport(reports[i])
	}
	_, _ = app.database.Conn().Exec(fmt.Sprintf(`DELETE FROM cfg_app_settings WHERE %s = ?`, app.cfgAppSettingsKeyColumn()), "strategy_schedule_reports")
	migrated, err := app.listStrategyScheduleReportsFromTable(30)
	if err != nil {
		return reports
	}
	return migrated
}

func (app *App) sendStrategyScheduleWechat(schedule config.StrategyScheduleSettings, report StrategyScheduleReport) (string, error) {
	webhook := strings.TrimSpace(schedule.WechatWebhook)
	if webhook == "" {
		return "", nil
	}
	content := app.strategyScheduleWechatContent(schedule, report)
	return content, app.sendWechatMarkdown(webhook, content)
}

func (app *App) strategyScheduleWechatContent(schedule config.StrategyScheduleSettings, report StrategyScheduleReport) string {
	statusText := "完成"
	if !report.Success {
		statusText = "需处理"
	}
	lines := []string{
		"## Quant Stock 每日股票更新",
		"",
		fmt.Sprintf("> [%s] %s", statusText, firstNonEmpty(report.Message, "定时任务已结束")),
		"",
		fmt.Sprintf("**运行**：%s - %s", formatScheduleTime(report.StartedAt), formatScheduleTime(report.FinishedAt)),
	}
	if report.Recommendation.GeneratedAt != "" || len(report.Recommendation.Rows) > 0 {
		lines = append(lines, "")
		lines = append(lines, fmt.Sprintf("**截面**：%s", formatScheduleTradeDate(report.Recommendation.Date)))
		lines = append(lines, fmt.Sprintf("**调仓**：买入 %d｜卖出 %d｜计划 %d", report.Recommendation.NBuy, report.Recommendation.NSell, len(report.Recommendation.Rows)))
		actionRows := scheduleRebalanceRows(report.Recommendation.Rows, 12)
		if len(actionRows) == 0 {
			lines = append(lines, "", "### 今日计划", "暂无需要调仓的股票。")
		} else {
			lines = append(lines, "", "### 今日计划")
			for i, item := range actionRows {
				lines = append(lines, formatScheduleRebalanceLine(i+1, item))
			}
			if len(report.Recommendation.Rows) > len(actionRows) {
				lines = append(lines, fmt.Sprintf("> 还有 %d 条计划，请在桌面端查看完整列表。", len(report.Recommendation.Rows)-len(actionRows)))
			}
		}
	}
	lines = append(lines, "")
	lines = append(lines, "### 执行状态")
	for _, row := range report.Rows {
		mark := "[成功]"
		if row.Status != "success" {
			mark = "[异常]"
		}
		lines = append(lines, fmt.Sprintf("- %s %s：%s", mark, row.Label, firstNonEmpty(row.Message, "-")))
	}
	if len(schedule.WechatUsers) > 0 {
		mentions := make([]string, 0, len(schedule.WechatUsers))
		for _, user := range schedule.WechatUsers {
			user = strings.Trim(strings.TrimSpace(user), "@")
			if user != "" {
				mentions = append(mentions, "<@"+user+">")
			}
		}
		if len(mentions) > 0 {
			lines = append(lines, "", strings.Join(mentions, " "))
		}
	}
	return strings.Join(lines, "\n")
}

func (app *App) sendWechatMarkdown(webhook string, content string) error {
	webhook = strings.TrimSpace(webhook)
	if webhook == "" {
		return errors.New("企业微信 Webhook 未配置")
	}
	payload := map[string]any{
		"msgtype": "markdown",
		"markdown": map[string]string{
			"content": content,
		},
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequest(http.MethodPost, webhook, bytes.NewReader(data))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("企业微信通知失败: HTTP %d %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	var result struct {
		ErrCode int    `json:"errcode"`
		ErrMsg  string `json:"errmsg"`
	}
	if len(body) > 0 && json.Unmarshal(body, &result) == nil && result.ErrCode != 0 {
		return fmt.Errorf("企业微信通知失败: %d %s", result.ErrCode, result.ErrMsg)
	}
	return nil
}

func scheduleRebalanceRows(rows []position.RecommendationItem, limit int) []position.RecommendationItem {
	out := make([]position.RecommendationItem, 0, len(rows))
	for _, row := range rows {
		switch row.Action {
		case "新建", "加仓", "减仓", "清仓":
			out = append(out, row)
		}
	}
	if limit > 0 && len(out) > limit {
		return out[:limit]
	}
	return out
}

func formatScheduleRebalanceLine(rank int, item position.RecommendationItem) string {
	action := strings.TrimSpace(item.Action)
	if action == "" {
		action = "观察"
	}
	name := strings.TrimSpace(item.Name)
	if name == "" {
		name = item.TSCode
	}
	return fmt.Sprintf(
		"%d. **%s** `%s`｜%s %d股\n   买≤%s｜卖≥%s｜止损 %s",
		rank,
		name,
		item.TSCode,
		action,
		item.TargetShares,
		formatSchedulePrice(item.BuyTriggerPrice),
		formatSchedulePrice(item.SellTargetPrice),
		formatSchedulePrice(item.StopPrice),
	)
}

func formatScheduleTime(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return "-"
	}
	if t, ok := parseScheduleReportTime(value); ok {
		loc, err := time.LoadLocation("Asia/Shanghai")
		if err == nil {
			t = t.In(loc)
		}
		return t.Format("01-02 15:04")
	}
	return value
}

func formatScheduleTradeDate(value string) string {
	value = strings.TrimSpace(value)
	if len(value) == 8 {
		return value[:4] + "-" + value[4:6] + "-" + value[6:8]
	}
	return firstNonEmpty(value, "-")
}

func formatSchedulePrice(value float64) string {
	if value <= 0 || math.IsNaN(value) || math.IsInf(value, 0) {
		return "-"
	}
	return fmt.Sprintf("¥%.2f", value)
}

func (app *App) databaseConfigChanged(settings config.Settings) bool {
	current := config.NormalizeForCompare(app.settings)
	next := config.NormalizeForCompare(settings)
	return current.DataPath != next.DataPath ||
		current.DatabaseBackend != next.DatabaseBackend ||
		current.MySQLDSN != next.MySQLDSN
}

func (app *App) hasActiveRuntimeWork() (bool, string) {
	if app.database == nil {
		if len(productionWorkerPIDs()) > 0 {
			return true, "仍有生产 Python 进程"
		}
		return false, ""
	}
	app.reconcileProductionWorkerProcesses()
	app.reconcileStaleRunStatusProcesses()
	app.reconcileStaleRunStatusTaskJobs()
	db := app.database.Conn()
	var evaluationCount int
	if err := db.QueryRow(`SELECT COUNT(*) FROM task_jobs
		WHERE task_type IN (?, ?)
		  AND status IN ('queued','running')
		  AND (task_type <> ? OR COALESCE(params_json, '') LIKE '%profit_arena%')`,
		string(task.TypeModelTraining), string(task.TypeFactorSnapshot), string(task.TypeModelTraining),
	).Scan(&evaluationCount); err == nil && evaluationCount > 0 {
		return true, "生产任务正在运行或排队"
	}
	var runStatusCount int
	if err := db.QueryRow(`SELECT COUNT(*) FROM task_run_status WHERE state = 'running'`).Scan(&runStatusCount); err == nil && runStatusCount > 0 {
		return true, "Python 状态任务正在运行"
	}
	if len(productionWorkerPIDs()) > 0 {
		return true, "仍有生产 Python 进程"
	}
	return false, ""
}

func (app *App) activateBestStrategyModelRun(strategy string) {
	if app.database == nil || app.database.Conn() == nil {
		return
	}
	if err := app.ensureStrategyModelActiveTable(); err != nil {
		return
	}
	strategy = strings.TrimSpace(strategy)
	if strategy == "" {
		return
	}
	strategy = normalizeDesktopActiveStrategy(strategy)
	if strategy == "" {
		return
	}
	if runID := app.activeArenaChampionRunID(strategy); runID != "" && app.strategyModelRunAdmissible(strategy, runID) {
		now := time.Now().Format(time.RFC3339)
		_, _ = app.database.Conn().Exec(
			app.database.UpsertSQL("strategy_model_active", []string{"strategy", "run_id", "updated_at"}, []string{"strategy"}, []string{"run_id", "updated_at"}),
			strategy, strings.TrimSpace(runID), now,
		)
		return
	}
	query := ""
	switch strategy {
	case profitArenaStrategyID:
		query = `SELECT run_id
			FROM profit_arena_runs
			WHERE status = 'success'
			  AND COALESCE(JSON_EXTRACT(summary_json, '$.best.capital_annual_return') + 0, 0) > 0
			  AND COALESCE(JSON_EXTRACT(summary_json, '$.best.capital_max_drawdown') + 0, -1) >= -0.22
			  AND COALESCE(JSON_EXTRACT(summary_json, '$.best.rank_ic') + 0, -1) >= 0.08
			  AND COALESCE(JSON_EXTRACT(summary_json, '$.best.trade_count') + 0, 0) >= 120
			  AND LOWER(REPLACE(COALESCE(JSON_EXTRACT(summary_json, '$.best.capacity_status'), 'pass'), '"', '')) <> 'fail'
			  AND LOWER(REPLACE(COALESCE(JSON_EXTRACT(summary_json, '$.best.portfolio_risk_status'), 'pass'), '"', '')) <> 'fail'
			  AND LOWER(REPLACE(COALESCE(JSON_EXTRACT(summary_json, '$.best_challenger_score_components.hard_gate_ok'), 'true'), '"', '')) NOT IN ('false', '0')
			ORDER BY
			  COALESCE(JSON_EXTRACT(summary_json, '$.best_challenger_score_components.score') + 0, 0) DESC,
			  COALESCE(JSON_EXTRACT(summary_json, '$.best.capital_annual_return') + 0, 0) DESC,
			  updated_at DESC
			LIMIT 1`
	default:
		return
	}
	var runID string
	err := app.database.Conn().QueryRow(query).Scan(&runID)
	if err != nil || strings.TrimSpace(runID) == "" {
		return
	}
	now := time.Now().Format(time.RFC3339)
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL("strategy_model_active", []string{"strategy", "run_id", "updated_at"}, []string{"strategy"}, []string{"run_id", "updated_at"}),
		strategy, strings.TrimSpace(runID), now,
	)
}

func normalizeDesktopActiveStrategy(strategy string) string {
	switch strings.TrimSpace(strategy) {
	case profitArenaStrategyID, "profit_arena":
		return profitArenaStrategyID
	default:
		return ""
	}
}

func (app *App) ensureStrategyArenaChampionTable() error {
	if app.database == nil || app.database.Conn() == nil {
		return errors.New("database is not initialized")
	}
	_, err := app.database.Conn().Exec(`CREATE TABLE IF NOT EXISTS strategy_arena_champions (
		strategy_id VARCHAR(64) NOT NULL,
		arena_name VARCHAR(128) NOT NULL,
		champion_run_id VARCHAR(255) NOT NULL DEFAULT '',
		champion_version BIGINT NOT NULL DEFAULT 0,
		arena_score DOUBLE NOT NULL DEFAULT 0,
		qualification_status VARCHAR(32) NOT NULL DEFAULT '',
		champion_type VARCHAR(32) NOT NULL DEFAULT '',
		validation_status VARCHAR(32) NOT NULL DEFAULT '',
		champion_json LONGTEXT,
		updated_at VARCHAR(64) NOT NULL,
		PRIMARY KEY(strategy_id, arena_name)
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`)
	return err
}

func (app *App) activeArenaChampionRunID(strategy string) string {
	if app.database == nil || app.database.Conn() == nil {
		return ""
	}
	if err := app.ensureStrategyArenaChampionTable(); err != nil {
		return ""
	}
	var runID string
	_ = app.database.Conn().QueryRow(`SELECT champion_run_id
		FROM strategy_arena_champions
		WHERE strategy_id = ?
		  AND COALESCE(champion_run_id, '') <> ''
		ORDER BY
		  CASE
		    WHEN validation_status = 'confirmed' THEN 3
		    WHEN validation_status = 'pending_rerun' THEN 2
		    ELSE 1
		  END DESC,
		  arena_score DESC,
		  updated_at DESC
		LIMIT 1`, strings.TrimSpace(strategy)).Scan(&runID)
	return strings.TrimSpace(runID)
}

func (app *App) ensureStrategyModelActiveTable() error {
	if app.database == nil || app.database.Conn() == nil {
		return errors.New("database is not initialized")
	}
	_, err := app.database.Conn().Exec(`CREATE TABLE IF NOT EXISTS strategy_model_active (
		strategy VARCHAR(191) PRIMARY KEY,
		run_id VARCHAR(191) NOT NULL,
		updated_at VARCHAR(191) NOT NULL
	)`)
	return err
}

func (app *App) strategyModelRunAdmissible(strategy string, runID string) bool {
	if app.database == nil || app.database.Conn() == nil {
		return false
	}
	strategy = strings.TrimSpace(strategy)
	runID = strings.TrimSpace(runID)
	if strategy == "" || runID == "" {
		return false
	}
	query := ""
	switch strategy {
	case profitArenaStrategyID:
		query = `SELECT COUNT(*)
			FROM profit_arena_runs
			WHERE run_id = ? AND status = 'success'
			  AND COALESCE(JSON_EXTRACT(summary_json, '$.best.capital_annual_return') + 0, 0) > 0
			  AND COALESCE(JSON_EXTRACT(summary_json, '$.best.capital_max_drawdown') + 0, -1) >= -0.22
			  AND COALESCE(JSON_EXTRACT(summary_json, '$.best.rank_ic') + 0, -1) >= 0.08
			  AND COALESCE(JSON_EXTRACT(summary_json, '$.best.trade_count') + 0, 0) >= 120
			  AND LOWER(REPLACE(COALESCE(JSON_EXTRACT(summary_json, '$.best.capacity_status'), 'pass'), '"', '')) <> 'fail'
			  AND LOWER(REPLACE(COALESCE(JSON_EXTRACT(summary_json, '$.best.portfolio_risk_status'), 'pass'), '"', '')) <> 'fail'
			  AND LOWER(REPLACE(COALESCE(JSON_EXTRACT(summary_json, '$.best_challenger_score_components.hard_gate_ok'), 'true'), '"', '')) NOT IN ('false', '0')`
	default:
		return false
	}
	var count int
	_ = app.database.Conn().QueryRow(query, runID).Scan(&count)
	return count > 0
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
	var candidateName string
	var candidateStatus string
	var candidateScore float64
	var weightsJSON string
	var validationStatus string
	row := app.database.Conn().QueryRow(
		`SELECT name, status, score, weights_json, COALESCE(validation_status,'')
		 FROM eval_portfolio_candidates WHERE run_id = ? AND candidate_id = ?`,
		runID,
		candidateID,
	)
	if err := row.Scan(&candidateName, &candidateStatus, &candidateScore, &weightsJSON, &validationStatus); err != nil {
		return SettingsResponse{}, err
	}
	if candidateStatus != "ok" {
		return SettingsResponse{}, fmt.Errorf("candidate is not usable: status=%s", candidateStatus)
	}
	var weights map[string]float64
	if err := json.Unmarshal([]byte(weightsJSON), &weights); err != nil {
		return SettingsResponse{}, err
	}
	if len(weights) == 0 {
		return SettingsResponse{}, errors.New("candidate has no strategy weights")
	}
	if app.database != nil {
		app.configService.WithDatabase(app.database)
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
	active := activePortfolioCandidateRecord{
		RunID:            runID,
		CandidateID:      candidateID,
		Name:             candidateName,
		Status:           candidateStatus,
		Score:            candidateScore,
		Weights:          weights,
		ValidationStatus: validationStatus,
		AppliedAt:        time.Now().Format(time.RFC3339),
	}
	activeJSON, _ := json.Marshal(active)
	now := time.Now().Format(time.RFC3339)
	if _, err := app.database.Conn().Exec(
		app.database.UpsertSQL("cfg_app_settings", []string{"key", "value", "updated_at"}, []string{"key"}, []string{"value", "updated_at"}),
		"active_portfolio_candidate", string(activeJSON), now,
	); err != nil {
		return SettingsResponse{}, err
	}
	_, _ = app.database.Conn().Exec(`DELETE FROM rec_daily_recommendations`)
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
	if err := app.runMarketDataFileScan(); err != nil {
		return nil, err
	}
	return app.marketService.List()
}

func (app *App) ListMarketDataFiles() ([]market.DataFileDTO, error) {
	if err := app.ensureMarketService(); err != nil {
		return nil, err
	}
	return app.marketService.List()
}

func (app *App) runMarketDataFileScan() error {
	if err := app.ensureDatabase(); err != nil {
		return err
	}
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return errors.New("数据路径未设置")
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	logDir := filepath.Join(dataPath, "logs", "data_file_scan")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return err
	}
	logPath := filepath.Join(logDir, time.Now().Format("20060102_150405")+".log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	defer logFile.Close()
	args := []string{
		"scripts/scan_market_files.py",
		"--data-root", dataPath,
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv()...)...)
	if err := cmd.Run(); err != nil {
		app.markPythonStatusTaskError("data_file_scan", "本地数据文件扫描失败: "+err.Error()+"，日志: "+logPath)
		return fmt.Errorf("本地数据文件扫描失败: %w，请查看日志 %s", err, logPath)
	}
	return nil
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

func (app *App) waitPythonStatusTask(cmd *exec.Cmd, logFile *os.File, logPath string, taskName string) {
	err := cmd.Wait()
	_ = logFile.Close()
	if err == nil || app.database == nil {
		return
	}
	status, statusErr := app.positionService.GetRunStatus(taskName)
	if statusErr == nil && status.State != "running" {
		return
	}
	app.markPythonStatusTaskError(taskName, "分析进程已退出: "+err.Error()+"，日志: "+logPath)
}

func (app *App) markPythonStatusTaskError(taskName string, message string) {
	if app.database == nil {
		return
	}
	now := time.Now().Format(time.RFC3339)
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{"task", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"state", "message", "updated_at", "finished_at"},
		),
		taskName, "error", 0, 0, "", "", message, now, now, now,
	)
	app.ensureRunStatusTaskType(taskName)
	app.upsertRunStatusTaskJobError(taskName, message)
}

func (app *App) markPythonStatusTaskMessage(taskName string, state string, message string) {
	if app.database == nil {
		return
	}
	state = strings.TrimSpace(state)
	if state == "" {
		state = "idle"
	}
	now := time.Now().Format(time.RFC3339)
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{"task", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"state", "message", "updated_at"},
		),
		taskName, state, 0, 0, "", "", message, now, now, "",
	)
	app.ensureRunStatusTaskType(taskName)
	app.upsertRunStatusTaskJobMessage(taskName, state, message)
}

func (app *App) markPythonStatusTaskStage(taskName string, taskType string, state string, idx int, total int, stage string, name string, message string) {
	if app.database == nil {
		return
	}
	state = strings.TrimSpace(state)
	if state == "" {
		state = "running"
	}
	if total <= 0 {
		total = 100
	}
	if idx < 0 {
		idx = 0
	}
	now := time.Now().Format(time.RFC3339)
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{"task", "task_type", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"task_type", "state", "idx", "total", "stage", "name", "message", "updated_at", "finished_at"},
		),
		taskName, taskType, state, idx, total, stage, name, message, now, now, "",
	)
	app.ensureRunStatusTaskType(taskName)
	app.upsertRunStatusTaskJobMessage(taskName, state, message)
}

func (app *App) markGenericPythonWorkerStarted(taskName string, taskType string, pid int, logPath string) {
	if app.database == nil {
		return
	}
	now := time.Now().Format(time.RFC3339)
	displayName := runStatusTaskDisplayName(taskName)
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{"task", "task_type", "state", "idx", "total", "stage", "name", "message", "worker_pid", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"task_type", "state", "idx", "total", "stage", "name", "message", "worker_pid", "updated_at", "finished_at"},
		),
		taskName, taskType, "running", 0, 5, "prepare", "启动"+displayName+"进程", "日志: "+logPath, pid, now, now, "",
	)
	app.upsertRunStatusTaskJobStarted(taskName, taskType, pid, logPath)
}

func runStatusTaskJobID(taskName string) string {
	return "run_status:" + taskName
}

func runStatusTaskDisplayName(taskName string) string {
	switch taskName {
	case "factor_snapshot":
		return "因子快照"
	case profitArenaStrategyID:
		return "通用策略"
	case "data_update":
		return "数据更新"
	case "data_file_scan":
		return "本地数据文件扫描"
	default:
		return taskName
	}
}

func runStatusArenaStrategySummary(taskName string, runID string, params map[string]any) map[string]any {
	if modelTrainingStrategy(params) != profitArenaStrategyID && taskName != profitArenaStrategyID {
		return nil
	}
	arenaName := strings.TrimSpace(stringParam(params, "arena_name", profitArenaDefaultArenaName))
	if arenaName == "" {
		arenaName = profitArenaDefaultArenaName
	}
	taskLabel := "通用策略 · 版本训练"
	if strings.TrimSpace(stringParam(params, "latest_inference_source_run_id", stringParam(params, "source_run_id", ""))) != "" || strings.TrimSpace(stringParam(params, "profile", "")) == "inference" {
		taskLabel = "通用策略 · 最新截面推理"
	} else if strings.TrimSpace(stringParam(params, "eval_only_predictions", "")) != "" {
		taskLabel = "通用策略 · 快速重评估"
	}
	return map[string]any{
		"run_id":             strings.TrimSpace(runID),
		"strategy_id":        profitArenaStrategyID,
		"display_name":       "通用策略",
		"artifact_dir_name":  "profit_arena",
		"default_arena_name": profitArenaDefaultArenaName,
		"arena_name":         arenaName,
		"task_key":           "arena:" + profitArenaStrategyID + ":" + arenaName,
		"task_label":         taskLabel,
		"tables": map[string]any{
			"run":        "profit_arena_runs",
			"evaluation": "profit_arena_evaluations",
			"prediction": "profit_arena_predictions",
			"feature":    "profit_arena_features",
		},
	}
}

func (app *App) upsertRunStatusTaskJobStarted(taskName string, taskType string, pid int, logPath string) {
	if app.database == nil {
		return
	}
	now := time.Now()
	params := mustJSON(map[string]any{"status_task": taskName})
	summary := mustJSON(map[string]any{"status_task": taskName, "stage": "prepare", "name": "启动任务", "message": "日志: " + logPath, "idx": 0, "total": 100})
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_jobs",
			[]string{"id", "name", "task_type", "status", "progress", "params_json", "summary_json", "result_path", "log_path", "worker_type", "worker_pid", "external_run_id", "error_message", "parent_id", "group_run_id", "subtask_key", "subtask_name", "sequence", "total", "attempt", "max_attempts", "created_at", "queued_at", "started_at", "finished_at", "updated_at"},
			[]string{"id"},
			[]string{"name", "task_type", "status", "progress", "params_json", "summary_json", "log_path", "worker_type", "worker_pid", "error_message", "started_at", "finished_at", "updated_at"},
		),
		runStatusTaskJobID(taskName), runStatusTaskDisplayName(taskName), taskType, string(task.StatusRunning), 0.02, params, summary, "", logPath, "python", pid, taskName, "", "", "", taskName, runStatusTaskDisplayName(taskName), 0, 1, 0, 1, now, now, now, nil, now,
	)
}

func (app *App) upsertRunStatusTaskJobError(taskName string, message string) {
	if app.database == nil {
		return
	}
	now := time.Now()
	taskType := runStatusTaskType(taskName)
	params := mustJSON(map[string]any{"status_task": taskName})
	summary := mustJSON(map[string]any{"status_task": taskName, "stage": "error", "name": "任务失败", "message": message, "idx": 100, "total": 100})
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_jobs",
			[]string{"id", "name", "task_type", "status", "progress", "params_json", "summary_json", "result_path", "log_path", "worker_type", "worker_pid", "external_run_id", "error_message", "parent_id", "group_run_id", "subtask_key", "subtask_name", "sequence", "total", "attempt", "max_attempts", "created_at", "queued_at", "started_at", "finished_at", "updated_at"},
			[]string{"id"},
			[]string{"name", "task_type", "status", "progress", "summary_json", "worker_pid", "error_message", "finished_at", "updated_at"},
		),
		runStatusTaskJobID(taskName), runStatusTaskDisplayName(taskName), taskType, string(task.StatusFailed), 1, params, summary, "", "", "python", nil, taskName, message, "", "", taskName, runStatusTaskDisplayName(taskName), 0, 1, 0, 1, now, now, now, now, now,
	)
}

func (app *App) upsertRunStatusTaskJobMessage(taskName string, state string, message string) {
	if app.database == nil {
		return
	}
	now := time.Now()
	taskType := runStatusTaskType(taskName)
	status := task.StatusQueued
	progress := 0.0
	if strings.EqualFold(state, "running") {
		status = task.StatusRunning
		progress = 0.05
	} else if strings.EqualFold(state, "done") || strings.EqualFold(state, "success") {
		status = task.StatusSuccess
		progress = 1
	}
	params := mustJSON(map[string]any{"status_task": taskName})
	summary := mustJSON(map[string]any{"status_task": taskName, "stage": state, "name": runStatusTaskDisplayName(taskName), "message": message, "idx": int(progress * 100), "total": 100})
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_jobs",
			[]string{"id", "name", "task_type", "status", "progress", "params_json", "summary_json", "result_path", "log_path", "worker_type", "worker_pid", "external_run_id", "error_message", "parent_id", "group_run_id", "subtask_key", "subtask_name", "sequence", "total", "attempt", "max_attempts", "created_at", "queued_at", "started_at", "finished_at", "updated_at"},
			[]string{"id"},
			[]string{"name", "task_type", "status", "progress", "summary_json", "error_message", "updated_at"},
		),
		runStatusTaskJobID(taskName), runStatusTaskDisplayName(taskName), taskType, string(status), progress, params, summary, "", "", "python", nil, taskName, "", "", "", taskName, runStatusTaskDisplayName(taskName), 0, 1, 0, 1, now, now, now, nil, now,
	)
}

func (app *App) waitGenericPythonWorker(cmd *exec.Cmd, logFile *os.File, taskName string, logPath string) {
	err := cmd.Wait()
	_ = logFile.Close()
	if err == nil {
		return
	}
	if app.database == nil {
		return
	}
	if app.positionService != nil {
		if status, statusErr := app.positionService.GetRunStatus(taskName); statusErr == nil && status.State != "running" {
			return
		}
	}
	app.markPythonStatusTaskError(taskName, "训练进程已退出: "+err.Error()+"，日志: "+logPath)
}

func (app *App) ensureRunStatusTaskType(taskName string) {
	if app.database == nil {
		return
	}
	_, _ = app.database.Conn().Exec(
		`UPDATE task_run_status SET task_type=? WHERE task=? AND COALESCE(task_type,'')=''`,
		runStatusTaskType(taskName),
		taskName,
	)
}

func runStatusTaskType(taskName string) string {
	switch taskName {
	case "data_update", "data_file_scan":
		return "data_update"
	case profitArenaStrategyID:
		return "model_training"
	case "factor_snapshot":
		return "factor_snapshot"
	default:
		return "python"
	}
}

func (app *App) pythonDBEnv() []string {
	backend := strings.TrimSpace(app.settings.DatabaseBackend)
	if backend == "" {
		backend, _ = config.PackagedDatabaseConfig()
	}
	dsn := strings.TrimSpace(app.settings.MySQLDSN)
	if dsn == "" {
		_, dsn = config.PackagedDatabaseConfig()
	}
	return []string{
		"DESKTOP_DB_BACKEND=" + backend,
		"DESKTOP_DB_DSN=" + dsn,
	}
}

func (app *App) clearRunStatus(taskName string) {
	if app.database == nil {
		return
	}
	now := time.Now().Format(time.RFC3339)
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{"task", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"state", "idx", "total", "stage", "name", "message", "updated_at", "finished_at"},
		),
		taskName, "idle", 0, 0, "", "", "", now, now, "",
	)
	app.ensureRunStatusTaskType(taskName)
}

func (app *App) ListFactorResearchRuns(limit int) ([]FactorResearchRunSummary, error) {
	if err := app.ensureDatabase(); err != nil {
		return []FactorResearchRunSummary{}, err
	}
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	rows, err := app.database.Conn().Query(`
		SELECT runs.run_id,
		       COALESCE(p.start_date, r.start_date, ''), COALESCE(p.end_date, r.end_date, ''), COALESCE(p.freq, r.freq, 'monthly'),
		       COALESCE(p.label, r.label, m.label, 'fwd20_excess_industry'),
		       COALESCE(m.status, r.status, 'success'),
		       COALESCE(p.factor_count, 0), COALESCE(p.sample_dates, 0), COALESCE(p.sample_rows, 0),
		       COALESCE(p.panel_path, ''),
		       COALESCE(m.updated_at, p.updated_at, s.updated_at, r.updated_at, ''),
		       COALESCE(m.status, ''), COALESCE(JSON_EXTRACT(m.summary_json, '$.oos_rank_ic_mean') + 0, 0)
		FROM (
			SELECT run_id FROM factor_model_runs
			UNION
			SELECT run_id FROM factor_panel_meta
			UNION
			SELECT run_id FROM factor_research_stage_results
			UNION
			SELECT run_id FROM factor_research_runs
		) runs
		LEFT JOIN factor_research_runs r ON r.run_id = runs.run_id
		LEFT JOIN factor_panel_meta p ON p.run_id = runs.run_id
		LEFT JOIN factor_model_runs m ON m.run_id = runs.run_id
		LEFT JOIN (
			SELECT run_id, MAX(updated_at) AS updated_at
			FROM factor_research_stage_results
			GROUP BY run_id
		) s ON s.run_id = runs.run_id
		WHERE COALESCE(m.run_id, p.run_id, s.run_id) IS NOT NULL
		ORDER BY COALESCE(m.updated_at, p.updated_at, s.updated_at, r.updated_at, '') DESC
		LIMIT ?`, limit)
	if err != nil {
		return []FactorResearchRunSummary{}, nil
	}
	defer rows.Close()
	out := []FactorResearchRunSummary{}
	for rows.Next() {
		var item FactorResearchRunSummary
		if err := rows.Scan(&item.RunID, &item.StartDate, &item.EndDate, &item.Freq, &item.Label, &item.Status, &item.FactorCount, &item.SampleDates, &item.SampleRows, &item.PanelPath, &item.UpdatedAt, &item.ModelStatus, &item.RankIC); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListFactorICResults(runID string, limit int) ([]FactorICResult, error) {
	if err := app.ensureDatabase(); err != nil {
		return []FactorICResult{}, err
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		latest, err := app.latestFactorRunID()
		if err != nil {
			return []FactorICResult{}, err
		}
		runID = latest
	}
	if runID == "" {
		return []FactorICResult{}, nil
	}
	if limit <= 0 || limit > 200 {
		limit = 80
	}
	rows, err := app.database.Conn().Query(`
		SELECT i.run_id, i.factor, i.family, i.variant, i.horizon,
		       COALESCE(i.ic_mean, 0), COALESCE(i.rank_ic_mean, 0), COALESCE(i.ic_win_rate, 0),
		       COALESCE(i.icir, 0), i.status,
		       COALESCE(q.long_short_return, 0), COALESCE(q.monotonic_score, 0)
		FROM factor_ic_results i
		LEFT JOIN factor_quantile_results q
		  ON q.run_id = i.run_id AND q.factor = i.factor AND q.variant = i.variant AND q.horizon = i.horizon
		WHERE i.run_id = ?
		ORDER BY i.rank_ic_mean DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []FactorICResult{}, nil
	}
	defer rows.Close()
	out := []FactorICResult{}
	for rows.Next() {
		var item FactorICResult
		if err := rows.Scan(&item.RunID, &item.Factor, &item.Family, &item.Variant, &item.Horizon, &item.ICMean, &item.RankICMean, &item.ICWinRate, &item.ICIR, &item.Status, &item.LongShortReturn, &item.MonotonicScore); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListFactorStateICResults(runID string, limit int) ([]FactorStateICResult, error) {
	if err := app.ensureDatabase(); err != nil {
		return []FactorStateICResult{}, err
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		latest, err := app.latestFactorRunID()
		if err != nil {
			return []FactorStateICResult{}, err
		}
		runID = latest
	}
	if runID == "" {
		return []FactorStateICResult{}, nil
	}
	if limit <= 0 || limit > 300 {
		limit = 120
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, factor, family, variant, horizon, market_state,
		       COALESCE(rank_ic_mean, 0), COALESCE(ic_win_rate, 0), COALESCE(icir, 0),
		       COALESCE(n_periods, 0), COALESCE(n_obs, 0), status, COALESCE(summary_json, '')
		FROM factor_state_ic_results
		WHERE run_id = ?
		ORDER BY
		  CASE market_state
		    WHEN 'crash' THEN 0
		    WHEN 'weak' THEN 1
		    WHEN 'liquidity_squeeze' THEN 2
		    WHEN 'post_crash_repair' THEN 3
		    WHEN 'normal' THEN 4
		    ELSE 9
		  END,
		  rank_ic_mean DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []FactorStateICResult{}, nil
	}
	defer rows.Close()
	out := []FactorStateICResult{}
	for rows.Next() {
		var item FactorStateICResult
		if err := rows.Scan(
			&item.RunID, &item.Factor, &item.Family, &item.Variant, &item.Horizon, &item.MarketState,
			&item.RankICMean, &item.ICWinRate, &item.ICIR, &item.NPeriods, &item.NObs, &item.Status, &item.SummaryJSON,
		); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) GetFactorModelRun(runID string) (FactorModelRun, error) {
	if err := app.ensureDatabase(); err != nil {
		return FactorModelRun{}, err
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		latest, err := app.latestFactorRunID()
		if err != nil {
			return FactorModelRun{}, err
		}
		runID = latest
	}
	if runID == "" {
		return FactorModelRun{}, nil
	}
	row := app.database.Conn().QueryRow(`
		SELECT run_id, model_type, label, feature_count, status, COALESCE(model_path, ''),
		       COALESCE(JSON_EXTRACT(summary_json, '$.oos_rank_ic_mean') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.top_bottom_spread') + 0, 0),
		       COALESCE(summary_json, ''), updated_at
		FROM factor_model_runs WHERE run_id = ?`, runID)
	var item FactorModelRun
	if err := row.Scan(&item.RunID, &item.ModelType, &item.Label, &item.FeatureCount, &item.Status, &item.ModelPath, &item.RankIC, &item.TopBottom, &item.SummaryJSON, &item.UpdatedAt); err != nil {
		return FactorModelRun{}, nil
	}
	return item, nil
}

func (app *App) ListFactorModelFeatures(runID string, limit int) ([]FactorModelFeature, error) {
	if err := app.ensureDatabase(); err != nil {
		return []FactorModelFeature{}, err
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		row := app.database.Conn().QueryRow(`SELECT run_id FROM factor_model_runs WHERE status = 'success' ORDER BY updated_at DESC LIMIT 1`)
		_ = row.Scan(&runID)
	}
	if runID == "" {
		return []FactorModelFeature{}, nil
	}
	if limit <= 0 || limit > 200 {
		limit = 80
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, feature, COALESCE(importance, 0), COALESCE(rank_no, 0), COALESCE(summary_json, '')
		FROM factor_model_features
		WHERE run_id = ?
		ORDER BY rank_no ASC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []FactorModelFeature{}, nil
	}
	defer rows.Close()
	out := []FactorModelFeature{}
	for rows.Next() {
		var item FactorModelFeature
		if err := rows.Scan(&item.RunID, &item.Feature, &item.Importance, &item.RankNo, &item.SummaryJSON); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListFactorModelPredictions(runID string, limit int) ([]FactorModelPrediction, error) {
	if err := app.ensureDatabase(); err != nil {
		return []FactorModelPrediction{}, err
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		latest, err := app.latestFactorRunID()
		if err != nil {
			return []FactorModelPrediction{}, err
		}
		runID = latest
	}
	if runID == "" {
		return []FactorModelPrediction{}, nil
	}
	if limit <= 0 || limit > 500 {
		limit = 120
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, trade_date, ts_code, COALESCE(pred_score, 0), COALESCE(realized_return, 0),
		       COALESCE(pred_rank, 0), COALESCE(test_year, 0)
		FROM factor_model_predictions
		WHERE run_id = ? AND is_top20 = 1
		ORDER BY trade_date DESC, pred_score DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []FactorModelPrediction{}, nil
	}
	defer rows.Close()
	out := []FactorModelPrediction{}
	for rows.Next() {
		var item FactorModelPrediction
		if err := rows.Scan(&item.RunID, &item.TradeDate, &item.TsCode, &item.PredScore, &item.RealizedReturn, &item.PredRank, &item.TestYear); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListFactorCorrelationResults(runID string, limit int) ([]FactorCorrelationResult, error) {
	if err := app.ensureDatabase(); err != nil {
		return []FactorCorrelationResult{}, err
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		latest, err := app.latestFactorRunID()
		if err != nil {
			return []FactorCorrelationResult{}, err
		}
		runID = latest
	}
	if runID == "" {
		return []FactorCorrelationResult{}, nil
	}
	if limit <= 0 || limit > 500 {
		limit = 120
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, feature_a, feature_b, COALESCE(correlation, 0), COALESCE(abs_correlation, 0),
		       COALESCE(family_a, ''), COALESCE(family_b, ''), COALESCE(keep_feature, ''),
		       COALESCE(drop_feature, ''), COALESCE(reason, '')
		FROM factor_correlation_results
		WHERE run_id = ?
		ORDER BY abs_correlation DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []FactorCorrelationResult{}, nil
	}
	defer rows.Close()
	out := []FactorCorrelationResult{}
	for rows.Next() {
		var item FactorCorrelationResult
		if err := rows.Scan(&item.RunID, &item.FeatureA, &item.FeatureB, &item.Correlation, &item.AbsCorrelation, &item.FamilyA, &item.FamilyB, &item.KeepFeature, &item.DropFeature, &item.Reason); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListFactorStressResults(runID string, limit int) ([]FactorStressResult, error) {
	if err := app.ensureDatabase(); err != nil {
		return []FactorStressResult{}, err
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		latest, err := app.latestFactorRunID()
		if err != nil {
			return []FactorStressResult{}, err
		}
		runID = latest
	}
	if runID == "" {
		return []FactorStressResult{}, nil
	}
	if limit <= 0 || limit > 500 {
		limit = 160
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, bucket_type, bucket_key, bucket_label, start_date, end_date,
		       COALESCE(n_days, 0), COALESCE(total_return, 0), COALESCE(annual_return, 0),
		       COALESCE(max_drawdown, 0), COALESCE(sharpe, 0), COALESCE(win_rate, 0),
		       COALESCE(avg_daily_return, 0), COALESCE(volatility, 0), COALESCE(summary_json, '')
		FROM factor_model_stress_results
		WHERE run_id = ?
		ORDER BY
		  CASE bucket_type WHEN 'full' THEN 0 WHEN 'event' THEN 1 WHEN 'year' THEN 2 WHEN 'market_state' THEN 3 ELSE 9 END,
		  bucket_key
		LIMIT ?`, runID, limit)
	if err != nil {
		return []FactorStressResult{}, nil
	}
	defer rows.Close()
	out := []FactorStressResult{}
	for rows.Next() {
		var item FactorStressResult
		if err := rows.Scan(
			&item.RunID, &item.BucketType, &item.BucketKey, &item.BucketLabel, &item.StartDate, &item.EndDate,
			&item.NDays, &item.TotalReturn, &item.AnnualReturn, &item.MaxDrawdown, &item.Sharpe, &item.WinRate,
			&item.AvgDailyReturn, &item.Volatility, &item.SummaryJSON,
		); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListFactorLatestPredictions(runID string, limit int) ([]FactorLatestPrediction, error) {
	if err := app.ensureDatabase(); err != nil {
		return []FactorLatestPrediction{}, err
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		runID = app.latestFactorRunIDValue()
	}
	if runID == "" {
		return []FactorLatestPrediction{}, nil
	}
	if limit <= 0 || limit > 500 {
		limit = 120
	}
	rows, err := app.database.Conn().Query(`
		SELECT p.run_id, p.trade_date, p.ts_code,
		       COALESCE(s.name, ''), COALESCE(s.industry, ''),
		       COALESCE(d.close, 0), COALESCE(d.pct_chg, 0),
		       COALESCE(p.pred_score, 0), COALESCE(p.pred_rank, 0),
		       COALESCE(p.is_top20, 0), COALESCE(p.model_path, '')
		FROM factor_latest_predictions p
		LEFT JOIN data_stock_basic s ON s.ts_code = p.ts_code
		LEFT JOIN data_daily_bars d ON d.ts_code = p.ts_code AND d.trade_date = p.trade_date
		WHERE p.run_id = ?
		ORDER BY p.trade_date DESC, p.pred_score DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []FactorLatestPrediction{}, nil
	}
	defer rows.Close()
	out := []FactorLatestPrediction{}
	for rows.Next() {
		var item FactorLatestPrediction
		var isTop20 int
		if err := rows.Scan(&item.RunID, &item.TradeDate, &item.TsCode, &item.Name, &item.Industry, &item.Price, &item.PctChg, &item.PredScore, &item.PredRank, &isTop20, &item.ModelPath); err != nil {
			return out, err
		}
		item.IsTop20 = isTop20 != 0
		if item.Price <= 0 {
			item.Price = app.latestClosePrice(item.TsCode)
		}
		out = append(out, item)
	}
	if err := rows.Err(); err != nil {
		return out, err
	}
	if len(out) > 0 {
		if err := app.syncFactorObservationPool(runID, out); err != nil {
			return out, nil
		}
		app.attachFactorObservationMeta(out)
	}
	return out, nil
}

func (app *App) syncFactorObservationPool(runID string, rows []FactorLatestPrediction) error {
	if app.database == nil || app.database.Conn() == nil || len(rows) == 0 {
		return nil
	}
	tradeDate := rows[0].TradeDate
	if tradeDate == "" {
		return nil
	}
	strategy := factorResearchArchiveStrategyID
	now := time.Now().Format(time.RFC3339)
	activeBefore := map[string]struct{}{}
	activeRows, err := app.database.Conn().Query(`SELECT ts_code FROM strategy_observation_pool WHERE strategy = ? AND status = 'active'`, strategy)
	if err == nil {
		defer activeRows.Close()
		for activeRows.Next() {
			var code string
			if scanErr := activeRows.Scan(&code); scanErr == nil && code != "" {
				activeBefore[code] = struct{}{}
			}
		}
	}
	current := map[string]FactorLatestPrediction{}
	rankNo := 0
	for _, item := range rows {
		if !item.IsTop20 {
			continue
		}
		rankNo++
		current[item.TsCode] = item
		eventType := "kept"
		if _, ok := activeBefore[item.TsCode]; !ok {
			eventType = "entered"
		}
		reason := factorObservationReason(eventType, rankNo, item)
		if err := app.upsertObservationPoolRow(strategy, runID, tradeDate, item, rankNo, eventType, reason, now); err != nil {
			return err
		}
		if err := app.insertObservationEvent(strategy, runID, tradeDate, item, rankNo, eventType, reason, now); err != nil {
			return err
		}
		if err := app.refreshObservationPoolStats(strategy, item.TsCode); err != nil {
			return err
		}
	}
	for code := range activeBefore {
		if _, ok := current[code]; ok {
			continue
		}
		item := FactorLatestPrediction{RunID: runID, TradeDate: tradeDate, TsCode: code}
		_ = app.database.Conn().QueryRow(`SELECT COALESCE(name, ''), COALESCE(industry, '') FROM strategy_observation_pool WHERE strategy = ? AND ts_code = ?`, strategy, code).Scan(&item.Name, &item.Industry)
		reason := "未进入本次Top20候选，最新截面刷新后移出观察池"
		if _, err := app.database.Conn().Exec(`UPDATE strategy_observation_pool SET status='dropped', exit_reason=?, last_run_id=?, updated_at=? WHERE strategy=? AND ts_code=?`, reason, runID, now, strategy, code); err != nil {
			return err
		}
		if err := app.insertObservationEvent(strategy, runID, tradeDate, item, 0, "dropped", reason, now); err != nil {
			return err
		}
	}
	return nil
}

func (app *App) refreshObservationPoolStats(strategy string, tsCode string) error {
	var seenCount int
	err := app.database.Conn().QueryRow(`
		SELECT COUNT(DISTINCT trade_date)
		FROM strategy_observation_events
		WHERE strategy = ? AND ts_code = ? AND event_type IN ('entered', 'kept')`, strategy, tsCode).Scan(&seenCount)
	if err != nil {
		return err
	}
	_, err = app.database.Conn().Exec(`UPDATE strategy_observation_pool SET seen_count = ? WHERE strategy = ? AND ts_code = ?`, seenCount, strategy, tsCode)
	return err
}

func (app *App) upsertObservationPoolRow(strategy string, runID string, tradeDate string, item FactorLatestPrediction, rankNo int, eventType string, reason string, now string) error {
	payload, _ := json.Marshal(map[string]any{
		"pred_score": item.PredScore,
		"pred_rank":  item.PredRank,
		"price":      item.Price,
		"pct_chg":    item.PctChg,
	})
	insertSQL := app.database.UpsertSQL(
		"strategy_observation_pool",
		[]string{"strategy", "ts_code", "name", "industry", "first_seen_date", "last_seen_date", "last_run_id", "seen_count", "last_rank", "best_rank", "last_score", "best_score", "last_rank_pct", "best_rank_pct", "status", "enter_reason", "keep_reason", "exit_reason", "payload_json", "created_at", "updated_at"},
		[]string{"strategy", "ts_code"},
		[]string{"name", "industry", "last_seen_date", "last_run_id", "last_rank", "last_score", "last_rank_pct", "status", "keep_reason", "exit_reason", "payload_json", "updated_at"},
	)
	enterReason := reason
	keepReason := reason
	if eventType != "entered" {
		enterReason = ""
	}
	if eventType == "entered" {
		keepReason = "首次进入观察池"
	}
	_, err := app.database.Conn().Exec(
		insertSQL,
		strategy, item.TsCode, item.Name, item.Industry, tradeDate, tradeDate, runID, 1, rankNo, rankNo, item.PredScore, item.PredScore, item.PredRank, item.PredRank, "active", enterReason, keepReason, "", string(payload), now, now,
	)
	if err != nil {
		return err
	}
	_, err = app.database.Conn().Exec(`
		UPDATE strategy_observation_pool
		SET seen_count = CASE WHEN first_seen_date = ? THEN seen_count ELSE seen_count END,
		    best_rank = CASE WHEN best_rank = 0 OR ? < best_rank THEN ? ELSE best_rank END,
		    best_score = CASE WHEN ? > best_score THEN ? ELSE best_score END,
		    best_rank_pct = CASE WHEN ? > best_rank_pct THEN ? ELSE best_rank_pct END
		WHERE strategy = ? AND ts_code = ?`,
		tradeDate, rankNo, rankNo, item.PredScore, item.PredScore, item.PredRank, item.PredRank, strategy, item.TsCode,
	)
	return err
}

func (app *App) insertObservationEvent(strategy string, runID string, tradeDate string, item FactorLatestPrediction, rankNo int, eventType string, reason string, now string) error {
	payload, _ := json.Marshal(map[string]any{
		"pred_score": item.PredScore,
		"pred_rank":  item.PredRank,
		"price":      item.Price,
		"pct_chg":    item.PctChg,
	})
	insertSQL := app.database.UpsertSQL(
		"strategy_observation_events",
		[]string{"id", "strategy", "run_id", "trade_date", "ts_code", "name", "industry", "event_type", "rank_no", "score", "rank_pct", "reason", "payload_json", "created_at"},
		[]string{"id"},
		[]string{"name", "industry", "rank_no", "score", "rank_pct", "reason", "payload_json", "created_at"},
	)
	eventID := strings.Join([]string{strategy, runID, tradeDate, item.TsCode, eventType}, "|")
	_, err := app.database.Conn().Exec(insertSQL, eventID, strategy, runID, tradeDate, item.TsCode, item.Name, item.Industry, eventType, rankNo, item.PredScore, item.PredRank, reason, string(payload), now)
	return err
}

func (app *App) attachFactorObservationMeta(rows []FactorLatestPrediction) {
	if app.database == nil || app.database.Conn() == nil {
		return
	}
	for i := range rows {
		err := app.database.Conn().QueryRow(`
			SELECT COALESCE(first_seen_date, ''), COALESCE(last_seen_date, ''), COALESCE(seen_count, 0),
			       COALESCE(status, ''), COALESCE(NULLIF(keep_reason, ''), enter_reason, exit_reason, '')
			FROM strategy_observation_pool
			WHERE strategy = ? AND ts_code = ?`, factorResearchArchiveStrategyID, rows[i].TsCode).
			Scan(&rows[i].FirstSeenDate, &rows[i].LastSeenDate, &rows[i].SeenCount, &rows[i].ObservationStatus, &rows[i].ObservationReason)
		if err != nil {
			continue
		}
		rows[i].ObservationDays = observationDays(rows[i].FirstSeenDate, firstNonEmpty(rows[i].TradeDate, rows[i].LastSeenDate))
		rows[i].ObservationResult = app.strategyObservationResult(factorResearchArchiveStrategyID, rows[i].TsCode, rows[i].Price)
	}
}

func factorObservationReason(eventType string, rankNo int, item FactorLatestPrediction) string {
	if eventType == "entered" {
		return fmt.Sprintf("首次进入因子研究Top20，排名第%d，预测分位%s", rankNo, formatPercentForReason(item.PredRank))
	}
	return fmt.Sprintf("继续保留在因子研究Top20，排名第%d，预测分位%s", rankNo, formatPercentForReason(item.PredRank))
}

func formatPercentForReason(value float64) string {
	if math.IsNaN(value) || math.IsInf(value, 0) {
		return "-"
	}
	return fmt.Sprintf("%.2f%%", value*100)
}

func (app *App) syncStrategyObservationPool(strategy string, runID string, tradeDate string, candidates []strategyObservationCandidate) error {
	if app.database == nil || app.database.Conn() == nil || strategy == "" || tradeDate == "" {
		return nil
	}
	now := time.Now().Format(time.RFC3339)
	activeBefore := map[string]struct{}{}
	activeRows, err := app.database.Conn().Query(`SELECT ts_code FROM strategy_observation_pool WHERE strategy = ? AND status = 'active'`, strategy)
	if err == nil {
		defer activeRows.Close()
		for activeRows.Next() {
			var code string
			if scanErr := activeRows.Scan(&code); scanErr == nil && code != "" {
				activeBefore[code] = struct{}{}
			}
		}
	}
	current := map[string]strategyObservationCandidate{}
	for _, item := range candidates {
		if item.TSCode == "" {
			continue
		}
		item.Strategy = strategy
		item.RunID = firstNonEmpty(item.RunID, runID)
		item.TradeDate = firstNonEmpty(item.TradeDate, tradeDate)
		current[item.TSCode] = item
		eventType := "kept"
		if _, ok := activeBefore[item.TSCode]; !ok {
			eventType = "entered"
		}
		reason := strings.TrimSpace(item.Reason)
		if reason == "" {
			reason = genericObservationReason(strategy, eventType, item)
		}
		if err := app.upsertGenericObservationPoolRow(strategy, item.RunID, item.TradeDate, item, eventType, reason, now); err != nil {
			return err
		}
		if err := app.insertGenericObservationEvent(strategy, item.RunID, item.TradeDate, item, eventType, reason, now); err != nil {
			return err
		}
		if err := app.refreshObservationPoolStats(strategy, item.TSCode); err != nil {
			return err
		}
	}
	for code := range activeBefore {
		if _, ok := current[code]; ok {
			continue
		}
		item := strategyObservationCandidate{Strategy: strategy, RunID: runID, TradeDate: tradeDate, TSCode: code}
		_ = app.database.Conn().QueryRow(`SELECT COALESCE(name, ''), COALESCE(industry, '') FROM strategy_observation_pool WHERE strategy = ? AND ts_code = ?`, strategy, code).Scan(&item.Name, &item.Industry)
		reason := "未进入本次推荐列表，最新刷新后移出观察池"
		if _, err := app.database.Conn().Exec(`UPDATE strategy_observation_pool SET status='dropped', exit_reason=?, last_run_id=?, updated_at=? WHERE strategy=? AND ts_code=?`, reason, runID, now, strategy, code); err != nil {
			return err
		}
		if err := app.insertGenericObservationEvent(strategy, runID, tradeDate, item, "dropped", reason, now); err != nil {
			return err
		}
	}
	return nil
}

func (app *App) upsertGenericObservationPoolRow(strategy string, runID string, tradeDate string, item strategyObservationCandidate, eventType string, reason string, now string) error {
	payload, _ := json.Marshal(map[string]any{
		"score":    item.Score,
		"rank_pct": item.RankPct,
		"price":    item.Price,
		"pct_chg":  item.PctChg,
	})
	insertSQL := app.database.UpsertSQL(
		"strategy_observation_pool",
		[]string{"strategy", "ts_code", "name", "industry", "first_seen_date", "last_seen_date", "last_run_id", "seen_count", "last_rank", "best_rank", "last_score", "best_score", "last_rank_pct", "best_rank_pct", "status", "enter_reason", "keep_reason", "exit_reason", "payload_json", "created_at", "updated_at"},
		[]string{"strategy", "ts_code"},
		[]string{"name", "industry", "last_seen_date", "last_run_id", "last_rank", "last_score", "last_rank_pct", "status", "keep_reason", "exit_reason", "payload_json", "updated_at"},
	)
	enterReason := reason
	keepReason := reason
	if eventType != "entered" {
		enterReason = ""
	}
	if eventType == "entered" {
		keepReason = "首次进入观察池"
	}
	_, err := app.database.Conn().Exec(
		insertSQL,
		strategy, item.TSCode, item.Name, item.Industry, tradeDate, tradeDate, runID, 1, item.RankNo, item.RankNo, item.Score, item.Score, item.RankPct, item.RankPct, "active", enterReason, keepReason, "", string(payload), now, now,
	)
	if err != nil {
		return err
	}
	_, err = app.database.Conn().Exec(`
		UPDATE strategy_observation_pool
		SET best_rank = CASE WHEN best_rank = 0 OR ? < best_rank THEN ? ELSE best_rank END,
		    best_score = CASE WHEN ? > best_score THEN ? ELSE best_score END,
		    best_rank_pct = CASE WHEN ? > best_rank_pct THEN ? ELSE best_rank_pct END
		WHERE strategy = ? AND ts_code = ?`,
		item.RankNo, item.RankNo, item.Score, item.Score, item.RankPct, item.RankPct, strategy, item.TSCode,
	)
	return err
}

func (app *App) insertGenericObservationEvent(strategy string, runID string, tradeDate string, item strategyObservationCandidate, eventType string, reason string, now string) error {
	payload, _ := json.Marshal(map[string]any{
		"score":    item.Score,
		"rank_pct": item.RankPct,
		"price":    item.Price,
		"pct_chg":  item.PctChg,
	})
	insertSQL := app.database.UpsertSQL(
		"strategy_observation_events",
		[]string{"id", "strategy", "run_id", "trade_date", "ts_code", "name", "industry", "event_type", "rank_no", "score", "rank_pct", "reason", "payload_json", "created_at"},
		[]string{"id"},
		[]string{"name", "industry", "rank_no", "score", "rank_pct", "reason", "payload_json", "created_at"},
	)
	eventID := strings.Join([]string{strategy, runID, tradeDate, item.TSCode, eventType}, "|")
	_, err := app.database.Conn().Exec(insertSQL, eventID, strategy, runID, tradeDate, item.TSCode, item.Name, item.Industry, eventType, item.RankNo, item.Score, item.RankPct, reason, string(payload), now)
	return err
}

func (app *App) strategyObservationMeta(strategy string, tsCode string, currentDate string, currentPrice float64) strategyObservationInfo {
	meta := strategyObservationInfo{}
	if app.database == nil || app.database.Conn() == nil || strategy == "" || tsCode == "" {
		return meta
	}
	err := app.database.Conn().QueryRow(`
		SELECT COALESCE(first_seen_date, ''), COALESCE(last_seen_date, ''), COALESCE(seen_count, 0),
		       COALESCE(status, ''), COALESCE(NULLIF(keep_reason, ''), enter_reason, exit_reason, '')
		FROM strategy_observation_pool
		WHERE strategy = ? AND ts_code = ?`, strategy, tsCode).
		Scan(&meta.FirstSeenDate, &meta.LastSeenDate, &meta.SeenCount, &meta.ObservationStatus, &meta.ObservationReason)
	if err != nil {
		return meta
	}
	meta.ObservationDays = observationDays(meta.FirstSeenDate, firstNonEmpty(currentDate, meta.LastSeenDate))
	meta.ObservationResult = app.strategyObservationResult(strategy, tsCode, currentPrice)
	return meta
}

func (app *App) strategyObservationResult(strategy string, tsCode string, currentPrice float64) string {
	if currentPrice <= 0 {
		return "观察中，暂无价格结果"
	}
	var payload string
	err := app.database.Conn().QueryRow(`
		SELECT payload_json
		FROM strategy_observation_events
		WHERE strategy = ? AND ts_code = ? AND event_type IN ('entered','kept')
		ORDER BY trade_date ASC, created_at ASC
		LIMIT 1`, strategy, tsCode).Scan(&payload)
	if err != nil || payload == "" {
		return "观察中，暂无入池价"
	}
	var data map[string]any
	if json.Unmarshal([]byte(payload), &data) != nil {
		return "观察中，暂无入池价"
	}
	entry := numberFromAny(data["price"])
	if entry <= 0 {
		return "观察中，暂无入池价"
	}
	ret := currentPrice/entry - 1
	return fmt.Sprintf("入池后%s，入池价¥%.2f", formatPercentForReason(ret), entry)
}

func observationDays(firstDate string, currentDate string) int {
	start, ok := parseObservationDate(firstDate)
	if !ok {
		return 0
	}
	end, ok := parseObservationDate(currentDate)
	if !ok || end.Before(start) {
		return 1
	}
	return int(end.Sub(start).Hours()/24) + 1
}

func parseObservationDate(value string) (time.Time, bool) {
	value = strings.TrimSpace(value)
	if len(value) >= 10 && strings.Contains(value[:10], "-") {
		t, err := time.Parse("2006-01-02", value[:10])
		return t, err == nil
	}
	if len(value) >= 8 {
		t, err := time.Parse("20060102", value[:8])
		return t, err == nil
	}
	return time.Time{}, false
}

func normalizeDateKey(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	digits := strings.Builder{}
	for _, r := range value {
		if r >= '0' && r <= '9' {
			digits.WriteRune(r)
		}
		if digits.Len() >= 8 {
			break
		}
	}
	if digits.Len() < 8 {
		return strings.TrimSpace(value)
	}
	return digits.String()
}

func numberFromAny(value any) float64 {
	switch v := value.(type) {
	case float64:
		return v
	case int:
		return float64(v)
	case json.Number:
		n, _ := v.Float64()
		return n
	case string:
		n, _ := strconv.ParseFloat(v, 64)
		return n
	default:
		return 0
	}
}

func intFromAny(value any) int {
	return int(numberFromAny(value))
}

func numberFromAnyDefault(value any, fallback float64) float64 {
	switch v := value.(type) {
	case nil:
		return fallback
	case float64:
		return v
	case float32:
		return float64(v)
	case int:
		return float64(v)
	case int64:
		return float64(v)
	case json.Number:
		n, err := v.Float64()
		if err != nil {
			return fallback
		}
		return n
	case string:
		text := strings.TrimSpace(v)
		if text == "" {
			return fallback
		}
		n, err := strconv.ParseFloat(text, 64)
		if err != nil {
			return fallback
		}
		return n
	}
	return fallback
}

func boolFromAnyDefault(value any, fallback bool) bool {
	switch v := value.(type) {
	case nil:
		return fallback
	case bool:
		return v
	case float64:
		return v != 0
	case float32:
		return v != 0
	case int:
		return v != 0
	case int64:
		return v != 0
	case json.Number:
		n, err := v.Float64()
		if err != nil {
			return fallback
		}
		return n != 0
	case string:
		text := strings.ToLower(strings.TrimSpace(strings.Trim(v, `"`)))
		if text == "" {
			return fallback
		}
		if text == "false" || text == "0" || text == "no" || text == "off" {
			return false
		}
		if text == "true" || text == "1" || text == "yes" || text == "on" {
			return true
		}
	}
	return fallback
}

func asString(value any) string {
	switch v := value.(type) {
	case string:
		return v
	case fmt.Stringer:
		return v.String()
	case nil:
		return ""
	default:
		return fmt.Sprint(v)
	}
}

func minInt(a int, b int) int {
	if a < b {
		return a
	}
	return b
}

func maxInt(a int, b int) int {
	if a > b {
		return a
	}
	return b
}

func genericObservationReason(strategy string, eventType string, item strategyObservationCandidate) string {
	label := strategyLabel(strategy)
	if eventType == "entered" {
		return fmt.Sprintf("首次进入%s观察池，排名第%d", label, item.RankNo)
	}
	return fmt.Sprintf("继续保留在%s观察池，排名第%d", label, item.RankNo)
}

func strategyLabel(strategy string) string {
	switch strategy {
	case factorResearchArchiveStrategyID:
		return "因子研究"
	default:
		return strategy
	}
}

func (app *App) ListFactorObservationEvents(limit int) ([]FactorObservationEvent, error) {
	if err := app.ensureDatabase(); err != nil {
		return []FactorObservationEvent{}, err
	}
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	rows, err := app.database.Conn().Query(`
		SELECT e.strategy, e.run_id, e.trade_date, e.ts_code, COALESCE(e.name, ''), COALESCE(e.industry, ''),
		       e.event_type, COALESCE(e.rank_no, 0), COALESCE(e.score, 0), COALESCE(e.rank_pct, 0),
		       COALESCE(e.reason, ''), COALESCE(p.first_seen_date, ''), COALESCE(p.last_seen_date, ''),
		       COALESCE(p.seen_count, 0), COALESCE(p.status, ''), COALESCE(e.created_at, '')
		FROM strategy_observation_events e
		LEFT JOIN strategy_observation_pool p ON p.strategy = e.strategy AND p.ts_code = e.ts_code
		WHERE e.strategy = ?
		ORDER BY e.trade_date DESC, e.created_at DESC
		LIMIT ?`, factorResearchArchiveStrategyID, limit)
	if err != nil {
		return []FactorObservationEvent{}, nil
	}
	defer rows.Close()
	out := []FactorObservationEvent{}
	for rows.Next() {
		var item FactorObservationEvent
		if err := rows.Scan(
			&item.Strategy, &item.RunID, &item.TradeDate, &item.TsCode, &item.Name, &item.Industry,
			&item.EventType, &item.RankNo, &item.Score, &item.RankPct, &item.Reason,
			&item.FirstSeenDate, &item.LastSeenDate, &item.SeenCount, &item.ObservationStatus, &item.CreatedAt,
		); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListFactorAdmissionComparisons(limit int) ([]FactorAdmissionComparison, error) {
	if err := app.ensureDatabase(); err != nil {
		return []FactorAdmissionComparison{}, err
	}
	if limit <= 0 || limit > 100 {
		limit = 30
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, strategy, admission, COALESCE(admission_score, 0), COALESCE(reason, ''),
		       COALESCE(annual_return, 0), COALESCE(total_return, 0), COALESCE(max_drawdown, 0),
		       COALESCE(sharpe, 0), COALESCE(avg_turnover, 0),
		       COALESCE(effective_start, ''), COALESCE(effective_end, ''),
		       COALESCE(JSON_EXTRACT(payload_json, '$.stress_penalty') + 0, 0),
		       COALESCE(JSON_EXTRACT(payload_json, '$.stress_bad_event_count') + 0, 0),
		       COALESCE(JSON_EXTRACT(payload_json, '$.stress_crash_state_failed') + 0, 0),
	       COALESCE(JSON_EXTRACT(payload_json, '$.stress_weak_drawdown_failed') + 0, 0),
	       generated_at
		FROM eval_strategy_admission
		WHERE strategy = ?
		ORDER BY generated_at DESC
		LIMIT ?`, factorResearchArchiveStrategyID, limit)
	if err != nil {
		return []FactorAdmissionComparison{}, nil
	}
	defer rows.Close()
	out := []FactorAdmissionComparison{}
	for rows.Next() {
		var item FactorAdmissionComparison
		var crashFailed, weakFailed int
		if err := rows.Scan(
			&item.RunID, &item.Strategy, &item.Admission, &item.AdmissionScore, &item.Reason,
			&item.AnnualReturn, &item.TotalReturn, &item.MaxDrawdown, &item.Sharpe, &item.AvgTurnover,
			&item.EffectiveStart, &item.EffectiveEnd, &item.StressPenalty, &item.StressBadEventCount,
			&crashFailed, &weakFailed, &item.GeneratedAt,
		); err != nil {
			return out, err
		}
		item.StressCrashStateFailed = crashFailed != 0
		item.StressWeakDrawdownFailed = weakFailed != 0
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) RunProfitArenaTraining() error {
	if err := app.ensureDatabase(); err != nil {
		return err
	}
	endDate := app.latestDailyBarTradeDateOrToday()
	if err := app.ensureProfitArenaFactorSnapshotReady(endDate); err != nil {
		return err
	}
	dto, err := app.CreateTask(task.CreateRequest{
		Name:     "收益最大化通用策略训练",
		TaskType: task.TypeModelTraining,
		Params: map[string]any{
			"strategy":                           profitArenaStrategyID,
			"arena_name":                         profitArenaDefaultArenaName,
			"start_date":                         "20100101",
			"end_date":                           endDate,
			"min_train_years":                    4,
			"train_window_years":                 4,
			"min_test_year":                      2014,
			"min_train_rows":                     3000,
			"feature_set":                        "stock_h20_general_final_v1",
			"model_kind":                         "hybrid",
			"target_mode":                        "net_return",
			"score_mode":                         "raw",
			"horizons":                           "20",
			"top_n":                              "1,2,3,5",
			"min_pred_return":                    "-999,0.02,0.04,0.06,0.08,0.1",
			"min_market_up_ratio":                "-999",
			"min_market_ret5":                    "-999",
			"min_market_ret20":                   "-999",
			"min_market_amount_chg5":             "-999",
			"min_market_volatility20":            "-999",
			"max_market_drawdown20":              "999",
			"max_market_volatility20":            "999",
			"min_industry_up_ratio":              "-999",
			"max_crash_prob":                     "0.08,0.10,0.12,0.15,999",
			"min_daily_top_score":                "-999",
			"min_daily_top_pred_return":          "-999,0.08,0.10",
			"max_daily_top_crash_prob":           "0.08,0.10,0.12,999",
			"scopes":                             "small",
			"selection_metric":                   "capital_annual_return",
			"min_rank_ic":                        0.08,
			"min_rank_ic_days":                   80,
			"min_capital_annual_return":          0.0,
			"max_capital_drawdown":               -0.30,
			"selection_min_trades":               120,
			"selection_min_trade_years":          8,
			"n_estimators":                       520,
			"learning_rate":                      0.03,
			"num_leaves":                         63,
			"max_depth":                          7,
			"min_child_samples":                  80,
			"subsample":                          0.86,
			"colsample_bytree":                   0.86,
			"reg_alpha":                          0.10,
			"reg_lambda":                         1.2,
			"crash_filter":                       "classifier",
			"crash_return_threshold":             -0.08,
			"crash_drawdown_threshold":           -0.12,
			"crash_n_estimators":                 160,
			"breakout_filter":                    "classifier",
			"breakout_quantile":                  0.95,
			"breakout_n_estimators":              160,
			"execution_stop_loss":                "0",
			"execution_take_profit":              "0.20,0.25,0.30",
			"position_weighting":                 "score,score_cap50,equal",
			"capital_scale_mode":                 "none,light_tail_guard",
			"capital_tranche_fractions":          "0.8,0.9,1.0",
			"factor_store_id":                    "stock_factor_base_v1",
			"factor_store_mode":                  "require",
			"factor_store_feature_set":           "stock_factor_base_v1",
			"factor_preprocess":                  "institutional",
			"require_fresh_factor_snapshot":      true,
			"capacity_capital_base":              20000.0,
			"capacity_target_participation_rate": 0.02,
			"capacity_max_participation_rate":    0.05,
			"capacity_impact_bps_coefficient":    50.0,
			"enforce_capacity_gate":              true,
			"portfolio_max_single_weight":        0.10,
			"portfolio_max_industry_weight":      0.30,
			"portfolio_max_size_bucket_weight":   0.60,
			"portfolio_max_avg_crash_prob":       0.15,
			"enforce_portfolio_risk_gate":        true,
			"progress_every_evals":               250,
			"threads":                            4,
		},
	})
	if err != nil {
		return err
	}
	_, err = app.StartTask(dto.ID)
	return err
}

func (app *App) RunProfitArenaLatestInference() (task.DTO, error) {
	if err := app.ensureDatabase(); err != nil {
		return task.DTO{}, err
	}
	run, err := app.bestProfitArenaRunByCurrentScore()
	if err != nil {
		return task.DTO{}, err
	}
	if strings.TrimSpace(run.RunID) == "" {
		return task.DTO{}, errors.New("暂无通用策略冠军版本，请先完成通用策略训练")
	}
	summary := map[string]any{}
	_ = json.Unmarshal([]byte(run.SummaryJSON), &summary)
	sourceRunID := strings.TrimSpace(asString(summary["source_run_id"]))
	if sourceRunID == "" {
		sourceRunID = run.RunID
	}
	modelPath := strings.TrimSpace(run.ModelPath)
	if !strings.HasSuffix(strings.ToLower(modelPath), ".joblib") && sourceRunID != run.RunID {
		var sourceModelPath string
		_ = app.database.Conn().QueryRow(`SELECT COALESCE(model_path, '') FROM profit_arena_runs WHERE run_id = ?`, sourceRunID).Scan(&sourceModelPath)
		if strings.TrimSpace(sourceModelPath) != "" {
			modelPath = strings.TrimSpace(sourceModelPath)
		}
	}
	if !strings.HasSuffix(strings.ToLower(modelPath), ".joblib") {
		return task.DTO{}, fmt.Errorf("当前冠军版本缺少可推理模型文件: %s", modelPath)
	}
	resolvedModelPath := modelPath
	if !filepath.IsAbs(resolvedModelPath) {
		resolvedModelPath = filepath.Join(filepath.Dir(app.settings.DataPath), resolvedModelPath)
	}
	if !pathExists(resolvedModelPath) {
		return task.DTO{}, fmt.Errorf("当前冠军版本模型文件不存在，请重新训练通用策略: %s", modelPath)
	}
	modelPath = resolvedModelPath
	best := mapParam(summary, "best")
	scope := strings.TrimSpace(asString(best["scope"]))
	if scope == "" {
		scope = strings.TrimSpace(run.BestScope)
	}
	if scope == "" {
		scope = "small"
	}
	horizon := int(numberFromAny(best["horizon"]))
	if horizon <= 0 {
		horizon = int(run.BestHorizon)
	}
	if horizon <= 0 {
		horizon = 20
	}
	featureSet := strings.TrimSpace(asString(summary["feature_set"]))
	if featureSet == "" {
		featureSet = "stock_h20_general_final_v1"
	}
	modelKind := "hybrid"
	if value := strings.TrimSpace(asString(summary["model_kind"])); value != "" {
		modelKind = value
	}
	targetMode := "net_return"
	if value := strings.TrimSpace(asString(summary["target_mode"])); value != "" {
		targetMode = value
	}
	scoreMode := "raw"
	arenaName := strings.TrimSpace(asString(summary["arena_name"]))
	if arenaName == "" {
		arenaName = profitArenaDefaultArenaName
	}
	riskFilter := mapParam(summary, "risk_filter")
	if value := strings.TrimSpace(asString(riskFilter["score_mode"])); value != "" {
		scoreMode = value
	}
	crashFilter := "none"
	if value := strings.TrimSpace(asString(riskFilter["crash_filter"])); value != "" {
		crashFilter = value
	}
	breakoutFilter := "none"
	if value := strings.TrimSpace(asString(riskFilter["breakout_filter"])); value != "" {
		breakoutFilter = value
	}
	positionWeighting := strings.TrimSpace(asString(best["position_weighting"]))
	if positionWeighting == "" {
		positionWeighting = "equal"
	}
	capitalScaleMode := strings.TrimSpace(asString(best["capital_scale_mode"]))
	if capitalScaleMode == "" {
		capitalScaleMode = "none"
	}
	capitalFraction := numberFromAnyDefault(best["capital_tranche_fraction"], 1.0)
	buyTopN := int(run.BestTopN)
	if buyTopN <= 0 {
		buyTopN = int(numberFromAny(best["top_n"]))
	}
	if buyTopN <= 0 {
		buyTopN = 3
	}
	inferenceTopN := maxInt(20, buyTopN*8)
	endDate := app.latestDailyBarTradeDateOrToday()
	if err := app.ensureProfitArenaFactorSnapshotReady(endDate); err != nil {
		return task.DTO{}, err
	}
	dto, err := app.CreateTask(task.CreateRequest{
		Name:     fmt.Sprintf("通用策略重新推理-%s", endDate),
		TaskType: task.TypeModelTraining,
		Params: map[string]any{
			"strategy":                           profitArenaStrategyID,
			"arena_name":                         arenaName,
			"profile":                            "inference",
			"source_run_id":                      sourceRunID,
			"model_path":                         modelPath,
			"start_date":                         "20100101",
			"end_date":                           endDate,
			"horizons":                           strconv.Itoa(horizon),
			"top_n":                              strconv.Itoa(inferenceTopN),
			"scopes":                             scope,
			"feature_set":                        featureSet,
			"model_kind":                         modelKind,
			"target_mode":                        targetMode,
			"score_mode":                         scoreMode,
			"crash_filter":                       crashFilter,
			"breakout_filter":                    breakoutFilter,
			"rank_score_weight":                  numberFromAnyDefault(riskFilter["rank_score_weight"], 1.0),
			"pred_score_weight":                  numberFromAnyDefault(riskFilter["pred_score_weight"], 0.25),
			"breakout_score_weight":              numberFromAnyDefault(riskFilter["breakout_score_weight"], 1.0),
			"crash_score_weight":                 numberFromAnyDefault(riskFilter["crash_score_weight"], 0.25),
			"latest_inference_source_run_id":     sourceRunID,
			"latest_inference_model_path":        modelPath,
			"latest_inference_scope":             scope,
			"latest_inference_horizon":           horizon,
			"latest_inference_buy_top_n":         buyTopN,
			"execution_stop_loss":                "0",
			"execution_take_profit":              "0.20,0.25,0.30",
			"position_weighting":                 positionWeighting,
			"capital_scale_mode":                 capitalScaleMode,
			"capital_tranche_fractions":          fmt.Sprintf("%.12g", capitalFraction),
			"factor_store_id":                    "stock_factor_base_v1",
			"factor_store_mode":                  "require",
			"factor_store_feature_set":           "stock_factor_base_v1",
			"factor_preprocess":                  "institutional",
			"require_fresh_factor_snapshot":      true,
			"capacity_capital_base":              20000.0,
			"capacity_target_participation_rate": 0.02,
			"capacity_max_participation_rate":    0.05,
			"capacity_impact_bps_coefficient":    50.0,
			"enforce_capacity_gate":              true,
			"portfolio_max_single_weight":        0.10,
			"portfolio_max_industry_weight":      0.30,
			"portfolio_max_size_bucket_weight":   0.60,
			"portfolio_max_avg_crash_prob":       0.15,
			"enforce_portfolio_risk_gate":        true,
			"threads":                            4,
		},
	})
	if err != nil {
		return task.DTO{}, err
	}
	return app.StartTask(dto.ID)
}

func (app *App) GetProfitArenaRunStatus() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	return app.positionService.GetRunStatus(profitArenaStrategyID)
}

func (app *App) GetFactorSnapshotStatus() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	return app.positionService.GetRunStatus("factor_snapshot")
}

func (app *App) runFactorSnapshotManualDisabled() error {
	return errors.New("因子快照已切换为数据更新后的自动任务；请在数据页运行全部/基础/行情更新触发")
}

func (app *App) GetProfitArenaMarketDate() (string, error) {
	if err := app.ensureDatabase(); err != nil {
		return "", err
	}
	return app.latestDailyBarTradeDateOrToday(), nil
}

func (app *App) latestDailyBarTradeDateOrToday() string {
	if app.database != nil && app.database.Conn() != nil {
		var latest string
		_ = app.database.Conn().QueryRow(`SELECT COALESCE(MAX(trade_date), '') FROM data_daily_bars`).Scan(&latest)
		if strings.TrimSpace(latest) != "" {
			return strings.TrimSpace(latest)
		}
	}
	return time.Now().Format("20060102")
}

func (app *App) GetFactorStoreGovernance(factorStoreID string) (map[string]any, error) {
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return map[string]any{}, errors.New("数据路径未设置")
	}
	id := safeFactorStoreID(factorStoreID)
	if id == "" {
		id = "stock_factor_base_v1"
	}
	path := filepath.Join(dataPath, "factor_store", id, "latest.json")
	expectedEnd := app.latestDailyBarTradeDateOrToday()
	if !pathExists(path) {
		return map[string]any{
			"factor_store_id":       id,
			"status":                "missing",
			"message":               "尚未生成因子快照",
			"expected_trade_date":   expectedEnd,
			"snapshot_fresh_status": "missing",
			"snapshot_freshness": map[string]any{
				"status":     "missing",
				"expected":   expectedEnd,
				"actual":     "",
				"stale":      true,
				"message":    "尚未生成因子快照",
				"meta_path":  path,
				"checked_at": time.Now().Format(time.RFC3339),
			},
		}, nil
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return map[string]any{}, err
	}
	out := map[string]any{}
	if err := json.Unmarshal(raw, &out); err != nil {
		return map[string]any{}, err
	}
	out["latest_meta_path"] = path
	if _, ok := out["factor_store_id"]; !ok {
		out["factor_store_id"] = id
	}
	actual := strings.TrimSpace(asString(out["trade_date_max"]))
	freshStatus := "pass"
	freshMessage := "因子快照覆盖最新交易日"
	stale := false
	if actual == "" {
		freshStatus = "fail"
		freshMessage = "因子快照缺少 trade_date_max"
		stale = true
	} else if expectedEnd != "" && actual < expectedEnd {
		freshStatus = "fail"
		freshMessage = fmt.Sprintf("因子快照落后最新交易日: %s < %s", actual, expectedEnd)
		stale = true
	}
	out["expected_trade_date"] = expectedEnd
	out["snapshot_fresh_status"] = freshStatus
	out["snapshot_freshness"] = map[string]any{
		"status":     freshStatus,
		"expected":   expectedEnd,
		"actual":     actual,
		"stale":      stale,
		"message":    freshMessage,
		"meta_path":  path,
		"checked_at": time.Now().Format(time.RFC3339),
	}
	if id == "stock_factor_base_v1" || id == "profit_arena_v1" {
		spec := app.profitArenaFactorSnapshotSpecStatus(out, expectedEnd)
		out["profit_arena_spec"] = spec
		qualityGate := mapParam(out, "quality_gate")
		qualityStatus := strings.TrimSpace(asString(qualityGate["status"]))
		qualityReady := qualityStatus == "pass" || qualityStatus == "warn"
		testcase := mapParam(out, "factor_testcase")
		testcaseStatus := strings.TrimSpace(asString(testcase["status"]))
		testcaseReady := testcaseStatus == "pass"
		ready := strings.TrimSpace(asString(spec["status"])) == "pass" && freshStatus == "pass" && qualityReady && testcaseReady
		out["production_snapshot_ready"] = ready
		if ready {
			out["production_snapshot_message"] = "通用策略生产因子快照已就绪"
		} else if strings.TrimSpace(asString(spec["status"])) == "fail" {
			out["production_snapshot_message"] = "当前 latest 指向旧/非生产因子快照，请在数据管理运行全部/基础/行情更新后等待后置因子快照完成"
		} else if freshStatus == "fail" {
			out["production_snapshot_message"] = freshMessage + "，请重新运行数据更新"
		} else if !qualityReady {
			out["production_snapshot_message"] = "因子质量门禁未通过，请重新运行数据更新并检查因子治理报告"
		} else if !testcaseReady {
			out["production_snapshot_message"] = "因子 testcase 未通过，请重新运行数据更新并检查因子复算报告"
		} else {
			out["production_snapshot_message"] = "等待通用策略生产因子快照"
		}
	}
	return out, nil
}

func (app *App) ensureProfitArenaFactorSnapshotReady(endDate string) error {
	if strings.TrimSpace(endDate) == "" {
		endDate = app.latestDailyBarTradeDateOrToday()
	}
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return errors.New("数据路径未设置")
	}
	path := filepath.Join(dataPath, "factor_store", "stock_factor_base_v1", "latest.json")
	if !pathExists(path) {
		return errors.New("通用策略需要先生成因子快照：请在数据页运行全部/基础/行情更新，等待后置因子截面任务成功")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	meta := map[string]any{}
	if err := json.Unmarshal(raw, &meta); err != nil {
		return fmt.Errorf("因子快照元数据不可读: %w", err)
	}
	spec := app.profitArenaFactorSnapshotSpecStatus(meta, endDate)
	if strings.TrimSpace(asString(spec["status"])) != "pass" {
		return fmt.Errorf("通用策略因子快照预检失败：%s。请在数据页重新运行全部/基础/行情更新并等待后置因子截面任务成功", asString(spec["message"]))
	}
	qualityGate := mapParam(meta, "quality_gate")
	qualityStatus := strings.TrimSpace(asString(qualityGate["status"]))
	if qualityStatus != "pass" && qualityStatus != "warn" {
		return fmt.Errorf("通用策略因子质量门禁未通过：status=%s。请在数据页重新运行全部/基础/行情更新并检查因子治理报告", qualityStatus)
	}
	testcase := mapParam(meta, "factor_testcase")
	testcaseStatus := strings.TrimSpace(asString(testcase["status"]))
	if testcaseStatus != "pass" {
		return fmt.Errorf("通用策略因子 testcase 未通过：status=%s。请在数据页重新运行全部/基础/行情更新并检查因子复算报告", testcaseStatus)
	}
	return nil
}

func (app *App) profitArenaFactorSnapshotSpecStatus(meta map[string]any, expectedEnd string) map[string]any {
	checks := []string{}
	fail := []string{}
	actualDate := strings.TrimSpace(asString(meta["trade_date_max"]))
	metaStart := strings.TrimSpace(asString(meta["start"]))
	metaEnd := strings.TrimSpace(asString(meta["end"]))
	featureSet := strings.TrimSpace(asString(meta["feature_set"]))
	version := strings.TrimSpace(asString(meta["version"]))
	params := mapParam(meta, "params")
	preprocess := strings.TrimSpace(asString(meta["factor_preprocess"]))
	if preprocess == "" {
		preprocess = strings.TrimSpace(asString(meta["preprocess"]))
	}
	if preprocess == "" {
		preprocess = strings.TrimSpace(asString(params["preprocess"]))
	}
	if preprocess == "" {
		preprocess = strings.TrimSpace(asString(params["factor_preprocess"]))
	}
	takeProfits := numberListFromAny(meta["execution_take_profits"])
	if len(takeProfits) == 0 {
		takeProfits = numberListFromAny(params["execution_take_profits"])
	}
	if len(takeProfits) == 0 {
		takeProfits = numberListFromAny(params["execution_take_profit"])
	}
	horizons := intListFromAny(meta["horizons"])
	normalizedExpectedEnd := normalizeDateKey(expectedEnd)
	normalizedActualDate := normalizeDateKey(actualDate)
	normalizedMetaStart := normalizeDateKey(metaStart)
	normalizedMetaEnd := normalizeDateKey(metaEnd)
	expectedStart := "20100101"
	if normalizedMetaStart == "" || normalizedMetaStart > expectedStart {
		fail = append(fail, fmt.Sprintf("start 覆盖不足 actual=%s expected<=%s", metaStart, expectedStart))
	} else {
		checks = append(checks, "start")
	}
	if normalizedActualDate == "" || (normalizedExpectedEnd != "" && normalizedActualDate < normalizedExpectedEnd) {
		fail = append(fail, fmt.Sprintf("覆盖日期不足 actual=%s expected=%s", actualDate, expectedEnd))
	} else {
		checks = append(checks, "trade_date_max")
	}
	if normalizedMetaEnd == "" || (normalizedExpectedEnd != "" && normalizedMetaEnd < normalizedExpectedEnd) {
		fail = append(fail, fmt.Sprintf("end 覆盖不足 actual=%s expected>=%s", metaEnd, expectedEnd))
	} else {
		checks = append(checks, "end")
	}
	if featureSet != "stock_factor_base_v1" {
		fail = append(fail, fmt.Sprintf("feature_set 不匹配 actual=%s expected=stock_factor_base_v1", featureSet))
	} else {
		checks = append(checks, "feature_set")
	}
	if version != "profit_arena_panel_v7" {
		fail = append(fail, fmt.Sprintf("version 不匹配 actual=%s expected=profit_arena_panel_v7", version))
	} else {
		checks = append(checks, "version")
	}
	if preprocess != "institutional" {
		fail = append(fail, fmt.Sprintf("preprocess 不匹配 actual=%s expected=institutional", preprocess))
	} else {
		checks = append(checks, "preprocess")
	}
	if !intListContains(horizons, 20) {
		fail = append(fail, fmt.Sprintf("horizons 缺少 20 actual=%v", horizons))
	} else {
		checks = append(checks, "horizons")
	}
	if !floatListContainsAll(takeProfits, []float64{0.20, 0.25, 0.30}, 0.000001) {
		fail = append(fail, fmt.Sprintf("execution_take_profits 缺少生产止盈档 actual=%v expected包含[0.2 0.25 0.3]", takeProfits))
	} else {
		checks = append(checks, "execution_take_profits")
	}
	status := "pass"
	message := "通用策略因子快照签名匹配"
	if len(fail) > 0 {
		status = "fail"
		message = strings.Join(fail, "；")
	}
	return map[string]any{
		"status":           status,
		"message":          message,
		"passed_checks":    checks,
		"failed_checks":    fail,
		"expected_start":   expectedStart,
		"expected_end":     expectedEnd,
		"start":            metaStart,
		"trade_date_max":   actualDate,
		"feature_set":      featureSet,
		"version":          version,
		"preprocess":       preprocess,
		"horizons":         horizons,
		"take_profit_list": takeProfits,
	}
}

func intListFromAny(value any) []int {
	out := []int{}
	switch v := value.(type) {
	case []any:
		for _, item := range v {
			out = append(out, int(numberFromAny(item)))
		}
	case []int:
		out = append(out, v...)
	case []float64:
		for _, item := range v {
			out = append(out, int(item))
		}
	case string:
		for _, part := range strings.Split(v, ",") {
			if strings.TrimSpace(part) == "" {
				continue
			}
			out = append(out, int(numberFromAny(strings.TrimSpace(part))))
		}
	}
	return out
}

func numberListFromAny(value any) []float64 {
	out := []float64{}
	switch v := value.(type) {
	case []any:
		for _, item := range v {
			out = append(out, numberFromAny(item))
		}
	case []float64:
		out = append(out, v...)
	case []int:
		for _, item := range v {
			out = append(out, float64(item))
		}
	case string:
		for _, part := range strings.Split(v, ",") {
			if strings.TrimSpace(part) == "" {
				continue
			}
			out = append(out, numberFromAny(strings.TrimSpace(part)))
		}
	}
	return out
}

func intListContains(values []int, target int) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

func floatListContainsAll(values []float64, expected []float64, tolerance float64) bool {
	for _, target := range expected {
		found := false
		for _, value := range values {
			if math.Abs(value-target) <= tolerance {
				found = true
				break
			}
		}
		if !found {
			return false
		}
	}
	return true
}

func floatListEqual(left []float64, right []float64, tolerance float64) bool {
	if len(left) != len(right) {
		return false
	}
	for i := range left {
		if math.Abs(left[i]-right[i]) > tolerance {
			return false
		}
	}
	return true
}

func safeFactorStoreID(value string) string {
	text := strings.TrimSpace(value)
	var b strings.Builder
	for _, ch := range text {
		if (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9') || ch == '_' || ch == '-' || ch == '.' {
			b.WriteRune(ch)
		}
	}
	return b.String()
}

func (app *App) ListProfitArenaRuns(limit int) ([]ProfitArenaRunSummary, error) {
	if err := app.ensureDatabase(); err != nil {
		return []ProfitArenaRunSummary{}, err
	}
	if !app.database.TableExists("profit_arena_runs") {
		return []ProfitArenaRunSummary{}, nil
	}
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, start_date, end_date, train_mode, model_type,
		       COALESCE(feature_count, 0), status, COALESCE(best_scope, ''),
		       COALESCE(best_horizon, 0), COALESCE(best_top_n, 0),
		       COALESCE(best_compound_return, 0), COALESCE(summary_json, ''),
		       COALESCE(model_path, ''), updated_at
		FROM profit_arena_runs
		ORDER BY updated_at DESC
		LIMIT ?`, limit)
	if err != nil {
		return []ProfitArenaRunSummary{}, err
	}
	defer rows.Close()
	out := []ProfitArenaRunSummary{}
	for rows.Next() {
		var item ProfitArenaRunSummary
		if err := rows.Scan(&item.RunID, &item.StartDate, &item.EndDate, &item.TrainMode, &item.ModelType, &item.FeatureCount, &item.Status, &item.BestScope, &item.BestHorizon, &item.BestTopN, &item.BestCompoundReturn, &item.SummaryJSON, &item.ModelPath, &item.UpdatedAt); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) bestProfitArenaRunByCurrentScore() (ProfitArenaRunSummary, error) {
	runs, err := app.ListProfitArenaRuns(100)
	if err != nil {
		return ProfitArenaRunSummary{}, err
	}
	var best ProfitArenaRunSummary
	bestScore := math.Inf(-1)
	for _, run := range runs {
		if strings.ToLower(strings.TrimSpace(run.Status)) != "success" {
			continue
		}
		if !profitArenaRunHardGateOK(run) {
			continue
		}
		score := profitArenaCurrentScore(run)
		if best.RunID == "" || score > bestScore || (score == bestScore && profitArenaTieBreak(run, best)) {
			best = run
			bestScore = score
		}
	}
	return best, nil
}

func profitArenaRunHardGateOK(run ProfitArenaRunSummary) bool {
	payload := map[string]any{}
	if strings.TrimSpace(run.SummaryJSON) == "" {
		return true
	}
	if err := json.Unmarshal([]byte(run.SummaryJSON), &payload); err != nil {
		return true
	}
	components := mapParam(payload, "best_challenger_score_components")
	if raw, ok := components["hard_gate_ok"]; ok {
		if !boolFromAnyDefault(raw, true) {
			return false
		}
	}
	diagnostics := mapParam(payload, "gate_diagnostics")
	if raw, ok := diagnostics["hard_gate_ok"]; ok {
		if !boolFromAnyDefault(raw, true) {
			return false
		}
	}
	best := mapParam(payload, "best")
	if strings.ToLower(strings.TrimSpace(asString(best["capacity_status"]))) == "fail" {
		return false
	}
	if strings.ToLower(strings.TrimSpace(asString(best["portfolio_risk_status"]))) == "fail" {
		return false
	}
	return true
}

func profitArenaCurrentScore(run ProfitArenaRunSummary) float64 {
	payload := map[string]any{}
	_ = json.Unmarshal([]byte(run.SummaryJSON), &payload)
	raw := mapParam(mapParam(payload, "best_challenger_score_components"), "raw")
	best := mapParam(payload, "best")
	annual := numberFromAny(raw["capital_annual_return"])
	if annual == 0 {
		annual = numberFromAny(best["capital_annual_return"])
	}
	drawdown := numberFromAny(raw["capital_max_drawdown"])
	if drawdown == 0 {
		drawdown = numberFromAny(best["capital_max_drawdown"])
	}
	rankIC := numberFromAny(raw["rank_ic"])
	if rankIC == 0 {
		rankIC = numberFromAny(best["rank_ic"])
	}
	sharpe := numberFromAny(raw["capital_sharpe"])
	if sharpe == 0 {
		sharpe = numberFromAny(best["capital_sharpe"])
	}
	calmar := numberFromAny(raw["calmar"])
	if calmar == 0 && drawdown < 0 {
		calmar = annual / math.Abs(drawdown)
	}
	return 0.4*profitArenaAnnualBucket(annual) + 0.3*profitArenaCalmarBucket(calmar) + 0.2*profitArenaRankICBucket(rankIC) + 0.1*profitArenaSharpeBucket(sharpe)
}

func profitArenaTieBreak(a ProfitArenaRunSummary, b ProfitArenaRunSummary) bool {
	ap := map[string]any{}
	bp := map[string]any{}
	_ = json.Unmarshal([]byte(a.SummaryJSON), &ap)
	_ = json.Unmarshal([]byte(b.SummaryJSON), &bp)
	ab := mapParam(ap, "best")
	bb := mapParam(bp, "best")
	aAnnual := numberFromAny(ab["capital_annual_return"])
	bAnnual := numberFromAny(bb["capital_annual_return"])
	if aAnnual != bAnnual {
		return aAnnual > bAnnual
	}
	aIC := numberFromAny(ab["rank_ic"])
	bIC := numberFromAny(bb["rank_ic"])
	if aIC != bIC {
		return aIC > bIC
	}
	return a.UpdatedAt > b.UpdatedAt
}

func profitArenaAnnualBucket(value float64) float64 {
	switch {
	case value < 0.05:
		return 0
	case value < 0.10:
		return 20
	case value < 0.15:
		return 40
	case value < 0.20:
		return 60
	case value < 0.30:
		return 80
	case value < 0.40:
		return 90
	case value < 0.60:
		return 95
	default:
		return 100
	}
}

func profitArenaCalmarBucket(value float64) float64 {
	switch {
	case value < 0.5:
		return 0
	case value < 1.0:
		return 30
	case value < 1.5:
		return 60
	case value < 2.0:
		return 80
	case value < 2.5:
		return 90
	case value < 3.0:
		return 95
	default:
		return 100
	}
}

func profitArenaRankICBucket(value float64) float64 {
	switch {
	case value < 0.01:
		return 0
	case value < 0.03:
		return 30
	case value < 0.05:
		return 50
	case value < 0.08:
		return 70
	case value < 0.10:
		return 85
	case value < 0.12:
		return 95
	default:
		return 100
	}
}

func profitArenaSharpeBucket(value float64) float64 {
	switch {
	case value < 0.5:
		return 0
	case value < 1.0:
		return 40
	case value < 1.2:
		return 60
	case value < 1.5:
		return 75
	case value < 2.0:
		return 90
	default:
		return 100
	}
}

func (app *App) ListProfitArenaEvaluations(runID string, limit int) ([]ProfitArenaEvaluation, error) {
	if err := app.ensureDatabase(); err != nil {
		return []ProfitArenaEvaluation{}, err
	}
	if !app.database.TableExists("profit_arena_evaluations") {
		return []ProfitArenaEvaluation{}, nil
	}
	runID = app.resolveLatestProfitArenaRunID(runID)
	if runID == "" {
		return []ProfitArenaEvaluation{}, nil
	}
	if limit <= 0 || limit > 500 {
		limit = 100
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, scope, horizon, top_n, min_pred_return,
		       min_market_up_ratio, min_market_ret5, min_market_amount_chg5, min_industry_up_ratio, segment,
		       trade_count, trade_days, avg_return, win_rate, compound_return,
		       annual_return, max_drawdown, sharpe,
		       COALESCE(capital_compound_return, 0), COALESCE(capital_annual_return, 0),
		       COALESCE(capital_max_drawdown, 0), COALESCE(capital_sharpe, 0), COALESCE(capital_final_equity, 1),
		       COALESCE(summary_json, ''), updated_at
		FROM profit_arena_evaluations
		WHERE run_id = ?
		ORDER BY compound_return DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []ProfitArenaEvaluation{}, err
	}
	defer rows.Close()
	out := []ProfitArenaEvaluation{}
	for rows.Next() {
		var item ProfitArenaEvaluation
		if err := rows.Scan(
			&item.RunID, &item.Scope, &item.Horizon, &item.TopN, &item.MinPredReturn,
			&item.MinMarketUpRatio, &item.MinMarketRet5, &item.MinMarketAmountChg5, &item.MinIndustryUpRatio,
			&item.Segment, &item.TradeCount, &item.TradeDays, &item.AvgReturn, &item.WinRate,
			&item.CompoundReturn, &item.AnnualReturn, &item.MaxDrawdown, &item.Sharpe,
			&item.CapitalCompoundReturn, &item.CapitalAnnualReturn, &item.CapitalMaxDrawdown, &item.CapitalSharpe, &item.CapitalFinalEquity,
			&item.SummaryJSON, &item.UpdatedAt,
		); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListProfitArenaPredictions(runID string, limit int) ([]ProfitArenaPrediction, error) {
	if err := app.ensureDatabase(); err != nil {
		return []ProfitArenaPrediction{}, err
	}
	if !app.database.TableExists("profit_arena_predictions") {
		return []ProfitArenaPrediction{}, nil
	}
	runID = app.resolveLatestProfitArenaRunID(runID)
	if runID == "" {
		return []ProfitArenaPrediction{}, nil
	}
	if limit <= 0 || limit > 500 {
		limit = 100
	}
	priceExpr := "COALESCE(d.close, 0)"
	if app.mysqlColumnExists("profit_arena_predictions", "price") {
		priceExpr = "COALESCE(NULLIF(p.price, 0), d.close, 0)"
	}
	rows, err := app.database.Conn().Query(`
		SELECT p.run_id, p.scope, p.horizon, p.trade_date, p.ts_code, p.name, p.industry, p.size_bucket,
		       `+priceExpr+`, COALESCE(d.amount, 0), p.pred_return, p.model_score, p.realized_return, p.future_return, p.future_max_return,
		       p.future_drawdown, COALESCE(p.crash_prob, 0), COALESCE(p.exit_date, ''), p.is_latest, COALESCE(p.summary_json, ''), p.updated_at
		FROM profit_arena_predictions p
		LEFT JOIN data_daily_bars d ON d.ts_code = p.ts_code AND d.trade_date = p.trade_date
		WHERE p.run_id = ?
		ORDER BY p.is_latest DESC, p.model_score DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []ProfitArenaPrediction{}, err
	}
	defer rows.Close()
	out := []ProfitArenaPrediction{}
	for rows.Next() {
		var item ProfitArenaPrediction
		var isLatest int
		if err := rows.Scan(&item.RunID, &item.Scope, &item.Horizon, &item.TradeDate, &item.TSCode, &item.Name, &item.Industry, &item.SizeBucket, &item.Price, &item.Amount, &item.PredReturn, &item.ModelScore, &item.RealizedReturn, &item.FutureReturn, &item.FutureMaxReturn, &item.FutureDrawdown, &item.CrashProb, &item.ExitDate, &isLatest, &item.SummaryJSON, &item.UpdatedAt); err != nil {
			return out, err
		}
		item.IsLatest = isLatest != 0
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListProfitArenaFeatures(runID string, limit int) ([]ProfitArenaFeature, error) {
	if err := app.ensureDatabase(); err != nil {
		return []ProfitArenaFeature{}, err
	}
	if !app.database.TableExists("profit_arena_features") {
		return []ProfitArenaFeature{}, nil
	}
	runID = app.resolveLatestProfitArenaRunID(runID)
	if runID == "" {
		return []ProfitArenaFeature{}, nil
	}
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, scope, horizon, feature, importance, rank_no
		FROM profit_arena_features
		WHERE run_id = ?
		ORDER BY importance DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []ProfitArenaFeature{}, err
	}
	defer rows.Close()
	out := []ProfitArenaFeature{}
	for rows.Next() {
		var item ProfitArenaFeature
		if err := rows.Scan(&item.RunID, &item.Scope, &item.Horizon, &item.Feature, &item.Importance, &item.RankNo); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) mysqlColumnExists(tableName string, columnName string) bool {
	if app.database == nil || app.database.Conn() == nil {
		return false
	}
	var count int
	err := app.database.Conn().QueryRow(`
		SELECT COUNT(*)
		FROM INFORMATION_SCHEMA.COLUMNS
		WHERE TABLE_SCHEMA = DATABASE()
		  AND TABLE_NAME = ?
		  AND COLUMN_NAME = ?`, tableName, columnName).Scan(&count)
	return err == nil && count > 0
}

func (app *App) resolveLatestProfitArenaRunID(runID string) string {
	runID = strings.TrimSpace(runID)
	if runID != "" {
		return runID
	}
	if app.database == nil || app.database.Conn() == nil {
		return ""
	}
	if app.database.TableExists("profit_arena_predictions") {
		_ = app.database.Conn().QueryRow(`
			SELECT run_id
			FROM profit_arena_predictions
			WHERE is_latest = 1
			GROUP BY run_id
			ORDER BY MAX(trade_date) DESC, MAX(updated_at) DESC
			LIMIT 1`).Scan(&runID)
		if strings.TrimSpace(runID) != "" {
			return runID
		}
	}
	if app.database.TableExists("profit_arena_runs") {
		_ = app.database.Conn().QueryRow(`SELECT run_id FROM profit_arena_runs WHERE status='success' ORDER BY updated_at DESC LIMIT 1`).Scan(&runID)
	}
	return runID
}

func parseJSONStringList(value string) []string {
	value = strings.TrimSpace(value)
	if value == "" {
		return []string{}
	}
	var items []string
	if err := json.Unmarshal([]byte(value), &items); err == nil {
		out := make([]string, 0, len(items))
		for _, item := range items {
			if strings.TrimSpace(item) != "" {
				out = append(out, strings.TrimSpace(item))
			}
		}
		return out
	}
	return []string{}
}

func roundPrice(value float64) float64 {
	return math.Round(value*100) / 100
}

func (app *App) ConfirmPositionTrades(trades []position.TradeRequest) (position.Summary, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.Summary{}, err
	}
	app.applyLatestCloseExecutionPrices(trades)
	trades = filterTriggeredTrades(trades)
	if len(trades) == 0 {
		return position.Summary{}, errors.New("没有达到条件价的调仓单，已跳过执行")
	}
	return app.positionService.ConfirmTrades(app.settings.DataPath, trades)
}

func filterTriggeredTrades(trades []position.TradeRequest) []position.TradeRequest {
	out := make([]position.TradeRequest, 0, len(trades))
	for _, trade := range trades {
		if trade.Price <= 0 || trade.Shares <= 0 {
			continue
		}
		triggerType := strings.TrimSpace(trade.TriggerType)
		triggerPrice := trade.TriggerPrice
		if triggerType == "" || triggerPrice <= 0 {
			out = append(out, trade)
			continue
		}
		switch triggerType {
		case "buy_below":
			if trade.Price <= triggerPrice {
				out = append(out, trade)
			}
		case "sell_above":
			if trade.Price >= triggerPrice {
				out = append(out, trade)
			}
		case "stop_below":
			if trade.Price <= triggerPrice {
				out = append(out, trade)
			}
		default:
			out = append(out, trade)
		}
	}
	return out
}

func (app *App) RefreshPositionRealtimeQuotes() (position.Summary, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.Summary{}, err
	}
	holdings, err := app.positionService.GetHoldings()
	if err != nil {
		return position.Summary{}, err
	}
	if len(holdings) == 0 {
		summary, err := app.positionService.GetSummary(app.settings.DataPath)
		if err != nil {
			return position.Summary{}, err
		}
		app.enrichPositionSources(&summary)
		summary.QuoteStatus = "idle"
		summary.QuoteMessage = "暂无持仓，无需刷新实时行情"
		summary.QuoteSource = "none"
		summary.QuoteUpdatedAt = time.Now().Format(time.RFC3339)
		return summary, nil
	}
	type quoteResult struct {
		code    string
		price   float64
		source  string
		errText string
	}
	codes := make([]string, 0, len(holdings))
	seenCodes := map[string]bool{}
	for _, holding := range holdings {
		code := strings.TrimSpace(holding.TSCode)
		if code == "" || seenCodes[code] {
			continue
		}
		seenCodes[code] = true
		codes = append(codes, code)
	}
	prices := map[string]float64{}
	realtimeCount := 0
	fallbackCount := 0
	failedCount := 0
	errSamples := []string{}
	results := make(chan quoteResult, len(codes))
	quoteConcurrency := 4
	if len(codes) < quoteConcurrency {
		quoteConcurrency = len(codes)
	}
	if quoteConcurrency <= 0 {
		quoteConcurrency = 1
	}
	sem := make(chan struct{}, quoteConcurrency)
	var wg sync.WaitGroup
	for _, code := range codes {
		wg.Add(1)
		go func(code string) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			price, err := app.fetchRealtimePrice(code)
			if price > 0 {
				results <- quoteResult{code: code, price: price, source: "realtime"}
				return
			}
			fallbackPrice := app.latestClosePrice(code)
			if fallbackPrice > 0 {
				out := quoteResult{code: code, price: fallbackPrice, source: "latest_close"}
				if err != nil {
					out.errText = err.Error()
				}
				results <- out
				return
			}
			out := quoteResult{code: code, source: "failed"}
			if err != nil {
				out.errText = err.Error()
			}
			results <- out
		}(code)
	}
	wg.Wait()
	close(results)
	for result := range results {
		switch result.source {
		case "realtime":
			prices[result.code] = result.price
			realtimeCount++
		case "latest_close":
			prices[result.code] = result.price
			fallbackCount++
			if result.errText != "" && len(errSamples) < 2 {
				errSamples = append(errSamples, result.code+": "+result.errText)
			}
		default:
			failedCount++
			if result.errText != "" && len(errSamples) < 2 {
				errSamples = append(errSamples, result.code+": "+result.errText)
			}
		}
	}
	if len(prices) == 0 {
		summary, err := app.positionService.GetSummary(app.settings.DataPath)
		if err != nil {
			return position.Summary{}, err
		}
		app.enrichPositionSources(&summary)
		summary.QuoteStatus = "error"
		summary.QuoteMessage = "实时行情和日线收盘价均不可用，已显示最近一次持仓估值"
		if len(errSamples) > 0 {
			summary.QuoteMessage += "；" + strings.Join(errSamples, "；")
		}
		summary.QuoteSource = "cached"
		summary.QuoteUpdatedAt = time.Now().Format(time.RFC3339)
		return summary, nil
	}
	summary, err := app.positionService.RefreshValuationWithPrices(prices, time.Now().Format("20060102"))
	if err != nil {
		summary, summaryErr := app.positionService.GetSummary(app.settings.DataPath)
		if summaryErr != nil {
			return position.Summary{}, err
		}
		app.enrichPositionSources(&summary)
		summary.QuoteStatus = "error"
		summary.QuoteSource = "cached"
		summary.QuoteUpdatedAt = time.Now().Format(time.RFC3339)
		summary.QuoteMessage = "行情价格已获取，但刷新持仓估值失败，已显示最近一次持仓估值：" + err.Error()
		return summary, nil
	}
	app.enrichPositionSources(&summary)
	summary.QuoteUpdatedAt = time.Now().Format(time.RFC3339)
	if fallbackCount > 0 || failedCount > 0 {
		summary.QuoteStatus = "fallback"
		summary.QuoteSource = "realtime+latest_close"
		summary.QuoteMessage = fmt.Sprintf("实时行情刷新 %d 只，日线收盘价兜底 %d 只，失败 %d 只", realtimeCount, fallbackCount, failedCount)
		if len(errSamples) > 0 {
			summary.QuoteMessage += "；" + strings.Join(errSamples, "；")
		}
	} else {
		summary.QuoteStatus = "success"
		summary.QuoteSource = "realtime"
		summary.QuoteMessage = fmt.Sprintf("实时行情刷新成功：%d 只", realtimeCount)
	}
	return summary, nil
}

func (app *App) ClearPositionPool() (position.Summary, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.Summary{}, err
	}
	return app.positionService.ClearPool(app.settings.DataPath, app.settings.DefaultInitialCash)
}

func (app *App) GetPositionSummary() (position.Summary, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.Summary{}, err
	}
	summary, err := app.positionService.GetSummary(app.settings.DataPath)
	if err != nil {
		return position.Summary{}, err
	}
	app.enrichPositionSources(&summary)
	return summary, nil
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
	holdings, err := app.positionService.GetHoldings()
	if err != nil {
		return nil, err
	}
	if len(holdings) == 0 {
		return holdings, nil
	}
	summary := position.Summary{Positions: holdings}
	app.enrichPositionSources(&summary)
	return summary.Positions, nil
}

func (app *App) applyLatestCloseExecutionPrices(trades []position.TradeRequest) {
	for i := range trades {
		price := app.latestClosePrice(trades[i].TSCode)
		if price > 0 {
			trades[i].Price = price
		}
	}
}

func (app *App) latestMarketPrice(tsCode string) float64 {
	if realtimePrice, err := app.fetchRealtimePrice(tsCode); err == nil && realtimePrice > 0 {
		return realtimePrice
	}
	return app.latestClosePrice(tsCode)
}

func (app *App) fetchRealtimePrice(tsCode string) (float64, error) {
	type quoteSource struct {
		name string
		fn   func(string) (float64, error)
	}
	sources := []quoteSource{
		{name: "东方财富", fn: app.fetchDCRealtimePrice},
		{name: "腾讯", fn: app.fetchTencentRealtimePrice},
		{name: "新浪", fn: app.fetchSinaRealtimePrice},
	}
	errs := make([]string, 0, len(sources))
	for _, source := range sources {
		price, err := source.fn(tsCode)
		if err == nil && price > 0 {
			return price, nil
		}
		if err != nil {
			errs = append(errs, source.name+": "+err.Error())
		} else {
			errs = append(errs, source.name+": empty price")
		}
	}
	return 0, errors.New(strings.Join(errs, "; "))
}

func (app *App) fetchDCRealtimePrice(tsCode string) (float64, error) {
	tsCode = strings.TrimSpace(tsCode)
	if tsCode == "" {
		return 0, errors.New("ts_code is empty")
	}
	secID := eastmoneySecID(tsCode)
	if secID == "" {
		return 0, fmt.Errorf("unsupported ts_code: %s", tsCode)
	}
	baseCtx := app.ctx
	if baseCtx == nil {
		baseCtx = context.Background()
	}
	ctx, cancel := context.WithTimeout(baseCtx, 2500*time.Millisecond)
	defer cancel()
	url := fmt.Sprintf("https://push2.eastmoney.com/api/qt/stock/get?secid=%s&fields=f43,f58,f60", secID)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return 0, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0")
	var lastErr error
	for attempt := 0; attempt < 1; attempt++ {
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			lastErr = err
			continue
		}
		var payload struct {
			Data map[string]any `json:"data"`
		}
		decodeErr := json.NewDecoder(resp.Body).Decode(&payload)
		_ = resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			lastErr = fmt.Errorf("dc quote http %d", resp.StatusCode)
			continue
		}
		if decodeErr != nil {
			lastErr = decodeErr
			continue
		}
		raw := anyToFloat(payload.Data["f43"])
		if raw > 0 {
			return raw / 100, nil
		}
		lastErr = errors.New("dc quote price is empty")
	}
	return 0, lastErr
}

func (app *App) fetchSinaRealtimePrice(tsCode string) (float64, error) {
	symbol := sinaQuoteSymbol(tsCode)
	if symbol == "" {
		return 0, fmt.Errorf("unsupported ts_code: %s", tsCode)
	}
	baseCtx := app.ctx
	if baseCtx == nil {
		baseCtx = context.Background()
	}
	ctx, cancel := context.WithTimeout(baseCtx, 2500*time.Millisecond)
	defer cancel()
	url := "https://hq.sinajs.cn/list=" + symbol
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return 0, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0")
	req.Header.Set("Referer", "https://finance.sina.com.cn/")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("sina quote http %d", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, err
	}
	text := string(body)
	start := strings.Index(text, "\"")
	end := strings.LastIndex(text, "\"")
	if start < 0 || end <= start+1 {
		return 0, errors.New("sina quote payload is empty")
	}
	fields := strings.Split(text[start+1:end], ",")
	if len(fields) <= 3 {
		return 0, errors.New("sina quote fields are incomplete")
	}
	price, err := strconv.ParseFloat(strings.TrimSpace(fields[3]), 64)
	if err != nil || price <= 0 {
		if err != nil {
			return 0, err
		}
		return 0, errors.New("sina quote price is empty")
	}
	return price, nil
}

func (app *App) fetchTencentRealtimePrice(tsCode string) (float64, error) {
	symbol := tencentQuoteSymbol(tsCode)
	if symbol == "" {
		return 0, fmt.Errorf("unsupported ts_code: %s", tsCode)
	}
	baseCtx := app.ctx
	if baseCtx == nil {
		baseCtx = context.Background()
	}
	ctx, cancel := context.WithTimeout(baseCtx, 2500*time.Millisecond)
	defer cancel()
	url := "https://qt.gtimg.cn/q=" + symbol
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return 0, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0")
	req.Header.Set("Referer", "https://gu.qq.com/")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("tencent quote http %d", resp.StatusCode)
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, err
	}
	text := string(body)
	start := strings.Index(text, "\"")
	end := strings.LastIndex(text, "\"")
	if start < 0 || end <= start+1 {
		return 0, errors.New("tencent quote payload is empty")
	}
	fields := strings.Split(text[start+1:end], "~")
	if len(fields) <= 3 {
		return 0, errors.New("tencent quote fields are incomplete")
	}
	price, err := strconv.ParseFloat(strings.TrimSpace(fields[3]), 64)
	if err != nil || price <= 0 {
		if err != nil {
			return 0, err
		}
		return 0, errors.New("tencent quote price is empty")
	}
	return price, nil
}

func sinaQuoteSymbol(tsCode string) string {
	parts := strings.Split(strings.TrimSpace(tsCode), ".")
	if len(parts) != 2 || parts[0] == "" {
		return ""
	}
	switch strings.ToUpper(parts[1]) {
	case "SH":
		return "sh" + parts[0]
	case "SZ":
		return "sz" + parts[0]
	case "BJ":
		return "bj" + parts[0]
	default:
		return ""
	}
}

func tencentQuoteSymbol(tsCode string) string {
	parts := strings.Split(strings.TrimSpace(tsCode), ".")
	if len(parts) != 2 || parts[0] == "" {
		return ""
	}
	switch strings.ToUpper(parts[1]) {
	case "SH":
		return "sh" + parts[0]
	case "SZ":
		return "sz" + parts[0]
	case "BJ":
		return "bj" + parts[0]
	default:
		return ""
	}
}

func eastmoneySecID(tsCode string) string {
	parts := strings.Split(strings.TrimSpace(tsCode), ".")
	if len(parts) != 2 || parts[0] == "" {
		return ""
	}
	switch strings.ToUpper(parts[1]) {
	case "SH":
		return "1." + parts[0]
	case "SZ", "BJ":
		return "0." + parts[0]
	default:
		return ""
	}
}

func anyToFloat(value any) float64 {
	switch v := value.(type) {
	case float64:
		return v
	case float32:
		return float64(v)
	case int:
		return float64(v)
	case int64:
		return float64(v)
	case json.Number:
		out, _ := v.Float64()
		return out
	case string:
		out, _ := strconv.ParseFloat(strings.TrimSpace(strings.ReplaceAll(v, ",", "")), 64)
		return out
	default:
		return 0
	}
}

func (app *App) latestClosePrice(tsCode string) float64 {
	if app.database == nil || app.database.Conn() == nil || strings.TrimSpace(tsCode) == "" {
		return 0
	}
	var price float64
	err := app.database.Conn().QueryRow(`
		SELECT COALESCE(close, 0)
		FROM data_daily_bars
		WHERE ts_code = ?
		ORDER BY trade_date DESC
		LIMIT 1`, strings.TrimSpace(tsCode)).Scan(&price)
	if err != nil || price <= 0 {
		return 0
	}
	return price
}

func (app *App) GetPositionRecommendation() (position.Recommendation, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.Recommendation{}, err
	}
	return app.buildAccountRebalanceRecommendation()
}

type accountTarget struct {
	TSCode          string
	Name            string
	Industry        string
	Price           float64
	PctChg          float64
	TargetWeight    float64
	BuyTriggerPrice float64
	SellTargetPrice float64
	StopPrice       float64
	Sources         []position.Source
}

const profitArenaAccountInitialCapital = 500000.0
const profitArenaDailyBuyBudget = 20000.0

func (app *App) buildAccountRebalanceRecommendation() (position.Recommendation, error) {
	if app.database == nil {
		return position.Recommendation{}, errors.New("database is not initialized")
	}
	summary, err := app.positionService.GetSummary(app.settings.DataPath)
	if err != nil {
		return position.Recommendation{}, err
	}
	targets := map[string]*accountTarget{}
	date, ok, arenaMeta := app.mergeProfitArenaTargets(targets, summary)
	activeVersions := app.accountRebalanceStrategyVersions()
	metadata := map[string]any{"profit_arena": arenaMeta}
	if !ok {
		return position.Recommendation{
			Date:                   date,
			GeneratedAt:            time.Now().Format(time.RFC3339),
			Rows:                   []position.RecommendationItem{},
			ActiveStrategyVersions: activeVersions,
			Metadata:               metadata,
		}, nil
	}
	rows := app.buildAccountRebalanceRows(targets, summary, date, false)
	rows, lifecycleSellCount := app.appendProfitArenaLifecycleSellRows(rows, summary, date, arenaMeta)
	metadata["profit_arena_lifecycle_sell_count"] = lifecycleSellCount
	totalWeight := targetWeightSum(targets)
	nBuy := 0
	nSell := 0
	for _, row := range rows {
		switch row.Action {
		case "新建", "加仓":
			nBuy++
		case "减仓", "清仓":
			nSell++
		}
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].Action != rows[j].Action {
			return actionRank(rows[i].Action) < actionRank(rows[j].Action)
		}
		return math.Abs(rows[i].DeltaWeight) > math.Abs(rows[j].DeltaWeight)
	})
	rec := position.Recommendation{
		Date:                   date,
		GeneratedAt:            time.Now().Format(time.RFC3339),
		TotalWeight:            totalWeight,
		NHoldings:              len(targets),
		NBuy:                   nBuy,
		NSell:                  nSell,
		Rows:                   rows,
		ActiveStrategyVersions: activeVersions,
		Metadata:               metadata,
	}
	if rec.Date != "" {
		var count int
		err := app.database.Conn().QueryRow(`SELECT COUNT(*) FROM portfolio_pool_trades WHERE trade_date = ?`, rec.Date).Scan(&count)
		if err != nil {
			return position.Recommendation{}, err
		}
		rec.Rebalanced = count > 0
		rec.RebalanceTrades = count
	}
	return rec, nil
}

func (app *App) enrichPositionSources(summary *position.Summary) {
	if summary == nil || len(summary.Positions) == 0 || app.database == nil {
		return
	}
	targets := map[string]*accountTarget{}
	_, ok, _ := app.mergeProfitArenaTargets(targets, *summary)
	for i := range summary.Positions {
		item := &summary.Positions[i]
		if ok {
			if target := targets[item.TSCode]; target != nil && len(target.Sources) > 0 {
				item.Sources = compactSources(target.Sources)
				continue
			}
			item.Sources = []position.Source{{Strategy: profitArenaStrategyID, Weight: 0}}
			continue
		}
		if target := targets[item.TSCode]; target != nil && len(target.Sources) > 0 {
			item.Sources = compactSources(target.Sources)
			continue
		}
		item.Sources = []position.Source{{Strategy: profitArenaStrategyID, Weight: 0}}
	}
}

func targetWeightSum(targets map[string]*accountTarget) float64 {
	total := 0.0
	for _, item := range targets {
		total += math.Max(item.TargetWeight, 0)
	}
	if total > 0.92 {
		return 0.92
	}
	return total
}

func actionRank(action string) int {
	switch action {
	case "新建":
		return 1
	case "加仓":
		return 2
	case "减仓":
		return 3
	case "清仓":
		return 4
	default:
		return 9
	}
}

func (app *App) latestRecommendationDate() string {
	dates := []string{}
	var date string
	if err := app.database.Conn().QueryRow(`SELECT COALESCE(MAX(trade_date),'') FROM profit_arena_predictions WHERE is_latest = 1`).Scan(&date); err == nil && date != "" {
		dates = append(dates, date)
	}
	sort.Strings(dates)
	if len(dates) > 0 {
		return dates[len(dates)-1]
	}
	return time.Now().Format("20060102")
}

func (app *App) accountRebalanceStrategyVersions() []position.RecommendationStrategyVersion {
	out := []position.RecommendationStrategyVersion{
		{Strategy: profitArenaStrategyID, Label: "通用策略冠军版本", Version: 1, Mode: "source", Weight: 1},
	}
	return out
}

func (app *App) targetFor(targets map[string]*accountTarget, tsCode, name, industry string, price, pctChg float64) *accountTarget {
	key := strings.TrimSpace(tsCode)
	if key == "" {
		return nil
	}
	item := targets[key]
	if item == nil {
		item = &accountTarget{TSCode: key}
		targets[key] = item
	}
	if item.Name == "" {
		item.Name = name
	}
	if item.Industry == "" {
		item.Industry = industry
	}
	if item.Price <= 0 && price > 0 {
		item.Price = price
	}
	if item.PctChg == 0 && pctChg != 0 {
		item.PctChg = pctChg
	}
	return item
}

func (app *App) addTargetWeight(targets map[string]*accountTarget, tsCode, name, industry string, price, pctChg, weight float64, strategy string) {
	if weight <= 0 {
		return
	}
	item := app.targetFor(targets, tsCode, name, industry, price, pctChg)
	if item == nil {
		return
	}
	item.TargetWeight += weight
	item.Sources = append(item.Sources, position.Source{Strategy: strategy, Weight: weight})
}

func (app *App) addTargetPlan(targets map[string]*accountTarget, tsCode, name, industry string, price, pctChg, weight float64, strategy string, buyTriggerPrice float64, sellTargetPrice float64, stopPrice float64) {
	app.addTargetWeight(targets, tsCode, name, industry, price, pctChg, weight, strategy)
	item := targets[strings.TrimSpace(tsCode)]
	if item == nil {
		return
	}
	if buyTriggerPrice > 0 && buyTriggerPrice > item.BuyTriggerPrice {
		item.BuyTriggerPrice = buyTriggerPrice
	}
	if sellTargetPrice > 0 && (item.SellTargetPrice <= 0 || sellTargetPrice < item.SellTargetPrice) {
		item.SellTargetPrice = sellTargetPrice
	}
	if stopPrice > 0 && stopPrice > item.StopPrice {
		item.StopPrice = stopPrice
	}
}

func (app *App) mergeProfitArenaTargets(targets map[string]*accountTarget, summary position.Summary) (string, bool, map[string]any) {
	meta := map[string]any{"status": "missing"}
	run, err := app.bestProfitArenaRunByCurrentScore()
	if err != nil || strings.TrimSpace(run.RunID) == "" {
		meta["reason"] = "no_profit_arena_champion"
		return app.latestRecommendationDate(), false, meta
	}
	meta["run_id"] = run.RunID
	summaryPayload := map[string]any{}
	_ = json.Unmarshal([]byte(run.SummaryJSON), &summaryPayload)
	best := mapParam(summaryPayload, "best")
	topN := int(numberFromAny(best["top_n"]))
	if topN <= 0 {
		topN = int(run.BestTopN)
	}
	if topN <= 0 {
		topN = 3
	}
	takeProfit := math.Max(0, numberFromAnyDefault(best["execution_take_profit"], 0))
	stopLoss := math.Max(0, numberFromAnyDefault(best["execution_stop_loss"], 0))
	capitalFraction := numberFromAnyDefault(best["capital_tranche_fraction"], 1)
	horizon := int(numberFromAnyDefault(best["horizon"], float64(run.BestHorizon)))
	if horizon <= 0 {
		horizon = run.BestHorizon
	}
	if horizon <= 0 {
		horizon = 20
	}
	meta["horizon"] = horizon
	meta["execution_take_profit"] = takeProfit
	meta["execution_stop_loss"] = stopLoss
	capitalFraction = profitArenaEffectiveCapitalFraction(capitalFraction, horizon)
	meta["capital_fraction"] = capitalFraction
	positionWeighting := strings.TrimSpace(asString(best["position_weighting"]))
	if positionWeighting == "" {
		positionWeighting = "equal"
	}
	// Predictions and parameters must come from the same run. The latest-inference
	// path (RunProfitArenaLatestInference / write_latest_predictions) writes the
	// fresh is_latest rows under the run's source_run_id (falling back to RunID),
	// so resolve predictions against that same id instead of the globally freshest run.
	predictionRunID := strings.TrimSpace(asString(summaryPayload["source_run_id"]))
	if predictionRunID == "" {
		predictionRunID = run.RunID
	}
	rows, err := app.ListProfitArenaPredictions(predictionRunID, 300)
	if err != nil || len(rows) == 0 {
		meta["status"] = "no_predictions"
		meta["reason"] = "no_latest_predictions"
		return app.latestRecommendationDate(), false, meta
	}
	latestDate := ""
	for _, row := range rows {
		if row.IsLatest && normalizeDateText(row.TradeDate) > latestDate {
			latestDate = normalizeDateText(row.TradeDate)
		}
	}
	if latestDate == "" {
		for _, row := range rows {
			if normalizeDateText(row.TradeDate) > latestDate {
				latestDate = normalizeDateText(row.TradeDate)
			}
		}
	}
	meta["date"] = latestDate
	meta["top_n"] = topN
	marketDate := normalizeDateText(app.latestDailyBarTradeDateOrToday())
	meta["market_date"] = marketDate
	if strings.TrimSpace(latestDate) == "" {
		meta["status"] = "missing_prediction_date"
		meta["reason"] = "profit_arena_latest_prediction_date_missing"
		meta["selected_count"] = 0
		meta["tradable_count"] = 0
		meta["buy_plan_complete"] = false
		return latestDate, false, meta
	}
	if profitArenaPredictionStale(latestDate, marketDate) {
		meta["status"] = "stale_predictions"
		meta["reason"] = "profit_arena_predictions_behind_market_date"
		meta["selected_count"] = 0
		meta["tradable_count"] = 0
		meta["buy_plan_complete"] = false
		return latestDate, false, meta
	}
	capacityAware := false
	capacityPass := 0
	capacityWarn := 0
	capacityFail := 0
	capacityUnknown := 0
	portfolioRiskStatus := ""
	buyPlanStatus := ""
	buyPlanReason := ""
	latestCandidateCount := 0
	observationCandidateCount := 0
	for _, row := range rows {
		if normalizeDateText(row.TradeDate) != latestDate {
			continue
		}
		if !profitArenaPredictionIsBuyCandidate(row) {
			observationCandidateCount++
			continue
		}
		latestCandidateCount++
		if status, reason := profitArenaPredictionBuyPlan(row); status != "" {
			if buyPlanStatus == "" || status == "blocked_by_portfolio_risk" || status == "blocked_by_capacity" {
				buyPlanStatus = status
				buyPlanReason = reason
			}
		}
		if buyPlanStatus == "blocked_by_portfolio_risk" {
			portfolioRiskStatus = "fail"
		}
		if status := profitArenaPredictionPortfolioRiskStatus(row); status != "" {
			if status == "fail" {
				portfolioRiskStatus = status
			} else if portfolioRiskStatus == "" {
				portfolioRiskStatus = status
			}
		}
		status := profitArenaPredictionCapacityStatus(row)
		switch status {
		case "pass":
			capacityPass++
		case "warn":
			capacityWarn++
		case "fail":
			capacityFail++
		default:
			capacityUnknown++
		}
		if status != "" {
			capacityAware = true
		}
	}
	meta["capacity_aware"] = capacityAware
	meta["latest_candidate_count"] = latestCandidateCount
	meta["buy_candidate_count"] = latestCandidateCount
	meta["observation_candidate_count"] = observationCandidateCount
	meta["capacity_pass_count"] = capacityPass
	meta["capacity_warn_count"] = capacityWarn
	meta["capacity_fail_count"] = capacityFail
	meta["capacity_unknown_count"] = capacityUnknown
	meta["portfolio_risk_status"] = portfolioRiskStatus
	meta["buy_plan_status"] = buyPlanStatus
	meta["buy_plan_reason"] = buyPlanReason
	if portfolioRiskStatus == "fail" {
		meta["status"] = "blocked_by_portfolio_risk"
		if buyPlanStatus != "" {
			meta["status"] = buyPlanStatus
		}
		meta["selected_count"] = 0
		meta["tradable_count"] = 0
		meta["buy_plan_complete"] = false
		return latestDate, false, meta
	}
	selected := make([]ProfitArenaPrediction, 0, topN)
	for _, row := range rows {
		if normalizeDateText(row.TradeDate) != latestDate {
			continue
		}
		if !profitArenaPredictionIsBuyCandidate(row) {
			continue
		}
		capacityStatus := profitArenaPredictionCapacityStatus(row)
		if capacityAware && capacityStatus != "pass" && capacityStatus != "warn" {
			continue
		}
		price := row.Price
		if price <= 0 {
			price = app.latestClosePrice(row.TSCode)
		}
		if price <= 0 {
			continue
		}
		if !capacityAware && profitArenaPredictionCapacityFailed(row) {
			continue
		}
		row.Price = price
		selected = append(selected, row)
		if len(selected) >= topN {
			break
		}
	}
	if len(selected) == 0 {
		meta["status"] = "blocked_by_capacity"
		meta["selected_count"] = 0
		meta["tradable_count"] = capacityPass + capacityWarn
		meta["buy_plan_complete"] = false
		return latestDate, false, meta
	}
	assets := summary.TotalAssets
	if assets <= 0 {
		assets = app.settings.DefaultInitialCash
	}
	if assets <= 0 {
		assets = profitArenaAccountInitialCapital
	}
	capital := profitArenaDailyBuyBudget
	if capitalFraction > 0 && capitalFraction < 1 {
		capital = math.Min(profitArenaDailyBuyBudget, profitArenaAccountInitialCapital*capitalFraction)
	}
	weights := profitArenaEffectiveTargetWeights(selected, positionWeighting)
	plannedNotional := 0.0
	held := map[string]bool{}
	for _, position := range summary.Positions {
		if position.Shares > 0 {
			held[strings.TrimSpace(position.TSCode)] = true
		}
	}
	skippedExistingHolding := 0
	meta["selected_count"] = len(selected)
	meta["tradable_count"] = capacityPass + capacityWarn
	meta["buy_plan_complete"] = len(selected) >= topN
	meta["status"] = "ready"
	if len(selected) < topN {
		meta["status"] = "partial_capacity"
	}
	if buyPlanStatus != "" && buyPlanStatus != "ready" {
		meta["status"] = buyPlanStatus
	}
	for i, row := range selected {
		if held[strings.TrimSpace(row.TSCode)] {
			skippedExistingHolding++
			continue
		}
		targetAmount := capital * weights[i]
		plannedNotional += targetAmount
		targetWeight := targetAmount / assets
		buyTrigger := roundPrice(row.Price)
		sellTarget := 0.0
		if takeProfit > 0 {
			sellTarget = roundPrice(row.Price * (1 + takeProfit))
		}
		stopPrice := 0.0
		if stopLoss > 0 {
			stopPrice = roundPrice(row.Price * (1 - stopLoss))
		}
		app.addTargetPlan(targets, row.TSCode, row.Name, row.Industry, row.Price, 0, targetWeight, profitArenaStrategyID, buyTrigger, sellTarget, stopPrice)
	}
	meta["existing_holding_skipped_count"] = skippedExistingHolding
	meta["account_initial_capital"] = profitArenaAccountInitialCapital
	meta["daily_buy_budget"] = profitArenaDailyBuyBudget
	meta["capital_base"] = profitArenaAccountInitialCapital
	meta["effective_capital"] = capital
	meta["planned_notional"] = plannedNotional
	meta["assets"] = assets
	return latestDate, true, meta
}

func profitArenaPredictionStale(predictionDate string, marketDate string) bool {
	prediction := normalizeDateText(predictionDate)
	market := normalizeDateText(marketDate)
	return prediction != "" && market != "" && prediction < market
}

func profitArenaEffectiveTargetWeights(rows []ProfitArenaPrediction, mode string) []float64 {
	out := make([]float64, len(rows))
	storedCount := 0
	for i, row := range rows {
		payload := map[string]any{}
		if strings.TrimSpace(row.SummaryJSON) == "" {
			continue
		}
		if err := json.Unmarshal([]byte(row.SummaryJSON), &payload); err != nil {
			continue
		}
		weight := numberFromAny(payload["position_weight"])
		if weight <= 0 {
			continue
		}
		scale := numberFromAnyDefault(payload["capital_scale"], 1)
		if scale < 0 {
			scale = 0
		}
		if scale > 1 {
			scale = 1
		}
		out[i] = weight * scale
		storedCount++
	}
	if storedCount == len(rows) {
		return out
	}
	return profitArenaTargetWeights(rows, mode)
}

func profitArenaPredictionCapacityFailed(row ProfitArenaPrediction) bool {
	status := profitArenaPredictionCapacityStatus(row)
	if status == "fail" {
		return true
	}
	if status != "" {
		return false
	}
	payload := map[string]any{}
	if strings.TrimSpace(row.SummaryJSON) == "" {
		return false
	}
	if err := json.Unmarshal([]byte(row.SummaryJSON), &payload); err != nil {
		return false
	}
	participation := numberFromAny(payload["capacity_participation_rate"])
	return participation > 0 && participation > 0.05
}

func profitArenaPredictionCapacityStatus(row ProfitArenaPrediction) string {
	payload := map[string]any{}
	if strings.TrimSpace(row.SummaryJSON) == "" {
		return ""
	}
	if err := json.Unmarshal([]byte(row.SummaryJSON), &payload); err != nil {
		return ""
	}
	status := strings.ToLower(strings.TrimSpace(asString(payload["capacity_status"])))
	if status == "pass" || status == "warn" || status == "fail" {
		return status
	}
	participation := numberFromAny(payload["capacity_participation_rate"])
	if participation > 0.05 {
		return "fail"
	}
	if participation > 0.02 {
		return "warn"
	}
	if participation > 0 {
		return "pass"
	}
	return ""
}

func profitArenaPredictionIsBuyCandidate(row ProfitArenaPrediction) bool {
	payload := map[string]any{}
	if strings.TrimSpace(row.SummaryJSON) == "" {
		return true
	}
	if err := json.Unmarshal([]byte(row.SummaryJSON), &payload); err != nil {
		return true
	}
	raw, ok := payload["is_buy_candidate"]
	if !ok {
		return true
	}
	return numberFromAnyDefault(raw, 0) > 0
}

func profitArenaPredictionPortfolioRiskStatus(row ProfitArenaPrediction) string {
	payload := map[string]any{}
	if strings.TrimSpace(row.SummaryJSON) == "" {
		return ""
	}
	if err := json.Unmarshal([]byte(row.SummaryJSON), &payload); err != nil {
		return ""
	}
	status := strings.ToLower(strings.TrimSpace(asString(payload["portfolio_risk_status"])))
	if status == "pass" || status == "warn" || status == "fail" {
		return status
	}
	return ""
}

func profitArenaPredictionBuyPlan(row ProfitArenaPrediction) (string, string) {
	payload := map[string]any{}
	if strings.TrimSpace(row.SummaryJSON) == "" {
		return "", ""
	}
	if err := json.Unmarshal([]byte(row.SummaryJSON), &payload); err != nil {
		return "", ""
	}
	status := strings.ToLower(strings.TrimSpace(asString(payload["buy_plan_status"])))
	reason := strings.TrimSpace(asString(payload["buy_plan_reason"]))
	return status, reason
}

func profitArenaPredictionBuyPlanStatus(row ProfitArenaPrediction) string {
	status, _ := profitArenaPredictionBuyPlan(row)
	return status
}

func profitArenaEffectiveCapitalFraction(raw float64, horizon int) float64 {
	if horizon <= 0 {
		horizon = 20
	}
	fraction := raw
	if fraction <= 0 {
		fraction = 1 / float64(horizon)
	}
	if fraction < 0 {
		return 0
	}
	if fraction > 1 {
		return 1
	}
	return fraction
}

func profitArenaTargetWeights(rows []ProfitArenaPrediction, mode string) []float64 {
	out := make([]float64, len(rows))
	if len(rows) == 0 {
		return out
	}
	if mode == "equal" {
		for i := range out {
			out[i] = 1 / float64(len(out))
		}
		return out
	}
	total := 0.0
	for _, row := range rows {
		total += math.Max(0, row.ModelScore)
	}
	if total <= 0 {
		for i := range out {
			out[i] = 1 / float64(len(out))
		}
		return out
	}
	for i, row := range rows {
		out[i] = math.Max(0, row.ModelScore) / total
		if mode == "score_cap50" && out[i] > 0.5 {
			out[i] = 0.5
		}
	}
	total = 0
	for _, weight := range out {
		total += weight
	}
	if total <= 0 {
		for i := range out {
			out[i] = 1 / float64(len(out))
		}
		return out
	}
	for i := range out {
		out[i] /= total
	}
	return out
}

func (app *App) latestFactorRunIDValue() string {
	var runID string
	if app.database != nil {
		_ = app.database.Conn().QueryRow(`
			SELECT run_id
			FROM factor_latest_predictions
			GROUP BY run_id
			ORDER BY MAX(trade_date) DESC, MAX(model_path) DESC
			LIMIT 1`).Scan(&runID)
	}
	if strings.TrimSpace(runID) != "" {
		return runID
	}
	runID, _ = app.latestFactorRunID()
	return runID
}

func (app *App) latestFactorRunID() (string, error) {
	if err := app.ensureDatabase(); err != nil {
		return "", err
	}
	var runID string
	err := app.database.Conn().QueryRow(`
		SELECT run_id
		FROM (
			SELECT run_id, COALESCE(updated_at, '') AS updated_at FROM factor_model_runs WHERE status = 'success'
			UNION ALL
			SELECT run_id, COALESCE(updated_at, '') AS updated_at FROM factor_research_runs WHERE status = 'success'
			UNION ALL
			SELECT run_id, COALESCE(updated_at, '') AS updated_at FROM factor_panel_meta
		) runs
		ORDER BY updated_at DESC
		LIMIT 1`).Scan(&runID)
	if err == sql.ErrNoRows {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(runID), nil
}

func (app *App) buildAccountRebalanceRows(targets map[string]*accountTarget, summary position.Summary, decisionDate string, clearUnmatched bool) []position.RecommendationItem {
	current := map[string]position.Position{}
	for _, item := range summary.Positions {
		current[item.TSCode] = item
		if _, ok := targets[item.TSCode]; !ok {
			if clearUnmatched {
				targets[item.TSCode] = &accountTarget{
					TSCode:       item.TSCode,
					Name:         item.Name,
					Industry:     item.Industry,
					Price:        item.Price,
					TargetWeight: 0,
					Sources:      []position.Source{{Strategy: profitArenaStrategyID, Weight: 0}},
				}
				continue
			}
			targets[item.TSCode] = &accountTarget{
				TSCode:       item.TSCode,
				Name:         item.Name,
				Industry:     item.Industry,
				Price:        item.Price,
				TargetWeight: item.Weight,
				Sources:      []position.Source{{Strategy: profitArenaStrategyID, Weight: 0}},
			}
		}
	}
	if len(targets) == 0 {
		return []position.RecommendationItem{}
	}
	scale := 1.0
	total := 0.0
	for _, item := range targets {
		total += item.TargetWeight
	}
	if total > 0.92 {
		scale = 0.92 / total
	}
	rows := make([]position.RecommendationItem, 0, len(targets))
	for _, item := range targets {
		holding := current[item.TSCode]
		fromWeight := holding.Weight
		price := app.latestClosePrice(item.TSCode)
		if price <= 0 {
			price = item.Price
		}
		if price <= 0 {
			price = holding.Price
		}
		toWeight := item.TargetWeight * scale
		if toWeight < 0.005 {
			toWeight = 0
		}
		targetAmount := summary.TotalAssets * toWeight
		targetShares := 0
		if price > 0 && targetAmount > 0 {
			targetShares = int(targetAmount/price/100) * 100
		}
		if holding.Shares > 0 && targetShares > holding.Shares && isNewlyOpenedPosition(holding.FirstEntryDate, decisionDate) {
			targetShares = holding.Shares
			toWeight = fromWeight
			targetAmount = float64(targetShares) * price
		}
		if holding.Shares > 0 && targetShares > 0 && math.Abs(float64(targetShares-holding.Shares)) < 100 {
			targetShares = holding.Shares
			toWeight = fromWeight
			targetAmount = float64(targetShares) * price
		}
		action := "持有"
		if holding.Shares <= 0 && targetShares > 0 {
			action = "新建"
		} else if holding.Shares > 0 && targetShares <= 0 {
			action = "清仓"
		} else if targetShares > holding.Shares {
			action = "加仓"
		} else if targetShares < holding.Shares {
			action = "减仓"
		}
		if action == "持有" {
			continue
		}
		rows = append(rows, position.RecommendationItem{
			Action:          action,
			TSCode:          item.TSCode,
			Name:            firstNonEmpty(item.Name, holding.Name),
			Industry:        firstNonEmpty(item.Industry, holding.Industry),
			FromWeight:      fromWeight,
			ToWeight:        toWeight,
			DeltaWeight:     toWeight - fromWeight,
			Price:           price,
			PctChg:          item.PctChg,
			TargetShares:    targetShares,
			TargetAmount:    targetAmount,
			BuyTriggerPrice: item.BuyTriggerPrice,
			SellTargetPrice: item.SellTargetPrice,
			StopPrice:       item.StopPrice,
			Sources:         compactSources(item.Sources),
		})
	}
	return rows
}

func (app *App) appendProfitArenaLifecycleSellRows(rows []position.RecommendationItem, summary position.Summary, decisionDate string, meta map[string]any) ([]position.RecommendationItem, int) {
	horizon := int(numberFromAnyDefault(meta["horizon"], 20))
	if horizon <= 0 {
		horizon = 20
	}
	takeProfit := math.Max(0, numberFromAnyDefault(meta["execution_take_profit"], 0))
	stopLoss := math.Max(0, numberFromAnyDefault(meta["execution_stop_loss"], 0))
	existing := map[string]bool{}
	for _, row := range rows {
		existing[strings.TrimSpace(row.TSCode)] = true
	}
	added := 0
	for _, holding := range summary.Positions {
		code := strings.TrimSpace(holding.TSCode)
		if code == "" || holding.Shares <= 0 || existing[code] {
			continue
		}
		price := app.latestClosePrice(code)
		if price <= 0 {
			price = holding.Price
		}
		if price <= 0 {
			price = holding.AvgCost
		}
		if price <= 0 || holding.AvgCost <= 0 {
			continue
		}
		holdDays, plannedExitDate := app.profitArenaTradingHoldDays(code, holding.FirstEntryDate, decisionDate, horizon)
		exitReason := ""
		exitPct := 0.0
		sellTargetPrice := 0.0
		stopPrice := 0.0
		if stopLoss > 0 {
			stopPrice = roundPrice(holding.AvgCost * (1 - stopLoss))
			if price <= stopPrice {
				exitReason = "stop_loss"
				exitPct = -stopLoss
			}
		}
		if exitReason == "" && takeProfit > 0 {
			sellTargetPrice = roundPrice(holding.AvgCost * (1 + takeProfit))
			if price >= sellTargetPrice {
				exitReason = "take_profit"
				exitPct = takeProfit
			}
		}
		if exitReason == "" && holdDays >= horizon {
			exitReason = "horizon_expired"
			exitPct = price/holding.AvgCost - 1
		}
		if exitReason == "" {
			continue
		}
		targetAmount := 0.0
		rows = append(rows, position.RecommendationItem{
			Action:          "清仓",
			TSCode:          code,
			Name:            holding.Name,
			Industry:        holding.Industry,
			FromWeight:      holding.Weight,
			ToWeight:        0,
			DeltaWeight:     -holding.Weight,
			Price:           price,
			TargetShares:    0,
			TargetAmount:    targetAmount,
			SellTargetPrice: sellTargetPrice,
			StopPrice:       stopPrice,
			ExitReason:      exitReason,
			ExitPct:         exitPct,
			Horizon:         horizon,
			HoldDays:        holdDays,
			PlannedExitDate: plannedExitDate,
			Sources:         []position.Source{{Strategy: profitArenaStrategyID, Weight: holding.Weight}},
		})
		existing[code] = true
		added++
	}
	return rows, added
}

func (app *App) profitArenaTradingHoldDays(tsCode string, entryDate string, decisionDate string, horizon int) (int, string) {
	entry := normalizeDateText(entryDate)
	decision := normalizeDateText(decisionDate)
	if app.database == nil || entry == "" || decision == "" || strings.TrimSpace(tsCode) == "" {
		return 0, ""
	}
	var holdDays int
	_ = app.database.Conn().QueryRow(`
		SELECT COUNT(*)
		FROM data_daily_bars
		WHERE ts_code = ? AND trade_date > ? AND trade_date <= ?`,
		strings.TrimSpace(tsCode), entry, decision,
	).Scan(&holdDays)
	plannedExitDate := ""
	if horizon > 0 {
		rows, err := app.database.Conn().Query(`
			SELECT trade_date
			FROM data_daily_bars
			WHERE ts_code = ? AND trade_date > ?
			ORDER BY trade_date
			LIMIT ?`,
			strings.TrimSpace(tsCode), entry, horizon,
		)
		if err == nil {
			defer rows.Close()
			for rows.Next() {
				_ = rows.Scan(&plannedExitDate)
			}
		}
	}
	return holdDays, plannedExitDate
}

func isNewlyOpenedPosition(openDate string, decisionDate string) bool {
	openDate = normalizeDateText(openDate)
	decisionDate = normalizeDateText(decisionDate)
	if openDate == "" || decisionDate == "" {
		return false
	}
	openTime, err := time.Parse("20060102", openDate)
	if err != nil {
		return false
	}
	decisionTime, err := time.Parse("20060102", decisionDate)
	if err != nil {
		return false
	}
	days := int(decisionTime.Sub(openTime).Hours() / 24)
	return days >= 0 && days <= 3
}

func normalizeDateText(value string) string {
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

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func compactSources(sources []position.Source) []position.Source {
	weights := map[string]float64{}
	for _, source := range sources {
		if source.Strategy == "" || source.Weight <= 0 {
			continue
		}
		if source.Strategy != profitArenaStrategyID && source.Strategy != "profit_arena" {
			continue
		}
		weights[source.Strategy] += source.Weight
	}
	out := make([]position.Source, 0, len(weights))
	for strategy, weight := range weights {
		out = append(out, position.Source{Strategy: strategy, Weight: weight})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Weight > out[j].Weight })
	return out
}

func (app *App) markProfitArenaRebalanceReady(rec position.Recommendation, stage string, prefix string) {
	now := time.Now().Format(time.RFC3339)
	app.upsertSignalRunStatus(position.RunStatus{
		Task:       "profit_arena_rebalance",
		TaskType:   "profit_arena_rebalance",
		State:      "done",
		Idx:        100,
		Total:      100,
		Stage:      stage,
		Name:       "通用策略调仓计划",
		Message:    fmt.Sprintf("%s：日期 %s，买入 %d，卖出 %d，计划 %d", prefix, firstNonEmpty(rec.Date, "今日"), rec.NBuy, rec.NSell, len(rec.Rows)),
		StartedAt:  now,
		UpdatedAt:  now,
		FinishedAt: now,
	})
}

func (app *App) markProfitArenaRebalanceRunning(stage string, message string) {
	now := time.Now().Format(time.RFC3339)
	app.upsertSignalRunStatus(position.RunStatus{
		Task:      "profit_arena_rebalance",
		TaskType:  "profit_arena_rebalance",
		State:     "running",
		Idx:       1,
		Total:     100,
		Stage:     stage,
		Name:      "通用策略调仓计划",
		Message:   message,
		StartedAt: now,
		UpdatedAt: now,
	})
}

func (app *App) markProfitArenaRebalanceError(stage string, message string) {
	now := time.Now().Format(time.RFC3339)
	app.upsertSignalRunStatus(position.RunStatus{
		Task:       "profit_arena_rebalance",
		TaskType:   "profit_arena_rebalance",
		State:      "error",
		Idx:        0,
		Total:      100,
		Stage:      stage,
		Name:       "通用策略调仓计划",
		Message:    message,
		UpdatedAt:  now,
		FinishedAt: now,
	})
}

func (app *App) GetProfitArenaRebalanceStatus() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	return app.positionService.GetRunStatus("profit_arena_rebalance")
}

func (app *App) cfgAppSettingsKeyColumn() string {
	if app.database != nil && app.database.IsMySQL() {
		return "`key`"
	}
	return "key"
}

func latestRunningTask(db *sql.DB, taskType task.Type) (position.RunStatus, error) {
	row := db.QueryRow(`SELECT id, name, progress, created_at, COALESCE(started_at,''), updated_at, COALESCE(worker_pid,0)
		FROM task_jobs
		WHERE task_type = ? AND status = 'running'
		ORDER BY created_at DESC LIMIT 1`, string(taskType))
	var id string
	var name string
	var progress float64
	var createdAt string
	var startedAt string
	var updatedAt string
	var workerPID int
	if err := row.Scan(&id, &name, &progress, &createdAt, &startedAt, &updatedAt, &workerPID); err != nil {
		return position.RunStatus{}, err
	}
	if workerPID <= 0 || !processExists(workerPID) {
		now := time.Now()
		_, _ = db.Exec(
			`UPDATE task_jobs
			 SET status = ?, worker_pid = NULL, error_message = ?, finished_at = ?, updated_at = ?
			 WHERE id = ? AND status = 'running'`,
			string(task.StatusInterrupted), "worker process is no longer running", now, now, id,
		)
		return position.RunStatus{}, sql.ErrNoRows
	}
	idx := int(progress * 100)
	return position.RunStatus{
		Task:      "profit_arena_rebalance",
		TaskType:  "profit_arena_rebalance",
		State:     "running",
		Idx:       idx,
		Total:     100,
		Stage:     "running",
		Name:      name,
		WorkerPID: workerPID,
		StartedAt: firstNonEmpty(startedAt, createdAt),
		UpdatedAt: updatedAt,
	}, nil
}

func (app *App) reconcileSignalRunStatus(status position.RunStatus) (position.RunStatus, error) {
	if status.WorkerPID > 0 && processExists(status.WorkerPID) {
		return status, nil
	}
	now := time.Now()
	_, _ = app.database.Conn().Exec(
		`UPDATE task_jobs
		 SET status = ?, worker_pid = NULL, error_message = ?, finished_at = ?, updated_at = ?
		 WHERE task_type = ? AND status = 'running'`,
		string(task.StatusInterrupted), "worker process is no longer running", now, now, "profit_arena_rebalance",
	)
	status.State = "error"
	status.Stage = "interrupted"
	status.Message = "通用策略调仓计划进程已不存在，已自动清理运行状态"
	status.WorkerPID = 0
	status.UpdatedAt = now.Format(time.RFC3339)
	status.FinishedAt = now.Format(time.RFC3339)
	app.upsertSignalRunStatus(status)
	return status, nil
}

func (app *App) upsertSignalRunStatus(status position.RunStatus) {
	if app.database == nil {
		return
	}
	now := time.Now().Format(time.RFC3339)
	if status.Task == "" {
		status.Task = "profit_arena_rebalance"
	}
	if status.TaskType == "" {
		status.TaskType = "profit_arena_rebalance"
	}
	if status.UpdatedAt == "" {
		status.UpdatedAt = now
	}
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{"task", "task_type", "state", "idx", "total", "stage", "name", "message", "worker_pid", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"task_type", "state", "idx", "total", "stage", "name", "message", "worker_pid", "started_at", "updated_at", "finished_at"},
		),
		status.Task, status.TaskType, status.State, status.Idx, status.Total, status.Stage, status.Name, status.Message,
		nullZeroInt(status.WorkerPID), status.StartedAt, status.UpdatedAt, status.FinishedAt,
	)
}

func nullZeroInt(value int) any {
	if value <= 0 {
		return nil
	}
	return value
}

func isSignalCancelError(err error) bool {
	if err == nil {
		return false
	}
	message := strings.ToLower(err.Error())
	return strings.Contains(message, "signal: terminated") ||
		strings.Contains(message, "killed") ||
		strings.Contains(message, "interrupt") ||
		strings.Contains(message, "cancel")
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

func boolFlag(flag string, enabled bool) string {
	if enabled {
		return flag
	}
	return ""
}

func compactArgs(args []string) []string {
	out := make([]string, 0, len(args))
	for _, arg := range args {
		if strings.TrimSpace(arg) != "" {
			out = append(out, arg)
		}
	}
	return out
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

func cloneAnyMap(src map[string]any) map[string]any {
	if src == nil {
		return nil
	}
	out := make(map[string]any, len(src))
	for key, value := range src {
		out[key] = cloneAnyValue(value)
	}
	return out
}

func cloneAnyValue(value any) any {
	switch typed := value.(type) {
	case map[string]any:
		return cloneAnyMap(typed)
	case []any:
		out := make([]any, len(typed))
		for i, item := range typed {
			out[i] = cloneAnyValue(item)
		}
		return out
	default:
		return typed
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

func readFactorResearchStageSummaryFromDB(db *sql.DB, runID string, stage string) string {
	if db == nil || strings.TrimSpace(runID) == "" || strings.TrimSpace(stage) == "" {
		return ""
	}
	row := db.QueryRow(`SELECT summary_json FROM factor_research_stage_results WHERE run_id = ? AND stage = ?`, runID, stage)
	var summary string
	if err := row.Scan(&summary); err != nil {
		return ""
	}
	return summary
}

func readSummaryJSON(db *sql.DB, query string, args ...any) string {
	if db == nil {
		return ""
	}
	row := db.QueryRow(query, args...)
	var summary string
	if err := row.Scan(&summary); err != nil {
		return ""
	}
	return summary
}

func readFactorResearchSummaryFromDB(db *sql.DB, runID string) string {
	if db == nil || strings.TrimSpace(runID) == "" {
		return ""
	}
	rows, err := db.Query(`SELECT stage, status, summary_json, error, updated_at FROM factor_research_stage_results WHERE run_id = ? ORDER BY sequence ASC, stage ASC`, runID)
	if err != nil {
		return ""
	}
	defer rows.Close()
	items := []any{}
	completed := 0
	failed := 0
	running := 0
	for rows.Next() {
		var stage, status, summaryJSON, errorText, updatedAt string
		if err := rows.Scan(&stage, &status, &summaryJSON, &errorText, &updatedAt); err != nil {
			continue
		}
		item := map[string]any{"stage": stage, "status": status, "error": errorText, "updated_at": updatedAt}
		if summaryJSON != "" {
			var summary map[string]any
			if json.Unmarshal([]byte(summaryJSON), &summary) == nil {
				for key, value := range summary {
					item[key] = value
				}
			}
		}
		switch status {
		case "success":
			completed++
		case "failed":
			failed++
		case "running":
			running++
		}
		items = append(items, item)
	}
	payload := map[string]any{
		"run_id":          runID,
		"rows":            items,
		"planned_count":   len(items),
		"completed_count": completed,
		"failed_count":    failed,
		"running_count":   running,
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return ""
	}
	return string(data)
}

func (app *App) RunDataUpdate(req datafetch.UpdateRequest) error {
	if err := app.ensureDatafetchService(); err != nil {
		return err
	}
	app.dataUpdateMu.Lock()
	defer app.dataUpdateMu.Unlock()
	req = normalizeDataUpdateRequest(req)
	if status, err := app.datafetchService.GetStatus(); err == nil {
		status, _ = app.reconcileDataUpdateStatus(status)
		if status.State == "running" {
			return fmt.Errorf("原子数据更新正在运行中：%s，请等待完成后再启动数据更新（%w）", dataUpdateRunningLabel(status), datafetch.ErrAlreadyRunning)
		}
	}
	if app.factorSnapshotAlreadyRunning() {
		return fmt.Errorf("通用策略因子截面正在生成中：%s，请等待完成后再启动数据更新", app.factorSnapshotRunningLabel())
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
		"--exclude-datasets", strings.Join(req.ExcludeDatasets, ","),
		"--token", token,
		"--data-path", dataPath,
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath, "TUSHARE_TOKEN=" + token}, app.pythonDBEnv()...)...)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		app.markPythonStatusTaskError("data_update", "数据更新进程启动失败: "+err.Error()+"，日志: "+logPath)
		return err
	}
	app.markDataUpdateWorkerStarted(cmd.Process.Pid)
	go app.waitDataUpdate(cmd, logFile, logPath, req)
	return nil
}

func normalizeDataUpdateRequest(req datafetch.UpdateRequest) datafetch.UpdateRequest {
	req.Phase = strings.TrimSpace(req.Phase)
	req.StartDate = strings.TrimSpace(req.StartDate)
	req.Dataset = strings.TrimSpace(req.Dataset)
	if req.Phase == "" {
		req.Phase = "all"
	}
	if req.Dataset != "" {
		return req
	}
	phase := strings.ToLower(req.Phase)
	if phase != "all" && phase != "event" {
		return req
	}
	hasTop10 := false
	for _, name := range req.ExcludeDatasets {
		if strings.TrimSpace(name) == "top10_holders" {
			hasTop10 = true
			break
		}
	}
	if !hasTop10 {
		req.ExcludeDatasets = append(req.ExcludeDatasets, "top10_holders")
	}
	return req
}

func dataUpdateRunningLabel(status datafetch.RunStatus) string {
	parts := []string{}
	if strings.TrimSpace(status.Stage) != "" {
		parts = append(parts, "阶段="+strings.TrimSpace(status.Stage))
	}
	if strings.TrimSpace(status.Name) != "" {
		parts = append(parts, "名称="+strings.TrimSpace(status.Name))
	}
	if status.Total > 0 {
		parts = append(parts, fmt.Sprintf("进度=%d/%d", status.Idx, status.Total))
	}
	if strings.TrimSpace(status.UpdatedAt) != "" {
		parts = append(parts, "更新="+strings.TrimSpace(status.UpdatedAt))
	}
	if len(parts) == 0 {
		return "running"
	}
	return strings.Join(parts, "，")
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

func (app *App) waitDataUpdate(cmd *exec.Cmd, logFile *os.File, logPath string, req datafetch.UpdateRequest) {
	err := cmd.Wait()
	_ = logFile.Close()
	if app.database == nil {
		return
	}
	status, statusErr := app.datafetchService.GetStatus()
	if statusErr != nil {
		return
	}
	if status.State != "running" {
		if err == nil && status.State == "success" && app.shouldRunFactorSnapshotAfterDataUpdate(req) {
			go func() { _ = app.runFactorSnapshotAfterDataUpdate() }()
		}
		return
	}
	if err != nil {
		app.markDataUpdateError("更新进程已退出: " + err.Error() + "，日志: " + logPath)
		return
	}
	app.markDataUpdateError("更新进程已退出但未写入完成状态，日志: " + logPath)
}

func (app *App) shouldRunFactorSnapshotAfterDataUpdate(req datafetch.UpdateRequest) bool {
	if strings.TrimSpace(req.Dataset) != "" {
		return false
	}
	switch strings.ToLower(strings.TrimSpace(req.Phase)) {
	case "", "all", "basic", "price":
		return true
	default:
		return false
	}
}

func (app *App) runFactorSnapshotAfterDataUpdate() error {
	app.factorSnapshotMu.Lock()
	defer app.factorSnapshotMu.Unlock()
	if app.factorSnapshotAlreadyRunning() {
		app.markPythonStatusTaskMessage("factor_snapshot", "running", "后置因子快照已在运行，本次数据更新不重复启动；等待现有任务完成")
		return nil
	}
	app.markPythonStatusTaskStage(
		"factor_snapshot",
		"factor_snapshot",
		"running",
		1,
		100,
		"prepare",
		"等待后置因子截面启动",
		"原子数据已完成，正在准备通用策略因子截面任务",
	)
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		msg := "数据路径未设置，无法生成因子快照"
		app.markPythonStatusTaskError("factor_snapshot", msg)
		return errors.New(msg)
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	logDir := filepath.Join(dataPath, "logs", "factor_snapshot")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		msg := "因子快照日志目录创建失败: " + err.Error()
		app.markPythonStatusTaskError("factor_snapshot", msg)
		return errors.New(msg)
	}
	logPath := filepath.Join(logDir, time.Now().Format("20060102_150405")+".log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		msg := "因子快照日志创建失败: " + err.Error()
		app.markPythonStatusTaskError("factor_snapshot", msg)
		return errors.New(msg)
	}
	args := []string{
		"scripts/factor_snapshot_worker.py",
		"--data-path", dataPath,
		"--factor-store-id", "stock_factor_base_v1",
		"--start", "20100101",
		"--end", app.latestDailyBarTradeDateOrToday(),
		"--horizons", "20",
		"--feature-set", "stock_factor_base_v1",
		"--preprocess", "institutional",
		"--enforce-quality-gate",
		"--execution-stop-loss", "0",
		"--execution-take-profit", "0.20,0.25,0.30",
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv()...)...)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		msg := "因子快照进程启动失败: " + err.Error() + "，日志: " + logPath
		app.markPythonStatusTaskError("factor_snapshot", msg)
		return errors.New(msg)
	}
	app.markGenericPythonWorkerStarted("factor_snapshot", "factor_snapshot", cmd.Process.Pid, logPath)
	go app.syncRunStatusTaskJobProcess("factor_snapshot", cmd, logFile, logPath)
	return nil
}

func (app *App) factorSnapshotAlreadyRunning() bool {
	if app.database == nil {
		return false
	}
	var state, updatedAt string
	var workerPID int
	err := app.database.Conn().QueryRow(
		`SELECT state, COALESCE(worker_pid,0), updated_at FROM task_run_status WHERE task='factor_snapshot'`,
	).Scan(&state, &workerPID, &updatedAt)
	if err != nil || !strings.EqualFold(strings.TrimSpace(state), "running") {
		return false
	}
	if workerPID > 0 && processExists(workerPID) {
		return true
	}
	if latestHeartbeat := app.latestRunStatusTaskJobHeartbeat("factor_snapshot"); latestHeartbeat != "" {
		if latestAt, latestOK := parseRunStatusTime(latestHeartbeat); latestOK {
			if statusAt, statusOK := parseRunStatusTime(updatedAt); !statusOK || latestAt.After(statusAt) {
				updatedAt = latestHeartbeat
			}
		}
	}
	if updated, ok := parseRunStatusTime(updatedAt); ok && time.Since(updated) <= 10*time.Minute {
		return true
	}
	app.markPythonStatusTaskError("factor_snapshot", "因子快照进程超过 10 分钟无心跳且进程不存在，已标记异常并允许重新触发")
	return false
}

func (app *App) factorSnapshotRunningLabel() string {
	row, err := app.readRunStatusRow("factor_snapshot")
	if err != nil {
		return "等待任务状态上报"
	}
	parts := []string{}
	if strings.TrimSpace(row.Stage) != "" {
		parts = append(parts, "阶段="+strings.TrimSpace(row.Stage))
	}
	if strings.TrimSpace(row.Name) != "" {
		parts = append(parts, "名称="+strings.TrimSpace(row.Name))
	}
	if row.Total > 0 {
		parts = append(parts, fmt.Sprintf("进度=%d/%d", row.Idx, row.Total))
	}
	if strings.TrimSpace(row.UpdatedAt) != "" {
		parts = append(parts, "更新="+strings.TrimSpace(row.UpdatedAt))
	}
	if len(parts) == 0 {
		return "running"
	}
	return strings.Join(parts, "，")
}

func (app *App) reconcileStaleRunStatusProcesses() {
	if app.database == nil {
		return
	}
	rows, err := app.database.Conn().Query(
		`SELECT task, COALESCE(worker_pid,0), updated_at FROM task_run_status WHERE state='running'`,
	)
	if err != nil {
		return
	}
	defer rows.Close()
	type runningStatus struct {
		task      string
		workerPID int
		updatedAt string
	}
	items := []runningStatus{}
	for rows.Next() {
		var item runningStatus
		if err := rows.Scan(&item.task, &item.workerPID, &item.updatedAt); err == nil {
			items = append(items, item)
		}
	}
	for _, item := range items {
		if item.workerPID > 0 && processExists(item.workerPID) {
			continue
		}
		heartbeat := item.updatedAt
		if latestHeartbeat := app.latestRunStatusTaskJobHeartbeat(item.task); latestHeartbeat != "" {
			if latestAt, latestOK := parseRunStatusTime(latestHeartbeat); latestOK {
				if statusAt, statusOK := parseRunStatusTime(heartbeat); !statusOK || latestAt.After(statusAt) {
					heartbeat = latestHeartbeat
				}
			}
		}
		if updated, ok := parseRunStatusTime(heartbeat); ok && time.Since(updated) <= 10*time.Minute {
			continue
		}
		message := fmt.Sprintf("%s进程超过 10 分钟无心跳且进程不存在，已自动标记为异常", runStatusTaskDisplayName(item.task))
		if item.task == "data_update" {
			app.markDataUpdateError(message)
			continue
		}
		app.markPythonStatusTaskError(item.task, message)
	}
}

func (app *App) reconcileStaleRunStatusTaskJobs() {
	if app.database == nil {
		return
	}
	rows, err := app.database.Conn().Query(
		`SELECT id, COALESCE(worker_pid,0), COALESCE(updated_at,'')
		 FROM task_jobs
		 WHERE id LIKE 'run_status:%'
		   AND status IN ('created','queued','running')`,
	)
	if err != nil {
		return
	}
	defer rows.Close()
	type statusJob struct {
		id        string
		workerPID int
		updatedAt string
	}
	items := []statusJob{}
	for rows.Next() {
		var item statusJob
		if err := rows.Scan(&item.id, &item.workerPID, &item.updatedAt); err == nil {
			items = append(items, item)
		}
	}
	for _, item := range items {
		taskName := strings.TrimSpace(strings.TrimPrefix(item.id, "run_status:"))
		if taskName == "" || taskName == item.id {
			continue
		}
		var state, statusUpdatedAt string
		var statusPID int
		err := app.database.Conn().QueryRow(
			`SELECT state, COALESCE(worker_pid,0), COALESCE(updated_at,'')
			 FROM task_run_status WHERE task=?`,
			taskName,
		).Scan(&state, &statusPID, &statusUpdatedAt)
		state = strings.ToLower(strings.TrimSpace(state))
		if err != nil {
			app.upsertRunStatusTaskJobError(taskName, runStatusTaskDisplayName(taskName)+"状态记录缺失，已清理卡住的运行记录")
			continue
		}
		if state == "running" {
			pid := statusPID
			if pid <= 0 {
				pid = item.workerPID
			}
			if pid > 0 && processExists(pid) {
				continue
			}
			heartbeat := item.updatedAt
			if latestAt, latestOK := parseRunStatusTime(statusUpdatedAt); latestOK {
				if jobAt, jobOK := parseRunStatusTime(heartbeat); !jobOK || latestAt.After(jobAt) {
					heartbeat = statusUpdatedAt
				}
			}
			if updated, ok := parseRunStatusTime(heartbeat); ok && time.Since(updated) <= 10*time.Minute {
				continue
			}
			message := fmt.Sprintf("%s进程超过 10 分钟无心跳且进程不存在，已自动标记为异常", runStatusTaskDisplayName(taskName))
			if taskName == "data_update" {
				app.markDataUpdateError(message)
				continue
			}
			app.markPythonStatusTaskError(taskName, message)
			continue
		}
		if state == "done" || state == "success" {
			app.upsertRunStatusTaskJobMessage(taskName, state, runStatusTaskDisplayName(taskName)+"已完成，已清理运行记录")
			continue
		}
		app.upsertRunStatusTaskJobError(taskName, runStatusTaskDisplayName(taskName)+"状态已结束，已清理卡住的运行记录")
	}
}

func (app *App) latestRunStatusTaskJobHeartbeat(taskName string) string {
	if app.database == nil {
		return ""
	}
	var updatedAt string
	err := app.database.Conn().QueryRow(
		`SELECT COALESCE(updated_at, '') FROM task_jobs WHERE id=? AND status IN ('created','queued','running')`,
		runStatusTaskJobID(taskName),
	).Scan(&updatedAt)
	if err != nil {
		return ""
	}
	return updatedAt
}

func (app *App) reconcileDataUpdateStatus(status datafetch.RunStatus) (datafetch.RunStatus, error) {
	if status.State != "running" {
		return status, nil
	}
	heartbeat := status.UpdatedAt
	if latestDatasetHeartbeat := app.latestDatasetUpdateHeartbeat(); latestDatasetHeartbeat != "" {
		if latestAt, latestOK := parseRunStatusTime(latestDatasetHeartbeat); latestOK {
			if statusAt, statusOK := parseRunStatusTime(heartbeat); !statusOK || latestAt.After(statusAt) {
				heartbeat = latestDatasetHeartbeat
			}
		}
	}
	updatedAt, ok := parseRunStatusTime(heartbeat)
	if ok && time.Since(updatedAt) <= 10*time.Minute {
		if heartbeat != status.UpdatedAt {
			app.touchDataUpdateStatus(heartbeat)
			status.UpdatedAt = heartbeat
		}
		return status, nil
	}
	if status.WorkerPID > 0 && processExists(status.WorkerPID) {
		return status, nil
	}
	app.markDataUpdateError("更新进程超过 10 分钟没有进度，已自动标记为异常")
	return app.datafetchService.GetStatus()
}

func (app *App) markDataUpdateWorkerStarted(pid int) {
	if app.database == nil || pid <= 0 {
		return
	}
	now := time.Now().Format(time.RFC3339)
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{"task", "task_type", "state", "idx", "total", "stage", "name", "message", "worker_pid", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"task_type", "state", "worker_pid", "updated_at", "finished_at"},
		),
		"data_update", "data_update", "running", 0, 0, "", "", "", pid, now, now, "",
	)
}

func (app *App) latestDatasetUpdateHeartbeat() string {
	if app.database == nil {
		return ""
	}
	var updatedAt string
	err := app.database.Conn().QueryRow(
		`SELECT COALESCE(MAX(updated_at), '') FROM task_jobs
		 WHERE task_type='data_update' AND status IN ('created','queued','running')`,
	).Scan(&updatedAt)
	if err != nil {
		return ""
	}
	return updatedAt
}

func (app *App) touchDataUpdateStatus(updatedAt string) {
	if app.database == nil || strings.TrimSpace(updatedAt) == "" {
		return
	}
	_, _ = app.database.Conn().Exec(
		`UPDATE task_run_status SET updated_at=? WHERE task='data_update' AND state='running'`,
		updatedAt,
	)
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
		`UPDATE task_run_status
		 SET state='error', message=?, worker_pid=NULL, updated_at=?, finished_at=?
		 WHERE task='data_update' AND state='running'`,
		message, now, now,
	)
	_, _ = db.Exec(
		`UPDATE task_jobs
		 SET status='failed', error_message=?, finished_at=?, updated_at=?
		 WHERE task_type='data_update' AND status IN ('created','queued','running')`,
		message, now, now,
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

func (app *App) CheckExternalDependencies() ([]ExternalDependencyStatus, error) {
	return []ExternalDependencyStatus{
		app.checkMySQLDependency(),
		app.checkTushareDependency(),
		app.checkLLMDependency(),
		app.checkRealtimeQuoteDependency(),
		app.checkWechatDependency(),
	}, nil
}

func (app *App) checkMySQLDependency() ExternalDependencyStatus {
	return app.measureDependency("mysql", "MySQL 数据库", "基础设施", func() error {
		if err := app.ensureDatabase(); err != nil {
			return err
		}
		if app.database == nil || app.database.Conn() == nil {
			return errors.New("数据库连接未初始化")
		}
		return app.database.Conn().Ping()
	})
}

func (app *App) checkTushareDependency() ExternalDependencyStatus {
	token := strings.TrimSpace(app.settings.TushareToken)
	if token == "" {
		return dependencyStatus("tushare", "Tushare 数据接口", "行情/财务数据", "missing", 0, "config.toml 未配置 [data].tushare_token")
	}
	return app.measureDependency("tushare", "Tushare 数据接口", "行情/财务数据", func() error {
		payload, _ := json.Marshal(map[string]any{
			"api_name": "trade_cal",
			"token":    token,
			"params": map[string]any{
				"exchange":   "SSE",
				"start_date": time.Now().AddDate(0, 0, -7).Format("20060102"),
				"end_date":   time.Now().Format("20060102"),
			},
			"fields": "cal_date,is_open",
		})
		ctx, cancel := context.WithTimeout(app.contextOrBackground(), 6*time.Second)
		defer cancel()
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, "http://api.tushare.pro", bytes.NewReader(payload))
		if err != nil {
			return err
		}
		req.Header.Set("Content-Type", "application/json")
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			return err
		}
		defer resp.Body.Close()
		respBody, _ := io.ReadAll(io.LimitReader(resp.Body, 1024*1024))
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return fmt.Errorf("HTTP %d", resp.StatusCode)
		}
		var parsed struct {
			Code int    `json:"code"`
			Msg  string `json:"msg"`
		}
		if err := json.Unmarshal(respBody, &parsed); err != nil {
			return err
		}
		if parsed.Code != 0 {
			return fmt.Errorf("Tushare code=%d %s", parsed.Code, strings.TrimSpace(parsed.Msg))
		}
		return nil
	})
}

func (app *App) checkDeepSeekDependency() ExternalDependencyStatus {
	return app.checkLLMDependency()
}

func (app *App) llmProvider() string {
	provider := strings.ToLower(strings.TrimSpace(app.settings.LLMProvider))
	if provider == "deepseek" {
		return "deepseek"
	}
	return "openai"
}

func (app *App) llmToken() string {
	if app.llmProvider() == "deepseek" {
		return app.settings.DeepSeekToken
	}
	return app.settings.OpenAIToken
}

func (app *App) llmModel() string {
	if app.llmProvider() == "deepseek" {
		return firstNonEmpty(app.settings.DeepSeekModel, "deepseek-v4-pro")
	}
	return firstNonEmpty(app.settings.OpenAIModel, "gpt-5.5")
}

func (app *App) llmDisplayName() string {
	if app.llmProvider() == "deepseek" {
		return "DeepSeek"
	}
	return "OpenAI"
}

func (app *App) llmEndpoint() string {
	if app.llmProvider() == "deepseek" {
		return "https://api.deepseek.com/chat/completions"
	}
	return "https://api.openai.com/v1/chat/completions"
}

func (app *App) llmMissingTokenMessage() string {
	if app.llmProvider() == "deepseek" {
		return "DeepSeek Token 未设置，请在设置页填写"
	}
	return "OpenAI Token 未设置，请在设置页填写"
}

func (app *App) checkLLMDependency() ExternalDependencyStatus {
	provider := app.llmProvider()
	token := strings.TrimSpace(app.llmToken())
	name := app.llmDisplayName()
	if token == "" {
		return dependencyStatus("llm", name, "AI 复盘/报告", "missing", 0, app.llmMissingTokenMessage())
	}
	return app.measureDependency("llm", name, "AI 复盘/报告", func() error {
		body := map[string]any{
			"model": app.llmModel(),
			"messages": []map[string]string{
				{"role": "system", "content": "你是接口健康检查助手。"},
				{"role": "user", "content": "请只输出 ok 两个字母。"},
			},
			"stream": false,
		}
		if provider == "deepseek" {
			body["thinking"] = map[string]string{"type": "enabled"}
			body["reasoning_effort"] = "high"
		}
		payload, _ := json.Marshal(body)
		ctx, cancel := context.WithTimeout(app.contextOrBackground(), 12*time.Second)
		defer cancel()
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, app.llmEndpoint(), bytes.NewReader(payload))
		if err != nil {
			return err
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", "Bearer "+token)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			return err
		}
		defer resp.Body.Close()
		respBody, _ := io.ReadAll(io.LimitReader(resp.Body, 1024*1024))
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return fmt.Errorf("HTTP %d %s", resp.StatusCode, strings.TrimSpace(string(respBody)))
		}
		var parsed struct {
			Choices []struct {
				Message struct {
					Content          string `json:"content"`
					ReasoningContent string `json:"reasoning_content"`
				} `json:"message"`
			} `json:"choices"`
		}
		if err := json.Unmarshal(respBody, &parsed); err != nil {
			return err
		}
		if len(parsed.Choices) == 0 {
			return fmt.Errorf("%s 未返回 choices", name)
		}
		content := strings.TrimSpace(parsed.Choices[0].Message.Content)
		reasoning := strings.TrimSpace(parsed.Choices[0].Message.ReasoningContent)
		if content == "" && reasoning == "" {
			excerpt := strings.TrimSpace(string(respBody))
			if len(excerpt) > 280 {
				excerpt = excerpt[:280] + "..."
			}
			return fmt.Errorf("%s 返回为空：%s", name, excerpt)
		}
		return nil
	})
}

func (app *App) checkRealtimeQuoteDependency() ExternalDependencyStatus {
	return app.measureDependency("realtime_quote", "实时行情接口", "实时价格", func() error {
		price, err := app.fetchRealtimePrice("000001.SZ")
		if err != nil {
			return err
		}
		if price <= 0 {
			return errors.New("未返回有效价格")
		}
		return nil
	})
}

func (app *App) checkWechatDependency() ExternalDependencyStatus {
	webhook := strings.TrimSpace(app.settings.StrategySchedule.WechatWebhook)
	if webhook == "" {
		return dependencyStatus("wechat", "企业微信机器人", "通知", "missing", 0, "config.toml 未配置 [wechat].webhook")
	}
	if !strings.HasPrefix(webhook, "https://qyapi.weixin.qq.com/cgi-bin/webhook/send") {
		return dependencyStatus("wechat", "企业微信机器人", "通知", "error", 0, "webhook 地址格式不像企业微信机器人")
	}
	return dependencyStatus("wechat", "企业微信机器人", "通知", "ready", 0, "已配置；监控页不自动发送测试消息")
}

func (app *App) measureDependency(key string, name string, category string, fn func() error) ExternalDependencyStatus {
	start := time.Now()
	err := fn()
	latency := time.Since(start).Milliseconds()
	if err != nil {
		return dependencyStatus(key, name, category, "error", latency, err.Error())
	}
	return dependencyStatus(key, name, category, "ready", latency, "可用")
}

func dependencyStatus(key string, name string, category string, state string, latencyMS int64, message string) ExternalDependencyStatus {
	return ExternalDependencyStatus{
		Key:       key,
		Name:      name,
		Category:  category,
		State:     state,
		LatencyMS: latencyMS,
		Message:   message,
		CheckedAt: time.Now().Format(time.RFC3339),
	}
}

func (app *App) contextOrBackground() context.Context {
	if app.ctx != nil {
		return app.ctx
	}
	return context.Background()
}

func (app *App) ensureDatafetchService() error {
	if app.datafetchService != nil {
		return nil
	}
	if err := app.ensureDatabase(); err != nil {
		return err
	}
	svc := datafetch.New(
		app.database,
		app.settings.DataPath,
		func() string { return app.settings.TushareToken },
	)
	svc.SetContext(app.ctx)
	app.datafetchService = svc
	return nil
}

func (app *App) CreateTask(req task.CreateRequest) (task.DTO, error) {
	if err := app.ensureTaskService(); err != nil {
		return task.DTO{}, err
	}
	normalizedReq, err := normalizeDesktopCreateTaskRequest(req)
	if err != nil {
		return task.DTO{}, err
	}
	req = normalizedReq
	if req.TaskType == task.TypeModelTraining && modelTrainingStrategy(req.Params) != profitArenaStrategyID {
		return task.DTO{}, errors.New("该模型训练策略已从桌面生产链路删除；只允许创建通用策略训练/推理任务")
	}
	if req.TaskType == task.TypeModelTraining && modelTrainingStrategy(req.Params) == profitArenaStrategyID {
		app.profitArenaTaskMu.Lock()
		defer app.profitArenaTaskMu.Unlock()
		blocker, err := app.activeProfitArenaModelTaskBlocker("")
		if err != nil {
			return task.DTO{}, err
		}
		if blocker.Count > 0 {
			return task.DTO{}, fmt.Errorf("已有 %d 个通用策略训练/推理任务未完成：%s，请等待完成或到任务中心处理后再创建", blocker.Count, blocker.Label())
		}
	}
	dto, err := app.taskService.Create(req)
	if err != nil {
		return task.DTO{}, err
	}

	if req.TaskType == task.TypeFactorResearch {
		parent, err := app.taskService.Repository().Get(dto.ID)
		if err != nil {
			return task.DTO{}, err
		}
		if err := app.initializeFactorResearch(parent); err != nil {
			return task.DTO{}, err
		}
		parent, err = app.taskService.Repository().Get(dto.ID)
		if err != nil {
			return task.DTO{}, err
		}
		return task.ToDTO(parent), nil
	}
	if req.TaskType == task.TypeModelTraining {
		parent, err := app.taskService.Repository().Get(dto.ID)
		if err != nil {
			return task.DTO{}, err
		}
		if err := app.initializeModelTraining(parent); err != nil {
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

type activeProfitArenaTaskBlocker struct {
	Count  int
	ID     string
	Name   string
	Status string
}

func (b activeProfitArenaTaskBlocker) Label() string {
	id := strings.TrimSpace(b.ID)
	if len(id) > 12 {
		id = id[:12]
	}
	name := strings.TrimSpace(b.Name)
	if name == "" {
		name = "通用策略任务"
	}
	status := strings.TrimSpace(b.Status)
	if status == "" {
		status = "active"
	}
	if id == "" {
		return fmt.Sprintf("%s/%s", name, status)
	}
	return fmt.Sprintf("%s/%s/%s", name, status, id)
}

func (app *App) activeProfitArenaModelTaskBlocker(excludeID string) (activeProfitArenaTaskBlocker, error) {
	if app.database == nil || app.database.Conn() == nil || !app.database.TableExists("task_jobs") {
		return activeProfitArenaTaskBlocker{}, nil
	}
	args := []any{
		string(task.TypeModelTraining),
		strings.TrimSpace(excludeID),
		"%" + profitArenaStrategyID + "%",
	}
	var blocker activeProfitArenaTaskBlocker
	countRow := app.database.Conn().QueryRow(`
		SELECT COUNT(*)
		FROM task_jobs
		WHERE task_type = ?
		  AND status IN ('created', 'queued', 'running')
		  AND id <> ?
		  AND COALESCE(params_json, '') LIKE ?`,
		args...,
	)
	if err := countRow.Scan(&blocker.Count); err != nil {
		return activeProfitArenaTaskBlocker{}, err
	}
	if blocker.Count == 0 {
		return blocker, nil
	}
	detailRow := app.database.Conn().QueryRow(`
		SELECT id, name, status
		FROM task_jobs
		WHERE task_type = ?
		  AND status IN ('created', 'queued', 'running')
		  AND id <> ?
		  AND COALESCE(params_json, '') LIKE ?
		ORDER BY updated_at DESC, created_at DESC
		LIMIT 1`,
		args...,
	)
	if err := detailRow.Scan(&blocker.ID, &blocker.Name, &blocker.Status); err != nil {
		return activeProfitArenaTaskBlocker{}, err
	}
	return blocker, nil
}

func normalizeDesktopCreateTaskRequest(req task.CreateRequest) (task.CreateRequest, error) {
	if req.Params == nil {
		req.Params = map[string]any{}
	}
	if req.TaskType == "" {
		return task.CreateRequest{}, errors.New("桌面任务必须指定生产任务类型；请使用通用策略训练、数据更新或因子快照入口")
	}
	switch req.TaskType {
	case task.TypeEvaluationTimeMachine:
		return task.CreateRequest{}, errors.New("历史时间机器验证已退出生产链路；通用策略验证请查看通用策略训练结果和评估表")
	case task.TypeFactorResearch:
		return req, nil
	case task.TypeModelTraining:
		if modelTrainingStrategy(req.Params) != profitArenaStrategyID {
			return task.CreateRequest{}, errors.New("该模型训练任务不在桌面生产链路；桌面只允许新建通用策略训练/推理任务")
		}
		req.Params["strategy"] = profitArenaStrategyID
		return req, nil
	default:
		return task.CreateRequest{}, fmt.Errorf("桌面生产入口不允许新建 %s；请使用通用策略、因子研究留档或数据更新入口", req.TaskType)
	}
}

func normalizeProfitArenaOnlyParam(params map[string]any, key string) error {
	values := stringListParam(params[key])
	if len(values) == 0 {
		params[key] = profitArenaStrategyID
		return nil
	}
	normalized := make([]string, 0, len(values))
	for _, value := range values {
		strategy := normalizeProfitArenaStrategyID(value)
		if strategy == "" {
			return fmt.Errorf("桌面组合评估只允许通用策略模型，已拒绝旧模型: %s", value)
		}
		normalized = append(normalized, strategy)
	}
	switch params[key].(type) {
	case []string, []any:
		params[key] = normalized
	default:
		params[key] = strings.Join(normalized, ",")
	}
	return nil
}

func stringListParam(value any) []string {
	switch v := value.(type) {
	case nil:
		return nil
	case string:
		parts := strings.Split(v, ",")
		out := make([]string, 0, len(parts))
		for _, part := range parts {
			item := strings.TrimSpace(part)
			if item != "" {
				out = append(out, item)
			}
		}
		return out
	case []string:
		out := make([]string, 0, len(v))
		for _, item := range v {
			item = strings.TrimSpace(item)
			if item != "" {
				out = append(out, item)
			}
		}
		return out
	case []any:
		out := make([]string, 0, len(v))
		for _, item := range v {
			text := strings.TrimSpace(fmt.Sprint(item))
			if text != "" {
				out = append(out, text)
			}
		}
		return out
	default:
		text := strings.TrimSpace(fmt.Sprint(v))
		if text == "" {
			return nil
		}
		return []string{text}
	}
}

func normalizeProfitArenaStrategyID(value string) string {
	switch strings.TrimSpace(value) {
	case profitArenaStrategyID, "profit_arena":
		return profitArenaStrategyID
	default:
		return ""
	}
}

func (app *App) initializeFactorResearch(parent task.Task) error {
	if app.database == nil {
		if err := app.ensureDatabase(); err != nil {
			return err
		}
	}
	params := task.ToDTO(parent).Params
	startDate := stringParam(params, "start_date", "")
	endDate := stringParam(params, "end_date", "")
	if startDate == "" || endDate == "" {
		return errors.New("factor research requires start_date and end_date")
	}
	children, err := app.taskService.Repository().ListChildren(parent.ID)
	if err != nil {
		return err
	}
	if len(children) > 0 {
		return app.ensureFactorResearchStages(parent, children)
	}
	profile := factorResearchProfile(params)
	stages := factorResearchStages(profile)
	now := time.Now()
	runID := parent.ExternalRunID
	if requestedRunID := strings.TrimSpace(stringParam(params, "run_id", "")); requestedRunID != "" {
		runID = requestedRunID
	}
	if runID == "" {
		runID = factorResearchRunID(profile, parent.ID)
	}
	minTrainYears := int(numberParam(params, "min_train_years", factorResearchDefaultMinTrainYears(profile)))
	minTestYear := int(numberParam(params, "min_test_year", factorResearchDefaultMinTestYear(profile)))
	stressAware := boolParam(params, "stress_aware", profile != "smoke")
	parent.ExternalRunID = runID
	parent.Total = len(stages)
	parent.Progress = 0
	parent.ResultPath = filepath.Join(app.settings.DataPath, "factor_research", runID)
	parent.SummaryJSON = mustJSON(map[string]any{
		"start":           startDate,
		"end":             endDate,
		"freq":            stringParam(params, "freq", "monthly"),
		"label":           stringParam(params, "label", "fwd20_excess_industry"),
		"profile":         profile,
		"min_train_years": minTrainYears,
		"min_test_year":   minTestYear,
		"stress_aware":    stressAware,
		"planned_count":   len(stages),
		"completed_count": 0,
		"failed_count":    0,
		"running_count":   0,
		"rows":            []any{},
	})
	parent.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(parent); err != nil {
		return err
	}
	for idx, stage := range stages {
		childParams := map[string]any{
			"start_date":      startDate,
			"end_date":        endDate,
			"freq":            stringParam(params, "freq", "monthly"),
			"label":           stringParam(params, "label", "fwd20_excess_industry"),
			"profile":         profile,
			"min_train_years": minTrainYears,
			"min_test_year":   minTestYear,
			"stress_aware":    stressAware,
			"stage":           stage["key"],
		}
		paramsData, err := json.Marshal(childParams)
		if err != nil {
			return err
		}
		child := task.Task{
			ID:            task.NewID(),
			Name:          stage["name"],
			TaskType:      task.TypeFactorResearch,
			Status:        task.StatusCreated,
			Progress:      0,
			ParamsJSON:    string(paramsData),
			WorkerType:    "python",
			ExternalRunID: runID,
			ParentID:      parent.ID,
			GroupRunID:    runID,
			SubtaskKey:    stage["key"],
			SubtaskName:   stage["name"],
			Sequence:      idx + 1,
			Total:         len(stages),
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

func (app *App) ensureFactorResearchStages(parent task.Task, children []task.Task) error {
	params := task.ToDTO(parent).Params
	profile := factorResearchProfile(params)
	if profile == "inference" {
		return nil
	}
	startDate := stringParam(params, "start_date", "")
	endDate := stringParam(params, "end_date", "")
	if startDate == "" || endDate == "" {
		return errors.New("factor research requires start_date and end_date")
	}
	stages := factorResearchStages(profile)
	existing := make(map[string]bool, len(children))
	maxSequence := 0
	for _, child := range children {
		if child.SubtaskKey != "" {
			existing[child.SubtaskKey] = true
		}
		if child.Sequence > maxSequence {
			maxSequence = child.Sequence
		}
	}
	if len(existing) >= len(stages) {
		return nil
	}
	runID := parent.ExternalRunID
	if requestedRunID := strings.TrimSpace(stringParam(params, "run_id", "")); requestedRunID != "" {
		runID = requestedRunID
	}
	if runID == "" {
		runID = parent.GroupRunID
	}
	if runID == "" {
		runID = factorResearchRunID(profile, parent.ID)
	}
	minTrainYears := int(numberParam(params, "min_train_years", factorResearchDefaultMinTrainYears(profile)))
	minTestYear := int(numberParam(params, "min_test_year", factorResearchDefaultMinTestYear(profile)))
	stressAware := boolParam(params, "stress_aware", profile != "smoke")
	now := time.Now()
	added := 0
	for _, stage := range stages {
		key := stage["key"]
		if existing[key] {
			continue
		}
		maxSequence++
		childParams := map[string]any{
			"start_date":      startDate,
			"end_date":        endDate,
			"freq":            stringParam(params, "freq", "monthly"),
			"label":           stringParam(params, "label", "fwd20_excess_industry"),
			"profile":         profile,
			"min_train_years": minTrainYears,
			"min_test_year":   minTestYear,
			"stress_aware":    stressAware,
			"stage":           key,
		}
		paramsData, err := json.Marshal(childParams)
		if err != nil {
			return err
		}
		child := task.Task{
			ID:            task.NewID(),
			Name:          stage["name"],
			TaskType:      task.TypeFactorResearch,
			Status:        task.StatusCreated,
			Progress:      0,
			ParamsJSON:    string(paramsData),
			WorkerType:    "python",
			ExternalRunID: runID,
			ParentID:      parent.ID,
			GroupRunID:    runID,
			SubtaskKey:    key,
			SubtaskName:   stage["name"],
			Sequence:      maxSequence,
			Total:         len(stages),
			MaxAttempts:   2,
			CreatedAt:     now.Add(time.Duration(maxSequence) * time.Millisecond),
			UpdatedAt:     now,
		}
		if err := app.taskService.Repository().Create(child); err != nil {
			return err
		}
		added++
	}
	if added == 0 {
		return nil
	}
	parent.ExternalRunID = runID
	parent.GroupRunID = runID
	parent.Total = len(stages)
	parent.ResultPath = filepath.Join(app.settings.DataPath, "factor_research", runID)
	parent.UpdatedAt = now
	return app.taskService.Repository().UpdateRuntime(parent)
}

func factorResearchProfile(params map[string]any) string {
	profile := strings.ToLower(stringParam(params, "profile", "full"))
	switch profile {
	case "smoke", "full", "inference":
		return profile
	default:
		return "full"
	}
}

func factorResearchRunID(profile string, taskID string) string {
	prefix := "fr_full_"
	if profile == "smoke" {
		prefix = "fr_smoke_"
	}
	return prefix + strings.ReplaceAll(taskID, "-", "")
}

func factorResearchDefaultMinTrainYears(profile string) float64 {
	if profile == "smoke" {
		return 2
	}
	return 4
}

func factorResearchDefaultMinTestYear(profile string) float64 {
	if profile == "smoke" {
		return 2020
	}
	return 0
}

func factorResearchStages(profile string) []map[string]string {
	if profile == "inference" {
		return []map[string]string{
			{"key": "latest_inference", "name": "最新截面推理"},
		}
	}
	stages := []map[string]string{
		{"key": "build_factor_panel", "name": "生成因子面板"},
		{"key": "evaluate_factors", "name": "因子检验"},
		{"key": "factor_correlation_report", "name": "因子相关性报告"},
		{"key": "train_lgbm", "name": "训练 LightGBM"},
		{"key": "latest_inference", "name": "最新截面推理"},
		{"key": "stress_report", "name": "压力测试报告"},
		{"key": "validate_research_run", "name": "产物完整性检查"},
	}
	return stages
}

func factorResearchStageCommandArgs(runID string, stage string, startDate string, endDate string, params map[string]any) []string {
	if stage == "strategy_admission" {
		stage = "validate_research_run"
	}
	args := []string{
		"scripts/factor_research_worker.py",
		"--run-id", runID,
		"--stage", stage,
		"--start", startDate,
		"--end", endDate,
		"--freq", stringParam(params, "freq", "monthly"),
		"--label", stringParam(params, "label", "fwd20_excess_industry"),
		"--min-train-years", strconv.Itoa(int(numberParam(params, "min_train_years", 4))),
		"--min-test-year", strconv.Itoa(int(numberParam(params, "min_test_year", 0))),
	}
	if boolParam(params, "stress_aware", false) {
		args = append(args, "--stress-aware")
	}
	return args
}

func factorResearchStageEnv(runID string, stage string, params map[string]any) []string {
	return nil
}

func (app *App) initializeModelTraining(parent task.Task) error {
	if app.database == nil {
		if err := app.ensureDatabase(); err != nil {
			return err
		}
	}
	params := task.ToDTO(parent).Params
	strategy := modelTrainingStrategy(params)
	if strategy == "" {
		return errors.New("model training requires strategy")
	}
	children, err := app.taskService.Repository().ListChildren(parent.ID)
	if err != nil {
		return err
	}
	if len(children) > 0 {
		return nil
	}
	stages := modelTrainingStages(strategy)
	runID := strings.TrimSpace(parent.ExternalRunID)
	if requestedRunID := strings.TrimSpace(stringParam(params, "run_id", "")); requestedRunID != "" {
		runID = requestedRunID
	}
	if runID == "" {
		runID = modelTrainingRunID(strategy)
	}
	now := time.Now()
	parent.ExternalRunID = runID
	parent.GroupRunID = runID
	parent.Total = len(stages)
	parent.Progress = 0
	parent.ResultPath = filepath.Join(app.settings.DataPath, "model_training", strategy, runID)
	parent.SummaryJSON = mustJSON(map[string]any{
		"strategy":        strategy,
		"strategy_name":   modelTrainingStrategyName(strategy),
		"run_id":          runID,
		"planned_count":   len(stages),
		"completed_count": 0,
		"failed_count":    0,
		"running_count":   0,
		"rows":            []any{},
	})
	parent.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(parent); err != nil {
		return err
	}
	for idx, stage := range stages {
		childParams := map[string]any{
			"strategy": strategy,
			"stage":    stage["key"],
		}
		for key, value := range params {
			if _, exists := childParams[key]; !exists {
				childParams[key] = value
			}
		}
		paramsData, err := json.Marshal(childParams)
		if err != nil {
			return err
		}
		child := task.Task{
			ID:            task.NewID(),
			Name:          stage["name"],
			TaskType:      task.TypeModelTraining,
			Status:        task.StatusCreated,
			Progress:      0,
			ParamsJSON:    string(paramsData),
			WorkerType:    "python",
			ExternalRunID: runID,
			ParentID:      parent.ID,
			GroupRunID:    runID,
			SubtaskKey:    stage["key"],
			SubtaskName:   stage["name"],
			Sequence:      idx + 1,
			Total:         len(stages),
			MaxAttempts:   1,
			CreatedAt:     now.Add(time.Duration(idx) * time.Millisecond),
			UpdatedAt:     now,
		}
		if err := app.taskService.Repository().Create(child); err != nil {
			return err
		}
	}
	return nil
}

func modelTrainingStrategy(params map[string]any) string {
	strategy := strings.TrimSpace(stringParam(params, "strategy", ""))
	if strategy == "" {
		strategy = strings.TrimSpace(stringParam(params, "task", ""))
	}
	switch strategy {
	case profitArenaStrategyID, "profit_arena":
		return profitArenaStrategyID
	default:
		return ""
	}
}

func modelTrainingStages(strategy string) []map[string]string {
	if strategy == profitArenaStrategyID {
		return []map[string]string{
			{"key": "train_model", "name": modelTrainingStrategyName(strategy) + "训练"},
		}
	}
	return []map[string]string{
		{"key": "train_model", "name": modelTrainingStrategyName(strategy) + "训练"},
		{"key": "validate_model_run", "name": "产物完整性检查"},
	}
}

func modelTrainingStrategyName(strategy string) string {
	switch strategy {
	case profitArenaStrategyID:
		return "通用策略模型"
	default:
		return "策略模型"
	}
}

func modelTrainingRunID(strategy string) string {
	prefix := "mt"
	if strategy == profitArenaStrategyID {
		prefix = "profit_arena"
	}
	return prefix + "_" + time.Now().Format("20060102_150405")
}

func modelTrainingStatusTask(strategy string) string {
	if strategy == profitArenaStrategyID {
		return profitArenaStrategyID
	}
	return strategy
}

func modelTrainingStageCommandArgs(strategy string, runID string, stage string, dataPath string, params map[string]any) ([]string, error) {
	endDate := strings.TrimSpace(stringParam(params, "end_date", time.Now().Format("20060102")))
	if endDate == "" {
		endDate = time.Now().Format("20060102")
	}
	switch stage {
	case "train_model":
		switch strategy {
		case profitArenaStrategyID:
			if stringParam(params, "profile", "") == "inference" {
				return compactArgs([]string{
					"scripts/profit_arena_worker.py",
					"--run-id", runID,
					"--data-path", dataPath,
					"--start", stringParam(params, "start_date", "20100101"),
					"--end", endDate,
					"--horizons", stringParam(params, "horizons", "20"),
					"--top-n", stringParam(params, "top_n", "20"),
					"--arena-name", stringParam(params, "arena_name", profitArenaDefaultArenaName),
					"--scopes", stringParam(params, "scopes", "small"),
					"--feature-set", stringParam(params, "feature_set", "stock_h20_general_final_v1"),
					"--factor-store-id", stringParam(params, "factor_store_id", "stock_factor_base_v1"),
					"--factor-store-mode", stringParam(params, "factor_store_mode", "auto"),
					"--factor-store-feature-set", stringParam(params, "factor_store_feature_set", "stock_factor_base_v1"),
					"--factor-preprocess", stringParam(params, "factor_preprocess", "institutional"),
					boolFlag("--allow-factor-quality-fail", boolParam(params, "allow_factor_quality_fail", false)),
					boolFlag("--allow-feature-consistency-fail", boolParam(params, "allow_feature_consistency_fail", false)),
					boolFlag("--require-fresh-factor-snapshot", boolParam(params, "require_fresh_factor_snapshot", false)),
					boolFlag("--allow-factor-snapshot-stale", boolParam(params, "allow_factor_snapshot_stale", false)),
					"--capacity-capital-base", fmt.Sprintf("%g", numberParam(params, "capacity_capital_base", 20000.0)),
					"--capacity-target-participation-rate", fmt.Sprintf("%g", numberParam(params, "capacity_target_participation_rate", 0.02)),
					"--capacity-max-participation-rate", fmt.Sprintf("%g", numberParam(params, "capacity_max_participation_rate", 0.05)),
					"--capacity-impact-bps-coefficient", fmt.Sprintf("%g", numberParam(params, "capacity_impact_bps_coefficient", 50.0)),
					boolFlag("--enforce-capacity-gate", boolParam(params, "enforce_capacity_gate", false)),
					boolFlag("--allow-capacity-fail", boolParam(params, "allow_capacity_fail", false)),
					"--portfolio-max-single-weight", fmt.Sprintf("%g", numberParam(params, "portfolio_max_single_weight", 0.10)),
					"--portfolio-max-industry-weight", fmt.Sprintf("%g", numberParam(params, "portfolio_max_industry_weight", 0.30)),
					"--portfolio-max-size-bucket-weight", fmt.Sprintf("%g", numberParam(params, "portfolio_max_size_bucket_weight", 0.60)),
					"--portfolio-max-avg-crash-prob", fmt.Sprintf("%g", numberParam(params, "portfolio_max_avg_crash_prob", 0.15)),
					boolFlag("--enforce-portfolio-risk-gate", boolParam(params, "enforce_portfolio_risk_gate", false)),
					boolFlag("--allow-portfolio-risk-fail", boolParam(params, "allow_portfolio_risk_fail", false)),
					"--model-kind", stringParam(params, "model_kind", "hybrid"),
					"--target-mode", stringParam(params, "target_mode", "net_return"),
					"--score-mode", stringParam(params, "score_mode", "raw"),
					"--crash-filter", stringParam(params, "crash_filter", "none"),
					"--breakout-filter", stringParam(params, "breakout_filter", "none"),
					"--rank-score-weight", fmt.Sprintf("%g", numberParam(params, "rank_score_weight", 1.0)),
					"--pred-score-weight", fmt.Sprintf("%g", numberParam(params, "pred_score_weight", 0.25)),
					"--breakout-score-weight", fmt.Sprintf("%g", numberParam(params, "breakout_score_weight", 1.0)),
					"--crash-score-weight", fmt.Sprintf("%g", numberParam(params, "crash_score_weight", 0.25)),
					"--latest-inference-source-run-id", stringParam(params, "latest_inference_source_run_id", stringParam(params, "source_run_id", "")),
					"--latest-inference-model-path", stringParam(params, "latest_inference_model_path", stringParam(params, "model_path", "")),
					"--latest-inference-scope", stringParam(params, "latest_inference_scope", stringParam(params, "scopes", "small")),
					"--latest-inference-horizon", strconv.Itoa(int(numberParam(params, "latest_inference_horizon", numberParam(params, "horizon", 20)))),
					"--latest-inference-buy-top-n", strconv.Itoa(int(numberParam(params, "latest_inference_buy_top_n", numberParam(params, "best_top_n", 0)))),
					"--execution-stop-loss=" + stringParam(params, "execution_stop_loss", "0"),
					"--execution-take-profit=" + stringParam(params, "execution_take_profit", "0.20,0.25,0.30"),
					"--threads", strconv.Itoa(int(numberParam(params, "threads", 4))),
				}), nil
			}
			return compactArgs([]string{
				"scripts/profit_arena_worker.py",
				"--run-id", runID,
				"--data-path", dataPath,
				"--start", stringParam(params, "start_date", "20100101"),
				"--end", endDate,
				"--min-train-years", strconv.Itoa(int(numberParam(params, "min_train_years", 4))),
				"--train-window-years", strconv.Itoa(int(numberParam(params, "train_window_years", 4))),
				"--min-test-year", strconv.Itoa(int(numberParam(params, "min_test_year", 2014))),
				"--min-train-rows", strconv.Itoa(int(numberParam(params, "min_train_rows", 3000))),
				"--arena-name", stringParam(params, "arena_name", profitArenaDefaultArenaName),
				"--horizons", stringParam(params, "horizons", "10"),
				"--top-n", stringParam(params, "top_n", "1,2,3,5,10"),
				"--min-pred-return=" + stringParam(params, "min_pred_return", "-999,0,0.005,0.01,0.02,0.03,0.05,0.08,0.1"),
				"--min-market-up-ratio=" + stringParam(params, "min_market_up_ratio", "-999"),
				"--min-market-ret5=" + stringParam(params, "min_market_ret5", "-999"),
				"--min-market-ret20=" + stringParam(params, "min_market_ret20", "-999"),
				"--min-market-amount-chg5=" + stringParam(params, "min_market_amount_chg5", "-999,0"),
				"--min-market-volatility20=" + stringParam(params, "min_market_volatility20", "-999"),
				"--max-market-drawdown20=" + stringParam(params, "max_market_drawdown20", "999"),
				"--max-market-volatility20=" + stringParam(params, "max_market_volatility20", "999"),
				"--min-industry-up-ratio=" + stringParam(params, "min_industry_up_ratio", "-999"),
				"--max-crash-prob=" + stringParam(params, "max_crash_prob", "999"),
				"--min-daily-top-score=" + stringParam(params, "min_daily_top_score", "-999"),
				"--min-daily-top-pred-return=" + stringParam(params, "min_daily_top_pred_return", "-999"),
				"--max-daily-top-crash-prob=" + stringParam(params, "max_daily_top_crash_prob", "999"),
				"--scopes", stringParam(params, "scopes", "all"),
				"--feature-set", stringParam(params, "feature_set", "stock_h20_general_final_v1"),
				"--factor-store-id", stringParam(params, "factor_store_id", "stock_factor_base_v1"),
				"--factor-store-mode", stringParam(params, "factor_store_mode", "auto"),
				"--factor-store-feature-set", stringParam(params, "factor_store_feature_set", "stock_factor_base_v1"),
				"--factor-preprocess", stringParam(params, "factor_preprocess", "institutional"),
				boolFlag("--allow-factor-quality-fail", boolParam(params, "allow_factor_quality_fail", false)),
				boolFlag("--allow-feature-consistency-fail", boolParam(params, "allow_feature_consistency_fail", false)),
				boolFlag("--require-fresh-factor-snapshot", boolParam(params, "require_fresh_factor_snapshot", false)),
				boolFlag("--allow-factor-snapshot-stale", boolParam(params, "allow_factor_snapshot_stale", false)),
				"--capacity-capital-base", fmt.Sprintf("%g", numberParam(params, "capacity_capital_base", 20000.0)),
				"--capacity-target-participation-rate", fmt.Sprintf("%g", numberParam(params, "capacity_target_participation_rate", 0.02)),
				"--capacity-max-participation-rate", fmt.Sprintf("%g", numberParam(params, "capacity_max_participation_rate", 0.05)),
				"--capacity-impact-bps-coefficient", fmt.Sprintf("%g", numberParam(params, "capacity_impact_bps_coefficient", 50.0)),
				boolFlag("--enforce-capacity-gate", boolParam(params, "enforce_capacity_gate", false)),
				boolFlag("--allow-capacity-fail", boolParam(params, "allow_capacity_fail", false)),
				"--portfolio-max-single-weight", fmt.Sprintf("%g", numberParam(params, "portfolio_max_single_weight", 0.10)),
				"--portfolio-max-industry-weight", fmt.Sprintf("%g", numberParam(params, "portfolio_max_industry_weight", 0.30)),
				"--portfolio-max-size-bucket-weight", fmt.Sprintf("%g", numberParam(params, "portfolio_max_size_bucket_weight", 0.60)),
				"--portfolio-max-avg-crash-prob", fmt.Sprintf("%g", numberParam(params, "portfolio_max_avg_crash_prob", 0.15)),
				boolFlag("--enforce-portfolio-risk-gate", boolParam(params, "enforce_portfolio_risk_gate", false)),
				boolFlag("--allow-portfolio-risk-fail", boolParam(params, "allow_portfolio_risk_fail", false)),
				"--model-kind", stringParam(params, "model_kind", "regressor"),
				"--target-mode", stringParam(params, "target_mode", "net_return"),
				"--score-mode", stringParam(params, "score_mode", "blended"),
				"--crash-filter", stringParam(params, "crash_filter", "none"),
				"--crash-return-threshold", fmt.Sprintf("%g", numberParam(params, "crash_return_threshold", -0.08)),
				"--crash-drawdown-threshold", fmt.Sprintf("%g", numberParam(params, "crash_drawdown_threshold", -0.12)),
				"--crash-n-estimators", strconv.Itoa(int(numberParam(params, "crash_n_estimators", 160))),
				"--breakout-filter", stringParam(params, "breakout_filter", "none"),
				"--breakout-quantile", fmt.Sprintf("%g", numberParam(params, "breakout_quantile", 0.95)),
				"--breakout-n-estimators", strconv.Itoa(int(numberParam(params, "breakout_n_estimators", 160))),
				"--selection-metric", stringParam(params, "selection_metric", "capital_annual_return"),
				"--min-rank-ic", fmt.Sprintf("%g", numberParam(params, "min_rank_ic", 0)),
				"--min-rank-ic-days", strconv.Itoa(int(numberParam(params, "min_rank_ic_days", 0))),
				"--min-capital-annual-return", fmt.Sprintf("%g", numberParam(params, "min_capital_annual_return", 0)),
				"--max-capital-drawdown", fmt.Sprintf("%g", numberParam(params, "max_capital_drawdown", -0.25)),
				"--selection-min-trades", strconv.Itoa(int(numberParam(params, "selection_min_trades", 20))),
				"--selection-min-trade-years", strconv.Itoa(int(numberParam(params, "selection_min_trade_years", 0))),
				"--n-estimators", strconv.Itoa(int(numberParam(params, "n_estimators", 80))),
				"--learning-rate", fmt.Sprintf("%g", numberParam(params, "learning_rate", 0.05)),
				"--num-leaves", strconv.Itoa(int(numberParam(params, "num_leaves", 31))),
				"--max-depth", strconv.Itoa(int(numberParam(params, "max_depth", -1))),
				"--min-child-samples", strconv.Itoa(int(numberParam(params, "min_child_samples", 40))),
				"--subsample", fmt.Sprintf("%g", numberParam(params, "subsample", 0.9)),
				"--colsample-bytree", fmt.Sprintf("%g", numberParam(params, "colsample_bytree", 0.9)),
				"--reg-alpha", fmt.Sprintf("%g", numberParam(params, "reg_alpha", 0)),
				"--reg-lambda", fmt.Sprintf("%g", numberParam(params, "reg_lambda", 0)),
				"--execution-stop-loss=" + stringParam(params, "execution_stop_loss", "0"),
				"--execution-take-profit=" + stringParam(params, "execution_take_profit", "0.20,0.25,0.30"),
				"--position-weighting", stringParam(params, "position_weighting", "equal"),
				"--capital-scale-mode", stringParam(params, "capital_scale_mode", "none"),
				"--capital-tranche-fractions", stringParam(params, "capital_tranche_fractions", "1.0"),
				"--progress-every-evals", strconv.Itoa(int(numberParam(params, "progress_every_evals", 250))),
				"--threads", strconv.Itoa(int(numberParam(params, "threads", 4))),
			}), nil
		default:
			return nil, errors.New("unsupported model training strategy")
		}
	default:
		return nil, errors.New("unsupported model training stage")
	}
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
	visible := make([]task.DTO, 0, len(items))
	for _, item := range items {
		if isDesktopVisibleTask(item) {
			visible = append(visible, item)
		}
	}
	return visible, nil
}

func (app *App) GetTask(id string) (task.DTO, error) {
	if err := app.ensureTaskService(); err != nil {
		return task.DTO{}, err
	}
	t, err := app.taskService.Repository().Get(id)
	if err != nil {
		return task.DTO{}, err
	}
	dto := task.ToDTO(t)
	if !isDesktopVisibleTask(dto) {
		return task.DTO{}, errors.New("该任务已归档，不在桌面生产链路展示")
	}
	return dto, nil
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
	dto := task.ToDTO(t)
	if !isDesktopVisibleTask(dto) {
		return task.DTO{}, errors.New("该任务已归档，不在桌面生产链路展示")
	}
	return dto, nil
}

func isDesktopVisibleTask(dto task.DTO) bool {
	switch dto.TaskType {
	case task.TypeDataUpdate, task.TypeFactorSnapshot, task.TypeFactorResearch:
		return true
	case task.TypeModelTraining:
		return modelTrainingStrategy(dto.Params) == profitArenaStrategyID
	case profitArenaRebalanceTaskType:
		return true
	default:
		return false
	}
}

func (app *App) reconcileTaskStatus(t task.Task) task.Task {
	if t.Status != task.StatusRunning && t.Status != task.StatusQueued {
		return t
	}

	now := time.Now()
	if isHistoricalGovernanceTaskType(t.TaskType) {
		t.Status = task.StatusInterrupted
		t.WorkerPID = 0
		t.ErrorMessage = "历史治理任务已下线，只读保留，不再调度"
		t.FinishedAt = now
		t.UpdatedAt = now
		_ = app.taskService.Repository().UpdateStatus(t)
		_ = app.taskService.Repository().UpdateRuntime(t)
		return t
	}
	return t
}

func (app *App) StartTask(id string) (task.DTO, error) {
	if err := app.ensureTaskService(); err != nil {
		return task.DTO{}, err
	}
	t, err := app.taskService.Repository().Get(id)
	if err != nil {
		return task.DTO{}, err
	}
	t = app.reconcileTaskStatus(t)
	if t.Status == task.StatusRunning {
		return task.ToDTO(t), nil
	}
	if t.Status != task.StatusCreated && t.Status != task.StatusQueued && t.Status != task.StatusInterrupted && t.Status != task.StatusFailed && t.Status != task.StatusCancelled {
		return task.DTO{}, errors.New("task cannot be started in current status")
	}
	if isHistoricalGovernanceTaskType(t.TaskType) {
		return task.DTO{}, errors.New("非生产治理任务已归档；桌面生产入口只允许启动通用策略训练/推理任务")
	}
	if t.TaskType == task.TypeEvaluationTimeMachine {
		return task.DTO{}, errors.New("历史时间机器验证已只读留档；通用策略生产验证请查看通用策略训练结果和评估表")
	}
	if t.TaskType == task.TypeModelTraining && modelTrainingStrategy(task.ToDTO(t).Params) != profitArenaStrategyID {
		return task.DTO{}, errors.New("该模型训练任务不在桌面生产链路；桌面生产入口只允许启动通用策略训练/推理")
	}
	if t.TaskType == task.TypeModelTraining && modelTrainingStrategy(task.ToDTO(t).Params) == profitArenaStrategyID {
		app.profitArenaTaskMu.Lock()
		defer app.profitArenaTaskMu.Unlock()
		blocker, err := app.activeProfitArenaModelTaskBlocker(t.ID)
		if err != nil {
			return task.DTO{}, err
		}
		if blocker.Count > 0 {
			return task.DTO{}, fmt.Errorf("已有 %d 个通用策略训练/推理任务未完成：%s，请等待完成或到任务中心处理后再启动", blocker.Count, blocker.Label())
		}
	}
	if t.TaskType != task.TypeFactorResearch && t.TaskType != task.TypeModelTraining {
		return task.DTO{}, errors.New("桌面只允许启动通用策略生产任务或因子研究留档任务")
	}
	if err := app.ensureDataQualityForEvaluation(); err != nil {
		return task.DTO{}, err
	}
	app.reconcileStaleEvaluationLocks(10 * time.Minute)
	running, err := app.taskService.Repository().HasRunningEvaluation(t.ID)
	if err != nil {
		return task.DTO{}, err
	}
	if running {
		return task.DTO{}, errors.New("已有离线任务正在运行，同一时间只运行一个重任务")
	}
	if t.TaskType == task.TypeFactorResearch {
		return app.startFactorResearchTask(t)
	}
	if t.TaskType == task.TypeModelTraining {
		return app.startModelTrainingTask(t)
	}
	return task.DTO{}, errors.New("unsupported production task")
}

func (app *App) ensureDataQualityForEvaluation() error {
	if err := app.ensureDatabase(); err != nil {
		return err
	}
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return errors.New("数据目录未配置，请先在设置页确认数据目录")
	}
	if !pathExists(dataPath) {
		return fmt.Errorf("数据目录不存在：%s，请先在数据管理执行数据更新", dataPath)
	}
	if app.database == nil {
		return errors.New("数据库未连接，请重启桌面端后重试")
	}
	for _, tableName := range []string{"data_stock_basic", "data_daily_bars"} {
		if !app.database.TableExists(tableName) {
			return fmt.Errorf("基础数据表 %s 不存在，请先在数据管理执行基础/行情更新", tableName)
		}
	}
	return nil
}

func (app *App) startMarketEvaluationTask(t task.Task) (task.DTO, error) {
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return task.DTO{}, errors.New("数据路径未设置")
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	runID := strings.TrimSpace(t.ExternalRunID)
	if runID == "" {
		runID = strings.ReplaceAll(t.ID, "-", "")
	}
	params := task.ToDTO(t).Params
	params["run_id"] = runID
	statusTask, args, err := marketEvaluationTaskCommand(t.TaskType, dataPath, params)
	if err != nil {
		return task.DTO{}, err
	}
	arenaStrategy := runStatusArenaStrategySummary(statusTask, runID, params)
	runPath := filepath.Join(dataPath, "logs", statusTask, runID)
	if err := os.MkdirAll(runPath, 0o755); err != nil {
		return task.DTO{}, err
	}
	logPath := filepath.Join(runPath, "worker.log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return task.DTO{}, err
	}
	nowText := time.Now().Format(time.RFC3339)
	app.ensureTaskRunStatusArenaColumns()
	runIDValue, strategyIDValue, arenaNameValue, taskKeyValue, taskLabelValue, metadataJSONValue := "", "", "", "", "", ""
	if arenaStrategy != nil {
		runIDValue = strings.TrimSpace(fmt.Sprint(arenaStrategy["run_id"]))
		strategyIDValue = strings.TrimSpace(fmt.Sprint(arenaStrategy["strategy_id"]))
		arenaNameValue = strings.TrimSpace(fmt.Sprint(arenaStrategy["arena_name"]))
		taskKeyValue = strings.TrimSpace(fmt.Sprint(arenaStrategy["task_key"]))
		taskLabelValue = strings.TrimSpace(fmt.Sprint(arenaStrategy["task_label"]))
		if payload, err := json.Marshal(arenaStrategy); err == nil {
			metadataJSONValue = string(payload)
		}
	}
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{
				"task", "task_type", "state", "idx", "total", "stage", "name", "message",
				"run_id", "strategy_id", "arena_name", "task_key", "task_label", "metadata_json",
				"started_at", "updated_at", "finished_at",
			},
			[]string{"task"},
			[]string{
				"task_type", "state", "idx", "total", "stage", "name", "message",
				"run_id", "strategy_id", "arena_name", "task_key", "task_label", "metadata_json",
				"started_at", "updated_at", "finished_at",
			},
		),
		statusTask, runStatusTaskType(statusTask), "running", 1, 100, "prepare", "启动离线任务", "",
		runIDValue, strategyIDValue, arenaNameValue, taskKeyValue, taskLabelValue, metadataJSONValue,
		nowText, nowText, "",
	)
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv()...)...)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		finishedAt := time.Now().Format(time.RFC3339)
		_, _ = app.database.Conn().Exec(
			`UPDATE task_run_status SET state='error', message=?, updated_at=?, finished_at=? WHERE task=?`,
			err.Error(), finishedAt, finishedAt, statusTask,
		)
		return task.DTO{}, err
	}
	now := time.Now()
	t.Status = task.StatusRunning
	t.Progress = 0.02
	t.ResultPath = runPath
	t.LogPath = logPath
	t.SummaryJSON = mustJSON(map[string]any{
		"status_task":    statusTask,
		"stage":          "prepare",
		"name":           "启动离线任务",
		"message":        "",
		"idx":            1,
		"total":          100,
		"arena_strategy": arenaStrategy,
	})
	t.WorkerPID = cmd.Process.Pid
	t.ExternalRunID = runID
	t.ErrorMessage = ""
	t.StartedAt = now
	t.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(t); err != nil {
		_ = worker.NewManager().Cancel(cmd.Process.Pid)
		_ = logFile.Close()
		return task.DTO{}, err
	}
	go app.syncMarketEvaluationTask(t.ID, statusTask, cmd, logFile)
	return task.ToDTO(t), nil
}

func marketEvaluationTaskCommand(taskType task.Type, dataPath string, params map[string]any) (string, []string, error) {
	switch taskType {
	default:
		return "", nil, errors.New("该任务不在桌面生产链路")
	}
}

func (app *App) syncMarketEvaluationTask(taskID string, statusTask string, cmd *exec.Cmd, logFile *os.File) {
	done := make(chan error, 1)
	go func() {
		done <- cmd.Wait()
		_ = logFile.Close()
	}()
	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()
	var waitErr error
	for {
		select {
		case waitErr = <-done:
			app.updateTaskFromRunStatus(taskID, statusTask, waitErr, true)
			return
		case <-ticker.C:
			app.updateTaskFromRunStatus(taskID, statusTask, nil, false)
		}
	}
}

func (app *App) syncRunStatusTaskJobProcess(statusTask string, cmd *exec.Cmd, logFile *os.File, logPath string) {
	done := make(chan error, 1)
	go func() {
		done <- cmd.Wait()
		_ = logFile.Close()
	}()
	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()
	taskID := runStatusTaskJobID(statusTask)
	for {
		select {
		case waitErr := <-done:
			if waitErr != nil {
				app.markPythonStatusTaskError(statusTask, fmt.Sprintf("%s进程失败: %v，日志: %s", runStatusTaskDisplayName(statusTask), waitErr, logPath))
			}
			if err := app.ensureTaskService(); err == nil {
				app.updateTaskFromRunStatus(taskID, statusTask, waitErr, true)
			}
			if waitErr == nil && statusTask == "factor_snapshot" {
				go app.runProfitArenaLatestInferenceAfterFactorSnapshot()
			}
			return
		case <-ticker.C:
			if err := app.ensureTaskService(); err == nil {
				app.updateTaskFromRunStatus(taskID, statusTask, nil, false)
			}
		}
	}
}

func (app *App) runProfitArenaLatestInferenceAfterFactorSnapshot() {
	if app.database == nil {
		return
	}
	run, err := app.bestProfitArenaRunByCurrentScore()
	if err != nil || strings.TrimSpace(run.RunID) == "" {
		return
	}
	if _, err := app.RunProfitArenaLatestInference(); err != nil {
		app.markPythonStatusTaskError(profitArenaStrategyID, "因子快照完成后自动刷新通用策略买入清单失败: "+err.Error())
	}
}

func (app *App) updateTaskFromRunStatus(taskID string, statusTask string, waitErr error, finished bool) {
	if app.taskService == nil || app.database == nil {
		return
	}
	t, err := app.taskService.Repository().Get(taskID)
	if err != nil {
		return
	}
	s, err := app.readRunStatusRow(statusTask)
	if err != nil {
		if finished && waitErr != nil {
			t.Status = task.StatusFailed
			t.Progress = 1
			t.ErrorMessage = waitErr.Error()
			t.WorkerPID = 0
			t.FinishedAt = time.Now()
			t.UpdatedAt = time.Now()
			_ = app.taskService.Repository().UpdateStatus(t)
			_ = app.taskService.Repository().UpdateRuntime(t)
		}
		return
	}
	progress := 0.05
	if s.Total > 0 {
		progress = math.Max(0.02, math.Min(0.98, float64(s.Idx)/float64(s.Total)))
	}
	summary := map[string]any{
		"status_task": s.Task,
		"stage":       s.Stage,
		"name":        s.Name,
		"message":     s.Message,
		"idx":         s.Idx,
		"total":       s.Total,
		"updated_at":  s.UpdatedAt,
	}
	if arenaStrategy := runStatusArenaStrategyFromRow(s); arenaStrategy != nil {
		summary["arena_strategy"] = arenaStrategy
	}
	if observability := runStatusObservabilitySummary(s.Stage, s.Message); len(observability) > 0 {
		if strategy, ok := summary["arena_strategy"]; ok {
			observability["arena_strategy"] = strategy
		}
		summary["observability"] = observability
	}
	payload, _ := json.Marshal(summary)
	t.SummaryJSON = string(payload)
	if strings.TrimSpace(s.Stage) != "" || strings.TrimSpace(s.Name) != "" {
		subtaskKey, subtaskName := runStatusSubtaskLabels(s.Stage, s.Name)
		t.SubtaskKey = subtaskKey
		t.SubtaskName = subtaskName
		_, _ = app.database.Conn().Exec(
			fmt.Sprintf(`UPDATE task_jobs SET subtask_key = ?, subtask_name = ?, updated_at = %s WHERE id = ?`, app.database.CurrentTimestampSQL()),
			t.SubtaskKey, t.SubtaskName, t.ID,
		)
	}
	t.Progress = progress
	t.UpdatedAt = time.Now()
	switch s.State {
	case "done", "success":
		t.Status = task.StatusSuccess
		t.Progress = 1
		t.WorkerPID = 0
		t.FinishedAt = time.Now()
	case "error", "failed":
		t.Status = task.StatusFailed
		t.Progress = 1
		t.WorkerPID = 0
		t.ErrorMessage = s.Message
		t.FinishedAt = time.Now()
	default:
		if finished {
			if waitErr != nil {
				t.Status = task.StatusFailed
				t.ErrorMessage = waitErr.Error()
				finishedAt := time.Now().Format(time.RFC3339)
				_, _ = app.database.Conn().Exec(
					`UPDATE task_run_status SET state='error', message=?, updated_at=?, finished_at=? WHERE task=?`,
					waitErr.Error(), finishedAt, finishedAt, statusTask,
				)
			} else {
				t.Status = task.StatusSuccess
				t.Progress = 1
				finishedAt := time.Now().Format(time.RFC3339)
				message := s.Message
				if strings.TrimSpace(message) == "" {
					message = "离线任务已结束；如果没有截面结果，请先刷新通用策略买入清单生成预测快照"
				}
				_, _ = app.database.Conn().Exec(
					`UPDATE task_run_status SET state='done', idx=100, total=100, stage='done', name='评估完成', message=?, updated_at=?, finished_at=? WHERE task=? AND state NOT IN ('done','success','error','failed')`,
					message, finishedAt, finishedAt, statusTask,
				)
			}
			t.WorkerPID = 0
			t.FinishedAt = time.Now()
		} else {
			t.Status = task.StatusRunning
		}
	}
	_ = app.taskService.Repository().UpdateStatus(t)
	_ = app.taskService.Repository().UpdateRuntime(t)
}

type runStatusRow struct {
	Task         string
	State        string
	Idx          int
	Total        int
	Stage        string
	Name         string
	Message      string
	RunID        string
	StrategyID   string
	ArenaName    string
	TaskKey      string
	TaskLabel    string
	MetadataJSON string
	UpdatedAt    string
}

func (app *App) ensureTaskRunStatusArenaColumns() {
	if app.database == nil || app.database.Conn() == nil {
		return
	}
	columns := map[string]string{
		"run_id":        "TEXT",
		"strategy_id":   "TEXT",
		"arena_name":    "TEXT",
		"task_key":      "TEXT",
		"task_label":    "TEXT",
		"metadata_json": "TEXT",
	}
	for name, ddl := range columns {
		if app.mysqlColumnExists("task_run_status", name) {
			continue
		}
		_, _ = app.database.Conn().Exec(fmt.Sprintf("ALTER TABLE task_run_status ADD COLUMN %s %s", name, ddl))
	}
}

func runStatusObservabilitySummary(stage string, message string) map[string]any {
	tokens := runStatusMessageTokens(message)
	if len(tokens) == 0 {
		return map[string]any{}
	}
	out := map[string]any{}
	if value, ok := tokens["buy_plan"]; ok {
		out["buy_plan_status"] = value
	}
	if hasAnyToken(tokens, "capacity_pass", "capacity_warn", "capacity_fail") {
		out["capacity"] = map[string]any{
			"pass_count": tokenInt(tokens, "capacity_pass"),
			"warn_count": tokenInt(tokens, "capacity_warn"),
			"fail_count": tokenInt(tokens, "capacity_fail"),
		}
	}
	if status, ok := tokens["portfolio_status"]; ok {
		out["portfolio_risk"] = map[string]any{
			"status":     status,
			"fail_count": tokenInt(tokens, "portfolio_fail"),
			"warn_count": tokenInt(tokens, "portfolio_warn"),
		}
	}
	if hasAnyToken(tokens, "gate_pass", "gate_fail") {
		out["hard_gate"] = map[string]any{
			"pass_count": tokenInt(tokens, "gate_pass"),
			"fail_count": tokenInt(tokens, "gate_fail"),
			"final":      strings.TrimSpace(stage) == "done",
		}
	}
	if hasAnyToken(tokens, "done", "total", "eta", "best_score", "gate_pass") {
		out["evaluation_grid"] = map[string]any{
			"done":             tokenInt(tokens, "done"),
			"total":            tokenInt(tokens, "total"),
			"eta_seconds":      tokenFloat(tokens, "eta"),
			"gate_pass_count":  tokenInt(tokens, "gate_pass"),
			"best_arena_score": tokenFloat(tokens, "best_score"),
		}
	}
	if hasAnyToken(tokens, "quality", "drift", "rows", "factors") {
		factorSnapshot := map[string]any{}
		if value, ok := tokens["quality"]; ok {
			factorSnapshot["quality_status"] = value
		}
		if value, ok := tokens["drift"]; ok {
			factorSnapshot["drift_status"] = value
		}
		if hasAnyToken(tokens, "rows") {
			factorSnapshot["row_count"] = tokenInt(tokens, "rows")
		}
		if hasAnyToken(tokens, "factors") {
			factorSnapshot["factor_count"] = tokenInt(tokens, "factors")
		}
		if value, ok := tokens["manifest"]; ok {
			factorSnapshot["manifest_path"] = value
		}
		out["factor_snapshot"] = factorSnapshot
	}
	return out
}

func runStatusArenaStrategyFromRow(s runStatusRow) map[string]any {
	metadataText := strings.TrimSpace(s.MetadataJSON)
	if metadataText != "" {
		var metadata map[string]any
		if err := json.Unmarshal([]byte(metadataText), &metadata); err == nil && len(metadata) > 0 {
			return metadata
		}
	}
	if strings.TrimSpace(s.StrategyID) == "" && strings.TrimSpace(s.TaskKey) == "" {
		return nil
	}
	return map[string]any{
		"run_id":      s.RunID,
		"strategy_id": s.StrategyID,
		"arena_name":  s.ArenaName,
		"task_key":    s.TaskKey,
		"task_label":  s.TaskLabel,
	}
}

func runStatusMessageTokens(message string) map[string]string {
	out := map[string]string{}
	for _, field := range strings.Fields(message) {
		key, value, ok := strings.Cut(field, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		value = strings.Trim(strings.TrimSpace(value), ",;")
		if key != "" && value != "" {
			out[key] = value
		}
	}
	return out
}

func hasAnyToken(tokens map[string]string, keys ...string) bool {
	for _, key := range keys {
		if _, ok := tokens[key]; ok {
			return true
		}
	}
	return false
}

func tokenInt(tokens map[string]string, key string) int {
	value, ok := tokens[key]
	if !ok {
		return 0
	}
	parsed, _ := strconv.Atoi(strings.TrimSpace(value))
	return parsed
}

func tokenFloat(tokens map[string]string, key string) float64 {
	value, ok := tokens[key]
	if !ok {
		return 0
	}
	parsed, _ := strconv.ParseFloat(strings.TrimSpace(value), 64)
	return parsed
}

func runStatusSubtaskLabels(stage string, name string) (string, string) {
	subtaskKey := strings.TrimSpace(stage)
	subtaskName := strings.TrimSpace(name)
	if subtaskKey == "" {
		subtaskKey = subtaskName
	}
	if subtaskName == "" {
		subtaskName = subtaskKey
	}
	return subtaskKey, subtaskName
}

func (app *App) readRunStatusRow(statusTask string) (runStatusRow, error) {
	app.ensureTaskRunStatusArenaColumns()
	row := app.database.Conn().QueryRow(
		`SELECT task, state, idx, total, COALESCE(stage,''), COALESCE(name,''), COALESCE(message,''),
		 COALESCE(run_id,''), COALESCE(strategy_id,''), COALESCE(arena_name,''), COALESCE(task_key,''), COALESCE(task_label,''), COALESCE(metadata_json,''), updated_at
		FROM task_run_status WHERE task = ?`,
		statusTask,
	)
	var out runStatusRow
	err := row.Scan(
		&out.Task, &out.State, &out.Idx, &out.Total, &out.Stage, &out.Name, &out.Message,
		&out.RunID, &out.StrategyID, &out.ArenaName, &out.TaskKey, &out.TaskLabel, &out.MetadataJSON, &out.UpdatedAt,
	)
	return out, err
}

func (app *App) RetryTask(id string) (task.DTO, error) {
	if err := app.ensureTaskService(); err != nil {
		return task.DTO{}, err
	}
	t, err := app.taskService.Repository().Get(id)
	if err != nil {
		return task.DTO{}, err
	}
	if t.ParentID == "" {
		return app.StartTask(id)
	}
	if t.Status == task.StatusRunning {
		return task.ToDTO(t), nil
	}
	if isHistoricalGovernanceTaskType(t.TaskType) {
		return task.DTO{}, errors.New("历史治理/组合优化任务已下线，不能重跑；请使用通用策略训练/推理任务")
	}
	if t.TaskType != task.TypeFactorResearch && t.TaskType != task.TypeModelTraining {
		return task.DTO{}, errors.New("task cannot be retried")
	}
	if err := app.ensureDataQualityForEvaluation(); err != nil {
		return task.DTO{}, err
	}
	parent, err := app.taskService.Repository().Get(t.ParentID)
	if err != nil {
		return task.DTO{}, err
	}
	parentAlreadyRunning := parent.Status == task.StatusRunning
	if !parentAlreadyRunning {
		running, err := app.taskService.Repository().HasRunningEvaluation(t.ID)
		if err != nil {
			return task.DTO{}, err
		}
		if running {
			return task.DTO{}, errors.New("已有离线任务正在运行，同一时间只运行一个重任务")
		}
	}
	app.reconcileOrphanRunningChildren(parent.ID)
	now := time.Now()
	t.Status = task.StatusCreated
	t.Progress = 0
	t.WorkerPID = 0
	t.ErrorMessage = ""
	t.SummaryJSON = ""
	t.QueuedAt = now
	t.StartedAt = time.Time{}
	t.FinishedAt = time.Time{}
	t.UpdatedAt = now
	if err := app.taskService.Repository().UpdateRuntime(t); err != nil {
		return task.DTO{}, err
	}
	if err := app.taskService.Repository().UpdateStatus(t); err != nil {
		return task.DTO{}, err
	}
	children, _ := app.taskService.Repository().ListChildren(parent.ID)
	parent.Status = task.StatusRunning
	parent.Progress = portfolioParentProgress(children)
	parent.ErrorMessage = ""
	parent.FinishedAt = time.Time{}
	parent.UpdatedAt = now
	if t.TaskType == task.TypeFactorResearch {
		parent.SummaryJSON = app.factorResearchSummaryForParent(parent, children)
	} else if t.TaskType == task.TypeModelTraining {
		parent.SummaryJSON = app.modelTrainingSummaryForParent(parent, children)
	}
	_ = app.taskService.Repository().UpdateStatus(parent)
	_ = app.taskService.Repository().UpdateRuntime(parent)
	if t.TaskType == task.TypeFactorResearch {
		go app.runFactorResearchChildren(parent)
	} else if t.TaskType == task.TypeModelTraining {
		go app.runModelTrainingChildren(parent)
	}

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

func isHistoricalGovernanceTaskType(taskType task.Type) bool {
	switch string(taskType) {
	case "eval_strategy_admission", "portfolio_optimization", "walk_forward_evaluation", "parameter_experiment":
		return true
	default:
		return false
	}
}

func (app *App) startFactorResearchTask(t task.Task) (task.DTO, error) {
	if t.ParentID != "" {
		return app.RetryTask(t.ID)
	}
	children, err := app.taskService.Repository().ListChildren(t.ID)
	if err != nil {
		return task.DTO{}, err
	}
	if len(children) == 0 {
		if err := app.initializeFactorResearch(t); err != nil {
			return task.DTO{}, err
		}
		children, err = app.taskService.Repository().ListChildren(t.ID)
		if err != nil {
			return task.DTO{}, err
		}
	} else if err := app.ensureFactorResearchStages(t, children); err != nil {
		return task.DTO{}, err
	} else {
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
	go app.runFactorResearchChildren(t)
	return task.ToDTO(t), nil
}

func (app *App) startModelTrainingTask(t task.Task) (task.DTO, error) {
	if t.ParentID != "" {
		return app.RetryTask(t.ID)
	}
	params := task.ToDTO(t).Params
	if modelTrainingStrategy(params) == profitArenaStrategyID {
		endDate := stringParam(params, "end_date", app.latestDailyBarTradeDateOrToday())
		if err := app.ensureProfitArenaFactorSnapshotReady(endDate); err != nil {
			now := time.Now()
			t.Status = task.StatusFailed
			t.Progress = 0
			t.WorkerPID = 0
			t.ErrorMessage = err.Error()
			t.FinishedAt = now
			t.UpdatedAt = now
			_ = app.taskService.Repository().UpdateStatus(t)
			_ = app.taskService.Repository().UpdateRuntime(t)
			return task.ToDTO(t), err
		}
	}
	children, err := app.taskService.Repository().ListChildren(t.ID)
	if err != nil {
		return task.DTO{}, err
	}
	if len(children) == 0 {
		if err := app.initializeModelTraining(t); err != nil {
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
	go app.runModelTrainingChildren(t)
	return task.ToDTO(t), nil
}

func (app *App) runFactorResearchChildren(parent task.Task) {
	app.schedulerMu.Lock()
	defer app.schedulerMu.Unlock()
	for {
		latestParent, err := app.taskService.Repository().Get(parent.ID)
		if err != nil {
			app.finishFactorResearchParent(parent, task.StatusFailed, err.Error(), nil)
			return
		}
		if latestParent.Status != task.StatusRunning {
			return
		}
		parent = latestParent
		app.reconcileOrphanRunningChildren(parent.ID)
		children, err := app.taskService.Repository().ListChildren(parent.ID)
		if err != nil {
			app.finishFactorResearchParent(parent, task.StatusFailed, err.Error(), children)
			return
		}
		next, blockedByFailedStage := nextFactorResearchChild(children)
		if next.ID == "" {
			if blockedByFailedStage {
				app.finishFactorResearchParent(parent, task.StatusFailed, "前置研究阶段失败", children)
				return
			}
			status := portfolioParentStatus(children)
			if status != task.StatusRunning {
				app.finishFactorResearchParent(parent, status, "", children)
				return
			}
			parent.Progress = portfolioParentProgress(children)
			parent.SummaryJSON = app.factorResearchSummaryForParent(parent, children)
			parent.UpdatedAt = time.Now()
			_ = app.taskService.Repository().UpdateStatus(parent)
			_ = app.taskService.Repository().UpdateRuntime(parent)
			time.Sleep(1 * time.Second)
			continue
		}
		next.Status = task.StatusQueued
		next.UpdatedAt = time.Now()
		_ = app.taskService.Repository().UpdateStatus(next)
		_ = app.taskService.Repository().UpdateRuntime(next)
		updated, err := app.startFactorResearchChildTaskSync(next)
		if err != nil {
			if updated.ID == "" {
				updated = next
			}
			app.markChildTaskFailed(updated, err)
		}
		children, _ = app.taskService.Repository().ListChildren(parent.ID)
		parent.Progress = portfolioParentProgress(children)
		parent.SummaryJSON = app.factorResearchSummaryForParent(parent, children)
		parent.UpdatedAt = time.Now()
		_ = app.taskService.Repository().UpdateStatus(parent)
		_ = app.taskService.Repository().UpdateRuntime(parent)
	}
}

func (app *App) startFactorResearchChildTaskSync(t task.Task) (task.Task, error) {
	runID := t.ExternalRunID
	if runID == "" {
		runID = t.GroupRunID
	}
	if runID == "" {
		return t, errors.New("factor research child requires run id")
	}
	params := task.ToDTO(t).Params
	stage := stringParam(params, "stage", t.SubtaskKey)
	startDate := stringParam(params, "start_date", "")
	endDate := stringParam(params, "end_date", "")
	if stage == "" || startDate == "" || endDate == "" {
		return t, errors.New("factor research child requires stage, start_date and end_date")
	}
	runPath := filepath.Join(app.settings.DataPath, "factor_research", runID, stage)
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
	args := factorResearchStageCommandArgs(runID, stage, startDate, endDate, params)
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + app.settings.DataPath}, app.pythonDBEnv()...)...)
	cmd.Env = append(cmd.Env, factorResearchStageEnv(runID, stage, params)...)
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
	done := make(chan struct{})
	progressStopped := make(chan struct{})
	go func() {
		defer close(progressStopped)
		app.pollFactorResearchChildProgress(t, runID, stage, done)
	}()
	waitErr := cmd.Wait()
	close(done)
	<-progressStopped
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
	t.SummaryJSON = readFactorResearchStageSummaryFromDB(app.database.Conn(), runID, stage)
	_ = app.taskService.Repository().UpdateRuntime(t)
	if t.SummaryJSON != "" {
		_ = app.taskService.Repository().UpdateStatus(t)
	}
	return t, nil
}

func (app *App) pollFactorResearchChildProgress(t task.Task, runID string, stage string, done <-chan struct{}) {
	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-done:
			return
		case <-ticker.C:
			progress, summary, ok := app.factorResearchStageProgress(runID, stage)
			if !ok {
				continue
			}
			if progress <= t.Progress {
				progress = t.Progress
			}
			if progress >= 1 {
				progress = 0.99
			}
			t.Progress = progress
			t.SummaryJSON = summary
			t.UpdatedAt = time.Now()
			_ = app.taskService.Repository().UpdateStatus(t)
		}
	}
}

func (app *App) factorResearchStageProgress(runID string, stage string) (float64, string, bool) {
	if app.database == nil || app.database.Conn() == nil {
		return 0, "", false
	}
	row := app.database.Conn().QueryRow(`
		SELECT COALESCE(summary_json, '')
		FROM factor_research_stage_results
		WHERE run_id = ? AND stage = ? AND status = 'running'`, runID, stage)
	var summary string
	if err := row.Scan(&summary); err != nil || strings.TrimSpace(summary) == "" {
		return 0, "", false
	}
	payload := map[string]any{}
	if err := json.Unmarshal([]byte(summary), &payload); err != nil {
		return 0, summary, false
	}
	progress := numberParam(payload, "progress", 0)
	if progress <= 0 {
		return 0, summary, false
	}
	return progress, summary, true
}

func (app *App) factorResearchSummaryForParent(parent task.Task, children []task.Task) string {
	summary := ""
	if app.database != nil && app.database.Conn() != nil && parent.ExternalRunID != "" {
		summary = readFactorResearchSummaryFromDB(app.database.Conn(), parent.ExternalRunID)
	}
	payload := map[string]any{}
	if summary != "" {
		_ = json.Unmarshal([]byte(summary), &payload)
	} else if parent.SummaryJSON != "" {
		_ = json.Unmarshal([]byte(parent.SummaryJSON), &payload)
	}
	childRows := make([]any, 0, len(children))
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
		row := map[string]any{
			"stage":       child.SubtaskKey,
			"stage_name":  child.SubtaskName,
			"task_status": child.Status,
			"progress":    child.Progress,
			"sequence":    child.Sequence,
			"total":       child.Total,
			"error":       child.ErrorMessage,
			"result_path": child.ResultPath,
			"log_path":    child.LogPath,
		}
		if child.SummaryJSON != "" {
			var childSummary map[string]any
			if json.Unmarshal([]byte(child.SummaryJSON), &childSummary) == nil {
				for key, value := range childSummary {
					row[key] = value
				}
			}
		}
		childRows = append(childRows, row)
	}
	payload["planned_count"] = len(children)
	payload["completed_count"] = successChildren
	payload["failed_task_count"] = failedChildren
	payload["running_count"] = runningChildren
	payload["progress"] = portfolioParentProgress(children)
	if len(childRows) > 0 {
		payload["rows"] = childRows
	}
	out, err := json.Marshal(payload)
	if err != nil {
		return parent.SummaryJSON
	}
	return string(out)
}

func (app *App) finishFactorResearchParent(parent task.Task, status task.Status, message string, children []task.Task) {
	now := time.Now()
	app.releaseChildSlotsForParent(parent.ID)
	parent.Status = status
	parent.Progress = portfolioParentProgress(children)
	if status == task.StatusSuccess {
		parent.Progress = 1
	}
	parent.WorkerPID = 0
	parent.ErrorMessage = message
	parent.SummaryJSON = app.factorResearchSummaryForParent(parent, children)
	parent.FinishedAt = now
	parent.UpdatedAt = now
	_ = app.taskService.Repository().UpdateStatus(parent)
	_ = app.taskService.Repository().UpdateRuntime(parent)
}

func (app *App) runModelTrainingChildren(parent task.Task) {
	app.schedulerMu.Lock()
	defer app.schedulerMu.Unlock()
	for {
		latestParent, err := app.taskService.Repository().Get(parent.ID)
		if err != nil {
			app.finishModelTrainingParent(parent, task.StatusFailed, err.Error(), nil)
			return
		}
		if latestParent.Status != task.StatusRunning {
			return
		}
		parent = latestParent
		app.reconcileOrphanRunningChildren(parent.ID)
		children, err := app.taskService.Repository().ListChildren(parent.ID)
		if err != nil {
			app.finishModelTrainingParent(parent, task.StatusFailed, err.Error(), children)
			return
		}
		next, blockedByFailedStage := nextFactorResearchChild(children)
		if next.ID == "" {
			if blockedByFailedStage {
				app.finishModelTrainingParent(parent, task.StatusFailed, "前置训练阶段失败", children)
				return
			}
			status := portfolioParentStatus(children)
			if status != task.StatusRunning {
				app.finishModelTrainingParent(parent, status, "", children)
				return
			}
			parent.Progress = portfolioParentProgress(children)
			parent.SummaryJSON = app.modelTrainingSummaryForParent(parent, children)
			parent.UpdatedAt = time.Now()
			_ = app.taskService.Repository().UpdateStatus(parent)
			_ = app.taskService.Repository().UpdateRuntime(parent)
			time.Sleep(1 * time.Second)
			continue
		}
		next.Status = task.StatusQueued
		next.UpdatedAt = time.Now()
		_ = app.taskService.Repository().UpdateStatus(next)
		_ = app.taskService.Repository().UpdateRuntime(next)
		updated, err := app.startModelTrainingChildTaskSync(next)
		if err != nil {
			if updated.ID == "" {
				updated = next
			}
			app.markChildTaskFailed(updated, err)
		}
		children, _ = app.taskService.Repository().ListChildren(parent.ID)
		parent.Progress = portfolioParentProgress(children)
		parent.SummaryJSON = app.modelTrainingSummaryForParent(parent, children)
		parent.UpdatedAt = time.Now()
		_ = app.taskService.Repository().UpdateStatus(parent)
		_ = app.taskService.Repository().UpdateRuntime(parent)
	}
}

func (app *App) startModelTrainingChildTaskSync(t task.Task) (task.Task, error) {
	runID := t.ExternalRunID
	if runID == "" {
		runID = t.GroupRunID
	}
	if runID == "" {
		return t, errors.New("model training child requires run id")
	}
	params := task.ToDTO(t).Params
	strategy := modelTrainingStrategy(params)
	stage := stringParam(params, "stage", t.SubtaskKey)
	if strategy == "" || stage == "" {
		return t, errors.New("model training child requires strategy and stage")
	}
	if strategy == profitArenaStrategyID {
		endDate := stringParam(params, "end_date", app.latestDailyBarTradeDateOrToday())
		if err := app.ensureProfitArenaFactorSnapshotReady(endDate); err != nil {
			return t, err
		}
	}
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return t, errors.New("数据路径未设置")
	}
	runPath := filepath.Join(dataPath, "model_training", strategy, runID, stage)
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
	args, err := modelTrainingStageCommandArgs(strategy, runID, stage, dataPath, params)
	if err != nil {
		_ = logFile.Close()
		return t, err
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv()...)...)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		return t, err
	}
	now := time.Now()
	t.Status = task.StatusRunning
	t.Progress = 0.02
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
	done := make(chan struct{})
	progressStopped := make(chan struct{})
	go func() {
		defer close(progressStopped)
		app.pollModelTrainingChildProgress(t, strategy, runID, stage, done)
	}()
	waitErr := cmd.Wait()
	close(done)
	<-progressStopped
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
	t.SummaryJSON = app.modelTrainingStageSummary(strategy, runID, stage)
	_ = app.taskService.Repository().UpdateRuntime(t)
	if t.SummaryJSON != "" {
		_ = app.taskService.Repository().UpdateStatus(t)
	}
	if stage == "validate_model_run" {
		app.activateBestStrategyModelRun(strategy)
	}
	return t, nil
}

func (app *App) pollModelTrainingChildProgress(t task.Task, strategy string, runID string, stage string, done <-chan struct{}) {
	ticker := time.NewTicker(1 * time.Second)
	defer ticker.Stop()
	statusTask := modelTrainingStatusTask(strategy)
	for {
		select {
		case <-done:
			return
		case <-ticker.C:
			progress := t.Progress
			summary := ""
			if stage == "train_model" {
				if row, err := app.readRunStatusRow(statusTask); err == nil && row.Total > 0 {
					progress = math.Max(0.02, math.Min(0.98, float64(row.Idx)/float64(row.Total)))
					summary = mustJSON(map[string]any{
						"strategy":    strategy,
						"run_id":      runID,
						"stage":       stage,
						"status_task": row.Task,
						"name":        row.Name,
						"message":     row.Message,
						"idx":         row.Idx,
						"total":       row.Total,
						"updated_at":  row.UpdatedAt,
					})
				}
			} else if summary = app.modelTrainingStageSummary(strategy, runID, stage); summary != "" {
				progress = 0.9
			}
			if progress <= t.Progress {
				progress = t.Progress
			}
			if progress >= 1 {
				progress = 0.99
			}
			t.Progress = progress
			if summary != "" {
				t.SummaryJSON = summary
			}
			t.UpdatedAt = time.Now()
			_ = app.taskService.Repository().UpdateStatus(t)
		}
	}
}

func (app *App) modelTrainingStageSummary(strategy string, runID string, stage string) string {
	if app.database == nil || app.database.Conn() == nil {
		return ""
	}
	if stage == "validate_model_run" {
		return readSummaryJSON(app.database.Conn(), `SELECT summary_json FROM strategy_model_validation_results WHERE strategy = ? AND run_id = ?`, strategy, runID)
	}
	switch strategy {
	case profitArenaStrategyID:
		return readSummaryJSON(app.database.Conn(), `SELECT summary_json FROM profit_arena_runs WHERE run_id = ?`, runID)
	default:
		return ""
	}
}

func (app *App) modelTrainingSummaryForParent(parent task.Task, children []task.Task) string {
	payload := map[string]any{}
	if parent.SummaryJSON != "" {
		_ = json.Unmarshal([]byte(parent.SummaryJSON), &payload)
	}
	childRows := make([]any, 0, len(children))
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
		row := map[string]any{
			"stage":       child.SubtaskKey,
			"stage_name":  child.SubtaskName,
			"task_status": child.Status,
			"progress":    child.Progress,
			"sequence":    child.Sequence,
			"total":       child.Total,
			"error":       child.ErrorMessage,
			"result_path": child.ResultPath,
			"log_path":    child.LogPath,
		}
		if child.SummaryJSON != "" {
			var childSummary map[string]any
			if json.Unmarshal([]byte(child.SummaryJSON), &childSummary) == nil {
				for key, value := range childSummary {
					row[key] = value
				}
			}
		}
		childRows = append(childRows, row)
	}
	payload["planned_count"] = len(children)
	payload["completed_count"] = successChildren
	payload["failed_task_count"] = failedChildren
	payload["running_count"] = runningChildren
	payload["progress"] = portfolioParentProgress(children)
	if len(childRows) > 0 {
		payload["rows"] = childRows
	}
	out, err := json.Marshal(payload)
	if err != nil {
		return parent.SummaryJSON
	}
	return string(out)
}

func (app *App) finishModelTrainingParent(parent task.Task, status task.Status, message string, children []task.Task) {
	now := time.Now()
	app.releaseChildSlotsForParent(parent.ID)
	parent.Status = status
	parent.Progress = portfolioParentProgress(children)
	if status == task.StatusSuccess {
		parent.Progress = 1
	}
	parent.WorkerPID = 0
	parent.ErrorMessage = message
	parent.SummaryJSON = app.modelTrainingSummaryForParent(parent, children)
	parent.FinishedAt = now
	parent.UpdatedAt = now
	_ = app.taskService.Repository().UpdateStatus(parent)
	_ = app.taskService.Repository().UpdateRuntime(parent)
}

func runnablePortfolioChildren(children []task.Task, limit int) []task.Task {
	if limit <= 0 {
		limit = 1
	}
	out := make([]task.Task, 0, limit)
	for idx := range children {
		child := children[idx]
		if child.Status == task.StatusSuccess || child.Status == task.StatusRunning || child.Status == task.StatusQueued || child.Status == task.StatusCancelled || child.Status == task.StatusInterrupted {
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

func nextFactorResearchChild(children []task.Task) (task.Task, bool) {
	for idx := range children {
		child := children[idx]
		switch child.Status {
		case task.StatusSuccess:
			continue
		case task.StatusRunning, task.StatusQueued, task.StatusCancelled, task.StatusInterrupted:
			return task.Task{}, false
		case task.StatusFailed:
			if child.MaxAttempts <= 0 || child.Attempt < child.MaxAttempts {
				return child, false
			}
			return task.Task{}, true
		default:
			return child, false
		}
	}
	return task.Task{}, false
}

func (app *App) reconcileOrphanRunningChildren(parentID string) {
	children, err := app.taskService.Repository().ListChildren(parentID)
	if err != nil {
		return
	}
	now := time.Now()
	for _, child := range children {
		if child.Status != task.StatusRunning || child.WorkerPID <= 0 || processExists(child.WorkerPID) {
			continue
		}
		child.Status = task.StatusInterrupted
		child.Progress = 1
		child.WorkerPID = 0
		child.ErrorMessage = "worker process is no longer running"
		child.FinishedAt = now
		child.UpdatedAt = now
		_ = app.taskService.Repository().UpdateStatus(child)
		_ = app.taskService.Repository().UpdateRuntime(child)
		app.releaseChildSlotForTask(child.ID)
	}
}

func (app *App) reconcileProductionWorkerProcesses() {
	if app.database == nil || app.database.Conn() == nil {
		return
	}
	rows, err := app.database.Conn().Query(`
		SELECT id, worker_pid
		FROM task_jobs
		WHERE status = ? AND COALESCE(worker_pid, 0) > 0`,
		task.StatusRunning,
	)
	if err != nil {
		return
	}
	active := map[int]string{}
	for rows.Next() {
		var id string
		var pid int
		if err := rows.Scan(&id, &pid); err == nil && pid > 0 {
			active[pid] = id
		}
	}
	_ = rows.Close()

	osWorkers := productionWorkerPIDs()
	now := time.Now().Format(time.RFC3339)
	for pid, id := range active {
		if osWorkers[pid] {
			continue
		}
		_, _ = app.database.Conn().Exec(`
			UPDATE task_jobs
			SET status = ?, progress = 1, worker_pid = NULL,
				error_message = ?, finished_at = ?, updated_at = ?
			WHERE id = ? AND status = ?`,
			task.StatusInterrupted,
			"worker process is no longer running",
			now,
			now,
			id,
			task.StatusRunning,
		)
	}

	for pid := range osWorkers {
		if _, ok := active[pid]; ok {
			continue
		}
		_ = worker.NewManager().Cancel(pid)
	}
}

func (app *App) reconcileStaleEvaluationLocks(maxIdle time.Duration) {
	app.reconcileProductionWorkerProcesses()
	if app.taskService == nil {
		return
	}
	items, err := app.taskService.Repository().List(task.Query{Limit: 1000})
	if err != nil {
		return
	}
	now := time.Now()
	for _, item := range items {
		if item.ParentID != "" || item.Status != task.StatusRunning || item.WorkerPID > 0 || !isProductionRuntimeTask(item) {
			continue
		}
		if maxIdle > 0 && !item.UpdatedAt.IsZero() && now.Sub(item.UpdatedAt) <= maxIdle {
			continue
		}
		children, err := app.taskService.Repository().ListChildren(item.ID)
		if err != nil {
			continue
		}
		hasActiveChild := false
		for _, child := range children {
			if child.Status == task.StatusQueued {
				hasActiveChild = true
				break
			}
			if child.Status == task.StatusRunning && (child.WorkerPID <= 0 || processExists(child.WorkerPID)) {
				hasActiveChild = true
				break
			}
		}
		if hasActiveChild {
			continue
		}
		item.Status = task.StatusInterrupted
		item.WorkerPID = 0
		item.ErrorMessage = "no active child task is running"
		item.FinishedAt = now
		item.UpdatedAt = now
		_ = app.taskService.Repository().UpdateStatus(item)
		_ = app.taskService.Repository().UpdateRuntime(item)
	}
}

func isProductionRuntimeTask(item task.Task) bool {
	switch item.TaskType {
	case task.TypeFactorResearch, task.TypeFactorSnapshot:
		return true
	case task.TypeModelTraining:
		return strings.Contains(item.ParamsJSON, "profit_arena")
	default:
		return false
	}
}

func productionWorkerPIDs() map[int]bool {
	out := map[int]bool{}
	cmd := exec.Command("ps", "-axo", "pid=,command=")
	data, err := cmd.Output()
	if err != nil {
		return out
	}
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		parts := strings.Fields(line)
		if len(parts) < 2 {
			continue
		}
		pid, err := strconv.Atoi(parts[0])
		if err != nil || pid <= 0 || pid == os.Getpid() {
			continue
		}
		if strings.Contains(line, "scripts/profit_arena_worker.py") ||
			strings.Contains(line, "scripts/factor_snapshot_worker.py") ||
			strings.Contains(line, "scripts/factor_research_worker.py") ||
			strings.Contains(line, "scripts/data_update_worker.py") {
			out[pid] = true
		}
	}
	return out
}

func hasLiveRunningChild(children []task.Task) bool {
	for _, child := range children {
		if child.Status == task.StatusRunning && child.WorkerPID > 0 && processExists(child.WorkerPID) {
			return true
		}
	}
	return false
}

func hasRunnableChild(children []task.Task) bool {
	return len(runnablePortfolioChildren(children, 1)) > 0
}

func (app *App) availableChildSlots(children []task.Task) int {
	limit := app.taskConcurrency()
	if limit <= 0 {
		limit = 1
	}
	running := 0
	for _, child := range children {
		if child.Status == task.StatusRunning || child.Status == task.StatusQueued {
			running++
		}
	}
	slots := limit - running
	if slots < 0 {
		return 0
	}
	return slots
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

func (app *App) startChildTaskBatch(children []task.Task, runner func(task.Task) (task.Task, error)) {
	for _, child := range children {
		child := child
		lockName, acquired, err := app.tryAcquireChildSlot(child.ParentID, child.ID)
		if err != nil {
			app.markChildTaskFailed(child, err)
			continue
		}
		if !acquired {
			continue
		}
		child.Status = task.StatusQueued
		child.UpdatedAt = time.Now()
		_ = app.taskService.Repository().UpdateStatus(child)
		_ = app.taskService.Repository().UpdateRuntime(child)
		go func() {
			defer app.releaseChildSlot(lockName)
			updated, err := runner(child)
			if err != nil {
				if updated.ID == "" {
					updated = child
				}
				app.markChildTaskFailed(updated, err)
			}
		}()
	}
}

func (app *App) tryAcquireChildSlot(parentID string, childID string) (string, bool, error) {
	if app.database == nil || app.database.Conn() == nil {
		return "", false, errors.New("database is not initialized")
	}
	parentID = strings.TrimSpace(parentID)
	childID = strings.TrimSpace(childID)
	if parentID == "" || childID == "" {
		return "", false, errors.New("child slot requires parent and child id")
	}
	if err := app.cleanupChildSlotLocks(parentID); err != nil {
		return "", false, err
	}
	limit := app.taskConcurrency()
	if limit <= 0 {
		limit = 1
	}
	now := time.Now().Format(time.RFC3339)
	hostname, _ := os.Hostname()
	if hostname == "" {
		hostname = "local"
	}
	insertSQL := app.database.InsertIgnoreSQL("task_run_locks", []string{"name", "pid", "hostname", "acquired_at", "heartbeat", "task"})
	for slot := 1; slot <= limit; slot++ {
		lockName := childSlotLockName(parentID, slot)
		result, err := app.database.Conn().Exec(insertSQL, lockName, 0, hostname, now, now, childID)
		if err != nil {
			return "", false, err
		}
		affected, _ := result.RowsAffected()
		if affected > 0 {
			return lockName, true, nil
		}
	}
	return "", false, nil
}

func (app *App) cleanupChildSlotLocks(parentID string) error {
	parentID = strings.TrimSpace(parentID)
	if parentID == "" || app.database == nil || app.database.Conn() == nil {
		return nil
	}
	prefix := childSlotLockPrefix(parentID) + "%"
	_, err := app.database.Conn().Exec(`
		DELETE FROM task_run_locks
		WHERE name LIKE ?
		  AND (
			task IS NULL
			OR task = ''
			OR task NOT IN (
				SELECT id FROM task_jobs
				WHERE parent_id = ? AND status IN ('queued', 'running')
			)
		  )`,
		prefix,
		parentID,
	)
	return err
}

func (app *App) releaseChildSlot(lockName string) {
	lockName = strings.TrimSpace(lockName)
	if lockName == "" || app.database == nil || app.database.Conn() == nil {
		return
	}
	_, _ = app.database.Conn().Exec(`DELETE FROM task_run_locks WHERE name = ?`, lockName)
}

func (app *App) releaseChildSlotsForParent(parentID string) {
	parentID = strings.TrimSpace(parentID)
	if parentID == "" || app.database == nil || app.database.Conn() == nil {
		return
	}
	_, _ = app.database.Conn().Exec(`DELETE FROM task_run_locks WHERE name LIKE ?`, childSlotLockPrefix(parentID)+"%")
}

func (app *App) releaseChildSlotForTask(taskID string) {
	taskID = strings.TrimSpace(taskID)
	if taskID == "" || app.database == nil || app.database.Conn() == nil {
		return
	}
	_, _ = app.database.Conn().Exec(`DELETE FROM task_run_locks WHERE name LIKE 'eval_child_slot:%' AND task = ?`, taskID)
}

func childSlotLockPrefix(parentID string) string {
	return "eval_child_slot:" + parentID + ":"
}

func childSlotLockName(parentID string, slot int) string {
	return fmt.Sprintf("%s%d", childSlotLockPrefix(parentID), slot)
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
	app.releaseChildSlotForTask(child.ID)
}

func (app *App) taskConcurrency() int {
	if app.database != nil {
		app.configService.WithDatabase(app.database)
		if settings, err := app.configService.Load(app.settings); err == nil {
			app.settings = settings
		}
	}
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
	if isHistoricalGovernanceTaskType(t.TaskType) || (t.TaskType == task.TypeModelTraining && modelTrainingStrategy(task.ToDTO(t).Params) != profitArenaStrategyID) {
		return task.DTO{}, errors.New("非生产任务已归档且只读保留，不能取消；请使用通用策略生产任务")
	}

	if t.WorkerPID > 0 {
		_ = worker.NewManager().Cancel(t.WorkerPID)
	}

	// 取消状态由 Python SIGTERM handler 写入 MySQL。Go 只负责发取消信号。
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
		filepath.Join(mustGetwd(), "quant_stock_core"),
		filepath.Join(mustGetwd(), "..", "quant_stock_core"),
	}
	if exe, err := os.Executable(); err == nil {
		if resolved, err := filepath.EvalSymlinks(exe); err == nil {
			exe = resolved
		}
		for _, candidate := range quantCoreCandidatesFrom(filepath.Dir(exe)) {
			candidates = append(candidates, candidate)
		}
	}
	candidates = append(candidates, quantCoreCandidatesFrom(mustGetwd())...)
	for _, candidate := range candidates {
		clean := filepath.Clean(candidate)
		if isQuantCoreRoot(clean) {
			return clean
		}
	}
	return filepath.Clean(filepath.Join(filepath.Dir(app.settings.DataPath), "quant_stock_core"))
}

func quantCoreCandidatesFrom(base string) []string {
	out := make([]string, 0, 10)
	seen := map[string]bool{}
	dir := filepath.Clean(base)
	for i := 0; i < 8 && dir != "." && dir != string(filepath.Separator); i++ {
		for _, candidate := range []string{filepath.Join(dir, "quant_stock_core"), dir} {
			clean := filepath.Clean(candidate)
			if !seen[clean] {
				seen[clean] = true
				out = append(out, clean)
			}
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return out
}

func isQuantCoreRoot(path string) bool {
	for _, marker := range []string{
		filepath.Join("scripts", "data_update_worker.py"),
		filepath.Join("scripts", "factor_snapshot_worker.py"),
		filepath.Join("scripts", "profit_arena_worker.py"),
	} {
		if info, err := os.Stat(filepath.Join(path, marker)); err == nil && !info.IsDir() {
			return true
		}
	}
	return false
}

func pythonPathForCore(quantRoot string) string {
	repoRoot := filepath.Dir(quantRoot)
	for _, candidate := range []string{
		filepath.Join(quantRoot, ".venv", "bin", "python"),
		filepath.Join(repoRoot, "quant_stock_desktop", ".venv", "bin", "python"),
		filepath.Join(repoRoot, ".venv", "bin", "python"),
	} {
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate
		}
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
	app.marketService = market.NewService(market.NewRepository(app.database))
	return nil
}

func (app *App) ensurePositionService() error {
	if app.positionService != nil {
		return nil
	}
	if err := app.ensureMarketService(); err != nil {
		return err
	}
	app.positionService = position.NewService(app.marketService, app.database)
	app.positionService.SetRuntimeDatabaseConfig(app.settings.DatabaseBackend, app.settings.MySQLDSN)
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
	backend, packagedDSN := config.PackagedDatabaseConfig()
	app.settings.DatabaseBackend = backend
	app.settings.MySQLDSN = packagedDSN
	if app.database != nil {
		return nil
	}
	var bootstrap *database.MySQLBootstrapConfig
	if app.settings.DatabaseBackend == "mysql" {
		mysqlCfg := config.PackagedMySQLBootstrapConfig(app.settings.MySQLDSN)
		if strings.TrimSpace(mysqlCfg.AdminDSN) != "" {
			bootstrap = &database.MySQLBootstrapConfig{
				AdminDSN: mysqlCfg.AdminDSN,
				Database: mysqlCfg.Database,
				User:     mysqlCfg.User,
				Password: mysqlCfg.Password,
				AppDSN:   mysqlCfg.AppDSN,
			}
		}
	}
	db, err := database.OpenConfigured(database.Config{
		Backend:        app.settings.DatabaseBackend,
		MySQLDSN:       app.settings.MySQLDSN,
		MySQLBootstrap: bootstrap,
	})
	if err != nil {
		return err
	}
	app.database = db
	app.configService.WithDatabase(db)
	if settings, err := app.configService.Load(app.settings); err == nil {
		settings.DataPath = app.fixedDataPath()
		app.settings = settings
		_ = app.configService.Save(app.settings)
	}
	app.taskService = task.NewService(task.NewRepository(db.Conn()))
	app.marketService = market.NewService(market.NewRepository(db))
	app.positionService = position.NewService(app.marketService, app.database)
	app.positionService.SetRuntimeDatabaseConfig(app.settings.DatabaseBackend, app.settings.MySQLDSN)
	_ = app.ensureProfitArenaProductionState()
	return nil
}

func (app *App) ensureProfitArenaProductionState() error {
	if app.database == nil || app.database.Conn() == nil {
		return errors.New("database is not initialized")
	}
	if !app.database.TableExists("profit_arena_predictions") || !app.database.TableExists("profit_arena_runs") {
		return nil
	}
	runID := app.latestProfitArenaPredictionRunID()
	if runID == "" || !app.strategyModelRunAdmissible(profitArenaStrategyID, runID) {
		return nil
	}
	if err := app.ensureStrategyModelActiveTable(); err != nil {
		return err
	}
	if err := app.ensureStrategyArenaChampionTable(); err != nil {
		return err
	}
	now := time.Now().Format(time.RFC3339)
	if _, err := app.database.Conn().Exec(
		app.database.UpsertSQL("strategy_model_active", []string{"strategy", "run_id", "updated_at"}, []string{"strategy"}, []string{"run_id", "updated_at"}),
		profitArenaStrategyID, runID, now,
	); err != nil {
		return err
	}
	arenaScore := app.profitArenaRunScore(runID)
	championVersion := time.Now().Unix()
	championPayload, _ := json.Marshal(map[string]any{
		"source":     "desktop_startup_production_state",
		"strategy":   profitArenaStrategyID,
		"arena_name": profitArenaDefaultArenaName,
		"run_id":     runID,
		"reason":     "align_active_champion_with_latest_prediction_snapshot",
		"updated_at": now,
	})
	_, err := app.database.Conn().Exec(
		app.database.UpsertSQL(
			"strategy_arena_champions",
			[]string{"strategy_id", "arena_name", "champion_run_id", "champion_version", "arena_score", "qualification_status", "champion_type", "validation_status", "champion_json", "updated_at"},
			[]string{"strategy_id", "arena_name"},
			[]string{"champion_run_id", "champion_version", "arena_score", "qualification_status", "champion_type", "validation_status", "champion_json", "updated_at"},
		),
		profitArenaStrategyID,
		profitArenaDefaultArenaName,
		runID,
		championVersion,
		arenaScore,
		"qualified",
		"production_latest_prediction",
		"confirmed",
		string(championPayload),
		now,
	)
	return err
}

func (app *App) latestProfitArenaPredictionRunID() string {
	if app.database == nil || app.database.Conn() == nil || !app.database.TableExists("profit_arena_predictions") {
		return ""
	}
	var latestDate string
	if err := app.database.Conn().QueryRow(`SELECT COALESCE(MAX(trade_date), '') FROM profit_arena_predictions`).Scan(&latestDate); err != nil || strings.TrimSpace(latestDate) == "" {
		return ""
	}
	var runID string
	err := app.database.Conn().QueryRow(`
		SELECT run_id
		FROM profit_arena_predictions
		WHERE trade_date = ?
		GROUP BY run_id
		ORDER BY COUNT(*) DESC
		LIMIT 1`, latestDate).Scan(&runID)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(runID)
}

func (app *App) profitArenaRunScore(runID string) float64 {
	if app.database == nil || app.database.Conn() == nil || strings.TrimSpace(runID) == "" || !app.database.TableExists("profit_arena_runs") {
		return 0
	}
	var score float64
	_ = app.database.Conn().QueryRow(`
		SELECT COALESCE(JSON_EXTRACT(summary_json, '$.best_challenger_score_components.score') + 0, 0)
		FROM profit_arena_runs
		WHERE run_id = ?
		LIMIT 1`, strings.TrimSpace(runID)).Scan(&score)
	return score
}

func (app *App) fixedDataPath() string {
	dataPath, _ := app.fixedDataPathWithSource()
	return dataPath
}

func (app *App) fixedDataPathWithSource() (string, string) {
	if dataPath, ok := inferWorkspaceDataPath(); ok {
		return dataPath, "workspace"
	}
	if app.settings.DataPath != "" {
		return filepath.Clean(app.settings.DataPath), "settings"
	}
	if homeDir, err := os.UserHomeDir(); err == nil {
		return config.DefaultSettings(homeDir).DataPath, "home_default"
	}
	return filepath.Join("data_store"), "relative_default"
}

func inferWorkspaceDataPath() (string, bool) {
	starts := make([]string, 0, 2)
	if wd, err := os.Getwd(); err == nil {
		starts = append(starts, wd)
	}
	if exe, err := os.Executable(); err == nil {
		starts = append(starts, filepath.Dir(exe))
	}
	for _, start := range starts {
		if dataPath, ok := findDataStoreUpwards(start); ok {
			return dataPath, true
		}
	}
	return "", false
}

func legacyUserSQLiteStateExists() bool {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return false
	}
	path := filepath.Join(homeDir, "Library", "Application Support", "QuantStockDesktop", "data_store", "meta.db")
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func (app *App) retiredStrategyVersionCount() int64 {
	if app.database == nil || !app.database.TableExists("strategy_config_versions") {
		return 0
	}
	var count int64
	if err := app.database.Conn().QueryRow(`SELECT COUNT(*) FROM strategy_config_versions WHERE strategy <> ?`, profitArenaStrategyID).Scan(&count); err != nil {
		return 0
	}
	return count
}

func (app *App) retiredStrategyTaskCount() int64 {
	if app.database == nil || !app.database.TableExists("task_jobs") {
		return 0
	}
	var count int64
	query := `SELECT COUNT(*) FROM task_jobs WHERE ` + retiredStrategyTaskWhere("task_type", "name", "params_json", "external_run_id")
	if err := app.database.Conn().QueryRow(query).Scan(&count); err != nil {
		return 0
	}
	return count
}

func (app *App) retiredStrategyStatusCount() int64 {
	if app.database == nil || !app.database.TableExists("task_run_status") {
		return 0
	}
	var count int64
	query := `SELECT COUNT(*) FROM task_run_status WHERE ` + retiredStrategyTaskWhere("task", "task_type", "state", "stage", "name", "message")
	if err := app.database.Conn().QueryRow(query).Scan(&count); err != nil {
		return 0
	}
	return count
}

func (app *App) retiredActiveModelCount() int64 {
	if app.database == nil || !app.database.TableExists("strategy_model_active") {
		return 0
	}
	var count int64
	if err := app.database.Conn().QueryRow(`SELECT COUNT(*) FROM strategy_model_active WHERE strategy <> ?`, profitArenaStrategyID).Scan(&count); err != nil {
		return 0
	}
	return count
}

func (app *App) retiredValidationResultCount() int64 {
	if app.database == nil || !app.database.TableExists("strategy_model_validation_results") {
		return 0
	}
	var count int64
	if err := app.database.Conn().QueryRow(`SELECT COUNT(*) FROM strategy_model_validation_results WHERE strategy REGEXP 'limit|t0|horizontal|sideways'`).Scan(&count); err != nil {
		return 0
	}
	return count
}

func (app *App) retiredObservationCount() int64 {
	if app.database == nil {
		return 0
	}
	var total int64
	if app.database.TableExists("strategy_observation_pool") {
		var count int64
		if err := app.database.Conn().QueryRow(`SELECT COUNT(*) FROM strategy_observation_pool WHERE strategy NOT IN (?)`, factorResearchArchiveStrategyID).Scan(&count); err == nil {
			total += count
		}
	}
	if app.database.TableExists("strategy_observation_events") {
		var count int64
		if err := app.database.Conn().QueryRow(`SELECT COUNT(*) FROM strategy_observation_events WHERE strategy NOT IN (?)`, factorResearchArchiveStrategyID).Scan(&count); err == nil {
			total += count
		}
	}
	return total
}

func (app *App) retiredMySQLTableCount() int64 {
	if app.database == nil {
		return 0
	}
	var count int64
	legacyToken := "t0" + "_daily"
	query := fmt.Sprintf(`
		SELECT COUNT(*)
		FROM information_schema.tables
		WHERE table_schema = DATABASE()
		  AND (
			table_name LIKE '%%limit_up%%'
			OR table_name LIKE '%%limit_breakout%%'
			OR table_name LIKE '%%%s%%'
			OR table_name LIKE '%%horizontal%%'
			OR table_name LIKE '%%sideways%%'
		  )`, legacyToken)
	if err := app.database.Conn().QueryRow(query).Scan(&count); err != nil {
		return 0
	}
	return count
}

func (app *App) retiredDataArtifactCount() int64 {
	dataPath := app.fixedDataPath()
	legacyPaths := []string{
		filepath.Join(dataPath, "limit_up_model"),
		filepath.Join(dataPath, "limit_breakout_model"),
		filepath.Join(dataPath, "t0"+"daily_model"),
		filepath.Join(dataPath, "model_training", "limit_up_model"),
		filepath.Join(dataPath, "model_training", "limit_breakout_model"),
		filepath.Join(dataPath, "logs", "t0"+"daily_timemachine"),
		filepath.Join(dataPath, "logs", "t0"+"daily_research"),
		filepath.Join(dataPath, "logs", "limit_breakout"),
		filepath.Join(dataPath, "logs", "limit_up_momentum"),
	}
	var count int64
	for _, path := range legacyPaths {
		if info, err := os.Stat(path); err == nil && info.IsDir() {
			count++
		}
	}
	return count
}

func (app *App) profitArenaProductionHealth() map[string]any {
	out := map[string]any{
		"profit_arena_active_run_id":          "",
		"profit_arena_champion_run_id":        "",
		"profit_arena_latest_prediction_run_id": "",
		"profit_arena_active_matches_champion": false,
		"profit_arena_active_matches_latest_prediction": false,
		"profit_arena_run_count":              int64(0),
		"profit_arena_latest_prediction_date": "",
		"profit_arena_latest_prediction_count": int64(0),
	}
	if app.database == nil {
		return out
	}
	if app.database.TableExists("strategy_model_active") {
		var runID string
		if err := app.database.Conn().QueryRow(`SELECT run_id FROM strategy_model_active WHERE strategy = ? LIMIT 1`, profitArenaStrategyID).Scan(&runID); err == nil {
			out["profit_arena_active_run_id"] = strings.TrimSpace(runID)
		}
	}
	if app.database.TableExists("strategy_arena_champions") {
		var championRunID string
		if err := app.database.Conn().QueryRow(`SELECT champion_run_id FROM strategy_arena_champions WHERE strategy_id = ? ORDER BY updated_at DESC LIMIT 1`, profitArenaStrategyID).Scan(&championRunID); err == nil {
			out["profit_arena_champion_run_id"] = strings.TrimSpace(championRunID)
		}
	}
	out["profit_arena_active_matches_champion"] = strings.TrimSpace(fmt.Sprint(out["profit_arena_active_run_id"])) != "" &&
		strings.TrimSpace(fmt.Sprint(out["profit_arena_active_run_id"])) == strings.TrimSpace(fmt.Sprint(out["profit_arena_champion_run_id"]))
	if app.database.TableExists("profit_arena_runs") {
		var count int64
		if err := app.database.Conn().QueryRow(`SELECT COUNT(*) FROM profit_arena_runs`).Scan(&count); err == nil {
			out["profit_arena_run_count"] = count
		}
	}
	if app.database.TableExists("profit_arena_predictions") {
		var latestDate string
		if err := app.database.Conn().QueryRow(`SELECT COALESCE(MAX(trade_date), '') FROM profit_arena_predictions`).Scan(&latestDate); err == nil {
			out["profit_arena_latest_prediction_date"] = latestDate
			if latestDate != "" {
				var count int64
				if err := app.database.Conn().QueryRow(`SELECT COUNT(*) FROM profit_arena_predictions WHERE trade_date = ?`, latestDate).Scan(&count); err == nil {
					out["profit_arena_latest_prediction_count"] = count
				}
				var runID string
				if err := app.database.Conn().QueryRow(`
					SELECT run_id
					FROM profit_arena_predictions
					WHERE trade_date = ?
					GROUP BY run_id
					ORDER BY COUNT(*) DESC
					LIMIT 1`, latestDate).Scan(&runID); err == nil {
					out["profit_arena_latest_prediction_run_id"] = strings.TrimSpace(runID)
				}
			}
		}
	}
	out["profit_arena_active_matches_latest_prediction"] = strings.TrimSpace(fmt.Sprint(out["profit_arena_active_run_id"])) != "" &&
		strings.TrimSpace(fmt.Sprint(out["profit_arena_active_run_id"])) == strings.TrimSpace(fmt.Sprint(out["profit_arena_latest_prediction_run_id"]))
	return out
}

func retiredStrategyTaskWhere(columns ...string) string {
	expr := "LOWER(CONCAT_WS(' ', " + strings.Join(columns, ", ") + "))"
	rawExpr := "CONCAT_WS(' ', " + strings.Join(columns, ", ") + ")"
	parts := []string{
		expr + " LIKE '%limit_breakout%'",
		expr + " LIKE '%limit_up%'",
		expr + " LIKE '%horizontal%'",
		expr + " LIKE '%sideways%'",
		expr + " LIKE '%" + "t0" + "_daily%'",
		rawExpr + " LIKE '%" + string([]rune{28072, 20572}) + "%'",
		rawExpr + " LIKE '%" + string([]rune{27178, 30424}) + "%'",
		expr + " LIKE '%" + string([]rune{20570}) + "t%'",
	}
	return strings.Join(parts, " OR ")
}

func redactDSN(dsn string) string {
	value := strings.TrimSpace(dsn)
	if value == "" {
		return ""
	}
	at := strings.Index(value, "@")
	if at < 0 {
		return value
	}
	return "***" + value[at:]
}

func findDataStoreUpwards(start string) (string, bool) {
	dir := filepath.Clean(start)
	for {
		dataPath := filepath.Join(dir, "data_store")
		if pathExists(dataPath) {
			return dataPath, true
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", false
		}
		dir = parent
	}
}

func pathExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func processExists(pid int) bool {
	if pid <= 0 {
		return false
	}
	proc, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	return proc.Signal(syscall.Signal(0)) == nil
}

func mustGetwd() string {
	wd, err := os.Getwd()
	if err != nil {
		return "."
	}
	return wd
}
