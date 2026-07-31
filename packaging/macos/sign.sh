#!/bin/bash
# Signs a built CHIRP.app with a Developer ID Application certificate and
# the hardened runtime.
#
# Disabled by default in the GitHub Actions workflow. Never invoke this
# with real credentials outside of GitHub encrypted secrets.
#
# Required env vars:
#   MACOS_CERTIFICATE_P12       base64-encoded .p12 certificate
#   MACOS_CERTIFICATE_PASSWORD  password for the .p12 file
#   MACOS_SIGNING_IDENTITY      e.g. "Developer ID Application: NAME (TEAMID)"
#
# Usage: ./packaging/macos/sign.sh <path-to-CHIRP.app> [signing-info-out.json]
#
# Signs from the inside out: nested frameworks, then loose .dylib/.so files,
# then helper executables, then the main executable, then the outer bundle
# (without --deep -- everything nested is already explicitly signed by the
# time the outer bundle is signed, so --deep at that point would be
# redundant re-signing rather than the primary signing mechanism). A final
# --deep --strict verify is still used to confirm the *result*, which is a
# different thing from using --deep to *produce* the signature.
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
    echo "error: sign.sh must run on macOS." >&2
    exit 1
fi

APP_PATH="${1:?usage: sign.sh <path-to-CHIRP.app> [signing-info-out.json]}"
SIGNING_INFO_OUT="${2:-}"
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

# Import into this ephemeral keychain only -- never the runner's login
# keychain, so nothing signing-related persists past this job.
security import "$CERT_FILE" -k "$KEYCHAIN" -P "$MACOS_CERTIFICATE_PASSWORD" \
    -T /usr/bin/codesign -T /usr/bin/security
rm -f "$CERT_FILE"

security set-key-partition-list -S apple-tool:,apple:,codesign: \
    -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN" >/dev/null

PREV_KEYCHAINS=()
while IFS= read -r line; do
    PREV_KEYCHAINS+=("$(echo "$line" | xargs)")
done < <(security list-keychains -d user | tr -d '"')
security list-keychains -d user -s "$KEYCHAIN" "${PREV_KEYCHAINS[@]}"

echo "Verifying signing identity is present and unambiguous..."
IDENTITY_MATCHES="$(security find-identity -v -p codesigning "$KEYCHAIN" \
    | grep -c -F "$MACOS_SIGNING_IDENTITY" || true)"
if [ "$IDENTITY_MATCHES" -eq 0 ]; then
    echo "error: signing identity '$MACOS_SIGNING_IDENTITY' not found in the imported certificate." >&2
    security find-identity -v -p codesigning "$KEYCHAIN" >&2 || true
    exit 1
elif [ "$IDENTITY_MATCHES" -gt 1 ]; then
    echo "error: signing identity '$MACOS_SIGNING_IDENTITY' matches $IDENTITY_MATCHES entries; must be unambiguous." >&2
    security find-identity -v -p codesigning "$KEYCHAIN" >&2 || true
    exit 1
fi
echo "Confirmed exactly one matching identity."

sign_one() {
    codesign --force --timestamp --options runtime \
        --entitlements "$ENTITLEMENTS" --sign "$MACOS_SIGNING_IDENTITY" "$1"
}

echo "Signing nested frameworks..."
find "$APP_PATH/Contents/Frameworks" -maxdepth 1 -name "*.framework" -type d 2>/dev/null | while read -r fw; do
    echo "  $fw"
    sign_one "$fw"
done

echo "Signing loose .dylib and .so files (excluding anything inside an already-signed .framework)..."
find "$APP_PATH/Contents" \( -name "*.dylib" -o -name "*.so" \) -type f \
    -not -path "*.framework/*" -print0 \
    | while IFS= read -r -d '' f; do
        sign_one "$f"
    done

echo "Signing helper executables and the main executable in Contents/MacOS..."
find "$APP_PATH/Contents/MacOS" -type f -perm -u+x -print0 \
    | while IFS= read -r -d '' f; do
        sign_one "$f"
    done

echo "Signing the outer bundle $APP_PATH (top-level only -- nested content already signed above)..."
sign_one "$APP_PATH"

echo "Verifying complete signature (this --deep is a verification pass, not how the signature was produced)..."
codesign --verify --deep --strict --verbose=4 "$APP_PATH"

echo "== Signature details =="
codesign -dv --verbose=4 "$APP_PATH" 2>&1 | tee /tmp/chirp_codesign_dv.txt

AUTHORITY="$(codesign -dv --verbose=4 "$APP_PATH" 2>&1 | grep '^Authority=' | head -1 | sed 's/^Authority=//')"
TEAM_ID="$(codesign -dv --verbose=4 "$APP_PATH" 2>&1 | grep '^TeamIdentifier=' | head -1 | sed 's/^TeamIdentifier=//')"
BUNDLE_ID_SIGNED="$(codesign -dv --verbose=4 "$APP_PATH" 2>&1 | grep '^Identifier=' | head -1 | sed 's/^Identifier=//')"
RUNTIME_VERSION="$(codesign -dv --verbose=4 "$APP_PATH" 2>&1 | grep '^Runtime Version=' | head -1 | sed 's/^Runtime Version=//')"
HAS_TIMESTAMP="false"
codesign -dv --verbose=4 "$APP_PATH" 2>&1 | grep -q '^Timestamp=' && HAS_TIMESTAMP="true"
HARDENED_RUNTIME="false"
[ -n "$RUNTIME_VERSION" ] && HARDENED_RUNTIME="true"

echo "Authority: $AUTHORITY"
echo "Team ID: $TEAM_ID"
echo "Bundle ID: $BUNDLE_ID_SIGNED"
echo "Hardened runtime: $HARDENED_RUNTIME (runtime version: $RUNTIME_VERSION)"
echo "Timestamp present: $HAS_TIMESTAMP"

if [ -n "$SIGNING_INFO_OUT" ]; then
    python3 - "$SIGNING_INFO_OUT" "$AUTHORITY" "$TEAM_ID" "$BUNDLE_ID_SIGNED" "$HARDENED_RUNTIME" "$HAS_TIMESTAMP" <<'PYEOF'
import json
import sys

out_path, authority, team_id, bundle_id, hardened_runtime, has_timestamp = sys.argv[1:7]
with open(out_path, "w") as f:
    json.dump({
        "authority": authority,
        "team_id": team_id,
        "bundle_id": bundle_id,
        "hardened_runtime": hardened_runtime == "true",
        "timestamp_present": has_timestamp == "true",
    }, f, indent=2)
PYEOF
    echo "Signing info written to: $SIGNING_INFO_OUT"
fi

echo "Signed: $APP_PATH"
