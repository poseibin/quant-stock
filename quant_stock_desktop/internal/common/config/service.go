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
		LLMProvider:          "openai",
		OpenAIModel:          "gpt-5.5",
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
			_ = service.pruneUnsupportedStrategyVersions()
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
	if err := pruneUnsupportedStrategyVersionsTx(tx); err != nil {
		return err
	}
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

func (service *Service) pruneUnsupportedStrategyVersions() error {
	if service.db == nil {
		return nil
	}
	_, err := service.db.Conn().Exec(`DELETE FROM strategy_config_versions WHERE strategy <> ?`, "profit_arena_model")
	return err
}

func pruneUnsupportedStrategyVersionsTx(tx *sql.Tx) error {
	_, err := tx.Exec(`DELETE FROM strategy_config_versions WHERE strategy <> ?`, "profit_arena_model")
	return err
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
	settings.OpenAIToken = strings.TrimSpace(settings.OpenAIToken)
	settings.DeepSeekToken = strings.TrimSpace(settings.DeepSeekToken)
	if strings.TrimSpace(settings.LLMProvider) == "" {
		if settings.OpenAIToken != "" {
			settings.LLMProvider = "openai"
		} else if settings.DeepSeekToken != "" {
			settings.LLMProvider = "deepseek"
		}
	}
	settings.LLMProvider = normalizeLLMProvider(settings.LLMProvider)
	if settings.OpenAIModel == "" {
		settings.OpenAIModel = "gpt-5.5"
	}
	if settings.DeepSeekModel == "" {
		settings.DeepSeekModel = "deepseek-v4-pro"
	}
	settings.Strategies = normalizeStrategies(settings.Strategies)
	if settings.PortfolioRisk == nil {
		settings.PortfolioRisk = defaultPortfolioRisk()
	}
	if settings.ExitRules == nil {
		settings.ExitRules = defaultExitRules()
	}
	settings.GovernanceRules = normalizeGovernanceRules(settings.GovernanceRules)
	settings.StrategySchedule = normalizeStrategySchedule(settings.StrategySchedule)
	return settings
}

func normalizeLLMProvider(provider string) string {
	switch strings.ToLower(strings.TrimSpace(provider)) {
	case "openai", "chatgpt", "gpt", "chat_gpt":
		return "openai"
	case "deepseek":
		return "deepseek"
	default:
		return "openai"
	}
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
			"arena": true,
		}
	} else {
		schedule.Targets = map[string]bool{"arena": true}
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
		"profit_arena_factor_store_id":       "profit_arena_v1",
		"min_arena_score":                    85.0,
		"min_rank_ic":                        0.08,
		"min_capital_annual_return":          0.12,
		"max_capital_drawdown":               0.22,
		"min_capital_sharpe":                 0.30,
		"max_single_weight":                  0.10,
		"max_industry_weight":                0.30,
		"max_target_participation_rate":      0.02,
		"max_allowed_participation_rate":     0.05,
		"require_fresh_factor_snapshot":      true,
		"require_profit_arena_spec_pass":     true,
		"require_positive_capital_return":    true,
		"block_untradeable_boards":           true,
		"auto_refresh_after_factor_snapshot": true,
	}
}

func normalizeGovernanceRules(current map[string]any) map[string]any {
	merged := mergeAnyMap(defaultGovernanceRules(), current)
	for _, key := range legacyGovernanceRuleKeys() {
		delete(merged, key)
	}
	return merged
}

func legacyGovernanceRuleKeys() []string {
	return []string{
		"min_promotable_score",
		"min_research_score",
		"min_paper_score",
		"min_active_candidate_score",
		"max_drawdown",
		"min_sharpe",
		"min_calmar",
		"max_turnover",
		"min_stability_rate",
		"min_walk_forward_pass_rate",
		"min_eval_walk_forward_windows",
		"min_parameter_stable_rate",
		"require_positive_return",
		"allow_missing_parameter_tests",
	}
}

func defaultStrategies() map[string]StrategySettings {
	return map[string]StrategySettings{
		"profit_arena_model": {
			Label:     "收益擂台",
			Enabled:   true,
			Weight:    1.0,
			Rebalance: "daily",
			Universe:  map[string]any{"exclude_restricted": true},
			Filters:   map[string]any{},
			Selection: map[string]any{"factor_store_id": "profit_arena_v1"},
			Position:  map[string]any{"n_holdings": 10, "max_single_weight": 0.10},
		},
	}
}

func normalizeStrategies(strategies map[string]StrategySettings) map[string]StrategySettings {
	defaults := defaultStrategies()
	result := cloneStrategies(defaults)
	if existing, ok := strategies["profit_arena_model"]; ok {
		merged := mergeStrategies(defaults, map[string]StrategySettings{"profit_arena_model": existing})["profit_arena_model"]
		merged.Enabled = true
		merged.Weight = 1.0
		if strings.TrimSpace(merged.Label) == "" {
			merged.Label = "收益擂台"
		}
		result["profit_arena_model"] = merged
	}
	return result
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
