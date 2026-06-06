package market

import (
	"database/sql"
	"math"
	"sort"
	"strconv"
	"strings"
)

type DailyBasic struct {
	TSCode    string  `json:"ts_code"`
	TradeDate string  `json:"trade_date"`
	Close     float64 `json:"close"`
	Pe        float64 `json:"pe"`
	PeTTM     float64 `json:"pe_ttm"`
	Pb        float64 `json:"pb"`
	Ps        float64 `json:"ps"`
	PsTTM     float64 `json:"ps_ttm"`
	TotalMV   float64 `json:"total_mv"`
	CircMV    float64 `json:"circ_mv"`
}

type ValuationQuery struct {
	TSCode string `json:"ts_code"`
}

type StockValuation struct {
	TSCode              string   `json:"ts_code"`
	Name                string   `json:"name"`
	Industry            string   `json:"industry"`
	TradeDate           string   `json:"trade_date"`
	Close               float64  `json:"close"`
	TotalMV             float64  `json:"total_mv"`
	CircMV              float64  `json:"circ_mv"`
	PeTTM               float64  `json:"pe_ttm"`
	Pb                  float64  `json:"pb"`
	PsTTM               float64  `json:"ps_ttm"`
	ROE                 float64  `json:"roe"`
	DebtToAssets        float64  `json:"debt_to_assets"`
	PeerCount           int      `json:"peer_count"`
	ValuationPercentile float64  `json:"valuation_percentile"`
	MarketCapPercentile float64  `json:"market_cap_percentile"`
	ImpliedMV           float64  `json:"implied_mv"`
	MispricingPct       float64  `json:"mispricing_pct"`
	Score               float64  `json:"score"`
	Verdict             string   `json:"verdict"`
	Reason              string   `json:"reason"`
	Tags                []string `json:"tags"`
}

func (service *Service) GetStockValuation(dataPath string, query ValuationQuery) (StockValuation, error) {
	tsCode := strings.TrimSpace(query.TSCode)
	if tsCode == "" || service == nil || service.repo == nil || service.repo.db == nil {
		return StockValuation{}, nil
	}
	stock, err := service.getStockBasic(tsCode)
	if err != nil {
		return StockValuation{}, err
	}
	latest, err := service.getLatestDailyBasic(tsCode)
	if err != nil {
		return StockValuation{}, err
	}
	if latest.TSCode == "" {
		return StockValuation{TSCode: tsCode, Name: stock.Name, Industry: stock.Industry}, nil
	}
	financials, err := service.ListFinancialIndicators(dataPath, FinancialQuery{TSCode: tsCode, Limit: 8})
	if err != nil {
		return StockValuation{}, err
	}
	latestFinancial := FinancialIndicator{}
	if len(financials) > 0 {
		latestFinancial = financials[len(financials)-1]
	}
	peers, err := service.listIndustryDailyBasic(latest.TradeDate, stock.Industry)
	if err != nil {
		return StockValuation{}, err
	}
	pePct := percentileRank(latest.PeTTM, metricValues(peers, func(item DailyBasic) float64 { return item.PeTTM }))
	pbPct := percentileRank(latest.Pb, metricValues(peers, func(item DailyBasic) float64 { return item.Pb }))
	psPct := percentileRank(latest.PsTTM, metricValues(peers, func(item DailyBasic) float64 { return item.PsTTM }))
	mvPct := percentileRank(latest.TotalMV, metricValues(peers, func(item DailyBasic) float64 { return item.TotalMV }))
	valuationPct := averagePositive([]float64{pePct, pbPct, psPct})
	if valuationPct < 0 {
		valuationPct = 0.5
	}
	impliedMV := impliedMarketValue(latest, peers)
	mispricingPct := 0.0
	if impliedMV > 0 && latest.TotalMV > 0 {
		mispricingPct = latest.TotalMV/impliedMV - 1
	}
	score := valuationScore(valuationPct, latestFinancial.ROE, latestFinancial.DebtToAssets)
	verdict, tags := valuationVerdict(valuationPct, mispricingPct, latestFinancial.ROE, latestFinancial.DebtToAssets, latest)
	return StockValuation{
		TSCode:              tsCode,
		Name:                stock.Name,
		Industry:            stock.Industry,
		TradeDate:           latest.TradeDate,
		Close:               latest.Close,
		TotalMV:             latest.TotalMV,
		CircMV:              latest.CircMV,
		PeTTM:               latest.PeTTM,
		Pb:                  latest.Pb,
		PsTTM:               latest.PsTTM,
		ROE:                 latestFinancial.ROE,
		DebtToAssets:        latestFinancial.DebtToAssets,
		PeerCount:           len(peers),
		ValuationPercentile: valuationPct,
		MarketCapPercentile: mvPct,
		ImpliedMV:           impliedMV,
		MispricingPct:       mispricingPct,
		Score:               score,
		Verdict:             verdict,
		Reason:              valuationReason(verdict, valuationPct, mispricingPct, latestFinancial.ROE, latestFinancial.DebtToAssets),
		Tags:                tags,
	}, nil
}

func (service *Service) getStockBasic(tsCode string) (StockBasic, error) {
	row := service.repo.db.Conn().QueryRow(`SELECT ts_code, symbol, name, area, industry, market, list_date, list_status FROM data_stock_basic WHERE ts_code = ?`, tsCode)
	var item StockBasic
	err := row.Scan(&item.TSCode, &item.Symbol, &item.Name, &item.Area, &item.Industry, &item.Market, &item.ListDate, &item.ListStatus)
	if err == sql.ErrNoRows || isMissingDataTable(err) {
		return StockBasic{TSCode: tsCode}, nil
	}
	return item, err
}

func (service *Service) getLatestDailyBasic(tsCode string) (DailyBasic, error) {
	row := service.repo.db.Conn().QueryRow(`SELECT ts_code, trade_date, close, pe, pe_ttm, pb, ps, ps_ttm, total_mv, circ_mv
		FROM data_daily_basic WHERE ts_code = ? ORDER BY trade_date DESC LIMIT 1`, tsCode)
	var item DailyBasic
	err := row.Scan(&item.TSCode, &item.TradeDate, &item.Close, &item.Pe, &item.PeTTM, &item.Pb, &item.Ps, &item.PsTTM, &item.TotalMV, &item.CircMV)
	if err == sql.ErrNoRows || isMissingDataTable(err) {
		return DailyBasic{}, nil
	}
	return item, err
}

func (service *Service) listIndustryDailyBasic(tradeDate string, industry string) ([]DailyBasic, error) {
	if tradeDate == "" || industry == "" {
		return []DailyBasic{}, nil
	}
	rows, err := service.repo.db.Conn().Query(`SELECT b.ts_code, b.trade_date, b.close, b.pe, b.pe_ttm, b.pb, b.ps, b.ps_ttm, b.total_mv, b.circ_mv
		FROM data_daily_basic b INNER JOIN data_stock_basic s ON s.ts_code = b.ts_code
		WHERE b.trade_date = ? AND s.industry = ? AND b.total_mv > 0`, tradeDate, industry)
	if isMissingDataTable(err) {
		return []DailyBasic{}, nil
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []DailyBasic{}
	for rows.Next() {
		var item DailyBasic
		if err := rows.Scan(&item.TSCode, &item.TradeDate, &item.Close, &item.Pe, &item.PeTTM, &item.Pb, &item.Ps, &item.PsTTM, &item.TotalMV, &item.CircMV); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func metricValues(items []DailyBasic, pick func(DailyBasic) float64) []float64 {
	values := make([]float64, 0, len(items))
	for _, item := range items {
		value := pick(item)
		if value > 0 && isFinite(value) {
			values = append(values, value)
		}
	}
	sort.Float64s(values)
	return values
}

func percentileRank(value float64, sortedValues []float64) float64 {
	if value <= 0 || !isFinite(value) || len(sortedValues) == 0 {
		return -1
	}
	index := sort.SearchFloat64s(sortedValues, value)
	return float64(index) / float64(len(sortedValues))
}

func median(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	mid := len(values) / 2
	if len(values)%2 == 1 {
		return values[mid]
	}
	return (values[mid-1] + values[mid]) / 2
}

func averagePositive(values []float64) float64 {
	total := 0.0
	count := 0.0
	for _, value := range values {
		if value >= 0 {
			total += value
			count++
		}
	}
	if count == 0 {
		return -1
	}
	return total / count
}

func impliedMarketValue(item DailyBasic, peers []DailyBasic) float64 {
	estimates := make([]float64, 0, 3)
	if item.PeTTM > 0 {
		if peerMedian := median(metricValues(peers, func(peer DailyBasic) float64 { return peer.PeTTM })); peerMedian > 0 {
			estimates = append(estimates, item.TotalMV*peerMedian/item.PeTTM)
		}
	}
	if item.Pb > 0 {
		if peerMedian := median(metricValues(peers, func(peer DailyBasic) float64 { return peer.Pb })); peerMedian > 0 {
			estimates = append(estimates, item.TotalMV*peerMedian/item.Pb)
		}
	}
	if item.PsTTM > 0 {
		if peerMedian := median(metricValues(peers, func(peer DailyBasic) float64 { return peer.PsTTM })); peerMedian > 0 {
			estimates = append(estimates, item.TotalMV*peerMedian/item.PsTTM)
		}
	}
	sort.Float64s(estimates)
	return median(estimates)
}

func valuationScore(valuationPct float64, roe float64, debtToAssets float64) float64 {
	score := 100 - valuationPct*100
	if roe >= 15 {
		score += 10
	} else if roe < 5 {
		score -= 10
	}
	if debtToAssets > 75 {
		score -= 10
	} else if debtToAssets > 0 && debtToAssets < 45 {
		score += 5
	}
	return math.Max(0, math.Min(100, score))
}

func valuationVerdict(valuationPct float64, mispricingPct float64, roe float64, debtToAssets float64, item DailyBasic) (string, []string) {
	tags := []string{}
	if valuationPct <= 0.35 {
		tags = append(tags, "行业估值低位")
	}
	if valuationPct >= 0.72 {
		tags = append(tags, "行业估值高位")
	}
	if roe >= 12 {
		tags = append(tags, "ROE较强")
	}
	if debtToAssets >= 70 {
		tags = append(tags, "负债偏高")
	}
	if item.PeTTM <= 0 {
		tags = append(tags, "PE不可用")
	}
	if valuationPct <= 0.35 && mispricingPct <= -0.15 && roe >= 8 && debtToAssets < 75 {
		return "低估", tags
	}
	if valuationPct >= 0.72 || mispricingPct >= 0.35 || (item.Pb > 8 && roe < 8) {
		return "虚高", tags
	}
	return "匹配", tags
}

func valuationReason(verdict string, valuationPct float64, mispricingPct float64, roe float64, debtToAssets float64) string {
	return strings.Join([]string{
		"估值分位 " + formatPctText(valuationPct),
		"相对行业中位 " + signedPctText(mispricingPct),
		"ROE " + formatPctText(roe/100),
		"资产负债率 " + formatPctText(debtToAssets/100),
		verdict,
	}, "；")
}

func formatPctText(value float64) string {
	if !isFinite(value) {
		return "—"
	}
	return strings.TrimRight(strings.TrimRight((strconvFormat(value*100, 1)), "0"), ".") + "%"
}

func signedPctText(value float64) string {
	if !isFinite(value) {
		return "—"
	}
	prefix := ""
	if value >= 0 {
		prefix = "+"
	}
	return prefix + strings.TrimRight(strings.TrimRight(strconvFormat(value*100, 1), "0"), ".") + "%"
}

func strconvFormat(value float64, precision int) string {
	return strconv.FormatFloat(value, 'f', precision, 64)
}

func isFinite(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0)
}
