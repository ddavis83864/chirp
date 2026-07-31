#!/bin/bash
# Packages a built CHIRP.app into a drag-and-drop DMG installer.
#
# Usage: ./packaging/macos/build_dmg.sh <path-to-CHIRP.app> <output.dmg> [volume-name]
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
    echo "error: build_dmg.sh must run on macOS." >&2
    exit 1
fi

APP_PATH="${1:?usage: build_dmg.sh <path-to-CHIRP.app> <output.dmg> [volume-name]}"
OUT_DMG="${2:?usage: build_dmg.sh <path-to-CHIRP.app> <output.dmg> [volume-name]}"
VOLUME_NAME="${3:-CHIRP}"

if [ ! -d "$APP_PATH" ]; then
    echo "error: $APP_PATH is not a directory" >&2
    exit 1
fi

STAGING_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGING_DIR"' EXIT

cp -R "$APP_PATH" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"

rm -f "$OUT_DMG"
mkdir -p "$(dirname "$OUT_DMG")"

hdiutil create \
    -volname "$VOLUME_NAME" \
    -srcfolder "$STAGING_DIR" \
    -ov \
    -format UDZO \
    "$OUT_DMG"

echo "Built: $OUT_DMG"
