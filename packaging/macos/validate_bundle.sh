#!/bin/bash
# Static + architecture validation for a built CHIRP.app bundle.
#
# Usage: ./packaging/macos/validate_bundle.sh <path-to-CHIRP.app> \
#            --version 1.12.0 --bundle-id com.ddavis83864.chirp \
#            [--arch x86_64|arm64|universal2] [--min-macos 11.0]
#
# Exits non-zero on any check failure. Codesign/spctl checks are reported
# but never fail this script -- unsigned builds are expected and valid;
# packaging-workflow.md documents how to interpret their output.
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
    echo "error: validate_bundle.sh must run on macOS." >&2
    exit 1
fi

APP_PATH="${1:-}"
if [ -z "$APP_PATH" ] || [ ! -d "$APP_PATH" ]; then
    echo "error: usage: validate_bundle.sh <path-to-CHIRP.app> [--version X] [--bundle-id Y] [--arch Z]" >&2
    exit 1
fi
shift

EXPECT_VERSION=""
EXPECT_BUNDLE_ID=""
EXPECT_ARCH=""
EXPECT_MIN_MACOS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --version) EXPECT_VERSION="$2"; shift 2 ;;
        --bundle-id) EXPECT_BUNDLE_ID="$2"; shift 2 ;;
        --arch) EXPECT_ARCH="$2"; shift 2 ;;
        --min-macos) EXPECT_MIN_MACOS="$2"; shift 2 ;;
        *) echo "error: unknown argument '$1'" >&2; exit 1 ;;
    esac
done

FAILURES=0
fail() {
    echo "FAIL: $1" >&2
    FAILURES=$((FAILURES + 1))
}
pass() {
    echo "OK:   $1"
}

INFO_PLIST="$APP_PATH/Contents/Info.plist"
EXECUTABLE="$APP_PATH/Contents/MacOS/chirp"

echo "== Structure =="
[ -d "$APP_PATH/Contents" ] && pass "Contents/ exists" || fail "Contents/ missing"
[ -d "$APP_PATH/Contents/MacOS" ] && pass "Contents/MacOS/ exists" || fail "Contents/MacOS/ missing"
[ -d "$APP_PATH/Contents/Resources" ] && pass "Contents/Resources/ exists" || fail "Contents/Resources/ missing"
[ -f "$INFO_PLIST" ] && pass "Info.plist exists" || fail "Info.plist missing"

echo "== Info.plist =="
if [ -f "$INFO_PLIST" ]; then
    if plutil -lint "$INFO_PLIST" >/dev/null; then
        pass "Info.plist is well-formed"
    else
        fail "Info.plist failed plutil -lint"
    fi

    ACTUAL_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$INFO_PLIST" 2>/dev/null || true)"
    ACTUAL_BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$INFO_PLIST" 2>/dev/null || true)"
    ACTUAL_EXEC="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$INFO_PLIST" 2>/dev/null || true)"
    ACTUAL_MIN_MACOS="$(/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$INFO_PLIST" 2>/dev/null || true)"

    echo "CFBundleShortVersionString: $ACTUAL_VERSION"
    echo "CFBundleIdentifier: $ACTUAL_BUNDLE_ID"
    echo "CFBundleExecutable: $ACTUAL_EXEC"
    echo "LSMinimumSystemVersion: $ACTUAL_MIN_MACOS"

    if [ -n "$EXPECT_VERSION" ]; then
        [ "$ACTUAL_VERSION" = "$EXPECT_VERSION" ] \
            && pass "version matches expected $EXPECT_VERSION" \
            || fail "version '$ACTUAL_VERSION' != expected '$EXPECT_VERSION'"
    fi
    if [ -n "$EXPECT_BUNDLE_ID" ]; then
        [ "$ACTUAL_BUNDLE_ID" = "$EXPECT_BUNDLE_ID" ] \
            && pass "bundle id matches expected $EXPECT_BUNDLE_ID" \
            || fail "bundle id '$ACTUAL_BUNDLE_ID' != expected '$EXPECT_BUNDLE_ID'"
    fi
    if [ -n "$EXPECT_MIN_MACOS" ]; then
        [ "$ACTUAL_MIN_MACOS" = "$EXPECT_MIN_MACOS" ] \
            && pass "minimum macOS version matches expected $EXPECT_MIN_MACOS" \
            || fail "minimum macOS version '$ACTUAL_MIN_MACOS' != expected '$EXPECT_MIN_MACOS'"
    fi
fi

echo "== Executable =="
if [ -f "$EXECUTABLE" ]; then
    pass "executable present at Contents/MacOS/chirp"
    if [ -x "$EXECUTABLE" ]; then
        pass "executable has execute permission"
    else
        fail "executable is missing the execute bit"
    fi
else
    fail "executable missing at Contents/MacOS/chirp"
fi

echo "== Icon =="
if [ -f "$APP_PATH/Contents/Resources/chirp.icns" ]; then
    pass "chirp.icns present in Resources"
else
    fail "chirp.icns missing from Resources"
fi

echo "== Bundled resources =="
for check in \
    "Contents/Resources/chirp/stock_configs" \
    "Contents/Resources/chirp/locale"; do
    if [ -e "$APP_PATH/$check" ]; then
        pass "$check present"
    else
        fail "$check missing"
    fi
done

STOCK_CONFIG_COUNT=$(find "$APP_PATH/Contents/Resources/chirp/stock_configs" -name "*.csv" 2>/dev/null | wc -l | tr -d ' ')
echo "stock_configs *.csv count: $STOCK_CONFIG_COUNT"
if [ "$STOCK_CONFIG_COUNT" -ge 10 ]; then
    pass "stock_configs has $STOCK_CONFIG_COUNT csv files (expected ~20)"
else
    fail "stock_configs only has $STOCK_CONFIG_COUNT csv files, expected ~20 -- resources may not have bundled correctly"
fi

# Regression check: a prior version of chirpwx.spec's datas list collapsed
# every language's compiled CHIRP.mo into one shared destination directory,
# so only the last-processed language survived instead of all of them.
# Assert both the per-language directory layout and a realistic minimum
# count so that class of bug fails loudly instead of shipping silently.
MO_COUNT=$(find "$APP_PATH/Contents/Resources/chirp/locale" -name "*.mo" 2>/dev/null | wc -l | tr -d ' ')
MO_LANG_DIRS=$(find "$APP_PATH/Contents/Resources/chirp/locale" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
echo "locale .mo file count: $MO_COUNT, language directories: $MO_LANG_DIRS"
if [ "$MO_COUNT" -ge 10 ] && [ "$MO_LANG_DIRS" -ge 10 ]; then
    pass "locale has $MO_COUNT .mo files across $MO_LANG_DIRS language directories (expected ~18)"
else
    fail "locale only has $MO_COUNT .mo files across $MO_LANG_DIRS language directories, expected ~18 each -- translations did not bundle correctly (see chirpwx.spec locale datas handling)"
fi

echo "== Architecture =="
if [ -f "$EXECUTABLE" ]; then
    FILE_OUT="$(file "$EXECUTABLE")"
    echo "file: $FILE_OUT"
    LIPO_OUT="$(lipo -info "$EXECUTABLE" 2>&1 || true)"
    echo "lipo -info: $LIPO_OUT"

    case "$EXPECT_ARCH" in
        universal2)
            if echo "$LIPO_OUT" | grep -q "x86_64" && echo "$LIPO_OUT" | grep -q "arm64"; then
                pass "universal2: both x86_64 and arm64 slices present"
            else
                fail "expected universal2 (x86_64 + arm64) but lipo reports: $LIPO_OUT"
            fi
            ;;
        x86_64|arm64)
            if echo "$LIPO_OUT" | grep -q "$EXPECT_ARCH" && ! echo "$LIPO_OUT" | grep -qE "Architectures.*and"; then
                pass "single-architecture $EXPECT_ARCH confirmed"
            else
                fail "expected single architecture $EXPECT_ARCH but lipo reports: $LIPO_OUT"
            fi
            ;;
        "")
            echo "(no --arch given; architecture not asserted, only reported)"
            ;;
    esac
fi

echo "== Dynamic library references =="
if [ -f "$EXECUTABLE" ]; then
    OTOOL_OUT="$(otool -L "$EXECUTABLE" 2>&1 || true)"
    echo "$OTOOL_OUT"
    if echo "$OTOOL_OUT" | grep -qE '/Users/runner|/opt/homebrew|/usr/local/Cellar|/private/var/folders'; then
        fail "executable references a build-machine-only path (runner homedir, Homebrew, or temp dir)"
    else
        pass "no build-machine-only paths in otool -L output"
    fi
fi

echo "== Build path leakage =="
if [ -f "$EXECUTABLE" ] && grep -qa "$(dirname "$APP_PATH")" "$EXECUTABLE" 2>/dev/null; then
    fail "executable embeds its own build directory path"
else
    pass "no embedded build directory path found in executable"
fi

echo "== Code signing (informational) =="
codesign -dv --verbose=4 "$APP_PATH" 2>&1 || echo "(unsigned or codesign check failed -- expected for unsigned builds)"

echo "== Gatekeeper assessment (informational) =="
spctl --assess --type execute --verbose=4 "$APP_PATH" 2>&1 || echo "(not accepted by Gatekeeper -- expected for unsigned/non-notarized builds)"

echo
if [ "$FAILURES" -eq 0 ]; then
    echo "All required checks passed."
    exit 0
else
    echo "$FAILURES check(s) failed."
    exit 1
fi
