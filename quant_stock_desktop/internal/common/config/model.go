package config

type Settings struct {
	DataPath             string                      `json:"data_path"`
	DatabaseBackend      string                      `json:"database_backend"`
	MySQLDSN             string                      `json:"mysql_dsn"`
	DefaultInitialCash   float64                     `json:"default_initial_cash"`
	DefaultRebalanceFreq int                         `json:"default_rebalance_freq"`
	TaskConcurrency      int                         `json:"task_concurrency"`
	TushareToken         string                      `json:"tushare_token"`
	LLMProvider          string                      `json:"llm_provider"`
	OpenAIToken          string                      `json:"openai_token"`
	OpenAIModel          string                      `json:"openai_model"`
	DeepSeekToken        string                      `json:"deepseek_token"`
	DeepSeekModel        string                      `json:"deepseek_model"`
	Strategies           map[string]StrategySettings `json:"strategies"`
	PortfolioRisk        map[string]any              `json:"portfolio_risk"`
	ExitRules            map[string]any              `json:"exit_rules"`
	GovernanceRules      map[string]any              `json:"governance_rules"`
	StrategySchedule     StrategyScheduleSettings    `json:"strategy_schedule"`
}

type StrategySettings struct {
	Label     string         `json:"label"`
	Enabled   bool           `json:"enabled"`
	Weight    float64        `json:"weight"`
	Rebalance string         `json:"rebalance"`
	Universe  map[string]any `json:"universe"`
	Filters   map[string]any `json:"filters"`
	Selection map[string]any `json:"selection"`
	Position  map[string]any `json:"position"`
}

type StrategyScheduleSettings struct {
	Enabled       bool            `json:"enabled"`
	TimeOfDay     string          `json:"time_of_day"`
	Weekdays      []int           `json:"weekdays"`
	Targets       map[string]bool `json:"targets"`
	WechatWebhook string          `json:"wechat_webhook"`
	WechatUsers   []string        `json:"wechat_users"`
}

type ValidationIssue struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}
