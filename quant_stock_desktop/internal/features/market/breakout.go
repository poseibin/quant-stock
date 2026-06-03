package market

import (
	"encoding/json"
	"io"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	parquet "github.com/parquet-go/parquet-go"
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
	TSCode        string        `json:"ts_code"`
	Name          string        `json:"name"`
	Industry      string        `json:"industry"`
	LatestDate    string        `json:"latest_date"`
	Close         float64       `json:"close"`
	Score         float64       `json:"score"`
	FlatScore     float64       `json:"flat_score"`
	BreakoutScore float64       `json:"breakout_score"`
	QualityScore  float64       `json:"quality_score"`
	BaseLow       float64       `json:"base_low"`
	BaseHigh      float64       `json:"base_high"`
	BaseRatio     float64       `json:"base_ratio"`
	BaseReturn    float64       `json:"base_return"`
	RecentReturn  float64       `json:"recent_return"`
	LimitUpCount  int           `json:"limit_up_count"`
	VolumeSurge   float64       `json:"volume_surge"`
	ROE           float64       `json:"roe"`
	NetMargin     float64       `json:"net_margin"`
	DebtToAssets  float64       `json:"debt_to_assets"`
	Reasons       []string      `json:"reasons"`
	Bars          []BreakoutBar `json:"bars"`
	ProjectedBars []BreakoutBar `json:"projected_bars"`
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
	query = normalizeBreakoutQuery(query)
	scanQuery := query
	if scanQuery.Limit < 100 {
		scanQuery.Limit = 100
	}
	out, err := scanLimitBreakoutCandidates(dataPath, scanQuery)
	if err != nil {
		return nil, err
	}
	if service != nil && service.repo != nil && service.repo.db != nil {
		if err := service.repo.ReplaceLimitBreakoutCache(breakoutCacheKey(query), out); err != nil {
			return nil, err
		}
	}
	if len(out) > query.Limit {
		out = out[:query.Limit]
	}
	return out, nil
}

func scanLimitBreakoutCandidates(dataPath string, query BreakoutQuery) ([]LimitBreakoutCandidate, error) {
	stocks, err := readStockBasicMap(dataPath)
	if err != nil {
		return nil, err
	}
	barsByCode, err := readRecentDailyGroups(dataPath, query.Lookback+80)
	if err != nil {
		return nil, err
	}
	financials, _ := readLatestFinancialMap(dataPath)
	out := make([]LimitBreakoutCandidate, 0)
	for code, bars := range barsByCode {
		stock, ok := stocks[code]
		if !ok || stock.ListStatus != "L" || strings.Contains(strings.ToUpper(stock.Name), "ST") {
			continue
		}
		candidate, ok := scoreLimitBreakout(stock, bars, financials[code], query.Lookback, query.RecentDays)
		if ok {
			out = append(out, candidate)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Score > out[j].Score })
	if len(out) > query.Limit {
		out = out[:query.Limit]
	}
	return out, nil
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
	rows, err := repo.db.Query(`SELECT payload_json FROM limit_breakout_cache
		WHERE cache_key = ? ORDER BY rank ASC LIMIT ?`, cacheKey, limit)
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
	err := repo.db.QueryRow(`SELECT COUNT(1) FROM limit_breakout_cache_meta WHERE cache_key = ?`, cacheKey).Scan(&count)
	return count > 0, err
}

func (repo *Repository) ReplaceLimitBreakoutCache(cacheKey string, items []LimitBreakoutCandidate) error {
	now := time.Now().Format("2006-01-02 15:04:05")
	tx, err := repo.db.Begin()
	if err != nil {
		return err
	}
	if _, err := tx.Exec(`DELETE FROM limit_breakout_cache WHERE cache_key = ?`, cacheKey); err != nil {
		_ = tx.Rollback()
		return err
	}
	if _, err := tx.Exec(`INSERT INTO limit_breakout_cache_meta (
		cache_key, item_count, generated_at, updated_at
	) VALUES (?, ?, ?, ?)
	ON CONFLICT(cache_key) DO UPDATE SET
		item_count = excluded.item_count,
		generated_at = excluded.generated_at,
		updated_at = excluded.updated_at`, cacheKey, len(items), now, now); err != nil {
		_ = tx.Rollback()
		return err
	}
	stmt, err := tx.Prepare(`INSERT INTO limit_breakout_cache (
		cache_key, rank, ts_code, latest_date, score, payload_json, generated_at, updated_at
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

func scoreLimitBreakout(stock StockBasic, allBars []DailyBar, fi FinancialIndicator, lookback, recentDays int) (LimitBreakoutCandidate, bool) {
	if len(allBars) < 260 {
		return LimitBreakoutCandidate{}, false
	}
	sort.Slice(allBars, func(i, j int) bool { return allBars[i].TradeDate < allBars[j].TradeDate })
	if len(allBars) > lookback+recentDays {
		allBars = allBars[len(allBars)-lookback-recentDays:]
	}
	if len(allBars) < 260+recentDays {
		return LimitBreakoutCandidate{}, false
	}
	base := allBars[:len(allBars)-recentDays]
	recent := allBars[len(allBars)-recentDays:]
	baseLow, baseHigh := closeRange(base)
	if baseLow <= 0 || baseHigh <= 0 {
		return LimitBreakoutCandidate{}, false
	}
	baseRatio := baseHigh / baseLow
	baseReturn := base[len(base)-1].Close/base[0].Close - 1
	baseVolatility := closeVolatility(base)
	latest := recent[len(recent)-1]
	recentReturn := latest.Close/recent[0].Close - 1
	limitCount := countLimitUps(recent, stock)
	volumeSurge := amountSurge(base, recent)
	breakoutRatio := latest.Close / baseHigh

	flatScore := clamp01((2.4-baseRatio)/1.1)*0.45 + clamp01((0.55-math.Abs(baseReturn))/0.55)*0.25 + clamp01((0.018-baseVolatility)/0.018)*0.30
	breakoutScore := clamp01(recentReturn/0.75)*0.35 + clamp01(float64(limitCount)/5.0)*0.35 + clamp01((volumeSurge-1.0)/5.0)*0.15 + clamp01((breakoutRatio-1.0)/0.5)*0.15
	qualityScore := businessQualityScore(fi)
	score := 100 * (flatScore*0.42 + breakoutScore*0.38 + qualityScore*0.20)

	if flatScore < 0.38 || breakoutScore < 0.22 {
		return LimitBreakoutCandidate{}, false
	}
	if recentReturn < 0.15 && limitCount == 0 && breakoutRatio < 1.05 {
		return LimitBreakoutCandidate{}, false
	}
	reasons := []string{}
	if baseRatio < 1.8 {
		reasons = append(reasons, "长期箱体窄，K线接近水平")
	}
	if math.Abs(baseReturn) < 0.30 {
		reasons = append(reasons, "多年中枢变化小")
	}
	if limitCount > 0 {
		reasons = append(reasons, "近期出现涨停/接近涨停")
	}
	if volumeSurge >= 2.5 {
		reasons = append(reasons, "成交额明显放大")
	}
	if fi.ROE > 0 {
		reasons = append(reasons, "最新ROE为正")
	}
	if fi.DebtToAssets > 0 && fi.DebtToAssets < 70 {
		reasons = append(reasons, "资产负债率可控")
	}
	chartBars := toBreakoutBars(tailDailyBars(allBars, 140), false)
	projected := projectLimitUpBars(latest, stock, 5)
	return LimitBreakoutCandidate{
		TSCode: stock.TSCode, Name: stock.Name, Industry: stock.Industry,
		LatestDate: latest.TradeDate, Close: latest.Close, Score: score,
		FlatScore: flatScore * 100, BreakoutScore: breakoutScore * 100, QualityScore: qualityScore * 100,
		BaseLow: baseLow, BaseHigh: baseHigh, BaseRatio: baseRatio, BaseReturn: baseReturn,
		RecentReturn: recentReturn, LimitUpCount: limitCount, VolumeSurge: volumeSurge,
		ROE: fi.ROE, NetMargin: fi.NetMargin, DebtToAssets: fi.DebtToAssets,
		Reasons: reasons, Bars: chartBars, ProjectedBars: projected,
	}, true
}

func readRecentDailyGroups(dataPath string, maxBars int) (map[string][]DailyBar, error) {
	files, _ := filepath.Glob(filepath.Join(dataPath, "raw", "daily", "*.parquet"))
	sort.Strings(files)
	out := map[string][]DailyBar{}
	for _, filePath := range files {
		file, err := os.Open(filePath)
		if err != nil {
			continue
		}
		reader := parquet.NewGenericReader[DailyBar](file)
		buffer := make([]DailyBar, 4096)
		for {
			count, readErr := reader.Read(buffer)
			for i := 0; i < count; i++ {
				bar := buffer[i]
				if bar.TSCode == "" || bar.Close <= 0 {
					continue
				}
				items := append(out[bar.TSCode], bar)
				if len(items) > maxBars {
					items = items[len(items)-maxBars:]
				}
				out[bar.TSCode] = items
			}
			if readErr == io.EOF {
				break
			}
			if readErr != nil {
				_ = reader.Close()
				_ = file.Close()
				return nil, readErr
			}
		}
		_ = reader.Close()
		_ = file.Close()
	}
	return out, nil
}

func readStockBasicMap(dataPath string) (map[string]StockBasic, error) {
	items, err := readStockBasicAll(filepath.Join(dataPath, "raw", "stock_basic", "data.parquet"))
	if err != nil {
		return nil, err
	}
	out := make(map[string]StockBasic, len(items))
	for _, item := range items {
		out[item.TSCode] = item
	}
	return out, nil
}

func readStockBasicAll(path string) ([]StockBasic, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	reader := parquet.NewGenericReader[StockBasic](file)
	defer reader.Close()
	out := []StockBasic{}
	buffer := make([]StockBasic, 1024)
	for {
		count, readErr := reader.Read(buffer)
		out = append(out, buffer[:count]...)
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			return nil, readErr
		}
	}
	return out, nil
}

func readLatestFinancialMap(dataPath string) (map[string]FinancialIndicator, error) {
	files, _ := filepath.Glob(filepath.Join(dataPath, "raw", "fina_indicator", "*.parquet"))
	sort.Strings(files)
	out := map[string]FinancialIndicator{}
	for _, filePath := range files {
		file, err := os.Open(filePath)
		if err != nil {
			continue
		}
		reader := parquet.NewGenericReader[FinancialIndicator](file)
		buffer := make([]FinancialIndicator, 2048)
		for {
			count, readErr := reader.Read(buffer)
			for i := 0; i < count; i++ {
				item := buffer[i]
				if item.TSCode == "" {
					continue
				}
				prev := out[item.TSCode]
				if item.EndDate >= prev.EndDate {
					out[item.TSCode] = item
				}
			}
			if readErr == io.EOF {
				break
			}
			if readErr != nil {
				_ = reader.Close()
				_ = file.Close()
				return out, readErr
			}
		}
		_ = reader.Close()
		_ = file.Close()
	}
	return out, nil
}

func closeRange(bars []DailyBar) (float64, float64) {
	low := math.MaxFloat64
	high := 0.0
	for _, bar := range bars {
		if bar.Close <= 0 {
			continue
		}
		low = math.Min(low, bar.Close)
		high = math.Max(high, bar.Close)
	}
	if low == math.MaxFloat64 {
		return 0, 0
	}
	return low, high
}

func closeVolatility(bars []DailyBar) float64 {
	if len(bars) < 2 {
		return 0
	}
	returns := make([]float64, 0, len(bars)-1)
	for i := 1; i < len(bars); i++ {
		if bars[i-1].Close > 0 && bars[i].Close > 0 {
			returns = append(returns, bars[i].Close/bars[i-1].Close-1)
		}
	}
	if len(returns) == 0 {
		return 0
	}
	avg := 0.0
	for _, v := range returns {
		avg += v
	}
	avg /= float64(len(returns))
	variance := 0.0
	for _, v := range returns {
		variance += (v - avg) * (v - avg)
	}
	return math.Sqrt(variance / float64(len(returns)))
}

func countLimitUps(bars []DailyBar, stock StockBasic) int {
	threshold := limitRate(stock)*100 - 0.5
	count := 0
	for _, bar := range bars {
		if bar.PctChg >= threshold || (bar.PreClose > 0 && bar.Close/bar.PreClose-1 >= limitRate(stock)-0.005) {
			count++
		}
	}
	return count
}

func amountSurge(base, recent []DailyBar) float64 {
	baseTail := tailDailyBars(base, 120)
	baseAmount := avgAmount(baseTail)
	recentAmount := avgAmount(tailDailyBars(recent, 5))
	if baseAmount <= 0 {
		return 0
	}
	return recentAmount / baseAmount
}

func avgAmount(bars []DailyBar) float64 {
	if len(bars) == 0 {
		return 0
	}
	total := 0.0
	count := 0
	for _, bar := range bars {
		if bar.Amount > 0 {
			total += bar.Amount
			count++
		}
	}
	if count == 0 {
		return 0
	}
	return total / float64(count)
}

func businessQualityScore(fi FinancialIndicator) float64 {
	roe := clamp01(fi.ROE / 12.0)
	margin := clamp01(fi.NetMargin / 12.0)
	debt := 0.5
	if fi.DebtToAssets > 0 {
		debt = clamp01((85.0 - fi.DebtToAssets) / 60.0)
	}
	return roe*0.45 + margin*0.25 + debt*0.30
}

func toBreakoutBars(bars []DailyBar, projected bool) []BreakoutBar {
	out := make([]BreakoutBar, 0, len(bars))
	for _, bar := range bars {
		out = append(out, BreakoutBar{
			TradeDate: bar.TradeDate, Open: bar.Open, High: bar.High, Low: bar.Low,
			Close: bar.Close, PctChg: bar.PctChg, Projected: projected,
		})
	}
	return out
}

func projectLimitUpBars(latest DailyBar, stock StockBasic, days int) []BreakoutBar {
	rate := limitRate(stock)
	out := make([]BreakoutBar, 0, days)
	prev := latest.Close
	date := parseTradeDate(latest.TradeDate)
	for i := 0; i < days; i++ {
		date = nextCalendarTradeDate(date)
		closePrice := round2(prev * (1 + rate))
		out = append(out, BreakoutBar{
			TradeDate: date.Format("20060102"),
			Open:      prev, Low: prev, High: closePrice, Close: closePrice,
			PctChg: rate * 100, Projected: true,
		})
		prev = closePrice
	}
	return out
}

func limitRate(stock StockBasic) float64 {
	name := strings.ToUpper(stock.Name)
	code := stock.TSCode
	if strings.Contains(name, "ST") {
		return 0.05
	}
	if strings.HasPrefix(code, "688") || strings.HasPrefix(code, "300") {
		return 0.20
	}
	if strings.HasPrefix(code, "8") || strings.HasPrefix(code, "4") || strings.Contains(code, ".BJ") {
		return 0.30
	}
	return 0.10
}

func tailDailyBars(bars []DailyBar, n int) []DailyBar {
	if len(bars) <= n {
		return bars
	}
	return bars[len(bars)-n:]
}

func parseTradeDate(value string) time.Time {
	if t, err := time.Parse("20060102", value); err == nil {
		return t
	}
	return time.Now()
}

func nextCalendarTradeDate(value time.Time) time.Time {
	next := value.AddDate(0, 0, 1)
	for next.Weekday() == time.Saturday || next.Weekday() == time.Sunday {
		next = next.AddDate(0, 0, 1)
	}
	return next
}

func round2(value float64) float64 {
	return math.Round(value*100) / 100
}

func clamp01(value float64) float64 {
	if value < 0 {
		return 0
	}
	if value > 1 {
		return 1
	}
	return value
}
