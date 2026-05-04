#!/bin/bash
# Fire4ArkOS — Sound Test Launcher
# Launches the browser directly to the local audio test page.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Use the existing run_browser.sh wrapper
bash "$SCRIPT_DIR/run_browser.sh" "file://$SCRIPT_DIR/audio-test.html"
