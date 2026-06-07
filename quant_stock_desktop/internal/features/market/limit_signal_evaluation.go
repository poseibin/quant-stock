package market

import (
	"database/sql"
	"strings"
)

type LimitSignalEvaluationSummary struct {
	SignalType       string  `json:"signal_type"`
	StrategyVersion  string  `json:"strategy_version"`
	ParameterKey     string  `json:"parameter_key"`
	SampleCount      int     `json:"sample_count"`
	PendingCount     int     `json:"pending_count"`
	HitRate          float64 `json:"hit_rate"`
	AvgReturn1D      float64 `json:"avg_return_1d"`
	AvgReturn3D      float64 `json:"avg_return_3d"`
	AvgReturn5D      float64 `json:"avg_return_5d"`
	AvgReturn10D     float64 `json:"avg_return_10d"`
	AvgMaxDrawdown5D float64 `json:"avg_max_drawdown_5d"`
	AvgScore         float64 `json:"avg_score"`
	Recommendation   string  `json:"recommendation"`
	ParameterHint    string  `json:"parameter_hint"`
	UpdatedAt        string  `json:"updated_at"`
}

type LimitSignalTimeMachineSlice struct {
	SignalType        string  `json:"signal_type"`
	StrategyVersion   string  `json:"strategy_version"`
	ParameterKey      string  `json:"parameter_key"`
	SignalDate        string  `json:"signal_date"`
	CandidateCount    int     `json:"candidate_count"`
	EvaluatedCount    int     `json:"evaluated_count"`
	HitRate           float64 `json:"hit_rate"`
	LimitUpHitRate    float64 `json:"limit_up_hit_rate"`
	AvgReturn1D       float64 `json:"avg_return_1d"`
	AvgReturn3D       float64 `json:"avg_return_3d"`
	AvgReturn5D       float64 `json:"avg_return_5d"`
	AvgReturn10D      float64 `json:"avg_return_10d"`
	AvgTargetReturn   float64 `json:"avg_target_return"`
	AvgMaxDrawdown5D  float64 `json:"avg_max_drawdown_5d"`
	AvgScore          float64 `json:"avg_score"`
	SliceScore        float64 `json:"slice_score"`
	MarketHeatScore   float64 `json:"market_heat_score"`
	LimitUpCount      int     `json:"limit_up_count"`
	LimitUpRatio      float64 `json:"limit_up_ratio"`
	UpRatio           float64 `json:"up_ratio"`
	HotTagsJSON       string  `json:"hot_tags_json"`
	TopIndustriesJSON string  `json:"top_industries_json"`
	Recommendation    string  `json:"recommendation"`
	SummaryJSON       string  `json:"summary_json"`
	UpdatedAt         string  `json:"updated_at"`
}

func (service *Service) ListLimitSignalEvaluationSummary() ([]LimitSignalEvaluationSummary, error) {
	if service == nil || service.repo == nil || service.repo.db == nil {
		return []LimitSignalEvaluationSummary{}, nil
	}
	return service.repo.ListLimitSignalEvaluationSummary()
}

func (service *Service) ListLimitSignalTimeMachineSlices(limit int) ([]LimitSignalTimeMachineSlice, error) {
	if service == nil || service.repo == nil || service.repo.db == nil {
		return []LimitSignalTimeMachineSlice{}, nil
	}
	return service.repo.ListLimitSignalTimeMachineSlices(limit)
}

func (repo *Repository) ensureLimitSignalEvaluationTables() error {
	stmts := []string{
		`CREATE TABLE IF NOT EXISTS market_limit_signal_predictions (
			id TEXT PRIMARY KEY,
			signal_type TEXT NOT NULL,
			strategy_version TEXT NOT NULL DEFAULT 'v1',
			parameter_key TEXT NOT NULL,
			cache_key TEXT NOT NULL,
			rank INTEGER NOT NULL DEFAULT 0,
			ts_code TEXT NOT NULL,
			name TEXT NOT NULL DEFAULT '',
			industry TEXT NOT NULL DEFAULT '',
			signal_date TEXT NOT NULL,
			signal_price REAL NOT NULL DEFAULT 0,
			score REAL NOT NULL DEFAULT 0,
			recommendation TEXT NOT NULL DEFAULT '',
			payload_json TEXT NOT NULL DEFAULT '{}',
			ret_1d REAL,
			ret_3d REAL,
			ret_5d REAL,
			ret_10d REAL,
			max_drawdown_5d REAL,
			hit_limit_up_5d INTEGER,
			target_hit INTEGER,
			outcome_json TEXT NOT NULL DEFAULT '{}',
			evaluated_at TEXT,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			UNIQUE(signal_type, parameter_key, ts_code, signal_date)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_market_limit_signal_predictions_type_date
			ON market_limit_signal_predictions(signal_type, signal_date);`,
		`CREATE TABLE IF NOT EXISTS market_limit_signal_eval_summary (
			signal_type TEXT NOT NULL,
			strategy_version TEXT NOT NULL DEFAULT 'v1',
			parameter_key TEXT NOT NULL,
			sample_count INTEGER NOT NULL DEFAULT 0,
			pending_count INTEGER NOT NULL DEFAULT 0,
			hit_rate REAL NOT NULL DEFAULT 0,
			avg_return_1d REAL NOT NULL DEFAULT 0,
			avg_return_3d REAL NOT NULL DEFAULT 0,
			avg_return_5d REAL NOT NULL DEFAULT 0,
			avg_return_10d REAL NOT NULL DEFAULT 0,
			avg_max_drawdown_5d REAL NOT NULL DEFAULT 0,
			avg_score REAL NOT NULL DEFAULT 0,
			recommendation TEXT NOT NULL DEFAULT '',
			parameter_hint TEXT NOT NULL DEFAULT '',
			updated_at TEXT NOT NULL,
			PRIMARY KEY(signal_type, strategy_version, parameter_key)
		);`,
		`CREATE TABLE IF NOT EXISTS market_limit_signal_tm_slices (
			signal_type TEXT NOT NULL,
			strategy_version TEXT NOT NULL DEFAULT 'v1',
			parameter_key TEXT NOT NULL,
			signal_date TEXT NOT NULL,
			candidate_count INTEGER NOT NULL DEFAULT 0,
			evaluated_count INTEGER NOT NULL DEFAULT 0,
			hit_rate REAL NOT NULL DEFAULT 0,
			limit_up_hit_rate REAL NOT NULL DEFAULT 0,
			avg_return_1d REAL NOT NULL DEFAULT 0,
			avg_return_3d REAL NOT NULL DEFAULT 0,
			avg_return_5d REAL NOT NULL DEFAULT 0,
			avg_return_10d REAL NOT NULL DEFAULT 0,
			avg_target_return REAL NOT NULL DEFAULT 0,
			avg_max_drawdown_5d REAL NOT NULL DEFAULT 0,
			avg_score REAL NOT NULL DEFAULT 0,
			slice_score REAL NOT NULL DEFAULT 0,
			market_heat_score REAL NOT NULL DEFAULT 0,
			limit_up_count INTEGER NOT NULL DEFAULT 0,
			limit_up_ratio REAL NOT NULL DEFAULT 0,
			up_ratio REAL NOT NULL DEFAULT 0,
			hot_tags_json TEXT NOT NULL DEFAULT '[]',
			top_industries_json TEXT NOT NULL DEFAULT '[]',
			recommendation TEXT NOT NULL DEFAULT '',
			summary_json TEXT NOT NULL DEFAULT '{}',
			updated_at TEXT NOT NULL,
			PRIMARY KEY(signal_type, strategy_version, parameter_key, signal_date)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_market_limit_signal_tm_slices_date
			ON market_limit_signal_tm_slices(signal_date DESC, slice_score DESC);`,
	}
	for _, stmt := range stmts {
		if err := repo.db.ExecSchemaStatement(stmt); err != nil {
			return err
		}
	}
	for _, column := range []struct {
		name string
		ddl  string
	}{
		{"market_heat_score", "REAL NOT NULL DEFAULT 0"},
		{"limit_up_count", "INTEGER NOT NULL DEFAULT 0"},
		{"limit_up_ratio", "REAL NOT NULL DEFAULT 0"},
		{"up_ratio", "REAL NOT NULL DEFAULT 0"},
		{"hot_tags_json", "TEXT NOT NULL DEFAULT '[]'"},
		{"top_industries_json", "TEXT NOT NULL DEFAULT '[]'"},
	} {
		if err := repo.ensureLimitSignalSliceColumn(column.name, column.ddl); err != nil {
			return err
		}
	}
	return nil
}

func (repo *Repository) ensureLimitSignalSliceColumn(name string, ddl string) error {
	var probe int
	err := repo.db.Conn().QueryRow("SELECT COUNT(*) FROM market_limit_signal_tm_slices WHERE 1 = 0 AND " + name + " IS NULL").Scan(&probe)
	if err == nil {
		return nil
	}
	if repo.db.IsMySQL() {
		ddl = strings.ReplaceAll(ddl, "INTEGER", "BIGINT")
		ddl = strings.ReplaceAll(ddl, "REAL", "DOUBLE")
		if strings.HasPrefix(strings.ToUpper(ddl), "TEXT ") {
			ddl = "LONGTEXT"
		}
	}
	_, err = repo.db.Conn().Exec("ALTER TABLE market_limit_signal_tm_slices ADD COLUMN " + name + " " + ddl)
	if err != nil {
		var probeAfter int
		if probeErr := repo.db.Conn().QueryRow("SELECT COUNT(*) FROM market_limit_signal_tm_slices WHERE 1 = 0 AND " + name + " IS NULL").Scan(&probeAfter); probeErr == nil {
			return nil
		}
		return err
	}
	return nil
}

func (repo *Repository) ListLimitSignalTimeMachineSlices(limit int) ([]LimitSignalTimeMachineSlice, error) {
	if err := repo.ensureLimitSignalEvaluationTables(); err != nil {
		return nil, err
	}
	if limit <= 0 || limit > 300 {
		limit = 80
	}
	rows, err := repo.db.Conn().Query(
		`SELECT signal_type, strategy_version, parameter_key, signal_date,
			candidate_count, evaluated_count, hit_rate, limit_up_hit_rate,
			avg_return_1d, avg_return_3d, avg_return_5d, avg_return_10d,
			avg_target_return, avg_max_drawdown_5d, avg_score, slice_score,
			COALESCE(market_heat_score, 0), COALESCE(limit_up_count, 0), COALESCE(limit_up_ratio, 0), COALESCE(up_ratio, 0),
			COALESCE(hot_tags_json, '[]'), COALESCE(top_industries_json, '[]'),
			recommendation, summary_json, updated_at
		FROM market_limit_signal_tm_slices
		ORDER BY signal_date DESC, slice_score DESC
		LIMIT ?`,
		limit,
	)
	if err != nil {
		if err == sql.ErrNoRows {
			return []LimitSignalTimeMachineSlice{}, nil
		}
		return nil, err
	}
	defer rows.Close()
	out := make([]LimitSignalTimeMachineSlice, 0)
	for rows.Next() {
		var item LimitSignalTimeMachineSlice
		if err := rows.Scan(
			&item.SignalType,
			&item.StrategyVersion,
			&item.ParameterKey,
			&item.SignalDate,
			&item.CandidateCount,
			&item.EvaluatedCount,
			&item.HitRate,
			&item.LimitUpHitRate,
			&item.AvgReturn1D,
			&item.AvgReturn3D,
			&item.AvgReturn5D,
			&item.AvgReturn10D,
			&item.AvgTargetReturn,
			&item.AvgMaxDrawdown5D,
			&item.AvgScore,
			&item.SliceScore,
			&item.MarketHeatScore,
			&item.LimitUpCount,
			&item.LimitUpRatio,
			&item.UpRatio,
			&item.HotTagsJSON,
			&item.TopIndustriesJSON,
			&item.Recommendation,
			&item.SummaryJSON,
			&item.UpdatedAt,
		); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}

func (repo *Repository) ListLimitSignalEvaluationSummary() ([]LimitSignalEvaluationSummary, error) {
	if err := repo.ensureLimitSignalEvaluationTables(); err != nil {
		return nil, err
	}
	rows, err := repo.db.Conn().Query(
		`SELECT signal_type, strategy_version, parameter_key, sample_count, pending_count,
			hit_rate, avg_return_1d, avg_return_3d, avg_return_5d, avg_return_10d,
			avg_max_drawdown_5d, avg_score, recommendation, parameter_hint, updated_at
		FROM market_limit_signal_eval_summary
		ORDER BY updated_at DESC, signal_type ASC`,
	)
	if err != nil {
		if err == sql.ErrNoRows {
			return []LimitSignalEvaluationSummary{}, nil
		}
		return nil, err
	}
	defer rows.Close()
	out := make([]LimitSignalEvaluationSummary, 0)
	for rows.Next() {
		var item LimitSignalEvaluationSummary
		if err := rows.Scan(
			&item.SignalType,
			&item.StrategyVersion,
			&item.ParameterKey,
			&item.SampleCount,
			&item.PendingCount,
			&item.HitRate,
			&item.AvgReturn1D,
			&item.AvgReturn3D,
			&item.AvgReturn5D,
			&item.AvgReturn10D,
			&item.AvgMaxDrawdown5D,
			&item.AvgScore,
			&item.Recommendation,
			&item.ParameterHint,
			&item.UpdatedAt,
		); err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, rows.Err()
}
