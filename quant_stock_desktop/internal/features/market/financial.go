package market

import (
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	parquet "github.com/parquet-go/parquet-go"
)

type FinancialIndicator struct {
	TSCode       string  `parquet:"ts_code" json:"ts_code"`
	AnnDate      string  `parquet:"ann_date" json:"ann_date"`
	EndDate      string  `parquet:"end_date" json:"end_date"`
	EPS          float64 `parquet:"eps" json:"eps"`
	ROE          float64 `parquet:"roe" json:"roe"`
	GrossMargin  float64 `parquet:"grossprofit_margin" json:"gross_margin"`
	NetMargin    float64 `parquet:"netprofit_margin" json:"net_margin"`
	DebtToAssets float64 `parquet:"debt_to_assets" json:"debt_to_assets"`
}

type FinancialQuery struct {
	TSCode string `json:"ts_code"`
	Limit  int    `json:"limit"`
}

func (service *Service) ListFinancialIndicators(dataPath string, query FinancialQuery) ([]FinancialIndicator, error) {
	tsCode := strings.TrimSpace(query.TSCode)
	if tsCode == "" {
		return []FinancialIndicator{}, nil
	}
	limit := query.Limit
	if limit <= 0 || limit > 100 {
		limit = 40
	}
	files, _ := filepath.Glob(filepath.Join(dataPath, "raw", "fina_indicator", "*.parquet"))
	sort.Strings(files)

	items := make([]FinancialIndicator, 0)
	for _, filePath := range files {
		part, err := readFinancialFile(filePath, tsCode, limit-len(items))
		if err != nil {
			return nil, err
		}
		items = append(items, part...)
		if len(items) >= limit {
			break
		}
	}
	sort.Slice(items, func(i, j int) bool {
		return items[i].EndDate < items[j].EndDate
	})
	return items, nil
}

func readFinancialFile(filePath string, tsCode string, limit int) ([]FinancialIndicator, error) {
	if limit <= 0 {
		return []FinancialIndicator{}, nil
	}
	file, err := os.Open(filePath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	reader := parquet.NewGenericReader[FinancialIndicator](file)
	defer reader.Close()

	items := make([]FinancialIndicator, 0)
	buffer := make([]FinancialIndicator, 512)
	for len(items) < limit {
		count, err := reader.Read(buffer)
		for index := 0; index < count && len(items) < limit; index++ {
			item := buffer[index]
			if item.TSCode == tsCode {
				items = append(items, item)
			}
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
	}
	return items, nil
}
