#!/bin/bash
# ArkOS Deployment Script for Fire4ArkOS Browser
# This script sets up the browser on an ArkOS/R36S device (ARM64)
# Run this on the target device after copying files

set -e

INSTALL_DIR="${1:-.}"
INSTALL_DIR="$(cd "$INSTALL_DIR" && pwd)"
APP_NAME="Fire4ArkOS Browser"
EXEC_NAME="browser"
PYTHON_WRAPPER="firefox-framebuffer-wrapper.py"

echo "=========================================="
echo "$APP_NAME - ArkOS Deployment"
echo "=========================================="
echo ""

# [1/5] Checking environment and tools...
echo "[1/5] Checking environment and tools..."

# Fix any existing broken states (generic fix)
if [ "$(dpkg --get-selections | grep -c 'hold\|deinstall\|error')" -gt 0 ]; then
    echo "  System state seems inconsistent. Attempting to fix broken dependencies..."
    sudo apt-get -y --fix-broken install || true
fi

# We only install core TOOLS and DEV LIBS from the official repositories.
# We NEVER use local .deb files that could conflict with your OS versions.
CORE_PKGS="gdb libc6-dev libsdl2-dev linux-libc-dev g++ libstdc++-9-dev libsdl2-ttf-dev git python3 ninja-build cmake make i2c-tools usbutils fbcat fbset mmc-utils libglew-dev libegl1-mesa-dev libgl1-mesa-dev libgles2-mesa-dev libglu1-mesa-dev fonts-liberation xvfb ffmpeg xdotool"
echo "  Ensuring required packages are present: $CORE_PKGS"
sudo apt-get update
sudo apt-get install --reinstall -y $CORE_PKGS || echo "  WARNING: Some packages failed to install. Check your internet connection."

if ! command -v firefox &> /dev/null; then
    echo "WARNING: Firefox not found"
    echo "  Attempting to install firefox-esr..."
    sudo apt-get install -y firefox-esr || sudo apt-get install -y firefox || true
fi

if [ ! -d "$INSTALL_DIR/libs" ]; then
    echo "WARNING: Local 'libs' directory not found in $INSTALL_DIR"
    echo "  The browser may fail to launch if SDL2 or other dependencies are missing from your OS."
fi

echo "  ✓ Environment check complete"
echo ""

# [2/5] Checking files...
echo "[2/5] Checking files..."
EXEC_PATH=""
for path in "$INSTALL_DIR/$EXEC_NAME" "$INSTALL_DIR/build/$EXEC_NAME" "$INSTALL_DIR/build/$EXEC_NAME.arm64"; do
    if [ -f "$path" ]; then
        EXEC_PATH="$path"
        break
    fi
done

if [ -z "$EXEC_PATH" ]; then
    echo "WARNING: $EXEC_NAME binary not found in $INSTALL_DIR or $INSTALL_DIR/build/"
    echo "Would you like to attempt to build it natively now? (y/n)"
    read -r build_choice
    if [[ "$build_choice" =~ ^[Yy]$ ]]; then
        if command -v make &>/dev/null && command -v g++ &>/dev/null; then
            echo "Building natively..."
            make native
            # Re-check
            for path in "$INSTALL_DIR/build/$EXEC_NAME" "$INSTALL_DIR/build/$EXEC_NAME.arm64"; do
                if [ -f "$path" ]; then
                    EXEC_PATH="$path"
                    break
                fi
            done
        else
            echo "ERROR: 'make' or 'g++' not found. Please install build-essential or copy a pre-built binary."
            exit 1
        fi
    fi
    
    if [ -z "$EXEC_PATH" ]; then
        echo "ERROR: $EXEC_NAME binary still not found. Deployment aborted."
        exit 1
    fi
fi

if [ ! -f "$INSTALL_DIR/$PYTHON_WRAPPER" ]; then
    echo "ERROR: $PYTHON_WRAPPER not found in $INSTALL_DIR"
    exit 1
fi
echo "  ✓ All core files present"
echo ""

# Make executable
echo "[3/5] Setting permissions..."
chmod +x "$EXEC_PATH"
chmod +x "$INSTALL_DIR/$PYTHON_WRAPPER"
if [ -f "$INSTALL_DIR/run_browser.sh" ]; then
    chmod +x "$INSTALL_DIR/run_browser.sh"
fi
echo "  ✓ Permissions set"
echo ""

# Create symlink or copy to bin
echo "[4/5] Installing to system..."
mkdir -p /usr/local/bin
if [ "$INSTALL_DIR" != "/usr/local/bin" ]; then
    ln -sf "$EXEC_PATH" /usr/local/bin/$EXEC_NAME || cp "$EXEC_PATH" /usr/local/bin/$EXEC_NAME
    ln -sf "$INSTALL_DIR/$PYTHON_WRAPPER" /usr/local/bin/$PYTHON_WRAPPER || true
    if [ -f "$INSTALL_DIR/run_browser.sh" ]; then
        ln -sf "$INSTALL_DIR/run_browser.sh" /usr/local/bin/fire4arkos || true
    fi
    echo "  ✓ Installed to /usr/local/bin/"
fi
echo ""

# Create launcher script if run_browser.sh is missing or we need a wrapper
if [ ! -f "/usr/local/bin/fire4arkos" ]; then
    echo "[5/5] Creating launcher..."
    LAUNCHER="/usr/local/bin/fire4arkos"
    cat > "$LAUNCHER" << 'LAUNCHER_SCRIPT'
#!/bin/bash
# Fire4ArkOS Browser Launcher
export FIRE4ARKOS_HOME="__INSTALL_DIR__"
exec "$FIRE4ARKOS_HOME/run_browser.sh" "$@"
LAUNCHER_SCRIPT
    sed -i "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$LAUNCHER"
    chmod +x "$LAUNCHER"
    echo "  ✓ Created $LAUNCHER"
else
    echo "[5/5] Launcher already linked to run_browser.sh"
fi
echo ""

echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "Usage:"
echo "  fire4arkos                    # Launch with default URL (example.com)"
echo "  fire4arkos https://example.com  # Launch with specific URL"
echo "  $(dirname "$0")/$EXEC_NAME    # Direct launch"
echo ""
echo "Environment:"
echo "  SDL2: $(pkg-config --modversion sdl2 2>/dev/null || echo 'not found')"
echo "  Firefox: $(firefox --version 2>/dev/null || echo 'not found')"
echo "  Python3: $(python3 --version 2>/dev/null || echo 'not found')"
echo ""
echo "Tips:"
echo "  - Press 'S' or 'Tab' to edit URL"
echo "  - Press 'T' or Left Shoulder for page text keyboard"
echo "  - Use D-pad to scroll"
echo "  - Press 'Return' to load/click"
echo "  - Press 'Backspace' to go back"
echo "  - Press 'R' to reload"
echo "  - Press 'Q' or 'Esc' to quit"
echo ""
