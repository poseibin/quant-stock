#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
CORE_DIR="$REPO_ROOT/quant_stock_core"
DESKTOP_DIR="$REPO_ROOT/quant_stock_desktop"
FRONTEND_DIR="$DESKTOP_DIR/frontend"
WORKER_DIST_DIR="$CORE_DIR/dist/quant_worker"
PACKAGE_DIR="$REPO_ROOT/dist"
PACKAGE_ZIP="$PACKAGE_DIR/QuantStockDesktop-macos-$(uname -m).zip"

usage() {
  cat <<'EOF'
Usage:
  ./build.sh start     Start Wails development mode.
  ./build.sh restart   Stop current dev processes, then start Wails development mode.
  ./build.sh package   Build worker, build app, embed worker, sign, and create zip.

Aliases:
  ./build.sh dev       Same as start.
  ./build.sh build     Same as package.
EOF
}

find_wails() {
  if command -v wails >/dev/null 2>&1; then
    command -v wails
    return
  fi

  local gopath
  gopath="$(go env GOPATH 2>/dev/null || true)"
  if [ -n "$gopath" ] && [ -x "$gopath/bin/wails" ]; then
    echo "$gopath/bin/wails"
    return
  fi

  echo ""
}

require_wails() {
  WAILS_BIN="$(find_wails)"
  if [ -z "$WAILS_BIN" ]; then
    echo "ERROR: wails command not found."
    echo "Install it first:"
    echo "  go install github.com/wailsapp/wails/v2/cmd/wails@latest"
    exit 1
  fi
}

check_common_tools() {
  require_wails
  echo "==> Tools"
  echo "    Wails: $WAILS_BIN"
  echo "    Go: $(go version)"
  echo "    Node: $(node --version)"
}

ensure_frontend_deps() {
  cd "$FRONTEND_DIR"
  if [ ! -d "node_modules" ]; then
    echo "==> Installing frontend dependencies"
    npm install
  fi
}

sync_app_icon() {
  mkdir -p "$DESKTOP_DIR/build"
  if [ -f "$DESKTOP_DIR/appicon.png" ]; then
    echo "==> Sync app icon"
    COPYFILE_DISABLE=1 cp "$DESKTOP_DIR/appicon.png" "$DESKTOP_DIR/build/appicon.png"
  fi
}

ensure_core_venv() {
  cd "$CORE_DIR"
  if [ ! -d ".venv" ]; then
    echo "==> Creating core venv"
    python3 -m venv .venv
  fi

  echo "==> Installing Python dependencies"
  .venv/bin/pip install -q -r requirements.txt
}

build_worker() {
  ensure_core_venv

  cd "$CORE_DIR"
  echo "==> Building Python worker"
  .venv/bin/pip install -q pyinstaller
  .venv/bin/pyinstaller --clean --noconfirm quant_worker.spec

  if [ ! -x "$WORKER_DIST_DIR/quant_worker" ]; then
    echo "ERROR: worker binary not found at $WORKER_DIST_DIR/quant_worker"
    exit 1
  fi
}

run_dev() {
  check_common_tools
  ensure_frontend_deps
  sync_app_icon

  echo "==> Starting Wails dev"
  echo "    Data default: ~/Library/Application Support/QuantStockDesktop/data_store"
  echo "    Worker: quant_stock_core/.venv/bin/python"
  cd "$DESKTOP_DIR"
  "$WAILS_BIN" dev
}

kill_matching_processes() {
  local label="$1"
  local pattern="$2"
  local pids

  pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
  if [ -z "$pids" ]; then
    return
  fi

  echo "==> Stopping $label"
  echo "$pids" | xargs kill 2>/dev/null || true
  sleep 1

  pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
}

stop_dev() {
  kill_matching_processes "Wails dev" "wails.*dev.*$DESKTOP_DIR|$DESKTOP_DIR.*wails.*dev"
  kill_matching_processes "frontend dev server" "vite.*$FRONTEND_DIR|$FRONTEND_DIR.*vite"
  kill_matching_processes "QuantStockDesktop dev app" "QuantStockDesktop.*$DESKTOP_DIR|$DESKTOP_DIR.*QuantStockDesktop"
}

restart_dev() {
  stop_dev
  run_dev
}

package_app() {
  local app_bundle
  local app_resources
  local worker_resources

  check_common_tools
  build_worker
  ensure_frontend_deps
  sync_app_icon

  echo "==> Building Wails app"
  cd "$DESKTOP_DIR"
  "$WAILS_BIN" build -clean

  app_bundle="$(find "$DESKTOP_DIR/build/bin" -maxdepth 1 -type d -name '*.app' | head -n 1)"
  if [ ! -d "$app_bundle" ]; then
    echo "ERROR: app bundle not found under $DESKTOP_DIR/build/bin"
    exit 1
  fi

  app_resources="$app_bundle/Contents/Resources"
  worker_resources="$app_resources/quant_worker"

  echo "==> Embedding quant_worker"
  rm -rf "$worker_resources"
  mkdir -p "$worker_resources"
  COPYFILE_DISABLE=1 cp -R "$WORKER_DIST_DIR"/. "$worker_resources"/
  chmod +x "$worker_resources/quant_worker"

  find "$app_bundle" -name '._*' -delete

  echo "==> Signing app bundle"
  codesign --force --deep --sign - "$app_bundle"

  echo "==> Creating distributable zip"
  mkdir -p "$PACKAGE_DIR"
  rm -f "$PACKAGE_ZIP"
  (
    cd "$(dirname "$app_bundle")"
    zip -qryX "$PACKAGE_ZIP" "$(basename "$app_bundle")"
  )

  echo "==> Done"
  echo "    App: $app_bundle"
  echo "    Zip: $PACKAGE_ZIP"
}

mode="${1:-}"
case "$mode" in
  start | dev)
    run_dev
    ;;
  restart)
    restart_dev
    ;;
  package | build)
    package_app
    ;;
  -h | --help | help)
    usage
    ;;
  "")
    usage
    exit 1
    ;;
  *)
    echo "ERROR: unknown mode: $mode"
    echo
    usage
    exit 1
    ;;
esac
