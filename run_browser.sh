#!/bin/bash
# Fire4ArkOS Launcher Script for RK3326 (R36S)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Minimal environment setup to match direct execution
export MOZ_USE_XINPUT2=1
export FIRE4ARKOS_MAX_PERF="${FIRE4ARKOS_MAX_PERF:-1}"
export FPS="${FPS:-60}"
export SDL_RENDER_VSYNC="${SDL_RENDER_VSYNC:-0}"
APP_DIR="${FIRE4ARKOS_HOME:-$SCRIPT_DIR}"
export FIRE4ARKOS_HOME="$APP_DIR"
export FIRE4ARKOS_WRAPPER="$APP_DIR/firefox-framebuffer-wrapper.py"

# Clean up path to avoid confusion
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

# Request maximum CPU clocks when running on Linux with write access.
if [ "${FIRE4ARKOS_MAX_PERF}" = "1" ]; then
    for governor in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        if [ -w "$governor" ]; then
            echo performance > "$governor" 2>/dev/null || true
        fi
    done
fi

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