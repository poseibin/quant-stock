package market

import "time"

type DataFile struct {
	ID            string    `json:"id"`
	DataType      string    `json:"data_type"`
	PartitionName string    `json:"partition_name"`
	FilePath      string    `json:"file_path"`
	RowCount      int64     `json:"row_count"`
	FileSize      int64     `json:"file_size"`
	CreatedAt     time.Time `json:"created_at"`
	UpdatedAt     time.Time `json:"updated_at"`
}

type DataFileDTO struct {
	ID            string `json:"id"`
	DataType      string `json:"data_type"`
	PartitionName string `json:"partition_name"`
	FilePath      string `json:"file_path"`
	RowCount      int64  `json:"row_count"`
	FileSize      int64  `json:"file_size"`
	CreatedAt     string `json:"created_at"`
	UpdatedAt     string `json:"updated_at"`
}
