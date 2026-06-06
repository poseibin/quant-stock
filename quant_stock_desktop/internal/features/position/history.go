package position

import (
	"sort"
	"strings"
	"time"
)

func (service *Service) GetHistory(dataPath string) ([]HistoryPoint, error) {
	points := []HistoryPoint{}
	summary, summaryErr := service.GetSummary(dataPath)
	if summaryErr == nil && summary.TotalAssets > 0 {
		points = appendOrReplaceCurrentPoint(points, summary)
	}
	sort.Slice(points, func(i, j int) bool { return points[i].Date < points[j].Date })
	fillDailyReturns(points)
	return points, nil
}

func appendOrReplaceCurrentPoint(points []HistoryPoint, summary Summary) []HistoryPoint {
	date := normalizeSummaryDate(summary.UpdatedAt)
	if date == "" {
		date = time.Now().Format("20060102")
	}
	point := HistoryPoint{
		Date:          date,
		Cash:          summary.Cash,
		MarketValue:   summary.MarketValue,
		Equity:        summary.TotalAssets,
		NHoldings:     summary.NHoldings,
		UnrealizedPnL: summary.UnrealizedPnL,
		RealizedPnL:   summary.RealizedPnL,
		CumReturn:     summary.CumReturn,
	}
	for i := range points {
		if points[i].Date == point.Date {
			points[i] = point
			return points
		}
	}
	return append(points, point)
}

func fillDailyReturns(points []HistoryPoint) {
	var prev float64
	for i := range points {
		if prev > 0 && points[i].Equity > 0 {
			points[i].DailyReturn = points[i].Equity/prev - 1
		}
		prev = points[i].Equity
	}
}

func normalizeSnapshotDate(value string) string {
	digits := onlyDigits(value)
	if len(digits) >= 8 {
		return digits[:8]
	}
	return ""
}

func normalizeSummaryDate(value string) string {
	if t, ok := parseTimeValue(value); ok {
		return t.Format("20060102")
	}
	return normalizeSnapshotDate(value)
}

func parseTimeValue(value string) (time.Time, bool) {
	value = strings.TrimSpace(value)
	if value == "" {
		return time.Time{}, false
	}
	for _, layout := range []string{time.RFC3339, "2006-01-02T15:04:05", "2006-01-02 15:04:05", "20060102"} {
		if t, err := time.Parse(layout, value); err == nil {
			return t, true
		}
		if t, err := time.ParseInLocation(layout, value, time.Local); err == nil {
			return t, true
		}
	}
	return time.Time{}, false
}

func onlyDigits(value string) string {
	var b strings.Builder
	for _, r := range value {
		if r >= '0' && r <= '9' {
			b.WriteRune(r)
		}
	}
	return b.String()
}
