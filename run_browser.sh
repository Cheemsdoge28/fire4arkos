#!/bin/bash
# Fire4ArkOS Launcher Script for RK3326 (R36S)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Environment setup for Firefox and SDL
export MOZ_USE_XINPUT2=1
export MOZ_ENABLE_WAYLAND=0
export GTK_THEME=Adwaita

APP_DIR="${FIRE4ARKOS_HOME:-$SCRIPT_DIR}"
export FIRE4ARKOS_HOME="$APP_DIR"
export FIRE4ARKOS_WRAPPER="${FIRE4ARKOS_WRAPPER:-$APP_DIR/firefox-framebuffer-wrapper.py}"

# --- PortMaster-style Library Handling ---
# Use bundled libraries if available to avoid breaking the host OS
if [ -d "$APP_DIR/libs" ]; then
    export LD_LIBRARY_PATH="$APP_DIR/libs:$LD_LIBRARY_PATH"
    echo "[INFO] Using bundled libraries from $APP_DIR/libs"
fi

# --- Graphics & Compatibility ---
# We no longer force KMSDRM/GLES2 here as it may interfere with working system defaults.
# If you experience "opengles2 not available", uncomment the lines below:
# export SDL_VIDEODRIVER=kmsdrm
# export SDL_RENDER_DRIVER=opengles2

# --- EmulationStation / Handheld Compatibility ---
# Hide cursor and ensure we're using the right tty if launched from ES
if [ -t 0 ]; then
    setterm -cursor off || true
fi

# Cleanup on exit
cleanup() {
    if [ -t 0 ]; then
        setterm -cursor on || true
    fi
    # Clear any residual Xvfb locks if we were the last one
    rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
    echo "[INFO] Fire4ArkOS exited."
}
trap cleanup EXIT

# Search for the browser binary in order of preference
BINARIES=(
    "$APP_DIR/build/browser"
    "$APP_DIR/build/browser.arm64"
    "$APP_DIR/browser"
    "/usr/local/bin/browser"
)

for bin in "${BINARIES[@]}"; do
    if [ -x "$bin" ]; then
        echo "[INFO] Launching $bin..."
        # Use nice for better priority on handhelds
        exec nice -n -5 "$bin" "$@"
    fi
done

if command -v browser >/dev/null 2>&1; then
    echo "[INFO] Launching system 'browser'..."
    exec nice -n -5 browser "$@"
fi

echo "[ERROR] browser binary not found in $APP_DIR or PATH" >&2
exit 1