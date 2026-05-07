#!/bin/bash
# Fire4ArkOS Theme installer (ES-friendly)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1
export FIRE4ARKOS_FROM_ES=1

echo "Starting Fire4ArkOS Theme installer..."
echo "This installs the ES entry and theme assets."

sudo -E bash ./install.sh --theme-es "$@"

echo ""
echo "Installation finished!"
echo "Returning to EmulationStation in 5 seconds..."
sleep 5
