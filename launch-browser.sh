#!/bin/bash

# Compatibility launcher for systems that still call launch-browser.sh.
# It now delegates directly to the same launch path as run_browser.sh and
# does not stop or restart EmulationStation.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/run_browser.sh" "$@"
