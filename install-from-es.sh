#!/bin/bash
# Fire4ArkOS One-Click Installer for EmulationStation
# This script is designed to be run from the "Tools" or "Ports" menu.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Ensure we're in the right directory
cd "$SCRIPT_DIR"

# Launch the main installer with root privileges
# We set FIRE4ARKOS_FROM_ES=1 to tell the installer to be non-interactive
export FIRE4ARKOS_FROM_ES=1

echo "Starting Fire4ArkOS One-Click Installer..."
echo "Please wait, this may take a few minutes..."

# Using sudo because ES runs as the 'ark' user
sudo -E bash ./install.sh "$@"

echo ""
echo "Installation finished!"
echo "Returning to EmulationStation in 5 seconds..."
sleep 5