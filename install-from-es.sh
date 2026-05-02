#!/bin/bash
# ============================================================================
# Fire4ArkOS Installer — EmulationStation Wrapper
# ============================================================================
# This script attempts to elevate privileges and run install.sh.
# Called by EmulationStation when "Fire4ArkOS Installer" system is selected.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

run_installer() {
    bash "$SCRIPT_DIR/install.sh" --from-es "$@"
}

# Already root?
if [ "$(id -u)" -eq 0 ]; then
    run_installer "$@"
    exit $?
fi

# Try sudo with no password prompt
if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    exec sudo bash "$SCRIPT_DIR/install.sh" --from-es "$@"
fi

# Try pkexec (graphical privilege escalation)
if command -v pkexec >/dev/null 2>&1; then
    exec pkexec env DISPLAY="${DISPLAY:-}" XAUTHORITY="${XAUTHORITY:-}" bash "$SCRIPT_DIR/install.sh" --from-es "$@"
fi

# Fallback: print instructions
echo ""
echo "========================================================================" >&2
echo "Fire4ArkOS Installation" >&2
echo "========================================================================" >&2
echo "" >&2
echo "This installer requires root access." >&2
echo "" >&2
echo "Run this from a terminal or SSH session:" >&2
echo "  sudo bash \"$SCRIPT_DIR/install.sh\"" >&2
echo "" >&2
echo "Or add this folder to EmulationStation ES_Systems.cfg as an installer:" >&2
echo "  <path>$SCRIPT_DIR</path>" >&2
echo "  <command>sudo bash %ROM%/install.sh</command>" >&2
echo "" >&2
echo "========================================================================">&2
exit 1