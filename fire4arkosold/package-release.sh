#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RELEASE_ROOT="${1:-$SCRIPT_DIR/dist/release}"
APP_DIR="$RELEASE_ROOT/Fire4ArkOS"

copy_file() {
    local source_path="$1"
    local target_path="$2"
    mkdir -p "$(dirname "$target_path")"
    cp -f "$source_path" "$target_path"
    chmod +x "$target_path" 2>/dev/null || true
}

pick_binary() {
    for candidate in \
        "$SCRIPT_DIR/bin/browser.arm64" \
        "$SCRIPT_DIR/build/browser.arm64" \
        "$SCRIPT_DIR/browser.arm64"; do
        if [ -f "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/bin"

BINARY_PATH="$(pick_binary)"

copy_file "$SCRIPT_DIR/install.sh" "$APP_DIR/install.sh"
copy_file "$SCRIPT_DIR/install-from-es.sh" "$APP_DIR/install-from-es.sh"
copy_file "$SCRIPT_DIR/install-es-system.py" "$APP_DIR/install-es-system.py"
copy_file "$SCRIPT_DIR/run_browser.sh" "$APP_DIR/run_browser.sh"
copy_file "$SCRIPT_DIR/firefox-framebuffer-wrapper.py" "$APP_DIR/firefox-framebuffer-wrapper.py"
copy_file "$SCRIPT_DIR/firefox-viewport-culling.js" "$APP_DIR/firefox-viewport-culling.js"
copy_file "$SCRIPT_DIR/audio-test.html" "$APP_DIR/audio-test.html"
copy_file "$BINARY_PATH" "$APP_DIR/bin/browser.arm64"

# Include source for on-device rebuilding
mkdir -p "$APP_DIR/src"
cp -r "$SCRIPT_DIR/src/"* "$APP_DIR/src/"
copy_file "$SCRIPT_DIR/Makefile" "$APP_DIR/Makefile"

if [ -f "$SCRIPT_DIR/README.md" ]; then
    copy_file "$SCRIPT_DIR/README.md" "$APP_DIR/README.md"
fi

cat > "$APP_DIR/RELEASE_NOTES.txt" <<'EOF'
Fire4ArkOS runtime package (2026-05-03)

Major Fixes & Improvements:
- Restored 'fire4arkos' shell command (available after install).
- Restored 'firefox-framebuffer-wrapper.py' system symlink.
- Fixed missing build dependencies (libsdl2-ttf-dev).
- Fixed missing runtime tools (ffmpeg, fbset, i2c-tools, etc.).
- Synchronized ES launcher performance defaults (Scale=1, FrameSkip=1).

Contents:
- install.sh
- install-from-es.sh
- install-es-system.py
- run_browser.sh
- firefox-framebuffer-wrapper.py
- firefox-viewport-culling.js (for injection)
- audio-test.html
- bin/browser.arm64

If the prebuilt binary does not work on your device, run:
  sudo bash install.sh --rebuild
EOF

# Create archive using python (cross-platform fallback for zip)
echo "Creating archive..."
python3 -c "import shutil, os; \
archive_base = os.path.join('$RELEASE_ROOT', 'Fire4ArkOS-$(date +%G%m%d)'); \
shutil.make_archive(archive_base, 'zip', '$RELEASE_ROOT', 'Fire4ArkOS')"

echo "Release staged at: $APP_DIR"
echo "Archive created at: $RELEASE_ROOT/Fire4ArkOS-$(date +%G%m%d).zip"
echo "Binary used: $BINARY_PATH"