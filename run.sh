#!/bin/bash

# Compatibility entry point for environments that expect run.sh.
# It uses the same direct launch path as run_browser.sh.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/run_browser.sh" "$@"
