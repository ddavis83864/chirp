#!/bin/bash
# Signs a built CHIRP.app with a Developer ID Application certificate and
# the hardened runtime, for the optional signed-build path.
#
# Disabled by default in the GitHub Actions workflow. Never invoke this
# with real credentials outside of GitHub encrypted secrets.
#
# Required env vars:
#   MACOS_CERTIFICATE_P12       base64-encoded .p12 certificate
#   MACOS_CERTIFICATE_PASSWORD  password for the .p12 file
#   MACOS_SIGNING_IDENTITY      e.g. "Developer ID Application: NAME (TEAMID)"
#
# Usage: ./packaging/macos/sign.sh <path-to-CHIRP.app>
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
    echo "error: sign.sh must run on macOS." >&2
    exit 1
fi

APP_PATH="${1:?usage: sign.sh <path-to-CHIRP.app>}"
: "${MACOS_CERTIFICATE_P12:?MACOS_CERTIFICATE_P12 is required}"
: "${MACOS_CERTIFICATE_PASSWORD:?MACOS_CERTIFICATE_PASSWORD is required}"
: "${MACOS_SIGNING_IDENTITY:?MACOS_SIGNING_IDENTITY is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTITLEMENTS="$SCRIPT_DIR/entitlements.plist"

KEYCHAIN="chirp-signing-$$.keychain-db"
KEYCHAIN_PASSWORD="$(openssl rand -base64 24)"
CERT_FILE="$(mktemp -t chirp_cert.XXXXXX.p12)"

cleanup() {
    security delete-keychain "$KEYCHAIN" >/dev/null 2>&1 || true
    rm -f "$CERT_FILE"
}
trap cleanup EXIT

echo "$MACOS_CERTIFICATE_P12" | base64 --decode > "$CERT_FILE"

security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security set-keychain-settings -lut 21600 "$KEYCHAIN"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"

security import "$CERT_FILE" -k "$KEYCHAIN" -P "$MACOS_CERTIFICATE_PASSWORD" \
    -T /usr/bin/codesign -T /usr/bin/security

security set-key-partition-list -S apple-tool:,apple:,codesign: \
    -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN" >/dev/null

PREV_KEYCHAINS=()
while IFS= read -r line; do
    PREV_KEYCHAINS+=("$(echo "$line" | xargs)")
done < <(security list-keychains -d user | tr -d '"')
security list-keychains -d user -s "$KEYCHAIN" "${PREV_KEYCHAINS[@]}"

echo "Signing nested binaries in $APP_PATH..."
find "$APP_PATH/Contents" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 \
    | xargs -0 -I{} codesign --force --timestamp --options runtime \
        --entitlements "$ENTITLEMENTS" --sign "$MACOS_SIGNING_IDENTITY" "{}"

find "$APP_PATH/Contents/MacOS" -type f -perm -u+x -print0 \
    | xargs -0 -I{} codesign --force --timestamp --options runtime \
        --entitlements "$ENTITLEMENTS" --sign "$MACOS_SIGNING_IDENTITY" "{}"

echo "Signing $APP_PATH..."
codesign --force --deep --timestamp --options runtime \
    --entitlements "$ENTITLEMENTS" --sign "$MACOS_SIGNING_IDENTITY" "$APP_PATH"

echo "Verifying signature..."
codesign --verify --deep --strict --verbose=4 "$APP_PATH"

echo "Signed: $APP_PATH"
