package datafetch

// Tushare 字段类型映射。每个 dataset 对应的字段名 → 类型（"string" / "double" / "int64"）。
// 类型必须与 Python pyarrow 旧版本写出兼容，否则 DuckDB 读侧会报类型错。
// 参考实测 schema（见 MIGRATION_NOTES.md）。

type ColType string

const (
	ColString ColType = "string"
	ColDouble ColType = "double"
	ColInt64  ColType = "int64"
)

var DatasetSchemas = map[string]map[string]ColType{
	"stock_basic": {
		"ts_code": ColString, "symbol": ColString, "name": ColString, "area": ColString,
		"industry": ColString, "fullname": ColString, "market": ColString, "exchange": ColString,
		"list_status": ColString, "list_date": ColString, "delist_date": ColString, "is_hs": ColString,
	},
	"trade_cal": {
		"exchange": ColString, "cal_date": ColString, "is_open": ColInt64, "pretrade_date": ColString,
	},
	"daily": {
		"ts_code": ColString, "trade_date": ColString,
		"open": ColDouble, "high": ColDouble, "low": ColDouble, "close": ColDouble,
		"pre_close": ColDouble, "change": ColDouble, "pct_chg": ColDouble,
		"vol": ColDouble, "amount": ColDouble,
	},
	"daily_basic": {
		"ts_code": ColString, "trade_date": ColString, "close": ColDouble,
		"turnover_rate": ColDouble, "turnover_rate_f": ColDouble, "volume_ratio": ColDouble,
		"pe": ColDouble, "pe_ttm": ColDouble, "pb": ColDouble, "ps": ColDouble, "ps_ttm": ColDouble,
		"dv_ratio": ColDouble, "dv_ttm": ColDouble,
		"total_share": ColDouble, "float_share": ColDouble, "free_share": ColDouble,
		"total_mv": ColDouble, "circ_mv": ColDouble,
	},
	"adj_factor": {
		"ts_code": ColString, "trade_date": ColString, "adj_factor": ColDouble,
	},
	"top_list": {
		"trade_date": ColString, "ts_code": ColString, "name": ColString,
		"close": ColDouble, "pct_change": ColDouble, "turnover_rate": ColDouble, "amount": ColDouble,
		"l_sell": ColDouble, "l_buy": ColDouble, "l_amount": ColDouble,
		"net_amount": ColDouble, "net_rate": ColDouble, "amount_rate": ColDouble,
		"float_values": ColDouble, "reason": ColString,
	},
	"top_inst": {
		"trade_date": ColString, "ts_code": ColString, "exalter": ColString,
		"buy": ColDouble, "buy_rate": ColDouble, "sell": ColDouble, "sell_rate": ColDouble,
		"net_buy": ColDouble, "side": ColString, "reason": ColString,
	},
	"forecast": {
		"ts_code": ColString, "ann_date": ColString, "end_date": ColString, "type": ColString,
		"p_change_min": ColDouble, "p_change_max": ColDouble,
		"net_profit_min": ColDouble, "net_profit_max": ColDouble, "last_parent_net": ColDouble,
		"first_ann_date": ColString, "summary": ColString, "change_reason": ColString,
		"update_flag": ColString,
	},
	"stk_holdertrade": {
		"ts_code": ColString, "ann_date": ColString,
		"holder_name": ColString, "holder_type": ColString, "in_de": ColString,
		"change_vol": ColDouble, "change_ratio": ColDouble,
		"after_share": ColDouble, "after_ratio": ColDouble,
		"avg_price": ColDouble, "total_share": ColDouble,
	},
}

// 财务大表字段太多（80~140 列），动态从 Tushare 返回的 fields 推断：
// - 命中 financeStringCols 的列为 string，其它为 double
// - 这套规则已对齐 Python pyarrow 旧文件实测 schema
var financeStringCols = map[string]bool{
	"ts_code": true, "ann_date": true, "f_ann_date": true, "end_date": true,
	"report_type": true, "comp_type": true, "end_type": true, "update_flag": true,
}

func InferFinanceSchema(fields []string) map[string]ColType {
	out := make(map[string]ColType, len(fields))
	for _, f := range fields {
		if financeStringCols[f] {
			out[f] = ColString
		} else {
			out[f] = ColDouble
		}
	}
	return out
}

// 给定 dataset 名 + Tushare 返回的 fields，决定列类型。
func ResolveSchema(dataset string, fields []string) map[string]ColType {
	if s, ok := DatasetSchemas[dataset]; ok {
		// 已知 schema：以 fields 为基准，未知列回退到 string，避免遗漏
		out := make(map[string]ColType, len(fields))
		for _, f := range fields {
			if t, ok := s[f]; ok {
				out[f] = t
			} else {
				out[f] = ColString
			}
		}
		return out
	}
	// 未知 dataset → 按财务规则推断
	return InferFinanceSchema(fields)
}
