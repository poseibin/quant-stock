package market

import (
	"sort"
	"strings"
)

type FinancialIndicator struct {
	TSCode       string  `json:"ts_code"`
	AnnDate      string  `json:"ann_date"`
	EndDate      string  `json:"end_date"`
	EPS          float64 `json:"eps"`
	ROE          float64 `json:"roe"`
	GrossMargin  float64 `json:"gross_margin"`
	NetMargin    float64 `json:"net_margin"`
	DebtToAssets float64 `json:"debt_to_assets"`
}

type FinancialQuery struct {
	TSCode string `json:"ts_code"`
	Limit  int    `json:"limit"`
}

func (service *Service) ListFinancialIndicators(dataPath string, query FinancialQuery) ([]FinancialIndicator, error) {
	if service == nil || service.repo == nil || service.repo.db == nil {
		return []FinancialIndicator{}, nil
	}
	tsCode := strings.TrimSpace(query.TSCode)
	if tsCode == "" {
		return []FinancialIndicator{}, nil
	}
	limit := query.Limit
	if limit <= 0 || limit > 100 {
		limit = 40
	}
	rows, err := service.repo.db.Conn().Query(`SELECT ts_code, ann_date, end_date, eps, roe, grossprofit_margin, netprofit_margin, debt_to_assets
		FROM data_fina_indicator WHERE ts_code = ? ORDER BY end_date DESC LIMIT ?`, tsCode, limit)
	if isMissingDataTable(err) {
		return []FinancialIndicator{}, nil
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []FinancialIndicator{}
	for rows.Next() {
		var item FinancialIndicator
		if err := rows.Scan(&item.TSCode, &item.AnnDate, &item.EndDate, &item.EPS, &item.ROE, &item.GrossMargin, &item.NetMargin, &item.DebtToAssets); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	sort.Slice(out, func(i, j int) bool { return out[i].EndDate < out[j].EndDate })
	return out, nil
}
