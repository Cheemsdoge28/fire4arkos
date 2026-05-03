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
copy_file "$SCRIPT_DIR/run_browser.sh" "$APP_DIR/run_browser.sh"
copy_file "$SCRIPT_DIR/firefox-framebuffer-wrapper.py" "$APP_DIR/firefox-framebuffer-wrapper.py"
copy_file "$SCRIPT_DIR/audio-test.html" "$APP_DIR/audio-test.html"
copy_file "$BINARY_PATH" "$APP_DIR/bin/browser.arm64"

if [ -f "$SCRIPT_DIR/README.md" ]; then
    copy_file "$SCRIPT_DIR/README.md" "$APP_DIR/README.md"
fi

cat > "$APP_DIR/RELEASE_NOTES.txt" <<'EOF'
Fire4ArkOS runtime package

Contents:
- install.sh
- install-from-es.sh
- run_browser.sh
- firefox-framebuffer-wrapper.py
- audio-test.html
- bin/browser.arm64

If the prebuilt binary does not work on your device, run:
  sudo bash install.sh --rebuild
EOF

echo "Release staged at: $APP_DIR"
echo "Binary used: $BINARY_PATH"