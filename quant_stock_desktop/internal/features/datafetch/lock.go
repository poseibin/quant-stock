package datafetch

import (
	"database/sql"
	"errors"
	"time"
)

var ErrAlreadyRunning = errors.New("data update already running")

const statusTask = "data_update"

func statusBegin(db *sql.DB, total int) error {
	if db == nil {
		return nil
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, err := db.Exec(
		`INSERT INTO py_run_status(task,state,idx,total,stage,name,message,started_at,updated_at,finished_at)
		 VALUES(?,?,?,?,?,?,?,?,?,'')
		 ON CONFLICT(task) DO UPDATE SET
		   state=excluded.state, idx=0, total=excluded.total,
		   stage='', name='', message='',
		   started_at=excluded.started_at, updated_at=excluded.updated_at, finished_at=''`,
		statusTask, "running", 0, total, "", "", "", now, now)
	return err
}

func statusProgress(db *sql.DB, idx, total int, stage, name, message string) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, _ = db.Exec(
		`UPDATE py_run_status SET idx=?,total=?,stage=?,name=?,message=?,updated_at=? WHERE task=?`,
		idx, total, stage, name, message, now, statusTask)
}

func statusDone(db *sql.DB, message string) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, _ = db.Exec(
		`UPDATE py_run_status SET state='success',message=?,updated_at=?,finished_at=? WHERE task=?`,
		message, now, now, statusTask)
}

func statusError(db *sql.DB, message string) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, _ = db.Exec(
		`UPDATE py_run_status SET state='error',message=?,updated_at=?,finished_at=? WHERE task=?`,
		message, now, now, statusTask)
}

// ----------------------------------------------------------------------------
// 单数据集级状态：dataset_update_status
// ----------------------------------------------------------------------------

// DatasetStatus 是 dataset_update_status 表的一行。
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

// datasetMarkPending 在一次 Run 开始时把所有要跑的 dataset 标记为 pending。
func datasetMarkPending(db *sql.DB, jobs []JobEntry) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	for _, j := range jobs {
		_, _ = db.Exec(
			`INSERT INTO dataset_update_status
			   (dataset,category,state,progress_done,progress_total,message,rows_written,error_message,started_at,finished_at,updated_at)
			 VALUES(?,?,?,?,?,?,?,?,?,?,?)
			 ON CONFLICT(dataset) DO UPDATE SET
			   category=excluded.category,
			   state='pending',
			   progress_done=0,
			   progress_total=0,
			   message='',
			   error_message='',
			   started_at='',
			   finished_at='',
			   updated_at=excluded.updated_at`,
			j.Name, j.Category, "pending", 0, 0, "", 0, "", "", "", now)
	}
}

// datasetBegin 标记某 dataset 进入 running。
func datasetBegin(db *sql.DB, dataset, category string) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, _ = db.Exec(
		`INSERT INTO dataset_update_status
		   (dataset,category,state,progress_done,progress_total,message,rows_written,error_message,started_at,finished_at,updated_at)
		 VALUES(?,?,?,?,?,?,?,?,?,?,?)
		 ON CONFLICT(dataset) DO UPDATE SET
		   category=excluded.category,
		   state='running',
		   progress_done=0,
		   progress_total=0,
		   message='',
		   error_message='',
		   started_at=excluded.started_at,
		   finished_at='',
		   updated_at=excluded.updated_at`,
		dataset, category, "running", 0, 0, "", 0, "", now, "", now)
}

// datasetProgress 更新某 dataset 的当前进度（不改变 state）。
func datasetProgress(db *sql.DB, dataset string, done, total int, message string) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, _ = db.Exec(
		`UPDATE dataset_update_status
		 SET progress_done=?, progress_total=?, message=?, updated_at=?
		 WHERE dataset=?`,
		done, total, message, now, dataset)
}

// datasetSuccess 把某 dataset 标记为 success。
func datasetSuccess(db *sql.DB, dataset string, rows int, message string) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, _ = db.Exec(
		`UPDATE dataset_update_status
		 SET state='success', rows_written=?, message=?, error_message='', finished_at=?, updated_at=?
		 WHERE dataset=?`,
		rows, message, now, now, dataset)
}

// datasetFailed 把某 dataset 标记为 failed。
func datasetFailed(db *sql.DB, dataset, errMsg string, rows int) {
	if db == nil {
		return
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, _ = db.Exec(
		`UPDATE dataset_update_status
		 SET state='failed', rows_written=?, error_message=?, message=?, finished_at=?, updated_at=?
		 WHERE dataset=?`,
		rows, errMsg, errMsg, now, now, dataset)
}

// listDatasetStatus 查询所有 dataset 状态。
func listDatasetStatus(db *sql.DB) ([]DatasetStatus, error) {
	if db == nil {
		return []DatasetStatus{}, nil
	}
	rows, err := db.Query(
		`SELECT dataset,category,state,progress_done,progress_total,message,rows_written,
		        error_message,started_at,finished_at,updated_at
		 FROM dataset_update_status
		 ORDER BY dataset`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []DatasetStatus
	for rows.Next() {
		var s DatasetStatus
		if err := rows.Scan(&s.Dataset, &s.Category, &s.State, &s.ProgressDone, &s.ProgressTotal,
			&s.Message, &s.RowsWritten, &s.ErrorMessage, &s.StartedAt, &s.FinishedAt, &s.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}
