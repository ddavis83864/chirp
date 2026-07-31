#!/bin/bash
# Submits an artifact to Apple notarization, staples the resulting ticket to
# a target, and validates both the staple and Gatekeeper's assessment of it.
#
# Disabled by default in the GitHub Actions workflow. Never invoke this
# with real credentials outside of GitHub encrypted secrets.
#
# Required env vars:
#   APPLE_ID                    Apple ID email used for notarization
#   APPLE_TEAM_ID                Developer Team ID
#   APPLE_APP_SPECIFIC_PASSWORD  app-specific password for the Apple ID
#
# Usage:
#   ./packaging/macos/notarize.sh <path-to-submit> <path-to-staple> <app|dmg> [log-out-dir]
#
#   <path-to-submit>  what gets uploaded to Apple (a .zip, .dmg, or .pkg --
#                      never a raw .app directory, notarytool rejects that)
#   <path-to-staple>  what the accepted ticket gets stapled to (may be the
#                      same underlying .app/.dmg the submission was made
#                      from, or a .app inside a submission zip)
#   <app|dmg>          selects the correct spctl assessment type
#   [log-out-dir]      directory to write the sanitized notarization log
#                      into on failure (default: current directory)
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
    echo "error: notarize.sh must run on macOS." >&2
    exit 1
fi

SUBMIT_PATH="${1:?usage: notarize.sh <path-to-submit> <path-to-staple> <app|dmg> [log-out-dir]}"
STAPLE_TARGET="${2:?usage: notarize.sh <path-to-submit> <path-to-staple> <app|dmg> [log-out-dir]}"
TARGET_TYPE="${3:?usage: notarize.sh <path-to-submit> <path-to-staple> <app|dmg> [log-out-dir]}"
LOG_OUT_DIR="${4:-.}"

case "$TARGET_TYPE" in
    app|dmg) ;;
    *) echo "error: target type must be 'app' or 'dmg', got '$TARGET_TYPE'" >&2; exit 1 ;;
esac

: "${APPLE_ID:?APPLE_ID is required}"
: "${APPLE_TEAM_ID:?APPLE_TEAM_ID is required}"
: "${APPLE_APP_SPECIFIC_PASSWORD:?APPLE_APP_SPECIFIC_PASSWORD is required}"

mkdir -p "$LOG_OUT_DIR"
SUBMIT_BASENAME="$(basename "$SUBMIT_PATH")"
SUBMISSION_JSON="$(mktemp -t chirp_notary_submit.XXXXXX.json)"
trap 'rm -f "$SUBMISSION_JSON"' EXIT

echo "Submitting $SUBMIT_PATH for notarization..."
if ! xcrun notarytool submit "$SUBMIT_PATH" \
        --apple-id "$APPLE_ID" \
        --team-id "$APPLE_TEAM_ID" \
        --password "$APPLE_APP_SPECIFIC_PASSWORD" \
        --wait \
        --output-format json > "$SUBMISSION_JSON"; then
    echo "error: notarytool submit invocation failed before a result was returned." >&2
    cat "$SUBMISSION_JSON" >&2 || true
    exit 1
fi

cat "$SUBMISSION_JSON"

SUBMISSION_ID="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('id',''))" "$SUBMISSION_JSON")"
STATUS="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('status',''))" "$SUBMISSION_JSON")"

echo "Submission ID: $SUBMISSION_ID"
echo "Status: $STATUS"

if [ -z "$SUBMISSION_ID" ]; then
    echo "error: no submission ID returned by notarytool." >&2
    exit 1
fi

if [ "$STATUS" != "Accepted" ]; then
    echo "error: notarization was not accepted (status: $STATUS). Fetching log..." >&2
    LOG_FILE="$LOG_OUT_DIR/notarization-log-${SUBMIT_BASENAME}-${SUBMISSION_ID}.json"
    xcrun notarytool log "$SUBMISSION_ID" \
        --apple-id "$APPLE_ID" \
        --team-id "$APPLE_TEAM_ID" \
        --password "$APPLE_APP_SPECIFIC_PASSWORD" \
        "$LOG_FILE" || echo "warning: could not retrieve notarization log" >&2
    if [ -f "$LOG_FILE" ]; then
        echo "Notarization log saved to: $LOG_FILE" >&2
        cat "$LOG_FILE" >&2
    fi
    exit 1
fi

echo "Notarization accepted. Stapling ticket to $STAPLE_TARGET..."
xcrun stapler staple "$STAPLE_TARGET"

echo "Validating staple..."
xcrun stapler validate "$STAPLE_TARGET"

echo "Reassessing with spctl (type: $TARGET_TYPE)..."
if [ "$TARGET_TYPE" = "app" ]; then
    spctl --assess --type execute --verbose=4 "$STAPLE_TARGET"
else
    spctl --assess --type open --context context:primary-signature --verbose=4 "$STAPLE_TARGET"
fi

echo "Re-verifying code signature after stapling..."
if [ "$TARGET_TYPE" = "app" ]; then
    # --deep --strict are bundle-specific checks (walk nested code); a DMG
    # is a flat signed disk image, not a bundle, so they don't apply to it.
    codesign --verify --deep --strict --verbose=4 "$STAPLE_TARGET" 2>&1 || {
        echo "error: codesign verification failed after stapling." >&2
        exit 1
    }
else
    codesign --verify --verbose=4 "$STAPLE_TARGET" 2>&1 || {
        echo "error: codesign verification failed after stapling." >&2
        exit 1
    }
fi

echo "Notarization, stapling, and Gatekeeper assessment complete for $STAPLE_TARGET (submission $SUBMISSION_ID)"
