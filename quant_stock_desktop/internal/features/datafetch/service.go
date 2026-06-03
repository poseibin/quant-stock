package datafetch

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"log"
	"strings"
	"sync"
	"sync/atomic"
)

type UpdateRequest struct {
	Phase     string `json:"phase"`
	StartDate string `json:"start_date"`
	Dataset   string `json:"dataset"`
}

type RunStatus struct {
	Task       string `json:"task"`
	State      string `json:"state"`
	Idx        int    `json:"idx"`
	Total      int    `json:"total"`
	Stage      string `json:"stage"`
	Name       string `json:"name"`
	Message    string `json:"message"`
	StartedAt  string `json:"started_at"`
	UpdatedAt  string `json:"updated_at"`
	FinishedAt string `json:"finished_at"`
}

type Service struct {
	mu            sync.Mutex
	db            *sql.DB
	dataPath      string
	running       atomic.Bool
	tokenProvider func() string
	ctx           context.Context
}

func New(db *sql.DB, dataPath string, tokenProvider func() string) *Service {
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
		return RunStatus{Task: statusTask, State: "idle"}, nil
	}
	row := s.db.QueryRow(
		`SELECT task,state,idx,total,COALESCE(stage,''),COALESCE(name,''),COALESCE(message,''),
		 COALESCE(started_at,''),updated_at,COALESCE(finished_at,'')
		 FROM py_run_status WHERE task=?`, statusTask)
	var r RunStatus
	err := row.Scan(&r.Task, &r.State, &r.Idx, &r.Total, &r.Stage, &r.Name,
		&r.Message, &r.StartedAt, &r.UpdatedAt, &r.FinishedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return RunStatus{Task: statusTask, State: "idle"}, nil
	}
	if err != nil {
		return RunStatus{}, err
	}
	return r, nil
}

// ListDatasetStatus 返回每个数据集的更新状态（前端列表用）。
func (s *Service) ListDatasetStatus() ([]DatasetStatus, error) {
	return listDatasetStatus(s.db)
}

func (s *Service) IsRunning() bool { return s.running.Load() }

func (s *Service) run(ctx context.Context, req UpdateRequest) error {
	token := ""
	if s.tokenProvider != nil {
		token = strings.TrimSpace(s.tokenProvider())
	}
	if token == "" {
		_ = statusBegin(s.db, 0)
		statusError(s.db, "Tushare Token 未设置，请在设置页填写")
		return errors.New("tushare token is empty")
	}

	s.mu.Lock()
	dataPath := s.dataPath
	s.mu.Unlock()

	if strings.TrimSpace(dataPath) == "" {
		_ = statusBegin(s.db, 0)
		statusError(s.db, "数据路径未设置")
		return errors.New("data path is empty")
	}

	phase := ParsePhase(req.Phase)
	jobs := JobsForPhase(phase)
	if dataset := strings.TrimSpace(req.Dataset); dataset != "" {
		job, ok := JobForDataset(dataset)
		if !ok {
			_ = statusBegin(s.db, 0)
			statusError(s.db, fmt.Sprintf("未知数据集: %s", dataset))
			return fmt.Errorf("unknown dataset: %s", dataset)
		}
		jobs = []JobEntry{job}
	}
	if err := statusBegin(s.db, len(jobs)); err != nil {
		return err
	}
	datasetMarkPending(s.db, jobs)

	client := NewTushareClient(token)
	var failed []string

	for i, j := range jobs {
		select {
		case <-ctx.Done():
			statusError(s.db, ctx.Err().Error())
			datasetFailed(s.db, j.Name, ctx.Err().Error(), 0)
			return ctx.Err()
		default:
		}

		statusProgress(s.db, i, len(jobs), j.Name, j.Name, "running")
		datasetBegin(s.db, j.Name, j.Category)

		jc := &JobContext{
			Ctx:       ctx,
			Client:    client,
			DataPath:  dataPath,
			StartDate: strings.TrimSpace(req.StartDate),
			Progress: func(stage string, done, total int, extra string) {
				msg := fmt.Sprintf("%d/%d %s", done, total, extra)
				statusProgress(s.db, i, len(jobs), j.Name, stage, msg)
				datasetProgress(s.db, j.Name, done, total, extra)
			},
		}

		n, err := j.Fn(jc)
		if err != nil {
			log.Printf("[datafetch] %s failed: %v", j.Name, err)
			failed = append(failed, fmt.Sprintf("%s: %v", j.Name, err))
			statusProgress(s.db, i+1, len(jobs), j.Name, j.Name, fmt.Sprintf("failed: %v", err))
			datasetFailed(s.db, j.Name, err.Error(), n)
			continue
		}
		statusProgress(s.db, i+1, len(jobs), j.Name, j.Name, fmt.Sprintf("done rows=%d", n))
		datasetSuccess(s.db, j.Name, n, fmt.Sprintf("done rows=%d", n))
	}

	if len(failed) > 0 {
		errMsg := strings.Join(failed, "; ")
		statusError(s.db, errMsg)
		return fmt.Errorf("%d jobs failed", len(failed))
	}

	statusDone(s.db, fmt.Sprintf("%d 个任务完成", len(jobs)))
	return nil
}
