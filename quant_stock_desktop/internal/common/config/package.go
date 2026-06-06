package config

import "strings"

var PackagedDatabaseBackend = "mysql"
var PackagedMySQLDSN = ""
var PackagedMySQLAdminDSN = "root:rootpass@tcp(127.0.0.1:3306)/?parseTime=true&charset=utf8mb4&loc=Local&multiStatements=true"
var PackagedMySQLDatabase = "quant_stock"
var PackagedMySQLUser = "quant_stock"
var PackagedMySQLPassword = "quant_stock"

const DefaultLocalMySQLDSN = "quant_stock:quant_stock@tcp(127.0.0.1:3306)/quant_stock?parseTime=true&charset=utf8mb4&loc=Local"

func PackagedDatabaseConfig() (string, string) {
	backend := strings.ToLower(strings.TrimSpace(PackagedDatabaseBackend))
	if backend == "" {
		backend = "sqlite"
	}
	dsn := strings.TrimSpace(PackagedMySQLDSN)
	if backend == "mysql" && dsn == "" {
		dsn = DefaultLocalMySQLDSN
	}
	if backend != "mysql" {
		dsn = ""
	}
	return backend, dsn
}

func applyPackagedDatabaseConfig(settings Settings) Settings {
	backend, packagedDSN := PackagedDatabaseConfig()
	settings.DatabaseBackend = backend
	settings.MySQLDSN = strings.TrimSpace(settings.MySQLDSN)
	if backend == "mysql" {
		if settings.MySQLDSN == "" {
			settings.MySQLDSN = packagedDSN
		}
	} else {
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
