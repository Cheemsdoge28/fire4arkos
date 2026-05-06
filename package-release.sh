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
copy_file "$SCRIPT_DIR/Sound Test.sh" "$APP_DIR/Sound Test.sh"
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
Fire4ArkOS v1.5.31 "Installer Resilience" (2026-05-06)

Major Fixes & Improvements:
- Ironclad SDL Protection: Installer now locks (apt-mark hold) the high-performance system SDL to prevent repository downgrades.
- Symlink Repair: Auto-repair for broken libSDL2 symlinks commonly found on community ArkOS images.
- One-Click Installer: Added 'install-from-es.sh' for hassle-free installation from the ES Tools menu.
- Expanded Clone Support: Fixed stability and startup issues on arkos4clone and arkosk36 revisions.
- High-Precision Input: Switched to XTest injection for reliable, zero-latency interaction.
- Ironclad Audio Diagnostic: Rebuilt the audio pipeline with apulse and aggressive hardware reclamation.
- CPU & Memory Isolation: Balanced performance profile for RK3326-based handhelds.

Note:
The installer now explicitly protects the 2.0.30+ SDL runtime provided by ArkOS.
If you previously experienced 'slow' or 'broken' graphics after an update, this release fixes it.

Contents:
- install.sh / install-from-es.sh
- run_browser.sh
- firefox-framebuffer-wrapper.py
- bin/browser.arm64 (Updated Binary)
- src/ (Source for on-device rebuilds)

Installation:
1. Copy Fire4ArkOS folder to EASYROMS/tools/
2. Run 'install-from-es.sh' from the ES Tools menu.
3. Reboot.
EOF

# Create archive using python (cross-platform fallback for zip)
echo "Creating archive..."
python3 -c "import shutil, os; \
archive_base = os.path.join('$RELEASE_ROOT', 'Fire4ArkOS-$(date +%G%m%d)'); \
shutil.make_archive(archive_base, 'zip', '$RELEASE_ROOT', 'Fire4ArkOS')"

echo "Release staged at: $APP_DIR"
echo "Archive created at: $RELEASE_ROOT/Fire4ArkOS-$(date +%G%m%d).zip"
echo "Binary used: $BINARY_PATH"