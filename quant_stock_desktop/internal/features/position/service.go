package position

import (
	"bufio"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"quant_stock_desktop/internal/features/market"
)

const initialCash = 500000.0
const lotSize = 100

type Service struct {
	marketService *market.Service
	db            *sql.DB
	signalMu      sync.Mutex
	signalRunning bool
}

func NewService(marketService *market.Service, db *sql.DB) *Service {
	return &Service{marketService: marketService, db: db}
}

func (service *Service) tryAcquireSignal() bool {
	service.signalMu.Lock()
	defer service.signalMu.Unlock()
	if service.signalRunning {
		return false
	}
	service.signalRunning = true
	return true
}

func (service *Service) releaseSignal() {
	service.signalMu.Lock()
	service.signalRunning = false
	service.signalMu.Unlock()
}

func (service *Service) GetSummary(dataPath string) (Summary, error) {
	if service.db == nil {
		return Summary{}, errors.New("database is not initialized")
	}
	row := service.db.QueryRow(`SELECT initial_cash, current_cash, market_value, total_assets,
	    COALESCE(total_cost,0), total_pnl, today_pnl, COALESCE(today_pct,0),
	    COALESCE(unrealized_pnl,0), COALESCE(unrealized_pct,0),
	    COALESCE(realized_pnl,0), COALESCE(cum_return,0), COALESCE(n_closed,0),
	    COALESCE(updated_at,'') FROM pool_summary WHERE id = 1`)
	var s Summary
	if err := row.Scan(&s.InitialCash, &s.Cash, &s.MarketValue, &s.TotalAssets,
		&s.TotalCost, &s.TotalPnL, &s.TodayPnL, &s.TodayPct,
		&s.UnrealizedPnL, &s.UnrealizedPct, &s.RealizedPnL, &s.CumReturn, &s.NClosed,
		&s.UpdatedAt); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return Summary{InitialCash: initialCash, Cash: initialCash, TotalAssets: initialCash, Positions: []Position{}}, nil
		}
		return Summary{}, err
	}
	positions, err := service.GetHoldings()
	if err != nil {
		return Summary{}, err
	}
	s.Positions = positions
	s.NHoldings = len(positions)
	return s, nil
}

func (service *Service) GetHoldings() ([]Position, error) {
	if service.db == nil {
		return nil, errors.New("database is not initialized")
	}
	rows, err := service.db.Query(`SELECT ts_code, COALESCE(name,''), COALESCE(industry,''),
	    shares, avg_cost, last_price, market_value, weight, pnl, pnl_pct,
	    COALESCE(open_date,''), COALESCE(updated_at,'')
	    FROM pool_holdings WHERE shares > 0 ORDER BY weight DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]Position, 0)
	for rows.Next() {
		var p Position
		if err := rows.Scan(&p.TSCode, &p.Name, &p.Industry, &p.Shares, &p.AvgCost,
			&p.Price, &p.MarketValue, &p.Weight, &p.UnrealizedPnL, &p.UnrealizedPct,
			&p.FirstEntryDate, &p.LastActionDate); err != nil {
			return nil, err
		}
		p.Cost = p.AvgCost * float64(p.Shares)
		out = append(out, p)
	}
	return out, rows.Err()
}

func (service *Service) ConfirmTrades(dataPath string, trades []TradeRequest) (Summary, error) {
	if len(trades) == 0 {
		return service.GetSummary(dataPath)
	}
	tradeData := make([]map[string]any, 0, len(trades))
	for _, t := range trades {
		side := strings.ToLower(strings.TrimSpace(t.Action))
		if side != "buy" && side != "sell" {
			return Summary{}, fmt.Errorf("invalid trade action: %s", t.Action)
		}
		tradeData = append(tradeData, map[string]any{
			"ts_code":    t.TSCode,
			"side":       side,
			"shares":     t.Shares,
			"price":      t.Price,
			"trade_date": t.Date,
		})
	}
	tmpFile, err := os.CreateTemp("", "trades-*.json")
	if err != nil {
		return Summary{}, err
	}
	defer os.Remove(tmpFile.Name())
	if err := json.NewEncoder(tmpFile).Encode(tradeData); err != nil {
		tmpFile.Close()
		return Summary{}, err
	}
	tmpFile.Close()

	projectRoot := quantStockRoot(dataPath)
	scriptPath := filepath.Join(projectRoot, "scripts", "pool_confirm.py")
	python := quantCorePython(projectRoot)
	cmd := exec.Command(python, "-u", scriptPath, "--trades-json", tmpFile.Name())
	cmd.Dir = projectRoot
	cmd.Env = quantCoreEnv(dataPath, GenerateSignalRequest{})
	var stdout, stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		return Summary{}, fmt.Errorf("pool_confirm failed: %v stderr=%s", err, stderr.String())
	}
	return service.GetSummary(dataPath)
}

func (service *Service) GetRecommendation(dataPath string) (Recommendation, error) {
	if service.db == nil {
		return Recommendation{}, errors.New("database is not initialized")
	}
	row := service.db.QueryRow(`SELECT payload_json FROM daily_recommendation ORDER BY date DESC LIMIT 1`)
	var payload string
	if err := row.Scan(&payload); err != nil {
		return Recommendation{}, err
	}
	var rec Recommendation
	if err := json.Unmarshal([]byte(payload), &rec); err != nil {
		return Recommendation{}, err
	}
	if rec.Date != "" {
		var count int
		err := service.db.QueryRow(`SELECT COUNT(*) FROM pool_trades WHERE trade_date = ?`, rec.Date).Scan(&count)
		if err != nil {
			return Recommendation{}, err
		}
		rec.Rebalanced = count > 0
		rec.RebalanceTrades = count
	}
	return rec, nil
}

func (service *Service) GetRunStatus(task string) (RunStatus, error) {
	if service.db == nil {
		return RunStatus{Task: task, State: "idle"}, nil
	}
	row := service.db.QueryRow(
		`SELECT task, state, idx, total, COALESCE(stage,''), COALESCE(name,''), COALESCE(message,''),
		COALESCE(started_at,''), updated_at, COALESCE(finished_at,'') FROM py_run_status WHERE task = ?`,
		task,
	)
	var s RunStatus
	if err := row.Scan(&s.Task, &s.State, &s.Idx, &s.Total, &s.Stage, &s.Name, &s.Message, &s.StartedAt, &s.UpdatedAt, &s.FinishedAt); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return RunStatus{Task: task, State: "idle"}, nil
		}
		return RunStatus{}, err
	}
	return s, nil
}

func (service *Service) GenerateSignal(dataPath string, req GenerateSignalRequest) (GenerateSignalResponse, error) {
	return service.GenerateSignalWithProgress(dataPath, req, nil)
}

func (service *Service) GenerateSignalWithProgress(dataPath string, req GenerateSignalRequest, onProgress func(ProgressEvent)) (GenerateSignalResponse, error) {
	if !service.tryAcquireSignal() {
		return GenerateSignalResponse{Output: "signal generation already running", Success: false}, errors.New("signal generation already running")
	}
	defer service.releaseSignal()

	projectRoot := quantStockRoot(dataPath)
	if projectRoot == "" {
		return GenerateSignalResponse{}, errors.New("quant_stock project not found")
	}
	pythonPath := quantCorePython(projectRoot)
	logPath := filepath.Join(dataPath, "logs", "daily_signal_desktop.log")
	logDesktopSignal(logPath, "start GenerateSignalWithProgress dataPath=%s dbPath=%s projectRoot=%s python=%s date=%s initialCash=%.2f rebalanceFreq=%d",
		dataPath, filepath.Join(dataPath, "meta.db"), projectRoot, pythonPath, req.Date, req.InitialCash, req.RebalanceFreq)
	args := []string{"scripts/daily_signal.py", "--json-only"}
	if onProgress != nil {
		args = append(args, "--progress")
	}
	if strings.TrimSpace(req.Date) != "" {
		args = append(args, "--date", strings.TrimSpace(req.Date))
	}
	cmd := exec.Command(pythonPath, args...)
	cmd.Dir = projectRoot
	cmd.Env = append(os.Environ(), quantCoreEnv(dataPath, req)...)
	logDesktopSignal(logPath, "exec args=%s cwd=%s env DATA_ROOT=%s DESKTOP_DB_PATH=%s INITIAL_CASH=%.2f REBALANCE_FREQ=%d",
		strings.Join(args, " "), cmd.Dir, dataPath, filepath.Join(dataPath, "meta.db"), req.InitialCash, req.RebalanceFreq)
	applyLowPriority(cmd)

	stdoutPipe, err := cmd.StdoutPipe()
	if err != nil {
		return GenerateSignalResponse{}, err
	}
	stderrPipe, err := cmd.StderrPipe()
	if err != nil {
		return GenerateSignalResponse{}, err
	}
	if err := cmd.Start(); err != nil {
		return GenerateSignalResponse{}, err
	}
	if cmd.Process != nil {
		lowerPriorityAfterStart(cmd.Process.Pid)
	}

	stderrBuf := strings.Builder{}
	stderrDone := make(chan struct{})
	go func() {
		defer close(stderrDone)
		scanner := bufio.NewScanner(stderrPipe)
		scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
		for scanner.Scan() {
			line := scanner.Text()
			stderrBuf.WriteString(line)
			stderrBuf.WriteByte('\n')
			if onProgress != nil && strings.HasPrefix(line, "PROGRESS ") {
				var ev ProgressEvent
				if err := json.Unmarshal([]byte(strings.TrimPrefix(line, "PROGRESS ")), &ev); err == nil {
					onProgress(ev)
				}
			}
		}
	}()

	stdoutBytes, readErr := io.ReadAll(stdoutPipe)
	waitErr := cmd.Wait()
	<-stderrDone

	output := string(stdoutBytes)
	if waitErr != nil {
		combined := stderrBuf.String() + output
		logDesktopSignal(logPath, "python failed waitErr=%v stderr=%s stdout_prefix=%s", waitErr, tailString(stderrBuf.String(), 4000), headString(output, 1000))
		return GenerateSignalResponse{Output: combined, Success: false}, waitErr
	}
	if readErr != nil {
		logDesktopSignal(logPath, "python stdout read failed err=%v stdout_prefix=%s", readErr, headString(output, 1000))
		return GenerateSignalResponse{Output: output, Success: false}, readErr
	}
	logDesktopSignal(logPath, "python finished stdout_bytes=%d stderr_tail=%s", len(stdoutBytes), tailString(stderrBuf.String(), 2000))
	var head struct {
		Date string `json:"date"`
	}
	if err := json.Unmarshal(stdoutBytes, &head); err != nil {
		logDesktopSignal(logPath, "json unmarshal failed err=%v stdout_prefix=%s", err, headString(output, 2000))
		return GenerateSignalResponse{Output: output, Success: false}, err
	}
	logDesktopSignal(logPath, "signal generated date=%s output_bytes=%d", head.Date, len(stdoutBytes))
	return GenerateSignalResponse{Date: head.Date, Output: output, Success: true}, nil
}

func quantCoreEnv(dataPath string, req GenerateSignalRequest) []string {
	initialCashValue := req.InitialCash
	if initialCashValue <= 0 {
		initialCashValue = initialCash
	}
	rebalanceFreq := req.RebalanceFreq
	if rebalanceFreq <= 0 {
		rebalanceFreq = 5
	}
	dbPath := filepath.Join(dataPath, "meta.db")
	return []string{
		"DATA_ROOT=" + dataPath,
		"DESKTOP_DB_PATH=" + dbPath,
		"DESKTOP_CONFIG_DB_PATH=" + dbPath,
		fmt.Sprintf("INITIAL_CASH=%.2f", initialCashValue),
		fmt.Sprintf("REBALANCE_FREQ=%d", rebalanceFreq),
	}
}

func quantStockRoot(dataPath string) string {
	parent := filepath.Dir(dataPath)
	grandparent := filepath.Dir(parent)
	candidates := []string{
		filepath.Join(parent, "quant_stock_core"),
		filepath.Join(grandparent, "quant_stock_core"),
		filepath.Join(parent, "quant_core"),
	}
	for _, candidate := range candidates {
		if info, err := os.Stat(filepath.Join(candidate, "scripts", "daily_signal.py")); err == nil && !info.IsDir() {
			return candidate
		}
	}
	return ""
}

func quantCorePython(projectRoot string) string {
	if w := bundledWorkerPath(); w != "" {
		return w
	}
	parent := filepath.Dir(projectRoot) // .../lh
	candidates := []string{
		filepath.Join(projectRoot, ".venv", "bin", "python"),
		filepath.Join(parent, ".venv", "bin", "python"),
	}
	for _, candidate := range candidates {
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate
		}
	}
	return "python3"
}

func bundledWorkerPath() string {
	exe, err := os.Executable()
	if err != nil {
		return ""
	}
	exe, err = filepath.EvalSymlinks(exe)
	if err != nil {
		return ""
	}
	macosDir := filepath.Dir(exe)
	contentsDir := filepath.Dir(macosDir)
	candidate := filepath.Join(contentsDir, "Resources", "quant_worker", "quant_worker")
	if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
		return candidate
	}
	return ""
}

func logDesktopSignal(logPath string, format string, args ...any) {
	if strings.TrimSpace(logPath) == "" {
		return
	}
	if err := os.MkdirAll(filepath.Dir(logPath), 0o755); err != nil {
		return
	}
	line := fmt.Sprintf("%s ", time.Now().Format("2006-01-02T15:04:05")) + fmt.Sprintf(format, args...) + "\n"
	file, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return
	}
	defer file.Close()
	_, _ = file.WriteString(line)
}

func headString(value string, limit int) string {
	if len(value) <= limit {
		return value
	}
	return value[:limit]
}

func tailString(value string, limit int) string {
	if len(value) <= limit {
		return value
	}
	return value[len(value)-limit:]
}
