package market

import (
	"io"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	parquet "github.com/parquet-go/parquet-go"
)

type DailyBasic struct {
	TSCode    string  `parquet:"ts_code" json:"ts_code"`
	TradeDate string  `parquet:"trade_date" json:"trade_date"`
	Close     float64 `parquet:"close" json:"close"`
	Pe        float64 `parquet:"pe" json:"pe"`
	PeTTM     float64 `parquet:"pe_ttm" json:"pe_ttm"`
	Pb        float64 `parquet:"pb" json:"pb"`
	Ps        float64 `parquet:"ps" json:"ps"`
	PsTTM     float64 `parquet:"ps_ttm" json:"ps_ttm"`
	TotalMV   float64 `parquet:"total_mv" json:"total_mv"`
	CircMV    float64 `parquet:"circ_mv" json:"circ_mv"`
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
	if tsCode == "" {
		return StockValuation{}, nil
	}

	stockMap, err := readStockMap(dataPath)
	if err != nil {
		return StockValuation{}, err
	}
	stock := stockMap[tsCode]
	latest, filePath, err := latestDailyBasic(dataPath, tsCode)
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

	peers, err := readIndustryDailyBasic(filePath, latest.TradeDate, stock.Industry, stockMap)
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

func readStockMap(dataPath string) (map[string]StockBasic, error) {
	file, err := os.Open(filepath.Join(dataPath, "raw", "stock_basic", "data.parquet"))
	if err != nil {
		return nil, err
	}
	defer file.Close()

	reader := parquet.NewGenericReader[StockBasic](file)
	defer reader.Close()

	out := make(map[string]StockBasic)
	buffer := make([]StockBasic, 512)
	for {
		count, err := reader.Read(buffer)
		for index := 0; index < count; index++ {
			stock := buffer[index]
			out[stock.TSCode] = stock
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
	}
	return out, nil
}

func latestDailyBasic(dataPath string, tsCode string) (DailyBasic, string, error) {
	files, _ := filepath.Glob(filepath.Join(dataPath, "raw", "daily_basic", "*.parquet"))
	sort.Sort(sort.Reverse(sort.StringSlice(files)))
	for _, filePath := range files {
		item, err := readLatestDailyBasicFile(filePath, tsCode)
		if err != nil {
			return DailyBasic{}, "", err
		}
		if item.TSCode != "" {
			return item, filePath, nil
		}
	}
	return DailyBasic{}, "", nil
}

func readLatestDailyBasicFile(filePath string, tsCode string) (DailyBasic, error) {
	file, err := os.Open(filePath)
	if err != nil {
		return DailyBasic{}, err
	}
	defer file.Close()

	reader := parquet.NewGenericReader[DailyBasic](file)
	defer reader.Close()

	latest := DailyBasic{}
	buffer := make([]DailyBasic, 4096)
	for {
		count, err := reader.Read(buffer)
		for index := 0; index < count; index++ {
			item := buffer[index]
			if item.TSCode == tsCode && item.TradeDate > latest.TradeDate {
				latest = item
			}
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return DailyBasic{}, err
		}
	}
	return latest, nil
}

func readIndustryDailyBasic(filePath string, tradeDate string, industry string, stockMap map[string]StockBasic) ([]DailyBasic, error) {
	if filePath == "" || tradeDate == "" || industry == "" {
		return []DailyBasic{}, nil
	}
	file, err := os.Open(filePath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	reader := parquet.NewGenericReader[DailyBasic](file)
	defer reader.Close()

	out := make([]DailyBasic, 0)
	buffer := make([]DailyBasic, 4096)
	for {
		count, err := reader.Read(buffer)
		for index := 0; index < count; index++ {
			item := buffer[index]
			if item.TradeDate != tradeDate || item.TotalMV <= 0 {
				continue
			}
			if stockMap[item.TSCode].Industry == industry {
				out = append(out, item)
			}
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
	}
	return out, nil
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
		peerMedian := median(metricValues(peers, func(peer DailyBasic) float64 { return peer.PeTTM }))
		if peerMedian > 0 {
			estimates = append(estimates, item.TotalMV*peerMedian/item.PeTTM)
		}
	}
	if item.Pb > 0 {
		peerMedian := median(metricValues(peers, func(peer DailyBasic) float64 { return peer.Pb }))
		if peerMedian > 0 {
			estimates = append(estimates, item.TotalMV*peerMedian/item.Pb)
		}
	}
	if item.PsTTM > 0 {
		peerMedian := median(metricValues(peers, func(peer DailyBasic) float64 { return peer.PsTTM }))
		if peerMedian > 0 {
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
	if score < 0 {
		return 0
	}
	if score > 100 {
		return 100
	}
	return score
}

func valuationVerdict(valuationPct float64, mispricingPct float64, roe float64, debtToAssets float64, item DailyBasic) (string, []string) {
	tags := make([]string, 0)
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
		"负债率 " + formatPctText(debtToAssets/100),
		"结论 " + verdict,
	}, " · ")
}

func formatPctText(value float64) string {
	if !isFinite(value) {
		return "—"
	}
	return strings.TrimRight(strings.TrimRight(fmtFloat(value*100, 1), "0"), ".") + "%"
}

func signedPctText(value float64) string {
	if !isFinite(value) {
		return "—"
	}
	prefix := ""
	if value > 0 {
		prefix = "+"
	}
	return prefix + formatPctText(value)
}

func fmtFloat(value float64, precision int) string {
	pow := math.Pow10(precision)
	rounded := math.Round(value*pow) / pow
	return strconvFormatFloat(rounded, precision)
}

func strconvFormatFloat(value float64, precision int) string {
	return strconv.FormatFloat(value, 'f', precision, 64)
}

func isFinite(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0)
}
