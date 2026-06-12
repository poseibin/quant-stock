package config

import (
	"database/sql"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"time"

	"quant_stock_desktop/internal/common/database"
)

type Service struct {
	db *database.DB
}

func NewService() *Service {
	return &Service{}
}

func (service *Service) WithDB(db *sql.DB) *Service {
	service.db = database.Wrap(db, database.BackendMySQL)
	return service
}

func (service *Service) WithDatabase(db *database.DB) *Service {
	service.db = db
	return service
}

func DefaultSettings(homeDir string) Settings {
	return normalize(applyPackagedDatabaseConfig(Settings{
		DataPath:             defaultDataPathForHome(homeDir),
		DefaultInitialCash:   500000,
		DefaultRebalanceFreq: 5,
		TaskConcurrency:      2,
		DeepSeekModel:        "deepseek-v4-pro",
		Strategies:           defaultStrategies(),
		PortfolioRisk:        defaultPortfolioRisk(),
		ExitRules:            defaultExitRules(),
		GovernanceRules:      defaultGovernanceRules(),
	}))
}

func (service *Service) Load(defaults Settings) (Settings, error) {
	if service.db != nil {
		settings, err := service.loadFromDB(defaults)
		if err == nil {
			_ = service.ensureStrategyVersions(settings, "settings_load", "初始化策略版本")
			return settings, nil
		}
		if !errors.Is(err, sql.ErrNoRows) {
			return Settings{}, err
		}
		settings = normalize(defaults)
		_ = service.Save(settings)
		return settings, nil
	}
	return normalize(cloneSettings(defaults)), nil
}

func (service *Service) Save(settings Settings) error {
	settings = normalize(settings)
	settings = applyPackagedDatabaseConfig(settings)
	if err := os.MkdirAll(settings.DataPath, 0o755); err != nil {
		return err
	}
	if service.db != nil {
		return service.saveToDB(settings)
	}
	return nil
}

func (service *Service) loadFromDB(defaults Settings) (Settings, error) {
	row := service.db.Conn().QueryRow("SELECT value FROM cfg_app_settings WHERE `key` = ?", "settings")
	var value string
	if err := row.Scan(&value); err != nil {
		return Settings{}, err
	}
	settings := cloneSettings(defaults)
	if err := json.Unmarshal([]byte(value), &settings); err != nil {
		return Settings{}, err
	}
	settings = normalize(settings)
	return service.applyActiveStrategyVersions(settings), nil
}

func (service *Service) saveToDB(settings Settings) error {
	data, err := json.Marshal(settings)
	if err != nil {
		return err
	}
	tx, err := service.db.Conn().Begin()
	if err != nil {
		return err
	}
	defer func() {
		if err != nil {
			_ = tx.Rollback()
		}
	}()
	_, err = tx.Exec(
		service.db.UpsertSQL("cfg_app_settings", []string{"key", "value", "updated_at"}, []string{"key"}, []string{"value", "updated_at"}),
		"settings", string(data), time.Now().Format("2006-01-02T15:04:05"),
	)
	if err != nil {
		return err
	}
	if err = service.saveStrategyVersions(tx, settings, "settings_save", "用户保存策略配置"); err != nil {
		return err
	}
	err = tx.Commit()
	return err
}

func (service *Service) ensureStrategyVersions(settings Settings, source string, note string) error {
	if service.db == nil {
		return nil
	}
	var count int
	if err := service.db.Conn().QueryRow(`SELECT COUNT(*) FROM strategy_config_versions`).Scan(&count); err == nil && count > 0 {
		return nil
	}
	tx, err := service.db.Conn().Begin()
	if err != nil {
		return err
	}
	if err = service.saveStrategyVersions(tx, normalize(settings), source, note); err != nil {
		_ = tx.Rollback()
		return err
	}
	return tx.Commit()
}

func (service *Service) saveStrategyVersions(tx *sql.Tx, settings Settings, source string, note string) error {
	now := time.Now().Format("2006-01-02T15:04:05")
	for name, strategy := range settings.Strategies {
		configJSON, err := json.Marshal(strategy)
		if err != nil {
			return err
		}
		var latestVersion int
		var latestConfig string
		row := tx.QueryRow(`SELECT version, config_json FROM strategy_config_versions WHERE strategy = ? ORDER BY version DESC LIMIT 1`, name)
		scanErr := row.Scan(&latestVersion, &latestConfig)
		switch {
		case scanErr == nil && latestConfig == string(configJSON):
			if err := activateStrategyVersion(tx, name, latestVersion, now); err != nil {
				return err
			}
			continue
		case scanErr != nil && !errors.Is(scanErr, sql.ErrNoRows):
			return scanErr
		}
		version := latestVersion + 1
		if errors.Is(scanErr, sql.ErrNoRows) {
			version = 1
		}
		if _, err := tx.Exec(`UPDATE strategy_config_versions SET is_active = 0 WHERE strategy = ?`, name); err != nil {
			return err
		}
		if _, err := tx.Exec(`INSERT INTO strategy_config_versions(
			strategy, version, label, config_json, is_active, promotion_status, validation_json, source, note, created_at, activated_at
		) VALUES (?, ?, ?, ?, 1, 'active', '{}', ?, ?, ?, ?)`,
			name, version, strategy.Label, string(configJSON), source, note, now, now); err != nil {
			return err
		}
	}
	return nil
}

func activateStrategyVersion(tx *sql.Tx, strategy string, version int, activatedAt string) error {
	if _, err := tx.Exec(`UPDATE strategy_config_versions SET is_active = 0 WHERE strategy = ?`, strategy); err != nil {
		return err
	}
	_, err := tx.Exec(`UPDATE strategy_config_versions SET is_active = 1, promotion_status = 'active', activated_at = ? WHERE strategy = ? AND version = ?`, activatedAt, strategy, version)
	return err
}

func (service *Service) applyActiveStrategyVersions(settings Settings) Settings {
	if service.db == nil {
		return settings
	}
	rows, err := service.db.Conn().Query(`SELECT strategy, config_json FROM strategy_config_versions WHERE is_active = 1`)
	if err != nil {
		return settings
	}
	defer rows.Close()
	for rows.Next() {
		var name string
		var configJSON string
		if err := rows.Scan(&name, &configJSON); err != nil {
			continue
		}
		var strategy StrategySettings
		if err := json.Unmarshal([]byte(configJSON), &strategy); err != nil {
			continue
		}
		if settings.Strategies == nil {
			settings.Strategies = map[string]StrategySettings{}
		}
		settings.Strategies[name] = strategy
	}
	return normalize(settings)
}

func (service *Service) Validate(settings Settings) []ValidationIssue {
	issues := make([]ValidationIssue, 0)
	checkDir := func(field string, path string) {
		info, err := os.Stat(path)
		if err != nil {
			issues = append(issues, ValidationIssue{Field: field, Message: "路径不存在，请先创建目录"})
			return
		}
		if !info.IsDir() {
			issues = append(issues, ValidationIssue{Field: field, Message: "不是目录"})
		}
	}

	settings = normalize(settings)
	settings = applyPackagedDatabaseConfig(settings)
	checkDir("data_path", settings.DataPath)
	switch settings.DatabaseBackend {
	case "mysql":
		if strings.TrimSpace(settings.MySQLDSN) == "" {
			issues = append(issues, ValidationIssue{Field: "mysql_dsn", Message: "MySQL DSN 不能为空"})
		}
	default:
		issues = append(issues, ValidationIssue{Field: "database_backend", Message: "数据库类型必须是 mysql"})
	}

	if settings.DefaultInitialCash <= 0 {
		issues = append(issues, ValidationIssue{Field: "default_initial_cash", Message: "默认资金必须大于 0"})
	}
	if settings.DefaultRebalanceFreq <= 0 {
		issues = append(issues, ValidationIssue{Field: "default_rebalance_freq", Message: "调仓频率必须大于 0"})
	}
	if settings.TaskConcurrency < 1 || settings.TaskConcurrency > 8 {
		issues = append(issues, ValidationIssue{Field: "task_concurrency", Message: "任务并发数必须在 1 到 8 之间"})
	}
	totalWeight := 0.0
	for name, strategy := range settings.Strategies {
		if strategy.Enabled {
			if strategy.Weight < 0 {
				issues = append(issues, ValidationIssue{Field: "strategies." + name + ".weight", Message: "策略权重不能小于 0"})
			}
			totalWeight += strategy.Weight
		}
	}
	if totalWeight <= 0 {
		issues = append(issues, ValidationIssue{Field: "strategies", Message: "至少需要启用一个权重大于 0 的策略"})
	}
	return issues
}

func normalize(settings Settings) Settings {
	if settings.DataPath == "" {
		settings.DataPath = defaultDataPath()
	}
	settings.DatabaseBackend = strings.ToLower(strings.TrimSpace(settings.DatabaseBackend))
	if settings.DatabaseBackend == "" {
		settings.DatabaseBackend = "mysql"
	}
	if settings.DatabaseBackend != "mysql" {
		settings.DatabaseBackend = "mysql"
	}
	settings.MySQLDSN = strings.TrimSpace(settings.MySQLDSN)
	settings = applyPackagedDatabaseConfig(settings)
	if settings.DefaultInitialCash == 0 {
		settings.DefaultInitialCash = 500000
	}
	if settings.DefaultRebalanceFreq == 0 {
		settings.DefaultRebalanceFreq = 5
	}
	if settings.TaskConcurrency == 0 {
		settings.TaskConcurrency = 2
	}
	if settings.DeepSeekModel == "" {
		settings.DeepSeekModel = "deepseek-v4-pro"
	}
	settings.Strategies = mergeStrategies(defaultStrategies(), settings.Strategies)
	if settings.PortfolioRisk == nil {
		settings.PortfolioRisk = defaultPortfolioRisk()
	}
	if settings.ExitRules == nil {
		settings.ExitRules = defaultExitRules()
	}
	settings.GovernanceRules = mergeAnyMap(defaultGovernanceRules(), settings.GovernanceRules)
	settings.StrategySchedule = normalizeStrategySchedule(settings.StrategySchedule)
	return settings
}

func NormalizeForCompare(settings Settings) Settings {
	return normalize(settings)
}

func defaultDataPath() string {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join("data_store")
	}
	return defaultDataPathForHome(homeDir)
}

func defaultDataPathForHome(homeDir string) string {
	return filepath.Join(homeDir, "Library", "Application Support", "QuantStockDesktop", "data_store")
}

func cloneSettings(settings Settings) Settings {
	settings.Strategies = cloneStrategies(settings.Strategies)
	settings.PortfolioRisk = cloneAnyMap(settings.PortfolioRisk)
	settings.ExitRules = cloneAnyMap(settings.ExitRules)
	settings.GovernanceRules = cloneAnyMap(settings.GovernanceRules)
	settings.StrategySchedule = cloneStrategySchedule(settings.StrategySchedule)
	return settings
}

func normalizeStrategySchedule(schedule StrategyScheduleSettings) StrategyScheduleSettings {
	schedule.TimeOfDay = strings.TrimSpace(schedule.TimeOfDay)
	if schedule.TimeOfDay == "" || schedule.TimeOfDay == "15:20" {
		schedule.TimeOfDay = "22:00"
	}
	if len(schedule.Weekdays) == 0 {
		schedule.Weekdays = []int{1, 2, 3, 4, 5}
	}
	if schedule.Targets == nil {
		schedule.Targets = map[string]bool{
			"t0":       true,
			"limit_up": true,
			"breakout": true,
			"factor":   false,
		}
	} else {
		defaults := map[string]bool{"t0": true, "limit_up": true, "breakout": true, "factor": false}
		targets := make(map[string]bool, len(defaults))
		for key, value := range defaults {
			targets[key] = value
		}
		for key, value := range schedule.Targets {
			targets[strings.TrimSpace(key)] = value
		}
		schedule.Targets = targets
	}
	schedule.WechatWebhook = strings.TrimSpace(schedule.WechatWebhook)
	cleanUsers := make([]string, 0, len(schedule.WechatUsers))
	seen := map[string]bool{}
	for _, user := range schedule.WechatUsers {
		user = strings.Trim(strings.TrimSpace(user), "@")
		if user == "" || seen[user] {
			continue
		}
		seen[user] = true
		cleanUsers = append(cleanUsers, user)
	}
	schedule.WechatUsers = cleanUsers
	return schedule
}

func cloneStrategySchedule(schedule StrategyScheduleSettings) StrategyScheduleSettings {
	if schedule.Weekdays != nil {
		schedule.Weekdays = append([]int(nil), schedule.Weekdays...)
	}
	if schedule.Targets != nil {
		targets := make(map[string]bool, len(schedule.Targets))
		for key, value := range schedule.Targets {
			targets[key] = value
		}
		schedule.Targets = targets
	}
	if schedule.WechatUsers != nil {
		schedule.WechatUsers = append([]string(nil), schedule.WechatUsers...)
	}
	return schedule
}

func mergeAnyMap(defaults map[string]any, current map[string]any) map[string]any {
	merged := cloneAnyMap(defaults)
	for key, value := range current {
		merged[key] = cloneAnyValue(value)
	}
	return merged
}

func cloneStrategies(strategies map[string]StrategySettings) map[string]StrategySettings {
	if strategies == nil {
		return nil
	}
	out := make(map[string]StrategySettings, len(strategies))
	for name, strategy := range strategies {
		out[name] = cloneStrategySettings(strategy)
	}
	return out
}

func mergeStrategies(defaults map[string]StrategySettings, current map[string]StrategySettings) map[string]StrategySettings {
	merged := make(map[string]StrategySettings, len(defaults)+len(current))
	for name, def := range defaults {
		def = cloneStrategySettings(def)
		cur, ok := current[name]
		if !ok {
			merged[name] = def
			continue
		}
		if cur.Label == "" {
			cur.Label = def.Label
		}
		if cur.Rebalance == "" {
			cur.Rebalance = def.Rebalance
		}
		if cur.Universe == nil {
			cur.Universe = def.Universe
		} else {
			cur.Universe = cloneAnyMap(cur.Universe)
		}
		if cur.Filters == nil {
			cur.Filters = def.Filters
		} else {
			cur.Filters = cloneAnyMap(cur.Filters)
		}
		if cur.Selection == nil {
			cur.Selection = def.Selection
		} else {
			cur.Selection = cloneAnyMap(cur.Selection)
		}
		if cur.Position == nil {
			cur.Position = def.Position
		} else {
			cur.Position = cloneAnyMap(cur.Position)
		}
		merged[name] = cur
	}
	for name, cur := range current {
		if _, ok := merged[name]; ok {
			continue
		}
		merged[name] = cloneStrategySettings(cur)
	}
	return merged
}

func cloneStrategySettings(strategy StrategySettings) StrategySettings {
	strategy.Universe = cloneAnyMap(strategy.Universe)
	strategy.Filters = cloneAnyMap(strategy.Filters)
	strategy.Selection = cloneAnyMap(strategy.Selection)
	strategy.Position = cloneAnyMap(strategy.Position)
	return strategy
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

func defaultStrategies() map[string]StrategySettings {
	return map[string]StrategySettings{
		"market_regime_timing": {
			Label: "市场状态择时", Enabled: true, Weight: 0.10, Rebalance: "weekly",
			Filters:  map[string]any{"market_regime": map[string]any{"trend_window": 60, "breadth_window": 20, "min_breadth": 0.45, "normal_exposure": 1.0, "weak_exposure": 0.50, "bear_exposure": 0.25}},
			Position: map[string]any{"n_holdings": 25, "max_single_weight": 0.05},
		},
		"ml_factor_ranker": {
			Label:     "机器学习因子",
			Enabled:   false,
			Weight:    0.10,
			Rebalance: "monthly",
			Universe:  map[string]any{"exclude_restricted": true, "min_total_mv": 2000000000, "max_total_mv": 120000000000, "min_amount": 30000000},
			Filters: map[string]any{
				"exclude_st":     true,
				"max_day_return": 0.095,
				"market_regime": map[string]any{
					"continuous": true, "trend_window": 60, "breadth_window": 20,
					"drawdown_window": 120, "volatility_window": 20,
					"min_breadth": 0.50, "normal_exposure": 1.0, "weak_exposure": 0.30, "bear_exposure": 0.08,
					"crisis_guard": true, "crisis_exposure": 0.0, "crisis_drawdown": -0.10, "crisis_short_return": -0.045, "crisis_breadth": 0.34,
					"risk_state": map[string]any{"enabled": true, "normal_exposure": 1.0, "weak_exposure": 0.25, "post_crash_repair_exposure": 0.35, "liquidity_squeeze_exposure": 0.0, "crash_exposure": 0.0},
				},
				"stress_controls": map[string]any{
					"enabled": true, "states": []any{"weak", "crash", "liquidity_squeeze"},
					"stress_min_amount_mult": 1.8, "max_ret20": 0.18, "max_vol20": 0.55,
					"max_amount_chg20": 2.0, "max_turnover_rate": 12.0,
					"ret20_penalty": 0.28, "vol20_penalty": 0.12, "amount_chg20_penalty": 0.03,
					"turnover_penalty": 0.12, "weak_base_penalty": 0.03, "crash_drawdown_penalty": 0.18,
				},
				"crash_gate": map[string]any{"enabled": true, "lookback_days": 20, "crash_states": []any{"crash", "liquidity_squeeze"}, "cooldown_days": 10},
				"crash_exit": map[string]any{"enabled": true, "trigger_states": []any{"crash", "liquidity_squeeze"}, "cooldown_days": 10},
			},
			Selection: map[string]any{"run_id": "fr_full_105_2010_2025_20260606", "min_pred_rank": 0.97},
			Position:  map[string]any{"n_holdings": 24, "max_single_weight": 0.035, "max_industry_weight": 0.12},
		},
		"multi_factor_composite": {
			Label: "多因子综合", Enabled: true, Weight: 0.18, Rebalance: "monthly",
			Selection: map[string]any{"component_weights": map[string]any{"small_cap_quality": 0.30, "trend_pullback": 0.25, "dividend_quality": 0.20, "earnings_revision": 0.15, "industry_prosperity": 0.10}},
			Position:  map[string]any{"n_holdings": 30, "max_single_weight": 0.05},
		},
		"small_cap_quality": {
			Label: "小盘质量", Enabled: true, Weight: 0.30, Rebalance: "monthly",
			Universe: map[string]any{"profile": "retail_edge", "min_circ_mv": 2000000000, "max_circ_mv": 5000000000, "max_total_mv": 50000000000, "min_listed_days": 250, "min_avg_amount": 20000000, "max_20d_return": 0.35, "max_amount_spike": 5.0},
			Filters: map[string]any{
				"exclude_st": true, "exclude_delist_warn": true, "min_roe_ttm": 0.05, "max_debt_ratio": 0.70,
				"max_goodwill_to_equity": 0.50, "min_consecutive_profit_years": 2, "drop_pb_top_pct": 0.10,
				"score_weights": map[string]any{"small_size": 0.45, "low_pb": 0.25, "momentum_20d": 0.20, "low_vol_20d": 0.10},
			},
			Position: map[string]any{"n_holdings": 25, "max_single_weight": 0.05},
		},
		"trend_pullback": {
			Label: "趋势回撤", Enabled: true, Weight: 0.12, Rebalance: "weekly",
			Universe: map[string]any{"profile": "retail_edge", "min_listed_days": 365, "min_avg_amount": 50000000, "avg_amount_window": 20, "max_total_mv": 80000000000, "max_20d_return": 0.30, "max_amount_spike": 4.0},
			Filters: map[string]any{
				"exclude_st": true, "long_window": 120, "mid_window": 60, "short_window": 20,
				"min_mid_return": 0.06, "max_short_return": 0.18, "min_roe": 0.06, "max_debt_ratio": 0.75,
				"score_weights": map[string]any{"trend": 0.38, "breakout": 0.17, "liquidity": 0.15, "low_vol": 0.15, "quality": 0.15},
			},
			Position: map[string]any{"n_holdings": 18, "max_single_weight": 0.05, "max_industry_weight": 0.30},
		},
		"turtle_breakout": {
			Label: "海龟突破", Enabled: true, Weight: 0.08, Rebalance: "daily",
			Universe: map[string]any{"profile": "retail_edge", "min_listed_days": 365, "min_avg_amount": 50000000, "min_total_mv": 2000000000, "max_total_mv": 120000000000, "max_20d_return": 0.45, "max_amount_spike": 5.0},
			Filters:  map[string]any{"entry_window": 55, "exit_window": 20, "atr_window": 20, "trend_window": 120},
			Position: map[string]any{"n_holdings": 20, "max_units": 4, "risk_per_unit": 0.006, "max_unit_weight": 0.02, "max_single_weight": 0.06, "max_total_exposure": 1.0, "add_atr_step": 0.5, "stop_atr": 2.0},
		},
		"dividend_quality": {
			Label: "红利质量", Enabled: true, Weight: 0.10, Rebalance: "monthly",
			Universe: map[string]any{"profile": "retail_edge", "min_listed_days": 730, "min_avg_amount": 30000000, "avg_amount_window": 20, "min_total_mv": 5000000000, "max_total_mv": 120000000000, "max_20d_return": 0.25, "max_amount_spike": 4.0},
			Filters: map[string]any{
				"exclude_st": true, "min_total_mv": 8000000000, "min_dv_ttm": 2.0, "max_pb": 3.0,
				"vol_window": 60, "min_roe": 0.07, "max_debt_ratio": 0.70,
				"score_weights": map[string]any{"dividend": 0.35, "low_vol": 0.25, "low_pb": 0.15, "quality": 0.20, "liquidity": 0.05},
			},
			Position: map[string]any{"n_holdings": 20, "max_single_weight": 0.05, "max_industry_weight": 0.25},
		},
		"earnings_revision": {
			Label: "盈利预期修正", Enabled: true, Weight: 0.10, Rebalance: "event",
			Filters: map[string]any{
				"min_profit_growth": 25.0, "min_turnaround_profit": 20000000,
				"max_post_ann_return": 0.15, "max_pe_ttm": 70.0, "max_pb": 7.0, "min_total_mv": 2000000000, "max_total_mv": 80000000000,
				"min_avg_amount": 20000000, "lookback_days": 20, "holding_days": 35,
			},
			Position: map[string]any{"max_single_weight": 0.04, "max_active_events": 20},
		},
		"industry_prosperity": {
			Label: "行业景气", Enabled: true, Weight: 0.10, Rebalance: "monthly",
			Universe:  map[string]any{"profile": "retail_edge", "min_listed_days": 250, "min_avg_amount": 30000000, "max_total_mv": 120000000000, "max_20d_return": 0.30, "max_amount_spike": 4.0},
			Selection: map[string]any{"top_n_industries": 4, "momentum_window": 20, "rank_within_industry": []any{3, 10}, "stocks_per_industry": 3, "min_industry_size": 5},
			Position:  map[string]any{"n_holdings": 12, "max_single_weight": 0.05},
		},
		"low_crowding_reversal": {
			Label: "低拥挤反转", Enabled: true, Weight: 0.10, Rebalance: "quarterly",
			Filters: map[string]any{
				"exclude_st": true, "universe_profile": "retail_edge", "min_listed_days": 365, "min_avg_amount": 20000000, "max_total_mv": 80000000000, "max_20d_return": 0.25, "min_yoy_revenue": 0.0, "min_quarter_profit_yoy": 0.20,
				"last_year_negative_or_decline": 0.50, "min_cfo_to_ni_ratio": 0.50, "industry_60d_return_min": -0.05,
			},
			Position: map[string]any{"n_holdings": 15, "max_single_weight": 0.06, "max_industry_weight": 0.30},
		},
		"event_enhanced": {
			Label: "事件增强", Enabled: false, Weight: 0.06, Rebalance: "event",
			Filters: map[string]any{
				"min_profit_growth": 25.0, "min_turnaround_profit": 20000000, "min_net_amount": 30000000, "min_amount_rate": 1.0, "min_inst_net_buy": 50000000, "min_increase_amount": 10000000, "min_avg_to_current_price_ratio": 0.95,
				"max_post_ann_return": 0.15, "max_event_day_return": 6.0, "max_event_day_return_cap": 6.0, "min_total_mv": 2000000000, "max_total_mv": 80000000000, "min_avg_amount": 20000000,
				"entry_wait_days": 5, "max_pullback_from_event_close": -0.03, "min_60d_return": 0.10, "holding_days": 10,
			},
			Position: map[string]any{"max_single_weight": 0.03, "max_active_events": 20},
		},
		"beijing_satellite": {
			Label: "北交所卫星", Enabled: false, Weight: 0.04, Rebalance: "monthly",
			Universe: map[string]any{"market": "BJ", "min_avg_amount": 5000000},
			Filters:  map[string]any{"min_yoy_profit": 0.0, "max_60d_return": 0.25},
			Position: map[string]any{"n_holdings": 10, "max_single_weight": 0.06},
		},
		"insider_buy": {
			Label: "高管增持", Enabled: true, Weight: 0.20, Rebalance: "event",
			Filters: map[string]any{
				"min_increase_amount": 10000000, "min_avg_to_current_price_ratio": 0.95,
				"max_post_ann_return": 0.20, "min_total_mv": 2000000000, "max_total_mv": 80000000000, "min_avg_amount": 20000000, "max_20d_return": 0.35, "holding_days_min": 30, "holding_days_max": 60,
			},
			Position: map[string]any{"max_single_weight": 0.05, "stop_loss": -0.15},
		},
		"lhb_follow": {
			Label: "龙虎榜", Enabled: true, Weight: 0.10, Rebalance: "event",
			Filters:  map[string]any{"min_inst_net_buy": 50000000, "exclude_limit_up": true, "max_5d_return": 0.15, "holding_days": 7},
			Position: map[string]any{"max_single_weight": 0.04, "stop_loss_break_5d_low": true},
		},
		"trend_quality": {
			Label: "趋势质量", Enabled: false, Weight: 0.12, Rebalance: "monthly",
			Universe: map[string]any{"profile": "retail_edge", "min_listed_days": 365, "min_avg_amount": 50000000, "avg_amount_window": 20, "max_total_mv": 80000000000, "max_20d_return": 0.35, "max_amount_spike": 5.0},
			Filters: map[string]any{
				"exclude_st": true, "long_window": 120, "mid_window": 60, "short_window": 20,
				"min_mid_return": 0.08, "max_short_return": 0.25, "min_roe": 0.06, "max_debt_ratio": 0.75,
				"score_weights": map[string]any{"trend": 0.45, "breakout": 0.20, "liquidity": 0.15, "low_vol": 0.10, "quality": 0.10},
			},
			Position: map[string]any{"n_holdings": 18, "max_single_weight": 0.05, "max_industry_weight": 0.30},
		},
		"garp_quality": {
			Label: "质量成长", Enabled: false, Weight: 0.12, Rebalance: "monthly",
			Universe: map[string]any{"profile": "retail_edge", "min_listed_days": 730, "min_avg_amount": 40000000, "max_total_mv": 80000000000, "max_20d_return": 0.35, "max_amount_spike": 5.0},
			Filters: map[string]any{
				"exclude_st": true, "max_pe_ttm": 60.0, "max_pb": 8.0, "max_ps_ttm": 12.0,
				"min_roe": 0.08, "min_gross_margin": 0.15, "min_revenue_yoy": 0.08, "min_profit_yoy": 0.08,
			},
			Position: map[string]any{"n_holdings": 20, "max_single_weight": 0.05, "max_industry_weight": 0.30},
		},
		"moneyflow_pullback": {
			Label: "资金低吸", Enabled: false, Weight: 0.08, Rebalance: "event",
			Filters: map[string]any{
				"min_net_amount": 30000000, "min_amount_rate": 1.0,
				"max_event_day_return": 9.5, "max_event_day_return_cap": 6.0,
				"max_amount_rate": 200.0, "min_turnover_rate": 0.0, "max_turnover_rate": 100.0,
				"min_inst_net_buy": -1000000000000, "max_inst_net_buy": 1000000000000,
				"min_total_mv": 2000000000, "max_total_mv": 80000000000,
				"entry_wait_days": 5, "min_pullback_from_event_close": -1.00,
				"max_pullback_from_event_close": -0.03,
				"max_dist_to_20d_high":          0.06, "max_dist_to_20d_high_cap": 0.06,
				"min_close_to_ma20": 0.0, "min_close_to_ma60": 0.0,
				"min_60d_return": 0.10, "min_60d_return_floor": 0.10, "holding_days": 10,
			},
			Position: map[string]any{"max_single_weight": 0.04, "max_active_events": 15},
		},
	}
}

func defaultPortfolioRisk() map[string]any {
	return map[string]any{
		"max_industry_weight": 0.30,
		"max_single_weight":   0.05,
		"max_holdings":        50,
		"cash_buffer":         0.0,
		"blacklist":           []any{},
		"market_regime": map[string]any{
			"enabled": false, "trend_window": 60, "breadth_window": 20, "min_breadth": 0.45,
			"normal_exposure": 1.0, "weak_exposure": 0.50, "bear_exposure": 0.30,
		},
	}
}

func defaultExitRules() map[string]any {
	return map[string]any{
		"enabled":       true,
		"stop_loss":     -0.12,
		"trailing_stop": -0.08,
		"trailing_exec": "next_open",
		"slippage":      0.003,
	}
}
