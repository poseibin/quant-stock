package database

import (
	"database/sql"
	"fmt"
	"regexp"
	"strings"

	_ "github.com/go-sql-driver/mysql"
)

type MySQLBootstrapConfig struct {
	AdminDSN string
	Database string
	User     string
	Password string
	AppDSN   string
}

func BootstrapMySQL(cfg MySQLBootstrapConfig) error {
	if strings.TrimSpace(cfg.AdminDSN) == "" {
		return fmt.Errorf("mysql admin dsn is required")
	}
	if strings.TrimSpace(cfg.Database) == "" || strings.TrimSpace(cfg.User) == "" {
		return fmt.Errorf("mysql database and user are required")
	}
	admin, err := sql.Open("mysql", cfg.AdminDSN)
	if err != nil {
		return err
	}
	defer admin.Close()
	if err := admin.Ping(); err != nil {
		return fmt.Errorf("connect mysql admin: %w", err)
	}
	databaseName := quoteMySQLIdent(cfg.Database)
	userLiteral := quoteMySQLString(cfg.User)
	passwordLiteral := quoteMySQLString(cfg.Password)
	for _, stmt := range []string{
		fmt.Sprintf("CREATE DATABASE IF NOT EXISTS %s CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci", databaseName),
		fmt.Sprintf("CREATE USER IF NOT EXISTS %s@'localhost' IDENTIFIED BY %s", userLiteral, passwordLiteral),
		fmt.Sprintf("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", userLiteral, passwordLiteral),
		fmt.Sprintf("GRANT ALL PRIVILEGES ON %s.* TO %s@'localhost'", databaseName, userLiteral),
		fmt.Sprintf("GRANT ALL PRIVILEGES ON %s.* TO %s@'%%'", databaseName, userLiteral),
		"FLUSH PRIVILEGES",
	} {
		if _, err := admin.Exec(stmt); err != nil {
			return fmt.Errorf("mysql bootstrap %q: %w", stmt, err)
		}
	}
	if strings.TrimSpace(cfg.AppDSN) == "" {
		return nil
	}
	app, err := sql.Open("mysql", cfg.AppDSN)
	if err != nil {
		return err
	}
	defer app.Close()
	if err := app.Ping(); err != nil {
		return fmt.Errorf("connect mysql app database: %w", err)
	}
	return migrateMySQLSchema(app)
}

func migrateMySQLSchema(conn *sql.DB) error {
	db := Wrap(conn, BackendMySQL)
	if err := db.renameLegacyTables(); err != nil {
		return err
	}
	if _, err := conn.Exec(`CREATE TABLE IF NOT EXISTS schema_migrations (
		version BIGINT PRIMARY KEY,
		name VARCHAR(255) NOT NULL,
		applied_at VARCHAR(64) NOT NULL
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`); err != nil {
		return err
	}
	for _, stmt := range mysqlSchemaStatements() {
		if err := db.ExecSchemaStatement(stmt); err != nil {
			return fmt.Errorf("mysql schema: %w\n%s", err, stmt)
		}
	}
	return db.runSchemaMigrations()
}

func mysqlSchemaStatements() []string {
	out := make([]string, 0, len(baseSchemaStatements()))
	for _, stmt := range baseSchemaStatements() {
		out = append(out, mysqlizeSchemaStatement(stmt)...)
	}
	return out
}

func mysqlizeSchemaStatement(stmt string) []string {
	trimmed := strings.TrimSpace(stmt)
	if trimmed == "" {
		return nil
	}
	upper := strings.ToUpper(trimmed)
	if strings.Contains(upper, "WHERE IS_ACTIVE = 1") {
		return nil
	}
	out := trimmed
	out = strings.ReplaceAll(out, "CREATE UNIQUE INDEX IF NOT EXISTS", "CREATE UNIQUE INDEX")
	out = strings.ReplaceAll(out, "CREATE INDEX IF NOT EXISTS", "CREATE INDEX")
	out = strings.ReplaceAll(out, "INSERT OR IGNORE", "INSERT IGNORE")
	out = strings.ReplaceAll(out, "INTEGER PRIMARY KEY AUTOINCREMENT", "BIGINT PRIMARY KEY AUTO_INCREMENT")
	out = regexp.MustCompile(`(?i)\bINTEGER\b`).ReplaceAllString(out, "BIGINT")
	out = regexp.MustCompile(`(?i)\bREAL\b`).ReplaceAllString(out, "DOUBLE")
	out = regexp.MustCompile(`(?i)\bTEXT\s+NOT\s+NULL\s+DEFAULT\s+'[^']*'`).ReplaceAllString(out, "VARCHAR(255) NOT NULL DEFAULT ''")
	out = regexp.MustCompile(`(?i)\bTEXT\s+DEFAULT\s+'[^']*'`).ReplaceAllString(out, "VARCHAR(255) DEFAULT ''")
	out = regexp.MustCompile(`(?i)\bTEXT\s+NOT\s+NULL`).ReplaceAllString(out, "VARCHAR(255) NOT NULL")
	out = regexp.MustCompile(`(?i)\bTEXT\b`).ReplaceAllString(out, "VARCHAR(255)")
	for _, column := range []string{"config_json", "validation_json", "summary_json", "params_json", "payload_json", "result_json", "plan_json", "reasons_json", "risks_json", "rules_json", "metrics_json", "breakdown_json", "outcome_json"} {
		out = regexp.MustCompile("`?"+column+"`?\\s+VARCHAR\\(255\\)(\\s+NOT\\s+NULL)?(\\s+DEFAULT\\s+'[^']*')?").ReplaceAllStringFunc(out, func(fragment string) string {
			nullable := ""
			if strings.Contains(strings.ToUpper(fragment), "NOT NULL") {
				nullable = " NOT NULL"
			}
			return column + " LONGTEXT" + nullable
		})
	}
	out = strings.ReplaceAll(out, "data_market_files(file_path)", "data_market_files(file_path(191))")
	out = strings.ReplaceAll(out, "data_stock_basic(ts_code, symbol, name, industry)", "data_stock_basic(ts_code, symbol, name, industry)")
	return []string{out}
}

func (db *DB) execMySQLCreateIndexIfNeeded(statement string) (bool, error) {
	match := regexp.MustCompile(`(?is)^\s*CREATE\s+(UNIQUE\s+)?INDEX\s+` + "`?" + `([A-Za-z0-9_]+)` + "`?" + `\s+ON\s+` + "`?" + `([A-Za-z0-9_]+)` + "`?" + `\s*\((.+)\)\s*;?\s*$`).FindStringSubmatch(statement)
	if match == nil {
		return false, nil
	}
	indexName := match[2]
	tableName := match[3]
	var count int
	err := db.conn.QueryRow(
		`SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = ? AND index_name = ?`,
		tableName,
		indexName,
	).Scan(&count)
	if err != nil {
		return true, err
	}
	if count > 0 {
		return true, nil
	}
	_, err = db.conn.Exec(statement)
	return true, err
}

func quoteMySQLIdent(value string) string {
	return "`" + strings.ReplaceAll(value, "`", "``") + "`"
}

func quoteMySQLString(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "''") + "'"
}
