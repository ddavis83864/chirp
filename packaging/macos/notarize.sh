#!/bin/bash
# Submits a signed CHIRP.app (as a zip) or DMG to Apple notarization and
# staples the resulting ticket.
#
# Disabled by default in the GitHub Actions workflow. Never invoke this
# with real credentials outside of GitHub encrypted secrets.
#
# Required env vars:
#   APPLE_ID                    Apple ID email used for notarization
#   APPLE_TEAM_ID                Developer Team ID
#   APPLE_APP_SPECIFIC_PASSWORD  app-specific password for the Apple ID
#
# Usage: ./packaging/macos/notarize.sh <path-to.zip-or-.dmg> <path-to-CHIRP.app-to-staple>
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
    echo "error: notarize.sh must run on macOS." >&2
    exit 1
fi

SUBMIT_PATH="${1:?usage: notarize.sh <path-to.zip-or-.dmg> <path-to-CHIRP.app-to-staple>}"
STAPLE_TARGET="${2:?usage: notarize.sh <path-to.zip-or-.dmg> <path-to-CHIRP.app-to-staple>}"
: "${APPLE_ID:?APPLE_ID is required}"
: "${APPLE_TEAM_ID:?APPLE_TEAM_ID is required}"
: "${APPLE_APP_SPECIFIC_PASSWORD:?APPLE_APP_SPECIFIC_PASSWORD is required}"

echo "Submitting $SUBMIT_PATH for notarization..."
xcrun notarytool submit "$SUBMIT_PATH" \
    --apple-id "$APPLE_ID" \
    --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_SPECIFIC_PASSWORD" \
    --wait

echo "Stapling ticket to $STAPLE_TARGET..."
xcrun stapler staple "$STAPLE_TARGET"

echo "Reassessing with spctl..."
spctl --assess --type execute --verbose=4 "$STAPLE_TARGET"

echo "Notarization complete for $STAPLE_TARGET"
