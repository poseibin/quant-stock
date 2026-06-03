package datafetch

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/parquet-go/parquet-go"
)

// buildSchema 按字段顺序构建 parquet schema，所有列均为 OPTIONAL。
func buildSchema(name string, orderedFields []string, types map[string]ColType) *parquet.Schema {
	g := parquet.Group{}
	for _, f := range orderedFields {
		t, ok := types[f]
		if !ok {
			t = ColString
		}
		switch t {
		case ColString:
			g[f] = parquet.Optional(parquet.String())
		case ColDouble:
			g[f] = parquet.Optional(parquet.Leaf(parquet.DoubleType))
		case ColInt64:
			g[f] = parquet.Optional(parquet.Leaf(parquet.Int64Type))
		default:
			g[f] = parquet.Optional(parquet.String())
		}
	}
	return parquet.NewSchema(name, g)
}

// convertValue 把 Tushare 返回的 any 按目标 ColType 转为 parquet 兼容值；返回 nil 表示 null。
func convertValue(raw any, t ColType) (any, error) {
	if raw == nil {
		return nil, nil
	}
	switch v := raw.(type) {
	case string:
		if v == "" || v == "None" || v == "nan" || v == "NaN" {
			return nil, nil
		}
		switch t {
		case ColString:
			return v, nil
		case ColDouble:
			f, err := strconv.ParseFloat(v, 64)
			if err != nil {
				return nil, nil
			}
			return f, nil
		case ColInt64:
			i, err := strconv.ParseInt(v, 10, 64)
			if err != nil {
				f, err2 := strconv.ParseFloat(v, 64)
				if err2 != nil {
					return nil, nil
				}
				return int64(f), nil
			}
			return i, nil
		}
	case float64:
		switch t {
		case ColDouble:
			return v, nil
		case ColInt64:
			return int64(v), nil
		case ColString:
			return strconv.FormatFloat(v, 'f', -1, 64), nil
		}
	case float32:
		return convertValue(float64(v), t)
	case int:
		return convertValue(int64(v), t)
	case int32:
		return convertValue(int64(v), t)
	case int64:
		switch t {
		case ColInt64:
			return v, nil
		case ColDouble:
			return float64(v), nil
		case ColString:
			return strconv.FormatInt(v, 10), nil
		}
	case bool:
		switch t {
		case ColInt64:
			if v {
				return int64(1), nil
			}
			return int64(0), nil
		case ColString:
			return strconv.FormatBool(v), nil
		}
	}
	return nil, fmt.Errorf("convertValue: unsupported %T -> %s", raw, t)
}

// itemsToRows 把 Tushare 返回的 [][]any 按 fields 顺序对齐 orderedFields 后构造 parquet.Row。
// 不在 orderedFields 中的字段被忽略；orderedFields 中的字段在 fields 缺失则为 null。
func itemsToRows(orderedFields []string, types map[string]ColType, fields []string, items [][]any) ([]parquet.Row, error) {
	idx := make(map[string]int, len(fields))
	for i, f := range fields {
		idx[f] = i
	}

	rows := make([]parquet.Row, 0, len(items))
	for _, item := range items {
		row := make(parquet.Row, 0, len(orderedFields))
		for col, name := range orderedFields {
			t := types[name]
			var raw any
			if pos, ok := idx[name]; ok && pos < len(item) {
				raw = item[pos]
			}
			val, err := convertValue(raw, t)
			if err != nil {
				return nil, err
			}
			if val == nil {
				row = append(row, parquet.Value{}.Level(0, 0, col))
			} else {
				row = append(row, parquet.ValueOf(val).Level(0, 1, col))
			}
		}
		rows = append(rows, row)
	}
	return rows, nil
}

// orderedFieldsOf 给 dataset 决定字段顺序：已知小表用 DatasetSchemas key 顺序排序；
// 否则用 fields 原顺序。优先保证已知字段排前，未知字段尾随，避免 schema 漂移。
func orderedFieldsOf(dataset string, fields []string, types map[string]ColType) []string {
	known := DatasetSchemas[dataset]
	if known == nil {
		// 财务大表：直接用 fields 原顺序
		out := make([]string, len(fields))
		copy(out, fields)
		return out
	}
	// 已知 dataset：按 known 的稳定顺序（按字段名字典序）
	knownNames := make([]string, 0, len(known))
	for k := range known {
		knownNames = append(knownNames, k)
	}
	sort.Strings(knownNames)
	out := make([]string, 0, len(fields))
	seen := map[string]bool{}
	for _, n := range knownNames {
		if _, ok := types[n]; ok {
			out = append(out, n)
			seen[n] = true
		}
	}
	for _, n := range fields {
		if !seen[n] {
			out = append(out, n)
		}
	}
	return out
}

// writeParquetFile 原子写：先写 .tmp 再 rename。
func writeParquetFile(path, datasetName string, orderedFields []string, types map[string]ColType, rows []parquet.Row) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	tmp := path + ".tmp"
	f, err := os.Create(tmp)
	if err != nil {
		return err
	}
	schema := buildSchema(datasetName, orderedFields, types)
	w := parquet.NewGenericWriter[any](f, schema)
	if _, err := w.WriteRows(rows); err != nil {
		_ = w.Close()
		_ = f.Close()
		_ = os.Remove(tmp)
		return err
	}
	if err := w.Close(); err != nil {
		_ = f.Close()
		_ = os.Remove(tmp)
		return err
	}
	if err := f.Close(); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	return os.Rename(tmp, path)
}

// readParquetAsMaps 读旧文件为 []map[string]any，列顺序作为第二个返回值。
// 如果文件不存在返回 (nil, nil, nil)。
func readParquetAsMaps(path string) ([]map[string]any, []string, error) {
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil, nil
		}
		return nil, nil, err
	}
	defer f.Close()

	stat, err := f.Stat()
	if err != nil {
		return nil, nil, err
	}
	pf, err := parquet.OpenFile(f, stat.Size())
	if err != nil {
		return nil, nil, err
	}

	schema := pf.Schema()
	leafCols := schema.Columns()
	colNames := make([]string, 0, len(leafCols))
	for _, c := range leafCols {
		if len(c) > 0 {
			colNames = append(colNames, c[len(c)-1])
		}
	}

	totalRows := pf.NumRows()
	if totalRows <= 0 {
		return nil, colNames, nil
	}

	reader := parquet.NewReader(pf, schema)
	defer reader.Close()

	out := make([]map[string]any, 0, totalRows)
	buf := make([]parquet.Row, 1024)
	for {
		n, err := reader.ReadRows(buf)
		for i := 0; i < n; i++ {
			rec := make(map[string]any, len(colNames))
			for j, name := range colNames {
				if j >= len(buf[i]) {
					break
				}
				v := buf[i][j]
				if v.IsNull() {
					rec[name] = nil
				} else {
					rec[name] = parquetValueToAny(v)
				}
			}
			out = append(out, rec)
		}
		if err != nil {
			break
		}
	}
	return out, colNames, nil
}

// parquetValueToAny 将 parquet.Value 转换为通用 Go 类型 (string/int64/float64/bool)。
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

// rowKey 按 PK 列从 record 拼出主键字符串。
func rowKey(record map[string]any, pk []string) string {
	parts := make([]string, len(pk))
	for i, k := range pk {
		v := record[k]
		if v == nil {
			parts[i] = ""
		} else {
			parts[i] = fmt.Sprintf("%v", v)
		}
	}
	return strings.Join(parts, "\x1f")
}

// mapsToItems 把 []map → fields/items 形式（与 Tushare 返回格式对齐）。
func mapsToItems(records []map[string]any, orderedFields []string) [][]any {
	items := make([][]any, len(records))
	for i, r := range records {
		row := make([]any, len(orderedFields))
		for j, f := range orderedFields {
			row[j] = r[f]
		}
		items[i] = row
	}
	return items
}

// Upsert 把新数据合并到 path 文件：
//   - overwrite=true：直接写新数据覆盖
//   - overwrite=false：读旧数据，按 PK 去重保留 last（新数据优先），写回
//
// 返回写入的总行数。
func Upsert(path string, datasetName string, fields []string, items [][]any, pk []string, overwrite bool) (int, error) {
	types := ResolveSchema(datasetName, fields)
	orderedFields := orderedFieldsOf(datasetName, fields, types)

	if overwrite {
		rows, err := itemsToRows(orderedFields, types, fields, items)
		if err != nil {
			return 0, err
		}
		if err := writeParquetFile(path, datasetName, orderedFields, types, rows); err != nil {
			return 0, err
		}
		return len(rows), nil
	}

	old, _, err := readParquetAsMaps(path)
	if err != nil {
		return 0, err
	}

	merged := make(map[string]map[string]any, len(old)+len(items))
	keyOrder := make([]string, 0, len(old)+len(items))

	for _, r := range old {
		k := rowKey(r, pk)
		if _, ok := merged[k]; !ok {
			keyOrder = append(keyOrder, k)
		}
		merged[k] = r
	}

	idx := make(map[string]int, len(fields))
	for i, f := range fields {
		idx[f] = i
	}
	for _, item := range items {
		rec := make(map[string]any, len(orderedFields))
		for _, f := range orderedFields {
			t := types[f]
			var raw any
			if p, ok := idx[f]; ok && p < len(item) {
				raw = item[p]
			}
			val, err := convertValue(raw, t)
			if err != nil {
				return 0, err
			}
			rec[f] = val
		}
		k := rowKey(rec, pk)
		if _, ok := merged[k]; !ok {
			keyOrder = append(keyOrder, k)
		}
		merged[k] = rec
	}

	finalRecords := make([]map[string]any, 0, len(merged))
	for _, k := range keyOrder {
		finalRecords = append(finalRecords, merged[k])
	}

	finalItems := mapsToItems(finalRecords, orderedFields)
	rows, err := itemsToRows(orderedFields, types, orderedFields, finalItems)
	if err != nil {
		return 0, err
	}
	if err := writeParquetFile(path, datasetName, orderedFields, types, rows); err != nil {
		return 0, err
	}
	return len(rows), nil
}

// PartitionPath 计算 dataset + 分区策略对应的 parquet 文件路径。
func PartitionPath(dataPath, dataset string, partition PartitionStrategy, year int) string {
	base := filepath.Join(dataPath, "raw", dataset)
	switch partition {
	case PartitionSingle:
		return filepath.Join(base, "data.parquet")
	case PartitionYear:
		return filepath.Join(base, fmt.Sprintf("year=%d.parquet", year))
	}
	return filepath.Join(base, "data.parquet")
}

// LatestDate 扫 dataset 所有 parquet，取 dateField 列的最大值。返回空字符串表示无数据。
func LatestDate(dataPath, dataset, dateField string) (string, error) {
	dir := filepath.Join(dataPath, "raw", dataset)
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return "", nil
		}
		return "", err
	}
	var maxVal string
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".parquet") {
			continue
		}
		path := filepath.Join(dir, e.Name())
		recs, _, err := readParquetAsMaps(path)
		if err != nil {
			return "", err
		}
		for _, r := range recs {
			v, ok := r[dateField]
			if !ok || v == nil {
				continue
			}
			s, ok := v.(string)
			if !ok {
				s = fmt.Sprintf("%v", v)
			}
			if s > maxVal {
				maxVal = s
			}
		}
	}
	return maxVal, nil
}

// ListExistingPeriods 扫 dataset 所有 parquet 文件，从 dateField 列收集 distinct 值。
func ListExistingPeriods(dataPath, dataset, dateField string) (map[string]bool, error) {
	dir := filepath.Join(dataPath, "raw", dataset)
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return map[string]bool{}, nil
		}
		return nil, err
	}
	out := map[string]bool{}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".parquet") {
			continue
		}
		path := filepath.Join(dir, e.Name())
		recs, _, err := readParquetAsMaps(path)
		if err != nil {
			return nil, err
		}
		for _, r := range recs {
			v, ok := r[dateField]
			if !ok || v == nil {
				continue
			}
			s, ok := v.(string)
			if !ok {
				s = fmt.Sprintf("%v", v)
			}
			if s != "" {
				out[s] = true
			}
		}
	}
	return out, nil
}

// 日期辅助。
func today() string { return time.Now().Format("20060102") }

func nextDay(s string) (string, error) {
	t, err := time.Parse("20060102", s)
	if err != nil {
		return "", err
	}
	return t.AddDate(0, 0, 1).Format("20060102"), nil
}
