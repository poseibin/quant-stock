package task

import "time"

type Status string

type Type string

const (
	StatusCreated     Status = "created"
	StatusQueued      Status = "queued"
	StatusRunning     Status = "running"
	StatusSuccess     Status = "success"
	StatusFailed      Status = "failed"
	StatusCancelled   Status = "cancelled"
	StatusInterrupted Status = "interrupted"
)

const (
	TypeEvaluationTimeMachine Type = "evaluation_time_machine"
	TypeStrategyEvaluation    Type = "eval_strategy_admission"
	TypePortfolioOptimization Type = "portfolio_optimization"
	TypeWalkForwardEvaluation Type = "walk_forward_evaluation"
	TypeParameterExperiment   Type = "parameter_experiment"
	TypeFactorResearch        Type = "factor_research"
	TypeDataUpdate            Type = "data_update"
	TypeDailySignal           Type = "daily_signal"
)

type Task struct {
	ID            string    `json:"id"`
	Name          string    `json:"name"`
	TaskType      Type      `json:"task_type"`
	Status        Status    `json:"status"`
	Progress      float64   `json:"progress"`
	ParamsJSON    string    `json:"params_json"`
	SummaryJSON   string    `json:"summary_json"`
	ResultPath    string    `json:"result_path"`
	LogPath       string    `json:"log_path"`
	WorkerType    string    `json:"worker_type"`
	WorkerPID     int       `json:"worker_pid"`
	ExternalRunID string    `json:"external_run_id"`
	ErrorMessage  string    `json:"error_message"`
	ParentID      string    `json:"parent_id"`
	GroupRunID    string    `json:"group_run_id"`
	SubtaskKey    string    `json:"subtask_key"`
	SubtaskName   string    `json:"subtask_name"`
	Sequence      int       `json:"sequence"`
	Total         int       `json:"total"`
	Attempt       int       `json:"attempt"`
	MaxAttempts   int       `json:"max_attempts"`
	CreatedAt     time.Time `json:"created_at"`
	QueuedAt      time.Time `json:"queued_at"`
	StartedAt     time.Time `json:"started_at"`
	FinishedAt    time.Time `json:"finished_at"`
	UpdatedAt     time.Time `json:"updated_at"`
}

type CreateRequest struct {
	Name     string         `json:"name"`
	TaskType Type           `json:"task_type"`
	Params   map[string]any `json:"params"`
}

type Query struct {
	Status string `json:"status"`
	Limit  int    `json:"limit"`
}

type DTO struct {
	ID            string         `json:"id"`
	Name          string         `json:"name"`
	TaskType      Type           `json:"task_type"`
	Status        Status         `json:"status"`
	Progress      float64        `json:"progress"`
	Params        map[string]any `json:"params"`
	Summary       map[string]any `json:"summary"`
	ResultPath    string         `json:"result_path"`
	LogPath       string         `json:"log_path"`
	WorkerType    string         `json:"worker_type"`
	WorkerPID     int            `json:"worker_pid"`
	ExternalRunID string         `json:"external_run_id"`
	ErrorMessage  string         `json:"error_message"`
	ParentID      string         `json:"parent_id"`
	GroupRunID    string         `json:"group_run_id"`
	SubtaskKey    string         `json:"subtask_key"`
	SubtaskName   string         `json:"subtask_name"`
	Sequence      int            `json:"sequence"`
	Total         int            `json:"total"`
	Attempt       int            `json:"attempt"`
	MaxAttempts   int            `json:"max_attempts"`
	CreatedAt     string         `json:"created_at"`
	QueuedAt      string         `json:"queued_at"`
	StartedAt     string         `json:"started_at"`
	FinishedAt    string         `json:"finished_at"`
	UpdatedAt     string         `json:"updated_at"`
}
