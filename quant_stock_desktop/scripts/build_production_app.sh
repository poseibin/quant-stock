#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_DIR="$ROOT_DIR/quant_stock_desktop"
DIST_DIR="$ROOT_DIR/dist"
BUILD_APP="$APP_DIR/build/bin/quant-stock-desktop.app"
DIST_APP_NAME="quant-stock-desktop.app"
DIST_APP="$DIST_DIR/$DIST_APP_NAME"
INFO_PLIST="$DIST_APP/Contents/Info.plist"
BUNDLE_ID="com.quantstock.productionworkspace"
PRODUCT_NAME="Quant Stock Production Workspace"
PRODUCT_VERSION="1.0.0-profit-arena"
PRODUCT_COPYRIGHT="Copyright Quant Stock"
cd "$APP_DIR"
wails build

rm -rf "$DIST_APP"
mkdir -p "$DIST_DIR"
cp -R "$BUILD_APP" "$DIST_APP"
rm -f "$DIST_DIR/QuantStockDesktop-macos-arm64.zip" "$DIST_DIR/.DS_Store"

/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier $BUNDLE_ID" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleName $PRODUCT_NAME" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $PRODUCT_VERSION" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $PRODUCT_VERSION" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Set :NSHumanReadableCopyright $PRODUCT_COPYRIGHT" "$INFO_PLIST"

identifier="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$INFO_PLIST")"
name="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleName' "$INFO_PLIST")"
version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$INFO_PLIST")"

if [[ "$identifier" != "$BUNDLE_ID" ]]; then
  echo "unexpected CFBundleIdentifier: $identifier" >&2
  exit 1
fi
if [[ "$name" != "$PRODUCT_NAME" ]]; then
  echo "unexpected CFBundleName: $name" >&2
  exit 1
fi
if [[ "$version" != "$PRODUCT_VERSION" ]]; then
  echo "unexpected CFBundleShortVersionString: $version" >&2
  exit 1
fi

rm -rf "$BUILD_APP"

"$APP_DIR/scripts/verify_production_app.sh"
echo "Production app ready: $DIST_APP"
echo "Bundle: $identifier · $name · $version"
