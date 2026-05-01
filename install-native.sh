#!/bin/bash
# Fire4ArkOS Native Install Script
# Sets up dependencies and builds the browser for the current host architecture.

set -e

echo "=========================================="
echo "Fire4ArkOS - Native Installation"
echo "=========================================="

# Check for Debian/Ubuntu
if [ ! -f /etc/debian_version ]; then
    echo "ERROR: This script is intended for Debian or Ubuntu-based systems."
    exit 1
fi

echo "[1/3] Updating package lists..."
sudo apt-get update

echo "[2/3] Installing dependencies..."
# Core build tools and SDL2
CORE_DEPS="build-essential git pkg-config make"
SDL_DEPS="libsdl2-dev libsdl2-ttf-dev"

# Graphic libraries for GL/GLES support
GL_DEPS="libgl1-mesa-dev libgles2-mesa-dev libegl1-mesa-dev libglew-dev"

# Runtime dependencies for the Firefox wrapper
RUNTIME_DEPS="python3 xvfb ffmpeg xdotool firefox fonts-liberation x11-utils"

# Hardware tools (optional, but useful for embedded targets)
HW_TOOLS="i2c-tools fbset fbcat"

sudo apt-get install -y \
    $CORE_DEPS \
    $SDL_DEPS \
    $GL_DEPS \
    $RUNTIME_DEPS \
    $HW_TOOLS

echo "[3/3] Building and installing..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Clean previous build if it exists
if [ -d "build" ]; then
    make clean || true
fi

# Build for the native architecture
echo "Building..."
make native

# Install to /usr/local/bin
echo "Installing..."
sudo make install

echo "=========================================="
echo "Native installation complete!"
echo "You can now run the browser with: fire4arkos"
echo "=========================================="