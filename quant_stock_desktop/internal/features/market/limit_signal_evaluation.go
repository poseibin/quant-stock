package market

import "database/sql"

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

func (service *Service) ListLimitSignalEvaluationSummary() ([]LimitSignalEvaluationSummary, error) {
	if service == nil || service.repo == nil || service.repo.db == nil {
		return []LimitSignalEvaluationSummary{}, nil
	}
	return service.repo.ListLimitSignalEvaluationSummary()
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
	}
	for _, stmt := range stmts {
		if err := repo.db.ExecSchemaStatement(stmt); err != nil {
			return err
		}
	}
	return nil
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
