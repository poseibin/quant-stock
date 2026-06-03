package market

import (
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	parquet "github.com/parquet-go/parquet-go"
)

type DailyBar struct {
	TSCode    string  `parquet:"ts_code" json:"ts_code"`
	TradeDate string  `parquet:"trade_date" json:"trade_date"`
	Open      float64 `parquet:"open" json:"open"`
	High      float64 `parquet:"high" json:"high"`
	Low       float64 `parquet:"low" json:"low"`
	Close     float64 `parquet:"close" json:"close"`
	PreClose  float64 `parquet:"pre_close" json:"pre_close"`
	Change    float64 `parquet:"change" json:"change"`
	PctChg    float64 `parquet:"pct_chg" json:"pct_chg"`
	Vol       float64 `parquet:"vol" json:"vol"`
	Amount    float64 `parquet:"amount" json:"amount"`
}

type DailyQuery struct {
	TSCode    string `json:"ts_code"`
	StartDate string `json:"start_date"`
	EndDate   string `json:"end_date"`
	Limit     int    `json:"limit"`
}

func (service *Service) ListDailyBars(dataPath string, query DailyQuery) ([]DailyBar, error) {
	tsCode := strings.TrimSpace(query.TSCode)
	if tsCode == "" {
		return []DailyBar{}, nil
	}

	files := dailyFiles(dataPath, query.StartDate, query.EndDate)
	limit := query.Limit
	if limit <= 0 || limit > 5000 {
		limit = 5000
	}

	bars := make([]DailyBar, 0)
	for _, filePath := range files {
		items, err := readDailyFile(filePath, tsCode, query.StartDate, query.EndDate, limit-len(bars))
		if err != nil {
			return nil, err
		}
		bars = append(bars, items...)
		if len(bars) >= limit {
			break
		}
	}

	sort.Slice(bars, func(i, j int) bool {
		return bars[i].TradeDate < bars[j].TradeDate
	})
	return bars, nil
}

func dailyFiles(dataPath string, startDate string, endDate string) []string {
	dailyPath := filepath.Join(dataPath, "raw", "daily")
	startYear := yearFromDate(startDate)
	endYear := yearFromDate(endDate)
	if startYear > 0 && endYear > 0 {
		files := make([]string, 0, endYear-startYear+1)
		for year := startYear; year <= endYear; year++ {
			filePath := filepath.Join(dailyPath, "year="+strconv.Itoa(year)+".parquet")
			if _, err := os.Stat(filePath); err == nil {
				files = append(files, filePath)
			}
		}
		return files
	}
	files, _ := filepath.Glob(filepath.Join(dailyPath, "*.parquet"))
	sort.Strings(files)
	return files
}

func readDailyFile(filePath string, tsCode string, startDate string, endDate string, limit int) ([]DailyBar, error) {
	if limit <= 0 {
		return []DailyBar{}, nil
	}
	file, err := os.Open(filePath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	reader := parquet.NewGenericReader[DailyBar](file)
	defer reader.Close()

	bars := make([]DailyBar, 0)
	buffer := make([]DailyBar, 2048)
	for len(bars) < limit {
		count, err := reader.Read(buffer)
		for index := 0; index < count && len(bars) < limit; index++ {
			bar := buffer[index]
			if bar.TSCode == tsCode && inDateRange(bar.TradeDate, startDate, endDate) {
				bars = append(bars, bar)
			}
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
	}
	return bars, nil
}

func inDateRange(value string, startDate string, endDate string) bool {
	if startDate != "" && value < startDate {
		return false
	}
	if endDate != "" && value > endDate {
		return false
	}
	return true
}

func yearFromDate(value string) int {
	if len(value) < 4 {
		return 0
	}
	year, err := strconv.Atoi(value[:4])
	if err != nil {
		return 0
	}
	return year
}
