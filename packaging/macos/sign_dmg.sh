#!/bin/bash
# Signs a built DMG with the same Developer ID Application certificate used
# for the .app inside it. Must run after build_dmg.sh, using the same
# ephemeral-keychain identity already unlocked by sign.sh in the same job
# (this script does not re-import the certificate; it assumes sign.sh has
# already run in this job and left the identity available in the current
# keychain search list).
#
# Usage: ./packaging/macos/sign_dmg.sh <path-to.dmg>
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
    echo "error: sign_dmg.sh must run on macOS." >&2
    exit 1
fi

DMG_PATH="${1:?usage: sign_dmg.sh <path-to.dmg>}"
: "${MACOS_SIGNING_IDENTITY:?MACOS_SIGNING_IDENTITY is required}"

if [ ! -f "$DMG_PATH" ]; then
    echo "error: $DMG_PATH does not exist" >&2
    exit 1
fi

echo "Signing $DMG_PATH..."
codesign --force --timestamp --sign "$MACOS_SIGNING_IDENTITY" "$DMG_PATH"

echo "Verifying DMG signature..."
codesign --verify --verbose=4 "$DMG_PATH"
codesign -dv --verbose=4 "$DMG_PATH"

echo "Signed: $DMG_PATH"
