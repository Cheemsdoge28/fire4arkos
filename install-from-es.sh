#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

run_installer() {
    exec bash "$SCRIPT_DIR/install.sh" --from-es "$@"
}

if [ "$(id -u)" -eq 0 ]; then
    run_installer "$@"
fi

if command -v sudo >/dev/null 2>&1; then
    if sudo -n true >/dev/null 2>&1; then
        exec sudo bash "$SCRIPT_DIR/install.sh" --from-es "$@"
    fi
fi

if command -v pkexec >/dev/null 2>&1; then
    exec pkexec env DISPLAY="${DISPLAY:-}" XAUTHORITY="${XAUTHORITY:-}" bash "$SCRIPT_DIR/install.sh" --from-es "$@"
fi

for terminal in xterm lxterminal qterminal mate-terminal xfce4-terminal; do
    if command -v "$terminal" >/dev/null 2>&1; then
        exec "$terminal" -e bash -lc "sudo bash '$SCRIPT_DIR/install.sh' --from-es"
    fi
done

echo "Fire4ArkOS installer needs root access. Launch it from a terminal with sudo:" >&2
echo "  sudo bash $SCRIPT_DIR/install.sh" >&2
exit 1