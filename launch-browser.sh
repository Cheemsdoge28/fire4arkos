#!/bin/bash
# Script to gracefully close EmulationStation, run Fire4ArkOS browser, and reopen EmulationStation.

set -e

# Disable cursor
setterm -cursor off

echo "Stopping EmulationStation gracefully..."

# Try systemctl first if on a systemd OS
if systemctl list-units --full -all | grep -Fq "emulationstation.service"; then
    sudo systemctl stop emulationstation
else
    # Fallback to killing the process
    if pgrep -x "emulationstation" > /dev/null; then
        killall -15 emulationstation
        sleep 2
        # Force kill if still running
        killall -9 emulationstation 2>/dev/null || true
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

# Set the URL to the first argument or default a common homepage
URL="${1:-https://www.google.com}"

# Determine which binary to run based on typical installation locations
if command -v fire4arkos > /dev/null; then
    fire4arkos "$URL"
elif [ -x "/usr/local/bin/browser" ]; then
    /usr/local/bin/browser "$URL"
elif [ -x "./build/browser" ]; then
    ./build/browser "$URL"
elif [ -x "./browser" ]; then
    ./browser "$URL"
else
    echo "ERROR: Could not find Fire4ArkOS executable. Try running 'sudo make install' first."
fi

# Let the framebuffer catch up
sleep 1

# Restart EmulationStation when browser is closed
clear
echo "Restarting EmulationStation..."

if [ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
    echo ondemand | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null
fi

if systemctl list-units --full -all | grep -Fq "emulationstation.service"; then
    sudo systemctl start emulationstation
else
    # Fallback to starting it directly
    nohup emulationstation > /dev/null 2>&1 &
fi

# Re-enable cursor
setterm -cursor on
