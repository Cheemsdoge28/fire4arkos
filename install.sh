#!/bin/bash
# ============================================================================
# Fire4ArkOS Installer
# ============================================================================
# Usage:
#   1. Copy release files to /roms/fire4arkos/ on your R36S
#   2. SSH into device: ssh ark@<device-ip>
#   3. cd /roms/fire4arkos && sudo bash install.sh
#   4. Restart EmulationStation (Start > Quit > Restart EmulationStation)
#   5. "Fire4ArkOS" appears as a system in the main menu
#
# Uninstall:
#   sudo bash install.sh --uninstall
# ============================================================================

set -e

# ---------- Constants ----------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Fire4ArkOS"
INSTALL_DIR="/roms/fire4arkos"
BIN_DIR="/usr/local/bin"
ES_CFG="/etc/emulationstation/es_systems.cfg"
ES_CFG_DUAL="/etc/emulationstation/es_systems.cfg.dual"
LAUNCHER_SCRIPT="$INSTALL_DIR/Fire4ArkOS Browser.sh"
SYSTEM_NAME="fire4arkos"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

log_step() { echo -e "\n${CYAN}${BOLD}[$1]${NC} $2"; }
log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
log_err()  { echo -e "  ${RED}✗${NC} $1"; }
log_info() { echo -e "  $1"; }

# ---------- Uninstall ----------
if [ "$1" = "--uninstall" ]; then
    echo -e "${BOLD}${APP_NAME} Uninstaller${NC}"
    echo ""

    # Remove symlinks
    rm -f "$BIN_DIR/browser"
    rm -f "$BIN_DIR/fire4arkos"
    rm -f "$BIN_DIR/firefox-framebuffer-wrapper.py"
    log_ok "Removed /usr/local/bin symlinks"

    # Remove ES entry from es_systems.cfg
    for cfg in "$ES_CFG" "$ES_CFG_DUAL"; do
        if [ -f "$cfg" ] && grep -q "<name>$SYSTEM_NAME</name>" "$cfg"; then
            # Remove the <system>...</system> block for fire4arkos
            sed -i "/<name>$SYSTEM_NAME<\/name>/,/<\/system>/d" "$cfg"
            # Also remove the opening <system> tag that precedes it
            # (sed above removes from <name> to </system>, we need the <system> before it)
            sed -i '/<system>/{N;/^\s*<system>\s*$/d}' "$cfg" 2>/dev/null || true
            log_ok "Removed $SYSTEM_NAME entry from $cfg"
        fi
    done

    # Remove launch script
    rm -f "$LAUNCHER_SCRIPT"
    log_ok "Removed launch script"

    echo ""
    echo -e "${GREEN}Uninstall complete.${NC} Restart EmulationStation to apply."
    echo "Your files in $INSTALL_DIR are preserved."
    exit 0
fi

# ---------- Banner ----------
echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  ${APP_NAME} Installer${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""

# ---------- Pre-flight checks ----------
if [ "$(id -u)" -ne 0 ]; then
    log_err "This script must be run as root (use: sudo bash install.sh)"
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/firefox-framebuffer-wrapper.py" ]; then
    log_err "firefox-framebuffer-wrapper.py not found in $SCRIPT_DIR"
    log_err "Make sure you're running this from the Fire4ArkOS directory."
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/run_browser.sh" ]; then
    log_err "run_browser.sh not found in $SCRIPT_DIR"
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/Makefile" ]; then
    log_err "Makefile not found in $SCRIPT_DIR"
    exit 1
fi

# Detect architecture
ARCH="$(uname -m)"
if [ "$ARCH" != "aarch64" ]; then
    log_warn "Expected aarch64 architecture, got $ARCH. Build may fail."
fi

# ============================================================================
# Step 1: Fix APT sources + Install dependencies
# ============================================================================
log_step "1/6" "Installing dependencies..."

# ArkOS uses Ubuntu 19.10 (eoan) which is EOL — repos moved to old-releases
fix_apt_sources() {
    local sources="/etc/apt/sources.list"
    if grep -q "archive.ubuntu.com" "$sources" 2>/dev/null || \
       grep -q "security.ubuntu.com" "$sources" 2>/dev/null; then
        log_info "Fixing APT sources for EOL Ubuntu (eoan → old-releases)..."
        cp "$sources" "$sources.bak.fire4arkos"
        sed -i 's|http://archive.ubuntu.com|http://old-releases.ubuntu.com|g' "$sources"
        sed -i 's|http://security.ubuntu.com|http://old-releases.ubuntu.com|g' "$sources"
        sed -i 's|http://ports.ubuntu.com|http://old-releases.ubuntu.com|g' "$sources"
        log_ok "APT sources fixed (backup: $sources.bak.fire4arkos)"
    fi
}

fix_apt_sources

# Fix any broken dpkg state before we start
dpkg --configure -a 2>/dev/null || true
apt-get -y --fix-broken install 2>/dev/null || true

log_info "Updating package lists..."
if ! apt-get update -qq 2>/dev/null; then
    log_warn "apt-get update had errors (some repos may be unreachable)"
fi

# Build dependencies
BUILD_DEPS="build-essential g++ make pkg-config"

# SDL2 — rendering backend
SDL_DEPS="libsdl2-dev"

# Runtime — Firefox wrapper requirements
RUNTIME_DEPS="python3 xvfb xdotool x11-utils"

# Audio — apulse gives Firefox PulseAudio API via direct ALSA (no daemon overhead)
AUDIO_DEPS="apulse"

# Fonts — for readable text rendering
FONT_DEPS="fonts-liberation"

# GLES2/EGL — for hardware-accelerated SDL on Mali GPU
GL_DEPS="libgles2-mesa-dev libegl1-mesa-dev"

# Shared memory — needed for SHM frame transfer
MISC_DEPS="librt-ocaml-dev"

ALL_DEPS="$BUILD_DEPS $SDL_DEPS $RUNTIME_DEPS $AUDIO_DEPS $FONT_DEPS $GL_DEPS"

log_info "Installing: $ALL_DEPS"
apt-get install -y $ALL_DEPS 2>&1 | tail -5 || {
    log_warn "Some packages may have failed — continuing anyway"
}

# Firefox: check if already installed, try multiple package names
if ! command -v firefox &>/dev/null; then
    log_info "Firefox not found — installing..."
    apt-get install -y firefox-esr 2>/dev/null || \
    apt-get install -y firefox 2>/dev/null || {
        log_warn "Could not install Firefox via apt."
        log_warn "Firefox is REQUIRED. Install it manually: sudo apt-get install firefox-esr"
    }
fi

# Verify critical dependencies
MISSING=""
for cmd in python3 Xvfb xdotool firefox make g++; do
    if ! command -v "$cmd" &>/dev/null; then
        MISSING="$MISSING $cmd"
    fi
done

if [ -n "$MISSING" ]; then
    log_err "Missing critical dependencies:$MISSING"
    log_err "Install them manually and re-run this script."
    exit 1
fi

log_ok "All dependencies installed"

# ============================================================================
# Step 2: Build the browser binary
# ============================================================================
log_step "2/6" "Building browser binary (native)..."

cd "$SCRIPT_DIR"

# Clean any stale build
make clean 2>/dev/null || true

# Build natively — Makefile auto-detects aarch64 and tunes for Cortex-A35
if make native 2>&1 | tail -10; then
    log_ok "Build successful"
else
    log_err "Build failed. Check compiler errors above."
    exit 1
fi

# Verify the binary exists
BROWSER_BIN=""
for candidate in "$SCRIPT_DIR/build/browser" "$SCRIPT_DIR/build/browser.arm64"; do
    if [ -f "$candidate" ]; then
        BROWSER_BIN="$candidate"
        break
    fi
done

if [ -z "$BROWSER_BIN" ]; then
    log_err "Browser binary not found after build."
    exit 1
fi

# Strip debug symbols for smaller binary
strip "$BROWSER_BIN" 2>/dev/null || true
log_ok "Binary: $BROWSER_BIN ($(du -h "$BROWSER_BIN" | cut -f1))"

# ============================================================================
# Step 3: Install to system
# ============================================================================
log_step "3/6" "Installing to system..."

mkdir -p "$BIN_DIR"

# Install the browser binary
cp -f "$BROWSER_BIN" "$BIN_DIR/browser"
chmod +x "$BIN_DIR/browser"
log_ok "Installed browser → $BIN_DIR/browser"

# Symlink the Python wrapper
ln -sf "$SCRIPT_DIR/firefox-framebuffer-wrapper.py" "$BIN_DIR/firefox-framebuffer-wrapper.py"
chmod +x "$SCRIPT_DIR/firefox-framebuffer-wrapper.py"
log_ok "Linked firefox-framebuffer-wrapper.py"

# Symlink the launcher script
ln -sf "$SCRIPT_DIR/run_browser.sh" "$BIN_DIR/fire4arkos"
chmod +x "$SCRIPT_DIR/run_browser.sh"
log_ok "Linked run_browser.sh → $BIN_DIR/fire4arkos"

# Make all scripts executable
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true
chmod +x "$SCRIPT_DIR"/*.py 2>/dev/null || true

# ============================================================================
# Step 4: Create EmulationStation launch script
# ============================================================================
log_step "4/6" "Creating EmulationStation launch script..."

cat > "$LAUNCHER_SCRIPT" << 'LAUNCH_EOF'
#!/bin/bash
# Fire4ArkOS Browser — EmulationStation Launch Script
# This file is called by EmulationStation when the user selects Fire4ArkOS.

# Ensure we're running from the correct directory
cd /roms/fire4arkos 2>/dev/null || true

# Set performance governor for the browsing session
for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > "$gov" 2>/dev/null || true
done

# Launch the browser with a default page
# Pass FIRE4ARKOS_INTERNAL_SCALE=2 for better performance on RK3326
export FIRE4ARKOS_INTERNAL_SCALE="${FIRE4ARKOS_INTERNAL_SCALE:-2}"
export FIRE4ARKOS_SET_GOVERNOR=0

/usr/local/bin/fire4arkos "${1:-https://www.google.com}"

# Restore ondemand governor after browser exits
for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo ondemand > "$gov" 2>/dev/null || true
done
LAUNCH_EOF

chmod +x "$LAUNCHER_SCRIPT"
log_ok "Created: $LAUNCHER_SCRIPT"

# ============================================================================
# Step 5: Register with EmulationStation
# ============================================================================
log_step "5/6" "Registering with EmulationStation..."

# The system entry XML block
ES_SYSTEM_BLOCK="
  <!-- Fire4ArkOS Browser — added by install.sh -->
  <system>
    <name>$SYSTEM_NAME</name>
    <fullname>Fire4ArkOS Browser</fullname>
    <path>/roms/fire4arkos</path>
    <extension>.sh</extension>
    <command>bash %ROM%</command>
    <platform>pc</platform>
    <theme>ports</theme>
  </system>"

add_es_system() {
    local cfg="$1"

    if [ ! -f "$cfg" ]; then
        log_info "Skipping $cfg (file not found)"
        return
    fi

    # Check if already registered
    if grep -q "<name>$SYSTEM_NAME</name>" "$cfg"; then
        log_ok "Already registered in $cfg"
        return
    fi

    # Backup the original
    cp "$cfg" "$cfg.bak.fire4arkos"
    log_info "Backed up $cfg → $cfg.bak.fire4arkos"

    # Insert the system block before </systemList>
    if grep -q "</systemList>" "$cfg"; then
        sed -i "s|</systemList>|$ES_SYSTEM_BLOCK\n</systemList>|" "$cfg"
        log_ok "Registered $SYSTEM_NAME in $cfg"
    else
        log_warn "$cfg doesn't contain </systemList> — skipping"
    fi
}

# Register in both single-SD and dual-SD config files
add_es_system "$ES_CFG"
add_es_system "$ES_CFG_DUAL"

# ============================================================================
# Step 6: Verification
# ============================================================================
log_step "6/6" "Verifying installation..."

ERRORS=0

# Check binary
if [ -x "$BIN_DIR/browser" ]; then
    log_ok "browser binary: $BIN_DIR/browser"
else
    log_err "browser binary not found at $BIN_DIR/browser"
    ERRORS=$((ERRORS + 1))
fi

# Check launcher
if [ -x "$BIN_DIR/fire4arkos" ]; then
    log_ok "fire4arkos launcher: $BIN_DIR/fire4arkos"
else
    log_err "fire4arkos launcher not found"
    ERRORS=$((ERRORS + 1))
fi

# Check wrapper
if [ -f "$BIN_DIR/firefox-framebuffer-wrapper.py" ]; then
    log_ok "Python wrapper: $BIN_DIR/firefox-framebuffer-wrapper.py"
else
    log_err "Python wrapper not found"
    ERRORS=$((ERRORS + 1))
fi

# Check Firefox
if command -v firefox &>/dev/null; then
    FF_VERSION=$(firefox --version 2>/dev/null || echo "unknown")
    log_ok "Firefox: $FF_VERSION"
else
    log_err "Firefox not found in PATH"
    ERRORS=$((ERRORS + 1))
fi

# Check apulse
if command -v apulse &>/dev/null; then
    log_ok "apulse: $(which apulse)"
else
    log_warn "apulse not found — audio may not work"
fi

# Check ES registration
if [ -f "$ES_CFG" ] && grep -q "<name>$SYSTEM_NAME</name>" "$ES_CFG"; then
    log_ok "EmulationStation: registered in es_systems.cfg"
else
    log_warn "EmulationStation: not registered (manual restart may be needed)"
fi

# Check launch script
if [ -f "$LAUNCHER_SCRIPT" ]; then
    log_ok "Launch script: $LAUNCHER_SCRIPT"
else
    log_err "Launch script not found"
    ERRORS=$((ERRORS + 1))
fi

# ---------- Summary ----------
echo ""
echo -e "${BOLD}============================================${NC}"
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}${BOLD}  Installation Complete!${NC}"
else
    echo -e "${YELLOW}${BOLD}  Installation Complete (with $ERRORS warnings)${NC}"
fi
echo -e "${BOLD}============================================${NC}"
echo ""
echo -e "  ${BOLD}Next steps:${NC}"
echo -e "  1. Restart EmulationStation:"
echo -e "     ${CYAN}Start → Quit → Restart EmulationStation${NC}"
echo -e "  2. Navigate to ${BOLD}Fire4ArkOS Browser${NC} in the system list"
echo -e "  3. Select ${BOLD}Fire4ArkOS Browser.sh${NC} to launch"
echo ""
echo -e "  ${BOLD}Or launch directly via SSH:${NC}"
echo -e "     ${CYAN}fire4arkos \"https://www.google.com\"${NC}"
echo ""
echo -e "  ${BOLD}Uninstall:${NC}"
echo -e "     ${CYAN}sudo bash /roms/fire4arkos/install.sh --uninstall${NC}"
echo ""
