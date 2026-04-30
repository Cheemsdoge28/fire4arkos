#!/bin/bash
# Script to gracefully close EmulationStation, run Fire4ArkOS browser, and reopen EmulationStation.

set -u

ES_STOPPED=0
ES_SERVICE_PRESENT=0
BROWSER_BIN=""

cleanup() {
    if [ "$ES_STOPPED" -eq 1 ]; then
        echo "Restarting EmulationStation..."
        if command -v systemctl >/dev/null 2>&1 && [ "$ES_SERVICE_PRESENT" -eq 1 ]; then
            sudo -n systemctl start emulationstation 2>/dev/null || true
        else
            nohup emulationstation >/dev/null 2>&1 &
        fi
    fi

    # Re-enable cursor even if browser launch failed.
    setterm -cursor on 2>/dev/null || true
}

trap cleanup EXIT

# Disable cursor
setterm -cursor off

echo "Stopping EmulationStation gracefully..."

# Try systemctl first if on a systemd OS
if command -v systemctl >/dev/null 2>&1 && systemctl list-units --full -all 2>/dev/null | grep -Fq "emulationstation.service"; then
    ES_SERVICE_PRESENT=1
    sudo -n systemctl stop emulationstation 2>/dev/null || true
    ES_STOPPED=1
else
    # Fallback to killing the process
    if pgrep -x "emulationstation" > /dev/null; then
        killall -15 emulationstation
        sleep 2
        # Force kill if still running
        killall -9 emulationstation 2>/dev/null || true
        ES_STOPPED=1
    fi
fi

# Give it a moment to free up the framebuffer
sleep 1

# Clear terminal screen
clear

# Set CPU governor to performance for maximum speed
if [ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
    echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null
fi

echo "Launching Fire4ArkOS Browser..."

# Set environment for KMSDRM and GLES per optimization guide
export SDL_VIDEODRIVER=kmsdrm
export SDL_RENDER_DRIVER=opengles2
export SDL_HINT_FRAMEBUFFER_ACCELERATION=1

# Sane defaults for resolution and framerate
export WIDTH=${WIDTH:-640}
export HEIGHT=${HEIGHT:-480}
export FPS=${FPS:-15}
export PIXFMT=${PIXFMT:-bgra}

# Set the URL to the first argument or default a common homepage
URL="${1:-https://www.google.com}"

# Determine which binary to run based on typical installation locations
if command -v fire4arkos >/dev/null 2>&1; then
    BROWSER_BIN="$(command -v fire4arkos)"
elif [ -x "/usr/local/bin/browser" ]; then
    BROWSER_BIN="/usr/local/bin/browser"
elif [ -x "./build/browser" ]; then
    BROWSER_BIN="./build/browser"
elif [ -x "./browser" ]; then
    BROWSER_BIN="./browser"
fi

if [ -z "$BROWSER_BIN" ]; then
    echo "ERROR: Could not find Fire4ArkOS executable. Try running 'sudo make install' first."
    exit 1
fi

"$BROWSER_BIN" "$URL"

# Let the framebuffer catch up
sleep 1

clear

if [ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
    echo ondemand | sudo -n tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null 2>&1 || true
fi
