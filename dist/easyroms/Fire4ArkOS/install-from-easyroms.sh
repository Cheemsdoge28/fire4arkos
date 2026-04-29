#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="/opt/fire4arkos"

mkdir -p "$APP_DIR"
cp "$SCRIPT_DIR/browser" "$APP_DIR/browser"
cp "$SCRIPT_DIR/firefox-framebuffer-wrapper.py" "$APP_DIR/firefox-framebuffer-wrapper.py"
cp "$SCRIPT_DIR/arkos-deploy.sh" "$APP_DIR/arkos-deploy.sh"
chmod +x "$APP_DIR/browser" "$APP_DIR/firefox-framebuffer-wrapper.py" "$APP_DIR/arkos-deploy.sh"

bash "$APP_DIR/arkos-deploy.sh" "$APP_DIR"