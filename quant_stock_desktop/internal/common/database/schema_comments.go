package database

import (
	"database/sql"
	"fmt"
	"regexp"
	"strings"
	"time"
)

func (db *DB) applySchemaComments() error {
	if db == nil || db.conn == nil {
		return nil
	}
	if err := db.createSchemaCommentCatalog(); err != nil {
		return err
	}
	tables, err := db.schemaTableNames()
	if err != nil {
		return err
	}
	now := time.Now().Format(time.RFC3339)
	for _, table := range tables {
		tableComment := schemaTableComment(table)
		if err := db.upsertSchemaComment("table", table, "", tableComment, now); err != nil {
			return err
		}
		if _, err := db.conn.Exec(fmt.Sprintf("ALTER TABLE %s COMMENT = %s", quoteIdent(db.Backend(), table), quoteMySQLString(tableComment))); err != nil {
			return fmt.Errorf("comment table %s: %w", table, err)
		}
		columns, err := db.schemaColumnNames(table)
		if err != nil {
			return err
		}
		for _, column := range columns {
			columnComment := schemaColumnComment(table, column)
			if err := db.upsertSchemaComment("column", table, column, columnComment, now); err != nil {
				return err
			}
			if err := db.applyMySQLColumnComment(table, column, columnComment); err != nil {
				return err
			}
		}
	}
	return nil
}

func (db *DB) createSchemaCommentCatalog() error {
	_, err := db.conn.Exec(`CREATE TABLE IF NOT EXISTS cfg_schema_comments (
		object_type VARCHAR(32) NOT NULL,
		table_name VARCHAR(191) NOT NULL,
		column_name VARCHAR(191) NOT NULL DEFAULT '',
		comment_text LONGTEXT NOT NULL,
		updated_at VARCHAR(64) NOT NULL,
		PRIMARY KEY(object_type, table_name, column_name)
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='数据库表和字段中文说明元数据'`)
	return err
}

func (db *DB) upsertSchemaComment(objectType, table, column, comment, updatedAt string) error {
	_, err := db.conn.Exec(
		db.UpsertSQL(
			"cfg_schema_comments",
			[]string{"object_type", "table_name", "column_name", "comment_text", "updated_at"},
			[]string{"object_type", "table_name", "column_name"},
			[]string{"comment_text", "updated_at"},
		),
		objectType, table, column, comment, updatedAt,
	)
	return err
}

func (db *DB) schemaTableNames() ([]string, error) {
	rows, err := db.conn.Query(`SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		out = append(out, name)
	}
	return out, rows.Err()
}

func (db *DB) schemaColumnNames(table string) ([]string, error) {
	rows, err := db.conn.Query(`SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION`, table)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		out = append(out, name)
	}
	return out, rows.Err()
}

func (db *DB) applyMySQLColumnComment(table, column, comment string) error {
	var (
		field      string
		columnType string
		collation  sql.NullString
		nullable   string
		key        string
		def        sql.NullString
		extra      string
		privileges string
		oldComment string
	)
	row := db.conn.QueryRow(fmt.Sprintf("SHOW FULL COLUMNS FROM %s WHERE Field = ?", quoteIdent(db.Backend(), table)), column)
	if err := row.Scan(&field, &columnType, &collation, &nullable, &key, &def, &extra, &privileges, &oldComment); err != nil {
		return fmt.Errorf("read mysql column %s.%s: %w", table, column, err)
	}
	definition := fmt.Sprintf("%s %s", quoteIdent(db.Backend(), column), columnType)
	if strings.EqualFold(nullable, "NO") {
		definition += " NOT NULL"
	} else {
		definition += " NULL"
	}
	if def.Valid {
		definition += " DEFAULT " + mysqlDefaultLiteral(def.String)
	}
	if strings.Contains(strings.ToLower(extra), "auto_increment") {
		definition += " AUTO_INCREMENT"
	}
	definition += " COMMENT " + quoteMySQLString(comment)
	_, err := db.conn.Exec(fmt.Sprintf("ALTER TABLE %s MODIFY COLUMN %s", quoteIdent(db.Backend(), table), definition))
	if err != nil {
		return fmt.Errorf("comment column %s.%s: %w", table, column, err)
	}
	return nil
}

func mysqlDefaultLiteral(value string) string {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return "''"
	}
	lower := strings.ToLower(trimmed)
	if lower == "null" || strings.Contains(lower, "current_timestamp") {
		return trimmed
	}
	if regexp.MustCompile(`^-?\d+(\.\d+)?$`).MatchString(trimmed) {
		return trimmed
	}
	return quoteMySQLString(value)
}

func schemaTableComment(table string) string {
	if comment, ok := tableComments()[table]; ok {
		return comment
	}
	switch {
	case strings.HasPrefix(table, "cfg_"):
		return "配置模块数据表：" + table
	case strings.HasPrefix(table, "task_"):
		return "任务调度模块数据表：" + table
	case strings.HasPrefix(table, "data_"):
		return "数据管理模块数据表：" + table
	case strings.HasPrefix(table, "strategy_"):
		return "策略治理模块数据表：" + table
	case strings.HasPrefix(table, "eval_"):
		return "评估研究模块数据表：" + table
	case strings.HasPrefix(table, "portfolio_"):
		return "组合和模拟交易模块数据表：" + table
	case strings.HasPrefix(table, "market_"):
		return "市场信号模块数据表：" + table
	case strings.HasPrefix(table, "monitor_"):
		return "监控分析模块数据表：" + table
	case strings.HasPrefix(table, "rec_"):
		return "推荐复盘模块数据表：" + table
	default:
		return "业务数据表：" + table
	}
}

func schemaColumnComment(table, column string) string {
	if tableMap, ok := tableColumnComments()[table]; ok {
		if comment, ok := tableMap[column]; ok {
			return comment
		}
	}
	if comment, ok := commonColumnComments()[column]; ok {
		return comment
	}
	switch {
	case strings.HasSuffix(column, "_json"):
		return "JSON结构化扩展信息"
	case strings.HasSuffix(column, "_at"):
		return "业务时间戳"
	case strings.HasSuffix(column, "_date"):
		return "业务日期"
	case strings.HasSuffix(column, "_count"):
		return "数量统计值"
	case strings.HasSuffix(column, "_score"):
		return "评分指标"
	case strings.HasSuffix(column, "_status"):
		return "业务状态"
	case strings.HasSuffix(column, "_id"):
		return "业务对象ID"
	case strings.HasSuffix(column, "_type"):
		return "业务类型"
	case strings.HasSuffix(column, "_rate"):
		return "比率指标"
	case strings.HasSuffix(column, "_return"):
		return "收益率指标"
	case strings.HasSuffix(column, "_pnl"):
		return "盈亏金额"
	default:
		return "业务字段：" + column
	}
}

func tableComments() map[string]string {
	return map[string]string{
		"cfg_app_settings":                  "应用级配置键值表",
		"cfg_schema_comments":               "数据库表和字段中文说明元数据",
		"data_daily_bars":                   "日线行情查询表",
		"data_daily_basic":                  "每日估值和市值指标查询表",
		"data_etl_files":                    "本地数据ETL文件级版本日志",
		"data_etl_versions":                 "本地数据ETL版本日志",
		"data_fina_indicator":               "财务指标查询表",
		"data_market_files":                 "本地行情和财务数据文件索引",
		"data_stock_basic":                  "股票基础信息查询表",
		"eval_data_snapshots":               "评估对象的数据快照留痕",
		"eval_parameter_experiments":        "模型参数实验记录",
		"eval_portfolio_candidates":         "组合优化候选方案明细",
		"eval_portfolio_runs":               "组合优化运行批次",
		"eval_strategy_admission":           "策略准入评估结果",
		"eval_walk_forward_windows":         "Walk-forward 分窗验证结果",
		"portfolio_pool_holdings":           "模拟组合当前持仓",
		"portfolio_pool_summary":            "模拟组合账户汇总",
		"portfolio_pool_trades":             "模拟组合成交流水",
		"portfolio_tm_positions":            "时光机回放持仓明细",
		"portfolio_tm_snapshots":            "时光机回放账户快照",
		"portfolio_tm_trades":               "时光机回放交易明细",
		"rec_daily_recommendations":         "每日推荐结果",
		"rec_hindsight":                     "推荐结果事后复盘",
		"research_reports":                  "研究报告与验证说明",
		"risk_exposure_snapshots":           "组合风险暴露快照",
		"schema_migrations":                 "数据库结构迁移记录",
		"strategy_config_versions":          "策略配置版本库",
		"strategy_promotion_decisions":      "策略晋级/降级建议记录",
		"strategy_validation_reviews":       "策略或组合验证审查记录",
		"task_jobs":                         "统一任务和子任务明细表",
		"task_run_locks":                    "任务运行分布式锁和心跳",
		"task_run_status":                   "任务运行汇总状态",
		"trade_paper_log":                   "纸面交易信号执行日志",
	}
}

func commonColumnComments() map[string]string {
	return map[string]string{
		"id":                  "主键ID",
		"key":                 "配置键",
		"value":               "配置值",
		"name":                "名称",
		"label":               "展示名称",
		"strategy":            "策略标识",
		"strategy_version":    "策略配置版本号",
		"version":             "版本号",
		"run_id":              "运行批次ID",
		"task":                "任务标识",
		"task_type":           "任务类型",
		"status":              "任务或业务状态",
		"state":               "运行状态",
		"progress":            "任务进度比例",
		"idx":                 "当前处理序号",
		"total":               "总处理数量",
		"stage":               "当前阶段",
		"message":             "状态消息",
		"worker_pid":          "工作进程ID",
		"pid":                 "进程ID",
		"hostname":            "主机名",
		"acquired_at":         "锁获取时间",
		"heartbeat":           "进程心跳时间",
		"params_json":         "任务参数JSON",
		"summary_json":        "任务结果摘要JSON",
		"payload_json":        "业务载荷JSON",
		"metrics_json":        "指标结果JSON",
		"validation_json":     "验证结果JSON",
		"gates_json":          "准入门槛检查JSON",
		"weights_json":        "权重配置JSON",
		"evidence_json":       "证据明细JSON",
		"outcome_json":        "事后结果JSON",
		"industry_json":       "行业暴露JSON",
		"strategy_json":       "策略暴露JSON",
		"config_json":         "配置内容JSON",
		"result_path":         "结果文件路径",
		"log_path":            "日志文件路径",
		"worker_type":         "工作器类型",
		"external_run_id":     "外部运行ID",
		"error_message":       "错误信息",
		"parent_id":           "父任务ID",
		"group_run_id":        "任务组运行ID",
		"subtask_key":         "子任务业务键",
		"subtask_name":        "子任务名称",
		"sequence":            "子任务顺序号",
		"attempt":             "当前重试次数",
		"max_attempts":        "最大重试次数",
		"created_at":          "创建时间",
		"queued_at":           "入队时间",
		"started_at":          "开始时间",
		"finished_at":         "结束时间",
		"updated_at":          "更新时间",
		"generated_at":        "生成时间",
		"activated_at":        "启用时间",
		"evaluated_at":        "评估时间",
		"ts_code":             "股票代码",
		"trade_date":          "交易日期",
		"signal_date":         "信号日期",
		"recommendation_date": "推荐日期",
		"start_date":          "开始日期",
		"end_date":            "结束日期",
		"exec_date":           "执行日期",
		"ann_date":            "公告日期",
		"as_of_date":          "快照日期",
		"subject_type":        "对象类型",
		"subject_id":          "对象ID",
		"report_type":         "报告类型",
		"title":               "标题",
		"model":               "模型名称",
		"content_md":          "Markdown 内容",
		"reason":              "原因说明",
		"note":                "备注",
		"source":              "来源",
		"enabled":             "是否启用",
		"is_active":           "是否当前启用版本",
		"recommendation":      "建议动作",
		"admission":           "准入建议",
		"error":               "错误摘要",
		"score":               "综合评分",
		"rank":                "排序名次",
		"benchmark":           "基准标的",
		"baseline":            "基线策略",
		"objective":           "优化目标",
		"strategies":          "策略列表",
		"cash":                "现金余额",
		"initial_cash":        "初始资金",
		"current_cash":        "当前现金",
		"market_value":        "持仓市值",
		"total_assets":        "总资产",
		"total_cost":          "总成本",
		"shares":              "股数",
		"avg_cost":            "平均成本",
		"last_price":          "最新价格",
		"price":               "成交或估值价格",
		"amount":              "成交金额",
		"weight":              "组合权重",
		"target_weight":       "目标权重",
		"actual_weight":       "实际权重",
		"fee":                 "交易费用",
		"net_amount":          "扣费后金额",
		"side":                "交易方向",
		"action":              "操作动作",
		"exit_reason":         "退出原因",
		"hold_days":           "持仓天数",
		"open_date":           "建仓日期",
		"n_holdings":          "持仓数量",
		"n_eval":              "评估样本数",
		"n_days":              "交易天数",
		"top_n":               "候选保留数量",
		"file_path":           "文件路径",
		"file_size":           "文件大小",
		"row_count":           "数据行数",
		"data_type":           "数据类型",
		"partition_name":      "分区名称",
	}
}

func tableColumnComments() map[string]map[string]string {
	return map[string]map[string]string{
		"cfg_schema_comments": {
			"object_type":  "注释对象类型：table 或 column",
			"table_name":   "表名",
			"column_name":  "字段名；表注释为空字符串",
			"comment_text": "中文说明内容",
		},
		"eval_portfolio_candidates": {
			"candidate_id":            "候选组合ID",
			"exit_architecture_type":  "退出架构类型",
			"exit_architecture_label": "退出架构展示名称",
		},
		"rec_hindsight": {
			"horizon_days": "复盘持有周期天数",
			"next_date":    "复盘结束交易日",
		},
		"schema_migrations": {
			"version":    "迁移版本号",
			"name":       "迁移名称",
			"applied_at": "迁移应用时间",
		},
	}
}
