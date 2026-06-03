package market

import (
	"encoding/json"
	"strconv"
	"strings"
	"time"
)

type LimitUpMomentumQuery struct {
	Limit       int `json:"limit"`
	Lookback    int `json:"lookback"`
	HistoryDays int `json:"history_days"`
}

type LimitUpMomentumCandidate struct {
	TSCode            string        `json:"ts_code"`
	Name              string        `json:"name"`
	Industry          string        `json:"industry"`
	TradeDate         string        `json:"trade_date"`
	Close             float64       `json:"close"`
	Stage             string        `json:"stage"`
	Recommendation    string        `json:"recommendation"`
	Score             float64       `json:"score"`
	ChainPotential    float64       `json:"chain_potential"`
	EndRisk           float64       `json:"end_risk"`
	LiquidityRisk     float64       `json:"liquidity_risk"`
	FundConfirmation  float64       `json:"fund_confirmation"`
	LimitUpCount      int           `json:"limit_up_count"`
	ConsecutiveBoards int           `json:"consecutive_boards"`
	NextDayReturn     float64       `json:"next_day_return"`
	Return3D          float64       `json:"return_3d"`
	Return5D          float64       `json:"return_5d"`
	Return10D         float64       `json:"return_10d"`
	MaxDrawdown5D     float64       `json:"max_drawdown_5d"`
	Recent20Return    float64       `json:"recent_20_return"`
	Recent60Return    float64       `json:"recent_60_return"`
	TurnoverRate      float64       `json:"turnover_rate"`
	VolumeRatio       float64       `json:"volume_ratio"`
	Amount            float64       `json:"amount"`
	TotalMV           float64       `json:"total_mv"`
	CircMV            float64       `json:"circ_mv"`
	DragonTigerNetBuy float64       `json:"dragon_tiger_net_buy"`
	InstitutionNetBuy float64       `json:"institution_net_buy"`
	Reasons           []string      `json:"reasons"`
	Risks             []string      `json:"risks"`
	Bars              []BreakoutBar `json:"bars"`
	ProjectedBars     []BreakoutBar `json:"projected_bars"`
}

func NormalizeLimitUpMomentumQuery(query LimitUpMomentumQuery) LimitUpMomentumQuery {
	if query.Limit <= 0 || query.Limit > 100 {
		query.Limit = 40
	}
	if query.Lookback <= 0 || query.Lookback > 120 {
		query.Lookback = 20
	}
	if query.HistoryDays <= 0 || query.HistoryDays > 1500 {
		query.HistoryDays = 760
	}
	return query
}

func LimitUpMomentumCacheKey(query LimitUpMomentumQuery) string {
	query = NormalizeLimitUpMomentumQuery(query)
	return strings.Join([]string{
		"limit_up_momentum",
		"lookback", strconv.Itoa(query.Lookback),
		"history", strconv.Itoa(query.HistoryDays),
	}, ":")
}

func (service *Service) ListLimitUpMomentumCandidates(dataPath string, query LimitUpMomentumQuery) ([]LimitUpMomentumCandidate, error) {
	query = NormalizeLimitUpMomentumQuery(query)
	if service == nil || service.repo == nil || service.repo.db == nil {
		return []LimitUpMomentumCandidate{}, nil
	}
	cacheKey := LimitUpMomentumCacheKey(query)
	ok, err := service.repo.HasLimitUpMomentumCache(cacheKey)
	if err != nil {
		return nil, err
	}
	if !ok {
		return []LimitUpMomentumCandidate{}, nil
	}
	return service.repo.ListLimitUpMomentumCache(cacheKey, query.Limit)
}

func (repo *Repository) ListLimitUpMomentumCache(cacheKey string, limit int) ([]LimitUpMomentumCandidate, error) {
	rows, err := repo.db.Query(`SELECT payload_json FROM limit_up_momentum_cache
		WHERE cache_key = ? ORDER BY rank ASC LIMIT ?`, cacheKey, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]LimitUpMomentumCandidate, 0)
	for rows.Next() {
		var payload string
		if err := rows.Scan(&payload); err != nil {
			return nil, err
		}
		var item LimitUpMomentumCandidate
		if err := json.Unmarshal([]byte(payload), &item); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (repo *Repository) HasLimitUpMomentumCache(cacheKey string) (bool, error) {
	var count int
	err := repo.db.QueryRow(`SELECT COUNT(1) FROM limit_up_momentum_cache_meta WHERE cache_key = ?`, cacheKey).Scan(&count)
	return count > 0, err
}

func (repo *Repository) ReplaceLimitUpMomentumCache(cacheKey string, items []LimitUpMomentumCandidate) error {
	now := time.Now().Format("2006-01-02 15:04:05")
	tx, err := repo.db.Begin()
	if err != nil {
		return err
	}
	if _, err := tx.Exec(`DELETE FROM limit_up_momentum_cache WHERE cache_key = ?`, cacheKey); err != nil {
		_ = tx.Rollback()
		return err
	}
	if _, err := tx.Exec(`INSERT INTO limit_up_momentum_cache_meta (
		cache_key, item_count, generated_at, updated_at
	) VALUES (?, ?, ?, ?)
	ON CONFLICT(cache_key) DO UPDATE SET
		item_count = excluded.item_count,
		generated_at = excluded.generated_at,
		updated_at = excluded.updated_at`, cacheKey, len(items), now, now); err != nil {
		_ = tx.Rollback()
		return err
	}
	stmt, err := tx.Prepare(`INSERT INTO limit_up_momentum_cache (
		cache_key, rank, ts_code, trade_date, score, payload_json, generated_at, updated_at
	) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`)
	if err != nil {
		_ = tx.Rollback()
		return err
	}
	defer stmt.Close()
	for i, item := range items {
		payload, err := json.Marshal(item)
		if err != nil {
			_ = tx.Rollback()
			return err
		}
		if _, err := stmt.Exec(cacheKey, i+1, item.TSCode, item.TradeDate, item.Score, string(payload), now, now); err != nil {
			_ = tx.Rollback()
			return err
		}
	}
	return tx.Commit()
}
