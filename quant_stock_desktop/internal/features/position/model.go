package position

type Pool struct {
	InitialCash     float64          `json:"initial_cash"`
	CurrentCash     float64          `json:"current_cash"`
	UpdatedAt       string           `json:"updated_at"`
	Positions       []Position       `json:"positions"`
	ClosedPositions []ClosedPosition `json:"closed_positions"`
}

type Position struct {
	TSCode         string        `json:"ts_code"`
	Name           string        `json:"name"`
	Industry       string        `json:"industry"`
	Shares         int           `json:"shares"`
	AvgCost        float64       `json:"avg_cost"`
	PeakPrice      float64       `json:"peak_price"`
	FirstEntryDate string        `json:"first_entry_date"`
	LastActionDate string        `json:"last_action_date"`
	HolderAccount  string        `json:"holder_account"`
	Note           string        `json:"note"`
	Sources        []Source      `json:"sources"`
	Trades         []TradeRecord `json:"trades"`
	Price          float64       `json:"price"`
	Cost           float64       `json:"cost"`
	MarketValue    float64       `json:"market_value"`
	UnrealizedPnL  float64       `json:"unrealized_pnl"`
	UnrealizedPct  float64       `json:"unrealized_pct"`
	PrevClose      float64       `json:"prev_close"`
	TodayPnL       float64       `json:"today_pnl"`
	TodayPct       float64       `json:"today_pct"`
	Weight         float64       `json:"weight"`
	HoldDays       int           `json:"hold_days"`
}

type ClosedPosition struct {
	TSCode      string        `json:"ts_code"`
	Name        string        `json:"name"`
	Industry    string        `json:"industry"`
	OpenDate    string        `json:"open_date"`
	CloseDate   string        `json:"close_date"`
	HoldDays    int           `json:"hold_days"`
	RealizedPnL float64       `json:"realized_pnl"`
	RealizedPct float64       `json:"realized_pct"`
	ExitReason  string        `json:"exit_reason"`
	OpenSources []Source      `json:"open_sources"`
	Trades      []TradeRecord `json:"trades"`
}

type Source struct {
	Strategy string  `json:"strategy"`
	Weight   float64 `json:"weight"`
}

type TradeRecord struct {
	Date        string  `json:"date"`
	Action      string  `json:"action"`
	Shares      int     `json:"shares"`
	Price       float64 `json:"price"`
	Amount      float64 `json:"amount"`
	RealizedPnL float64 `json:"realized_pnl"`
	ExitReason  string  `json:"exit_reason"`
	ExitPct     float64 `json:"exit_pct"`
}

type TradeRequest struct {
	TSCode     string   `json:"ts_code"`
	Action     string   `json:"action"`
	Shares     int      `json:"shares"`
	Price      float64  `json:"price"`
	Date       string   `json:"date"`
	ExitReason string   `json:"exit_reason"`
	ExitPct    float64  `json:"exit_pct"`
	Sources    []Source `json:"sources"`
}

type Signal struct {
	Date        string          `json:"date"`
	Holdings    []SignalHolding `json:"holdings"`
	Trades      SignalTrades    `json:"trades"`
	GeneratedAt string          `json:"generated_at"`
}

type SignalHolding struct {
	TSCode  string   `json:"ts_code"`
	Weight  float64  `json:"weight"`
	Sources []Source `json:"sources"`
}

type SignalTrade struct {
	TSCode string  `json:"ts_code"`
	From   float64 `json:"from"`
	To     float64 `json:"to"`
}

type SignalTrades struct {
	Buy  []SignalTrade `json:"buy"`
	Sell []SignalTrade `json:"sell"`
}

type Recommendation struct {
	Date                   string                          `json:"date"`
	GeneratedAt            string                          `json:"generated_at"`
	TotalWeight            float64                         `json:"total_weight"`
	NHoldings              int                             `json:"n_holdings"`
	NBuy                   int                             `json:"n_buy"`
	NSell                  int                             `json:"n_sell"`
	Rebalanced             bool                            `json:"rebalanced"`
	RebalanceTrades        int                             `json:"rebalance_trades"`
	ActiveStrategyVersions []RecommendationStrategyVersion `json:"active_strategy_versions"`
	Rows                   []RecommendationItem            `json:"rows"`
}

type RecommendationStrategyVersion struct {
	Strategy string  `json:"strategy"`
	Label    string  `json:"label"`
	Version  int     `json:"version"`
	Mode     string  `json:"mode"`
	Weight   float64 `json:"weight"`
}

type GenerateSignalRequest struct {
	Date                  string  `json:"date"`
	InitialCash           float64 `json:"initial_cash"`
	RebalanceFreq         int     `json:"rebalance_freq"`
	PortfolioRunID        string  `json:"portfolio_run_id"`
	PortfolioCandidateID  string  `json:"portfolio_candidate_id"`
	StrategyOverridesJSON string  `json:"-"`
}

type GenerateSignalResponse struct {
	Date    string `json:"date"`
	Output  string `json:"output"`
	Success bool   `json:"success"`
}

type ProgressEvent struct {
	Idx       int    `json:"idx"`
	Total     int    `json:"total"`
	Stage     string `json:"stage"`
	Name      string `json:"name"`
	WorkerPID int    `json:"worker_pid"`
}

type RunStatus struct {
	Task       string `json:"task"`
	TaskType   string `json:"task_type"`
	State      string `json:"state"`
	Idx        int    `json:"idx"`
	Total      int    `json:"total"`
	Stage      string `json:"stage"`
	Name       string `json:"name"`
	Message    string `json:"message"`
	WorkerPID  int    `json:"worker_pid"`
	StartedAt  string `json:"started_at"`
	UpdatedAt  string `json:"updated_at"`
	FinishedAt string `json:"finished_at"`
}

type RecommendationItem struct {
	Action       string   `json:"action"`
	TSCode       string   `json:"ts_code"`
	Name         string   `json:"name"`
	Industry     string   `json:"industry"`
	FromWeight   float64  `json:"from_weight"`
	ToWeight     float64  `json:"to_weight"`
	DeltaWeight  float64  `json:"delta_weight"`
	Price        float64  `json:"price"`
	PctChg       float64  `json:"pct_chg"`
	TargetShares int      `json:"target_shares"`
	TargetAmount float64  `json:"target_amount"`
	Sources      []Source `json:"sources"`
}

type Summary struct {
	InitialCash   float64    `json:"initial_cash"`
	Cash          float64    `json:"cash"`
	MarketValue   float64    `json:"market_value"`
	TotalAssets   float64    `json:"total_assets"`
	TotalCost     float64    `json:"total_cost"`
	TotalFee      float64    `json:"total_fee"`
	TotalPnL      float64    `json:"total_pnl"`
	TodayPnL      float64    `json:"today_pnl"`
	TodayPct      float64    `json:"today_pct"`
	UnrealizedPnL float64    `json:"unrealized_pnl"`
	UnrealizedPct float64    `json:"unrealized_pct"`
	RealizedPnL   float64    `json:"realized_pnl"`
	CumReturn     float64    `json:"cum_return"`
	NHoldings     int        `json:"n_holdings"`
	NClosed       int        `json:"n_closed"`
	UpdatedAt     string     `json:"updated_at"`
	Positions     []Position `json:"positions"`
}

type HistoryPoint struct {
	Date          string  `json:"date"`
	Cash          float64 `json:"cash"`
	MarketValue   float64 `json:"market_value"`
	Equity        float64 `json:"equity"`
	NHoldings     int     `json:"n_holdings"`
	UnrealizedPnL float64 `json:"unrealized_pnl"`
	RealizedPnL   float64 `json:"realized_pnl"`
	CumReturn     float64 `json:"cum_return"`
	DailyReturn   float64 `json:"daily_return"`
}
