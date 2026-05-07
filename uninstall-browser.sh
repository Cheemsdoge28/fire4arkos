#!/bin/bash
# Fire4ArkOS Browser-only uninstaller (ES-friendly)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1
export FIRE4ARKOS_FROM_ES=1

echo "Starting Fire4ArkOS Browser uninstaller..."
echo "This removes the ES entry and launcher (no theme removal)."

sudo -E bash ./install.sh --uninstall-browser "$@"

echo ""
echo "Uninstall finished!"
echo "Returning to EmulationStation in 5 seconds..."
sleep 5
