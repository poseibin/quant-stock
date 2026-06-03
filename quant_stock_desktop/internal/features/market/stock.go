package market

import (
	"io"
	"os"
	"path/filepath"
	"strings"

	parquet "github.com/parquet-go/parquet-go"
)

type StockBasic struct {
	TSCode     string `parquet:"ts_code" json:"ts_code"`
	Symbol     string `parquet:"symbol" json:"symbol"`
	Name       string `parquet:"name" json:"name"`
	Area       string `parquet:"area" json:"area"`
	Industry   string `parquet:"industry" json:"industry"`
	Market     string `parquet:"market" json:"market"`
	ListDate   string `parquet:"list_date" json:"list_date"`
	ListStatus string `parquet:"list_status" json:"list_status"`
}

type StockBasicQuery struct {
	Keyword string `json:"keyword"`
	Limit   int    `json:"limit"`
}

func (service *Service) ListStockBasic(dataPath string, query StockBasicQuery) ([]StockBasic, error) {
	file, err := os.Open(filepath.Join(dataPath, "raw", "stock_basic", "data.parquet"))
	if err != nil {
		return nil, err
	}
	defer file.Close()

	reader := parquet.NewGenericReader[StockBasic](file)
	defer reader.Close()

	limit := query.Limit
	if limit <= 0 || limit > 5000 {
		limit = 5000
	}
	keyword := strings.ToLower(strings.TrimSpace(query.Keyword))
	stocks := make([]StockBasic, 0, limit)
	buffer := make([]StockBasic, 256)

	for len(stocks) < limit {
		count, err := reader.Read(buffer)
		for index := 0; index < count && len(stocks) < limit; index++ {
			stock := buffer[index]
			if keyword == "" || stock.matches(keyword) {
				stocks = append(stocks, stock)
			}
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
	}

	return stocks, nil
}

func (stock StockBasic) matches(keyword string) bool {
	return strings.Contains(strings.ToLower(stock.TSCode), keyword) ||
		strings.Contains(strings.ToLower(stock.Symbol), keyword) ||
		strings.Contains(strings.ToLower(stock.Name), keyword) ||
		strings.Contains(strings.ToLower(stock.Industry), keyword)
}
