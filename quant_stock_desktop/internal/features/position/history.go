package position

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/parquet-go/parquet-go"
)

func (service *Service) GetHistory(dataPath string) ([]HistoryPoint, error) {
	points, err := readSnapshotParquet(filepath.Join(dataPath, "positions", "snapshots.parquet"))
	if err != nil {
		return nil, err
	}
	summary, summaryErr := service.GetSummary(dataPath)
	if summaryErr == nil && summary.TotalAssets > 0 {
		points = appendOrReplaceCurrentPoint(points, summary)
	}
	sort.Slice(points, func(i, j int) bool { return points[i].Date < points[j].Date })
	fillDailyReturns(points)
	if points == nil {
		points = []HistoryPoint{}
	}
	return points, nil
}

func readSnapshotParquet(path string) ([]HistoryPoint, error) {
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return []HistoryPoint{}, nil
		}
		return nil, err
	}
	defer f.Close()
	stat, err := f.Stat()
	if err != nil {
		return nil, err
	}
	pf, err := parquet.OpenFile(f, stat.Size())
	if err != nil {
		return nil, err
	}
	schema := pf.Schema()
	cols := schema.Columns()
	names := make([]string, 0, len(cols))
	for _, col := range cols {
		if len(col) > 0 {
			names = append(names, col[len(col)-1])
		}
	}
	reader := parquet.NewReader(pf, schema)
	defer reader.Close()

	out := make([]HistoryPoint, 0, pf.NumRows())
	buf := make([]parquet.Row, 512)
	for {
		n, readErr := reader.ReadRows(buf)
		for i := 0; i < n; i++ {
			rec := make(map[string]any, len(names))
			for j, name := range names {
				if j >= len(buf[i]) {
					break
				}
				value := buf[i][j]
				if value.IsNull() {
					continue
				}
				rec[name] = parquetValueToAny(value)
			}
			point := HistoryPoint{
				Date:          normalizeSnapshotDate(stringValue(firstNonNil(rec["date"], rec["trade_date"]))),
				Cash:          floatValue(rec["cash"]),
				MarketValue:   floatValue(rec["market_value"]),
				Equity:        floatValue(firstNonNil(rec["equity"], rec["total_assets"])),
				NHoldings:     int(floatValue(rec["n_holdings"])),
				UnrealizedPnL: floatValue(rec["unrealized_pnl"]),
				RealizedPnL:   floatValue(rec["realized_pnl"]),
				CumReturn:     floatValue(rec["cum_return"]),
			}
			if point.Date != "" && point.Equity > 0 {
				out = append(out, point)
			}
		}
		if readErr != nil {
			break
		}
	}
	return out, nil
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

func firstNonNil(values ...any) any {
	for _, value := range values {
		if value != nil {
			return value
		}
	}
	return nil
}

func stringValue(value any) string {
	if value == nil {
		return ""
	}
	switch v := value.(type) {
	case string:
		return v
	case []byte:
		return string(v)
	default:
		return fmt.Sprintf("%v", v)
	}
}

func floatValue(value any) float64 {
	switch v := value.(type) {
	case float64:
		return v
	case float32:
		return float64(v)
	case int:
		return float64(v)
	case int32:
		return float64(v)
	case int64:
		return float64(v)
	case string:
		var out float64
		_, _ = fmt.Sscanf(v, "%f", &out)
		return out
	default:
		return 0
	}
}

func parquetValueToAny(v parquet.Value) any {
	switch v.Kind() {
	case parquet.Boolean:
		return v.Boolean()
	case parquet.Int32:
		return int64(v.Int32())
	case parquet.Int64:
		return v.Int64()
	case parquet.Float:
		return float64(v.Float())
	case parquet.Double:
		return v.Double()
	case parquet.ByteArray, parquet.FixedLenByteArray:
		return string(v.ByteArray())
	default:
		return v.String()
	}
}
