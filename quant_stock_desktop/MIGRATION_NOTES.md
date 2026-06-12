# 架构现状备忘（MySQL-only）

桌面端和 Python worker 统一使用 MySQL 作为业务元数据与任务状态库。

## 当前约定

- 默认库名：`quant_stock`
- 默认应用账号：`quant_stock`
- 默认 DSN：`quant_stock:quant_stock@tcp(127.0.0.1:3306)/quant_stock?parseTime=true&charset=utf8mb4&loc=Local`
- Go 端入口：`internal/common/database`
- Python 端入口：`quant_stock_core/common/infra/db.py`
- 任务状态、推荐结果、评估结果、策略配置版本均写入 MySQL。

## 迁移原则

- 新代码不要引入文件型元数据库。
- Python worker 通过 `DESKTOP_DB_DSN` / `DESKTOP_MYSQL_DSN` 连接 MySQL。
- 历史兼容参数如果仍存在，只能作为 no-op 传参，不得重新拼本地数据库文件路径。
