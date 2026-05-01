#!/bin/bash
# Fire4ArkOS Launcher Script for RK3326 (R36S)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Minimal environment setup to match direct execution
export MOZ_USE_XINPUT2=1
APP_DIR="${FIRE4ARKOS_HOME:-$SCRIPT_DIR}"
export FIRE4ARKOS_HOME="$APP_DIR"
export FIRE4ARKOS_WRAPPER="$APP_DIR/firefox-framebuffer-wrapper.py"

# Clean up path to avoid confusion
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

# Find and launch the binary
BINARIES=(
    "$APP_DIR/build/browser"
    "$APP_DIR/browser"
    "/usr/local/bin/browser"
)

for bin in "${BINARIES[@]}"; do
    if [ -x "$bin" ]; then
        echo "[INFO] Launching $bin..."
        # No 'nice' or 'setterm' to ensure identical behavior to direct execution
        exec "$bin" "$@"
    fi
done

if command -v browser >/dev/null 2>&1; then
    exec browser "$@"
fi

echo "[ERROR] browser binary not found in $APP_DIR or PATH" >&2
exit 1