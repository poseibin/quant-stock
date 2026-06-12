# Packaging Configuration

The desktop package is MySQL-only. Runtime settings display and edit the MySQL
DSN used by the app and Python workers.

Default package (MySQL, local DSN):

```bash
wails build
```

MySQL package metadata can be injected the same way. If no DSN is injected, the
packaged default is local MySQL:

```text
quant_stock:quant_stock@tcp(127.0.0.1:3306)/quant_stock?parseTime=true&charset=utf8mb4&loc=Local
```

Startup bootstrap for a MySQL package uses these defaults:

```text
admin_dsn: root:rootpass@tcp(127.0.0.1:3306)/?parseTime=true&charset=utf8mb4&loc=Local&multiStatements=true
database:  quant_stock
user:      quant_stock
password:  quant_stock
```

On startup, the app attempts to:

1. Connect with `admin_dsn`.
2. Create the `database` if it does not exist.
3. Create `user` for `localhost` and `%` if missing.
4. Grant the user privileges on the database.
5. Connect with the app DSN and create the project metadata tables.

Build a MySQL package with the default local DSN:

```bash
wails build -ldflags "-X quant_stock_desktop/internal/common/config.PackagedDatabaseBackend=mysql"
```

Build a MySQL package with an injected DSN:

```bash
wails build -ldflags "-X quant_stock_desktop/internal/common/config.PackagedDatabaseBackend=mysql -X 'quant_stock_desktop/internal/common/config.PackagedMySQLDSN=user:pass@tcp(127.0.0.1:3306)/quant_stock?parseTime=true&charset=utf8mb4'"
```

Override bootstrap credentials:

```bash
wails build -ldflags "-X quant_stock_desktop/internal/common/config.PackagedDatabaseBackend=mysql -X 'quant_stock_desktop/internal/common/config.PackagedMySQLAdminDSN=root:rootpass@tcp(127.0.0.1:3306)/?parseTime=true&charset=utf8mb4&loc=Local&multiStatements=true' -X quant_stock_desktop/internal/common/config.PackagedMySQLDatabase=quant_stock -X quant_stock_desktop/internal/common/config.PackagedMySQLUser=quant_stock -X quant_stock_desktop/internal/common/config.PackagedMySQLPassword=quant_stock"
```

In a MySQL package, the backend remains fixed to MySQL, but the DSN can be
edited in the settings page when no runtime work is active.
