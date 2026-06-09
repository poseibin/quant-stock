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
	schedulerMu      sync.Mutex
	signalMu         sync.Mutex
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

type T0Recommendation struct {
	TSCode            string   `json:"ts_code"`
	Name              string   `json:"name"`
	Industry          string   `json:"industry"`
	TradeDate         string   `json:"trade_date"`
	Action            string   `json:"action"`
	Recommendation    string   `json:"recommendation"`
	Score             float64  `json:"score"`
	State             string   `json:"state"`
	Setup             string   `json:"setup"`
	FirstAction       string   `json:"first_action"`
	Shares            int      `json:"shares"`
	MaxT0Shares       int      `json:"max_t0_shares"`
	Price             float64  `json:"price"`
	AvgCost           float64  `json:"avg_cost"`
	PositionWeight    float64  `json:"position_weight"`
	TodayPct          float64  `json:"today_pct"`
	Return5           float64  `json:"return_5d"`
	Return20          float64  `json:"return_20d"`
	AvgRange20        float64  `json:"avg_range_20d"`
	Drawdown20        float64  `json:"drawdown_20d"`
	Amount            float64  `json:"amount"`
	BuyBackPrice      float64  `json:"buy_back_price"`
	ReducePrice       float64  `json:"reduce_price"`
	StopPrice         float64  `json:"stop_price"`
	TRatio            float64  `json:"t_ratio"`
	ExpectedEdge      float64  `json:"expected_edge"`
	PlanJSON          string   `json:"plan_json"`
	Reasons           []string `json:"reasons"`
	Risks             []string `json:"risks"`
	GeneratedAt       string   `json:"generated_at"`
	FirstSeenDate     string   `json:"first_seen_date"`
	LastSeenDate      string   `json:"last_seen_date"`
	SeenCount         int      `json:"seen_count"`
	ObservationDays   int      `json:"observation_days"`
	ObservationStatus string   `json:"observation_status"`
	ObservationReason string   `json:"observation_reason"`
	ObservationResult string   `json:"observation_result"`
}

type T0DataPullCandidate struct {
	TSCode            string   `json:"ts_code"`
	Name              string   `json:"name"`
	Industry          string   `json:"industry"`
	TradeDate         string   `json:"trade_date"`
	Action            string   `json:"action"`
	Score             float64  `json:"score"`
	State             string   `json:"state"`
	Setup             string   `json:"setup"`
	FirstAction       string   `json:"first_action"`
	Price             float64  `json:"price"`
	ReducePrice       float64  `json:"reduce_price"`
	BuyPrice          float64  `json:"buy_price"`
	StopPrice         float64  `json:"stop_price"`
	TRatio            float64  `json:"t_ratio"`
	TodayPct          float64  `json:"today_pct"`
	Return5           float64  `json:"return_5d"`
	Return20          float64  `json:"return_20d"`
	AvgRange20        float64  `json:"avg_range_20d"`
	Drawdown20        float64  `json:"drawdown_20d"`
	Amount            float64  `json:"amount"`
	AvgAmount20       float64  `json:"avg_amount_20d"`
	ExpectedEdge      float64  `json:"expected_edge"`
	TargetFreq        string   `json:"target_freq"`
	LookbackDays      int      `json:"lookback_days"`
	PlanJSON          string   `json:"plan_json"`
	Reasons           []string `json:"reasons"`
	Risks             []string `json:"risks"`
	GeneratedAt       string   `json:"generated_at"`
	FirstSeenDate     string   `json:"first_seen_date"`
	LastSeenDate      string   `json:"last_seen_date"`
	SeenCount         int      `json:"seen_count"`
	ObservationDays   int      `json:"observation_days"`
	ObservationStatus string   `json:"observation_status"`
	ObservationReason string   `json:"observation_reason"`
	ObservationResult string   `json:"observation_result"`
}

type T0DailyBacktest struct {
	RunID        string  `json:"run_id"`
	TSCode       string  `json:"ts_code"`
	Name         string  `json:"name"`
	Industry     string  `json:"industry"`
	NDays        int     `json:"n_days"`
	NCandidates  int     `json:"n_candidates"`
	TwoSidedRate float64 `json:"two_sided_rate"`
	OneSidedRate float64 `json:"one_sided_rate"`
	AvgEdge      float64 `json:"avg_edge"`
	TotalEdge    float64 `json:"total_edge"`
	AvgNextRange float64 `json:"avg_next_range"`
	Score        float64 `json:"score"`
	SummaryJSON  string  `json:"summary_json"`
	UpdatedAt    string  `json:"updated_at"`
}

type T0DailyRunSummary struct {
	RunID          string `json:"run_id"`
	TradeDate      string `json:"trade_date"`
	Status         string `json:"status"`
	CandidateCount int    `json:"candidate_count"`
	BacktestCount  int    `json:"backtest_count"`
	SummaryJSON    string `json:"summary_json"`
	CreatedAt      string `json:"created_at"`
	UpdatedAt      string `json:"updated_at"`
}

type T0TimeMachineResult struct {
	RunID            string  `json:"run_id"`
	TSCode           string  `json:"ts_code"`
	Name             string  `json:"name"`
	Industry         string  `json:"industry"`
	AsOfDate         string  `json:"as_of_date"`
	EvalStartDate    string  `json:"eval_start_date"`
	EvalEndDate      string  `json:"eval_end_date"`
	Score            float64 `json:"score"`
	NEvalDays        int     `json:"n_eval_days"`
	TwoSidedCount    int     `json:"two_sided_count"`
	OneSidedCount    int     `json:"one_sided_count"`
	T0Edge           float64 `json:"t0_edge"`
	AvgT0Edge        float64 `json:"avg_t0_edge"`
	UnderlyingReturn float64 `json:"underlying_return"`
	CombinedReturn   float64 `json:"combined_return"`
	MaxDrawdown      float64 `json:"max_drawdown"`
	SummaryJSON      string  `json:"summary_json"`
	UpdatedAt        string  `json:"updated_at"`
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

type CrashWarningRunSummary struct {
	RunID          string  `json:"run_id"`
	ModelType      string  `json:"model_type"`
	StartDate      string  `json:"start_date"`
	EndDate        string  `json:"end_date"`
	Horizon        int     `json:"horizon"`
	FeatureCount   int     `json:"feature_count"`
	Status         string  `json:"status"`
	ModelPath      string  `json:"model_path"`
	Rows           int     `json:"rows"`
	PositiveRate   float64 `json:"positive_rate"`
	RocAUC         float64 `json:"roc_auc"`
	AvgPrecision   float64 `json:"avg_precision"`
	Top10Precision float64 `json:"top10_precision"`
	Top10Capture   float64 `json:"top10_capture"`
	P90Precision   float64 `json:"p90_precision"`
	P90Recall      float64 `json:"p90_recall"`
	SummaryJSON    string  `json:"summary_json"`
	UpdatedAt      string  `json:"updated_at"`
}

type CrashWarningFeature struct {
	RunID      string  `json:"run_id"`
	Feature    string  `json:"feature"`
	Importance float64 `json:"importance"`
	RankNo     int     `json:"rank_no"`
}

type LimitUpModelRunSummary struct {
	RunID           string  `json:"run_id"`
	StartDate       string  `json:"start_date"`
	EndDate         string  `json:"end_date"`
	Horizon         int     `json:"horizon"`
	ModelType       string  `json:"model_type"`
	FeatureCount    int     `json:"feature_count"`
	Status          string  `json:"status"`
	ModelPath       string  `json:"model_path"`
	Rows            int     `json:"rows"`
	CandidateRows   int     `json:"candidate_rows"`
	LatestDate      string  `json:"latest_date"`
	LatestCount     int     `json:"latest_count"`
	PositiveRate    float64 `json:"positive_rate"`
	BaselineReturn  float64 `json:"baseline_return"`
	TopReturn       float64 `json:"top_return"`
	TopExcessReturn float64 `json:"top_excess_return"`
	TopHitRate      float64 `json:"top_hit_rate"`
	TopLimitUpRate  float64 `json:"top_limit_up_rate"`
	TopDrawdown     float64 `json:"top_drawdown"`
	RankIC          float64 `json:"rank_ic"`
	SummaryJSON     string  `json:"summary_json"`
	UpdatedAt       string  `json:"updated_at"`
}

type LimitUpModelFeature struct {
	RunID      string  `json:"run_id"`
	Feature    string  `json:"feature"`
	Importance float64 `json:"importance"`
	RankNo     int     `json:"rank_no"`
}

type LimitUpModelPrediction struct {
	RunID             string  `json:"run_id"`
	TradeDate         string  `json:"trade_date"`
	TSCode            string  `json:"ts_code"`
	Name              string  `json:"name"`
	Industry          string  `json:"industry"`
	Price             float64 `json:"price"`
	High              float64 `json:"high"`
	Low               float64 `json:"low"`
	TodayPct          float64 `json:"today_pct"`
	Prob              float64 `json:"prob"`
	ModelScore        float64 `json:"model_score"`
	Label             int     `json:"label"`
	Fwd5Return        float64 `json:"fwd5_return"`
	Fwd5MaxReturn     float64 `json:"fwd5_max_return"`
	MaxDrawdown5D     float64 `json:"max_drawdown_5d"`
	HitLimitUp5D      int     `json:"hit_limit_up_5d"`
	IsLatest          bool    `json:"is_latest"`
	SummaryJSON       string  `json:"summary_json"`
	UpdatedAt         string  `json:"updated_at"`
	FirstSeenDate     string  `json:"first_seen_date"`
	LastSeenDate      string  `json:"last_seen_date"`
	SeenCount         int     `json:"seen_count"`
	ObservationDays   int     `json:"observation_days"`
	ObservationStatus string  `json:"observation_status"`
	ObservationReason string  `json:"observation_reason"`
	ObservationResult string  `json:"observation_result"`
}

type LimitUpModelTimeMachineSlice struct {
	RunID          string  `json:"run_id"`
	TradeDate      string  `json:"trade_date"`
	CandidateCount int     `json:"candidate_count"`
	TopCount       int     `json:"top_count"`
	AvgReturn      float64 `json:"avg_return"`
	AvgMaxReturn   float64 `json:"avg_max_return"`
	HitRate        float64 `json:"hit_rate"`
	LimitUpHitRate float64 `json:"limit_up_hit_rate"`
	AvgDrawdown    float64 `json:"avg_drawdown"`
	RankIC         float64 `json:"rank_ic"`
	UpdatedAt      string  `json:"updated_at"`
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

type SignalPortfolioCandidateDTO struct {
	RunID            string             `json:"run_id"`
	CandidateID      string             `json:"candidate_id"`
	Rank             int                `json:"rank"`
	Name             string             `json:"name"`
	Objective        string             `json:"objective"`
	Status           string             `json:"status"`
	Score            float64            `json:"score"`
	Strategies       string             `json:"strategies"`
	Weights          map[string]float64 `json:"weights"`
	AnnualReturn     *float64           `json:"annual_return"`
	MaxDrawdown      *float64           `json:"max_drawdown"`
	Sharpe           *float64           `json:"sharpe"`
	Calmar           *float64           `json:"calmar"`
	AvgTurnover      *float64           `json:"avg_turnover"`
	AvgHoldings      *float64           `json:"avg_holdings"`
	RebalanceFreq    int                `json:"rebalance_freq"`
	ValidationStatus string             `json:"validation_status"`
	Reason           string             `json:"reason"`
	UpdatedAt        string             `json:"updated_at"`
	IsActive         bool               `json:"is_active"`
}

type SignalPortfolioContextDTO struct {
	Active        *activePortfolioCandidateRecord `json:"active"`
	Candidates    []SignalPortfolioCandidateDTO   `json:"candidates"`
	CanGenerate   bool                            `json:"can_generate"`
	BlockedReason string                          `json:"blocked_reason"`
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

type StrategyModelRunRequest struct {
	Strategy string `json:"strategy"`
	RunID    string `json:"run_id"`
}

type ActiveStrategyModelRun struct {
	Strategy  string `json:"strategy"`
	RunID     string `json:"run_id"`
	UpdatedAt string `json:"updated_at"`
}

type PolicySupportSignalDTO struct {
	TradeDate          string  `json:"trade_date"`
	SignalLevel        string  `json:"signal_level"`
	TotalScore         float64 `json:"total_score"`
	MarketStressScore  float64 `json:"market_stress_score"`
	SupportScore       float64 `json:"support_score"`
	InstitutionScore   float64 `json:"institution_score"`
	WeightSupportScore float64 `json:"weight_support_score"`
	Direction          string  `json:"direction"`
	Reason             string  `json:"reason"`
	EvidenceJSON       string  `json:"evidence_json"`
	UpdatedAt          string  `json:"updated_at"`
}

type PolicySupportCandidateDTO struct {
	TradeDate         string  `json:"trade_date"`
	TSCode            string  `json:"ts_code"`
	Name              string  `json:"name"`
	Industry          string  `json:"industry"`
	CandidateType     string  `json:"candidate_type"`
	Score             float64 `json:"score"`
	PctChg            float64 `json:"pct_chg"`
	AmountRatio       float64 `json:"amount_ratio"`
	TurnoverRate      float64 `json:"turnover_rate"`
	InstitutionNetBuy float64 `json:"institution_net_buy"`
	Reason            string  `json:"reason"`
	UpdatedAt         string  `json:"updated_at"`
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
	if backend != "mysql" {
		settings.MySQLDSN = packagedDSN
	} else if strings.TrimSpace(settings.MySQLDSN) == "" {
		settings.MySQLDSN = packagedDSN
	}
	issues := app.configService.Validate(settings)
	if app.databaseConfigChanged(settings) {
		if running, message := app.hasActiveRuntimeWork(); running {
			issues = append(issues, config.ValidationIssue{Field: "database_backend", Message: "当前有任务运行中，不能切换数据库配置：" + message})
		}
	}
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
	issues = append(issues, app.configService.Validate(app.settings)...)
	return SettingsResponse{
		Settings: app.settings,
		Issues:   issues,
	}
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
		if len(evaluationWorkerPIDs()) > 0 {
			return true, "仍有评估 Python 进程"
		}
		return false, ""
	}
	app.reconcileEvaluationWorkerProcesses()
	db := app.database.Conn()
	var evaluationCount int
	if err := db.QueryRow(`SELECT COUNT(*) FROM task_jobs WHERE status IN ('queued','running')`).Scan(&evaluationCount); err == nil && evaluationCount > 0 {
		return true, "评估任务正在运行或排队"
	}
	var runStatusCount int
	if err := db.QueryRow(`SELECT COUNT(*) FROM task_run_status WHERE state = 'running'`).Scan(&runStatusCount); err == nil && runStatusCount > 0 {
		return true, "Python 状态任务正在运行"
	}
	if len(evaluationWorkerPIDs()) > 0 {
		return true, "仍有评估 Python 进程"
	}
	return false, ""
}

func (app *App) ListStrategyVersions(strategy string) ([]StrategyVersionDTO, error) {
	if err := app.ensureDatabase(); err != nil {
		return nil, err
	}
	query := `SELECT strategy, version, label, config_json, is_active, COALESCE(promotion_status,'research'),
		COALESCE(validation_json,'{}'), COALESCE(source,''), COALESCE(note,''), created_at, COALESCE(activated_at,'')
		FROM strategy_config_versions`
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
	row := app.database.Conn().QueryRow(`SELECT config_json FROM strategy_config_versions WHERE strategy = ? AND version = ?`, strategyName, req.Version)
	var configJSON string
	if err := row.Scan(&configJSON); err != nil {
		return SettingsResponse{}, err
	}
	var strategyCfg config.StrategySettings
	if err := json.Unmarshal([]byte(configJSON), &strategyCfg); err != nil {
		return SettingsResponse{}, err
	}
	if app.database != nil {
		app.configService.WithDatabase(app.database)
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
	if _, err := tx.Exec(`UPDATE strategy_config_versions SET is_active = 0 WHERE strategy = ?`, strategyName); err != nil {
		_ = tx.Rollback()
		return SettingsResponse{}, err
	}
	if _, err := tx.Exec(`UPDATE strategy_config_versions SET is_active = 1, promotion_status = 'active', activated_at = ? WHERE strategy = ? AND version = ?`, now, strategyName, req.Version); err != nil {
		_ = tx.Rollback()
		return SettingsResponse{}, err
	}
	_, settingsErr := tx.Exec(
		app.database.UpsertSQL("cfg_app_settings", []string{"key", "value", "updated_at"}, []string{"key"}, []string{"value", "updated_at"}),
		"settings", string(settingsData), now,
	)
	if settingsErr != nil {
		_ = tx.Rollback()
		return SettingsResponse{}, settingsErr
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
		if _, err := app.database.Conn().Exec(`UPDATE strategy_config_versions SET promotion_status = CASE WHEN version = ? THEN 'paper' WHEN promotion_status = 'paper' THEN 'research' ELSE promotion_status END WHERE strategy = ?`, req.Version, strategyName); err != nil {
			return nil, err
		}
	} else {
		if _, err := app.database.Conn().Exec(`UPDATE strategy_config_versions SET promotion_status = ? WHERE strategy = ? AND version = ?`, status, strategyName, req.Version); err != nil {
			return nil, err
		}
	}
	return app.ListStrategyVersions(strategyName)
}

func (app *App) GetActiveStrategyModelRun(strategy string) (ActiveStrategyModelRun, error) {
	if err := app.ensureDatabase(); err != nil {
		return ActiveStrategyModelRun{}, err
	}
	if err := app.ensureStrategyModelActiveTable(); err != nil {
		return ActiveStrategyModelRun{}, err
	}
	strategy = strings.TrimSpace(strategy)
	if strategy == "" {
		return ActiveStrategyModelRun{}, errors.New("strategy is required")
	}
	var item ActiveStrategyModelRun
	err := app.database.Conn().QueryRow(`SELECT strategy, run_id, updated_at FROM strategy_model_active WHERE strategy = ?`, strategy).
		Scan(&item.Strategy, &item.RunID, &item.UpdatedAt)
	if err == sql.ErrNoRows {
		return ActiveStrategyModelRun{Strategy: strategy}, nil
	}
	return item, err
}

func (app *App) ActivateStrategyModelRun(req StrategyModelRunRequest) (ActiveStrategyModelRun, error) {
	if err := app.ensureDatabase(); err != nil {
		return ActiveStrategyModelRun{}, err
	}
	if err := app.ensureStrategyModelActiveTable(); err != nil {
		return ActiveStrategyModelRun{}, err
	}
	strategy := strings.TrimSpace(req.Strategy)
	runID := strings.TrimSpace(req.RunID)
	if strategy == "" || runID == "" {
		return ActiveStrategyModelRun{}, errors.New("strategy and run_id are required")
	}
	if !app.strategyModelRunExists(strategy, runID) {
		return ActiveStrategyModelRun{}, errors.New("model run not found")
	}
	now := time.Now().Format(time.RFC3339)
	_, err := app.database.Conn().Exec(
		app.database.UpsertSQL("strategy_model_active", []string{"strategy", "run_id", "updated_at"}, []string{"strategy"}, []string{"run_id", "updated_at"}),
		strategy, runID, now,
	)
	if err != nil {
		return ActiveStrategyModelRun{}, err
	}
	return ActiveStrategyModelRun{Strategy: strategy, RunID: runID, UpdatedAt: now}, nil
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

func (app *App) activeStrategyModelRunID(strategy string) string {
	if app.database == nil || app.database.Conn() == nil {
		return ""
	}
	if err := app.ensureStrategyModelActiveTable(); err != nil {
		return ""
	}
	var runID string
	_ = app.database.Conn().QueryRow(`SELECT run_id FROM strategy_model_active WHERE strategy = ?`, strings.TrimSpace(strategy)).Scan(&runID)
	return strings.TrimSpace(runID)
}

func (app *App) strategyModelRunExists(strategy string, runID string) bool {
	table := ""
	switch strings.TrimSpace(strategy) {
	case "limit_up_model":
		table = "limit_up_model_runs"
	case "limit_breakout_model":
		table = "limit_breakout_model_runs"
	case "t0_daily":
		table = "t0_daily_runs"
	default:
		return false
	}
	var count int
	_ = app.database.Conn().QueryRow(fmt.Sprintf(`SELECT COUNT(*) FROM %s WHERE run_id = ?`, table), runID).Scan(&count)
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

func (app *App) GetSignalPortfolioContext() (SignalPortfolioContextDTO, error) {
	if err := app.ensureDatabase(); err != nil {
		return SignalPortfolioContextDTO{}, err
	}
	candidates, err := app.listSignalPortfolioCandidates(nil)
	if err != nil {
		return SignalPortfolioContextDTO{}, err
	}
	blockedReason := ""
	if len(candidates) == 0 {
		blockedReason = "请先在评估中心完成组合优化/时光机评估，生成候选组合后再生成信号"
	}
	return SignalPortfolioContextDTO{
		Active:        nil,
		Candidates:    candidates,
		CanGenerate:   len(candidates) > 0,
		BlockedReason: blockedReason,
	}, nil
}

func (app *App) activePortfolioCandidate() (*activePortfolioCandidateRecord, error) {
	if app.database == nil {
		return nil, errors.New("database is not initialized")
	}
	var payload string
	err := app.database.Conn().QueryRow(fmt.Sprintf(`SELECT value FROM cfg_app_settings WHERE %s = ?`, app.cfgAppSettingsKeyColumn()), "active_portfolio_candidate").Scan(&payload)
	if err != nil {
		return nil, err
	}
	var active activePortfolioCandidateRecord
	if err := json.Unmarshal([]byte(payload), &active); err != nil {
		return nil, err
	}
	return &active, nil
}

func (app *App) listSignalPortfolioCandidates(active *activePortfolioCandidateRecord) ([]SignalPortfolioCandidateDTO, error) {
	rows, err := app.database.Conn().Query(`SELECT run_id, candidate_id, ` + "`rank`" + `, name, objective, status, score,
		strategies, weights_json, annual_return, max_drawdown, sharpe, calmar, avg_turnover, avg_holdings,
		rebalance_freq, COALESCE(validation_status,''), COALESCE(reason,''), COALESCE(updated_at,'')
		FROM eval_portfolio_candidates
		WHERE status = 'ok'
		ORDER BY CASE WHEN ` + "`rank`" + ` > 0 THEN 0 ELSE 1 END, ` + "`rank`" + ` ASC, score DESC, updated_at DESC
		LIMIT 30`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]SignalPortfolioCandidateDTO, 0)
	for rows.Next() {
		var item SignalPortfolioCandidateDTO
		var weightsJSON string
		var annualReturn, maxDrawdown, sharpe, calmar, avgTurnover, avgHoldings sql.NullFloat64
		if err := rows.Scan(
			&item.RunID, &item.CandidateID, &item.Rank, &item.Name, &item.Objective, &item.Status, &item.Score,
			&item.Strategies, &weightsJSON, &annualReturn, &maxDrawdown, &sharpe, &calmar, &avgTurnover, &avgHoldings,
			&item.RebalanceFreq, &item.ValidationStatus, &item.Reason, &item.UpdatedAt,
		); err != nil {
			return nil, err
		}
		_ = json.Unmarshal([]byte(weightsJSON), &item.Weights)
		item.AnnualReturn = nullableFloatPtr(annualReturn)
		item.MaxDrawdown = nullableFloatPtr(maxDrawdown)
		item.Sharpe = nullableFloatPtr(sharpe)
		item.Calmar = nullableFloatPtr(calmar)
		item.AvgTurnover = nullableFloatPtr(avgTurnover)
		item.AvgHoldings = nullableFloatPtr(avgHoldings)
		if active != nil && active.RunID == item.RunID && active.CandidateID == item.CandidateID {
			item.IsActive = true
		}
		out = append(out, item)
	}
	return out, rows.Err()
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
	dbPath := filepath.Join(dataPath, "meta.db")
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
		"--db-path", dbPath,
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv(dbPath)...)...)
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

func (app *App) GetLatestPolicySupportSignal() (PolicySupportSignalDTO, error) {
	if err := app.ensureDatabase(); err != nil {
		return PolicySupportSignalDTO{}, err
	}
	var item PolicySupportSignalDTO
	err := app.database.Conn().QueryRow(`SELECT
			trade_date, signal_level, total_score, market_stress_score, support_score,
			institution_score, weight_support_score, direction, reason, evidence_json, updated_at
		FROM monitor_policy_support_signals
		ORDER BY trade_date DESC
		LIMIT 1`).Scan(
		&item.TradeDate,
		&item.SignalLevel,
		&item.TotalScore,
		&item.MarketStressScore,
		&item.SupportScore,
		&item.InstitutionScore,
		&item.WeightSupportScore,
		&item.Direction,
		&item.Reason,
		&item.EvidenceJSON,
		&item.UpdatedAt,
	)
	if errors.Is(err, sql.ErrNoRows) {
		return PolicySupportSignalDTO{}, nil
	}
	return item, err
}

func (app *App) ListPolicySupportCandidates(limit int) ([]PolicySupportCandidateDTO, error) {
	if err := app.ensureDatabase(); err != nil {
		return []PolicySupportCandidateDTO{}, err
	}
	if limit <= 0 || limit > 300 {
		limit = 80
	}
	var tradeDate string
	if err := app.database.Conn().QueryRow(`SELECT COALESCE(MAX(trade_date), '') FROM monitor_policy_support_signals`).Scan(&tradeDate); err != nil {
		return []PolicySupportCandidateDTO{}, err
	}
	if tradeDate == "" {
		return []PolicySupportCandidateDTO{}, nil
	}
	rows, err := app.database.Conn().Query(`SELECT
			trade_date, ts_code, name, industry, candidate_type, score, pct_chg,
			amount_ratio, turnover_rate, institution_net_buy, reason, updated_at
		FROM monitor_policy_support_candidates
		WHERE trade_date = ?
		ORDER BY score DESC
		LIMIT ?`, tradeDate, limit)
	if err != nil {
		return []PolicySupportCandidateDTO{}, err
	}
	defer rows.Close()
	out := make([]PolicySupportCandidateDTO, 0)
	for rows.Next() {
		var item PolicySupportCandidateDTO
		if err := rows.Scan(
			&item.TradeDate,
			&item.TSCode,
			&item.Name,
			&item.Industry,
			&item.CandidateType,
			&item.Score,
			&item.PctChg,
			&item.AmountRatio,
			&item.TurnoverRate,
			&item.InstitutionNetBuy,
			&item.Reason,
			&item.UpdatedAt,
		); err != nil {
			return []PolicySupportCandidateDTO{}, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) GetPolicySupportAnalysisStatus() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	return app.positionService.GetRunStatus("policy_support_analysis")
}

func (app *App) RunPolicySupportAnalysis() error {
	if err := app.ensureDatabase(); err != nil {
		return err
	}
	if status, err := app.GetPolicySupportAnalysisStatus(); err == nil && status.State == "running" {
		return errors.New("政策资金托底分析正在运行")
	}
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return errors.New("数据路径未设置")
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	dbPath := filepath.Join(dataPath, "meta.db")
	logDir := filepath.Join(dataPath, "logs", "policy_support")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return err
	}
	logPath := filepath.Join(logDir, time.Now().Format("20060102_150405")+".log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	now := time.Now().Format(time.RFC3339)
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{"task", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
		),
		"policy_support_analysis", "running", 0, 5, "prepare", "启动政策资金托底分析", "", now, now, "",
	)
	app.ensureRunStatusTaskType("policy_support_analysis")
	args := []string{
		"scripts/analyze_policy_support.py",
		"--data-root", dataPath,
		"--db-path", dbPath,
		"--json",
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv(dbPath)...)...)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		finishedAt := time.Now().Format(time.RFC3339)
		_, _ = app.database.Conn().Exec(
			`UPDATE task_run_status SET state='error', message=?, updated_at=?, finished_at=? WHERE task='policy_support_analysis'`,
			err.Error(),
			finishedAt,
			finishedAt,
		)
		return err
	}
	go app.waitPythonStatusTask(cmd, logFile, logPath, "policy_support_analysis")
	return nil
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
}

func (app *App) markGenericPythonWorkerStarted(taskName string, taskType string, pid int, logPath string) {
	if app.database == nil {
		return
	}
	now := time.Now().Format(time.RFC3339)
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{"task", "task_type", "state", "idx", "total", "stage", "name", "message", "worker_pid", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"task_type", "state", "idx", "total", "stage", "name", "message", "worker_pid", "updated_at", "finished_at"},
		),
		taskName, taskType, "running", 0, 5, "prepare", "启动训练进程", "日志: "+logPath, pid, now, now, "",
	)
}

func (app *App) waitGenericPythonWorker(cmd *exec.Cmd, logFile *os.File, taskName string, logPath string) {
	err := cmd.Wait()
	_ = logFile.Close()
	if err == nil || app.database == nil {
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
	case "daily_signal":
		return "signal"
	case "limit_signal_evaluation":
		return "evaluation"
	case "limit_breakout", "limit_up_momentum", "t0_daily_research", "t0_daily_timemachine":
		return "market_scan"
	case "limit_up_model":
		return "model_training"
	case "limit_breakout_model":
		return "model_training"
	case "policy_support_analysis":
		return "analysis"
	default:
		return "python"
	}
}

func (app *App) pythonDBEnv(dbPath string) []string {
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
		"DESKTOP_DB_PATH=" + dbPath,
		"DESKTOP_CONFIG_DB_PATH=" + dbPath,
	}
}

func (app *App) ListLimitBreakoutCandidates(query market.BreakoutQuery) ([]market.LimitBreakoutCandidate, error) {
	if err := app.ensureMarketService(); err != nil {
		return nil, err
	}
	items, err := app.marketService.ListLimitBreakoutCandidates(app.settings.DataPath, query)
	if err != nil {
		return nil, err
	}
	app.syncLimitBreakoutObservation(query, items)
	return items, nil
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
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv(dbPath)...)...)
	if err := cmd.Run(); err != nil {
		app.markPythonStatusTaskError("limit_breakout", "涨停预警扫描失败: "+err.Error()+"，日志: "+logPath)
		return nil, fmt.Errorf("涨停预警扫描失败: %w，请查看日志 %s", err, logPath)
	}
	items, err := app.marketService.ListLimitBreakoutCandidates(dataPath, query)
	if err != nil {
		return nil, err
	}
	app.syncLimitBreakoutObservation(query, items)
	return items, nil
}

func (app *App) ListLimitUpMomentumCandidates(query market.LimitUpMomentumQuery) ([]market.LimitUpMomentumCandidate, error) {
	if err := app.ensureMarketService(); err != nil {
		return nil, err
	}
	items, err := app.marketService.ListLimitUpMomentumCandidates(app.settings.DataPath, query)
	if err != nil {
		return nil, err
	}
	app.syncLimitUpMomentumObservation(query, items)
	return items, nil
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
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv(dbPath)...)...)
	if err := cmd.Run(); err != nil {
		app.markPythonStatusTaskError("limit_up_momentum", "涨停板推荐扫描失败: "+err.Error()+"，日志: "+logPath)
		return nil, fmt.Errorf("涨停板推荐扫描失败: %w，请查看日志 %s", err, logPath)
	}
	items, err := app.marketService.ListLimitUpMomentumCandidates(dataPath, query)
	if err != nil {
		return nil, err
	}
	app.syncLimitUpMomentumObservation(query, items)
	return items, nil
}

func (app *App) GetLimitBreakoutRunStatus() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	return app.positionService.GetRunStatus("limit_breakout")
}

func (app *App) syncLimitBreakoutObservation(query market.BreakoutQuery, items []market.LimitBreakoutCandidate) {
	if len(items) == 0 || app.database == nil || app.database.Conn() == nil {
		return
	}
	query = market.NormalizeBreakoutQuery(query)
	tradeDate := items[0].LatestDate
	runID := market.BreakoutCacheKey(query)
	candidates := make([]strategyObservationCandidate, 0, len(items))
	for i, item := range items {
		reason := ""
		if len(item.Reasons) > 0 {
			reason = strings.Join(item.Reasons[:minInt(len(item.Reasons), 2)], "；")
		}
		candidates = append(candidates, strategyObservationCandidate{
			Strategy:  "limit_breakout",
			RunID:     runID,
			TradeDate: item.LatestDate,
			TSCode:    item.TSCode,
			Name:      item.Name,
			Industry:  item.Industry,
			RankNo:    i + 1,
			Score:     item.Score,
			RankPct:   item.Score / 100,
			Price:     item.Close,
			PctChg:    item.RecentReturn,
			Reason:    reason,
		})
	}
	_ = app.syncStrategyObservationPool("limit_breakout", runID, tradeDate, candidates)
	for i := range items {
		meta := app.strategyObservationMeta("limit_breakout", items[i].TSCode, items[i].LatestDate, items[i].Close)
		items[i].FirstSeenDate = meta.FirstSeenDate
		items[i].LastSeenDate = meta.LastSeenDate
		items[i].SeenCount = meta.SeenCount
		items[i].ObservationDays = meta.ObservationDays
		items[i].ObservationStatus = meta.ObservationStatus
		items[i].ObservationReason = meta.ObservationReason
		items[i].ObservationResult = meta.ObservationResult
	}
}

func (app *App) syncLimitUpMomentumObservation(query market.LimitUpMomentumQuery, items []market.LimitUpMomentumCandidate) {
	if len(items) == 0 || app.database == nil || app.database.Conn() == nil {
		return
	}
	query = market.NormalizeLimitUpMomentumQuery(query)
	tradeDate := items[0].TradeDate
	runID := market.LimitUpMomentumCacheKey(query)
	candidates := make([]strategyObservationCandidate, 0, len(items))
	for i, item := range items {
		reason := firstNonEmpty(item.Recommendation, item.Stage)
		if len(item.Reasons) > 0 {
			reason = strings.Join(item.Reasons[:minInt(len(item.Reasons), 2)], "；")
		}
		candidates = append(candidates, strategyObservationCandidate{
			Strategy:  "limit_up_momentum",
			RunID:     runID,
			TradeDate: item.TradeDate,
			TSCode:    item.TSCode,
			Name:      item.Name,
			Industry:  item.Industry,
			RankNo:    i + 1,
			Score:     item.Score,
			RankPct:   item.Score / 100,
			Price:     item.Close,
			PctChg:    item.Recent20Return,
			Reason:    reason,
		})
	}
	_ = app.syncStrategyObservationPool("limit_up_momentum", runID, tradeDate, candidates)
	for i := range items {
		meta := app.strategyObservationMeta("limit_up_momentum", items[i].TSCode, items[i].TradeDate, items[i].Close)
		items[i].FirstSeenDate = meta.FirstSeenDate
		items[i].LastSeenDate = meta.LastSeenDate
		items[i].SeenCount = meta.SeenCount
		items[i].ObservationDays = meta.ObservationDays
		items[i].ObservationStatus = meta.ObservationStatus
		items[i].ObservationReason = meta.ObservationReason
		items[i].ObservationResult = meta.ObservationResult
	}
}

func (app *App) GetLimitUpMomentumRunStatus() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	return app.positionService.GetRunStatus("limit_up_momentum")
}

func (app *App) ClearLimitBreakoutCandidates() error {
	if err := app.ensureMarketService(); err != nil {
		return err
	}
	if err := app.marketService.ClearLimitBreakoutCandidates(); err != nil {
		return err
	}
	app.clearRunStatus("limit_breakout")
	return nil
}

func (app *App) ClearLimitUpMomentumCandidates() error {
	if err := app.ensureMarketService(); err != nil {
		return err
	}
	if err := app.marketService.ClearLimitUpMomentumCandidates(); err != nil {
		return err
	}
	app.clearRunStatus("limit_up_momentum")
	return nil
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

func (app *App) ListLimitSignalEvaluationSummary() ([]market.LimitSignalEvaluationSummary, error) {
	if err := app.ensureMarketService(); err != nil {
		return []market.LimitSignalEvaluationSummary{}, err
	}
	return app.marketService.ListLimitSignalEvaluationSummary()
}

func (app *App) ListLimitSignalTimeMachineSlices(limit int) ([]market.LimitSignalTimeMachineSlice, error) {
	if err := app.ensureMarketService(); err != nil {
		return []market.LimitSignalTimeMachineSlice{}, err
	}
	return app.marketService.ListLimitSignalTimeMachineSlices(limit)
}

func (app *App) ListFactorResearchRuns(limit int) ([]FactorResearchRunSummary, error) {
	if err := app.ensureDatabase(); err != nil {
		return []FactorResearchRunSummary{}, err
	}
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	rows, err := app.database.Conn().Query(`
		SELECT r.run_id, r.start_date, r.end_date, r.freq, r.label, r.status,
		       COALESCE(p.factor_count, 0), COALESCE(p.sample_dates, 0), COALESCE(p.sample_rows, 0),
		       COALESCE(p.panel_path, ''), r.updated_at,
		       COALESCE(m.status, ''), COALESCE(JSON_EXTRACT(m.summary_json, '$.oos_rank_ic_mean') + 0, 0)
		FROM factor_research_runs r
		LEFT JOIN factor_panel_meta p ON p.run_id = r.run_id
		LEFT JOIN factor_model_runs m ON m.run_id = r.run_id
		ORDER BY r.updated_at DESC
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
	strategy := "ml_factor_ranker"
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
			WHERE strategy = 'ml_factor_ranker' AND ts_code = ?`, rows[i].TsCode).
			Scan(&rows[i].FirstSeenDate, &rows[i].LastSeenDate, &rows[i].SeenCount, &rows[i].ObservationStatus, &rows[i].ObservationReason)
		if err != nil {
			continue
		}
		rows[i].ObservationDays = observationDays(rows[i].FirstSeenDate, firstNonEmpty(rows[i].TradeDate, rows[i].LastSeenDate))
		rows[i].ObservationResult = app.strategyObservationResult("ml_factor_ranker", rows[i].TsCode, rows[i].Price)
	}
}

func factorObservationReason(eventType string, rankNo int, item FactorLatestPrediction) string {
	if eventType == "entered" {
		return fmt.Sprintf("首次进入通用策略Top20，排名第%d，预测分位%s", rankNo, formatPercentForReason(item.PredRank))
	}
	return fmt.Sprintf("继续保留在通用策略Top20，排名第%d，预测分位%s", rankNo, formatPercentForReason(item.PredRank))
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

func minInt(a int, b int) int {
	if a < b {
		return a
	}
	return b
}

func genericObservationReason(strategy string, eventType string, item strategyObservationCandidate) string {
	label := strategyLabel(strategy)
	if eventType == "entered" {
		return fmt.Sprintf("首次进入%s推荐池，排名第%d", label, item.RankNo)
	}
	return fmt.Sprintf("继续保留在%s推荐池，排名第%d", label, item.RankNo)
}

func strategyLabel(strategy string) string {
	switch strategy {
	case "ml_factor_ranker":
		return "通用策略"
	case "t0_daily":
		return "做T策略"
	case "limit_up_momentum":
		return "涨停策略"
	case "limit_breakout":
		return "横盘策略"
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
		WHERE e.strategy = 'ml_factor_ranker'
		ORDER BY e.trade_date DESC, e.created_at DESC
		LIMIT ?`, limit)
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
		WHERE strategy = 'ml_factor_ranker'
		ORDER BY generated_at DESC
		LIMIT ?`, limit)
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

func (app *App) ListCrashWarningRuns(limit int) ([]CrashWarningRunSummary, error) {
	if err := app.ensureDatabase(); err != nil {
		return []CrashWarningRunSummary{}, err
	}
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, model_type, start_date, end_date, COALESCE(horizon, 0),
		       COALESCE(feature_count, 0), status, COALESCE(model_path, ''),
		       COALESCE(JSON_EXTRACT(summary_json, '$.rows') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.positive_rate') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.roc_auc') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.avg_precision') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.top10_precision') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.top10_capture') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.p90_precision') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.p90_recall') + 0, 0),
		       COALESCE(summary_json, ''), updated_at
		FROM market_crash_warning_runs
		ORDER BY updated_at DESC
		LIMIT ?`, limit)
	if err != nil {
		return []CrashWarningRunSummary{}, nil
	}
	defer rows.Close()
	out := []CrashWarningRunSummary{}
	for rows.Next() {
		var item CrashWarningRunSummary
		if err := rows.Scan(
			&item.RunID, &item.ModelType, &item.StartDate, &item.EndDate, &item.Horizon,
			&item.FeatureCount, &item.Status, &item.ModelPath, &item.Rows, &item.PositiveRate,
			&item.RocAUC, &item.AvgPrecision, &item.Top10Precision, &item.Top10Capture,
			&item.P90Precision, &item.P90Recall, &item.SummaryJSON, &item.UpdatedAt,
		); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListCrashWarningFeatures(runID string, limit int) ([]CrashWarningFeature, error) {
	if err := app.ensureDatabase(); err != nil {
		return []CrashWarningFeature{}, err
	}
	runID = strings.TrimSpace(runID)
	if runID == "" {
		row := app.database.Conn().QueryRow(`SELECT run_id FROM market_crash_warning_runs WHERE status = 'success' ORDER BY updated_at DESC LIMIT 1`)
		_ = row.Scan(&runID)
	}
	if runID == "" {
		return []CrashWarningFeature{}, nil
	}
	if limit <= 0 || limit > 100 {
		limit = 30
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, feature, COALESCE(importance, 0), COALESCE(rank_no, 0)
		FROM market_crash_warning_features
		WHERE run_id = ?
		ORDER BY rank_no ASC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []CrashWarningFeature{}, nil
	}
	defer rows.Close()
	out := []CrashWarningFeature{}
	for rows.Next() {
		var item CrashWarningFeature
		if err := rows.Scan(&item.RunID, &item.Feature, &item.Importance, &item.RankNo); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) RunLimitUpModelTraining() error {
	if err := app.ensureDatabase(); err != nil {
		return err
	}
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return errors.New("数据路径未设置")
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	dbPath := filepath.Join(dataPath, "meta.db")
	logDir := filepath.Join(dataPath, "logs", "limit_up_model")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return err
	}
	runID := "lum_" + time.Now().Format("20060102_150405")
	logPath := filepath.Join(logDir, runID+".log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	args := []string{
		"scripts/limit_up_model_worker.py",
		"--run-id", runID,
		"--data-path", dataPath,
		"--db-path", dbPath,
		"--start", "20150101",
		"--end", time.Now().Format("20060102"),
		"--min-test-year", "2019",
		"--threads", "4",
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv(dbPath)...)...)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		app.markPythonStatusTaskError("limit_up_model", "涨停模型训练启动失败: "+err.Error()+"，日志: "+logPath)
		return err
	}
	app.markGenericPythonWorkerStarted("limit_up_model", "model_training", cmd.Process.Pid, logPath)
	go app.waitGenericPythonWorker(cmd, logFile, "limit_up_model", logPath)
	return nil
}

func (app *App) GetLimitUpModelRunStatus() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	return app.positionService.GetRunStatus("limit_up_model")
}

func (app *App) RunLimitBreakoutModelTraining() error {
	if err := app.ensureDatabase(); err != nil {
		return err
	}
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return errors.New("数据路径未设置")
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	dbPath := filepath.Join(dataPath, "meta.db")
	logDir := filepath.Join(dataPath, "logs", "limit_breakout_model")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return err
	}
	runID := "lbm_" + time.Now().Format("20060102_150405")
	logPath := filepath.Join(logDir, runID+".log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	args := []string{
		"scripts/limit_breakout_model_worker.py",
		"--run-id", runID,
		"--data-path", dataPath,
		"--db-path", dbPath,
		"--start", "20150101",
		"--end", time.Now().Format("20060102"),
		"--min-test-year", "2020",
		"--top-k", "3",
		"--threads", "4",
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv(dbPath)...)...)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		app.markPythonStatusTaskError("limit_breakout_model", "横盘预警模型训练启动失败: "+err.Error()+"，日志: "+logPath)
		return err
	}
	app.markGenericPythonWorkerStarted("limit_breakout_model", "model_training", cmd.Process.Pid, logPath)
	go app.waitGenericPythonWorker(cmd, logFile, "limit_breakout_model", logPath)
	return nil
}

func (app *App) GetLimitBreakoutModelRunStatus() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	return app.positionService.GetRunStatus("limit_breakout_model")
}

func (app *App) ListLimitUpModelRuns(limit int) ([]LimitUpModelRunSummary, error) {
	if err := app.ensureDatabase(); err != nil {
		return []LimitUpModelRunSummary{}, err
	}
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, start_date, end_date, COALESCE(horizon, 0), model_type,
		       COALESCE(feature_count, 0), status, COALESCE(model_path, ''),
		       COALESCE(JSON_EXTRACT(summary_json, '$.rows') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.candidate_rows') + 0, 0),
		       COALESCE(JSON_UNQUOTE(JSON_EXTRACT(summary_json, '$.latest_date')), ''),
		       COALESCE(JSON_EXTRACT(summary_json, '$.latest_count') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.positive_rate') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.baseline_return') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.top_return') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.top_excess_return') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.top_hit_rate') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.top_limit_up_rate') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.top_drawdown') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.rank_ic') + 0, 0),
		       COALESCE(summary_json, ''), updated_at
		FROM limit_up_model_runs
		ORDER BY updated_at DESC
		LIMIT ?`, limit)
	if err != nil {
		return []LimitUpModelRunSummary{}, nil
	}
	defer rows.Close()
	out := []LimitUpModelRunSummary{}
	for rows.Next() {
		var item LimitUpModelRunSummary
		var rowsValue, candidateRowsValue, latestCountValue any
		if err := rows.Scan(
			&item.RunID, &item.StartDate, &item.EndDate, &item.Horizon, &item.ModelType,
			&item.FeatureCount, &item.Status, &item.ModelPath, &rowsValue, &candidateRowsValue,
			&item.LatestDate, &latestCountValue, &item.PositiveRate, &item.BaselineReturn,
			&item.TopReturn, &item.TopExcessReturn, &item.TopHitRate, &item.TopLimitUpRate,
			&item.TopDrawdown, &item.RankIC, &item.SummaryJSON, &item.UpdatedAt,
		); err != nil {
			return out, err
		}
		item.Rows = int(anyToFloat(rowsValue))
		item.CandidateRows = int(anyToFloat(candidateRowsValue))
		item.LatestCount = int(anyToFloat(latestCountValue))
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListLimitUpModelFeatures(runID string, limit int) ([]LimitUpModelFeature, error) {
	if err := app.ensureDatabase(); err != nil {
		return []LimitUpModelFeature{}, err
	}
	runID = app.resolveLatestLimitUpModelRunID(runID)
	if runID == "" {
		return []LimitUpModelFeature{}, nil
	}
	if limit <= 0 || limit > 100 {
		limit = 30
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, feature, COALESCE(importance, 0), COALESCE(rank_no, 0)
		FROM limit_up_model_features
		WHERE run_id = ?
		ORDER BY rank_no ASC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []LimitUpModelFeature{}, nil
	}
	defer rows.Close()
	out := []LimitUpModelFeature{}
	for rows.Next() {
		var item LimitUpModelFeature
		if err := rows.Scan(&item.RunID, &item.Feature, &item.Importance, &item.RankNo); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListLimitUpModelPredictions(runID string, limit int) ([]LimitUpModelPrediction, error) {
	if err := app.ensureDatabase(); err != nil {
		return []LimitUpModelPrediction{}, err
	}
	runID = app.resolveLatestLimitUpModelRunID(runID)
	if runID == "" {
		return []LimitUpModelPrediction{}, nil
	}
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	rows, err := app.database.Conn().Query(`
		SELECT p.run_id, p.trade_date, p.ts_code, p.name, p.industry,
		       COALESCE(d.close, 0), COALESCE(d.high, 0), COALESCE(d.low, 0), COALESCE(d.pct_chg, 0),
		       COALESCE(p.prob, 0), COALESCE(p.model_score, 0),
		       COALESCE(p.label, 0), COALESCE(p.fwd5_return, 0), COALESCE(p.fwd5_max_return, 0),
		       COALESCE(p.max_drawdown_5d, 0), COALESCE(p.hit_limit_up_5d, 0), COALESCE(p.is_latest, 0),
		       COALESCE(p.summary_json, ''), p.updated_at
		FROM limit_up_model_predictions p
		LEFT JOIN data_daily_bars d ON d.ts_code = p.ts_code AND d.trade_date = p.trade_date
		WHERE p.run_id = ? AND p.is_latest = 1
		ORDER BY p.model_score DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []LimitUpModelPrediction{}, nil
	}
	defer rows.Close()
	out := []LimitUpModelPrediction{}
	for rows.Next() {
		var item LimitUpModelPrediction
		var latest int
		if err := rows.Scan(
			&item.RunID, &item.TradeDate, &item.TSCode, &item.Name, &item.Industry,
			&item.Price, &item.High, &item.Low, &item.TodayPct, &item.Prob,
			&item.ModelScore, &item.Label, &item.Fwd5Return, &item.Fwd5MaxReturn, &item.MaxDrawdown5D,
			&item.HitLimitUp5D, &latest, &item.SummaryJSON, &item.UpdatedAt,
		); err != nil {
			return out, err
		}
		item.IsLatest = latest != 0
		if item.Price <= 0 {
			item.Price = app.latestClosePrice(item.TSCode)
		}
		out = append(out, item)
	}
	if err := rows.Err(); err != nil {
		return out, err
	}
	app.syncLimitModelPredictionObservation("limit_up_momentum", runID, out)
	return out, nil
}

func (app *App) ListLimitUpModelTimeMachineSlices(runID string, limit int) ([]LimitUpModelTimeMachineSlice, error) {
	if err := app.ensureDatabase(); err != nil {
		return []LimitUpModelTimeMachineSlice{}, err
	}
	runID = app.resolveLatestLimitUpModelRunID(runID)
	if runID == "" {
		return []LimitUpModelTimeMachineSlice{}, nil
	}
	if limit <= 0 || limit > 300 {
		limit = 80
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, trade_date, COALESCE(candidate_count, 0), COALESCE(top_count, 0),
		       COALESCE(avg_return, 0), COALESCE(avg_max_return, 0), COALESCE(hit_rate, 0),
		       COALESCE(limit_up_hit_rate, 0), COALESCE(avg_drawdown, 0), COALESCE(rank_ic, 0), updated_at
		FROM limit_up_model_tm_slices
		WHERE run_id = ?
		ORDER BY trade_date DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []LimitUpModelTimeMachineSlice{}, nil
	}
	defer rows.Close()
	out := []LimitUpModelTimeMachineSlice{}
	for rows.Next() {
		var item LimitUpModelTimeMachineSlice
		if err := rows.Scan(
			&item.RunID, &item.TradeDate, &item.CandidateCount, &item.TopCount, &item.AvgReturn,
			&item.AvgMaxReturn, &item.HitRate, &item.LimitUpHitRate, &item.AvgDrawdown, &item.RankIC, &item.UpdatedAt,
		); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) resolveLatestLimitUpModelRunID(runID string) string {
	runID = strings.TrimSpace(runID)
	if runID != "" || app.database == nil {
		return runID
	}
	if active := app.activeStrategyModelRunID("limit_up_model"); active != "" && app.strategyModelRunExists("limit_up_model", active) {
		return active
	}
	_ = app.database.Conn().QueryRow(`SELECT run_id FROM limit_up_model_runs WHERE status='success' ORDER BY updated_at DESC LIMIT 1`).Scan(&runID)
	return runID
}

func (app *App) syncLimitModelPredictionObservation(strategy string, runID string, items []LimitUpModelPrediction) {
	if len(items) == 0 || app.database == nil || app.database.Conn() == nil {
		return
	}
	tradeDate := items[0].TradeDate
	candidates := make([]strategyObservationCandidate, 0, len(items))
	for i, item := range items {
		candidates = append(candidates, strategyObservationCandidate{
			Strategy:  strategy,
			RunID:     runID,
			TradeDate: item.TradeDate,
			TSCode:    item.TSCode,
			Name:      item.Name,
			Industry:  item.Industry,
			RankNo:    i + 1,
			Score:     item.ModelScore,
			RankPct:   item.Prob,
			Price:     item.Price,
			PctChg:    item.TodayPct,
			Reason:    fmt.Sprintf("模型推荐，概率%s，分数%.1f", formatPercentForReason(item.Prob), item.ModelScore),
		})
	}
	_ = app.syncStrategyObservationPool(strategy, runID, tradeDate, candidates)
	for i := range items {
		meta := app.strategyObservationMeta(strategy, items[i].TSCode, items[i].TradeDate, items[i].Price)
		items[i].FirstSeenDate = meta.FirstSeenDate
		items[i].LastSeenDate = meta.LastSeenDate
		items[i].SeenCount = meta.SeenCount
		items[i].ObservationDays = meta.ObservationDays
		items[i].ObservationStatus = meta.ObservationStatus
		items[i].ObservationReason = meta.ObservationReason
		items[i].ObservationResult = meta.ObservationResult
	}
}

func (app *App) ListLimitBreakoutModelRuns(limit int) ([]LimitUpModelRunSummary, error) {
	if err := app.ensureDatabase(); err != nil {
		return []LimitUpModelRunSummary{}, err
	}
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, start_date, end_date, COALESCE(horizon, 0), model_type,
		       COALESCE(feature_count, 0), status, COALESCE(model_path, ''),
		       COALESCE(JSON_EXTRACT(summary_json, '$.rows') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.candidate_rows') + 0, 0),
		       COALESCE(JSON_UNQUOTE(JSON_EXTRACT(summary_json, '$.latest_date')), ''),
		       COALESCE(JSON_EXTRACT(summary_json, '$.latest_count') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.positive_rate') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.baseline_return') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.top_return') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.top_excess_return') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.top_hit_rate') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.top_limit_up_rate') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.top_drawdown') + 0, 0),
		       COALESCE(JSON_EXTRACT(summary_json, '$.rank_ic') + 0, 0),
		       COALESCE(summary_json, ''), updated_at
		FROM limit_breakout_model_runs
		ORDER BY updated_at DESC
		LIMIT ?`, limit)
	if err != nil {
		return []LimitUpModelRunSummary{}, nil
	}
	defer rows.Close()
	out := []LimitUpModelRunSummary{}
	for rows.Next() {
		var item LimitUpModelRunSummary
		var rowsValue, candidateRowsValue, latestCountValue any
		if err := rows.Scan(
			&item.RunID, &item.StartDate, &item.EndDate, &item.Horizon, &item.ModelType,
			&item.FeatureCount, &item.Status, &item.ModelPath, &rowsValue, &candidateRowsValue,
			&item.LatestDate, &latestCountValue, &item.PositiveRate, &item.BaselineReturn,
			&item.TopReturn, &item.TopExcessReturn, &item.TopHitRate, &item.TopLimitUpRate,
			&item.TopDrawdown, &item.RankIC, &item.SummaryJSON, &item.UpdatedAt,
		); err != nil {
			return out, err
		}
		item.Rows = int(anyToFloat(rowsValue))
		item.CandidateRows = int(anyToFloat(candidateRowsValue))
		item.LatestCount = int(anyToFloat(latestCountValue))
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListLimitBreakoutModelFeatures(runID string, limit int) ([]LimitUpModelFeature, error) {
	if err := app.ensureDatabase(); err != nil {
		return []LimitUpModelFeature{}, err
	}
	runID = app.resolveLatestLimitBreakoutModelRunID(runID)
	if runID == "" {
		return []LimitUpModelFeature{}, nil
	}
	if limit <= 0 || limit > 100 {
		limit = 30
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, feature, COALESCE(importance, 0), COALESCE(rank_no, 0)
		FROM limit_breakout_model_features
		WHERE run_id = ?
		ORDER BY rank_no ASC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []LimitUpModelFeature{}, nil
	}
	defer rows.Close()
	out := []LimitUpModelFeature{}
	for rows.Next() {
		var item LimitUpModelFeature
		if err := rows.Scan(&item.RunID, &item.Feature, &item.Importance, &item.RankNo); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListLimitBreakoutModelPredictions(runID string, limit int) ([]LimitUpModelPrediction, error) {
	if err := app.ensureDatabase(); err != nil {
		return []LimitUpModelPrediction{}, err
	}
	runID = app.resolveLatestLimitBreakoutModelRunID(runID)
	if runID == "" {
		return []LimitUpModelPrediction{}, nil
	}
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	rows, err := app.database.Conn().Query(`
		SELECT p.run_id, p.trade_date, p.ts_code, p.name, p.industry,
		       COALESCE(d.close, 0), COALESCE(d.high, 0), COALESCE(d.low, 0), COALESCE(d.pct_chg, 0),
		       COALESCE(p.prob, 0), COALESCE(p.model_score, 0),
		       COALESCE(p.label, 0), COALESCE(p.fwd5_return, 0), COALESCE(p.fwd5_max_return, 0),
		       COALESCE(p.max_drawdown_5d, 0), COALESCE(p.hit_limit_up_5d, 0), COALESCE(p.is_latest, 0),
		       COALESCE(p.summary_json, ''), p.updated_at
		FROM limit_breakout_model_predictions p
		LEFT JOIN data_daily_bars d ON d.ts_code = p.ts_code AND d.trade_date = p.trade_date
		WHERE p.run_id = ? AND p.is_latest = 1
		ORDER BY p.model_score DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []LimitUpModelPrediction{}, nil
	}
	defer rows.Close()
	out := []LimitUpModelPrediction{}
	for rows.Next() {
		var item LimitUpModelPrediction
		var latest int
		if err := rows.Scan(
			&item.RunID, &item.TradeDate, &item.TSCode, &item.Name, &item.Industry,
			&item.Price, &item.High, &item.Low, &item.TodayPct, &item.Prob,
			&item.ModelScore, &item.Label, &item.Fwd5Return, &item.Fwd5MaxReturn, &item.MaxDrawdown5D,
			&item.HitLimitUp5D, &latest, &item.SummaryJSON, &item.UpdatedAt,
		); err != nil {
			return out, err
		}
		item.IsLatest = latest != 0
		if item.Price <= 0 {
			item.Price = app.latestClosePrice(item.TSCode)
		}
		out = append(out, item)
	}
	if err := rows.Err(); err != nil {
		return out, err
	}
	app.syncLimitModelPredictionObservation("limit_breakout", runID, out)
	return out, nil
}

func (app *App) ListLimitBreakoutModelTimeMachineSlices(runID string, limit int) ([]LimitUpModelTimeMachineSlice, error) {
	if err := app.ensureDatabase(); err != nil {
		return []LimitUpModelTimeMachineSlice{}, err
	}
	runID = app.resolveLatestLimitBreakoutModelRunID(runID)
	if runID == "" {
		return []LimitUpModelTimeMachineSlice{}, nil
	}
	if limit <= 0 || limit > 300 {
		limit = 80
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, trade_date, COALESCE(candidate_count, 0), COALESCE(top_count, 0),
		       COALESCE(avg_return, 0), COALESCE(avg_max_return, 0), COALESCE(hit_rate, 0),
		       COALESCE(limit_up_hit_rate, 0), COALESCE(avg_drawdown, 0), COALESCE(rank_ic, 0), updated_at
		FROM limit_breakout_model_tm_slices
		WHERE run_id = ?
		ORDER BY trade_date DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return []LimitUpModelTimeMachineSlice{}, nil
	}
	defer rows.Close()
	out := []LimitUpModelTimeMachineSlice{}
	for rows.Next() {
		var item LimitUpModelTimeMachineSlice
		if err := rows.Scan(
			&item.RunID, &item.TradeDate, &item.CandidateCount, &item.TopCount, &item.AvgReturn,
			&item.AvgMaxReturn, &item.HitRate, &item.LimitUpHitRate, &item.AvgDrawdown, &item.RankIC, &item.UpdatedAt,
		); err != nil {
			return out, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) resolveLatestLimitBreakoutModelRunID(runID string) string {
	runID = strings.TrimSpace(runID)
	if runID != "" || app.database == nil {
		return runID
	}
	if active := app.activeStrategyModelRunID("limit_breakout_model"); active != "" && app.strategyModelRunExists("limit_breakout_model", active) {
		return active
	}
	_ = app.database.Conn().QueryRow(`SELECT run_id FROM limit_breakout_model_runs WHERE status='success' ORDER BY updated_at DESC LIMIT 1`).Scan(&runID)
	return runID
}

func (app *App) latestFactorRunID() (string, error) {
	row := app.database.Conn().QueryRow(`SELECT run_id FROM factor_research_runs ORDER BY updated_at DESC LIMIT 1`)
	var runID string
	if err := row.Scan(&runID); err != nil {
		return "", nil
	}
	return runID, nil
}

func (app *App) GetLimitSignalEvaluationRunStatus() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	return app.positionService.GetRunStatus("limit_signal_evaluation")
}

func (app *App) RunLimitSignalEvaluation() error {
	if err := app.ensureDatabase(); err != nil {
		return err
	}
	if status, err := app.GetLimitSignalEvaluationRunStatus(); err == nil && status.State == "running" {
		return errors.New("涨停策略评估正在运行")
	}
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return errors.New("数据路径未设置")
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	dbPath := filepath.Join(dataPath, "meta.db")
	logDir := filepath.Join(dataPath, "logs", "limit_signal_evaluation")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return err
	}
	logPath := filepath.Join(logDir, time.Now().Format("20060102_150405")+".log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	now := time.Now().Format(time.RFC3339)
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{"task", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
		),
		"limit_signal_evaluation", "running", 0, 100, "prepare", "启动涨停回看评估", "", now, now, "",
	)
	app.ensureRunStatusTaskType("limit_signal_evaluation")
	args := []string{
		"scripts/evaluate_limit_signals.py",
		"--data-path", dataPath,
		"--db-path", dbPath,
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv(dbPath)...)...)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		finishedAt := time.Now().Format(time.RFC3339)
		_, _ = app.database.Conn().Exec(
			`UPDATE task_run_status SET state='error', message=?, updated_at=?, finished_at=? WHERE task='limit_signal_evaluation'`,
			err.Error(),
			finishedAt,
			finishedAt,
		)
		return err
	}
	go app.waitLimitSignalEvaluation(cmd, logFile, logPath)
	return nil
}

func (app *App) waitLimitSignalEvaluation(cmd *exec.Cmd, logFile *os.File, logPath string) {
	err := cmd.Wait()
	_ = logFile.Close()
	if err == nil || app.database == nil {
		return
	}
	status, statusErr := app.GetLimitSignalEvaluationRunStatus()
	if statusErr == nil && status.State != "running" {
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
		"limit_signal_evaluation", "error", 0, 0, "", "", "评估进程已退出: "+err.Error()+"，日志: "+logPath, now, now, now,
	)
	app.ensureRunStatusTaskType("limit_signal_evaluation")
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
	summary, err := app.positionService.GetSummary(app.settings.DataPath)
	if err != nil {
		return nil, err
	}
	app.enrichPositionSources(&summary)
	return summary.Positions, nil
}

func (app *App) ListT0Recommendations(limit int) ([]T0Recommendation, error) {
	if err := app.ensureDatabase(); err != nil {
		return nil, err
	}
	runID := app.resolveLatestT0DailyRunID("")
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	rows, err := app.database.Conn().Query(`
		SELECT h.ts_code, COALESCE(NULLIF(h.name,''), c.name, ''), COALESCE(NULLIF(h.industry,''), c.industry, ''),
		       h.shares, h.avg_cost, h.last_price, h.weight,
		       COALESCE(c.trade_date,''), COALESCE(c.action,''), COALESCE(c.score,0), COALESCE(c.state,''),
		       COALESCE(c.setup,''), COALESCE(c.first_action,''), COALESCE(c.price, h.last_price),
		       COALESCE(c.reduce_price,0), COALESCE(c.buy_price,0), COALESCE(c.stop_price,0), COALESCE(c.t_ratio,0),
		       COALESCE(c.today_pct,0), COALESCE(c.return_5d,0), COALESCE(c.return_20d,0),
		       COALESCE(c.avg_range_20d,0), COALESCE(c.drawdown_20d,0), COALESCE(c.amount,0),
		       COALESCE(c.expected_edge,0), COALESCE(c.plan_json,''), COALESCE(c.reasons_json,'[]'), COALESCE(c.risks_json,'[]'), COALESCE(c.generated_at,'')
		FROM portfolio_pool_holdings h
		LEFT JOIN t0_daily_candidates c ON c.ts_code = h.ts_code
			AND c.run_id = ?
		WHERE h.shares > 0
		ORDER BY COALESCE(c.score,0) DESC, h.weight DESC, h.market_value DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]T0Recommendation, 0)
	for rows.Next() {
		var item T0Recommendation
		var reasonsJSON string
		var risksJSON string
		if err := rows.Scan(
			&item.TSCode, &item.Name, &item.Industry, &item.Shares, &item.AvgCost, &item.Price, &item.PositionWeight,
			&item.TradeDate, &item.Action, &item.Score, &item.State, &item.Setup, &item.FirstAction, &item.Price,
			&item.ReducePrice, &item.BuyBackPrice, &item.StopPrice, &item.TRatio, &item.TodayPct, &item.Return5, &item.Return20,
			&item.AvgRange20, &item.Drawdown20, &item.Amount, &item.ExpectedEdge, &item.PlanJSON, &reasonsJSON, &risksJSON, &item.GeneratedAt,
		); err != nil {
			return nil, err
		}
		if item.Price <= 0 {
			item.Price = app.latestClosePrice(item.TSCode)
		}
		item.MaxT0Shares = (int(float64(item.Shares)*0.3) / 100) * 100
		band := clamp(item.AvgRange20*0.55, 0.008, 0.035)
		if item.ReducePrice <= 0 {
			item.ReducePrice = roundPrice(item.Price * (1 + band))
		}
		if item.BuyBackPrice <= 0 {
			item.BuyBackPrice = roundPrice(item.Price * (1 - band))
		}
		if item.StopPrice <= 0 {
			item.StopPrice = roundPrice(item.Price * (1 - clamp(item.AvgRange20*0.9, 0.018, 0.06)))
		}
		if item.Action == "" {
			item.Action = "待评估"
			item.Recommendation = "请先运行日线做T评估"
		} else if item.Score >= 70 && item.MaxT0Shares >= 100 && item.ExpectedEdge > 0 {
			item.Action = "适合做T"
			item.Recommendation = "按日线计划等待高抛/低吸区间"
		} else if item.Score >= 52 && item.MaxT0Shares >= 100 {
			item.Action = "观察"
			item.Recommendation = "仅做小仓位观察，不强行触发"
		} else {
			item.Action = "不建议"
			item.Recommendation = "日线空间或底仓不足"
		}
		item.Reasons = parseJSONStringList(reasonsJSON)
		item.Risks = parseJSONStringList(risksJSON)
		if item.MaxT0Shares < 100 {
			item.Risks = append(item.Risks, "底仓不足 100 股整数，不适合机械做T")
		}
		out = append(out, item)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	app.syncT0RecommendationObservation(out)
	return out, nil
}

func (app *App) ListT0DataPullCandidates(limit int) ([]T0DataPullCandidate, error) {
	if err := app.ensureDatabase(); err != nil {
		return nil, err
	}
	runID := app.resolveLatestT0DailyRunID("")
	if limit <= 0 || limit > 300 {
		limit = 100
	}
	rows, err := app.database.Conn().Query(`
		SELECT ts_code, name, industry, trade_date, action, score, state, setup, first_action,
		       price, reduce_price, buy_price, stop_price, t_ratio, today_pct, return_5d, return_20d,
		       avg_range_20d, drawdown_20d, amount, avg_amount_20d, expected_edge, target_freq, lookback_days,
		       plan_json, reasons_json, risks_json, generated_at
		FROM t0_daily_candidates
		WHERE run_id = ?
		ORDER BY score DESC, avg_amount_20d DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]T0DataPullCandidate, 0)
	for rows.Next() {
		var item T0DataPullCandidate
		var reasonsJSON string
		var risksJSON string
		if err := rows.Scan(
			&item.TSCode, &item.Name, &item.Industry, &item.TradeDate, &item.Action, &item.Score, &item.State,
			&item.Setup, &item.FirstAction, &item.Price, &item.ReducePrice, &item.BuyPrice, &item.StopPrice,
			&item.TRatio, &item.TodayPct, &item.Return5, &item.Return20, &item.AvgRange20, &item.Drawdown20,
			&item.Amount, &item.AvgAmount20, &item.ExpectedEdge, &item.TargetFreq, &item.LookbackDays,
			&item.PlanJSON, &reasonsJSON, &risksJSON, &item.GeneratedAt,
		); err != nil {
			return nil, err
		}
		if item.Price <= 0 {
			item.Price = app.latestClosePrice(item.TSCode)
		}
		band := clamp(item.AvgRange20*0.55, 0.008, 0.04)
		if item.ReducePrice <= 0 {
			item.ReducePrice = roundPrice(item.Price * (1 + band))
		}
		if item.BuyPrice <= 0 {
			item.BuyPrice = roundPrice(item.Price * (1 - band))
		}
		if item.StopPrice <= 0 {
			item.StopPrice = roundPrice(item.Price * (1 - clamp(item.AvgRange20*0.9, 0.018, 0.06)))
		}
		item.Reasons = parseJSONStringList(reasonsJSON)
		item.Risks = parseJSONStringList(risksJSON)
		out = append(out, item)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	app.syncT0DataPullObservation(out)
	return out, nil
}

func (app *App) ListT0DailyRuns(limit int) ([]T0DailyRunSummary, error) {
	if err := app.ensureDatabase(); err != nil {
		return nil, err
	}
	if limit <= 0 || limit > 50 {
		limit = 10
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, trade_date, status, candidate_count, backtest_count, summary_json, created_at, updated_at
		FROM t0_daily_runs
		ORDER BY updated_at DESC
		LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]T0DailyRunSummary, 0)
	for rows.Next() {
		var item T0DailyRunSummary
		if err := rows.Scan(&item.RunID, &item.TradeDate, &item.Status, &item.CandidateCount, &item.BacktestCount, &item.SummaryJSON, &item.CreatedAt, &item.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return out, nil
}

func (app *App) resolveLatestT0DailyRunID(runID string) string {
	runID = strings.TrimSpace(runID)
	if runID != "" || app.database == nil {
		return runID
	}
	if active := app.activeStrategyModelRunID("t0_daily"); active != "" && app.strategyModelRunExists("t0_daily", active) {
		return active
	}
	_ = app.database.Conn().QueryRow(`SELECT run_id FROM t0_daily_runs WHERE status='success' ORDER BY updated_at DESC LIMIT 1`).Scan(&runID)
	return runID
}

func (app *App) syncT0DataPullObservation(items []T0DataPullCandidate) {
	if len(items) == 0 || app.database == nil || app.database.Conn() == nil {
		return
	}
	runID := app.resolveLatestT0DailyRunID("")
	if runID == "" {
		runID = "t0_daily_latest"
	}
	tradeDate := items[0].TradeDate
	candidates := make([]strategyObservationCandidate, 0, len(items))
	for i, item := range items {
		reason := firstNonEmpty(item.Setup, item.FirstAction, item.Action)
		if len(item.Reasons) > 0 {
			reason = strings.Join(item.Reasons[:minInt(len(item.Reasons), 2)], "；")
		}
		candidates = append(candidates, strategyObservationCandidate{
			Strategy:  "t0_daily",
			RunID:     runID,
			TradeDate: item.TradeDate,
			TSCode:    item.TSCode,
			Name:      item.Name,
			Industry:  item.Industry,
			RankNo:    i + 1,
			Score:     item.Score,
			RankPct:   item.Score / 100,
			Price:     item.Price,
			PctChg:    item.TodayPct,
			Reason:    reason,
		})
	}
	_ = app.syncStrategyObservationPool("t0_daily", runID, tradeDate, candidates)
	for i := range items {
		meta := app.strategyObservationMeta("t0_daily", items[i].TSCode, items[i].TradeDate, items[i].Price)
		items[i].FirstSeenDate = meta.FirstSeenDate
		items[i].LastSeenDate = meta.LastSeenDate
		items[i].SeenCount = meta.SeenCount
		items[i].ObservationDays = meta.ObservationDays
		items[i].ObservationStatus = meta.ObservationStatus
		items[i].ObservationReason = meta.ObservationReason
		items[i].ObservationResult = meta.ObservationResult
	}
}

func (app *App) syncT0RecommendationObservation(items []T0Recommendation) {
	if len(items) == 0 || app.database == nil || app.database.Conn() == nil {
		return
	}
	for i := range items {
		meta := app.strategyObservationMeta("t0_daily", items[i].TSCode, items[i].TradeDate, items[i].Price)
		items[i].FirstSeenDate = meta.FirstSeenDate
		items[i].LastSeenDate = meta.LastSeenDate
		items[i].SeenCount = meta.SeenCount
		items[i].ObservationDays = meta.ObservationDays
		items[i].ObservationStatus = meta.ObservationStatus
		items[i].ObservationReason = meta.ObservationReason
		items[i].ObservationResult = meta.ObservationResult
	}
}

func (app *App) ListT0DailyBacktests(limit int) ([]T0DailyBacktest, error) {
	if err := app.ensureDatabase(); err != nil {
		return nil, err
	}
	runID := app.resolveLatestT0DailyRunID("")
	if limit <= 0 || limit > 300 {
		limit = 100
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, ts_code, name, industry, n_days, n_candidates, two_sided_rate, one_sided_rate,
		       avg_edge, total_edge, avg_next_range, score, summary_json, updated_at
		FROM t0_daily_backtests
		WHERE run_id = ?
		ORDER BY score DESC, two_sided_rate DESC
		LIMIT ?`, runID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]T0DailyBacktest, 0)
	for rows.Next() {
		var item T0DailyBacktest
		if err := rows.Scan(
			&item.RunID, &item.TSCode, &item.Name, &item.Industry, &item.NDays, &item.NCandidates,
			&item.TwoSidedRate, &item.OneSidedRate, &item.AvgEdge, &item.TotalEdge, &item.AvgNextRange,
			&item.Score, &item.SummaryJSON, &item.UpdatedAt,
		); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) ListT0TimeMachineResults(limit int) ([]T0TimeMachineResult, error) {
	if err := app.ensureDatabase(); err != nil {
		return nil, err
	}
	if limit <= 0 || limit > 300 {
		limit = 100
	}
	rows, err := app.database.Conn().Query(`
		SELECT run_id, ts_code, name, industry, as_of_date, eval_start_date, eval_end_date, score,
		       n_eval_days, two_sided_count, one_sided_count, t0_edge, avg_t0_edge, underlying_return,
		       combined_return, max_drawdown, summary_json, updated_at
		FROM t0_daily_time_machine_results
		WHERE run_id = (SELECT run_id FROM t0_daily_time_machine_runs WHERE status='success' ORDER BY updated_at DESC LIMIT 1)
		ORDER BY combined_return DESC, t0_edge DESC
		LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]T0TimeMachineResult, 0)
	for rows.Next() {
		var item T0TimeMachineResult
		if err := rows.Scan(
			&item.RunID, &item.TSCode, &item.Name, &item.Industry, &item.AsOfDate, &item.EvalStartDate,
			&item.EvalEndDate, &item.Score, &item.NEvalDays, &item.TwoSidedCount, &item.OneSidedCount,
			&item.T0Edge, &item.AvgT0Edge, &item.UnderlyingReturn, &item.CombinedReturn, &item.MaxDrawdown,
			&item.SummaryJSON, &item.UpdatedAt,
		); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (app *App) RunT0DailyResearch() error {
	if err := app.ensureDatabase(); err != nil {
		return err
	}
	if status, err := app.GetT0DailyResearchStatus(); err == nil && status.State == "running" {
		return errors.New("日线做T研究正在运行")
	}
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return errors.New("数据路径未设置")
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	dbPath := filepath.Join(dataPath, "meta.db")
	logDir := filepath.Join(dataPath, "logs", "t0_daily_research")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return err
	}
	logPath := filepath.Join(logDir, time.Now().Format("20060102_150405")+".log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	now := time.Now().Format(time.RFC3339)
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{"task", "task_type", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"task_type", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
		),
		"t0_daily_research", "market_scan", "running", 0, 5, "prepare", "启动日线做T研究", "", now, now, "",
	)
	args := []string{
		"scripts/t0_daily_worker.py",
		"--data-path", dataPath,
		"--db-path", dbPath,
		"--lookback", "120",
		"--history-days", "520",
		"--limit", "120",
		"--backtest-limit", "120",
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv(dbPath)...)...)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		finishedAt := time.Now().Format(time.RFC3339)
		_, _ = app.database.Conn().Exec(
			`UPDATE task_run_status SET state='error', message=?, updated_at=?, finished_at=? WHERE task='t0_daily_research'`,
			err.Error(),
			finishedAt,
			finishedAt,
		)
		return err
	}
	go app.waitT0DailyResearch(cmd, logFile, logPath)
	return nil
}

func (app *App) RunT0TimeMachine() error {
	if err := app.ensureDatabase(); err != nil {
		return err
	}
	if status, err := app.GetT0TimeMachineStatus(); err == nil && status.State == "running" {
		return errors.New("做T时光机正在运行")
	}
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return errors.New("数据路径未设置")
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	dbPath := filepath.Join(dataPath, "meta.db")
	logDir := filepath.Join(dataPath, "logs", "t0_daily_timemachine")
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return err
	}
	logPath := filepath.Join(logDir, time.Now().Format("20060102_150405")+".log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	now := time.Now().Format(time.RFC3339)
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{"task", "task_type", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"task_type", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
		),
		"t0_daily_timemachine", "market_scan", "running", 0, 5, "prepare", "启动做T时光机", "", now, now, "",
	)
	args := []string{
		"scripts/t0_daily_worker.py",
		"--mode", "time_machine",
		"--data-path", dataPath,
		"--db-path", dbPath,
		"--lookback-grid", "40,60,80,120",
		"--eval-days-grid", "10,20,40",
		"--anchor-count", "4",
		"--anchor-step", "20",
		"--limit", "80",
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv(dbPath)...)...)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		finishedAt := time.Now().Format(time.RFC3339)
		_, _ = app.database.Conn().Exec(
			`UPDATE task_run_status SET state='error', message=?, updated_at=?, finished_at=? WHERE task='t0_daily_timemachine'`,
			err.Error(),
			finishedAt,
			finishedAt,
		)
		return err
	}
	go app.waitT0TimeMachine(cmd, logFile, logPath)
	return nil
}

func (app *App) waitT0TimeMachine(cmd *exec.Cmd, logFile *os.File, logPath string) {
	err := cmd.Wait()
	_ = logFile.Close()
	if err == nil || app.database == nil {
		return
	}
	status, statusErr := app.GetT0TimeMachineStatus()
	if statusErr == nil && status.State != "running" {
		return
	}
	app.markPythonStatusTaskError("t0_daily_timemachine", "做T时光机进程已退出: "+err.Error()+"，日志: "+logPath)
}

func (app *App) waitT0DailyResearch(cmd *exec.Cmd, logFile *os.File, logPath string) {
	err := cmd.Wait()
	_ = logFile.Close()
	if err == nil || app.database == nil {
		return
	}
	status, statusErr := app.GetT0DailyResearchStatus()
	if statusErr == nil && status.State != "running" {
		return
	}
	app.markPythonStatusTaskError("t0_daily_research", "日线做T研究进程已退出: "+err.Error()+"，日志: "+logPath)
}

func (app *App) GetT0DailyResearchStatus() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	return app.positionService.GetRunStatus("t0_daily_research")
}

func (app *App) GetT0TimeMachineStatus() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	return app.positionService.GetRunStatus("t0_daily_timemachine")
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
	app.applyLatestExecutionPrices(trades)
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
		return app.positionService.GetSummary(app.settings.DataPath)
	}
	prices := map[string]float64{}
	for _, holding := range holdings {
		code := strings.TrimSpace(holding.TSCode)
		if code == "" {
			continue
		}
		price, err := app.fetchDCRealtimePrice(code)
		if err != nil {
			continue
		}
		if price > 0 {
			prices[code] = price
		}
		time.Sleep(150 * time.Millisecond)
	}
	if len(prices) == 0 {
		return position.Summary{}, errors.New("东方财富 dc 实时行情未返回有效价格，已保留日线收盘价")
	}
	return app.positionService.RefreshValuationWithPrices(prices, time.Now().Format("20060102"))
}

func (app *App) ClearPositionPool() (position.Summary, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.Summary{}, err
	}
	return app.positionService.ClearPool(app.settings.DataPath, app.settings.DefaultInitialCash)
}

func (app *App) applyLatestExecutionPrices(trades []position.TradeRequest) {
	for i := range trades {
		price := 0.0
		if realtimePrice, err := app.fetchDCRealtimePrice(trades[i].TSCode); err == nil && realtimePrice > 0 {
			price = realtimePrice
		}
		if price <= 0 {
			price = app.latestClosePrice(trades[i].TSCode)
		}
		if price > 0 {
			trades[i].Price = price
		}
	}
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
	ctx, cancel := context.WithTimeout(baseCtx, 15*time.Second)
	defer cancel()
	url := fmt.Sprintf("https://push2.eastmoney.com/api/qt/stock/get?secid=%s&fields=f43,f58,f60", secID)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return 0, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0")
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			lastErr = err
			time.Sleep(time.Duration(attempt+1) * 300 * time.Millisecond)
			continue
		}
		var payload struct {
			Data map[string]any `json:"data"`
		}
		decodeErr := json.NewDecoder(resp.Body).Decode(&payload)
		_ = resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			lastErr = fmt.Errorf("dc quote http %d", resp.StatusCode)
			time.Sleep(time.Duration(attempt+1) * 300 * time.Millisecond)
			continue
		}
		if decodeErr != nil {
			lastErr = decodeErr
			time.Sleep(time.Duration(attempt+1) * 300 * time.Millisecond)
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

func (app *App) buildAccountRebalanceRecommendation() (position.Recommendation, error) {
	if app.database == nil {
		return position.Recommendation{}, errors.New("database is not initialized")
	}
	summary, err := app.positionService.GetSummary(app.settings.DataPath)
	if err != nil {
		return position.Recommendation{}, err
	}
	targets := map[string]*accountTarget{}
	date := app.latestRecommendationDate()
	activeVersions := app.accountRebalanceStrategyVersions()
	app.mergeFactorTargets(targets)
	app.mergeLimitUpModelTargets(targets)
	app.mergeBreakoutModelTargets(targets)
	app.mergeT0Targets(targets, summary)
	rows := app.buildAccountRebalanceRows(targets, summary, date)
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
	app.mergeFactorTargets(targets)
	app.mergeLimitUpModelTargets(targets)
	app.mergeBreakoutModelTargets(targets)
	app.mergeT0Targets(targets, *summary)
	for i := range summary.Positions {
		item := &summary.Positions[i]
		if target := targets[item.TSCode]; target != nil && len(target.Sources) > 0 {
			item.Sources = compactSources(target.Sources)
			continue
		}
		item.Sources = []position.Source{{Strategy: "account_rebalance", Weight: item.Weight}}
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
	if err := app.database.Conn().QueryRow(`SELECT COALESCE(MAX(trade_date),'') FROM market_limit_momentum_cache`).Scan(&date); err == nil && date != "" {
		dates = append(dates, date)
	}
	if err := app.database.Conn().QueryRow(`SELECT COALESCE(MAX(latest_date),'') FROM market_limit_breakout_cache`).Scan(&date); err == nil && date != "" {
		dates = append(dates, date)
	}
	if err := app.database.Conn().QueryRow(`SELECT COALESCE(MAX(trade_date),'') FROM limit_up_model_predictions WHERE is_latest = 1`).Scan(&date); err == nil && date != "" {
		dates = append(dates, date)
	}
	if err := app.database.Conn().QueryRow(`SELECT COALESCE(MAX(trade_date),'') FROM limit_breakout_model_predictions WHERE is_latest = 1`).Scan(&date); err == nil && date != "" {
		dates = append(dates, date)
	}
	if err := app.database.Conn().QueryRow(`SELECT COALESCE(MAX(trade_date),'') FROM factor_latest_predictions`).Scan(&date); err == nil && date != "" {
		dates = append(dates, date)
	}
	if err := app.database.Conn().QueryRow(`SELECT COALESCE(MAX(trade_date),'') FROM t0_daily_candidates`).Scan(&date); err == nil && date != "" {
		dates = append(dates, date)
	}
	if err := app.database.Conn().QueryRow(`SELECT COALESCE(MAX(date),'') FROM rec_daily_recommendations`).Scan(&date); err == nil && date != "" {
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
		{Strategy: "account_rebalance", Label: "账户调仓决策器", Version: 1, Mode: "active", Weight: 1},
		{Strategy: "ml_factor_ranker", Label: "通用因子截面", Version: 1, Mode: "source", Weight: 0.25},
		{Strategy: "limit_up_model", Label: "涨停预警模型", Version: 1, Mode: "source", Weight: 0.25},
		{Strategy: "limit_breakout_model", Label: "横盘预警模型", Version: 1, Mode: "source", Weight: 0.25},
		{Strategy: "t0_daily", Label: "做T助手", Version: 1, Mode: "source", Weight: 0.2},
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

func (app *App) mergeBaseRecommendationTargets(targets map[string]*accountTarget) {
	rec, err := app.positionService.GetRecommendation(app.settings.DataPath)
	if err != nil {
		return
	}
	for _, row := range rec.Rows {
		if row.ToWeight <= 0 || row.Action == "清仓" {
			continue
		}
		weight := math.Min(row.ToWeight, 0.08)
		app.addTargetWeight(targets, row.TSCode, row.Name, row.Industry, row.Price, row.PctChg, weight, "daily_recommendation")
	}
}

func (app *App) mergeFactorTargets(targets map[string]*accountTarget) {
	runID := strings.TrimSpace(app.latestFactorRunIDValue())
	if runID == "" {
		return
	}
	rows, err := app.database.Conn().Query(`
		SELECT p.ts_code, COALESCE(s.name, ''), COALESCE(s.industry, ''),
		       COALESCE(d.close, 0), COALESCE(d.pct_chg, 0),
		       COALESCE(p.pred_score, 0), COALESCE(p.pred_rank, 0)
		FROM factor_latest_predictions p
		LEFT JOIN data_stock_basic s ON s.ts_code = p.ts_code
		LEFT JOIN data_daily_bars d ON d.ts_code = p.ts_code AND d.trade_date = p.trade_date
		WHERE p.run_id = ? AND COALESCE(p.is_top20, 0) = 1
		ORDER BY p.pred_score DESC
		LIMIT 10`, runID)
	if err != nil {
		return
	}
	defer rows.Close()
	total := 0.0
	for rows.Next() {
		if total >= 0.20 {
			break
		}
		var tsCode, name, industry string
		var price, pctChg, score, rankPct float64
		if err := rows.Scan(&tsCode, &name, &industry, &price, &pctChg, &score, &rankPct); err != nil {
			continue
		}
		if price <= 0 {
			price = app.latestClosePrice(tsCode)
		}
		if price <= 0 {
			continue
		}
		weight := 0.02
		if score > 0 {
			weight = clamp(score/40, 0.015, 0.035)
		} else if rankPct > 0 {
			weight = clamp(rankPct/30, 0.015, 0.035)
		}
		if total+weight > 0.20 {
			weight = 0.20 - total
		}
		buyTrigger, sellTarget, stopPrice := factorTradePlanPrices(price, rankPct)
		app.addTargetPlan(targets, tsCode, name, industry, price, pctChg, weight, "ml_factor_ranker", buyTrigger, sellTarget, stopPrice)
		total += weight
	}
}

func factorTradePlanPrices(price float64, rankPct float64) (float64, float64, float64) {
	if price <= 0 {
		return 0, 0, 0
	}
	if rankPct <= 0 {
		rankPct = 0.8
	}
	buyBand := clamp(0.026-rankPct*0.014, 0.006, 0.025)
	sellBand := clamp(0.028+rankPct*0.04, 0.025, 0.08)
	stopBand := clamp(0.075-math.Min(rankPct, 1)*0.025, 0.035, 0.08)
	return roundPrice(price * (1 - buyBand)), roundPrice(price * (1 + sellBand)), roundPrice(price * (1 - stopBand))
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

func (app *App) mergeLimitUpModelTargets(targets map[string]*accountTarget) {
	run := app.latestLimitUpModelRunSummary()
	if !limitModelTradeLayerPass(run, "momentum") {
		return
	}
	items, err := app.ListLimitUpModelPredictions("", 10)
	if err != nil {
		return
	}
	total := 0.0
	for _, item := range items {
		if total >= 0.12 {
			break
		}
		if item.Prob < 0.62 || item.ModelScore < 72 || item.Price <= 0 {
			continue
		}
		weight := clamp((item.ModelScore-65)/700+0.018, 0.02, 0.035)
		if total+weight > 0.12 {
			weight = 0.12 - total
		}
		buyTrigger, sellTarget, stopPrice := limitModelTradePlanPrices(item.Price, "momentum")
		app.addTargetPlan(targets, item.TSCode, item.Name, item.Industry, item.Price, item.TodayPct, weight, "limit_up_model", buyTrigger, sellTarget, stopPrice)
		total += weight
	}
}

func (app *App) mergeBreakoutModelTargets(targets map[string]*accountTarget) {
	run := app.latestLimitBreakoutModelRunSummary()
	if !limitModelTradeLayerPass(run, "breakout") {
		return
	}
	items, err := app.ListLimitBreakoutModelPredictions("", 10)
	if err != nil {
		return
	}
	total := 0.0
	for _, item := range items {
		if total >= 0.12 {
			break
		}
		if item.Prob < 0.58 || item.ModelScore < 72 || item.Price <= 0 {
			continue
		}
		weight := clamp((item.ModelScore-65)/800+0.018, 0.02, 0.035)
		if total+weight > 0.12 {
			weight = 0.12 - total
		}
		buyTrigger, sellTarget, stopPrice := limitModelTradePlanPrices(item.Price, "breakout")
		app.addTargetPlan(targets, item.TSCode, item.Name, item.Industry, item.Price, item.TodayPct, weight, "limit_breakout_model", buyTrigger, sellTarget, stopPrice)
		total += weight
	}
}

func limitModelTradePlanPrices(price float64, variant string) (float64, float64, float64) {
	if price <= 0 {
		return 0, 0, 0
	}
	if variant == "breakout" {
		return roundPrice(price * 0.985), roundPrice(price * 1.08), roundPrice(price * 0.95)
	}
	return roundPrice(price * 1.015), roundPrice(price * 1.10), roundPrice(price * 0.95)
}

func (app *App) latestLimitUpModelRunSummary() *LimitUpModelRunSummary {
	runID := app.resolveLatestLimitUpModelRunID("")
	rows, err := app.ListLimitUpModelRuns(20)
	if err != nil || len(rows) == 0 {
		return nil
	}
	if runID != "" {
		for i := range rows {
			if rows[i].RunID == runID {
				return &rows[i]
			}
		}
	}
	return &rows[0]
}

func (app *App) latestLimitBreakoutModelRunSummary() *LimitUpModelRunSummary {
	runID := app.resolveLatestLimitBreakoutModelRunID("")
	rows, err := app.ListLimitBreakoutModelRuns(20)
	if err != nil || len(rows) == 0 {
		return nil
	}
	if runID != "" {
		for i := range rows {
			if rows[i].RunID == runID {
				return &rows[i]
			}
		}
	}
	return &rows[0]
}

func limitModelTradeLayerPass(run *LimitUpModelRunSummary, variant string) bool {
	if run == nil || run.TopReturn <= 0 || run.TopExcessReturn <= 0 {
		return false
	}
	trading := bestLimitTradingValidation(run.SummaryJSON)
	if trading == nil || trading.AvgReturn <= 0 || trading.CompoundReturn <= 0 {
		return false
	}
	if variant == "momentum" {
		return trading.MaxDrawdown > -0.35
	}
	return true
}

type limitTradingValidation struct {
	AvgReturn      float64 `json:"avg_return"`
	CompoundReturn float64 `json:"compound_return"`
	MaxDrawdown    float64 `json:"max_drawdown"`
}

func bestLimitTradingValidation(summaryJSON string) *limitTradingValidation {
	var payload struct {
		TradingValidation []limitTradingValidation `json:"trading_validation"`
	}
	if err := json.Unmarshal([]byte(strings.TrimSpace(summaryJSON)), &payload); err != nil {
		return nil
	}
	var best *limitTradingValidation
	for i := range payload.TradingValidation {
		item := &payload.TradingValidation[i]
		if best == nil || item.CompoundReturn > best.CompoundReturn {
			best = item
		}
	}
	return best
}

func (app *App) mergeT0Targets(targets map[string]*accountTarget, summary position.Summary) {
	currentWeight := map[string]float64{}
	for _, holding := range summary.Positions {
		currentWeight[holding.TSCode] = holding.Weight
	}
	runID := app.resolveLatestT0DailyRunID("")
	rows, err := app.database.Conn().Query(`
		SELECT ts_code, COALESCE(name,''), COALESCE(industry,''), COALESCE(score,0),
		       COALESCE(action,''), COALESCE(price,0), COALESCE(today_pct,0),
		       COALESCE(expected_edge,0), COALESCE(t_ratio,0), COALESCE(risks_json,'[]'),
		       COALESCE(buy_price,0), COALESCE(reduce_price,0), COALESCE(stop_price,0)
		FROM t0_daily_candidates
		WHERE run_id = ?
		ORDER BY score DESC
		LIMIT 10`, runID)
	if err != nil {
		return
	}
	defer rows.Close()
	for rows.Next() {
		var tsCode, name, industry, action string
		var risksJSON string
		var score, price, pctChg, expectedEdge, tRatio, buyTrigger, sellTarget, stopPrice float64
		if err := rows.Scan(&tsCode, &name, &industry, &score, &action, &price, &pctChg, &expectedEdge, &tRatio, &risksJSON, &buyTrigger, &sellTarget, &stopPrice); err != nil {
			continue
		}
		if price <= 0 {
			price = app.latestClosePrice(tsCode)
		}
		if price <= 0 {
			continue
		}
		base, ok := currentWeight[tsCode]
		weight := 0.0
		if ok {
			if score < 58 {
				continue
			}
			weight = math.Min(base, 0.08)
			if strings.Contains(action, "不建议") || score < 65 {
				weight = math.Min(base*0.7, weight)
			}
		} else {
			if !isT0TrialCandidate(action, score, expectedEdge, tRatio, parseJSONStringList(risksJSON)) {
				continue
			}
			assets := summary.TotalAssets
			if assets <= 0 {
				assets = app.settings.DefaultInitialCash
			}
			if assets <= 0 {
				continue
			}
			weight = clamp(10000/assets, 0.005, 0.035)
		}
		if buyTrigger <= 0 || sellTarget <= 0 || stopPrice <= 0 {
			fallbackBuy, fallbackSell, fallbackStop := t0TradePlanPrices(price)
			if buyTrigger <= 0 {
				buyTrigger = fallbackBuy
			}
			if sellTarget <= 0 {
				sellTarget = fallbackSell
			}
			if stopPrice <= 0 {
				stopPrice = fallbackStop
			}
		}
		app.addTargetPlan(targets, tsCode, name, industry, price, pctChg, weight, "t0_daily", buyTrigger, sellTarget, stopPrice)
	}
}

func t0TradePlanPrices(price float64) (float64, float64, float64) {
	if price <= 0 {
		return 0, 0, 0
	}
	return roundPrice(price * 0.98), roundPrice(price * 1.02), roundPrice(price * 0.96)
}

func isT0TrialCandidate(action string, score float64, expectedEdge float64, tRatio float64, risks []string) bool {
	label := strings.TrimSpace(action)
	if label == "可试仓" || label == "优先计划" {
		return true
	}
	if label == "暂缓" || label == "不建议" || label == "放弃" {
		return false
	}
	for _, risk := range risks {
		if strings.Contains(risk, "剔除") || strings.Contains(risk, "停手") || strings.Contains(risk, "为负") {
			return false
		}
	}
	return score >= 76 && expectedEdge > 0 && tRatio > 0
}

func (app *App) buildAccountRebalanceRows(targets map[string]*accountTarget, summary position.Summary, decisionDate string) []position.RecommendationItem {
	current := map[string]position.Position{}
	for _, item := range summary.Positions {
		current[item.TSCode] = item
		if _, ok := targets[item.TSCode]; !ok {
			targets[item.TSCode] = &accountTarget{
				TSCode:       item.TSCode,
				Name:         item.Name,
				Industry:     item.Industry,
				Price:        item.Price,
				TargetWeight: item.Weight,
				Sources:      []position.Source{{Strategy: "account_rebalance", Weight: item.Weight}},
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
		weights[source.Strategy] += source.Weight
	}
	out := make([]position.Source, 0, len(weights))
	for strategy, weight := range weights {
		out = append(out, position.Source{Strategy: strategy, Weight: weight})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Weight > out[j].Weight })
	return out
}

func (app *App) GeneratePositionSignal(req position.GenerateSignalRequest) (position.GenerateSignalResponse, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.GenerateSignalResponse{}, err
	}
	if _, err := app.prepareSignalPortfolioCandidate(&req); err != nil {
		return position.GenerateSignalResponse{}, err
	}
	if req.InitialCash <= 0 {
		req.InitialCash = app.settings.DefaultInitialCash
	}
	if req.RebalanceFreq <= 0 {
		req.RebalanceFreq = app.settings.DefaultRebalanceFreq
	}
	if date := app.signalTargetDate(req); date != "" && app.recommendationExists(date) {
		return position.GenerateSignalResponse{Date: date, Output: "当日信号已存在，本次复用缓存", Success: true}, nil
	}
	go app.runPositionSignalTask(req)
	return position.GenerateSignalResponse{Success: true}, nil
}

func (app *App) runPositionSignalTask(req position.GenerateSignalRequest) {
	app.signalMu.Lock()
	defer app.signalMu.Unlock()
	if app.database == nil || app.positionService == nil {
		return
	}
	if _, err := app.prepareSignalPortfolioCandidate(&req); err != nil {
		app.upsertSignalRunStatus(position.RunStatus{
			Task:       "daily_signal",
			TaskType:   "signal",
			State:      "error",
			Idx:        0,
			Total:      100,
			Stage:      "blocked",
			Name:       "缺少生产组合",
			Message:    err.Error(),
			UpdatedAt:  time.Now().Format(time.RFC3339),
			FinishedAt: time.Now().Format(time.RFC3339),
		})
		return
	}
	if date := app.signalTargetDate(req); date != "" && app.recommendationExists(date) {
		app.upsertSignalRunStatus(position.RunStatus{
			Task:       "daily_signal",
			TaskType:   "signal",
			State:      "done",
			Idx:        100,
			Total:      100,
			Stage:      "cached",
			Name:       "当日信号已存在",
			Message:    "当日信号已存在，本次复用缓存",
			UpdatedAt:  time.Now().Format(time.RFC3339),
			FinishedAt: time.Now().Format(time.RFC3339),
		})
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
	app.upsertSignalRunStatus(position.RunStatus{
		Task:      "daily_signal",
		TaskType:  "signal",
		State:     "running",
		Idx:       0,
		Total:     100,
		Stage:     "running",
		Name:      "当日信号生成",
		StartedAt: now.Format(time.RFC3339),
		UpdatedAt: now.Format(time.RFC3339),
	})
	_, err := app.positionService.GenerateSignalWithProgress(app.settings.DataPath, req, func(ev position.ProgressEvent) {
		if ev.WorkerPID > 0 && t.WorkerPID != ev.WorkerPID {
			t.WorkerPID = ev.WorkerPID
			_ = repo.UpdateRuntime(task.Task{
				ID:        t.ID,
				Status:    task.StatusRunning,
				Progress:  t.Progress,
				WorkerPID: ev.WorkerPID,
				StartedAt: t.StartedAt,
				UpdatedAt: time.Now(),
			})
		}
		progress := 0.0
		if ev.Total > 0 {
			progress = float64(ev.Idx) / float64(ev.Total)
			if ev.Stage == "done" {
				progress = float64(ev.Idx+1) / float64(ev.Total)
			}
		}
		t.Progress = progress
		_ = repo.UpdateRuntime(task.Task{
			ID:        t.ID,
			Status:    task.StatusRunning,
			Progress:  progress,
			WorkerPID: t.WorkerPID,
			StartedAt: t.StartedAt,
			UpdatedAt: time.Now(),
		})
		idx := ev.Idx
		total := ev.Total
		if total <= 0 {
			idx = int(progress * 100)
			total = 100
		}
		app.upsertSignalRunStatus(position.RunStatus{
			Task:      "daily_signal",
			TaskType:  "signal",
			State:     "running",
			Idx:       idx,
			Total:     total,
			Stage:     firstNonEmpty(ev.Stage, "running"),
			Name:      firstNonEmpty(ev.Name, "当日信号生成"),
			WorkerPID: t.WorkerPID,
			StartedAt: t.StartedAt.Format(time.RFC3339),
			UpdatedAt: time.Now().Format(time.RFC3339),
		})
	})
	if err == nil {
		if _, recErr := app.positionService.GetRecommendation(app.settings.DataPath); recErr != nil {
			err = recErr
		}
	}
	finishedAt := time.Now()
	if err != nil {
		if current, getErr := repo.Get(t.ID); getErr == nil && current.Status == task.StatusCancelled {
			return
		}
		status := task.StatusFailed
		state := "error"
		message := err.Error()
		if isSignalCancelError(err) {
			status = task.StatusCancelled
			state = "cancelled"
			message = "已取消当日信号生成"
		}
		_ = repo.UpdateRuntime(task.Task{
			ID:           t.ID,
			Status:       status,
			Progress:     1,
			ErrorMessage: message,
			StartedAt:    t.StartedAt,
			UpdatedAt:    finishedAt,
			FinishedAt:   finishedAt,
		})
		app.upsertSignalRunStatus(position.RunStatus{
			Task:       "daily_signal",
			TaskType:   "signal",
			State:      state,
			Idx:        100,
			Total:      100,
			Stage:      state,
			Name:       "当日信号生成",
			Message:    message,
			StartedAt:  t.StartedAt.Format(time.RFC3339),
			UpdatedAt:  finishedAt.Format(time.RFC3339),
			FinishedAt: finishedAt.Format(time.RFC3339),
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
	app.upsertSignalRunStatus(position.RunStatus{
		Task:       "daily_signal",
		TaskType:   "signal",
		State:      "done",
		Idx:        100,
		Total:      100,
		Stage:      "done",
		Name:       "当日信号生成",
		StartedAt:  t.StartedAt.Format(time.RFC3339),
		UpdatedAt:  finishedAt.Format(time.RFC3339),
		FinishedAt: finishedAt.Format(time.RFC3339),
	})
}

func (app *App) GetSignalRunStatus() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	status, err := app.positionService.GetRunStatus("daily_signal")
	if err != nil {
		return status, err
	}
	if status.State == "running" {
		reconciled, recErr := app.reconcileSignalRunStatus(status)
		if recErr == nil {
			return reconciled, nil
		}
		return status, nil
	}
	if app.database != nil {
		latestTask, taskErr := latestRunningTask(app.database.Conn(), task.TypeDailySignal)
		if taskErr == nil {
			return latestTask, nil
		}
	}
	return status, err
}

func (app *App) CancelPositionSignal() (position.RunStatus, error) {
	if err := app.ensurePositionService(); err != nil {
		return position.RunStatus{}, err
	}
	if app.database == nil {
		return position.RunStatus{Task: "daily_signal", TaskType: "signal", State: "idle"}, nil
	}
	now := time.Now()
	rows, err := app.database.Conn().Query(
		`SELECT id, COALESCE(worker_pid,0) FROM task_jobs
		 WHERE task_type = ? AND status = 'running'
		 ORDER BY created_at DESC`,
		string(task.TypeDailySignal),
	)
	if err != nil {
		return position.RunStatus{}, err
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var pid int
		if err := rows.Scan(&id, &pid); err != nil {
			return position.RunStatus{}, err
		}
		if pid > 0 && processExists(pid) {
			_ = worker.NewManager().Cancel(pid)
		}
		_, _ = app.database.Conn().Exec(
			`UPDATE task_jobs
			 SET status = ?, progress = 1, worker_pid = NULL, error_message = ?, finished_at = ?, updated_at = ?
			 WHERE id = ?`,
			string(task.StatusCancelled), "用户取消当日信号生成", now, now, id,
		)
	}
	if err := rows.Err(); err != nil {
		return position.RunStatus{}, err
	}
	status := position.RunStatus{
		Task:       "daily_signal",
		TaskType:   "signal",
		State:      "cancelled",
		Idx:        100,
		Total:      100,
		Stage:      "cancelled",
		Name:       "当日信号生成",
		Message:    "已取消当日信号生成",
		UpdatedAt:  now.Format(time.RFC3339),
		FinishedAt: now.Format(time.RFC3339),
	}
	app.upsertSignalRunStatus(status)
	return status, nil
}

func (app *App) requireActivePortfolioCandidate() error {
	if app.database == nil {
		return errors.New("数据库未初始化，不能生成实盘信号")
	}
	active, err := app.activePortfolioCandidate()
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return errors.New("缺少已选择的时光机组合方案：请先在评估中心完成组合优化/时光机评估，并在生成信号页选择一个组合后再生成信号")
		}
		return err
	}
	if active == nil || strings.TrimSpace(active.RunID) == "" || strings.TrimSpace(active.CandidateID) == "" {
		return errors.New("已选择组合方案缺少 run_id/candidate_id，请重新选择评估候选方案")
	}
	var status string
	var score float64
	var count int
	err = app.database.Conn().QueryRow(
		`SELECT status, score, COUNT(*) OVER()
		 FROM eval_portfolio_candidates WHERE run_id = ? AND candidate_id = ?`,
		active.RunID,
		active.CandidateID,
	).Scan(&status, &score, &count)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return errors.New("已选择组合方案在评估结果表中不存在，请重新完成时光机评估并选择候选组合")
		}
		return err
	}
	if count <= 0 || status != "ok" {
		return fmt.Errorf("已选择组合方案不可用于实盘信号：status=%s", status)
	}
	if math.IsNaN(score) || math.IsInf(score, 0) {
		return errors.New("已选择组合方案评分无效，请重新完成时光机评估")
	}
	return nil
}

func (app *App) prepareSignalPortfolioCandidate(req *position.GenerateSignalRequest) (*SignalPortfolioCandidateDTO, error) {
	if app.database == nil {
		return nil, errors.New("数据库未初始化，不能生成实盘信号")
	}
	runID := strings.TrimSpace(req.PortfolioRunID)
	candidateID := strings.TrimSpace(req.PortfolioCandidateID)
	if runID == "" || candidateID == "" {
		return nil, errors.New("请先在生成信号页选择一个时光机组合方案")
	}
	item, err := app.signalPortfolioCandidate(runID, candidateID)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, errors.New("选择的组合方案在评估结果表中不存在，请重新完成时光机评估并选择候选组合")
		}
		return nil, err
	}
	if item.Status != "ok" {
		return nil, fmt.Errorf("选择的组合方案不可用于实盘信号：status=%s", item.Status)
	}
	if math.IsNaN(item.Score) || math.IsInf(item.Score, 0) {
		return nil, errors.New("选择的组合方案评分无效，请重新完成时光机评估")
	}
	overridesJSON, err := app.signalStrategyOverridesJSON(item.Weights)
	if err != nil {
		return nil, err
	}
	req.StrategyOverridesJSON = overridesJSON
	if req.RebalanceFreq <= 0 && item.RebalanceFreq > 0 {
		req.RebalanceFreq = item.RebalanceFreq
	}
	return item, nil
}

func (app *App) signalPortfolioCandidate(runID string, candidateID string) (*SignalPortfolioCandidateDTO, error) {
	row := app.database.Conn().QueryRow(`SELECT run_id, candidate_id, `+"`rank`"+`, name, objective, status, score,
		strategies, weights_json, annual_return, max_drawdown, sharpe, calmar, avg_turnover, avg_holdings,
		rebalance_freq, COALESCE(validation_status,''), COALESCE(reason,''), COALESCE(updated_at,'')
		FROM eval_portfolio_candidates
		WHERE run_id = ? AND candidate_id = ?`, runID, candidateID)
	var item SignalPortfolioCandidateDTO
	var weightsJSON string
	var annualReturn, maxDrawdown, sharpe, calmar, avgTurnover, avgHoldings sql.NullFloat64
	if err := row.Scan(
		&item.RunID, &item.CandidateID, &item.Rank, &item.Name, &item.Objective, &item.Status, &item.Score,
		&item.Strategies, &weightsJSON, &annualReturn, &maxDrawdown, &sharpe, &calmar, &avgTurnover, &avgHoldings,
		&item.RebalanceFreq, &item.ValidationStatus, &item.Reason, &item.UpdatedAt,
	); err != nil {
		return nil, err
	}
	_ = json.Unmarshal([]byte(weightsJSON), &item.Weights)
	item.AnnualReturn = nullableFloatPtr(annualReturn)
	item.MaxDrawdown = nullableFloatPtr(maxDrawdown)
	item.Sharpe = nullableFloatPtr(sharpe)
	item.Calmar = nullableFloatPtr(calmar)
	item.AvgTurnover = nullableFloatPtr(avgTurnover)
	item.AvgHoldings = nullableFloatPtr(avgHoldings)
	return &item, nil
}

func (app *App) signalStrategyOverridesJSON(weights map[string]float64) (string, error) {
	normalized := normalizeWeights(weights)
	if len(normalized) == 0 {
		return "", errors.New("选择的组合方案没有有效策略权重")
	}
	if app.database != nil {
		app.configService.WithDatabase(app.database)
	}
	settings, err := app.configService.Load(app.settings)
	if err != nil {
		return "", err
	}
	overrides := map[string]map[string]any{}
	for name := range settings.Strategies {
		overrides[name] = map[string]any{"enabled": false, "weight": 0}
	}
	for name, weight := range normalized {
		overrides[name] = map[string]any{"enabled": true, "weight": weight}
	}
	payload, err := json.Marshal(overrides)
	if err != nil {
		return "", err
	}
	return string(payload), nil
}

func (app *App) cfgAppSettingsKeyColumn() string {
	if app.database != nil && app.database.IsMySQL() {
		return "`key`"
	}
	return "key"
}

func (app *App) signalTargetDate(req position.GenerateSignalRequest) string {
	date := strings.TrimSpace(req.Date)
	if date != "" {
		return strings.ReplaceAll(date, "-", "")
	}
	if app.database == nil {
		return ""
	}
	var latest string
	err := app.database.Conn().QueryRow(`SELECT COALESCE(MAX(trade_date), '') FROM data_daily_bars`).Scan(&latest)
	if err != nil || strings.TrimSpace(latest) == "" {
		return ""
	}
	return strings.TrimSpace(latest)
}

func (app *App) recommendationExists(date string) bool {
	if app.database == nil || strings.TrimSpace(date) == "" {
		return false
	}
	var count int
	err := app.database.Conn().QueryRow(`SELECT COUNT(*) FROM rec_daily_recommendations WHERE date = ?`, strings.TrimSpace(date)).Scan(&count)
	return err == nil && count > 0
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
		Task:      "daily_signal",
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
	if status.WorkerPID <= 0 {
		if latest, err := latestRunningTask(app.database.Conn(), task.TypeDailySignal); err == nil {
			return latest, nil
		}
	}
	now := time.Now()
	_, _ = app.database.Conn().Exec(
		`UPDATE task_jobs
		 SET status = ?, worker_pid = NULL, error_message = ?, finished_at = ?, updated_at = ?
		 WHERE task_type = ? AND status = 'running'`,
		string(task.StatusInterrupted), "worker process is no longer running", now, now, string(task.TypeDailySignal),
	)
	status.State = "error"
	status.Stage = "interrupted"
	status.Message = "当日信号生成进程已不存在，已自动清理运行状态"
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
		status.Task = "daily_signal"
	}
	if status.TaskType == "" {
		status.TaskType = "signal"
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
		FROM eval_strategy_admission WHERE run_id = ? ORDER BY strategy`, runID)
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
	row := db.QueryRow(`SELECT payload_json FROM eval_strategy_admission WHERE run_id = ? AND strategy = ?`, runID, strategyName)
	var payloadJSON string
	if err := row.Scan(&payloadJSON); err != nil {
		return ""
	}
	return payloadJSON
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
	row := db.QueryRow(`SELECT summary_json FROM eval_portfolio_runs WHERE run_id = ?`, runID)
	var summaryJSON string
	if err := row.Scan(&summaryJSON); err != nil {
		return ""
	}
	var payload map[string]any
	if err := json.Unmarshal([]byte(summaryJSON), &payload); err != nil {
		payload = map[string]any{}
	}
	rows, err := db.Query(`SELECT `+"`rank`"+`, score, annual_return, max_drawdown, sharpe, calmar, avg_turnover, avg_holdings, avg_total_mv, avg_amount, payload_json FROM eval_portfolio_candidates
		WHERE run_id = ? ORDER BY CASE WHEN `+"`rank`"+` > 0 THEN 0 ELSE 1 END, `+"`rank`"+`, score DESC`, runID)
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
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath, "TUSHARE_TOKEN=" + token}, app.pythonDBEnv(dbPath)...)...)
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		app.markPythonStatusTaskError("data_update", "数据更新进程启动失败: "+err.Error()+"，日志: "+logPath)
		return err
	}
	app.markDataUpdateWorkerStarted(cmd.Process.Pid)
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
	return dto, nil
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
		return nil
	}
	profile := factorResearchProfile(params)
	stages := factorResearchStages(profile)
	now := time.Now()
	runID := parent.ExternalRunID
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

func factorResearchProfile(params map[string]any) string {
	profile := strings.ToLower(stringParam(params, "profile", "full"))
	switch profile {
	case "smoke", "full":
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
	stages := []map[string]string{
		{"key": "build_factor_panel", "name": "生成因子面板"},
		{"key": "evaluate_factors", "name": "因子检验"},
		{"key": "factor_correlation_report", "name": "因子相关性报告"},
		{"key": "train_lgbm", "name": "训练 LightGBM"},
		{"key": "latest_inference", "name": "最新截面推理"},
		{"key": "stress_report", "name": "压力测试报告"},
		{"key": "strategy_admission", "name": "策略准入评估"},
		{"key": "validate_research_run", "name": "产物完整性检查"},
	}
	return stages
}

func factorResearchStageCommandArgs(runID string, stage string, startDate string, endDate string, params map[string]any, dbPath string) []string {
	if stage == "strategy_admission" {
		return []string{
			"scripts/evaluate_strategies.py",
			"--start", startDate,
			"--end", endDate,
			"--strategies", "ml_factor_ranker",
			"--baseline", "small_cap_quality",
			"--save", "eval_" + runID,
			"--db-path", dbPath,
			"--strategy-version-mode", "latest",
			"--json",
		}
	}
	args := []string{
		"scripts/factor_research_worker.py",
		"--run-id", runID,
		"--stage", stage,
		"--start", startDate,
		"--end", endDate,
		"--freq", stringParam(params, "freq", "monthly"),
		"--label", stringParam(params, "label", "fwd20_excess_industry"),
		"--db-path", dbPath,
		"--min-train-years", strconv.Itoa(int(numberParam(params, "min_train_years", 4))),
		"--min-test-year", strconv.Itoa(int(numberParam(params, "min_test_year", 0))),
	}
	if boolParam(params, "stress_aware", false) {
		args = append(args, "--stress-aware")
	}
	return args
}

func factorResearchStageEnv(runID string, stage string, params map[string]any) []string {
	if stage != "strategy_admission" {
		return nil
	}
	override := map[string]any{
		"ml_factor_ranker": map[string]any{
			"selection": map[string]any{
				"run_id":        runID,
				"min_pred_rank": numberParam(params, "min_pred_rank", 0.96),
			},
		},
	}
	if boolParam(params, "stress_aware", false) {
		override["ml_factor_ranker"].(map[string]any)["filters"] = map[string]any{
			"stress_controls": map[string]any{"enabled": true},
		}
	}
	return []string{"QUANT_STRATEGY_OVERRIDES_JSON=" + mustJSON(override)}
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
	"turtle_breakout",
	"dividend_quality",
	"earnings_revision",
	"industry_prosperity",
	"low_crowding_reversal",
	"event_enhanced",
	"beijing_satellite",
	"insider_buy",
	"lhb_follow",
	"trend_quality",
	"garp_quality",
	"moneyflow_pullback",
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
	now := time.Now().Format(time.RFC3339)
	_, err := app.database.Conn().Exec(
		app.database.UpsertSQL(
			"eval_portfolio_runs",
			[]string{"run_id", "start_date", "end_date", "objective", "benchmark", "strategy_count", "viable_count", "candidate_count", "top_n", "generated_at", "summary_json", "created_at", "updated_at"},
			[]string{"run_id"},
			[]string{"start_date", "end_date", "objective", "benchmark", "strategy_count", "candidate_count", "top_n", "generated_at", "summary_json", "updated_at"},
		),
		runID, startDate, endDate, objective, benchmark, strategyCount, 0, len(candidates), topN, now, summary, now, now)
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
		"进攻": {"turtle_breakout", "trend_pullback", "earnings_revision", "industry_prosperity"},
		"平衡": {"multi_factor_composite", "small_cap_quality", "trend_pullback", "turtle_breakout", "dividend_quality"},
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
		"min_eval_walk_forward_windows": 1,
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
		for _, name := range app.orderedConfiguredStrategyNames() {
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

func (app *App) orderedConfiguredStrategyNames() []string {
	strategies := app.settings.Strategies
	if len(strategies) == 0 {
		homeDir, _ := os.UserHomeDir()
		strategies = config.DefaultSettings(homeDir).Strategies
	}
	seen := map[string]bool{}
	names := make([]string, 0, len(strategies))
	for _, name := range researchStrategyUniverse {
		if _, ok := strategies[name]; ok {
			names = append(names, name)
			seen[name] = true
		}
	}
	extras := make([]string, 0)
	for name := range strategies {
		if !seen[name] {
			extras = append(extras, name)
		}
	}
	sort.Strings(extras)
	names = append(names, extras...)
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
		FROM eval_strategy_admission
		WHERE run_id = (
			SELECT run_id
			FROM eval_strategy_admission
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
		case "可启用", "限制启用", "继续观察":
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
		app.reconcileEvaluationWorkerProcesses()
		app.reconcileOrphanRunningChildren(t.ID)
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
			if t.Status == task.StatusRunning && !hasLiveRunningChild(children) && hasRunnableChild(children) {
				go app.runPortfolioOptimizationChildren(t)
			}
			return t
		}
	}
	if t.TaskType == task.TypeStrategyEvaluation && t.ParentID == "" {
		app.reconcileEvaluationWorkerProcesses()
		app.reconcileOrphanRunningChildren(t.ID)
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
			if t.Status == task.StatusRunning && !hasLiveRunningChild(children) && hasRunnableChild(children) {
				go app.runStrategyEvaluationChildren(t)
			}
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
		_, _ = app.database.Conn().Exec(fmt.Sprintf(`UPDATE eval_portfolio_runs SET summary_json = ?, validation_status = 'analyzed', validation_json = ?, updated_at = %s WHERE run_id = ?`, app.database.CurrentTimestampSQL()), string(data), string(validationJSON), t.ExternalRunID)
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
		row := app.database.Conn().QueryRow(`SELECT version FROM strategy_config_versions WHERE strategy = ? ORDER BY version DESC LIMIT 1`, strategyName)
		if err := row.Scan(&version); err != nil {
			return ValidationReviewDTO{}, err
		}
	}
	row := app.database.Conn().QueryRow(`SELECT run_id, annual_return, max_drawdown, sharpe, calmar, avg_turnover, monthly_win_rate, positive_3m_rate, payload_json
		FROM eval_strategy_admission
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
		"walk_forward_ok":        floatValue(walkForward["pass_rate"], 0) >= numberParam(rules, "min_walk_forward_pass_rate", 0.50) && floatValue(walkForward["window_count"], 0) >= numberParam(rules, "min_eval_walk_forward_windows", 1),
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
	cmd.Env = append(os.Environ(), app.pythonDBEnv(dbPath)...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if output, err := cmd.Output(); err != nil {
		return nil, fmt.Errorf("刷新推荐回看失败：%v %s", err, strings.TrimSpace(stderr.String()+string(output)))
	}
	app.saveResearchReport("rec_daily_recommendations", "hindsight", "rec_hindsight", "推荐结果回看", "已刷新推荐信号与次日表现回看。", map[string]any{"refreshed_at": time.Now().Format(time.RFC3339)})
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
		FROM rec_hindsight
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
	snapshotSQL := `SELECT id, subject_type, subject_id, COALESCE(snapshot_json, '{}'), created_at FROM eval_data_snapshots`
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
	row := app.database.Conn().QueryRow(`SELECT date, payload_json FROM rec_daily_recommendations ORDER BY date DESC LIMIT 1`)
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
	) VALUES (?, 'rec_daily_recommendations', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		"res_"+strings.ReplaceAll(task.NewID(), "-", ""), date, date, len(weights), totalWeight, maxSingle, top5, string(industryJSON), string(strategyJSON), string(auditJSON), time.Now().Format(time.RFC3339))
	return err
}

func (app *App) refreshPaperTradingLog() error {
	rows, err := app.database.Conn().Query(`SELECT date, payload_json FROM rec_daily_recommendations ORDER BY date DESC LIMIT 120`)
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
			_ = app.database.Conn().QueryRow(`SELECT weight FROM portfolio_pool_holdings WHERE ts_code = ?`, code).Scan(&actual)
			if actual.Valid {
				status = "tracked"
				reason = "已匹配当前持仓权重"
			}
			itemJSON, _ := json.Marshal(item)
			now := time.Now().Format(time.RFC3339)
			_, _ = app.database.Conn().Exec(
				app.database.UpsertSQL(
					"trade_paper_log",
					[]string{"id", "signal_date", "ts_code", "name", "action", "target_weight", "actual_weight", "status", "reason", "payload_json", "created_at", "updated_at"},
					[]string{"signal_date", "ts_code", "action"},
					[]string{"target_weight", "actual_weight", "status", "reason", "payload_json", "updated_at"},
				),
				"pt_"+strings.ReplaceAll(task.NewID(), "-", ""), date, code, name, action, targetWeight, nullableSQLValue(actual), status, reason, string(itemJSON), now, now)
		}
	}
	return rows.Err()
}

func (app *App) refreshPromotionDecisions() error {
	rows, err := app.database.Conn().Query(`SELECT strategy, version, COALESCE(promotion_status, 'research'), COALESCE(validation_json, '{}') FROM strategy_config_versions ORDER BY strategy, version DESC`)
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
		_, _ = app.database.Conn().Exec(
			app.database.UpsertSQL(
				"strategy_promotion_decisions",
				[]string{"id", "strategy", "strategy_version", "current_status", "recommended_status", "score", "reason", "payload_json", "created_at", "updated_at"},
				[]string{"strategy", "strategy_version"},
				[]string{"current_status", "recommended_status", "score", "reason", "payload_json", "updated_at"},
			),
			"pd_"+strings.ReplaceAll(task.NewID(), "-", ""), strategy, version, status, recommended, score, reason, string(payloadJSON), now, now)
	}
	return rows.Err()
}

func (app *App) refreshWalkForwardAndParameterExperiments() error {
	rows, err := app.database.Conn().Query(`SELECT run_id, strategy, COALESCE(strategy_version, 0), start_date, end_date, annual_return, max_drawdown, sharpe, calmar, avg_turnover, COALESCE(payload_json, '{}')
		FROM eval_strategy_admission ORDER BY strategy, start_date`)
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
		_, _ = app.database.Conn().Exec(
			app.database.UpsertSQL(
				"eval_walk_forward_windows",
				[]string{"id", "subject_type", "subject_id", "window_name", "start_date", "end_date", "status", "score", "metrics_json", "created_at", "updated_at"},
				[]string{"subject_type", "subject_id", "window_name"},
				[]string{"status", "score", "metrics_json", "updated_at"},
			),
			"wfw_"+strings.ReplaceAll(task.NewID(), "-", ""), "strategy_version", subjectID, runID, startDate, endDate, status, score, string(metricsJSON), now, now)
	}
	versionRows, err := app.database.Conn().Query(`SELECT strategy, version, config_json, COALESCE(validation_json, '{}') FROM strategy_config_versions ORDER BY strategy, version DESC`)
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
		_, _ = app.database.Conn().Exec(
			app.database.UpsertSQL(
				"eval_parameter_experiments",
				[]string{"id", "strategy", "strategy_version", "param_set", "status", "score", "params_json", "metrics_json", "created_at", "updated_at"},
				[]string{"strategy", "strategy_version", "param_set"},
				[]string{"status", "score", "params_json", "metrics_json", "updated_at"},
			),
			"pe_"+strings.ReplaceAll(task.NewID(), "-", ""), strategy, version, "version_config", status, score, configJSON, validationJSON, now, now)
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
		FROM eval_walk_forward_windows ORDER BY datetime(updated_at) DESC LIMIT 200`)
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
		FROM eval_parameter_experiments ORDER BY strategy, strategy_version DESC LIMIT 200`)
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
		FROM trade_paper_log ORDER BY signal_date DESC, updated_at DESC LIMIT 200`)
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
		FROM strategy_promotion_decisions ORDER BY strategy, strategy_version DESC LIMIT 200`)
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
	rows, err := app.database.Conn().Query(`SELECT data_type, COUNT(*), COALESCE(SUM(row_count), 0), COALESCE(MAX(updated_at), '') FROM data_market_files GROUP BY data_type ORDER BY data_type`)
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
	rows, err := app.database.Conn().Query(`SELECT status, attempt, max_attempts FROM task_jobs WHERE task_type IN (?, ?, ?, ?, ?)`,
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
	if _, err := app.database.Conn().Exec(
		app.database.UpsertSQL(
			"strategy_validation_reviews",
			[]string{"id", "subject_type", "subject_id", "strategy", "strategy_version", "source_run_id", "status", "score", "gates_json", "metrics_json", "recommendation", "created_at", "updated_at"},
			[]string{"id"},
			[]string{"status", "score", "gates_json", "metrics_json", "recommendation", "updated_at"},
		),
		review.ID, review.SubjectType, review.SubjectID, review.Strategy, review.StrategyVersion, review.SourceRunID, review.Status, review.Score, string(gatesJSON), string(metricsJSON), review.Recommendation, review.CreatedAt, review.UpdatedAt); err != nil {
		return ValidationReviewDTO{}, err
	}
	validationJSON, _ := json.Marshal(map[string]any{"review_id": review.ID, "status": review.Status, "score": review.Score, "gates": review.Gates, "metrics": review.Metrics, "recommendation": review.Recommendation, "updated_at": review.UpdatedAt})
	if review.SubjectType == "strategy_version" && review.Strategy != "" && review.StrategyVersion > 0 {
		_, _ = app.database.Conn().Exec(`UPDATE strategy_config_versions SET promotion_status = ?, validation_json = ? WHERE strategy = ? AND version = ?`,
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
		FROM eval_strategy_admission
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
		FROM strategy_config_versions
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
	_ = app.database.Conn().QueryRow(`SELECT COUNT(*) FROM eval_strategy_admission WHERE run_id = ?`, runID).Scan(&strategyTests)
	var candidateTests int
	_ = app.database.Conn().QueryRow(`SELECT COUNT(*) FROM eval_portfolio_candidates WHERE run_id = ?`, runID).Scan(&candidateTests)
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
	rows, err := app.database.Conn().Query(`SELECT data_type, COUNT(*), COALESCE(SUM(row_count), 0), COALESCE(MAX(updated_at), '') FROM data_market_files GROUP BY data_type ORDER BY data_type`)
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
	rows, err = app.database.Conn().Query(`SELECT COALESCE(subtask_key, ''), status, COALESCE(params_json, '{}'), COALESCE(summary_json, '{}'), updated_at FROM task_jobs WHERE task_type='data_update' AND COALESCE(subtask_key, '') <> '' ORDER BY COALESCE(sequence, 0), subtask_key LIMIT 200`)
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var dataset, status, paramsJSON, summaryJSON, updatedAt string
			if err := rows.Scan(&dataset, &status, &paramsJSON, &summaryJSON, &updatedAt); err == nil {
				params := map[string]any{}
				summary := map[string]any{}
				_ = json.Unmarshal([]byte(paramsJSON), &params)
				_ = json.Unmarshal([]byte(summaryJSON), &summary)
				datasetStatus = append(datasetStatus, map[string]any{
					"dataset":    firstNonEmptyString(dataset, stringFromAny(params["dataset"])),
					"category":   stringFromAny(params["category"]),
					"state":      dataUpdateTaskState(status),
					"done":       intFromAny(summary["progress_done"]),
					"total":      intFromAny(summary["progress_total"]),
					"updated_at": updatedAt,
				})
			}
		}
	}
	snapshot["data_market_files"] = typeCount
	snapshot["dataset_status"] = datasetStatus
	app.saveDataSnapshot(subjectType, subjectID, snapshot)
	return snapshot
}

func dataUpdateTaskState(status string) string {
	switch status {
	case "created", "queued":
		return "pending"
	case "running", "success":
		return status
	case "failed", "cancelled", "interrupted", "error":
		return "failed"
	default:
		return status
	}
}

func firstNonEmptyString(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func stringFromAny(value any) string {
	if s, ok := value.(string); ok {
		return s
	}
	return ""
}

func intFromAny(value any) int {
	switch v := value.(type) {
	case int:
		return v
	case int64:
		return int(v)
	case float64:
		return int(v)
	case json.Number:
		n, _ := v.Int64()
		return int(n)
	default:
		return 0
	}
}

func (app *App) saveDataSnapshot(subjectType string, subjectID string, snapshot map[string]any) {
	if app.database == nil || strings.TrimSpace(subjectType) == "" || strings.TrimSpace(subjectID) == "" {
		return
	}
	data, _ := json.Marshal(snapshot)
	_, _ = app.database.Conn().Exec(`INSERT INTO eval_data_snapshots(id, subject_type, subject_id, snapshot_json, created_at) VALUES(?, ?, ?, ?, ?)`,
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
		dbRows, err := app.database.Conn().Query(`SELECT `+"`rank`"+`, score, annual_return, max_drawdown, sharpe, calmar, avg_turnover, avg_holdings, avg_total_mv, avg_amount, payload_json
			FROM eval_portfolio_candidates
			WHERE run_id = ?
			ORDER BY CASE WHEN `+"`rank`"+` > 0 THEN `+"`rank`"+` ELSE 999999 END ASC, score DESC
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
	if t.TaskType != task.TypeEvaluationTimeMachine && t.TaskType != task.TypeStrategyEvaluation && t.TaskType != task.TypePortfolioOptimization && t.TaskType != task.TypeWalkForwardEvaluation && t.TaskType != task.TypeParameterExperiment && t.TaskType != task.TypeFactorResearch && t.TaskType != task.TypeLimitSignalEvaluation && t.TaskType != task.TypeT0DailyResearch && t.TaskType != task.TypeT0TimeMachine {
		return task.DTO{}, errors.New("only evaluation tasks can be started")
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
	if t.TaskType == task.TypeFactorResearch {
		return app.startFactorResearchTask(t)
	}
	if t.TaskType == task.TypeLimitSignalEvaluation || t.TaskType == task.TypeT0DailyResearch || t.TaskType == task.TypeT0TimeMachine {
		return app.startMarketEvaluationTask(t)
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
		DBBackend:      app.settings.DatabaseBackend,
		DBDSN:          app.settings.MySQLDSN,
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
	t.Progress = 0.02
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

func (app *App) startMarketEvaluationTask(t task.Task) (task.DTO, error) {
	dataPath := strings.TrimSpace(app.settings.DataPath)
	if dataPath == "" {
		return task.DTO{}, errors.New("数据路径未设置")
	}
	quantRoot := app.quantStockCorePath()
	pythonPath := pythonPathForCore(quantRoot)
	dbPath := filepath.Join(dataPath, "meta.db")
	statusTask, args, err := marketEvaluationTaskCommand(t.TaskType, dataPath, dbPath, task.ToDTO(t).Params)
	if err != nil {
		return task.DTO{}, err
	}
	runID := strings.TrimSpace(t.ExternalRunID)
	if runID == "" {
		runID = strings.ReplaceAll(t.ID, "-", "")
	}
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
	_, _ = app.database.Conn().Exec(
		app.database.UpsertSQL(
			"task_run_status",
			[]string{"task", "task_type", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"task_type", "state", "idx", "total", "stage", "name", "message", "started_at", "updated_at", "finished_at"},
		),
		statusTask, runStatusTaskType(statusTask), "running", 1, 100, "prepare", "启动评估任务", "", nowText, nowText, "",
	)
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + dataPath}, app.pythonDBEnv(dbPath)...)...)
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

func marketEvaluationTaskCommand(taskType task.Type, dataPath string, dbPath string, params map[string]any) (string, []string, error) {
	switch taskType {
	case task.TypeLimitSignalEvaluation:
		return "limit_signal_evaluation", []string{
			"scripts/evaluate_limit_signals.py",
			"--data-path", dataPath,
			"--db-path", dbPath,
		}, nil
	case task.TypeT0DailyResearch:
		return "t0_daily_research", []string{
			"scripts/t0_daily_worker.py",
			"--data-path", dataPath,
			"--db-path", dbPath,
			"--lookback", "120",
			"--history-days", "760",
			"--model-history-days", "2200",
			"--limit", "120",
			"--backtest-limit", "120",
		}, nil
	case task.TypeT0TimeMachine:
		mode := strings.TrimSpace(fmt.Sprint(params["mode"]))
		if mode == "quick" {
			return "t0_daily_timemachine", []string{
				"scripts/t0_daily_worker.py",
				"--mode", "time_machine",
				"--data-path", dataPath,
				"--db-path", dbPath,
				"--lookback-grid", "80",
				"--eval-days-grid", "20",
				"--anchor-count", "1",
				"--anchor-step", "20",
				"--model-history-days", "1600",
				"--limit", "80",
			}, nil
		}
		return "t0_daily_timemachine", []string{
			"scripts/t0_daily_worker.py",
			"--mode", "time_machine",
			"--data-path", dataPath,
			"--db-path", dbPath,
			"--lookback-grid", "40,60,80,120",
			"--eval-days-grid", "10,20,40",
			"--anchor-count", "4",
			"--anchor-step", "20",
			"--model-history-days", "2200",
			"--limit", "80",
		}, nil
	default:
		return "", nil, errors.New("unsupported market evaluation task")
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
	payload, _ := json.Marshal(summary)
	t.SummaryJSON = string(payload)
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
					message = "评估任务已结束；如果没有切面结果，请先刷新推荐生成预测快照"
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
	Task      string
	State     string
	Idx       int
	Total     int
	Stage     string
	Name      string
	Message   string
	UpdatedAt string
}

func (app *App) readRunStatusRow(statusTask string) (runStatusRow, error) {
	row := app.database.Conn().QueryRow(
		`SELECT task, state, idx, total, COALESCE(stage,''), COALESCE(name,''), COALESCE(message,''), updated_at
		FROM task_run_status WHERE task = ?`,
		statusTask,
	)
	var out runStatusRow
	err := row.Scan(&out.Task, &out.State, &out.Idx, &out.Total, &out.Stage, &out.Name, &out.Message, &out.UpdatedAt)
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
	if t.TaskType != task.TypeStrategyEvaluation && t.TaskType != task.TypeWalkForwardEvaluation && t.TaskType != task.TypeParameterExperiment && t.TaskType != task.TypePortfolioOptimization && t.TaskType != task.TypeFactorResearch && t.TaskType != task.TypeLimitSignalEvaluation && t.TaskType != task.TypeT0DailyResearch && t.TaskType != task.TypeT0TimeMachine {
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
			return task.DTO{}, errors.New("已有评估任务正在运行，同一时间只能运行一个评估")
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
	parent.SummaryJSON = app.strategyEvaluationSummaryForParent(parent, children)
	if t.TaskType == task.TypePortfolioOptimization {
		parent.SummaryJSON = app.portfolioSummaryForParent(parent, children)
	} else if t.TaskType == task.TypeFactorResearch {
		parent.SummaryJSON = app.factorResearchSummaryForParent(parent, children)
	}
	_ = app.taskService.Repository().UpdateStatus(parent)
	_ = app.taskService.Repository().UpdateRuntime(parent)
	if t.TaskType == task.TypePortfolioOptimization {
		go app.runPortfolioOptimizationChildren(parent)
	} else if t.TaskType == task.TypeFactorResearch {
		go app.runFactorResearchChildren(parent)
	} else {
		go app.runStrategyEvaluationChildren(parent)
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

func (app *App) startStrategyEvaluationTask(t task.Task) (task.DTO, error) {
	if t.ParentID != "" {
		return app.RetryTask(t.ID)
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
	dbPath := filepath.Join(app.settings.DataPath, "meta.db")
	args := factorResearchStageCommandArgs(runID, stage, startDate, endDate, params, dbPath)
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = quantRoot
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + app.settings.DataPath}, app.pythonDBEnv(dbPath)...)...)
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

func (app *App) runStrategyEvaluationChildren(parent task.Task) {
	app.schedulerMu.Lock()
	defer app.schedulerMu.Unlock()
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
		app.reconcileOrphanRunningChildren(parent.ID)
		children, err := app.taskService.Repository().ListChildren(parent.ID)
		if err != nil {
			app.finishStrategyEvaluationParent(parent, task.StatusFailed, err.Error(), children)
			return
		}
		next := runnablePortfolioChildren(children, app.availableChildSlots(children))
		if len(next) == 0 {
			status := portfolioParentStatus(children)
			if status != task.StatusRunning {
				app.finishStrategyEvaluationParent(parent, status, "", children)
				return
			}
			parent.Progress = portfolioParentProgress(children)
			parent.SummaryJSON = app.strategyEvaluationSummaryForParent(parent, children)
			parent.UpdatedAt = time.Now()
			_ = app.taskService.Repository().UpdateStatus(parent)
			_ = app.taskService.Repository().UpdateRuntime(parent)
			time.Sleep(1 * time.Second)
			continue
		}
		app.startChildTaskBatch(next, app.startStrategyEvaluationChildTaskSync)
		time.Sleep(1 * time.Second)
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
	dbPath := filepath.Join(app.settings.DataPath, "meta.db")
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + app.settings.DataPath}, app.pythonDBEnv(dbPath)...)...)
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
	app.releaseChildSlotsForParent(parent.ID)
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
		_, _ = app.database.Conn().Exec(
			app.database.UpsertSQL(
				"eval_walk_forward_windows",
				[]string{"id", "subject_type", "subject_id", "window_name", "start_date", "end_date", "status", "score", "metrics_json", "created_at", "updated_at"},
				[]string{"subject_type", "subject_id", "window_name"},
				[]string{"status", "score", "metrics_json", "updated_at"},
			),
			"wfw_"+strings.ReplaceAll(task.NewID(), "-", ""), "strategy", subjectID, windowName, stringParam(params, "start_date", ""), stringParam(params, "end_date", ""), status, score, string(metricsJSON), now, now)
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
		_, _ = app.database.Conn().Exec(
			app.database.UpsertSQL(
				"eval_parameter_experiments",
				[]string{"id", "strategy", "strategy_version", "param_set", "status", "score", "params_json", "metrics_json", "created_at", "updated_at"},
				[]string{"strategy", "strategy_version", "param_set"},
				[]string{"status", "score", "params_json", "metrics_json", "updated_at"},
			),
			"pe_"+strings.ReplaceAll(task.NewID(), "-", ""), strategyName, 0, paramSet, expStatus, score, string(overridesJSON), string(metricsJSON), now, now)
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
	app.schedulerMu.Lock()
	defer app.schedulerMu.Unlock()
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
		app.reconcileOrphanRunningChildren(parent.ID)
		children, err := app.taskService.Repository().ListChildren(parent.ID)
		if err != nil {
			app.finishPortfolioParent(parent, task.StatusFailed, err.Error(), children)
			return
		}
		next := runnablePortfolioChildren(children, app.availableChildSlots(children))
		if len(next) == 0 {
			status := portfolioParentStatus(children)
			if status != task.StatusRunning {
				app.finishPortfolioParent(parent, status, "", children)
				return
			}
			parent.Progress = portfolioParentProgress(children)
			parent.SummaryJSON = app.portfolioSummaryForParent(parent, children)
			parent.UpdatedAt = time.Now()
			_ = app.taskService.Repository().UpdateStatus(parent)
			_ = app.taskService.Repository().UpdateRuntime(parent)
			time.Sleep(1 * time.Second)
			continue
		}
		app.startChildTaskBatch(next, app.startPortfolioCandidateTaskSync)
		time.Sleep(1 * time.Second)
		children, _ = app.taskService.Repository().ListChildren(parent.ID)
		parent.Progress = portfolioParentProgress(children)
		parent.SummaryJSON = app.portfolioSummaryForParent(parent, children)
		parent.UpdatedAt = time.Now()
		_ = app.taskService.Repository().UpdateStatus(parent)
		_ = app.taskService.Repository().UpdateRuntime(parent)
	}
}

func (app *App) startPortfolioCandidateTask(t task.Task) (task.DTO, error) {
	return app.RetryTask(t.ID)
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
	dbPath := filepath.Join(app.settings.DataPath, "meta.db")
	cmd.Env = append(os.Environ(), append([]string{"DATA_ROOT=" + app.settings.DataPath}, app.pythonDBEnv(dbPath)...)...)
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

func (app *App) reconcileEvaluationWorkerProcesses() {
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

	osWorkers := evaluationWorkerPIDs()
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
	app.reconcileEvaluationWorkerProcesses()
	if app.taskService == nil {
		return
	}
	items, err := app.taskService.Repository().List(task.Query{Limit: 1000})
	if err != nil {
		return
	}
	now := time.Now()
	for _, item := range items {
		if item.ParentID != "" || item.Status != task.StatusRunning || item.WorkerPID > 0 || !isEvaluationRuntimeType(item.TaskType) {
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

func isEvaluationRuntimeType(taskType task.Type) bool {
	switch taskType {
	case task.TypeEvaluationTimeMachine, task.TypeStrategyEvaluation, task.TypePortfolioOptimization, task.TypeWalkForwardEvaluation, task.TypeParameterExperiment, task.TypeFactorResearch, task.TypeLimitSignalEvaluation, task.TypeT0DailyResearch, task.TypeT0TimeMachine:
		return true
	default:
		return false
	}
}

func evaluationWorkerPIDs() map[int]bool {
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
		if strings.Contains(line, "scripts/evaluate_strategies.py") ||
			strings.Contains(line, "scripts/run_portfolio_candidate.py") ||
			strings.Contains(line, "scripts/factor_research_worker.py") {
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

func (app *App) finishPortfolioParent(parent task.Task, status task.Status, message string, children []task.Task) {
	now := time.Now()
	app.releaseChildSlotsForParent(parent.ID)
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
	_, _ = app.database.Conn().Exec(fmt.Sprintf(`UPDATE eval_portfolio_runs SET summary_json = ?, updated_at = %s WHERE run_id = ?`, app.database.CurrentTimestampSQL()), string(out), parent.ExternalRunID)
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
	rows, err := app.database.Conn().Query(`SELECT candidate_id, score FROM eval_portfolio_candidates WHERE run_id = ? AND status = 'ok' ORDER BY score DESC`, runID)
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
		if _, err := app.database.Conn().Exec(fmt.Sprintf(`UPDATE eval_portfolio_candidates SET `+"`rank`"+` = ?, updated_at = %s WHERE run_id = ? AND candidate_id = ?`, app.database.CurrentTimestampSQL()), idx+1, runID, item.ID); err != nil {
			return err
		}
	}
	return nil
}

func readPortfolioCandidateSummaryFromDB(db *sql.DB, runID string, candidateID string) string {
	row := db.QueryRow(`SELECT payload_json FROM eval_portfolio_candidates WHERE run_id = ? AND candidate_id = ?`, runID, candidateID)
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
				app.releaseChildSlotForTask(child.ID)
			}
		}
		app.releaseChildSlotsForParent(t.ID)
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
				app.releaseChildSlotForTask(child.ID)
			}
		}
		app.releaseChildSlotsForParent(t.ID)
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
		filepath.Join("trading", "execution", "time_machine.py"),
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
	if backend != "mysql" {
		app.settings.MySQLDSN = packagedDSN
	} else if strings.TrimSpace(app.settings.MySQLDSN) == "" {
		app.settings.MySQLDSN = packagedDSN
	}
	if app.database != nil {
		return nil
	}
	dbPath := filepath.Join(app.settings.DataPath, "meta.db")
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
	} else if err := os.MkdirAll(filepath.Dir(dbPath), 0o755); err != nil {
		return err
	}
	db, err := database.OpenConfigured(database.Config{
		Backend:        app.settings.DatabaseBackend,
		SQLitePath:     dbPath,
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
	return nil
}

func (app *App) fixedDataPath() string {
	if dataPath, ok := inferWorkspaceDataPath(); ok {
		return dataPath
	}
	if app.settings.DataPath != "" {
		return filepath.Clean(app.settings.DataPath)
	}
	if homeDir, err := os.UserHomeDir(); err == nil {
		return config.DefaultSettings(homeDir).DataPath
	}
	return filepath.Join("data_store")
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

func mustGetwd() string {
	wd, err := os.Getwd()
	if err != nil {
		return "."
	}
	return wd
}
