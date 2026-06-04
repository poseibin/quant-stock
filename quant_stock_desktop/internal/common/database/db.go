package database

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	_ "modernc.org/sqlite"
)

type DB struct {
	conn *sql.DB
}

type migration struct {
	version int
	name    string
	up      func(*DB) error
}

func Open(path string) (*DB, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	conn, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	conn.SetMaxOpenConns(1)
	conn.SetMaxIdleConns(1)
	conn.SetConnMaxLifetime(0)
	for _, pragma := range []string{
		"PRAGMA busy_timeout=30000",
		"PRAGMA journal_mode=WAL",
		"PRAGMA foreign_keys=ON",
	} {
		if _, err := conn.Exec(pragma); err != nil {
			_ = conn.Close()
			return nil, fmt.Errorf("%s: %w", pragma, err)
		}
	}
	db := &DB{conn: conn}
	if err := db.Migrate(); err != nil {
		_ = conn.Close()
		return nil, err
	}
	return db, nil
}

func (db *DB) Conn() *sql.DB {
	return db.conn
}

func (db *DB) Close() error {
	if db == nil || db.conn == nil {
		return nil
	}
	return db.conn.Close()
}

func (db *DB) Migrate() error {
	statements := []string{
		`CREATE TABLE IF NOT EXISTS app_settings (
			key TEXT PRIMARY KEY,
			value TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE TABLE IF NOT EXISTS strategy_settings_versions (
			strategy TEXT NOT NULL,
			version INTEGER NOT NULL,
			label TEXT NOT NULL DEFAULT '',
			config_json TEXT NOT NULL,
			is_active INTEGER NOT NULL DEFAULT 0,
			promotion_status TEXT NOT NULL DEFAULT 'research',
			validation_json TEXT NOT NULL DEFAULT '{}',
			source TEXT NOT NULL DEFAULT '',
			note TEXT NOT NULL DEFAULT '',
			created_at TEXT NOT NULL,
			activated_at TEXT NOT NULL DEFAULT '',
			PRIMARY KEY(strategy, version)
		);`,
		`CREATE UNIQUE INDEX IF NOT EXISTS idx_strategy_settings_versions_active
			ON strategy_settings_versions(strategy)
			WHERE is_active = 1;`,
		`CREATE INDEX IF NOT EXISTS idx_strategy_settings_versions_strategy_version
			ON strategy_settings_versions(strategy, version DESC);`,
		`CREATE TABLE IF NOT EXISTS evaluation_tasks (
			id TEXT PRIMARY KEY,
			name TEXT NOT NULL,
			task_type TEXT NOT NULL,
			status TEXT NOT NULL,
			progress REAL NOT NULL DEFAULT 0,
			params_json TEXT NOT NULL,
			summary_json TEXT,
			result_path TEXT,
			log_path TEXT,
			worker_type TEXT NOT NULL DEFAULT 'python',
			worker_pid INTEGER,
			external_run_id TEXT,
			error_message TEXT,
			parent_id TEXT,
			group_run_id TEXT,
			subtask_key TEXT,
			subtask_name TEXT,
			sequence INTEGER NOT NULL DEFAULT 0,
			total INTEGER NOT NULL DEFAULT 0,
			attempt INTEGER NOT NULL DEFAULT 0,
			max_attempts INTEGER NOT NULL DEFAULT 1,
			created_at TEXT NOT NULL,
			queued_at TEXT,
			started_at TEXT,
			finished_at TEXT,
			updated_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_evaluation_tasks_status ON evaluation_tasks(status);`,
		`CREATE INDEX IF NOT EXISTS idx_evaluation_tasks_type ON evaluation_tasks(task_type);`,
		`CREATE INDEX IF NOT EXISTS idx_evaluation_tasks_created_at ON evaluation_tasks(created_at);`,
		`CREATE INDEX IF NOT EXISTS idx_evaluation_tasks_external_run_id ON evaluation_tasks(external_run_id);`,
		`CREATE TABLE IF NOT EXISTS time_machine_snapshots (
			run_id TEXT NOT NULL,
			trade_date TEXT NOT NULL,
			cash REAL NOT NULL DEFAULT 0,
			market_value REAL NOT NULL DEFAULT 0,
			equity REAL NOT NULL DEFAULT 0,
			n_holdings INTEGER NOT NULL DEFAULT 0,
			unrealized_pnl REAL NOT NULL DEFAULT 0,
			realized_pnl REAL NOT NULL DEFAULT 0,
			cum_return REAL NOT NULL DEFAULT 0,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(run_id, trade_date)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_time_machine_snapshots_date ON time_machine_snapshots(run_id, trade_date);`,
		`CREATE TABLE IF NOT EXISTS time_machine_trades (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			run_id TEXT NOT NULL,
			trade_date TEXT NOT NULL,
			ts_code TEXT NOT NULL,
			name TEXT NOT NULL DEFAULT '',
			action TEXT NOT NULL,
			shares INTEGER NOT NULL DEFAULT 0,
			price REAL NOT NULL DEFAULT 0,
			amount REAL NOT NULL DEFAULT 0,
			hold_days INTEGER NOT NULL DEFAULT 0,
			realized_pnl REAL NOT NULL DEFAULT 0,
			exit_reason TEXT NOT NULL DEFAULT '',
			exec_date TEXT NOT NULL DEFAULT '',
			is_new INTEGER NOT NULL DEFAULT 0,
			created_at TEXT NOT NULL
		);`,
		`CREATE UNIQUE INDEX IF NOT EXISTS idx_time_machine_trades_unique ON time_machine_trades(run_id, trade_date, ts_code, action, shares, price, amount, exit_reason);`,
		`CREATE INDEX IF NOT EXISTS idx_time_machine_trades_run_date ON time_machine_trades(run_id, trade_date);`,
		`CREATE TABLE IF NOT EXISTS time_machine_positions (
			run_id TEXT NOT NULL,
			trade_date TEXT NOT NULL,
			ts_code TEXT NOT NULL,
			name TEXT NOT NULL DEFAULT '',
			shares INTEGER NOT NULL DEFAULT 0,
			avg_cost REAL NOT NULL DEFAULT 0,
			price REAL NOT NULL DEFAULT 0,
			market_value REAL NOT NULL DEFAULT 0,
			unrealized_pnl REAL NOT NULL DEFAULT 0,
			unrealized_pct REAL NOT NULL DEFAULT 0,
			today_pnl REAL NOT NULL DEFAULT 0,
			today_pct REAL NOT NULL DEFAULT 0,
			weight REAL NOT NULL DEFAULT 0,
			hold_days INTEGER NOT NULL DEFAULT 0,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(run_id, trade_date, ts_code)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_time_machine_positions_run_date ON time_machine_positions(run_id, trade_date);`,
		`CREATE TABLE IF NOT EXISTS market_data_files (
			id TEXT PRIMARY KEY,
			data_type TEXT NOT NULL,
			partition_name TEXT NOT NULL,
			file_path TEXT NOT NULL,
			row_count INTEGER NOT NULL DEFAULT 0,
			file_size INTEGER NOT NULL DEFAULT 0,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE UNIQUE INDEX IF NOT EXISTS idx_market_data_files_path ON market_data_files(file_path);`,
		`CREATE INDEX IF NOT EXISTS idx_market_data_files_type ON market_data_files(data_type);`,
		`CREATE TABLE IF NOT EXISTS limit_breakout_cache (
			cache_key TEXT NOT NULL,
			rank INTEGER NOT NULL DEFAULT 0,
			ts_code TEXT NOT NULL,
			latest_date TEXT NOT NULL DEFAULT '',
			score REAL NOT NULL DEFAULT 0,
			payload_json TEXT NOT NULL,
			generated_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(cache_key, ts_code)
		);`,
		`CREATE TABLE IF NOT EXISTS limit_breakout_cache_meta (
			cache_key TEXT PRIMARY KEY,
			item_count INTEGER NOT NULL DEFAULT 0,
			generated_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_limit_breakout_cache_rank ON limit_breakout_cache(cache_key, rank);`,
		`CREATE INDEX IF NOT EXISTS idx_limit_breakout_cache_date ON limit_breakout_cache(latest_date);`,
		`CREATE TABLE IF NOT EXISTS limit_up_momentum_cache (
			cache_key TEXT NOT NULL,
			rank INTEGER NOT NULL DEFAULT 0,
			ts_code TEXT NOT NULL,
			trade_date TEXT NOT NULL DEFAULT '',
			score REAL NOT NULL DEFAULT 0,
			payload_json TEXT NOT NULL,
			generated_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(cache_key, ts_code)
		);`,
		`CREATE TABLE IF NOT EXISTS limit_up_momentum_cache_meta (
			cache_key TEXT PRIMARY KEY,
			item_count INTEGER NOT NULL DEFAULT 0,
			generated_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_limit_up_momentum_cache_rank ON limit_up_momentum_cache(cache_key, rank);`,
		`CREATE INDEX IF NOT EXISTS idx_limit_up_momentum_cache_date ON limit_up_momentum_cache(trade_date);`,
		`CREATE TABLE IF NOT EXISTS daily_recommendation (
			date TEXT PRIMARY KEY,
			generated_at TEXT NOT NULL,
			payload_json TEXT NOT NULL,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_daily_recommendation_date ON daily_recommendation(date);`,
		`CREATE TABLE IF NOT EXISTS strategy_evaluation (
			run_id TEXT NOT NULL,
			strategy TEXT NOT NULL,
			label TEXT NOT NULL DEFAULT '',
			enabled INTEGER NOT NULL DEFAULT 0,
			status TEXT NOT NULL DEFAULT '',
			admission TEXT NOT NULL DEFAULT '',
			admission_score REAL,
			reason TEXT NOT NULL DEFAULT '',
			start_date TEXT NOT NULL,
			end_date TEXT NOT NULL,
			benchmark TEXT NOT NULL DEFAULT '',
			baseline TEXT NOT NULL DEFAULT '',
			total_return REAL,
			annual_return REAL,
			annual_volatility REAL,
			sharpe REAL,
			max_drawdown REAL,
			calmar REAL,
			win_rate REAL,
			n_days INTEGER,
			month_count INTEGER,
			monthly_win_rate REAL,
			worst_month_return REAL,
			positive_3m_rate REAL,
			avg_turnover REAL,
			avg_holdings REAL,
			avg_total_mv REAL,
			avg_amount REAL,
			overlap_with_baseline REAL,
			corr_with_baseline REAL,
			return_score REAL,
			drawdown_score REAL,
			risk_adjusted_score REAL,
			cost_score REAL,
			capacity_score REAL,
			stability_score REAL,
			independence_score REAL,
			strategy_version INTEGER,
			strategy_version_mode TEXT,
			error TEXT NOT NULL DEFAULT '',
			generated_at TEXT NOT NULL,
			payload_json TEXT NOT NULL,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(run_id, strategy)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_run ON strategy_evaluation(run_id);`,
		`CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_date ON strategy_evaluation(start_date, end_date);`,
		`CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_strategy ON strategy_evaluation(strategy);`,
		`CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_admission ON strategy_evaluation(admission);`,
		`CREATE TABLE IF NOT EXISTS portfolio_optimization_runs (
			run_id TEXT PRIMARY KEY,
			start_date TEXT NOT NULL,
			end_date TEXT NOT NULL,
			objective TEXT NOT NULL,
			benchmark TEXT NOT NULL DEFAULT '',
			strategy_count INTEGER NOT NULL DEFAULT 0,
			viable_count INTEGER NOT NULL DEFAULT 0,
			candidate_count INTEGER NOT NULL DEFAULT 0,
			top_n INTEGER NOT NULL DEFAULT 0,
			validation_status TEXT NOT NULL DEFAULT '',
			validation_json TEXT NOT NULL DEFAULT '{}',
			generated_at TEXT NOT NULL,
			summary_json TEXT NOT NULL,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE TABLE IF NOT EXISTS portfolio_optimization_candidates (
			run_id TEXT NOT NULL,
			candidate_id TEXT NOT NULL,
			rank INTEGER NOT NULL DEFAULT 0,
			name TEXT NOT NULL DEFAULT '',
			objective TEXT NOT NULL DEFAULT '',
			status TEXT NOT NULL DEFAULT '',
			score REAL NOT NULL DEFAULT 0,
			strategies TEXT NOT NULL DEFAULT '',
			weights_json TEXT NOT NULL DEFAULT '{}',
			total_return REAL,
			excess_annual_return REAL,
			win_rate REAL,
			annual_volatility REAL,
			annual_return REAL,
			max_drawdown REAL,
			sharpe REAL,
			calmar REAL,
			avg_turnover REAL,
			avg_holdings REAL,
			avg_total_mv REAL,
			avg_amount REAL,
			exit_architecture_type TEXT NOT NULL DEFAULT '',
			exit_architecture_label TEXT NOT NULL DEFAULT '',
			exit_architecture_json TEXT NOT NULL DEFAULT '{}',
			rebalance_freq INTEGER NOT NULL DEFAULT 0,
			market_regime_filter TEXT NOT NULL DEFAULT '',
			position_max_weight REAL,
			validation_status TEXT NOT NULL DEFAULT '',
			validation_json TEXT NOT NULL DEFAULT '{}',
			reason TEXT NOT NULL DEFAULT '',
			payload_json TEXT NOT NULL,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(run_id, candidate_id)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_portfolio_optimization_candidates_run_rank ON portfolio_optimization_candidates(run_id, rank);`,
		`CREATE TABLE IF NOT EXISTS strategy_validation_reviews (
			id TEXT PRIMARY KEY,
			subject_type TEXT NOT NULL,
			subject_id TEXT NOT NULL,
			strategy TEXT NOT NULL DEFAULT '',
			strategy_version INTEGER,
			source_run_id TEXT NOT NULL DEFAULT '',
			status TEXT NOT NULL DEFAULT '',
			score REAL NOT NULL DEFAULT 0,
			gates_json TEXT NOT NULL DEFAULT '{}',
			metrics_json TEXT NOT NULL DEFAULT '{}',
			recommendation TEXT NOT NULL DEFAULT '',
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_strategy_validation_reviews_subject ON strategy_validation_reviews(subject_type, subject_id);`,
		`CREATE TABLE IF NOT EXISTS research_reports (
			id TEXT PRIMARY KEY,
			subject_type TEXT NOT NULL,
			subject_id TEXT NOT NULL,
			report_type TEXT NOT NULL,
			title TEXT NOT NULL DEFAULT '',
			model TEXT NOT NULL DEFAULT '',
			content_md TEXT NOT NULL DEFAULT '',
			payload_json TEXT NOT NULL DEFAULT '{}',
			created_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_research_reports_subject ON research_reports(subject_type, subject_id);`,
		`CREATE TABLE IF NOT EXISTS evaluation_data_snapshots (
			id TEXT PRIMARY KEY,
			subject_type TEXT NOT NULL,
			subject_id TEXT NOT NULL,
			snapshot_json TEXT NOT NULL DEFAULT '{}',
			created_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_evaluation_data_snapshots_subject ON evaluation_data_snapshots(subject_type, subject_id);`,
		`CREATE TABLE IF NOT EXISTS recommendation_hindsight (
			id TEXT PRIMARY KEY,
			recommendation_date TEXT NOT NULL,
			horizon_days INTEGER NOT NULL DEFAULT 1,
			next_date TEXT NOT NULL DEFAULT '',
			n_holdings INTEGER NOT NULL DEFAULT 0,
			n_eval INTEGER NOT NULL DEFAULT 0,
			weighted_return REAL,
			equal_weight_return REAL,
			hit_rate REAL,
			payload_json TEXT NOT NULL DEFAULT '{}',
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			UNIQUE(recommendation_date, horizon_days)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_recommendation_hindsight_date ON recommendation_hindsight(recommendation_date);`,
		`CREATE TABLE IF NOT EXISTS risk_exposure_snapshots (
			id TEXT PRIMARY KEY,
			subject_type TEXT NOT NULL,
			subject_id TEXT NOT NULL,
			as_of_date TEXT NOT NULL DEFAULT '',
			n_holdings INTEGER NOT NULL DEFAULT 0,
			total_weight REAL NOT NULL DEFAULT 0,
			max_single_weight REAL NOT NULL DEFAULT 0,
			top5_weight REAL NOT NULL DEFAULT 0,
			industry_json TEXT NOT NULL DEFAULT '{}',
			strategy_json TEXT NOT NULL DEFAULT '{}',
			payload_json TEXT NOT NULL DEFAULT '{}',
			created_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_risk_exposure_snapshots_subject ON risk_exposure_snapshots(subject_type, subject_id);`,
		`CREATE TABLE IF NOT EXISTS paper_trading_log (
			id TEXT PRIMARY KEY,
			signal_date TEXT NOT NULL,
			ts_code TEXT NOT NULL,
			name TEXT NOT NULL DEFAULT '',
			action TEXT NOT NULL DEFAULT '',
			target_weight REAL NOT NULL DEFAULT 0,
			actual_weight REAL,
			status TEXT NOT NULL DEFAULT 'signal_recorded',
			reason TEXT NOT NULL DEFAULT '',
			payload_json TEXT NOT NULL DEFAULT '{}',
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			UNIQUE(signal_date, ts_code, action)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_paper_trading_log_date ON paper_trading_log(signal_date);`,
		`CREATE TABLE IF NOT EXISTS promotion_decisions (
			id TEXT PRIMARY KEY,
			strategy TEXT NOT NULL,
			strategy_version INTEGER NOT NULL DEFAULT 0,
			current_status TEXT NOT NULL DEFAULT '',
			recommended_status TEXT NOT NULL DEFAULT '',
			score REAL NOT NULL DEFAULT 0,
			reason TEXT NOT NULL DEFAULT '',
			payload_json TEXT NOT NULL DEFAULT '{}',
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			UNIQUE(strategy, strategy_version)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_promotion_decisions_strategy ON promotion_decisions(strategy, strategy_version);`,
		`CREATE TABLE IF NOT EXISTS walk_forward_windows (
			id TEXT PRIMARY KEY,
			subject_type TEXT NOT NULL,
			subject_id TEXT NOT NULL,
			window_name TEXT NOT NULL DEFAULT '',
			start_date TEXT NOT NULL DEFAULT '',
			end_date TEXT NOT NULL DEFAULT '',
			status TEXT NOT NULL DEFAULT '',
			score REAL NOT NULL DEFAULT 0,
			metrics_json TEXT NOT NULL DEFAULT '{}',
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			UNIQUE(subject_type, subject_id, window_name)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_walk_forward_windows_subject ON walk_forward_windows(subject_type, subject_id);`,
		`CREATE TABLE IF NOT EXISTS parameter_experiments (
			id TEXT PRIMARY KEY,
			strategy TEXT NOT NULL,
			strategy_version INTEGER NOT NULL DEFAULT 0,
			param_set TEXT NOT NULL DEFAULT '',
			status TEXT NOT NULL DEFAULT '',
			score REAL NOT NULL DEFAULT 0,
			params_json TEXT NOT NULL DEFAULT '{}',
			metrics_json TEXT NOT NULL DEFAULT '{}',
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			UNIQUE(strategy, strategy_version, param_set)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_parameter_experiments_strategy ON parameter_experiments(strategy, strategy_version);`,
		`CREATE TABLE IF NOT EXISTS state_team_holder_snapshots (
			ts_code TEXT NOT NULL,
			name TEXT NOT NULL DEFAULT '',
			industry TEXT NOT NULL DEFAULT '',
			end_date TEXT NOT NULL,
			ann_date TEXT NOT NULL DEFAULT '',
			holder_count INTEGER NOT NULL DEFAULT 0,
			hold_amount REAL NOT NULL DEFAULT 0,
			hold_ratio REAL NOT NULL DEFAULT 0,
			hold_float_ratio REAL NOT NULL DEFAULT 0,
			holders TEXT NOT NULL DEFAULT '',
			updated_at TEXT NOT NULL,
			PRIMARY KEY(ts_code, end_date)
		);`,
		`CREATE TABLE IF NOT EXISTS state_team_holder_changes (
			ts_code TEXT NOT NULL,
			name TEXT NOT NULL DEFAULT '',
			industry TEXT NOT NULL DEFAULT '',
			action TEXT NOT NULL,
			current_period TEXT NOT NULL,
			previous_period TEXT NOT NULL,
			current_holder_count INTEGER NOT NULL DEFAULT 0,
			previous_holder_count INTEGER NOT NULL DEFAULT 0,
			current_hold_amount REAL NOT NULL DEFAULT 0,
			previous_hold_amount REAL NOT NULL DEFAULT 0,
			current_hold_ratio REAL NOT NULL DEFAULT 0,
			previous_hold_ratio REAL NOT NULL DEFAULT 0,
			hold_ratio_delta REAL NOT NULL DEFAULT 0,
			current_float_ratio REAL NOT NULL DEFAULT 0,
			previous_float_ratio REAL NOT NULL DEFAULT 0,
			current_holders TEXT NOT NULL DEFAULT '',
			previous_holders TEXT NOT NULL DEFAULT '',
			note TEXT NOT NULL DEFAULT '',
			updated_at TEXT NOT NULL,
			PRIMARY KEY(ts_code, current_period, previous_period)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_state_team_changes_period_action ON state_team_holder_changes(current_period, action);`,
		`CREATE TABLE IF NOT EXISTS policy_support_signals (
			trade_date TEXT PRIMARY KEY,
			signal_level TEXT NOT NULL,
			total_score REAL NOT NULL DEFAULT 0,
			market_stress_score REAL NOT NULL DEFAULT 0,
			support_score REAL NOT NULL DEFAULT 0,
			institution_score REAL NOT NULL DEFAULT 0,
			weight_support_score REAL NOT NULL DEFAULT 0,
			direction TEXT NOT NULL DEFAULT '',
			reason TEXT NOT NULL DEFAULT '',
			evidence_json TEXT NOT NULL DEFAULT '{}',
			updated_at TEXT NOT NULL
		);`,
		`CREATE TABLE IF NOT EXISTS policy_support_candidates (
			trade_date TEXT NOT NULL,
			ts_code TEXT NOT NULL,
			name TEXT NOT NULL DEFAULT '',
			industry TEXT NOT NULL DEFAULT '',
			candidate_type TEXT NOT NULL DEFAULT '',
			score REAL NOT NULL DEFAULT 0,
			pct_chg REAL NOT NULL DEFAULT 0,
			amount_ratio REAL NOT NULL DEFAULT 0,
			turnover_rate REAL NOT NULL DEFAULT 0,
			institution_net_buy REAL NOT NULL DEFAULT 0,
			reason TEXT NOT NULL DEFAULT '',
			updated_at TEXT NOT NULL,
			PRIMARY KEY(trade_date, ts_code)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_policy_support_candidates_score ON policy_support_candidates(trade_date, score DESC);`,
		`CREATE TABLE IF NOT EXISTS py_run_lock (
			name TEXT PRIMARY KEY,
			pid INTEGER NOT NULL,
			hostname TEXT NOT NULL,
			acquired_at TEXT NOT NULL,
			heartbeat TEXT NOT NULL,
			task TEXT
		);`,
		`CREATE TABLE IF NOT EXISTS py_run_status (
			task TEXT PRIMARY KEY,
			state TEXT NOT NULL,
			idx INTEGER NOT NULL DEFAULT 0,
			total INTEGER NOT NULL DEFAULT 0,
			stage TEXT,
			name TEXT,
			message TEXT,
			started_at TEXT,
			updated_at TEXT NOT NULL,
			finished_at TEXT
		);`,
		`CREATE TABLE IF NOT EXISTS dataset_update_status (
			dataset TEXT PRIMARY KEY,
			category TEXT NOT NULL,
			state TEXT NOT NULL,
			progress_done INTEGER NOT NULL DEFAULT 0,
			progress_total INTEGER NOT NULL DEFAULT 0,
			message TEXT NOT NULL DEFAULT '',
			rows_written INTEGER NOT NULL DEFAULT 0,
			error_message TEXT NOT NULL DEFAULT '',
			started_at TEXT NOT NULL DEFAULT '',
			finished_at TEXT NOT NULL DEFAULT '',
			updated_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_dataset_update_status_category ON dataset_update_status(category);`,
		`CREATE TABLE IF NOT EXISTS pool_summary (
			id INTEGER PRIMARY KEY CHECK (id = 1),
			initial_cash REAL NOT NULL DEFAULT 500000,
			current_cash REAL NOT NULL DEFAULT 500000,
			market_value REAL NOT NULL DEFAULT 0,
			total_assets REAL NOT NULL DEFAULT 500000,
			total_cost REAL NOT NULL DEFAULT 0,
			total_pnl REAL NOT NULL DEFAULT 0,
			today_pnl REAL NOT NULL DEFAULT 0,
			today_pct REAL NOT NULL DEFAULT 0,
			unrealized_pnl REAL NOT NULL DEFAULT 0,
			unrealized_pct REAL NOT NULL DEFAULT 0,
			realized_pnl REAL NOT NULL DEFAULT 0,
			cum_return REAL NOT NULL DEFAULT 0,
			n_closed INTEGER NOT NULL DEFAULT 0,
			updated_at TEXT NOT NULL DEFAULT ''
		);`,
		`INSERT OR IGNORE INTO pool_summary (id, initial_cash, current_cash, total_assets, updated_at) VALUES (1, 500000, 500000, 500000, '');`,
		`CREATE TABLE IF NOT EXISTS pool_holdings (
			ts_code TEXT PRIMARY KEY,
			name TEXT NOT NULL DEFAULT '',
			industry TEXT NOT NULL DEFAULT '',
			shares INTEGER NOT NULL DEFAULT 0,
			avg_cost REAL NOT NULL DEFAULT 0,
			last_price REAL NOT NULL DEFAULT 0,
			market_value REAL NOT NULL DEFAULT 0,
			weight REAL NOT NULL DEFAULT 0,
			pnl REAL NOT NULL DEFAULT 0,
			pnl_pct REAL NOT NULL DEFAULT 0,
			open_date TEXT NOT NULL DEFAULT '',
			updated_at TEXT NOT NULL DEFAULT ''
		);`,
		`CREATE TABLE IF NOT EXISTS pool_trades (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			ts_code TEXT NOT NULL,
			side TEXT NOT NULL,
			shares INTEGER NOT NULL,
			price REAL NOT NULL,
			amount REAL NOT NULL,
			trade_date TEXT NOT NULL,
			pnl REAL NOT NULL DEFAULT 0,
			fee REAL NOT NULL DEFAULT 0,
			net_amount REAL NOT NULL DEFAULT 0,
			created_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_pool_trades_date ON pool_trades(trade_date);`,
		`CREATE INDEX IF NOT EXISTS idx_pool_trades_ts ON pool_trades(ts_code);`,
	}
	for _, statement := range statements {
		if _, err := db.conn.Exec(statement); err != nil {
			return err
		}
	}
	if err := db.runSchemaMigrations(); err != nil {
		return err
	}
	return nil
}

func (db *DB) runSchemaMigrations() error {
	if _, err := db.conn.Exec(`CREATE TABLE IF NOT EXISTS schema_migrations (
		version INTEGER PRIMARY KEY,
		name TEXT NOT NULL,
		applied_at TEXT NOT NULL
	);`); err != nil {
		return err
	}
	applied, err := db.appliedMigrations()
	if err != nil {
		return err
	}
	for _, item := range db.schemaMigrations() {
		if applied[item.version] {
			continue
		}
		if db.isMigrationAlreadyApplied(item.version) {
			if err := db.recordSchemaMigration(item); err != nil {
				return err
			}
			continue
		}
		if err := db.runSchemaMigration(item); err != nil {
			return err
		}
	}
	return nil
}

func (db *DB) runSchemaMigration(item migration) error {
	if err := item.up(db); err != nil {
		return fmt.Errorf("migration %d %s failed: %w", item.version, item.name, err)
	}
	return db.recordSchemaMigration(item)
}

func (db *DB) recordSchemaMigration(item migration) error {
	_, err := db.conn.Exec(`INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)`, item.version, item.name, time.Now().Format(time.RFC3339))
	return err
}

func (db *DB) isMigrationAlreadyApplied(version int) bool {
	switch version {
	case 1:
		return db.columnsExist("pool_summary", "total_cost", "today_pct", "unrealized_pnl", "unrealized_pct", "realized_pnl", "cum_return", "n_closed", "total_fee") && db.columnsExist("pool_trades", "fee", "net_amount")
	case 2:
		return db.columnsExist("time_machine_trades", "is_new")
	case 3:
		return db.columnsExist("evaluation_tasks", "parent_id", "group_run_id", "subtask_key", "subtask_name", "sequence", "total", "attempt", "max_attempts")
	case 4:
		return db.columnsExist("strategy_settings_versions", "promotion_status", "validation_json")
	case 5:
		return db.columnsExist("portfolio_optimization_runs", "validation_status", "validation_json") && db.columnsExist("portfolio_optimization_candidates", "total_return", "excess_annual_return", "win_rate", "annual_volatility", "exit_architecture_type", "exit_architecture_label", "exit_architecture_json", "rebalance_freq", "market_regime_filter", "position_max_weight", "validation_status", "validation_json")
	case 6:
		return db.columnsExist("strategy_evaluation", "admission_score", "month_count", "monthly_win_rate", "worst_month_return", "positive_3m_rate", "return_score", "drawdown_score", "risk_adjusted_score", "cost_score", "capacity_score", "stability_score", "independence_score")
	default:
		return false
	}
}

func (db *DB) columnsExist(tableName string, names ...string) bool {
	columns, err := db.tableColumns(tableName)
	if err != nil {
		return false
	}
	for _, name := range names {
		if !columns[name] {
			return false
		}
	}
	return true
}

func (db *DB) appliedMigrations() (map[int]bool, error) {
	rows, err := db.conn.Query(`SELECT version FROM schema_migrations`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	applied := map[int]bool{}
	for rows.Next() {
		var version int
		if err := rows.Scan(&version); err != nil {
			return nil, err
		}
		applied[version] = true
	}
	return applied, rows.Err()
}

func (db *DB) schemaMigrations() []migration {
	return []migration{
		{version: 1, name: "pool_accounting_columns", up: func(db *DB) error {
			columns := []columnMigration{
				{table: "pool_summary", name: "total_cost", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "pool_summary", name: "today_pct", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "pool_summary", name: "unrealized_pnl", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "pool_summary", name: "unrealized_pct", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "pool_summary", name: "realized_pnl", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "pool_summary", name: "cum_return", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "pool_summary", name: "n_closed", ddl: "INTEGER NOT NULL DEFAULT 0"},
				{table: "pool_summary", name: "total_fee", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "pool_trades", name: "fee", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "pool_trades", name: "net_amount", ddl: "REAL NOT NULL DEFAULT 0"},
			}
			return db.addColumnsIfMissing(columns)
		}},
		{version: 2, name: "time_machine_trade_flags", up: func(db *DB) error {
			return db.addColumnsIfMissing([]columnMigration{{table: "time_machine_trades", name: "is_new", ddl: "INTEGER NOT NULL DEFAULT 0"}})
		}},
		{version: 3, name: "evaluation_task_subtasks", up: func(db *DB) error {
			columns := []columnMigration{
				{table: "evaluation_tasks", name: "parent_id", ddl: "TEXT"},
				{table: "evaluation_tasks", name: "group_run_id", ddl: "TEXT"},
				{table: "evaluation_tasks", name: "subtask_key", ddl: "TEXT"},
				{table: "evaluation_tasks", name: "subtask_name", ddl: "TEXT"},
				{table: "evaluation_tasks", name: "sequence", ddl: "INTEGER NOT NULL DEFAULT 0"},
				{table: "evaluation_tasks", name: "total", ddl: "INTEGER NOT NULL DEFAULT 0"},
				{table: "evaluation_tasks", name: "attempt", ddl: "INTEGER NOT NULL DEFAULT 0"},
				{table: "evaluation_tasks", name: "max_attempts", ddl: "INTEGER NOT NULL DEFAULT 1"},
			}
			if err := db.addColumnsIfMissing(columns); err != nil {
				return err
			}
			return db.createEvaluationTaskIndexes()
		}},
		{version: 4, name: "strategy_version_validation", up: func(db *DB) error {
			return db.addColumnsIfMissing([]columnMigration{
				{table: "strategy_settings_versions", name: "promotion_status", ddl: "TEXT NOT NULL DEFAULT 'research'"},
				{table: "strategy_settings_versions", name: "validation_json", ddl: "TEXT NOT NULL DEFAULT '{}'"},
			})
		}},
		{version: 5, name: "portfolio_validation_columns", up: func(db *DB) error {
			columns := []columnMigration{
				{table: "portfolio_optimization_runs", name: "validation_status", ddl: "TEXT NOT NULL DEFAULT ''"},
				{table: "portfolio_optimization_runs", name: "validation_json", ddl: "TEXT NOT NULL DEFAULT '{}'"},
				{table: "portfolio_optimization_candidates", name: "total_return", ddl: "REAL"},
				{table: "portfolio_optimization_candidates", name: "excess_annual_return", ddl: "REAL"},
				{table: "portfolio_optimization_candidates", name: "win_rate", ddl: "REAL"},
				{table: "portfolio_optimization_candidates", name: "annual_volatility", ddl: "REAL"},
				{table: "portfolio_optimization_candidates", name: "exit_architecture_type", ddl: "TEXT NOT NULL DEFAULT ''"},
				{table: "portfolio_optimization_candidates", name: "exit_architecture_label", ddl: "TEXT NOT NULL DEFAULT ''"},
				{table: "portfolio_optimization_candidates", name: "exit_architecture_json", ddl: "TEXT NOT NULL DEFAULT '{}'"},
				{table: "portfolio_optimization_candidates", name: "rebalance_freq", ddl: "INTEGER NOT NULL DEFAULT 0"},
				{table: "portfolio_optimization_candidates", name: "market_regime_filter", ddl: "TEXT NOT NULL DEFAULT ''"},
				{table: "portfolio_optimization_candidates", name: "position_max_weight", ddl: "REAL"},
				{table: "portfolio_optimization_candidates", name: "validation_status", ddl: "TEXT NOT NULL DEFAULT ''"},
				{table: "portfolio_optimization_candidates", name: "validation_json", ddl: "TEXT NOT NULL DEFAULT '{}'"},
			}
			return db.addColumnsIfMissing(columns)
		}},
		{version: 6, name: "strategy_evaluation_scores", up: func(db *DB) error {
			return db.migrateStrategyEvaluationSchema()
		}},
	}
}

type columnMigration struct {
	table string
	name  string
	ddl   string
}

func (db *DB) addColumnsIfMissing(columns []columnMigration) error {
	cache := map[string]map[string]bool{}
	for _, column := range columns {
		tableColumns, ok := cache[column.table]
		if !ok {
			var err error
			tableColumns, err = db.tableColumns(column.table)
			if err != nil {
				return err
			}
			cache[column.table] = tableColumns
		}
		if tableColumns[column.name] {
			continue
		}
		if _, err := db.conn.Exec(fmt.Sprintf("ALTER TABLE %s ADD COLUMN %s %s", column.table, column.name, column.ddl)); err != nil {
			return err
		}
		tableColumns[column.name] = true
	}
	return nil
}

func (db *DB) createEvaluationTaskIndexes() error {
	columns, err := db.tableColumns("evaluation_tasks")
	if err != nil {
		return err
	}
	if !columns["parent_id"] {
		return fmt.Errorf("evaluation_tasks.parent_id column is missing")
	}
	if _, err := db.conn.Exec(`CREATE INDEX IF NOT EXISTS idx_evaluation_tasks_parent_id ON evaluation_tasks(parent_id);`); err != nil {
		return err
	}
	if !columns["group_run_id"] {
		return fmt.Errorf("evaluation_tasks.group_run_id column is missing")
	}
	if _, err := db.conn.Exec(`CREATE INDEX IF NOT EXISTS idx_evaluation_tasks_group_run_id ON evaluation_tasks(group_run_id);`); err != nil {
		return err
	}
	return nil
}

func (db *DB) tableColumns(tableName string) (map[string]bool, error) {
	rows, err := db.conn.Query(fmt.Sprintf(`PRAGMA table_info(%s)`, tableName))
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	columns := map[string]bool{}
	for rows.Next() {
		var cid int
		var name string
		var typ string
		var notNull int
		var defaultValue sql.NullString
		var pk int
		if err := rows.Scan(&cid, &name, &typ, &notNull, &defaultValue, &pk); err != nil {
			return nil, err
		}
		columns[name] = true
	}
	return columns, rows.Err()
}

func (db *DB) migrateStrategyEvaluationSchema() error {
	rows, err := db.conn.Query(`PRAGMA table_info(strategy_evaluation)`)
	if err != nil {
		return err
	}
	defer rows.Close()

	columns := map[string]bool{}
	for rows.Next() {
		var cid int
		var name string
		var typ string
		var notNull int
		var defaultValue sql.NullString
		var pk int
		if err := rows.Scan(&cid, &name, &typ, &notNull, &defaultValue, &pk); err != nil {
			return err
		}
		columns[strings.ToLower(name)] = true
	}
	if err := rows.Err(); err != nil {
		return err
	}
	if columns["run_id"] {
		return db.ensureStrategyEvaluationScoreColumns(columns)
	}

	_, err = db.conn.Exec(`
		ALTER TABLE strategy_evaluation RENAME TO strategy_evaluation_legacy;
		CREATE TABLE strategy_evaluation (
			run_id TEXT NOT NULL,
			strategy TEXT NOT NULL,
			label TEXT NOT NULL DEFAULT '',
			enabled INTEGER NOT NULL DEFAULT 0,
			status TEXT NOT NULL DEFAULT '',
			admission TEXT NOT NULL DEFAULT '',
			admission_score REAL,
			reason TEXT NOT NULL DEFAULT '',
			start_date TEXT NOT NULL,
			end_date TEXT NOT NULL,
			benchmark TEXT NOT NULL DEFAULT '',
			baseline TEXT NOT NULL DEFAULT '',
			total_return REAL,
			annual_return REAL,
			annual_volatility REAL,
			sharpe REAL,
			max_drawdown REAL,
			calmar REAL,
			win_rate REAL,
			n_days INTEGER,
			month_count INTEGER,
			monthly_win_rate REAL,
			worst_month_return REAL,
			positive_3m_rate REAL,
			avg_turnover REAL,
			avg_holdings REAL,
			avg_total_mv REAL,
			avg_amount REAL,
			overlap_with_baseline REAL,
			corr_with_baseline REAL,
			return_score REAL,
			drawdown_score REAL,
			risk_adjusted_score REAL,
			cost_score REAL,
			capacity_score REAL,
			stability_score REAL,
			independence_score REAL,
			strategy_version INTEGER,
			strategy_version_mode TEXT,
			error TEXT NOT NULL DEFAULT '',
			generated_at TEXT NOT NULL,
			payload_json TEXT NOT NULL,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(run_id, strategy)
		);
		CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_run ON strategy_evaluation(run_id);
		CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_date ON strategy_evaluation(start_date, end_date);
		CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_strategy ON strategy_evaluation(strategy);
		CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_admission ON strategy_evaluation(admission);
	`)
	return err
}

func (db *DB) ensureStrategyEvaluationScoreColumns(columns map[string]bool) error {
	addColumns := map[string]string{
		"admission_score":       "REAL",
		"month_count":           "INTEGER",
		"monthly_win_rate":      "REAL",
		"worst_month_return":    "REAL",
		"positive_3m_rate":      "REAL",
		"return_score":          "REAL",
		"drawdown_score":        "REAL",
		"risk_adjusted_score":   "REAL",
		"cost_score":            "REAL",
		"capacity_score":        "REAL",
		"stability_score":       "REAL",
		"independence_score":    "REAL",
		"strategy_version":      "INTEGER",
		"strategy_version_mode": "TEXT",
	}
	for name, ddl := range addColumns {
		if columns[strings.ToLower(name)] {
			continue
		}
		if _, err := db.conn.Exec(fmt.Sprintf("ALTER TABLE strategy_evaluation ADD COLUMN %s %s", name, ddl)); err != nil {
			return err
		}
	}
	return nil
}
