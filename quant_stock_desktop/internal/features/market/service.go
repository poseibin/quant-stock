package market

import (
	"crypto/sha1"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type Repository struct {
	db *sql.DB
}

func NewRepository(db *sql.DB) *Repository {
	return &Repository{db: db}
}

func (repo *Repository) Upsert(file DataFile) error {
	_, err := repo.db.Exec(`INSERT INTO market_data_files (
		id, data_type, partition_name, file_path, row_count, file_size, created_at, updated_at
	) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
	ON CONFLICT(file_path) DO UPDATE SET
		data_type = excluded.data_type,
		partition_name = excluded.partition_name,
		row_count = excluded.row_count,
		file_size = excluded.file_size,
		updated_at = excluded.updated_at`,
		file.ID,
		file.DataType,
		file.PartitionName,
		file.FilePath,
		file.RowCount,
		file.FileSize,
		formatTime(file.CreatedAt),
		formatTime(file.UpdatedAt),
	)
	return err
}

func (repo *Repository) List() ([]DataFile, error) {
	rows, err := repo.db.Query(`SELECT id, data_type, partition_name, file_path, row_count, file_size, created_at, updated_at
		FROM market_data_files ORDER BY data_type, partition_name`)
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

func (service *Service) Scan(dataPath string) ([]DataFileDTO, error) {
	rawPath := filepath.Join(dataPath, "raw")
	entries, err := os.ReadDir(rawPath)
	if err != nil {
		return nil, err
	}
	now := time.Now()
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		dataType := entry.Name()
		datasetPath := filepath.Join(rawPath, dataType)
		files, err := filepath.Glob(filepath.Join(datasetPath, "*.parquet"))
		if err != nil {
			return nil, err
		}
		for _, filePath := range files {
			info, err := os.Stat(filePath)
			if err != nil {
				continue
			}
			partition := strings.TrimSuffix(filepath.Base(filePath), filepath.Ext(filePath))
			file := DataFile{
				ID:            idForPath(filePath),
				DataType:      dataType,
				PartitionName: partition,
				FilePath:      filePath,
				FileSize:      info.Size(),
				CreatedAt:     now,
				UpdatedAt:     now,
			}
			if err := service.repo.Upsert(file); err != nil {
				return nil, err
			}
		}
	}
	return service.List()
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

func idForPath(path string) string {
	sum := sha1.Sum([]byte(path))
	return fmt.Sprintf("mdf_%x", sum[:8])
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
