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
		if _, err := conn.Exec(stmt); err != nil {
			return fmt.Errorf("mysql schema: %w\n%s", err, stmt)
		}
	}
	return db.runSchemaMigrations()
}

func mysqlSchemaStatements() []string {
	out := make([]string, 0)
	for _, stmt := range sqliteBaseSchemaStatements() {
		converted, ok := sqliteStatementToMySQL(stmt)
		if ok {
			out = append(out, converted)
		}
	}
	return out
}

func sqliteStatementToMySQL(stmt string) (string, bool) {
	s := strings.TrimSpace(stmt)
	if s == "" {
		return "", false
	}
	upper := strings.ToUpper(s)
	if strings.HasPrefix(upper, "CREATE UNIQUE INDEX") || strings.HasPrefix(upper, "CREATE INDEX") {
		return "", false
	}
	if strings.HasPrefix(upper, "INSERT OR IGNORE") {
		return strings.Replace(s, "INSERT OR IGNORE", "INSERT IGNORE", 1), true
	}
	if !strings.HasPrefix(upper, "CREATE TABLE") {
		return "", false
	}
	s = strings.TrimSpace(strings.TrimSuffix(s, ";"))
	s = strings.TrimSpace(strings.TrimSuffix(s, ")"))
	s = strings.ReplaceAll(s, "INTEGER PRIMARY KEY AUTOINCREMENT", "BIGINT PRIMARY KEY AUTO_INCREMENT")
	s = strings.ReplaceAll(s, "INTEGER PRIMARY KEY", "BIGINT PRIMARY KEY")
	s = regexp.MustCompile(`\bINTEGER\b`).ReplaceAllString(s, "BIGINT")
	s = regexp.MustCompile(`\bREAL\b`).ReplaceAllString(s, "DOUBLE")
	lines := strings.Split(s, "\n")
	for i, line := range lines {
		lines[i] = mysqlColumnLine(line)
	}
	s = strings.Join(lines, "\n")
	return s + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci", true
}

func mysqlColumnLine(line string) string {
	trimmed := strings.TrimSpace(line)
	if trimmed == "" || strings.HasPrefix(strings.ToUpper(trimmed), "CREATE TABLE") {
		return line
	}
	if strings.HasPrefix(strings.ToUpper(trimmed), "PRIMARY KEY") {
		return quoteMySQLConstraintColumns(line)
	}
	if strings.HasPrefix(strings.ToUpper(trimmed), "UNIQUE") {
		return quoteMySQLConstraintColumns(line)
	}
	parts := strings.Fields(trimmed)
	if len(parts) < 2 {
		return line
	}
	column := strings.Trim(parts[0], "`,")
	line = strings.Replace(line, parts[0], quoteMySQLIdent(column), 1)
	if strings.ToUpper(parts[1]) != "TEXT" {
		return line
	}
	mysqlType := "VARCHAR(191)"
	if strings.Contains(column, "json") || strings.Contains(column, "message") ||
		strings.Contains(column, "reason") || strings.Contains(column, "note") ||
		strings.Contains(column, "payload") || strings.Contains(column, "config") ||
		strings.Contains(column, "value") {
		mysqlType = "LONGTEXT"
	}
	line = strings.Replace(line, "TEXT", mysqlType, 1)
	if mysqlType == "LONGTEXT" {
		line = strings.ReplaceAll(line, " NOT NULL DEFAULT ''", " NOT NULL")
		line = strings.ReplaceAll(line, " NOT NULL DEFAULT '{}'", " NOT NULL")
	}
	return line
}

func quoteMySQLConstraintColumns(line string) string {
	start := strings.Index(line, "(")
	end := strings.LastIndex(line, ")")
	if start < 0 || end <= start {
		return line
	}
	columns := strings.Split(line[start+1:end], ",")
	for i, column := range columns {
		columns[i] = quoteMySQLIdent(strings.Trim(strings.TrimSpace(column), "`"))
	}
	return line[:start+1] + strings.Join(columns, ", ") + line[end:]
}

func quoteMySQLIdent(value string) string {
	return "`" + strings.ReplaceAll(value, "`", "``") + "`"
}

func quoteMySQLString(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "''") + "'"
}
