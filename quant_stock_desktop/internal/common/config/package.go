package config

import (
	"os"
	"path/filepath"
	"strings"
)

var PackagedDatabaseBackend = "mysql"
var PackagedMySQLDSN = ""
var PackagedMySQLAdminDSN = ""
var PackagedMySQLDatabase = "quant_stock"
var PackagedMySQLUser = "quant_stock"
var PackagedMySQLPassword = "quant_stock"

const DefaultLocalMySQLDSN = "quant_stock:quant_stock@tcp(127.0.0.1:3306)/quant_stock?parseTime=true&charset=utf8mb4&loc=Local"

type databaseFileConfig struct {
	DatabaseBackend string
	MySQLDSN        string
	MySQLAdminDSN   string
	MySQLDatabase   string
	MySQLUser       string
	MySQLPassword   string
	TushareToken    string
	LLMProvider     string
	OpenAIToken     string
	OpenAIModel     string
	DeepSeekToken   string
	DeepSeekModel   string
	WechatWebhook   string
	WechatUsers     []string
}

func PackagedDatabaseConfig() (string, string) {
	fileCfg, _ := loadDatabaseFileConfig()
	return packagedDatabaseConfig(fileCfg)
}

func applyPackagedDatabaseConfig(settings Settings) Settings {
	fileCfg, _ := loadDatabaseFileConfig()
	backend, packagedDSN := packagedDatabaseConfig(fileCfg)
	settings.DatabaseBackend = backend
	settings.MySQLDSN = packagedDSN
	if fileCfg.TushareToken != "" {
		settings.TushareToken = fileCfg.TushareToken
	}
	if fileCfg.LLMProvider != "" {
		settings.LLMProvider = fileCfg.LLMProvider
	}
	if fileCfg.OpenAIToken != "" {
		settings.OpenAIToken = fileCfg.OpenAIToken
	}
	if fileCfg.OpenAIModel != "" {
		settings.OpenAIModel = fileCfg.OpenAIModel
	}
	if fileCfg.DeepSeekToken != "" {
		settings.DeepSeekToken = fileCfg.DeepSeekToken
	}
	if fileCfg.DeepSeekModel != "" {
		settings.DeepSeekModel = fileCfg.DeepSeekModel
	}
	if fileCfg.WechatWebhook != "" {
		settings.StrategySchedule.WechatWebhook = fileCfg.WechatWebhook
	}
	if len(fileCfg.WechatUsers) > 0 {
		settings.StrategySchedule.WechatUsers = fileCfg.WechatUsers
	}
	return settings
}

func packagedDatabaseConfig(fileCfg databaseFileConfig) (string, string) {
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
	if nextBackend := strings.ToLower(strings.TrimSpace(fileCfg.DatabaseBackend)); nextBackend == "mysql" {
		backend = nextBackend
	}
	if nextDSN := strings.TrimSpace(fileCfg.MySQLDSN); nextDSN != "" {
		dsn = nextDSN
	}
	return backend, dsn
}

type MySQLBootstrapConfig struct {
	AdminDSN string
	Database string
	User     string
	Password string
	AppDSN   string
}

func PackagedMySQLBootstrapConfig(appDSN string) MySQLBootstrapConfig {
	fileCfg, _ := loadDatabaseFileConfig()
	adminDSN := firstNonEmpty(fileCfg.MySQLAdminDSN, PackagedMySQLAdminDSN)
	database := mysqlIdent(firstNonEmpty(fileCfg.MySQLDatabase, PackagedMySQLDatabase), "quant_stock")
	user := mysqlIdent(firstNonEmpty(fileCfg.MySQLUser, PackagedMySQLUser), "quant_stock")
	password := firstNonEmpty(fileCfg.MySQLPassword, PackagedMySQLPassword)
	return MySQLBootstrapConfig{
		AdminDSN: strings.TrimSpace(adminDSN),
		Database: database,
		User:     user,
		Password: password,
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

func loadDatabaseFileConfig() (databaseFileConfig, bool) {
	paths := databaseConfigPaths()
	for _, path := range paths {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		if cfg, ok := parseDatabaseConfigText(string(data)); ok {
			return cfg, true
		}
	}
	return databaseFileConfig{}, false
}

func databaseConfigPaths() []string {
	paths := []string{}
	if cwd, err := os.Getwd(); err == nil && strings.TrimSpace(cwd) != "" {
		paths = append(paths, filepath.Join(cwd, "config.toml"))
		paths = append(paths, filepath.Join(cwd, "quant_stock_desktop", "config.toml"))
	}
	return paths
}

func parseDatabaseConfigText(text string) (databaseFileConfig, bool) {
	var cfg databaseFileConfig
	section := ""
	for _, rawLine := range strings.Split(text, "\n") {
		line := strings.TrimSpace(rawLine)
		if line == "" || strings.HasPrefix(line, "#") || strings.HasPrefix(line, ";") {
			continue
		}
		if strings.HasPrefix(line, "[") && strings.Contains(line, "]") {
			section = normalizeConfigKey(strings.TrimSpace(strings.TrimSuffix(strings.TrimPrefix(line, "["), "]")))
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		key = scopedConfigKey(section, key)
		value = cleanConfigValue(value)
		switch key {
		case "DATABASE_BACKEND":
			cfg.DatabaseBackend = value
		case "DATABASE_DSN", "DATABASE_MYSQL_DSN":
			cfg.MySQLDSN = value
		case "DATABASE_ADMIN_DSN":
			cfg.MySQLAdminDSN = value
		case "DATABASE_DATABASE", "DATABASE_NAME":
			cfg.MySQLDatabase = value
		case "DATABASE_USER":
			cfg.MySQLUser = value
		case "DATABASE_PASSWORD":
			cfg.MySQLPassword = value
		case "DATA_TUSHARE_TOKEN":
			cfg.TushareToken = value
		case "LLM_PROVIDER", "AI_PROVIDER":
			cfg.LLMProvider = value
		case "OPENAI_TOKEN", "OPENAI_API_KEY":
			cfg.OpenAIToken = value
		case "OPENAI_MODEL":
			cfg.OpenAIModel = value
		case "DEEPSEEK_TOKEN":
			cfg.DeepSeekToken = value
		case "DEEPSEEK_MODEL":
			cfg.DeepSeekModel = value
		case "WECHAT_WEBHOOK":
			cfg.WechatWebhook = value
		case "WECHAT_USERS":
			cfg.WechatUsers = splitConfigList(value)
		}
	}
	return cfg, cfg.DatabaseBackend != "" || cfg.MySQLDSN != "" || cfg.MySQLAdminDSN != "" ||
		cfg.MySQLDatabase != "" || cfg.MySQLUser != "" || cfg.MySQLPassword != "" ||
		cfg.TushareToken != "" || cfg.LLMProvider != "" || cfg.OpenAIToken != "" || cfg.OpenAIModel != "" ||
		cfg.DeepSeekToken != "" || cfg.DeepSeekModel != "" ||
		cfg.WechatWebhook != "" || len(cfg.WechatUsers) > 0
}

func normalizeConfigKey(value string) string {
	value = strings.TrimSpace(value)
	value = strings.TrimPrefix(value, "export ")
	value = strings.Trim(value, "\"'")
	value = strings.ReplaceAll(value, ".", "_")
	value = strings.ReplaceAll(value, "-", "_")
	return strings.ToUpper(value)
}

func scopedConfigKey(section string, key string) string {
	key = normalizeConfigKey(key)
	if section == "" {
		return key
	}
	return section + "_" + key
}

func cleanConfigValue(value string) string {
	value = strings.TrimSpace(value)
	if cut := strings.Index(value, " #"); cut >= 0 {
		value = strings.TrimSpace(value[:cut])
	}
	if cut := strings.Index(value, " ;"); cut >= 0 {
		value = strings.TrimSpace(value[:cut])
	}
	value = strings.TrimSuffix(value, ",")
	return strings.Trim(strings.TrimSpace(value), "\"'")
}

func splitConfigList(value string) []string {
	value = strings.TrimSpace(value)
	value = strings.Trim(value, "[]")
	parts := strings.FieldsFunc(value, func(r rune) bool {
		return r == ',' || r == '，' || r == '\n' || r == '\t' || r == ' '
	})
	out := make([]string, 0, len(parts))
	for _, part := range parts {
		item := strings.Trim(strings.TrimSpace(part), "\"'")
		if item != "" {
			out = append(out, strings.TrimPrefix(item, "@"))
		}
	}
	return out
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}
