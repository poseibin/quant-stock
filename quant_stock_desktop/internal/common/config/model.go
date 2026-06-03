package config

type Settings struct {
	DataPath             string                      `json:"data_path"`
	DefaultInitialCash   float64                     `json:"default_initial_cash"`
	DefaultRebalanceFreq int                         `json:"default_rebalance_freq"`
	TushareToken         string                      `json:"tushare_token"`
	DeepSeekToken        string                      `json:"deepseek_token"`
	DeepSeekModel        string                      `json:"deepseek_model"`
	Strategies           map[string]StrategySettings `json:"strategies"`
	PortfolioRisk        map[string]any              `json:"portfolio_risk"`
	ExitRules            map[string]any              `json:"exit_rules"`
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

type ValidationIssue struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}
