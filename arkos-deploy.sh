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

# Check if required files exist
echo "[1/5] Checking files..."
EXEC_PATH=""
for path in "$INSTALL_DIR/$EXEC_NAME" "$INSTALL_DIR/build/$EXEC_NAME" "$INSTALL_DIR/build/$EXEC_NAME.arm64"; do
    if [ -f "$path" ]; then
        EXEC_PATH="$path"
        break
    fi
done

if [ -z "$EXEC_PATH" ]; then
    echo "ERROR: $EXEC_NAME binary not found in $INSTALL_DIR or $INSTALL_DIR/build/"
    exit 1
fi

if [ ! -f "$INSTALL_DIR/$PYTHON_WRAPPER" ]; then
    echo "ERROR: $PYTHON_WRAPPER not found in $INSTALL_DIR"
    exit 1
fi
echo "  ✓ All core files present"
echo ""

# Check if SDL2 is installed
echo "[2/5] Checking dependencies..."

# Local .deb installation support
DEB_DIR="$INSTALL_DIR/deps/packages"
if [ -d "$DEB_DIR" ] && ls "$DEB_DIR"/*.deb &>/dev/null; then
    echo "  Found local .deb packages in $DEB_DIR"
    echo "  Attempting to install local dependencies..."
    if command -v dpkg &>/dev/null; then
        sudo dpkg -i "$DEB_DIR"/*.deb || echo "  WARNING: Some local packages failed to install (possibly missing base system deps)"
    else
        echo "  WARNING: dpkg not found, cannot install local .deb packages"
    fi
fi

if ! pkg-config --exists sdl2 2>/dev/null; then
    echo "WARNING: SDL2 not found via pkg-config"
    echo "  Install with: opkg install libsdl2-2.0 libsdl2-dev"
    echo "  Or: sudo apt install libsdl2-2.0"
fi

if ! command -v python3 &> /dev/null; then
    echo "WARNING: Python3 not found"
    echo "  Install with: opkg install python3"
fi

if ! command -v Xvfb &> /dev/null; then
    echo "WARNING: Xvfb not found"
    echo "  Real framebuffer capture needs Xvfb plus ffmpeg or ImageMagick import"
fi

if ! command -v ffmpeg &> /dev/null && ! command -v import &> /dev/null; then
    echo "WARNING: No framebuffer capture tool found"
    echo "  Install ffmpeg or ImageMagick to replace placeholder frames"
fi

if ! command -v xdotool &> /dev/null; then
    echo "WARNING: xdotool not found"
    echo "  URL loads and virtual keyboard text injection will be limited"
fi

if ! command -v firefox &> /dev/null; then
    echo "WARNING: Firefox not found"
    echo "  Attempting to install or download Firefox automatically."
    echo "  Note: Firefox is large (100-400MB). Redistribution may be subject to Mozilla's MPL."

    # Try common package managers first
    if command -v opkg &>/dev/null; then
        echo "  Using opkg to install firefox..."
        if opkg install firefox; then
            echo "  ✓ Firefox installed via opkg"
        else
            echo "  ✗ opkg install failed"
        fi
    elif command -v apt-get &>/dev/null; then
        echo "  Using apt-get to install firefox-esr/firefox..."
        if apt-get update && (apt-get install -y firefox-esr || apt-get install -y firefox); then
            echo "  ✓ Firefox installed via apt"
        else
            echo "  ✗ apt-get install failed"
        fi
    else
        echo "  No supported package manager (opkg/apt) found on device."
        # If user provided a tarball URL via env var, try downloading
        if [ -n "$FIREFOX_TARBALL_URL" ]; then
            echo "  Downloading Firefox from FIREFOX_TARBALL_URL..."
            echo "  This may take a while and requires sufficient disk space."
            mkdir -p /opt/firefox
            tmpf=$(mktemp /tmp/firefox.XXXXXX)
            if command -v curl &>/dev/null; then
                curl -L -o "$tmpf" "$FIREFOX_TARBALL_URL"
            elif command -v wget &>/dev/null; then
                wget -O "$tmpf" "$FIREFOX_TARBALL_URL"
            else
                echo "  No curl or wget available to download Firefox. Please install one or install Firefox manually."
                tmpf=""
            fi
            if [ -n "$tmpf" ] && [ -f "$tmpf" ]; then
                echo "  Extracting to /opt/firefox..."
                mkdir -p /opt/firefox
                if tar -xjf "$tmpf" -C /opt/firefox --strip-components=1 2>/dev/null; then
                    echo "  ✓ Extracted (bzip2)"
                elif tar -xzf "$tmpf" -C /opt/firefox --strip-components=1 2>/dev/null; then
                    echo "  ✓ Extracted (gzip)"
                else
                    echo "  ✗ Extraction failed"
                fi
                rm -f "$tmpf"
                if [ -x /opt/firefox/firefox ]; then
                    ln -sf /opt/firefox/firefox /usr/local/bin/firefox || true
                    echo "  ✓ Firefox installed to /opt/firefox"
                else
                    echo "  ✗ Firefox binary not found after extraction"
                fi
            fi
        else
            echo "  To auto-download a prebuilt Firefox, set the environment variable FIREFOX_TARBALL_URL to a linux-aarch64 Firefox tarball URL and re-run this script."
            echo "  Or install manually: opkg install firefox  OR  sudo apt install firefox-esr"
        fi
    fi
fi
echo "  ✓ Dependency check complete"
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
