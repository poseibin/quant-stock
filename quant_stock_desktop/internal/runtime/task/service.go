package task

import (
	"encoding/json"
	"strings"
	"time"
)

type Service struct {
	repo *Repository
}

func NewService(repo *Repository) *Service {
	return &Service{repo: repo}
}

func (service *Service) Repository() *Repository {
	return service.repo
}

func (service *Service) Create(req CreateRequest) (DTO, error) {
	if req.TaskType == "" {
		req.TaskType = TypeEvaluationTimeMachine
	}
	name := strings.TrimSpace(req.Name)
	if name == "" {
		name = "未命名评估"
	}
	paramsData, err := json.Marshal(req.Params)
	if err != nil {
		return DTO{}, err
	}
	now := time.Now()
	task := Task{
		ID:            NewID(),
		Name:          name,
		TaskType:      req.TaskType,
		Status:        StatusCreated,
		Progress:      0,
		ParamsJSON:    string(paramsData),
		WorkerType:    "python",
		ExternalRunID: NewRunID(req),
		CreatedAt:     now,
		UpdatedAt:     now,
	}
	if err := service.repo.Create(task); err != nil {
		return DTO{}, err
	}
	return ToDTO(task), nil
}

func (service *Service) Get(id string) (DTO, error) {
	task, err := service.repo.Get(id)
	if err != nil {
		return DTO{}, err
	}
	return ToDTO(task), nil
}

func (service *Service) List(query Query) ([]DTO, error) {
	tasks, err := service.repo.List(query)
	if err != nil {
		return nil, err
	}
	items := make([]DTO, 0, len(tasks))
	for _, task := range tasks {
		items = append(items, ToDTO(task))
	}
	return items, nil
}

func (service *Service) Delete(id string) error {
	return service.repo.Delete(id)
}

func ToDTO(task Task) DTO {
	return DTO{
		ID:            task.ID,
		Name:          task.Name,
		TaskType:      task.TaskType,
		Status:        task.Status,
		Progress:      task.Progress,
		Params:        decodeMap(task.ParamsJSON),
		Summary:       decodeMap(task.SummaryJSON),
		ResultPath:    task.ResultPath,
		LogPath:       task.LogPath,
		WorkerType:    task.WorkerType,
		WorkerPID:     task.WorkerPID,
		ExternalRunID: task.ExternalRunID,
		ErrorMessage:  task.ErrorMessage,
		CreatedAt:     formatTime(task.CreatedAt),
		QueuedAt:      formatTime(task.QueuedAt),
		StartedAt:     formatTime(task.StartedAt),
		FinishedAt:    formatTime(task.FinishedAt),
		UpdatedAt:     formatTime(task.UpdatedAt),
	}
}

func decodeMap(value string) map[string]any {
	out := make(map[string]any)
	if value == "" {
		return out
	}
	_ = json.Unmarshal([]byte(value), &out)
	return out
}
