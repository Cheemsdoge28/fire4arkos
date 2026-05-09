#!/bin/bash
# Fire4ArkOS Launcher Script for RK3326 (R36S)

# Resolve the real directory of the script, handling symlinks correctly.
REAL_SCRIPT_PATH=$(readlink -f "$0" 2>/dev/null || python3 -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$0" 2>/dev/null || echo "$0")
SCRIPT_DIR="$(cd "$(dirname "$REAL_SCRIPT_PATH")" && pwd)"
# Smart detection: if we are in a 'scripts' folder, the app root is one level up.
if [[ "$SCRIPT_DIR" == */scripts ]]; then
    APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
else
    APP_DIR="$SCRIPT_DIR"
fi
cd "$APP_DIR" || exit 1

# Minimal environment setup to match direct execution.
# Default to RK3326-safe settings for low-performance Ubuntu clients.
# ulimit -v 2097152 2>/dev/null || true
export MOZ_USE_XINPUT2=1
export FIRE4ARKOS_SOC="${FIRE4ARKOS_SOC:-rk3326}"
export FIRE4ARKOS_MAX_PERF="${FIRE4ARKOS_MAX_PERF:-1}"
export FIRE4ARKOS_LOW_QUALITY="${FIRE4ARKOS_LOW_QUALITY:-1}"
export FIRE4ARKOS_FORCE_VSYNC="${FIRE4ARKOS_FORCE_VSYNC:-1}"
export FIRE4ARKOS_AUDIO_BACKEND="${FIRE4ARKOS_AUDIO_BACKEND:-auto}"
export ALSA_CARD="${ALSA_CARD:-0}"
export FIRE4ARKOS_DEBUG_AUDIO="${FIRE4ARKOS_DEBUG_AUDIO:-0}"
export FIRE4ARKOS_USER_AGENT="${FIRE4ARKOS_USER_AGENT:-Mozilla/5.0 (Linux; Android 10; Pixel 4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36}"
export FIRE4ARKOS_NO_SLEEP="${FIRE4ARKOS_NO_SLEEP:-0}"
export FIRE4ARKOS_FRAME_SKIP="${FIRE4ARKOS_FRAME_SKIP:-1}"
export FIRE4ARKOS_INTERNAL_SCALE="${FIRE4ARKOS_INTERNAL_SCALE:-1}"
export FPS="${FPS:-30}"
export FIRE4ARKOS_CPUSET="${FIRE4ARKOS_CPUSET:-0-3}"

export SDL_RENDER_VSYNC="${SDL_RENDER_VSYNC:-$FIRE4ARKOS_FORCE_VSYNC}"
export FIRE4ARKOS_HOME="${FIRE4ARKOS_HOME:-$APP_DIR}"
export FIRE4ARKOS_WRAPPER="$SCRIPT_DIR/firefox-framebuffer-wrapper.py"
LOG_FILE="$FIRE4ARKOS_HOME/firefox.log"

# Clean up path to avoid confusion
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

# Request maximum CPU clocks only when explicitly enabled.
if [ "${FIRE4ARKOS_SET_GOVERNOR:-0}" = "1" ]; then
    for governor in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        if [ -w "$governor" ]; then
            echo performance > "$governor" 2>/dev/null || true
        fi
    done
fi

# Find and launch the binary
BINARIES=(
    "$APP_DIR/build/browser.arm64"
    "$APP_DIR/build/browser"
    "$APP_DIR/bin/browser.arm64"
    "$APP_DIR/bin/browser"
    "$APP_DIR/browser"
    "/usr/local/bin/browser"
)

for bin in "${BINARIES[@]}"; do
    if [ -x "$bin" ]; then
        echo "[INFO] Launching $bin..."
        echo "[Fire4ArkOS] Launching $bin" >> "$LOG_FILE"
        # No 'nice' or 'setterm' to ensure identical behavior to direct execution
        if [ "${FIRE4ARKOS_FROM_ES:-0}" = "1" ]; then
            exec "$bin" "$@" >> "$LOG_FILE" 2>&1
        else
            "$bin" "$@" 2>&1 | tee -a "$LOG_FILE"
            exit 0
        fi
    fi
done

if command -v browser >/dev/null 2>&1; then
    echo "[INFO] Launching browser from PATH..."
    echo "[Fire4ArkOS] Launching browser from PATH" >> "$LOG_FILE"
    if [ "${FIRE4ARKOS_FROM_ES:-0}" = "1" ]; then
        exec browser "$@" >> "$LOG_FILE" 2>&1
    else
        browser "$@" 2>&1 | tee -a "$LOG_FILE"
        exit 0
    fi
fi

if [ -f "$LOG_FILE" ] && tail -n 10 "$LOG_FILE" | grep -q "First frame received from Firefox"; then
    # If we already got frames, don't show the error (the browser just exited)
    exit 0
fi

echo "[ERROR] browser binary not found in $APP_DIR or PATH" >&2
echo "[Fire4ArkOS] browser binary not found in $APP_DIR or PATH" >> "$LOG_FILE"
echo "[Fire4ArkOS] See $LOG_FILE for logs" >&2
exit 1
