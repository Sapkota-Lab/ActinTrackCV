#!/usr/bin/env bash
#
# ActinTrackCV - macOS .app bundle build (PyInstaller).
#
# PREREQUISITES (this script does NOT install anything for you):
#   * macOS
#   * Python 3.10+ (the same interpreter you run the app with)
#   * Build environment (runtime deps + PyInstaller):
#         python -m pip install -r requirements-build.txt
#
# USAGE (from anywhere; the script locates the repo root itself):
#   bash packaging/macos/build_macos.sh
#
# ENV OPTIONS:
#   SKIP_TESTS=1   Skip unittest + compileall (not recommended).
#   KEEP_OLD=1     Do not delete previous build/ and dist/ outputs first.
#
# OUTPUT:
#   dist/ActinTrackCV.app   (windowed, one-dir .app bundle)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"
echo "Repo root: $REPO_ROOT"

SPEC="$REPO_ROOT/packaging/macos/actintrackcv.spec"
if [ ! -f "$SPEC" ]; then
    echo "Spec not found: $SPEC" >&2
    exit 1
fi

python --version
if ! python -c "import PyInstaller" >/dev/null 2>&1; then
    echo "PyInstaller is not installed. Run: python -m pip install -r requirements-build.txt" >&2
    exit 1
fi

if [ "${KEEP_OLD:-0}" != "1" ]; then
    echo "Cleaning old build/ and dist/ ..."
    rm -rf "$REPO_ROOT/build" \
           "$REPO_ROOT/dist/ActinTrackCV.app" \
           "$REPO_ROOT/dist/ActinTrackCV"
fi

if [ "${SKIP_TESTS:-0}" != "1" ]; then
    echo "Running unit tests ..."
    python -m unittest discover -s tests -p "test_*.py"
    echo "Compiling sources ..."
    python -m compileall -q actintrack_app tests
fi

echo "Running PyInstaller (.app bundle, windowed) ..."
python -m PyInstaller --clean --noconfirm "$SPEC"

APP_PATH="$REPO_ROOT/dist/ActinTrackCV.app"
if [ -d "$APP_PATH" ]; then
    echo ""
    echo "Build complete. Launch with:"
    echo "  open \"$APP_PATH\""
else
    echo "Build finished but expected .app not found: $APP_PATH" >&2
    exit 1
fi
