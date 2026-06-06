package market

import (
	"strings"
	"time"

	"quant_stock_desktop/internal/common/database"
)

type Repository struct {
	db *database.DB
}

func NewRepository(db *database.DB) *Repository {
	return &Repository{db: db}
}

func (repo *Repository) List() ([]DataFile, error) {
	rows, err := repo.db.Conn().Query(`SELECT id, data_type, partition_name, file_path, row_count, file_size, created_at, updated_at
		FROM data_market_files ORDER BY data_type, partition_name`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]DataFile, 0)
	for rows.Next() {
		var item DataFile
		var createdAt string
		var updatedAt string
		if err := rows.Scan(&item.ID, &item.DataType, &item.PartitionName, &item.FilePath, &item.RowCount, &item.FileSize, &createdAt, &updatedAt); err != nil {
			return nil, err
		}
		item.CreatedAt = parseTime(createdAt)
		item.UpdatedAt = parseTime(updatedAt)
		items = append(items, item)
	}
	return items, rows.Err()
}

type Service struct {
	repo *Repository
}

func NewService(repo *Repository) *Service {
	return &Service{repo: repo}
}

func isMissingDataTable(err error) bool {
	if err == nil {
		return false
	}
	text := strings.ToLower(err.Error())
	return strings.Contains(text, "no such table") ||
		strings.Contains(text, "doesn't exist") ||
		strings.Contains(text, "unknown table")
}

func (service *Service) List() ([]DataFileDTO, error) {
	items, err := service.repo.List()
	if err != nil {
		return nil, err
	}
	out := make([]DataFileDTO, 0, len(items))
	for _, item := range items {
		out = append(out, ToDTO(item))
	}
	return out, nil
}

func ToDTO(file DataFile) DataFileDTO {
	return DataFileDTO{
		ID:            file.ID,
		DataType:      file.DataType,
		PartitionName: file.PartitionName,
		FilePath:      file.FilePath,
		RowCount:      file.RowCount,
		FileSize:      file.FileSize,
		CreatedAt:     formatTime(file.CreatedAt),
		UpdatedAt:     formatTime(file.UpdatedAt),
	}
}

func formatTime(value time.Time) string {
	if value.IsZero() {
		return ""
	}
	return value.Format(time.RFC3339)
}

func parseTime(value string) time.Time {
	if value == "" {
		return time.Time{}
	}
	parsed, _ := time.Parse(time.RFC3339, value)
	return parsed
}
