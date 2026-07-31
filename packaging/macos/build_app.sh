#!/bin/bash
# Builds CHIRP.app from this git checkout using PyInstaller.
#
# Must run on macOS with Python 3.10 (wxPython 4.2.0 only ships macOS wheels
# for cp310, as a universal2 wheel -- see requirements-build.txt).
#
# Usage: ./packaging/macos/build_app.sh [x86_64|arm64|universal2]
#   Architecture arg is optional; if omitted, PyInstaller targets the
#   native architecture of the Python interpreter running the build.
# Env overrides: CHIRP_APP_VERSION, CHIRP_BUNDLE_ID, CHIRP_MIN_MACOS
# Output: packaging/macos/dist/CHIRP.app
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
    echo "error: build_app.sh must run on macOS." >&2
    exit 1
fi

TARGET_ARCH="${1:-}"
case "$TARGET_ARCH" in
    ""|x86_64|arm64|universal2) ;;
    *)
        echo "error: unknown architecture '$TARGET_ARCH' (expected x86_64, arm64, or universal2)" >&2
        exit 1
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"
DIST_DIR="$SCRIPT_DIR/dist"

PY_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "$PY_VERSION" != "3.10" ]; then
    echo "error: python3 on PATH is $PY_VERSION; wxPython 4.2.0 requires 3.10 on macOS." >&2
    exit 1
fi

export CHIRP_APP_VERSION="${CHIRP_APP_VERSION:-1.12.0}"
export CHIRP_BUNDLE_ID="${CHIRP_BUNDLE_ID:-com.ddavis83864.chirp}"
export CHIRP_MIN_MACOS="${CHIRP_MIN_MACOS:-11.0}"
export CHIRP_TARGET_ARCH="$TARGET_ARCH"

echo "Building CHIRP.app version $CHIRP_APP_VERSION (arch: ${TARGET_ARCH:-native}) from $REPO_ROOT"

VENV_DIR="$SCRIPT_DIR/.build-venv"
rm -rf "$VENV_DIR"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet -r "$SCRIPT_DIR/requirements-build.txt"

echo "Compiling translations..."
for po in "$REPO_ROOT"/chirp/locale/*.po; do
    lang="$(basename "$po" .po)"
    outdir="$REPO_ROOT/chirp/locale/$lang/LC_MESSAGES"
    mkdir -p "$outdir"
    msgfmt --output-file="$outdir/CHIRP.mo" "$po" || true
done

rm -rf "$BUILD_DIR" "$DIST_DIR"

echo "Running PyInstaller..."
pyinstaller \
    --distpath "$DIST_DIR" \
    --workpath "$BUILD_DIR" \
    --noconfirm \
    "$SCRIPT_DIR/chirpwx.spec"

deactivate

echo "Built: $DIST_DIR/CHIRP.app"
