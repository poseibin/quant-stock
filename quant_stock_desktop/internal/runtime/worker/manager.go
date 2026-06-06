package worker

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
)

type StartRequest struct {
	PythonPath     string
	QuantStockPath string
	DataPath       string
	DBPath         string
	ConfigDBPath   string
	DBBackend      string
	DBDSN          string
	TaskID         string
	RunID          string
	LogPath        string
	Params         map[string]any
}

type Manager struct{}

func NewManager() *Manager {
	return &Manager{}
}

func (manager *Manager) Start(req StartRequest) (ProcessInfo, error) {
	if err := os.MkdirAll(filepath.Dir(req.LogPath), 0o755); err != nil {
		return ProcessInfo{}, err
	}
	logFile, err := os.OpenFile(req.LogPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		return ProcessInfo{}, err
	}

	kwargs := map[string]any{
		"run_id":            req.RunID,
		"start_date":        req.Params["start_date"],
		"end_date":          req.Params["end_date"],
		"initial_cash":      req.Params["initial_cash"],
		"rebalance_freq":    req.Params["rebalance_freq"],
		"use_signal_cache":  req.Params["use_signal_cache"],
		"exit_rules_cfg":    req.Params["exit_rules_cfg"],
		"strategies_filter": req.Params["strategies_filter"],
		"eval_name":         req.Params["eval_name"],
	}
	if kwargs["eval_name"] == nil {
		kwargs["eval_name"] = req.TaskID
	}
	if kwargs["use_signal_cache"] == nil {
		kwargs["use_signal_cache"] = true
	}
	if kwargs["exit_rules_cfg"] == nil {
		kwargs["exit_rules_cfg"] = map[string]any{}
	}

	payload, err := json.Marshal(kwargs)
	if err != nil {
		_ = logFile.Close()
		return ProcessInfo{}, err
	}

	cmd := exec.Command(req.PythonPath, "-m", "trading.execution.eval_worker", string(payload))
	cmd.Dir = req.QuantStockPath
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.Env = os.Environ()
	if req.DataPath != "" {
		cmd.Env = append(cmd.Env, "DATA_ROOT="+req.DataPath)
	}
	if req.DBPath != "" {
		cmd.Env = append(cmd.Env, "DESKTOP_DB_PATH="+req.DBPath)
	}
	if req.ConfigDBPath != "" {
		cmd.Env = append(cmd.Env, "DESKTOP_CONFIG_DB_PATH="+req.ConfigDBPath)
	}
	if req.DBBackend != "" {
		cmd.Env = append(cmd.Env, "DESKTOP_DB_BACKEND="+req.DBBackend)
	}
	if req.DBDSN != "" {
		cmd.Env = append(cmd.Env, "DESKTOP_DB_DSN="+req.DBDSN)
	}
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		_ = logFile.Close()
		return ProcessInfo{}, err
	}
	go func() {
		_ = cmd.Wait()
		_ = logFile.Close()
	}()
	return ProcessInfo{PID: cmd.Process.Pid}, nil
}

func (manager *Manager) Cancel(pid int) error {
	if pid <= 0 {
		return nil
	}
	if err := syscall.Kill(-pid, syscall.SIGTERM); err == nil {
		return nil
	}
	return syscall.Kill(pid, syscall.SIGTERM)
}
