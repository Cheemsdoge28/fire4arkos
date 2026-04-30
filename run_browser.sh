#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Ensure PATH is sane
export PATH=/usr/local/bin:/usr/bin:/bin

# Ensure DISPLAY (important for Xvfb + SDL)
export DISPLAY=:99

echo "[INFO] Stopping EmulationStation..."

pkill -f emulationstation
sleep 1
echo "[INFO] Launching browser..."
/usr/local/bin/browser
echo "[INFO] Restarting EmulationStation..."
sudo -n systemctl start emulationstation 2>/dev/null || emulationstation &