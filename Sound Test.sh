#!/bin/bash
# Fire4ArkOS — Sound Test Launcher
# Launches the browser directly to the local audio test page.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Use the existing run_browser.sh wrapper (check scripts/ or root)
RUN_BIN="$SCRIPT_DIR/scripts/run_browser.sh"
if [ ! -f "$RUN_BIN" ]; then RUN_BIN="$SCRIPT_DIR/run_browser.sh"; fi

bash "$RUN_BIN" "file://$SCRIPT_DIR/audio-test.html"
