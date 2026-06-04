package task

import (
	"database/sql"
	"time"
)

type Repository struct {
	db *sql.DB
}

func NewRepository(db *sql.DB) *Repository {
	return &Repository{db: db}
}

func (repo *Repository) Create(task Task) error {
	_, err := repo.db.Exec(`INSERT INTO evaluation_tasks (
		id, name, task_type, status, progress, params_json, summary_json, result_path,
		log_path, worker_type, worker_pid, external_run_id, error_message,
		parent_id, group_run_id, subtask_key, subtask_name, sequence, total, attempt, max_attempts,
		created_at, queued_at, started_at, finished_at, updated_at
	) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		task.ID,
		task.Name,
		string(task.TaskType),
		string(task.Status),
		task.Progress,
		task.ParamsJSON,
		nullString(task.SummaryJSON),
		nullString(task.ResultPath),
		nullString(task.LogPath),
		task.WorkerType,
		nullInt(task.WorkerPID),
		nullString(task.ExternalRunID),
		nullString(task.ErrorMessage),
		nullString(task.ParentID),
		nullString(task.GroupRunID),
		nullString(task.SubtaskKey),
		nullString(task.SubtaskName),
		task.Sequence,
		task.Total,
		task.Attempt,
		task.MaxAttempts,
		formatTime(task.CreatedAt),
		nullTime(task.QueuedAt),
		nullTime(task.StartedAt),
		nullTime(task.FinishedAt),
		formatTime(task.UpdatedAt),
	)
	return err
}

func (repo *Repository) Get(id string) (Task, error) {
	row := repo.db.QueryRow(`SELECT id, name, task_type, status, progress, params_json,
		COALESCE(summary_json, ''), COALESCE(result_path, ''), COALESCE(log_path, ''),
		worker_type, COALESCE(worker_pid, 0), COALESCE(external_run_id, ''), COALESCE(error_message, ''),
		COALESCE(parent_id, ''), COALESCE(group_run_id, ''), COALESCE(subtask_key, ''), COALESCE(subtask_name, ''),
		COALESCE(sequence, 0), COALESCE(total, 0), COALESCE(attempt, 0), COALESCE(max_attempts, 1),
		created_at, COALESCE(queued_at, ''), COALESCE(started_at, ''), COALESCE(finished_at, ''), updated_at
		FROM evaluation_tasks WHERE id = ?`, id)
	return scanTask(row)
}

func (repo *Repository) List(query Query) ([]Task, error) {
	limit := query.Limit
	if limit <= 0 || limit > 500 {
		limit = 100
	}
	var rows *sql.Rows
	var err error
	if query.Status != "" {
		rows, err = repo.db.Query(`SELECT id, name, task_type, status, progress, params_json,
			COALESCE(summary_json, ''), COALESCE(result_path, ''), COALESCE(log_path, ''),
			worker_type, COALESCE(worker_pid, 0), COALESCE(external_run_id, ''), COALESCE(error_message, ''),
			COALESCE(parent_id, ''), COALESCE(group_run_id, ''), COALESCE(subtask_key, ''), COALESCE(subtask_name, ''),
			COALESCE(sequence, 0), COALESCE(total, 0), COALESCE(attempt, 0), COALESCE(max_attempts, 1),
			created_at, COALESCE(queued_at, ''), COALESCE(started_at, ''), COALESCE(finished_at, ''), updated_at
			FROM evaluation_tasks WHERE status = ? ORDER BY COALESCE(parent_id, id) DESC, sequence ASC, created_at DESC LIMIT ?`, query.Status, limit)
	} else {
		rows, err = repo.db.Query(`SELECT id, name, task_type, status, progress, params_json,
			COALESCE(summary_json, ''), COALESCE(result_path, ''), COALESCE(log_path, ''),
			worker_type, COALESCE(worker_pid, 0), COALESCE(external_run_id, ''), COALESCE(error_message, ''),
			COALESCE(parent_id, ''), COALESCE(group_run_id, ''), COALESCE(subtask_key, ''), COALESCE(subtask_name, ''),
			COALESCE(sequence, 0), COALESCE(total, 0), COALESCE(attempt, 0), COALESCE(max_attempts, 1),
			created_at, COALESCE(queued_at, ''), COALESCE(started_at, ''), COALESCE(finished_at, ''), updated_at
			FROM evaluation_tasks ORDER BY COALESCE(parent_id, id) DESC, sequence ASC, created_at DESC LIMIT ?`, limit)
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	tasks := make([]Task, 0)
	for rows.Next() {
		task, err := scanTask(rows)
		if err != nil {
			return nil, err
		}
		tasks = append(tasks, task)
	}
	return tasks, rows.Err()
}

func (repo *Repository) HasRunningEvaluation(excludeID string) (bool, error) {
	row := repo.db.QueryRow(`SELECT COUNT(*) FROM evaluation_tasks
		WHERE task_type IN (?, ?, ?, ?, ?) AND status IN ('queued', 'running') AND id <> ?`,
		string(TypeEvaluationTimeMachine), string(TypeStrategyEvaluation), string(TypePortfolioOptimization), string(TypeWalkForwardEvaluation), string(TypeParameterExperiment), excludeID)
	var count int
	if err := row.Scan(&count); err != nil {
		return false, err
	}
	return count > 0, nil
}

func (repo *Repository) ListChildren(parentID string) ([]Task, error) {
	rows, err := repo.db.Query(`SELECT id, name, task_type, status, progress, params_json,
		COALESCE(summary_json, ''), COALESCE(result_path, ''), COALESCE(log_path, ''),
		worker_type, COALESCE(worker_pid, 0), COALESCE(external_run_id, ''), COALESCE(error_message, ''),
		COALESCE(parent_id, ''), COALESCE(group_run_id, ''), COALESCE(subtask_key, ''), COALESCE(subtask_name, ''),
		COALESCE(sequence, 0), COALESCE(total, 0), COALESCE(attempt, 0), COALESCE(max_attempts, 1),
		created_at, COALESCE(queued_at, ''), COALESCE(started_at, ''), COALESCE(finished_at, ''), updated_at
		FROM evaluation_tasks WHERE parent_id = ? ORDER BY sequence ASC, created_at ASC`, parentID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	tasks := make([]Task, 0)
	for rows.Next() {
		task, err := scanTask(rows)
		if err != nil {
			return nil, err
		}
		tasks = append(tasks, task)
	}
	return tasks, rows.Err()
}

func (repo *Repository) UpdateRuntime(task Task) error {
	_, err := repo.db.Exec(`UPDATE evaluation_tasks SET
		status = ?, progress = ?, result_path = ?, log_path = ?, worker_pid = ?, external_run_id = ?, error_message = ?,
		attempt = ?, total = ?, queued_at = ?, started_at = ?, finished_at = ?, updated_at = ?
		WHERE id = ?`,
		string(task.Status),
		task.Progress,
		nullString(task.ResultPath),
		nullString(task.LogPath),
		nullInt(task.WorkerPID),
		nullString(task.ExternalRunID),
		nullString(task.ErrorMessage),
		task.Attempt,
		task.Total,
		nullTime(task.QueuedAt),
		nullTime(task.StartedAt),
		nullTime(task.FinishedAt),
		formatTime(task.UpdatedAt),
		task.ID,
	)
	return err
}

func (repo *Repository) UpdateStatus(task Task) error {
	_, err := repo.db.Exec(`UPDATE evaluation_tasks SET
		status = ?, progress = ?, summary_json = ?, error_message = ?, finished_at = ?, updated_at = ?
		WHERE id = ?`,
		string(task.Status),
		task.Progress,
		nullString(task.SummaryJSON),
		nullString(task.ErrorMessage),
		nullTime(task.FinishedAt),
		formatTime(task.UpdatedAt),
		task.ID,
	)
	return err
}

func (repo *Repository) Delete(id string) error {
	_, err := repo.db.Exec(`DELETE FROM evaluation_tasks WHERE id = ? OR parent_id = ?`, id, id)
	return err
}

func scanTask(scanner interface{ Scan(dest ...any) error }) (Task, error) {
	var task Task
	var taskType string
	var status string
	var createdAt string
	var queuedAt string
	var startedAt string
	var finishedAt string
	var updatedAt string
	err := scanner.Scan(
		&task.ID,
		&task.Name,
		&taskType,
		&status,
		&task.Progress,
		&task.ParamsJSON,
		&task.SummaryJSON,
		&task.ResultPath,
		&task.LogPath,
		&task.WorkerType,
		&task.WorkerPID,
		&task.ExternalRunID,
		&task.ErrorMessage,
		&task.ParentID,
		&task.GroupRunID,
		&task.SubtaskKey,
		&task.SubtaskName,
		&task.Sequence,
		&task.Total,
		&task.Attempt,
		&task.MaxAttempts,
		&createdAt,
		&queuedAt,
		&startedAt,
		&finishedAt,
		&updatedAt,
	)
	if err != nil {
		return Task{}, err
	}
	task.TaskType = Type(taskType)
	task.Status = Status(status)
	task.CreatedAt = parseTime(createdAt)
	task.QueuedAt = parseTime(queuedAt)
	task.StartedAt = parseTime(startedAt)
	task.FinishedAt = parseTime(finishedAt)
	task.UpdatedAt = parseTime(updatedAt)
	return task, nil
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

func nullString(value string) any {
	if value == "" {
		return nil
	}
	return value
}

func nullInt(value int) any {
	if value == 0 {
		return nil
	}
	return value
}

func nullTime(value time.Time) any {
	if value.IsZero() {
		return nil
	}
	return formatTime(value)
}
