package datafetch

import "time"

const DataStartDate = "20100101"

type PartitionStrategy string

const (
	PartitionSingle PartitionStrategy = "single"
	PartitionYear   PartitionStrategy = "year"
)

type DatasetSpec struct {
	Name      string
	Partition PartitionStrategy
	PK        []string
	DateField string
}

var Datasets = map[string]DatasetSpec{
	"stock_basic":     {Name: "stock_basic", Partition: PartitionSingle, PK: []string{"ts_code"}},
	"trade_cal":       {Name: "trade_cal", Partition: PartitionSingle, PK: []string{"cal_date"}},
	"daily":           {Name: "daily", Partition: PartitionYear, PK: []string{"ts_code", "trade_date"}, DateField: "trade_date"},
	"daily_basic":     {Name: "daily_basic", Partition: PartitionYear, PK: []string{"ts_code", "trade_date"}, DateField: "trade_date"},
	"adj_factor":      {Name: "adj_factor", Partition: PartitionYear, PK: []string{"ts_code", "trade_date"}, DateField: "trade_date"},
	"income":          {Name: "income", Partition: PartitionYear, PK: []string{"ts_code", "end_date", "report_type"}, DateField: "end_date"},
	"balancesheet":    {Name: "balancesheet", Partition: PartitionYear, PK: []string{"ts_code", "end_date", "report_type"}, DateField: "end_date"},
	"cashflow":        {Name: "cashflow", Partition: PartitionYear, PK: []string{"ts_code", "end_date", "report_type"}, DateField: "end_date"},
	"fina_indicator":  {Name: "fina_indicator", Partition: PartitionYear, PK: []string{"ts_code", "end_date"}, DateField: "end_date"},
	"forecast":        {Name: "forecast", Partition: PartitionYear, PK: []string{"ts_code", "ann_date", "end_date"}, DateField: "ann_date"},
	"stk_holdertrade": {Name: "stk_holdertrade", Partition: PartitionYear, PK: []string{"ts_code", "ann_date", "holder_name", "in_de"}, DateField: "ann_date"},
	"top_list":        {Name: "top_list", Partition: PartitionYear, PK: []string{"ts_code", "trade_date", "reason"}, DateField: "trade_date"},
	"top_inst":        {Name: "top_inst", Partition: PartitionYear, PK: []string{"ts_code", "trade_date", "exalter", "reason"}, DateField: "trade_date"},
}

const (
	tushareDefaultEndpoint = "https://api.tushare.pro"
	tushareCallsPerMinute  = 45
	tushareWindow          = time.Minute
	tushareDefaultInterval = 1200 * time.Millisecond
)

var tushareApiInterval = map[string]time.Duration{
	"stock_basic":        1000 * time.Millisecond,
	"trade_cal":          1000 * time.Millisecond,
	"daily":              1200 * time.Millisecond,
	"daily_basic":        1500 * time.Millisecond,
	"adj_factor":         1200 * time.Millisecond,
	"income":             2000 * time.Millisecond,
	"income_vip":         2000 * time.Millisecond,
	"balancesheet":       2000 * time.Millisecond,
	"balancesheet_vip":   2000 * time.Millisecond,
	"cashflow":           2000 * time.Millisecond,
	"cashflow_vip":       2000 * time.Millisecond,
	"fina_indicator":     2000 * time.Millisecond,
	"fina_indicator_vip": 2000 * time.Millisecond,
	"forecast":           2000 * time.Millisecond,
	"forecast_vip":       2000 * time.Millisecond,
	"stk_holdertrade":    2500 * time.Millisecond,
	"top_list":           2000 * time.Millisecond,
	"top_inst":           2000 * time.Millisecond,
}
