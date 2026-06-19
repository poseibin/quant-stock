#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_DIR="$ROOT_DIR/quant_stock_desktop"
DIST_DIR="$ROOT_DIR/dist"
DATA_STORE_DIR="$ROOT_DIR/data_store"
DIST_APP_NAME="quant-stock-desktop.app"
DIST_APP="$DIST_DIR/$DIST_APP_NAME"
INFO_PLIST="$DIST_APP/Contents/Info.plist"
BUNDLE_EXECUTABLE="$DIST_APP/Contents/MacOS/QuantStockDesktop"
BUNDLE_ID="com.quantstock.productionworkspace"
PRODUCT_NAME="Quant Stock Production Workspace"
PRODUCT_VERSION="1.0.0-profit-arena"
RETIRED_DESKTOP_TOKEN="desktop""2"
RETIRED_DESKTOP_TOKEN_CAPITALIZED="Desktop""2"
FORBIDDEN_FORMAL_SOURCE_PATTERN="${RETIRED_DESKTOP_TOKEN}|${RETIRED_DESKTOP_TOKEN_CAPITALIZED}|quant-stock-desktop 2|/Users/tiger|GolandProjects/lh|quant-stock-desktop-frontend@0\\.1\\.0|涨停预警|横盘|做T|T0|t0_daily"
FORBIDDEN_BUNDLE_TEXT_PATTERN="${RETIRED_DESKTOP_TOKEN}|${RETIRED_DESKTOP_TOKEN_CAPITALIZED}|quant-stock-desktop 2|涨停预警|横盘|做T|评估中心|托底监测"
REQUIRED_BUNDLE_LABELS=(总览 数据管理 收益擂台 持仓管理 任务中心 定时通知 因子研究留档 个股研究 设置)
MYSQL_HOST="127.0.0.1"
MYSQL_USER="quant_stock"
MYSQL_PASSWORD="quant_stock"
MYSQL_DATABASE="quant_stock"
FORMAL_SOURCE_GUARD_PATHS=(
  "$APP_DIR/config.json"
  "$APP_DIR/app.go"
  "$APP_DIR/frontend/src"
  "$APP_DIR/frontend/package.json"
  "$APP_DIR/wails.json"
)
LEGACY_META_DB="$HOME/Library/Application Support/QuantStockDesktop/data_store/meta.db"
FORBIDDEN_DATASTORE_NAME_PATTERN="limit_up|limit_breakout|t0_daily|T0|做T|涨停|横盘"

fail() {
  echo "production verification failed: $*" >&2
  exit 1
}

[[ -d "$DIST_APP" ]] || fail "missing dist app: $DIST_APP"
[[ -f "$INFO_PLIST" ]] || fail "missing Info.plist: $INFO_PLIST"
[[ -x "$BUNDLE_EXECUTABLE" ]] || fail "missing executable: $BUNDLE_EXECUTABLE"

identifier="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$INFO_PLIST")"
name="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleName' "$INFO_PLIST")"
short_version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$INFO_PLIST")"
bundle_version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$INFO_PLIST")"

[[ "$identifier" == "$BUNDLE_ID" ]] || fail "unexpected bundle id: $identifier"
[[ "$name" == "$PRODUCT_NAME" ]] || fail "unexpected bundle name: $name"
[[ "$short_version" == "$PRODUCT_VERSION" ]] || fail "unexpected short version: $short_version"
[[ "$bundle_version" == "$PRODUCT_VERSION" ]] || fail "unexpected bundle version: $bundle_version"

if find "$DIST_DIR" -maxdepth 1 -mindepth 1 ! -name "$DIST_APP_NAME" -print -quit | grep -q .; then
  find "$DIST_DIR" -maxdepth 1 -mindepth 1 >&2
  fail "unexpected extra artifact in dist"
fi

if find "$APP_DIR/build/bin" -maxdepth 1 -name "*.app" -print -quit 2>/dev/null | grep -q .; then
  find "$APP_DIR/build/bin" -maxdepth 1 -name "*.app" >&2
  fail "unexpected temporary app artifact in build/bin"
fi

if rg -n "$FORBIDDEN_FORMAL_SOURCE_PATTERN" "${FORMAL_SOURCE_GUARD_PATHS[@]}" >/tmp/quant_stock_formal_source_guard.log; then
  cat /tmp/quant_stock_formal_source_guard.log >&2
  fail "formal desktop source contains retired desktop/strategy residue"
fi
if ! rg -q "只允许创建收益擂台训练/推理任务" "$APP_DIR/app.go"; then
  fail "CreateTask is missing production guard for retired model training strategies"
fi
if ! rg -q "ensureProfitArenaProductionState" "$APP_DIR/app.go"; then
  fail "desktop startup is missing profit arena production state alignment"
fi

if LC_ALL=C grep -a -E -q "$FORBIDDEN_BUNDLE_TEXT_PATTERN" "$BUNDLE_EXECUTABLE"; then
  LC_ALL=C grep -a -E -o "$FORBIDDEN_BUNDLE_TEXT_PATTERN" "$BUNDLE_EXECUTABLE" | sort -u >&2
  fail "production bundle contains retired menu/desktop text"
fi

for label in "${REQUIRED_BUNDLE_LABELS[@]}"; do
  if ! LC_ALL=C grep -a -q "$label" "$BUNDLE_EXECUTABLE"; then
    fail "production bundle is missing required menu label: $label"
  fi
done

[[ ! -f "$LEGACY_META_DB" ]] || fail "legacy sqlite state still exists: $LEGACY_META_DB"

if find "$DATA_STORE_DIR" -maxdepth 5 \( -path "*limit_up*" -o -path "*limit_breakout*" -o -path "*t0_daily*" -o -path "*T0*" -o -path "*做T*" -o -path "*涨停*" -o -path "*横盘*" \) -print -quit | grep -q .; then
  find "$DATA_STORE_DIR" -maxdepth 5 \( -path "*limit_up*" -o -path "*limit_breakout*" -o -path "*t0_daily*" -o -path "*T0*" -o -path "*做T*" -o -path "*涨停*" -o -path "*横盘*" \) -print >&2
  fail "data_store contains retired strategy artifacts"
fi

command -v mysql >/dev/null 2>&1 || fail "mysql client is required for production verification"
legacy_table_count="$(
  mysql \
    --protocol=TCP \
    -h "$MYSQL_HOST" \
    -u "$MYSQL_USER" \
    "-p$MYSQL_PASSWORD" \
    -D "$MYSQL_DATABASE" \
    -N \
    -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND (table_name LIKE '%limit_up%' OR table_name LIKE '%limit_breakout%' OR table_name LIKE '%t0_daily%' OR table_name LIKE '%horizontal%' OR table_name LIKE '%sideways%');" \
    2>/tmp/quant_stock_verify_mysql.err \
    || true
)"
if [[ -z "$legacy_table_count" ]]; then
  cat /tmp/quant_stock_verify_mysql.err >&2
  fail "cannot inspect production mysql table names"
fi
if [[ "$legacy_table_count" != "0" ]]; then
  mysql \
    --protocol=TCP \
    -h "$MYSQL_HOST" \
    -u "$MYSQL_USER" \
    "-p$MYSQL_PASSWORD" \
    -D "$MYSQL_DATABASE" \
    -N \
    -e "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE() AND (table_name LIKE '%limit_up%' OR table_name LIKE '%limit_breakout%' OR table_name LIKE '%t0_daily%' OR table_name LIKE '%horizontal%' OR table_name LIKE '%sideways%') ORDER BY table_name;" \
    >&2 \
    || true
  fail "production mysql contains retired strategy tables"
fi
retired_strategy_count="$(
  mysql \
    --protocol=TCP \
    -h "$MYSQL_HOST" \
    -u "$MYSQL_USER" \
    "-p$MYSQL_PASSWORD" \
    -D "$MYSQL_DATABASE" \
    -N \
    -e "SELECT COUNT(*) FROM strategy_config_versions WHERE strategy <> 'profit_arena_model';" \
    2>/tmp/quant_stock_verify_mysql.err \
    || true
)"
if [[ -z "$retired_strategy_count" ]]; then
  cat /tmp/quant_stock_verify_mysql.err >&2
  fail "cannot inspect production mysql strategy_config_versions"
fi
if [[ "$retired_strategy_count" != "0" ]]; then
  mysql \
    --protocol=TCP \
    -h "$MYSQL_HOST" \
    -u "$MYSQL_USER" \
    "-p$MYSQL_PASSWORD" \
    -D "$MYSQL_DATABASE" \
    -N \
    -e "SELECT strategy, COUNT(*) FROM strategy_config_versions WHERE strategy <> 'profit_arena_model' GROUP BY strategy ORDER BY strategy;" \
    >&2 \
    || true
  fail "production mysql contains retired strategy versions"
fi
legacy_task_count="$(
  mysql \
    --protocol=TCP \
    -h "$MYSQL_HOST" \
    -u "$MYSQL_USER" \
    "-p$MYSQL_PASSWORD" \
    -D "$MYSQL_DATABASE" \
    -N \
    -e "SELECT COUNT(*) FROM task_jobs WHERE LOWER(CONCAT_WS(' ', task_type, name, params_json, external_run_id)) LIKE '%limit_breakout%' OR LOWER(CONCAT_WS(' ', task_type, name, params_json, external_run_id)) LIKE '%limit_up%' OR LOWER(CONCAT_WS(' ', task_type, name, params_json, external_run_id)) LIKE '%horizontal%' OR LOWER(CONCAT_WS(' ', task_type, name, params_json, external_run_id)) LIKE '%sideways%' OR LOWER(CONCAT_WS(' ', task_type, name, params_json, external_run_id)) LIKE '%t0_daily%' OR CONCAT_WS(' ', task_type, name, params_json, external_run_id) LIKE '%涨停%' OR CONCAT_WS(' ', task_type, name, params_json, external_run_id) LIKE '%横盘%' OR LOWER(CONCAT_WS(' ', task_type, name, params_json, external_run_id)) LIKE '%做t%';" \
    2>/tmp/quant_stock_verify_mysql.err \
    || true
)"
if [[ -z "$legacy_task_count" ]]; then
  cat /tmp/quant_stock_verify_mysql.err >&2
  fail "cannot inspect production mysql task_jobs"
fi
if [[ "$legacy_task_count" != "0" ]]; then
  fail "production mysql contains retired strategy task_jobs"
fi
legacy_status_count="$(
  mysql \
    --protocol=TCP \
    -h "$MYSQL_HOST" \
    -u "$MYSQL_USER" \
    "-p$MYSQL_PASSWORD" \
    -D "$MYSQL_DATABASE" \
    -N \
    -e "SELECT COUNT(*) FROM task_run_status WHERE LOWER(CONCAT_WS(' ', task, task_type, state, stage, name, message)) LIKE '%limit_breakout%' OR LOWER(CONCAT_WS(' ', task, task_type, state, stage, name, message)) LIKE '%limit_up%' OR LOWER(CONCAT_WS(' ', task, task_type, state, stage, name, message)) LIKE '%horizontal%' OR LOWER(CONCAT_WS(' ', task, task_type, state, stage, name, message)) LIKE '%sideways%' OR LOWER(CONCAT_WS(' ', task, task_type, state, stage, name, message)) LIKE '%t0_daily%' OR CONCAT_WS(' ', task, task_type, state, stage, name, message) LIKE '%涨停%' OR CONCAT_WS(' ', task, task_type, state, stage, name, message) LIKE '%横盘%' OR LOWER(CONCAT_WS(' ', task, task_type, state, stage, name, message)) LIKE '%做t%';" \
    2>/tmp/quant_stock_verify_mysql.err \
    || true
)"
if [[ -z "$legacy_status_count" ]]; then
  cat /tmp/quant_stock_verify_mysql.err >&2
  fail "cannot inspect production mysql task_run_status"
fi
if [[ "$legacy_status_count" != "0" ]]; then
  fail "production mysql contains retired strategy task_run_status rows"
fi
retired_active_model_count="$(
  mysql \
    --protocol=TCP \
    -h "$MYSQL_HOST" \
    -u "$MYSQL_USER" \
    "-p$MYSQL_PASSWORD" \
    -D "$MYSQL_DATABASE" \
    -N \
    -e "SELECT COUNT(*) FROM strategy_model_active WHERE strategy <> 'profit_arena_model';" \
    2>/tmp/quant_stock_verify_mysql.err \
    || true
)"
if [[ -z "$retired_active_model_count" ]]; then
  cat /tmp/quant_stock_verify_mysql.err >&2
  fail "cannot inspect production mysql strategy_model_active"
fi
if [[ "$retired_active_model_count" != "0" ]]; then
  fail "production mysql contains retired active model pointers"
fi
retired_validation_count="$(
  mysql \
    --protocol=TCP \
    -h "$MYSQL_HOST" \
    -u "$MYSQL_USER" \
    "-p$MYSQL_PASSWORD" \
    -D "$MYSQL_DATABASE" \
    -N \
    -e "SELECT COUNT(*) FROM strategy_model_validation_results WHERE strategy REGEXP 'limit|t0|horizontal|sideways';" \
    2>/tmp/quant_stock_verify_mysql.err \
    || true
)"
if [[ -z "$retired_validation_count" ]]; then
  cat /tmp/quant_stock_verify_mysql.err >&2
  fail "cannot inspect production mysql strategy_model_validation_results"
fi
if [[ "$retired_validation_count" != "0" ]]; then
  fail "production mysql contains retired strategy validation results"
fi
retired_observation_count="$(
  mysql \
    --protocol=TCP \
    -h "$MYSQL_HOST" \
    -u "$MYSQL_USER" \
    "-p$MYSQL_PASSWORD" \
    -D "$MYSQL_DATABASE" \
    -N \
    -e "SELECT (SELECT COUNT(*) FROM strategy_observation_pool WHERE strategy NOT IN ('ml_factor_ranker')) + (SELECT COUNT(*) FROM strategy_observation_events WHERE strategy NOT IN ('ml_factor_ranker'));" \
    2>/tmp/quant_stock_verify_mysql.err \
    || true
)"
if [[ -z "$retired_observation_count" ]]; then
  cat /tmp/quant_stock_verify_mysql.err >&2
  fail "cannot inspect production mysql strategy observation tables"
fi
if [[ "$retired_observation_count" != "0" ]]; then
  fail "production mysql contains retired strategy observation rows"
fi
profit_arena_health="$(
  mysql \
    --protocol=TCP \
    -h "$MYSQL_HOST" \
    -u "$MYSQL_USER" \
    "-p$MYSQL_PASSWORD" \
    -D "$MYSQL_DATABASE" \
    -N \
    -e "SELECT CONCAT(
      (SELECT COUNT(*) FROM strategy_model_active WHERE strategy = 'profit_arena_model'),
      '|',
      (SELECT COUNT(*) FROM strategy_arena_champions WHERE strategy_id = 'profit_arena_model'),
      '|',
      COALESCE((SELECT a.run_id = c.champion_run_id FROM strategy_model_active a JOIN strategy_arena_champions c ON c.strategy_id = a.strategy WHERE a.strategy = 'profit_arena_model' ORDER BY c.updated_at DESC LIMIT 1), 0),
      '|',
      (SELECT COUNT(*) FROM profit_arena_runs),
      '|',
      COALESCE((SELECT COUNT(*) FROM profit_arena_predictions WHERE trade_date = (SELECT MAX(trade_date) FROM profit_arena_predictions)), 0),
      '|',
      COALESCE((SELECT a.run_id = p.run_id
        FROM strategy_model_active a
        JOIN (
          SELECT run_id
          FROM profit_arena_predictions
          WHERE trade_date = (SELECT MAX(trade_date) FROM profit_arena_predictions)
          GROUP BY run_id
          ORDER BY COUNT(*) DESC
          LIMIT 1
        ) p ON 1=1
        WHERE a.strategy = 'profit_arena_model'
        LIMIT 1), 0)
    );" \
    2>/tmp/quant_stock_verify_mysql.err \
    || true
)"
if [[ -z "$profit_arena_health" ]]; then
  cat /tmp/quant_stock_verify_mysql.err >&2
  fail "cannot inspect production mysql profit arena health"
fi
IFS='|' read -r active_count champion_count active_match arena_run_count latest_prediction_count active_prediction_match <<< "$profit_arena_health"
[[ "$active_count" == "1" ]] || fail "profit arena active pointer is missing or duplicated"
[[ "$champion_count" != "0" ]] || fail "profit arena champion is missing"
[[ "$active_match" == "1" ]] || fail "profit arena active pointer does not match champion"
[[ "$arena_run_count" != "0" ]] || fail "profit arena has no training runs"
[[ "$latest_prediction_count" != "0" ]] || fail "profit arena latest prediction snapshot is empty"
[[ "$active_prediction_match" == "1" ]] || fail "profit arena latest prediction run does not match active pointer"

rogue_processes=""
while IFS= read -r pid; do
  [[ -z "$pid" ]] && continue
  command_path="$(ps -p "$pid" -o command= || true)"
  if [[ "$command_path" != "$DIST_APP/Contents/MacOS/QuantStockDesktop" ]]; then
    rogue_processes+="$pid $command_path"$'\n'
  fi
done < <(pgrep -x QuantStockDesktop || true)
if [[ -n "$rogue_processes" ]]; then
  echo "$rogue_processes" >&2
  fail "unexpected QuantStockDesktop process outside production app"
fi

echo "Production verification passed: $DIST_APP"
echo "Bundle: $identifier · $name · $short_version"
