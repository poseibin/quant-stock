package config

import "strings"

var PackagedDatabaseBackend = "mysql"
var PackagedMySQLDSN = ""
var PackagedMySQLAdminDSN = ""
var PackagedMySQLDatabase = "quant_stock"
var PackagedMySQLUser = "quant_stock"
var PackagedMySQLPassword = "quant_stock"

const DefaultLocalMySQLDSN = "quant_stock:quant_stock@tcp(127.0.0.1:3306)/quant_stock?parseTime=true&charset=utf8mb4&loc=Local"

func PackagedDatabaseConfig() (string, string) {
	backend := strings.ToLower(strings.TrimSpace(PackagedDatabaseBackend))
	if backend == "" {
		backend = "mysql"
	}
	if backend != "mysql" {
		backend = "mysql"
	}
	dsn := strings.TrimSpace(PackagedMySQLDSN)
	if dsn == "" {
		dsn = DefaultLocalMySQLDSN
	}
	return backend, dsn
}

func applyPackagedDatabaseConfig(settings Settings) Settings {
	backend, packagedDSN := PackagedDatabaseConfig()
	settings.DatabaseBackend = backend
	settings.MySQLDSN = strings.TrimSpace(settings.MySQLDSN)
	if settings.MySQLDSN == "" {
		settings.MySQLDSN = packagedDSN
	}
	return settings
}

type MySQLBootstrapConfig struct {
	AdminDSN string
	Database string
	User     string
	Password string
	AppDSN   string
}

func PackagedMySQLBootstrapConfig(appDSN string) MySQLBootstrapConfig {
	return MySQLBootstrapConfig{
		AdminDSN: strings.TrimSpace(PackagedMySQLAdminDSN),
		Database: mysqlIdent(PackagedMySQLDatabase, "quant_stock"),
		User:     mysqlIdent(PackagedMySQLUser, "quant_stock"),
		Password: PackagedMySQLPassword,
		AppDSN:   strings.TrimSpace(appDSN),
	}
}

func mysqlIdent(value string, fallback string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return fallback
	}
	return value
}
