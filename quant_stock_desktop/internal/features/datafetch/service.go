package datafetch

import (
	"context"
	"database/sql"
	"errors"
	"log"
	"sync"
	"sync/atomic"

	"quant_stock_desktop/internal/common/database"
)

type UpdateRequest struct {
	Phase     string `json:"phase"`
	StartDate string `json:"start_date"`
	Dataset   string `json:"dataset"`
}

type RunStatus struct {
	Task       string `json:"task"`
	TaskType   string `json:"task_type"`
	State      string `json:"state"`
	Idx        int    `json:"idx"`
	Total      int    `json:"total"`
	Stage      string `json:"stage"`
	Name       string `json:"name"`
	Message    string `json:"message"`
	WorkerPID  int    `json:"worker_pid"`
	StartedAt  string `json:"started_at"`
	UpdatedAt  string `json:"updated_at"`
	FinishedAt string `json:"finished_at"`
}

type Service struct {
	mu            sync.Mutex
	db            *database.DB
	dataPath      string
	running       atomic.Bool
	tokenProvider func() string
	ctx           context.Context
}

func New(db *database.DB, dataPath string, tokenProvider func() string) *Service {
	return &Service{
		db:            db,
		dataPath:      dataPath,
		tokenProvider: tokenProvider,
	}
}

func (s *Service) SetContext(ctx context.Context) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ctx = ctx
}

func (s *Service) SetDataPath(p string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.dataPath = p
}

func (s *Service) RunAsync(req UpdateRequest) error {
	if !s.running.CompareAndSwap(false, true) {
		return ErrAlreadyRunning
	}
	go func() {
		defer s.running.Store(false)
		if err := s.run(context.Background(), req); err != nil {
			log.Printf("[datafetch] run error: %v", err)
		}
	}()
	return nil
}

func (s *Service) GetStatus() (RunStatus, error) {
	if s.db == nil {
		return RunStatus{Task: statusTask, TaskType: "data_update", State: "idle"}, nil
	}
	row := s.db.Conn().QueryRow(
		`SELECT task,COALESCE(task_type,''),state,idx,total,COALESCE(stage,''),COALESCE(name,''),COALESCE(message,''),
		 COALESCE(worker_pid,0),COALESCE(started_at,''),updated_at,COALESCE(finished_at,'')
		 FROM task_run_status WHERE task=?`, statusTask)
	var r RunStatus
	err := row.Scan(&r.Task, &r.TaskType, &r.State, &r.Idx, &r.Total, &r.Stage, &r.Name,
		&r.Message, &r.WorkerPID, &r.StartedAt, &r.UpdatedAt, &r.FinishedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return RunStatus{Task: statusTask, TaskType: "data_update", State: "idle"}, nil
	}
	if err != nil {
		return RunStatus{}, err
	}
	if r.TaskType == "" {
		r.TaskType = "data_update"
	}
	return r, nil
}

// ListDatasetStatus 返回每个数据集的更新状态（前端列表用）。
func (s *Service) ListDatasetStatus() ([]DatasetStatus, error) {
	return listDatasetStatus(s.db)
}

func (s *Service) IsRunning() bool { return s.running.Load() }

func (s *Service) run(ctx context.Context, req UpdateRequest) error {
	_ = statusBegin(s.db, 0)
	statusError(s.db, "Go 数据更新通道已禁用，请使用 Python data_update_worker")
	return errors.New("go data update path is disabled")
}
