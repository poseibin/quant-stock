#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LH_DIR="$(cd "$ROOT_DIR/.." && pwd)"
CORE_DIR="$LH_DIR/quant_stock_core"
PY="$CORE_DIR/.venv/bin/python"
SCRIPT="$CORE_DIR/scripts/daily_signal.py"

if [ ! -x "$PY" ]; then
  echo "ERROR: venv python not found at $PY"
  echo "先建 venv: python3 -m venv $CORE_DIR/.venv && $CORE_DIR/.venv/bin/pip install -r $CORE_DIR/requirements.txt"
  exit 1
fi

if [ ! -f "$SCRIPT" ]; then
  echo "ERROR: daily_signal.py not found at $SCRIPT"
  exit 1
fi

: "${DATA_ROOT:=$LH_DIR/data_store}"
: "${DESKTOP_DB_PATH:=$DATA_ROOT/meta.db}"
: "${DESKTOP_CONFIG_DB_PATH:=$DESKTOP_DB_PATH}"
: "${INITIAL_CASH:=500000}"
: "${REBALANCE_FREQ:=5}"
: "${QUANT_CPU_LIMIT:=2}"

export DATA_ROOT DESKTOP_DB_PATH DESKTOP_CONFIG_DB_PATH INITIAL_CASH REBALANCE_FREQ QUANT_CPU_LIMIT

if [ ! -d "$DATA_ROOT" ]; then
  echo "ERROR: DATA_ROOT not exists: $DATA_ROOT"
  echo "用法: DATA_ROOT=/path/to/data_store bash $0 [args...]"
  exit 1
fi

mkdir -p "$(dirname "$DESKTOP_DB_PATH")"

echo "[run_signal] PY=$PY"
echo "[run_signal] CORE=$CORE_DIR"
echo "[run_signal] DATA_ROOT=$DATA_ROOT"
echo "[run_signal] DESKTOP_DB_PATH=$DESKTOP_DB_PATH"
echo "[run_signal] INITIAL_CASH=$INITIAL_CASH REBALANCE_FREQ=$REBALANCE_FREQ QUANT_CPU_LIMIT=$QUANT_CPU_LIMIT"
echo "[run_signal] args: $*"
echo "------------------------------------------------------------"

cd "$CORE_DIR"
exec "$PY" "$SCRIPT" "$@"
