package datafetch

import (
	"encoding/json"
	"errors"
	"math"
	"time"

	"quant_stock_desktop/internal/common/database"
)

var ErrAlreadyRunning = errors.New("data update already running")

const statusTask = "data_update"

func statusBegin(db *database.DB, total int) error {
	if db == nil {
		return nil
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, err := db.Conn().Exec(
		db.UpsertSQL(
			"task_run_status",
			[]string{"task", "task_type", "state", "idx", "total", "stage", "name", "message", "worker_pid", "started_at", "updated_at", "finished_at"},
			[]string{"task"},
			[]string{"task_type", "state", "idx", "total", "stage", "name", "message", "worker_pid", "started_at", "updated_at", "finished_at"},
		),
		statusTask, "data_update", "running", 0, total, "", "", "", nil, now, now, "")
	return err
}

func statusProgress(db *database.DB, idx, total int, stage, name, message string) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, _ = db.Conn().Exec(
		`UPDATE task_run_status SET task_type='data_update',idx=?,total=?,stage=?,name=?,message=?,updated_at=? WHERE task=?`,
		idx, total, stage, name, message, now, statusTask)
}

func statusDone(db *database.DB, message string) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, _ = db.Conn().Exec(
		`UPDATE task_run_status SET task_type='data_update',state='success',message=?,worker_pid=NULL,updated_at=?,finished_at=? WHERE task=?`,
		message, now, now, statusTask)
}

func statusError(db *database.DB, message string) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, _ = db.Conn().Exec(
		`UPDATE task_run_status SET task_type='data_update',state='error',message=?,worker_pid=NULL,updated_at=?,finished_at=? WHERE task=?`,
		message, now, now, statusTask)
}

// ----------------------------------------------------------------------------
// 单数据集级状态：task_jobs(task_type=data_update)
// ----------------------------------------------------------------------------

// DatasetStatus 是前端展示用的数据集更新状态。
type DatasetStatus struct {
	Dataset       string `json:"dataset"`
	Category      string `json:"category"`
	State         string `json:"state"`
	ProgressDone  int    `json:"progress_done"`
	ProgressTotal int    `json:"progress_total"`
	Message       string `json:"message"`
	RowsWritten   int    `json:"rows_written"`
	ErrorMessage  string `json:"error_message"`
	StartedAt     string `json:"started_at"`
	FinishedAt    string `json:"finished_at"`
	UpdatedAt     string `json:"updated_at"`
}

// datasetBegin 标记某 dataset 进入 running。
func datasetBegin(db *database.DB, dataset, category string) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	datasetUpsert(db, dataset, category, "running", 0, 0, "", 0, "", now, "", now, 0, 0)
}

// datasetProgress 更新某 dataset 的当前进度（不改变 state）。
func datasetProgress(db *database.DB, dataset string, done, total int, message string) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	summary := datasetSummary("", "", done, total, message, 0, "")
	_, _ = db.Conn().Exec(
		`UPDATE task_jobs
		 SET progress=?, summary_json=?, updated_at=?
		 WHERE task_type='data_update' AND subtask_key=?`,
		datasetProgressRatio(done, total), summary, now, dataset)
}

// datasetSuccess 把某 dataset 标记为 success。
func datasetSuccess(db *database.DB, dataset string, rows int, message string) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	summary := datasetSummary("", "", 1, 1, message, rows, "")
	_, _ = db.Conn().Exec(
		`UPDATE task_jobs
		 SET status='success', progress=1, summary_json=?, error_message='', finished_at=?, updated_at=?
		 WHERE task_type='data_update' AND subtask_key=?`,
		summary, now, now, dataset)
}

// datasetFailed 把某 dataset 标记为 failed。
func datasetFailed(db *database.DB, dataset, errMsg string, rows int) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	summary := datasetSummary("", "", 0, 0, errMsg, rows, errMsg)
	_, _ = db.Conn().Exec(
		`UPDATE task_jobs
		 SET status='failed', summary_json=?, error_message=?, finished_at=?, updated_at=?
		 WHERE task_type='data_update' AND subtask_key=?`,
		summary, errMsg, now, now, dataset)
}

// listDatasetStatus 查询所有 dataset 状态。
func listDatasetStatus(db *database.DB) ([]DatasetStatus, error) {
	if db == nil {
		return []DatasetStatus{}, nil
	}
	rows, err := db.Conn().Query(
		`SELECT COALESCE(subtask_key, ''), COALESCE(subtask_name, name), status, progress,
		        COALESCE(params_json, '{}'), COALESCE(summary_json, '{}'), COALESCE(error_message, ''),
		        COALESCE(started_at, ''), COALESCE(finished_at, ''), updated_at
		 FROM task_jobs
		 WHERE task_type='data_update' AND COALESCE(subtask_key, '') <> ''
		 ORDER BY COALESCE(sequence, 0), subtask_key`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []DatasetStatus
	for rows.Next() {
		var (
			dataset, name, status, paramsJSON, summaryJSON, errorMessage, startedAt, finishedAt, updatedAt string
			progress                                                                                       float64
		)
		if err := rows.Scan(&dataset, &name, &status, &progress, &paramsJSON, &summaryJSON, &errorMessage, &startedAt, &finishedAt, &updatedAt); err != nil {
			return nil, err
		}
		summary := map[string]any{}
		params := map[string]any{}
		_ = json.Unmarshal([]byte(summaryJSON), &summary)
		_ = json.Unmarshal([]byte(paramsJSON), &params)
		done := intValue(summary["progress_done"])
		total := intValue(summary["progress_total"])
		if total == 0 && progress > 0 {
			total = 100
			done = int(math.Round(progress * 100))
		}
		s := DatasetStatus{
			Dataset:       firstString(dataset, name, stringValue(params["dataset"])),
			Category:      stringValue(params["category"]),
			State:         datasetState(status),
			ProgressDone:  done,
			ProgressTotal: total,
			Message:       stringValue(summary["message"]),
			RowsWritten:   intValue(summary["rows_written"]),
			ErrorMessage:  firstString(errorMessage, stringValue(summary["error_message"])),
			StartedAt:     startedAt,
			FinishedAt:    finishedAt,
			UpdatedAt:     updatedAt,
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

func datasetUpsert(db *database.DB, dataset, category, status string, done, total int, message string, rowsWritten int, errorMessage string, startedAt, finishedAt, updatedAt string, sequence, sequenceTotal int) {
	if db == nil {
		return
	}
	params := datasetParams(dataset, category)
	summary := datasetSummary(dataset, category, done, total, message, rowsWritten, errorMessage)
	_, _ = db.Conn().Exec(
		db.UpsertSQL(
			"task_jobs",
			[]string{"id", "name", "task_type", "status", "progress", "params_json", "summary_json", "result_path", "log_path", "worker_type", "worker_pid", "external_run_id", "error_message", "parent_id", "group_run_id", "subtask_key", "subtask_name", "sequence", "total", "attempt", "max_attempts", "created_at", "queued_at", "started_at", "finished_at", "updated_at"},
			[]string{"id"},
			[]string{"name", "status", "progress", "params_json", "summary_json", "error_message", "subtask_key", "subtask_name", "sequence", "total", "queued_at", "started_at", "finished_at", "updated_at"},
		),
		datasetTaskID(dataset), dataset, "data_update", status, datasetProgressRatio(done, total), params, summary, "", "", "go", nil, "", errorMessage, statusTask, statusTask, dataset, dataset, sequence, sequenceTotal, 0, 1, updatedAt, queuedAt(status, updatedAt), startedAt, finishedAt, updatedAt,
	)
}

func datasetTaskID(dataset string) string {
	return "data_update:" + dataset
}

func datasetParams(dataset, category string) string {
	data, _ := json.Marshal(map[string]any{"dataset": dataset, "category": category})
	return string(data)
}

func datasetSummary(dataset, category string, done, total int, message string, rowsWritten int, errorMessage string) string {
	data, _ := json.Marshal(map[string]any{
		"dataset":        dataset,
		"category":       category,
		"progress_done":  done,
		"progress_total": total,
		"message":        message,
		"rows_written":   rowsWritten,
		"error_message":  errorMessage,
	})
	return string(data)
}

func queuedAt(status, updatedAt string) string {
	if status == "queued" {
		return updatedAt
	}
	return ""
}

func datasetProgressRatio(done, total int) float64 {
	if total <= 0 {
		return 0
	}
	return math.Max(0, math.Min(1, float64(done)/float64(total)))
}

func datasetState(status string) string {
	switch status {
	case "created", "queued":
		return "pending"
	case "running", "success":
		return status
	case "failed", "cancelled", "interrupted", "error":
		return "failed"
	default:
		return status
	}
}

func stringValue(value any) string {
	if s, ok := value.(string); ok {
		return s
	}
	return ""
}

func firstString(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

func intValue(value any) int {
	switch v := value.(type) {
	case int:
		return v
	case int64:
		return int(v)
	case float64:
		return int(v)
	case json.Number:
		n, _ := v.Int64()
		return int(n)
	default:
		return 0
	}
}
