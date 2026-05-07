#!/bin/bash
# Fire4ArkOS Browser-only installer (ES-friendly)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1
export FIRE4ARKOS_FROM_ES=1

echo "Starting Fire4ArkOS Browser installer..."
echo "This installs the browser and ES entry (no theme)."

sudo -E bash ./install.sh --browser-es "$@"

echo ""
echo "Installation finished!"
echo "Returning to EmulationStation in 5 seconds..."
sleep 5
