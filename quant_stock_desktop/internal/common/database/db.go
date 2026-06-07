package database

import (
	"database/sql"
	"fmt"
	"strings"
	"time"
)

type DB struct {
	conn    *sql.DB
	backend Backend
}

type Backend string

const (
	BackendMySQL Backend = "mysql"
)

const defaultLocalMySQLDSN = "quant_stock:quant_stock@tcp(127.0.0.1:3306)/quant_stock?parseTime=true&charset=utf8mb4&loc=Local"

type Config struct {
	Backend        string
	SQLitePath     string
	MySQLDSN       string
	MySQLBootstrap *MySQLBootstrapConfig
}

type migration struct {
	version int
	name    string
	up      func(*DB) error
}

func Wrap(conn *sql.DB, backend Backend) *DB {
	return &DB{conn: conn, backend: backend}
}

func OpenConfigured(cfg Config) (*DB, error) {
	cfg.Backend = string(BackendMySQL)
	if strings.TrimSpace(cfg.MySQLDSN) == "" {
		cfg.MySQLDSN = defaultLocalMySQLDSN
	}
	if cfg.MySQLBootstrap != nil {
		if err := BootstrapMySQL(*cfg.MySQLBootstrap); err != nil {
			if db, openErr := OpenMySQL(cfg.MySQLDSN); openErr == nil {
				return db, nil
			}
			return nil, err
		}
	}
	return OpenMySQL(cfg.MySQLDSN)
}

func Open(path string) (*DB, error) {
	return OpenMySQL(defaultLocalMySQLDSN)
}

func OpenMySQL(dsn string) (*DB, error) {
	conn, err := sql.Open("mysql", dsn)
	if err != nil {
		return nil, err
	}
	conn.SetMaxOpenConns(10)
	conn.SetMaxIdleConns(3)
	conn.SetConnMaxLifetime(0)
	if err := conn.Ping(); err != nil {
		_ = conn.Close()
		return nil, err
	}
	if err := migrateMySQLSchema(conn); err != nil {
		_ = conn.Close()
		return nil, err
	}
	return &DB{conn: conn, backend: BackendMySQL}, nil
}

func (db *DB) Conn() *sql.DB {
	return db.conn
}

func (db *DB) Backend() Backend {
	if db == nil || db.backend == "" {
		return BackendMySQL
	}
	return db.backend
}

func (db *DB) IsMySQL() bool {
	return db.Backend() == BackendMySQL
}

func (db *DB) CurrentTimestampSQL() string {
	return "CURRENT_TIMESTAMP"
}

func (db *DB) UpsertSQL(table string, columns []string, conflictColumns []string, updateColumns []string) string {
	placeholders := strings.TrimRight(strings.Repeat("?,", len(columns)), ",")
	columnSQL := quoteIdents(db.Backend(), columns)
	assignments := make([]string, 0, len(updateColumns))
	for _, column := range updateColumns {
		quoted := quoteIdent(db.Backend(), column)
		assignments = append(assignments, fmt.Sprintf("%s = VALUES(%s)", quoted, quoted))
	}
	return fmt.Sprintf("INSERT INTO %s (%s) VALUES (%s) ON DUPLICATE KEY UPDATE %s",
		quoteIdent(db.Backend(), table), columnSQL, placeholders, strings.Join(assignments, ", "))
}

func (db *DB) InsertIgnoreSQL(table string, columns []string) string {
	placeholders := strings.TrimRight(strings.Repeat("?,", len(columns)), ",")
	return fmt.Sprintf("INSERT IGNORE INTO %s (%s) VALUES (%s)", quoteIdent(db.Backend(), table), quoteIdents(db.Backend(), columns), placeholders)
}

func (db *DB) ExecSchemaStatement(statement string) error {
	converted, ok := sqliteStatementToMySQL(statement)
	if !ok {
		return nil
	}
	statement = converted
	_, err := db.conn.Exec(statement)
	return err
}

func (db *DB) Close() error {
	if db == nil || db.conn == nil {
		return nil
	}
	return db.conn.Close()
}

func normalizeBackend(value string) Backend {
	return BackendMySQL
}

func quoteIdents(backend Backend, values []string) string {
	out := make([]string, 0, len(values))
	for _, value := range values {
		out = append(out, quoteIdent(backend, value))
	}
	return strings.Join(out, ", ")
}

func quoteIdent(backend Backend, value string) string {
	quote := "`"
	return quote + strings.ReplaceAll(value, quote, quote+quote) + quote
}

func (db *DB) Migrate() error {
	if err := db.renameLegacyTables(); err != nil {
		return err
	}
	statements := sqliteBaseSchemaStatements()
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

type tableRename struct {
	old string
	new string
}

func legacyTableRenames() []tableRename {
	return []tableRename{
		{old: "app_settings", new: "cfg_app_settings"},
		{old: "strategy_settings_versions", new: "strategy_config_versions"},
		{old: "evaluation_tasks", new: "task_jobs"},
		{old: "task_evaluation", new: "task_jobs"},
		{old: "time_machine_snapshots", new: "portfolio_tm_snapshots"},
		{old: "time_machine_trades", new: "portfolio_tm_trades"},
		{old: "time_machine_positions", new: "portfolio_tm_positions"},
		{old: "market_data_files", new: "data_market_files"},
		{old: "limit_breakout_cache", new: "market_limit_breakout_cache"},
		{old: "limit_breakout_cache_meta", new: "market_limit_breakout_cache_meta"},
		{old: "limit_up_momentum_cache", new: "market_limit_momentum_cache"},
		{old: "limit_up_momentum_cache_meta", new: "market_limit_momentum_cache_meta"},
		{old: "limit_signal_predictions", new: "market_limit_signal_predictions"},
		{old: "limit_signal_evaluation_summary", new: "market_limit_signal_eval_summary"},
		{old: "daily_recommendation", new: "rec_daily_recommendations"},
		{old: "strategy_evaluation", new: "eval_strategy_admission"},
		{old: "portfolio_optimization_runs", new: "eval_portfolio_runs"},
		{old: "portfolio_optimization_candidates", new: "eval_portfolio_candidates"},
		{old: "evaluation_data_snapshots", new: "eval_data_snapshots"},
		{old: "recommendation_hindsight", new: "rec_hindsight"},
		{old: "paper_trading_log", new: "trade_paper_log"},
		{old: "promotion_decisions", new: "strategy_promotion_decisions"},
		{old: "walk_forward_windows", new: "eval_walk_forward_windows"},
		{old: "parameter_experiments", new: "eval_parameter_experiments"},
		{old: "policy_support_signals", new: "monitor_policy_support_signals"},
		{old: "policy_support_candidates", new: "monitor_policy_support_candidates"},
		{old: "py_run_lock", new: "task_run_locks"},
		{old: "py_run_status", new: "task_run_status"},
		{old: "runtime_run_locks", new: "task_run_locks"},
		{old: "runtime_run_status", new: "task_run_status"},
		{old: "pool_summary", new: "portfolio_pool_summary"},
		{old: "pool_holdings", new: "portfolio_pool_holdings"},
		{old: "pool_trades", new: "portfolio_pool_trades"},
	}
}

func (db *DB) renameLegacyTables() error {
	for _, item := range legacyTableRenames() {
		oldExists, err := db.tableExists(item.old)
		if err != nil {
			return err
		}
		if !oldExists {
			continue
		}
		newExists, err := db.tableExists(item.new)
		if err != nil {
			return err
		}
		if newExists {
			continue
		}
		if db.IsMySQL() {
			_, err = db.conn.Exec(fmt.Sprintf("RENAME TABLE %s TO %s", quoteIdent(db.Backend(), item.old), quoteIdent(db.Backend(), item.new)))
		} else {
			_, err = db.conn.Exec(fmt.Sprintf("ALTER TABLE %s RENAME TO %s", quoteIdent(db.Backend(), item.old), quoteIdent(db.Backend(), item.new)))
		}
		if err != nil {
			return fmt.Errorf("rename table %s to %s: %w", item.old, item.new, err)
		}
	}
	return nil
}

func sqliteBaseSchemaStatements() []string {
	return []string{
		`CREATE TABLE IF NOT EXISTS cfg_app_settings (
			key TEXT PRIMARY KEY,
			value TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE TABLE IF NOT EXISTS strategy_config_versions (
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
		`CREATE UNIQUE INDEX IF NOT EXISTS idx_strategy_config_versions_active
			ON strategy_config_versions(strategy)
			WHERE is_active = 1;`,
		`CREATE INDEX IF NOT EXISTS idx_strategy_config_versions_strategy_version
			ON strategy_config_versions(strategy, version DESC);`,
		`CREATE TABLE IF NOT EXISTS task_jobs (
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
		`CREATE INDEX IF NOT EXISTS idx_task_jobs_status ON task_jobs(status);`,
		`CREATE INDEX IF NOT EXISTS idx_task_jobs_type ON task_jobs(task_type);`,
		`CREATE INDEX IF NOT EXISTS idx_task_jobs_created_at ON task_jobs(created_at);`,
		`CREATE INDEX IF NOT EXISTS idx_task_jobs_external_run_id ON task_jobs(external_run_id);`,
		`CREATE TABLE IF NOT EXISTS portfolio_tm_snapshots (
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
		`CREATE INDEX IF NOT EXISTS idx_portfolio_tm_snapshots_date ON portfolio_tm_snapshots(run_id, trade_date);`,
		`CREATE TABLE IF NOT EXISTS portfolio_tm_trades (
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
		`CREATE UNIQUE INDEX IF NOT EXISTS idx_portfolio_tm_trades_unique ON portfolio_tm_trades(run_id, trade_date, ts_code, action, shares, price, amount, exit_reason);`,
		`CREATE INDEX IF NOT EXISTS idx_portfolio_tm_trades_run_date ON portfolio_tm_trades(run_id, trade_date);`,
		`CREATE TABLE IF NOT EXISTS portfolio_tm_positions (
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
		`CREATE INDEX IF NOT EXISTS idx_portfolio_tm_positions_run_date ON portfolio_tm_positions(run_id, trade_date);`,
		`CREATE TABLE IF NOT EXISTS data_market_files (
			id TEXT PRIMARY KEY,
			data_type TEXT NOT NULL,
			partition_name TEXT NOT NULL,
			file_path TEXT NOT NULL,
			row_count INTEGER NOT NULL DEFAULT 0,
			file_size INTEGER NOT NULL DEFAULT 0,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE UNIQUE INDEX IF NOT EXISTS idx_data_market_files_path ON data_market_files(file_path);`,
		`CREATE INDEX IF NOT EXISTS idx_data_market_files_type ON data_market_files(data_type);`,
		`CREATE TABLE IF NOT EXISTS data_etl_versions (
			dataset TEXT PRIMARY KEY,
			source_version TEXT NOT NULL,
			file_count INTEGER NOT NULL DEFAULT 0,
			row_count INTEGER NOT NULL DEFAULT 0,
			status TEXT NOT NULL DEFAULT '',
			message TEXT NOT NULL DEFAULT '',
			updated_at TEXT NOT NULL
		);`,
		`CREATE TABLE IF NOT EXISTS data_etl_files (
			id TEXT PRIMARY KEY,
			dataset TEXT NOT NULL,
			file_path TEXT NOT NULL,
			source_version TEXT NOT NULL,
			row_count INTEGER NOT NULL DEFAULT 0,
			status TEXT NOT NULL DEFAULT '',
			message TEXT NOT NULL DEFAULT '',
			updated_at TEXT NOT NULL
		);`,
		`CREATE TABLE IF NOT EXISTS data_stock_basic (
			ts_code TEXT PRIMARY KEY,
			symbol TEXT NOT NULL DEFAULT '',
			name TEXT NOT NULL DEFAULT '',
			area TEXT NOT NULL DEFAULT '',
			industry TEXT NOT NULL DEFAULT '',
			market TEXT NOT NULL DEFAULT '',
			list_date TEXT NOT NULL DEFAULT '',
			list_status TEXT NOT NULL DEFAULT '',
			updated_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_data_stock_basic_keyword ON data_stock_basic(ts_code, symbol, name, industry);`,
		`CREATE TABLE IF NOT EXISTS data_daily_bars (
			ts_code TEXT NOT NULL,
			trade_date TEXT NOT NULL,
			open REAL NOT NULL DEFAULT 0,
			high REAL NOT NULL DEFAULT 0,
			low REAL NOT NULL DEFAULT 0,
			close REAL NOT NULL DEFAULT 0,
			pre_close REAL NOT NULL DEFAULT 0,
			change_amount REAL NOT NULL DEFAULT 0,
			pct_chg REAL NOT NULL DEFAULT 0,
			vol REAL NOT NULL DEFAULT 0,
			amount REAL NOT NULL DEFAULT 0,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(ts_code, trade_date)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_data_daily_bars_date ON data_daily_bars(trade_date);`,
		`CREATE TABLE IF NOT EXISTS t0_daily_runs (
			run_id TEXT PRIMARY KEY,
			trade_date TEXT NOT NULL,
			status TEXT NOT NULL,
			candidate_count INTEGER NOT NULL DEFAULT 0,
			backtest_count INTEGER NOT NULL DEFAULT 0,
			summary_json TEXT NOT NULL,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE TABLE IF NOT EXISTS t0_daily_candidates (
			run_id TEXT NOT NULL,
			ts_code TEXT NOT NULL,
			name TEXT NOT NULL DEFAULT '',
			industry TEXT NOT NULL DEFAULT '',
			trade_date TEXT NOT NULL,
			action TEXT NOT NULL,
			score REAL NOT NULL DEFAULT 0,
			state TEXT NOT NULL DEFAULT '',
			setup TEXT NOT NULL DEFAULT '',
			first_action TEXT NOT NULL DEFAULT '',
			price REAL NOT NULL DEFAULT 0,
			reduce_price REAL NOT NULL DEFAULT 0,
			buy_price REAL NOT NULL DEFAULT 0,
			stop_price REAL NOT NULL DEFAULT 0,
			t_ratio REAL NOT NULL DEFAULT 0,
			today_pct REAL NOT NULL DEFAULT 0,
			return_5d REAL NOT NULL DEFAULT 0,
			return_20d REAL NOT NULL DEFAULT 0,
			avg_range_20d REAL NOT NULL DEFAULT 0,
			drawdown_20d REAL NOT NULL DEFAULT 0,
			amount REAL NOT NULL DEFAULT 0,
			avg_amount_20d REAL NOT NULL DEFAULT 0,
			expected_edge REAL NOT NULL DEFAULT 0,
			target_freq TEXT NOT NULL DEFAULT 'daily',
			lookback_days INTEGER NOT NULL DEFAULT 0,
			plan_json LONGTEXT NOT NULL,
			reasons_json TEXT NOT NULL,
			risks_json TEXT NOT NULL,
			generated_at TEXT NOT NULL,
			PRIMARY KEY(run_id, ts_code)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_t0_daily_candidates_latest ON t0_daily_candidates(trade_date, score DESC);`,
		`CREATE TABLE IF NOT EXISTS t0_daily_backtests (
			run_id TEXT NOT NULL,
			ts_code TEXT NOT NULL,
			name TEXT NOT NULL DEFAULT '',
			industry TEXT NOT NULL DEFAULT '',
			n_days INTEGER NOT NULL DEFAULT 0,
			n_candidates INTEGER NOT NULL DEFAULT 0,
			two_sided_rate REAL NOT NULL DEFAULT 0,
			one_sided_rate REAL NOT NULL DEFAULT 0,
			avg_edge REAL NOT NULL DEFAULT 0,
			total_edge REAL NOT NULL DEFAULT 0,
			avg_next_range REAL NOT NULL DEFAULT 0,
			score REAL NOT NULL DEFAULT 0,
			summary_json TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(run_id, ts_code)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_t0_daily_backtests_score ON t0_daily_backtests(run_id, score DESC);`,
		`CREATE TABLE IF NOT EXISTS t0_daily_time_machine_runs (
			run_id TEXT PRIMARY KEY,
			as_of_date TEXT NOT NULL,
			eval_start_date TEXT NOT NULL,
			eval_end_date TEXT NOT NULL,
			status TEXT NOT NULL,
			candidate_count INTEGER NOT NULL DEFAULT 0,
			evaluated_count INTEGER NOT NULL DEFAULT 0,
			avg_t0_edge REAL NOT NULL DEFAULT 0,
			avg_underlying_return REAL NOT NULL DEFAULT 0,
			avg_combined_return REAL NOT NULL DEFAULT 0,
			win_rate REAL NOT NULL DEFAULT 0,
			summary_json TEXT NOT NULL,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE TABLE IF NOT EXISTS t0_daily_time_machine_results (
			run_id TEXT NOT NULL,
			ts_code TEXT NOT NULL,
			name TEXT NOT NULL DEFAULT '',
			industry TEXT NOT NULL DEFAULT '',
			as_of_date TEXT NOT NULL,
			eval_start_date TEXT NOT NULL,
			eval_end_date TEXT NOT NULL,
			score REAL NOT NULL DEFAULT 0,
			n_eval_days INTEGER NOT NULL DEFAULT 0,
			two_sided_count INTEGER NOT NULL DEFAULT 0,
			one_sided_count INTEGER NOT NULL DEFAULT 0,
			t0_edge REAL NOT NULL DEFAULT 0,
			avg_t0_edge REAL NOT NULL DEFAULT 0,
			underlying_return REAL NOT NULL DEFAULT 0,
			combined_return REAL NOT NULL DEFAULT 0,
			max_drawdown REAL NOT NULL DEFAULT 0,
			summary_json TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(run_id, ts_code)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_t0_daily_tm_results_score ON t0_daily_time_machine_results(run_id, combined_return DESC);`,
		`CREATE TABLE IF NOT EXISTS data_daily_basic (
			ts_code TEXT NOT NULL,
			trade_date TEXT NOT NULL,
			close REAL NOT NULL DEFAULT 0,
			pe REAL NOT NULL DEFAULT 0,
			pe_ttm REAL NOT NULL DEFAULT 0,
			pb REAL NOT NULL DEFAULT 0,
			ps REAL NOT NULL DEFAULT 0,
			ps_ttm REAL NOT NULL DEFAULT 0,
			total_mv REAL NOT NULL DEFAULT 0,
			circ_mv REAL NOT NULL DEFAULT 0,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(ts_code, trade_date)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_data_daily_basic_date ON data_daily_basic(trade_date);`,
		`CREATE TABLE IF NOT EXISTS data_fina_indicator (
			ts_code TEXT NOT NULL,
			ann_date TEXT NOT NULL DEFAULT '',
			end_date TEXT NOT NULL,
			eps REAL NOT NULL DEFAULT 0,
			roe REAL NOT NULL DEFAULT 0,
			grossprofit_margin REAL NOT NULL DEFAULT 0,
			netprofit_margin REAL NOT NULL DEFAULT 0,
			debt_to_assets REAL NOT NULL DEFAULT 0,
			updated_at TEXT NOT NULL,
			PRIMARY KEY(ts_code, end_date)
		);`,
		`CREATE INDEX IF NOT EXISTS idx_data_fina_indicator_ts_end ON data_fina_indicator(ts_code, end_date);`,
		`CREATE TABLE IF NOT EXISTS market_limit_breakout_cache (
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
		`CREATE TABLE IF NOT EXISTS market_limit_breakout_cache_meta (
			cache_key TEXT PRIMARY KEY,
			item_count INTEGER NOT NULL DEFAULT 0,
			generated_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_market_limit_breakout_cache_rank ON market_limit_breakout_cache(cache_key, rank);`,
		`CREATE INDEX IF NOT EXISTS idx_market_limit_breakout_cache_date ON market_limit_breakout_cache(latest_date);`,
		`CREATE TABLE IF NOT EXISTS market_limit_momentum_cache (
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
		`CREATE TABLE IF NOT EXISTS market_limit_momentum_cache_meta (
			cache_key TEXT PRIMARY KEY,
			item_count INTEGER NOT NULL DEFAULT 0,
			generated_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_market_limit_momentum_cache_rank ON market_limit_momentum_cache(cache_key, rank);`,
		`CREATE INDEX IF NOT EXISTS idx_market_limit_momentum_cache_date ON market_limit_momentum_cache(trade_date);`,
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
		`CREATE TABLE IF NOT EXISTS rec_daily_recommendations (
			date TEXT PRIMARY KEY,
			generated_at TEXT NOT NULL,
			payload_json TEXT NOT NULL,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_rec_daily_recommendations_date ON rec_daily_recommendations(date);`,
		`CREATE TABLE IF NOT EXISTS eval_strategy_admission (
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
		`CREATE INDEX IF NOT EXISTS idx_eval_strategy_admission_run ON eval_strategy_admission(run_id);`,
		`CREATE INDEX IF NOT EXISTS idx_eval_strategy_admission_date ON eval_strategy_admission(start_date, end_date);`,
		`CREATE INDEX IF NOT EXISTS idx_eval_strategy_admission_strategy ON eval_strategy_admission(strategy);`,
		`CREATE INDEX IF NOT EXISTS idx_eval_strategy_admission_admission ON eval_strategy_admission(admission);`,
		`CREATE TABLE IF NOT EXISTS eval_portfolio_runs (
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
		`CREATE TABLE IF NOT EXISTS eval_portfolio_candidates (
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
		`CREATE INDEX IF NOT EXISTS idx_eval_portfolio_candidates_run_rank ON eval_portfolio_candidates(run_id, rank);`,
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
		`CREATE TABLE IF NOT EXISTS eval_data_snapshots (
			id TEXT PRIMARY KEY,
			subject_type TEXT NOT NULL,
			subject_id TEXT NOT NULL,
			snapshot_json TEXT NOT NULL DEFAULT '{}',
			created_at TEXT NOT NULL
		);`,
		`CREATE INDEX IF NOT EXISTS idx_eval_data_snapshots_subject ON eval_data_snapshots(subject_type, subject_id);`,
		`CREATE TABLE IF NOT EXISTS rec_hindsight (
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
		`CREATE INDEX IF NOT EXISTS idx_rec_hindsight_date ON rec_hindsight(recommendation_date);`,
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
		`CREATE TABLE IF NOT EXISTS trade_paper_log (
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
		`CREATE INDEX IF NOT EXISTS idx_trade_paper_log_date ON trade_paper_log(signal_date);`,
		`CREATE TABLE IF NOT EXISTS strategy_promotion_decisions (
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
		`CREATE INDEX IF NOT EXISTS idx_strategy_promotion_decisions_strategy ON strategy_promotion_decisions(strategy, strategy_version);`,
		`CREATE TABLE IF NOT EXISTS eval_walk_forward_windows (
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
		`CREATE INDEX IF NOT EXISTS idx_eval_walk_forward_windows_subject ON eval_walk_forward_windows(subject_type, subject_id);`,
		`CREATE TABLE IF NOT EXISTS eval_parameter_experiments (
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
		`CREATE INDEX IF NOT EXISTS idx_eval_parameter_experiments_strategy ON eval_parameter_experiments(strategy, strategy_version);`,
		`CREATE TABLE IF NOT EXISTS monitor_policy_support_signals (
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
		`CREATE TABLE IF NOT EXISTS monitor_policy_support_candidates (
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
		`CREATE INDEX IF NOT EXISTS idx_monitor_policy_support_candidates_score ON monitor_policy_support_candidates(trade_date, score DESC);`,
		`CREATE TABLE IF NOT EXISTS task_run_locks (
			name TEXT PRIMARY KEY,
			pid INTEGER NOT NULL,
			hostname TEXT NOT NULL,
			acquired_at TEXT NOT NULL,
			heartbeat TEXT NOT NULL,
			task TEXT
		);`,
		`CREATE TABLE IF NOT EXISTS task_run_status (
			task TEXT PRIMARY KEY,
			task_type TEXT NOT NULL DEFAULT '',
			state TEXT NOT NULL,
			idx INTEGER NOT NULL DEFAULT 0,
			total INTEGER NOT NULL DEFAULT 0,
			stage TEXT,
			name TEXT,
			message TEXT,
			worker_pid INTEGER,
			started_at TEXT,
			updated_at TEXT NOT NULL,
			finished_at TEXT
		);`,
		`CREATE TABLE IF NOT EXISTS portfolio_pool_summary (
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
		`INSERT OR IGNORE INTO portfolio_pool_summary (id, initial_cash, current_cash, total_assets, updated_at) VALUES (1, 500000, 500000, 500000, '');`,
		`CREATE TABLE IF NOT EXISTS portfolio_pool_holdings (
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
		`CREATE TABLE IF NOT EXISTS portfolio_pool_trades (
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
		`CREATE INDEX IF NOT EXISTS idx_portfolio_pool_trades_date ON portfolio_pool_trades(trade_date);`,
		`CREATE INDEX IF NOT EXISTS idx_portfolio_pool_trades_ts ON portfolio_pool_trades(ts_code);`,
	}
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
		return db.columnsExist("portfolio_pool_summary", "total_cost", "today_pct", "unrealized_pnl", "unrealized_pct", "realized_pnl", "cum_return", "n_closed", "total_fee") && db.columnsExist("portfolio_pool_trades", "fee", "net_amount")
	case 2:
		return db.columnsExist("portfolio_tm_trades", "is_new")
	case 3:
		return db.columnsExist("task_jobs", "parent_id", "group_run_id", "subtask_key", "subtask_name", "sequence", "total", "attempt", "max_attempts")
	case 4:
		return db.columnsExist("strategy_config_versions", "promotion_status", "validation_json")
	case 5:
		return db.columnsExist("eval_portfolio_runs", "validation_status", "validation_json") && db.columnsExist("eval_portfolio_candidates", "total_return", "excess_annual_return", "win_rate", "annual_volatility", "exit_architecture_type", "exit_architecture_label", "exit_architecture_json", "rebalance_freq", "market_regime_filter", "position_max_weight", "validation_status", "validation_json")
	case 6:
		return db.columnsExist("eval_strategy_admission", "admission_score", "month_count", "monthly_win_rate", "worst_month_return", "positive_3m_rate", "return_score", "drawdown_score", "risk_adjusted_score", "cost_score", "capacity_score", "stability_score", "independence_score")
	case 7:
		return db.columnsExist("task_run_status", "worker_pid")
	case 8:
		return db.columnsExist("task_run_status", "task_type")
	case 12:
		return db.columnsExist("t0_daily_candidates", "setup", "first_action", "reduce_price", "buy_price", "stop_price", "t_ratio", "plan_json")
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
				{table: "portfolio_pool_summary", name: "total_cost", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "portfolio_pool_summary", name: "today_pct", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "portfolio_pool_summary", name: "unrealized_pnl", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "portfolio_pool_summary", name: "unrealized_pct", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "portfolio_pool_summary", name: "realized_pnl", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "portfolio_pool_summary", name: "cum_return", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "portfolio_pool_summary", name: "n_closed", ddl: "INTEGER NOT NULL DEFAULT 0"},
				{table: "portfolio_pool_summary", name: "total_fee", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "portfolio_pool_trades", name: "fee", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "portfolio_pool_trades", name: "net_amount", ddl: "REAL NOT NULL DEFAULT 0"},
			}
			return db.addColumnsIfMissing(columns)
		}},
		{version: 2, name: "time_machine_trade_flags", up: func(db *DB) error {
			return db.addColumnsIfMissing([]columnMigration{{table: "portfolio_tm_trades", name: "is_new", ddl: "INTEGER NOT NULL DEFAULT 0"}})
		}},
		{version: 3, name: "evaluation_task_subtasks", up: func(db *DB) error {
			columns := []columnMigration{
				{table: "task_jobs", name: "parent_id", ddl: "TEXT"},
				{table: "task_jobs", name: "group_run_id", ddl: "TEXT"},
				{table: "task_jobs", name: "subtask_key", ddl: "TEXT"},
				{table: "task_jobs", name: "subtask_name", ddl: "TEXT"},
				{table: "task_jobs", name: "sequence", ddl: "INTEGER NOT NULL DEFAULT 0"},
				{table: "task_jobs", name: "total", ddl: "INTEGER NOT NULL DEFAULT 0"},
				{table: "task_jobs", name: "attempt", ddl: "INTEGER NOT NULL DEFAULT 0"},
				{table: "task_jobs", name: "max_attempts", ddl: "INTEGER NOT NULL DEFAULT 1"},
			}
			if err := db.addColumnsIfMissing(columns); err != nil {
				return err
			}
			return db.createEvaluationTaskIndexes()
		}},
		{version: 4, name: "strategy_version_validation", up: func(db *DB) error {
			return db.addColumnsIfMissing([]columnMigration{
				{table: "strategy_config_versions", name: "promotion_status", ddl: "TEXT NOT NULL DEFAULT 'research'"},
				{table: "strategy_config_versions", name: "validation_json", ddl: "TEXT NOT NULL DEFAULT '{}'"},
			})
		}},
		{version: 5, name: "portfolio_validation_columns", up: func(db *DB) error {
			columns := []columnMigration{
				{table: "eval_portfolio_runs", name: "validation_status", ddl: "TEXT NOT NULL DEFAULT ''"},
				{table: "eval_portfolio_runs", name: "validation_json", ddl: "TEXT NOT NULL DEFAULT '{}'"},
				{table: "eval_portfolio_candidates", name: "total_return", ddl: "REAL"},
				{table: "eval_portfolio_candidates", name: "excess_annual_return", ddl: "REAL"},
				{table: "eval_portfolio_candidates", name: "win_rate", ddl: "REAL"},
				{table: "eval_portfolio_candidates", name: "annual_volatility", ddl: "REAL"},
				{table: "eval_portfolio_candidates", name: "exit_architecture_type", ddl: "TEXT NOT NULL DEFAULT ''"},
				{table: "eval_portfolio_candidates", name: "exit_architecture_label", ddl: "TEXT NOT NULL DEFAULT ''"},
				{table: "eval_portfolio_candidates", name: "exit_architecture_json", ddl: "TEXT NOT NULL DEFAULT '{}'"},
				{table: "eval_portfolio_candidates", name: "rebalance_freq", ddl: "INTEGER NOT NULL DEFAULT 0"},
				{table: "eval_portfolio_candidates", name: "market_regime_filter", ddl: "TEXT NOT NULL DEFAULT ''"},
				{table: "eval_portfolio_candidates", name: "position_max_weight", ddl: "REAL"},
				{table: "eval_portfolio_candidates", name: "validation_status", ddl: "TEXT NOT NULL DEFAULT ''"},
				{table: "eval_portfolio_candidates", name: "validation_json", ddl: "TEXT NOT NULL DEFAULT '{}'"},
			}
			return db.addColumnsIfMissing(columns)
		}},
		{version: 6, name: "eval_strategy_admission_scores", up: func(db *DB) error {
			return db.migrateStrategyEvaluationSchema()
		}},
		{version: 7, name: "python_run_status_pid", up: func(db *DB) error {
			return db.addColumnsIfMissing([]columnMigration{
				{table: "task_run_status", name: "worker_pid", ddl: "INTEGER"},
			})
		}},
		{version: 8, name: "python_run_status_type", up: func(db *DB) error {
			if err := db.addColumnsIfMissing([]columnMigration{
				{table: "task_run_status", name: "task_type", ddl: "TEXT NOT NULL DEFAULT ''"},
			}); err != nil {
				return err
			}
			return db.backfillPyRunStatusTaskTypes()
		}},
		{version: 9, name: "drop_dataset_update_status_table", up: func(db *DB) error {
			if err := db.dropTableIfExists("data_dataset_update_status"); err != nil {
				return err
			}
			return db.dropTableIfExists("dataset_update_status")
		}},
		{version: 10, name: "schema_chinese_comments", up: func(db *DB) error {
			return db.applySchemaComments()
		}},
		{version: 11, name: "drop_state_team_tables", up: func(db *DB) error {
			for _, table := range []string{
				"monitor_state_team_holder_changes",
				"monitor_state_team_holder_snapshots",
				"state_team_holder_changes",
				"state_team_holder_snapshots",
			} {
				if err := db.dropTableIfExists(table); err != nil {
					return err
				}
			}
			_, err := db.conn.Exec(`DELETE FROM cfg_schema_comments WHERE table_name IN ('monitor_state_team_holder_changes', 'monitor_state_team_holder_snapshots', 'state_team_holder_changes', 'state_team_holder_snapshots')`)
			return err
		}},
		{version: 12, name: "t0_trader_plan_columns", up: func(db *DB) error {
			return db.addColumnsIfMissing([]columnMigration{
				{table: "t0_daily_candidates", name: "setup", ddl: "TEXT NOT NULL DEFAULT ''"},
				{table: "t0_daily_candidates", name: "first_action", ddl: "TEXT NOT NULL DEFAULT ''"},
				{table: "t0_daily_candidates", name: "reduce_price", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "t0_daily_candidates", name: "buy_price", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "t0_daily_candidates", name: "stop_price", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "t0_daily_candidates", name: "t_ratio", ddl: "REAL NOT NULL DEFAULT 0"},
				{table: "t0_daily_candidates", name: "plan_json", ddl: "LONGTEXT NOT NULL"},
			})
		}},
	}
}

func (db *DB) backfillPyRunStatusTaskTypes() error {
	_, err := db.conn.Exec(`
		UPDATE task_run_status
		SET task_type = CASE
			WHEN task = 'data_update' THEN 'data_update'
			WHEN task = 'daily_signal' THEN 'signal'
			WHEN task = 'limit_signal_evaluation' THEN 'evaluation'
			WHEN task IN ('limit_breakout', 'limit_up_momentum') THEN 'market_scan'
			WHEN task = 'policy_support_analysis' THEN 'analysis'
			ELSE 'python'
		END
		WHERE COALESCE(task_type, '') = ''`)
	return err
}

func (db *DB) dropTableIfExists(table string) error {
	_, err := db.conn.Exec(fmt.Sprintf("DROP TABLE IF EXISTS %s", quoteIdent(db.Backend(), table)))
	return err
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
		if _, err := db.conn.Exec(fmt.Sprintf("ALTER TABLE %s ADD COLUMN %s %s", quoteIdent(db.Backend(), column.table), quoteIdent(db.Backend(), column.name), column.ddl)); err != nil {
			return err
		}
		tableColumns[column.name] = true
	}
	return nil
}

func (db *DB) createEvaluationTaskIndexes() error {
	columns, err := db.tableColumns("task_jobs")
	if err != nil {
		return err
	}
	if !columns["parent_id"] {
		return fmt.Errorf("task_jobs.parent_id column is missing")
	}
	if _, err := db.conn.Exec(`CREATE INDEX IF NOT EXISTS idx_task_jobs_parent_id ON task_jobs(parent_id);`); err != nil {
		return err
	}
	if !columns["group_run_id"] {
		return fmt.Errorf("task_jobs.group_run_id column is missing")
	}
	if _, err := db.conn.Exec(`CREATE INDEX IF NOT EXISTS idx_task_jobs_group_run_id ON task_jobs(group_run_id);`); err != nil {
		return err
	}
	return nil
}

func (db *DB) tableExists(tableName string) (bool, error) {
	if db.IsMySQL() {
		var count int
		err := db.conn.QueryRow(
			`SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = ?`,
			tableName,
		).Scan(&count)
		return count > 0, err
	}
	var name string
	err := db.conn.QueryRow(
		`SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?`,
		tableName,
	).Scan(&name)
	if err == sql.ErrNoRows {
		return false, nil
	}
	return err == nil, err
}

func (db *DB) tableColumns(tableName string) (map[string]bool, error) {
	if db.IsMySQL() {
		rows, err := db.conn.Query(
			`SELECT column_name FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = ?`,
			tableName,
		)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		columns := map[string]bool{}
		for rows.Next() {
			var name string
			if err := rows.Scan(&name); err != nil {
				return nil, err
			}
			columns[name] = true
		}
		return columns, rows.Err()
	}
	rows, err := db.conn.Query(fmt.Sprintf(`PRAGMA table_info(%s)`, quoteIdent(db.Backend(), tableName)))
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
	columns, err := db.tableColumns("eval_strategy_admission")
	if err != nil {
		return err
	}
	if columns["run_id"] {
		return db.ensureStrategyEvaluationScoreColumns(columns)
	}

	_, err = db.conn.Exec(`
		ALTER TABLE eval_strategy_admission RENAME TO eval_strategy_admission_legacy;
		CREATE TABLE eval_strategy_admission (
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
		CREATE INDEX IF NOT EXISTS idx_eval_strategy_admission_run ON eval_strategy_admission(run_id);
		CREATE INDEX IF NOT EXISTS idx_eval_strategy_admission_date ON eval_strategy_admission(start_date, end_date);
		CREATE INDEX IF NOT EXISTS idx_eval_strategy_admission_strategy ON eval_strategy_admission(strategy);
		CREATE INDEX IF NOT EXISTS idx_eval_strategy_admission_admission ON eval_strategy_admission(admission);
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
		if _, err := db.conn.Exec(fmt.Sprintf("ALTER TABLE eval_strategy_admission ADD COLUMN %s %s", name, ddl)); err != nil {
			return err
		}
	}
	return nil
}
