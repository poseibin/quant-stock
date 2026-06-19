#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST_APP="$ROOT_DIR/dist/quant-stock-desktop.app"
INFO_PLIST="$DIST_APP/Contents/Info.plist"
BUNDLE_ID="com.quantstock.productionworkspace"
PRODUCT_NAME="Quant Stock Production Workspace"
LEGACY_SUPPORT_DIR="$HOME/Library/Application Support/QuantStockDesktop"
LEGACY_META_DB="$LEGACY_SUPPORT_DIR/data_store/meta.db"

if [[ ! -d "$DIST_APP" ]]; then
  echo "production app is missing: $DIST_APP" >&2
  echo "run quant_stock_desktop/scripts/build_production_app.sh first" >&2
  exit 1
fi

identifier="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$INFO_PLIST")"
name="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleName' "$INFO_PLIST")"
if [[ "$identifier" != "$BUNDLE_ID" ]]; then
  echo "refuse to open unexpected bundle id: $identifier" >&2
  exit 1
fi
if [[ "$name" != "$PRODUCT_NAME" ]]; then
  echo "refuse to open unexpected app name: $name" >&2
  exit 1
fi

if [[ -f "$LEGACY_META_DB" ]]; then
  legacy_target="$HOME/Library/Application Support/QuantStockDesktop.legacy.$(date +%Y%m%d%H%M%S)"
  mv "$LEGACY_SUPPORT_DIR" "$legacy_target"
  echo "Quarantined legacy desktop state: $legacy_target"
fi

osascript -e 'tell application "Quant Stock Production Workspace" to quit' >/dev/null 2>&1 || true
osascript -e 'tell application "QuantStockDesktop" to quit' >/dev/null 2>&1 || true
pkill -x QuantStockDesktop >/dev/null 2>&1 || true
sleep 1
open "$DIST_APP"

official_pid=""
for _ in {1..20}; do
  official_pid="$(pgrep -f "$DIST_APP/Contents/MacOS/QuantStockDesktop" | head -1 || true)"
  if [[ -n "$official_pid" ]]; then
    break
  fi
  sleep 0.5
done

if [[ -z "$official_pid" ]]; then
  echo "production app did not start from expected path: $DIST_APP" >&2
  exit 1
fi

rogue_processes=""
while IFS= read -r pid; do
  [[ -z "$pid" ]] && continue
  command_path="$(ps -p "$pid" -o command= || true)"
  if [[ "$command_path" != "$DIST_APP/Contents/MacOS/QuantStockDesktop" ]]; then
    rogue_processes+="$pid $command_path"$'\n'
  fi
done < <(pgrep -x QuantStockDesktop || true)
if [[ -n "$rogue_processes" ]]; then
  echo "unexpected QuantStockDesktop process outside production app:" >&2
  echo "$rogue_processes" >&2
  exit 1
fi

echo "Opened production app: $DIST_APP"
echo "Bundle: $identifier · $name"
echo "PID: $official_pid"
