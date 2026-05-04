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

# Include theme folder
if [ -d "$SCRIPT_DIR/theme" ]; then
    mkdir -p "$APP_DIR/theme"
    cp -r "$SCRIPT_DIR/theme/"* "$APP_DIR/theme/"
fi

if [ -f "$SCRIPT_DIR/README.md" ]; then
    copy_file "$SCRIPT_DIR/README.md" "$APP_DIR/README.md"
fi

cat > "$APP_DIR/RELEASE_NOTES.txt" <<'EOF'
Fire4ArkOS "Level 11" Performance Release (2026-05-04)

Major Fixes & Improvements:
- Near-Zero Latency Input: Implemented persistent xdotool pipe (bypasses subprocess overhead).
- Precise Physics: Quadratic stick acceleration + 150ms post-click freeze (stops 'flinging').
- Input Sync: Rewrote IPC reader to purge moves before clicks (stops 'springing').
- Ultra-Balanced Profile: Restored 150ms layout updates and WebM/VP9 for Reddit/YouTube.
- CPU Isolation: Reserved Core 3 for system/input to prevent Firefox from pinning the OS.
- Stick Drift Protection: Increased deadzone to 10000 for aging handheld sticks.
- Resolved Audio Sandbox: Forced EGL/Pulse backend for apulse stability.
- "Colorful" Theme Overhaul: Added premium system art and universal theme support.
- True Transparent Branding: Optimized logo for all ES themes.

Contents:
- install.sh
- run_browser.sh
- firefox-framebuffer-wrapper.py (High-perf version)
- bin/browser.arm64 (Level 11 skip-identical-frame build)
- src/ (Source for on-device rebuilds)

To apply the latest optimizations:
  git pull
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