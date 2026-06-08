package market

import (
	"encoding/json"
	"strconv"
	"strings"
	"time"
)

type BreakoutQuery struct {
	Limit      int `json:"limit"`
	Lookback   int `json:"lookback"`
	RecentDays int `json:"recent_days"`
}

type BreakoutBar struct {
	TradeDate string  `json:"trade_date"`
	Open      float64 `json:"open"`
	High      float64 `json:"high"`
	Low       float64 `json:"low"`
	Close     float64 `json:"close"`
	PctChg    float64 `json:"pct_chg"`
	Projected bool    `json:"projected"`
}

type LimitBreakoutCandidate struct {
	TSCode            string        `json:"ts_code"`
	Name              string        `json:"name"`
	Industry          string        `json:"industry"`
	LatestDate        string        `json:"latest_date"`
	Close             float64       `json:"close"`
	Score             float64       `json:"score"`
	FlatScore         float64       `json:"flat_score"`
	BreakoutScore     float64       `json:"breakout_score"`
	QualityScore      float64       `json:"quality_score"`
	BaseLow           float64       `json:"base_low"`
	BaseHigh          float64       `json:"base_high"`
	BaseRatio         float64       `json:"base_ratio"`
	BaseReturn        float64       `json:"base_return"`
	RecentReturn      float64       `json:"recent_return"`
	LimitUpCount      int           `json:"limit_up_count"`
	VolumeSurge       float64       `json:"volume_surge"`
	ROE               float64       `json:"roe"`
	NetMargin         float64       `json:"net_margin"`
	DebtToAssets      float64       `json:"debt_to_assets"`
	Reasons           []string      `json:"reasons"`
	Bars              []BreakoutBar `json:"bars"`
	ProjectedBars     []BreakoutBar `json:"projected_bars"`
	FirstSeenDate     string        `json:"first_seen_date"`
	LastSeenDate      string        `json:"last_seen_date"`
	SeenCount         int           `json:"seen_count"`
	ObservationDays   int           `json:"observation_days"`
	ObservationStatus string        `json:"observation_status"`
	ObservationReason string        `json:"observation_reason"`
	ObservationResult string        `json:"observation_result"`
}

func (service *Service) ListLimitBreakoutCandidates(dataPath string, query BreakoutQuery) ([]LimitBreakoutCandidate, error) {
	query = normalizeBreakoutQuery(query)
	if service != nil && service.repo != nil && service.repo.db != nil {
		cacheKey := breakoutCacheKey(query)
		ok, err := service.repo.HasLimitBreakoutCache(cacheKey)
		if err != nil {
			return nil, err
		}
		if !ok {
			return []LimitBreakoutCandidate{}, nil
		}
		cached, err := service.repo.ListLimitBreakoutCache(cacheKey, query.Limit)
		if err != nil {
			return nil, err
		}
		if cached != nil {
			return cached, nil
		}
	}
	return []LimitBreakoutCandidate{}, nil
}

func (service *Service) RefreshLimitBreakoutCandidates(dataPath string, query BreakoutQuery) ([]LimitBreakoutCandidate, error) {
	return service.ListLimitBreakoutCandidates(dataPath, query)
}

func (service *Service) ClearLimitBreakoutCandidates() error {
	if service == nil || service.repo == nil || service.repo.db == nil {
		return nil
	}
	return service.repo.ClearLimitBreakoutCache()
}

func normalizeBreakoutQuery(query BreakoutQuery) BreakoutQuery {
	if query.Limit <= 0 || query.Limit > 100 {
		query.Limit = 30
	}
	if query.Lookback <= 0 || query.Lookback > 1300 {
		query.Lookback = 1250
	}
	if query.RecentDays <= 0 || query.RecentDays > 60 {
		query.RecentDays = 20
	}
	return query
}

func breakoutCacheKey(query BreakoutQuery) string {
	return strings.Join([]string{
		"long_flat_limit_up",
		"lookback", strconv.Itoa(query.Lookback),
		"recent", strconv.Itoa(query.RecentDays),
	}, ":")
}

func NormalizeBreakoutQuery(query BreakoutQuery) BreakoutQuery {
	return normalizeBreakoutQuery(query)
}

func BreakoutCacheKey(query BreakoutQuery) string {
	return breakoutCacheKey(normalizeBreakoutQuery(query))
}

func (repo *Repository) ListLimitBreakoutCache(cacheKey string, limit int) ([]LimitBreakoutCandidate, error) {
	rows, err := repo.db.Conn().Query("SELECT payload_json FROM market_limit_breakout_cache WHERE cache_key = ? ORDER BY `rank` ASC LIMIT ?", cacheKey, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]LimitBreakoutCandidate, 0)
	for rows.Next() {
		var payload string
		if err := rows.Scan(&payload); err != nil {
			return nil, err
		}
		var item LimitBreakoutCandidate
		if err := json.Unmarshal([]byte(payload), &item); err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (repo *Repository) HasLimitBreakoutCache(cacheKey string) (bool, error) {
	var count int
	err := repo.db.Conn().QueryRow(`SELECT COUNT(1) FROM market_limit_breakout_cache_meta WHERE cache_key = ?`, cacheKey).Scan(&count)
	return count > 0, err
}

func (repo *Repository) ReplaceLimitBreakoutCache(cacheKey string, items []LimitBreakoutCandidate) error {
	now := time.Now().Format("2006-01-02 15:04:05")
	tx, err := repo.db.Conn().Begin()
	if err != nil {
		return err
	}
	if _, err := tx.Exec(`DELETE FROM market_limit_breakout_cache WHERE cache_key = ?`, cacheKey); err != nil {
		_ = tx.Rollback()
		return err
	}
	if _, err := tx.Exec(
		repo.db.UpsertSQL(
			"market_limit_breakout_cache_meta",
			[]string{"cache_key", "item_count", "generated_at", "updated_at"},
			[]string{"cache_key"},
			[]string{"item_count", "generated_at", "updated_at"},
		),
		cacheKey, len(items), now, now,
	); err != nil {
		_ = tx.Rollback()
		return err
	}
	stmt, err := tx.Prepare(`INSERT INTO market_limit_breakout_cache (
		cache_key, ` + "`rank`" + `, ts_code, latest_date, score, payload_json, generated_at, updated_at
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
		if _, err := stmt.Exec(cacheKey, i+1, item.TSCode, item.LatestDate, item.Score, string(payload), now, now); err != nil {
			_ = tx.Rollback()
			return err
		}
	}
	return tx.Commit()
}

func (repo *Repository) ClearLimitBreakoutCache() error {
	tx, err := repo.db.Conn().Begin()
	if err != nil {
		return err
	}
	if _, err := tx.Exec(`DELETE FROM market_limit_breakout_cache`); err != nil {
		_ = tx.Rollback()
		return err
	}
	if _, err := tx.Exec(`DELETE FROM market_limit_breakout_cache_meta`); err != nil {
		_ = tx.Rollback()
		return err
	}
	return tx.Commit()
}
