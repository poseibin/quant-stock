package market

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	parquet "github.com/parquet-go/parquet-go"
)

type DatasetPreviewQuery struct {
	Dataset string `json:"dataset"`
	Limit   int    `json:"limit"`
}

type DatasetPreview struct {
	Dataset string              `json:"dataset"`
	Columns []string            `json:"columns"`
	Rows    []map[string]string `json:"rows"`
}

func (service *Service) PreviewDataset(dataPath string, query DatasetPreviewQuery) (DatasetPreview, error) {
	dataset := strings.TrimSpace(query.Dataset)
	if dataset == "" || strings.Contains(dataset, string(filepath.Separator)) || strings.Contains(dataset, "..") {
		return DatasetPreview{}, fmt.Errorf("invalid dataset")
	}
	limit := query.Limit
	if limit <= 0 || limit > 200 {
		limit = 100
	}

	files, err := previewFiles(dataPath, dataset)
	if err != nil {
		return DatasetPreview{}, err
	}
	preview := DatasetPreview{
		Dataset: dataset,
		Rows:    make([]map[string]string, 0, limit),
	}
	for _, filePath := range files {
		columns, rows, err := readPreviewFile(filePath, limit-len(preview.Rows))
		if err != nil {
			return DatasetPreview{}, err
		}
		if len(preview.Columns) == 0 {
			preview.Columns = columns
		}
		preview.Rows = append(preview.Rows, rows...)
		if len(preview.Rows) >= limit {
			break
		}
	}
	return preview, nil
}

func previewFiles(dataPath string, dataset string) ([]string, error) {
	datasetPath := filepath.Join(dataPath, "raw", dataset)
	files, err := filepath.Glob(filepath.Join(datasetPath, "*.parquet"))
	if err != nil {
		return nil, err
	}
	sort.Strings(files)
	return files, nil
}

func readPreviewFile(filePath string, limit int) ([]string, []map[string]string, error) {
	if limit <= 0 {
		return nil, nil, nil
	}
	file, err := os.Open(filePath)
	if err != nil {
		return nil, nil, err
	}
	defer file.Close()

	reader := parquet.NewGenericReader[map[string]interface{}](file)
	defer reader.Close()

	rows := make([]map[string]string, 0, limit)
	columns := make([]string, 0)
	seenColumns := map[string]bool{}
	buffer := make([]map[string]interface{}, 128)
	for len(rows) < limit {
		count, err := reader.Read(buffer)
		for index := 0; index < count && len(rows) < limit; index++ {
			row := make(map[string]string)
			for key, value := range buffer[index] {
				if !seenColumns[key] {
					seenColumns[key] = true
					columns = append(columns, key)
				}
				row[key] = fmt.Sprint(value)
			}
			rows = append(rows, row)
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, nil, err
		}
	}
	sort.Strings(columns)
	return columns, rows, nil
}
