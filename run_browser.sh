#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Match the direct SSH launch path: run the installed browser binary with the
# same environment the ArkOS launcher uses.
export PATH=/usr/local/bin:/usr/bin:/bin
export MOZ_USE_XINPUT2=1
export MOZ_ENABLE_WAYLAND=0
export GTK_THEME=Adwaita
export SDL_VIDEODRIVER=opengles2
export SDL_RENDER_DRIVER=opengles2
export SDL_HINT_FRAMEBUFFER_ACCELERATION=1

APP_DIR="${FIRE4ARKOS_HOME:-$SCRIPT_DIR}"
export FIRE4ARKOS_HOME="$APP_DIR"
export FIRE4ARKOS_WRAPPER="${FIRE4ARKOS_WRAPPER:-$APP_DIR/firefox-framebuffer-wrapper.py}"

# Search for the browser binary in order of preference
BINARIES=(
    "$APP_DIR/build/browser"
    "$APP_DIR/build/browser.arm64"
    "$APP_DIR/browser"
    "browser"
)

for bin in "${BINARIES[@]}"; do
    if [[ "$bin" == "browser" ]]; then
        if command -v browser >/dev/null 2>&1; then
            echo "[INFO] Launching installed 'browser'..."
            exec browser "$@"
        fi
    elif [ -x "$bin" ]; then
        echo "[INFO] Launching $bin..."
        exec "$bin" "$@"
    fi
done

echo "[ERROR] browser binary not found in $APP_DIR or PATH" >&2
exit 1