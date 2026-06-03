package datafetch

import (
	"context"
	"errors"
	"fmt"
	"log"
	"sort"
	"strconv"
	"strings"
)

// Phase 表示一次 Run 要执行的阶段集合。
type Phase string

const (
	PhaseAll     Phase = "all"
	PhaseBasic   Phase = "basic"
	PhasePrice   Phase = "price"
	PhaseFinance Phase = "finance"
	PhaseEvent   Phase = "event"
)

// ProgressFn 让外层接管进度上报。stage = dataset 名，done/total 当前 stage 内进度，extra 可选附加信息。
type ProgressFn func(stage string, done, total int, extra string)

func noopProgress(string, int, int, string) {}

// JobContext 单次 Run 上下文。
type JobContext struct {
	Ctx       context.Context
	Client    *TushareClient
	DataPath  string
	StartDate string // 为空表示用 latest_date 增量
	Progress  ProgressFn
}

// Tushare 单次返回硬限制常见为 6000 行。这里主动压低每页行数，避免
// 财务大表一次写入过多宽字段时触发 parquet-go 内部大块分配。
const tushareMaxRowsPerCall = 2000

// callPaged 对支持 has_more（offset 翻页）的 API 自动分页直到收齐。
func callPaged(ctx context.Context, c *TushareClient, api string, params map[string]any, fields string) (*TushareResponse, error) {
	merged := &TushareResponse{}
	offset := 0
	for {
		p := map[string]any{}
		for k, v := range params {
			p[k] = v
		}
		if offset > 0 {
			p["offset"] = offset
		}
		p["limit"] = tushareMaxRowsPerCall

		resp, err := c.Call(ctx, api, p, fields)
		if err != nil {
			return nil, err
		}
		if len(merged.Fields) == 0 {
			merged.Fields = resp.Fields
		}
		merged.Items = append(merged.Items, resp.Items...)
		if len(resp.Items) < tushareMaxRowsPerCall {
			break
		}
		offset += len(resp.Items)
	}
	return merged, nil
}

func callPagedWithFallback(ctx context.Context, c *TushareClient, apis []string, params map[string]any, fields string) (*TushareResponse, string, error) {
	var lastErr error
	for _, api := range apis {
		resp, err := callPaged(ctx, c, api, params, fields)
		if err == nil {
			return resp, api, nil
		}
		lastErr = err
		if !IsHardLimit(err) {
			return nil, api, err
		}
		log.Printf("[datafetch] %s 受限，尝试降级接口: %v", api, err)
	}
	return nil, "", lastErr
}

// ----------------------------------------------------------------------------
// 基础类
// ----------------------------------------------------------------------------

// UpdateStockBasic 拉取上市/退市/暂停三态后整体覆盖。
func UpdateStockBasic(jc *JobContext) (int, error) {
	if jc.Progress == nil {
		jc.Progress = noopProgress
	}
	jc.Progress("stock_basic", 0, 3, "fetching")
	allFields := "ts_code,symbol,name,area,industry,fullname,market,exchange,list_status,list_date,delist_date,is_hs"

	var fields []string
	var items [][]any
	statuses := []string{"L", "D", "P"}
	for i, s := range statuses {
		resp, err := jc.Client.Call(jc.Ctx, "stock_basic", map[string]any{
			"exchange":    "",
			"list_status": s,
		}, allFields)
		if err != nil {
			return 0, fmt.Errorf("stock_basic[%s]: %w", s, err)
		}
		if len(fields) == 0 {
			fields = resp.Fields
		}
		items = append(items, resp.Items...)
		jc.Progress("stock_basic", i+1, 3, fmt.Sprintf("status=%s", s))
	}
	if len(fields) == 0 || len(items) == 0 {
		return 0, nil
	}
	path := PartitionPath(jc.DataPath, "stock_basic", PartitionSingle, 0)
	n, err := Upsert(path, "stock_basic", fields, items, []string{"ts_code"}, true)
	if err != nil {
		return 0, err
	}
	log.Printf("[datafetch] stock_basic 更新 %d 条", n)
	return n, nil
}

// UpdateTradeCal 拉 SSE 完整交易日历后整体覆盖。
func UpdateTradeCal(jc *JobContext) (int, error) {
	if jc.Progress == nil {
		jc.Progress = noopProgress
	}
	resp, err := jc.Client.Call(jc.Ctx, "trade_cal", map[string]any{
		"exchange":   "SSE",
		"start_date": DataStartDate,
		"end_date":   today(),
	}, "exchange,cal_date,is_open,pretrade_date")
	if err != nil {
		return 0, err
	}
	if len(resp.Items) == 0 {
		return 0, nil
	}
	path := PartitionPath(jc.DataPath, "trade_cal", PartitionSingle, 0)
	n, err := Upsert(path, "trade_cal", resp.Fields, resp.Items, []string{"cal_date"}, true)
	if err != nil {
		return 0, err
	}
	log.Printf("[datafetch] trade_cal 更新 %d 条", n)
	return n, nil
}

// loadTradeDates 读 trade_cal 的开市日列表，按字典序升序。
func loadTradeDates(dataPath, start, end string) ([]string, error) {
	path := PartitionPath(dataPath, "trade_cal", PartitionSingle, 0)
	recs, _, err := readParquetAsMaps(path)
	if err != nil {
		return nil, err
	}
	if recs == nil {
		return nil, errors.New("trade_cal 数据未初始化，请先运行基础阶段")
	}
	out := make([]string, 0, len(recs))
	for _, r := range recs {
		isOpen, _ := r["is_open"]
		open := false
		switch v := isOpen.(type) {
		case int64:
			open = v == 1
		case int32:
			open = v == 1
		case int:
			open = v == 1
		case float64:
			open = v == 1
		case string:
			open = v == "1"
		}
		if !open {
			continue
		}
		d, _ := r["cal_date"].(string)
		if d == "" {
			continue
		}
		if d >= start && d <= end {
			out = append(out, d)
		}
	}
	sort.Strings(out)
	return out, nil
}

// ----------------------------------------------------------------------------
// 行情类（按交易日逐日拉）
// ----------------------------------------------------------------------------

func fetchByTradeDate(jc *JobContext, api, dataset string, pk []string, backfillHistory bool) (int, error) {
	if jc.Progress == nil {
		jc.Progress = noopProgress
	}
	start := strings.TrimSpace(jc.StartDate)
	if start == "" {
		if backfillHistory {
			start = DataStartDate
		} else {
			var err error
			start, err = incrementalStart(jc, dataset, "trade_date")
			if err != nil {
				return 0, err
			}
		}
	}
	end := today()
	if start > end {
		log.Printf("[datafetch] %s 已最新", dataset)
		return 0, nil
	}
	allDates, err := loadTradeDates(jc.DataPath, start, end)
	if err != nil {
		return 0, err
	}
	existing, err := ListExistingPeriods(jc.DataPath, dataset, "trade_date")
	if err != nil {
		return 0, err
	}
	dates := make([]string, 0, len(allDates))
	for _, d := range allDates {
		if !existing[d] {
			dates = append(dates, d)
		}
	}
	sort.Sort(sort.Reverse(sort.StringSlice(dates)))
	if len(dates) == 0 {
		log.Printf("[datafetch] %s 无缺失交易日", dataset)
		return 0, nil
	}
	jc.Progress(dataset, 0, len(dates), fmt.Sprintf("missing %d/%d", len(dates), len(allDates)))

	// 累计每年的待写入数据，最后按年合并 upsert，减少 IO。
	type yearBatch struct {
		fields []string
		items  [][]any
	}
	batches := map[int]*yearBatch{}

	total := 0
	var hardErr error
	for i, d := range dates {
		jc.Progress(dataset, i+1, len(dates), d)
		select {
		case <-jc.Ctx.Done():
			return total, jc.Ctx.Err()
		default:
		}
		resp, err := jc.Client.Call(jc.Ctx, api, map[string]any{"trade_date": d}, "")
		if err != nil {
			if IsHardLimit(err) {
				hardErr = fmt.Errorf("%s %s API 受限: %w", dataset, d, err)
				log.Printf("[datafetch] %v", hardErr)
				break
			}
			log.Printf("[datafetch] %s %s 失败: %v", dataset, d, err)
			continue
		}
		if len(resp.Items) == 0 {
			continue
		}
		y, _ := strconv.Atoi(d[:4])
		b, ok := batches[y]
		if !ok {
			b = &yearBatch{fields: resp.Fields}
			batches[y] = b
		} else if len(b.fields) == 0 {
			b.fields = resp.Fields
		}
		b.items = append(b.items, resp.Items...)
	}

	for y, b := range batches {
		path := PartitionPath(jc.DataPath, dataset, PartitionYear, y)
		n, err := Upsert(path, dataset, b.fields, b.items, pk, false)
		if err != nil {
			return total, fmt.Errorf("%s year=%d upsert: %w", dataset, y, err)
		}
		total += n
	}
	log.Printf("[datafetch] %s 累计写入 %d 行", dataset, total)
	return total, hardErr
}

func UpdateDaily(jc *JobContext) (int, error) {
	return fetchByTradeDate(jc, "daily", "daily", []string{"ts_code", "trade_date"}, true)
}
func UpdateDailyBasic(jc *JobContext) (int, error) {
	return fetchByTradeDate(jc, "daily_basic", "daily_basic", []string{"ts_code", "trade_date"}, true)
}
func UpdateAdjFactor(jc *JobContext) (int, error) {
	return fetchByTradeDate(jc, "adj_factor", "adj_factor", []string{"ts_code", "trade_date"}, true)
}

// ----------------------------------------------------------------------------
// 财务类（按 period 全市场拉）
// ----------------------------------------------------------------------------

func periodsBetween(start, end string) []string {
	if len(start) < 4 || len(end) < 4 {
		return nil
	}
	sy, _ := strconv.Atoi(start[:4])
	ey, _ := strconv.Atoi(end[:4])
	var out []string
	for y := sy; y <= ey; y++ {
		for _, q := range []string{"0331", "0630", "0930", "1231"} {
			p := fmt.Sprintf("%d%s", y, q)
			if p >= start && p <= end {
				out = append(out, p)
			}
		}
	}
	return out
}

func incrementalStart(jc *JobContext, dataset, dateField string) (string, error) {
	if strings.TrimSpace(jc.StartDate) != "" {
		return strings.TrimSpace(jc.StartDate), nil
	}
	last, err := LatestDate(jc.DataPath, dataset, dateField)
	if err != nil {
		return "", err
	}
	if last == "" {
		return DataStartDate, nil
	}
	next, err := nextDay(last)
	if err != nil {
		return last, nil
	}
	return next, nil
}

func firstN(values []string, n int) []string {
	if len(values) <= n {
		return values
	}
	return values[:n]
}

func fetchFinanceByPeriod(jc *JobContext, apis []string, dataset string, pk []string) (int, error) {
	start := strings.TrimSpace(jc.StartDate)
	if start == "" {
		start = DataStartDate
	}
	allPeriods := periodsBetween(start, today())
	done, err := ListExistingPeriods(jc.DataPath, dataset, "end_date")
	if err != nil {
		return 0, err
	}
	pending := allPeriods[:0]
	for _, p := range allPeriods {
		if !done[p] {
			pending = append(pending, p)
		}
	}
	// 最新优先
	sort.Sort(sort.Reverse(sort.StringSlice(pending)))
	if len(pending) == 0 {
		log.Printf("[datafetch] %s 无待拉取 period", dataset)
		return 0, nil
	}

	total := 0
	var hardErr error
	var softErrors []string
	for i, period := range pending {
		jc.Progress(dataset, i+1, len(pending), period)
		select {
		case <-jc.Ctx.Done():
			return total, jc.Ctx.Err()
		default:
		}
		resp, usedAPI, err := callPagedWithFallback(jc.Ctx, jc.Client, apis, map[string]any{"period": period}, "")
		if err != nil {
			if IsHardLimit(err) {
				hardErr = fmt.Errorf("%s period=%s API 受限: %w", strings.Join(apis, "/"), period, err)
				log.Printf("[datafetch] %v", hardErr)
				break
			}
			log.Printf("[datafetch] %s period=%s 失败: %v", strings.Join(apis, "/"), period, err)
			softErrors = append(softErrors, fmt.Sprintf("%s: %v", period, err))
			continue
		}
		if usedAPI != "" && usedAPI != apis[0] {
			jc.Progress(dataset, i+1, len(pending), fmt.Sprintf("%s via %s", period, usedAPI))
		}
		if len(resp.Items) == 0 {
			continue
		}
		y, _ := strconv.Atoi(period[:4])
		path := PartitionPath(jc.DataPath, dataset, PartitionYear, y)
		n, err := Upsert(path, dataset, resp.Fields, resp.Items, pk, false)
		if err != nil {
			return total, fmt.Errorf("%s period=%s upsert: %w", dataset, period, err)
		}
		total += n
	}
	log.Printf("[datafetch] %s 累计写入 %d 行", dataset, total)
	if hardErr != nil {
		return total, hardErr
	}
	if total == 0 && len(softErrors) > 0 {
		return total, fmt.Errorf("%s 未写入数据，最近错误: %s", dataset, strings.Join(firstN(softErrors, 3), "; "))
	}
	return total, nil
}

func UpdateIncome(jc *JobContext) (int, error) {
	return fetchFinanceByPeriod(jc, []string{"income_vip", "income"}, "income", []string{"ts_code", "end_date", "report_type"})
}
func UpdateBalancesheet(jc *JobContext) (int, error) {
	return fetchFinanceByPeriod(jc, []string{"balancesheet_vip", "balancesheet"}, "balancesheet", []string{"ts_code", "end_date", "report_type"})
}
func UpdateCashflow(jc *JobContext) (int, error) {
	return fetchFinanceByPeriod(jc, []string{"cashflow_vip", "cashflow"}, "cashflow", []string{"ts_code", "end_date", "report_type"})
}
func UpdateFinaIndicator(jc *JobContext) (int, error) {
	return fetchFinanceByPeriod(jc, []string{"fina_indicator_vip", "fina_indicator"}, "fina_indicator", []string{"ts_code", "end_date"})
}

// 按 ann_date 区间拉的 period 类（forecast）：增量起点回溯 7 天保证一致性。
func annStart(jc *JobContext, dataset string) (string, error) {
	last, err := LatestDate(jc.DataPath, dataset, "ann_date")
	if err != nil {
		return "", err
	}
	if last == "" {
		if jc.StartDate != "" {
			return jc.StartDate, nil
		}
		return DataStartDate, nil
	}
	if d, err := shiftDateImpl(last, -7); err == nil {
		return d, nil
	}
	return last, nil
}

func UpdateForecast(jc *JobContext) (int, error) {
	if jc.Progress == nil {
		jc.Progress = noopProgress
	}
	start, err := annStart(jc, "forecast")
	if err != nil {
		return 0, err
	}
	end := today()
	if start > end {
		return 0, nil
	}
	jc.Progress("forecast", 0, 1, fmt.Sprintf("%s..%s", start, end))
	resp, usedAPI, err := callPagedWithFallback(jc.Ctx, jc.Client, []string{"forecast_vip", "forecast"}, map[string]any{
		"start_date": start, "end_date": end,
	}, "")
	if err != nil {
		if IsHardLimit(err) {
			log.Printf("[datafetch] forecast_vip/forecast 受限: %v", err)
			return 0, fmt.Errorf("forecast_vip/forecast API 受限: %w", err)
		}
		return 0, err
	}
	if usedAPI != "" && usedAPI != "forecast_vip" {
		jc.Progress("forecast", 0, 1, fmt.Sprintf("%s..%s via %s", start, end, usedAPI))
	}
	if len(resp.Items) == 0 {
		return 0, nil
	}
	jc.Progress("forecast", 1, 1, fmt.Sprintf("rows=%d", len(resp.Items)))
	return splitByYearAndUpsert(jc, "forecast", "ann_date", resp.Fields, resp.Items,
		[]string{"ts_code", "ann_date", "end_date"})
}

func UpdateHolderTrade(jc *JobContext) (int, error) {
	if jc.Progress == nil {
		jc.Progress = noopProgress
	}
	start, err := annStart(jc, "stk_holdertrade")
	if err != nil {
		return 0, err
	}
	end := today()
	if start > end {
		return 0, nil
	}
	jc.Progress("stk_holdertrade", 0, 1, fmt.Sprintf("%s..%s", start, end))
	resp, err := callPaged(jc.Ctx, jc.Client, "stk_holdertrade", map[string]any{
		"start_date": start, "end_date": end,
	}, "")
	if err != nil {
		if IsHardLimit(err) {
			log.Printf("[datafetch] stk_holdertrade 受限: %v", err)
			return 0, fmt.Errorf("stk_holdertrade API 受限: %w", err)
		}
		return 0, err
	}
	if len(resp.Items) == 0 {
		return 0, nil
	}
	jc.Progress("stk_holdertrade", 1, 1, fmt.Sprintf("rows=%d", len(resp.Items)))
	return splitByYearAndUpsert(jc, "stk_holdertrade", "ann_date", resp.Fields, resp.Items,
		[]string{"ts_code", "ann_date", "holder_name", "in_de"})
}

func UpdateTopList(jc *JobContext) (int, error) {
	return fetchByTradeDate(jc, "top_list", "top_list", []string{"ts_code", "trade_date", "reason"}, false)
}
func UpdateTopInst(jc *JobContext) (int, error) {
	return fetchByTradeDate(jc, "top_inst", "top_inst", []string{"ts_code", "trade_date", "exalter", "reason"}, false)
}

// splitByYearAndUpsert 按 dateField 列前 4 字符分组，分年 upsert。
func splitByYearAndUpsert(jc *JobContext, dataset, dateField string, fields []string, items [][]any, pk []string) (int, error) {
	dateIdx := -1
	for i, f := range fields {
		if f == dateField {
			dateIdx = i
			break
		}
	}
	if dateIdx < 0 {
		return 0, fmt.Errorf("%s: dateField %s 不在返回字段中", dataset, dateField)
	}

	groups := map[int][][]any{}
	for _, it := range items {
		var ds string
		if dateIdx < len(it) {
			switch v := it[dateIdx].(type) {
			case string:
				ds = v
			default:
				ds = fmt.Sprintf("%v", v)
			}
		}
		if len(ds) < 4 {
			continue
		}
		y, err := strconv.Atoi(ds[:4])
		if err != nil {
			continue
		}
		groups[y] = append(groups[y], it)
	}
	total := 0
	for y, gitems := range groups {
		path := PartitionPath(jc.DataPath, dataset, PartitionYear, y)
		n, err := Upsert(path, dataset, fields, gitems, pk, false)
		if err != nil {
			return total, err
		}
		total += n
	}
	return total, nil
}

// JobsForPhase 返回某阶段的 job 列表。
type JobFn func(*JobContext) (int, error)

type JobEntry struct {
	Name     string
	Category string
	Fn       JobFn
}

// 数据集分类标识，前端筛选用。
const (
	CategoryBasic   = "basic"
	CategoryPrice   = "price"
	CategoryFinance = "finance"
	CategoryEvent   = "event"
)

func JobsForPhase(phase Phase) []JobEntry {
	basic := []JobEntry{
		{"stock_basic", CategoryBasic, UpdateStockBasic},
		{"trade_cal", CategoryBasic, UpdateTradeCal},
	}
	price := []JobEntry{
		{"daily", CategoryPrice, UpdateDaily},
		{"daily_basic", CategoryPrice, UpdateDailyBasic},
		{"adj_factor", CategoryPrice, UpdateAdjFactor},
	}
	finance := []JobEntry{
		{"income", CategoryFinance, UpdateIncome},
		{"balancesheet", CategoryFinance, UpdateBalancesheet},
		{"cashflow", CategoryFinance, UpdateCashflow},
		{"fina_indicator", CategoryFinance, UpdateFinaIndicator},
		{"forecast", CategoryFinance, UpdateForecast},
	}
	event := []JobEntry{
		{"stk_holdertrade", CategoryEvent, UpdateHolderTrade},
		{"top_list", CategoryEvent, UpdateTopList},
		{"top_inst", CategoryEvent, UpdateTopInst},
	}
	switch phase {
	case PhaseBasic:
		return basic
	case PhasePrice:
		return price
	case PhaseFinance:
		return finance
	case PhaseEvent:
		return event
	default:
		all := append([]JobEntry{}, basic...)
		all = append(all, price...)
		all = append(all, finance...)
		all = append(all, event...)
		return all
	}
}

func JobForDataset(dataset string) (JobEntry, bool) {
	dataset = strings.TrimSpace(dataset)
	if dataset == "" {
		return JobEntry{}, false
	}
	for _, job := range AllJobs() {
		if job.Name == dataset {
			return job, true
		}
	}
	return JobEntry{}, false
}

// AllJobs 返回所有 jobs 的元数据（前端构建数据集列表用）。
func AllJobs() []JobEntry {
	return JobsForPhase(PhaseAll)
}

// ParsePhase 把字符串解析成 Phase，未识别返回 all。
func ParsePhase(s string) Phase {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "basic":
		return PhaseBasic
	case "price":
		return PhasePrice
	case "finance":
		return PhaseFinance
	case "event":
		return PhaseEvent
	default:
		return PhaseAll
	}
}
