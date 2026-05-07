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
        "$SCRIPT_DIR/build/browser.arm64" \
        "$SCRIPT_DIR/build/browser" \
        "$SCRIPT_DIR/bin/browser.arm64" \
        "$SCRIPT_DIR/bin/browser" \
        "$SCRIPT_DIR/fire4arkos-ondevice/build/browser.arm64" \
        "$SCRIPT_DIR/fire4arkos-ondevice/build/browser" \
        "$SCRIPT_DIR/fire4arkos-ondevice/bin/browser.arm64" \
        "$SCRIPT_DIR/fire4arkos-ondevice/bin/browser" \
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
if [ -f "$SCRIPT_DIR/VERSION" ]; then
    copy_file "$SCRIPT_DIR/VERSION" "$APP_DIR/VERSION"
fi

cat > "$APP_DIR/RELEASE_NOTES.txt" <<'EOF'
Fire4ArkOS v1.5.33 "Smart Focus" (2026-05-07)

Major Fixes & Improvements:
- Smart Window Stabilization: Re-introduced menu-aware stabilization worker. It ensures the browser stays focused without "fighting" with open dropdowns or popups, making menus fully functional again.
- A/L3 Unification: Physical A now mirrors L3 left-click behavior for consistent dragging.
- Right Click Binding: Dedicated R3 right-click with updated on-screen hints.
- Unified Installer: Consolidated multiple scripts into a single, interactive install.sh for a cleaner experience.

Contents:
- install.sh / install-from-es.sh
- run_browser.sh
- firefox-framebuffer-wrapper.py
- bin/browser.arm64 (Updated Binary)
- src/ (Source for on-device rebuilds)

Installation:
1. Copy Fire4ArkOS folder to EASYROMS/tools/
2. Run install.sh from the terminal (or ES Tools menu) and follow the prompts.
3. Reboot.
EOF

# Create archive using python (cross-platform fallback for zip)
echo "Creating archive..."
RELEASE_ROOT_PY="$RELEASE_ROOT"
if command -v cygpath >/dev/null 2>&1; then
    RELEASE_ROOT_PY="$(cygpath -w "$RELEASE_ROOT")"
fi
python3 -c "import shutil, os; \
archive_base = os.path.join(r'$RELEASE_ROOT_PY', 'Fire4ArkOS-$(date +%G%m%d)'); \
shutil.make_archive(archive_base, 'zip', r'$RELEASE_ROOT_PY', 'Fire4ArkOS')"

echo "Release staged at: $APP_DIR"
echo "Archive created at: $RELEASE_ROOT/Fire4ArkOS-$(date +%G%m%d).zip"
echo "Binary used: $BINARY_PATH"