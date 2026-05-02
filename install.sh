#!/bin/bash
# ============================================================================
# Fire4ArkOS Installer
# ============================================================================
# Usage:
#   1. Copy the fire4arkos folder to /roms/fire4arkos/ on your R36S
#   2. SSH into device: ssh ark@<device-ip>
#   3. cd /roms/fire4arkos && sudo bash install.sh
#   4. Restart EmulationStation (Start > Quit > Restart EmulationStation)
#   5. "Fire4ArkOS" appears as a system in the main menu
#
# Options:
#   --uninstall    Remove Fire4ArkOS from the system
#   --rebuild      Force native compile even if pre-built binary exists
#   --from-es      Run non-interactively from EmulationStation wrapper
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
NC='\033[0m'

log_step() { echo -e "\n${CYAN}${BOLD}[$1]${NC} $2"; }
log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
log_err()  { echo -e "  ${RED}✗${NC} $1"; }
log_info() { echo -e "  $1"; }

FORCE_REBUILD=0
for arg in "$@"; do
    case "$arg" in
        --rebuild) FORCE_REBUILD=1 ;;
    esac
done

# ---------- Uninstall ----------
if [ "$1" = "--uninstall" ]; then
    echo -e "${BOLD}${APP_NAME} Uninstaller${NC}"
    echo ""

    rm -f "$BIN_DIR/browser" "$BIN_DIR/fire4arkos" "$BIN_DIR/firefox-framebuffer-wrapper.py"
    log_ok "Removed /usr/local/bin symlinks"

    for cfg in "$ES_CFG" "$ES_CFG_DUAL"; do
        if [ -f "$cfg" ] && grep -q "<name>$SYSTEM_NAME</name>" "$cfg"; then
            # Remove the full <system>...</system> block including the comment above it
            sed -i "/<!-- Fire4ArkOS Browser/,/<\/system>/d" "$cfg"
            log_ok "Removed $SYSTEM_NAME entry from $cfg"
        fi
    done

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

for required in firefox-framebuffer-wrapper.py run_browser.sh; do
    if [ ! -f "$SCRIPT_DIR/$required" ]; then
        log_err "$required not found in $SCRIPT_DIR"
        log_err "Make sure you're running this from the Fire4ArkOS directory."
        exit 1
    fi
done

ARCH="$(uname -m)"

# ============================================================================
# Step 1: Install runtime dependencies
# ============================================================================
log_step "1/6" "Installing dependencies..."

# ArkOS uses Ubuntu 19.10 (eoan) which is EOL — repos moved to old-releases
fix_apt_sources() {
    local sources="/etc/apt/sources.list"
    if grep -q "archive.ubuntu.com\|security.ubuntu.com\|ports.ubuntu.com" "$sources" 2>/dev/null; then
        if ! grep -q "old-releases.ubuntu.com" "$sources" 2>/dev/null; then
            log_info "Fixing APT sources for EOL Ubuntu (eoan → old-releases)..."
            cp "$sources" "$sources.bak.fire4arkos"
            sed -i 's|http://archive.ubuntu.com|http://old-releases.ubuntu.com|g' "$sources"
            sed -i 's|http://security.ubuntu.com|http://old-releases.ubuntu.com|g' "$sources"
            sed -i 's|http://ports.ubuntu.com|http://old-releases.ubuntu.com|g' "$sources"
            log_ok "APT sources fixed (backup: $sources.bak.fire4arkos)"
        fi
    fi
}

fix_apt_sources

# Fix any broken dpkg state
dpkg --configure -a 2>/dev/null || true
apt-get -y --fix-broken install 2>/dev/null || true

log_info "Updating package lists..."
apt-get update -qq 2>/dev/null || log_warn "apt-get update had errors (some repos may be unreachable)"

# Runtime dependencies only — no build tools unless we need to compile
RUNTIME_DEPS="python3 xvfb xdotool x11-utils apulse fonts-liberation"

log_info "Installing runtime dependencies..."
apt-get install -y $RUNTIME_DEPS 2>&1 | tail -3 || log_warn "Some packages may have failed"

# Firefox
if ! command -v firefox &>/dev/null; then
    log_info "Firefox not found — installing..."
    apt-get install -y firefox-esr 2>/dev/null || \
    apt-get install -y firefox 2>/dev/null || \
    log_warn "Could not install Firefox. Install manually: sudo apt-get install firefox-esr"
fi

# Verify critical runtime deps
MISSING=""
for cmd in python3 Xvfb xdotool firefox; do
    if ! command -v "$cmd" &>/dev/null; then
        MISSING="$MISSING $cmd"
    fi
done
if [ -n "$MISSING" ]; then
    log_err "Missing critical dependencies:$MISSING"
    log_err "Install them manually and re-run this script."
    exit 1
fi

log_ok "All runtime dependencies installed"

# ============================================================================
# Step 2: Get browser binary (pre-built or compile)
# ============================================================================
log_step "2/6" "Setting up browser binary..."

BROWSER_BIN=""

# Try pre-built binary first (shipped in bin/ or build/)
if [ "$FORCE_REBUILD" -eq 0 ]; then
    for candidate in \
        "$SCRIPT_DIR/bin/browser.arm64" \
        "$SCRIPT_DIR/bin/browser" \
        "$SCRIPT_DIR/build/browser" \
        "$SCRIPT_DIR/browser"; do
        if [ -f "$candidate" ]; then
            BROWSER_BIN="$candidate"
            break
        fi
    done
fi

if [ -n "$BROWSER_BIN" ] && [ "$FORCE_REBUILD" -eq 0 ]; then
    # Verify the binary actually runs on this architecture
    chmod +x "$BROWSER_BIN"
    if "$BROWSER_BIN" --version >/dev/null 2>&1 || file "$BROWSER_BIN" 2>/dev/null | grep -q "$ARCH"; then
        log_ok "Using pre-built binary: $BROWSER_BIN ($(du -h "$BROWSER_BIN" | cut -f1))"
    else
        log_warn "Pre-built binary exists but may not be compatible with $ARCH"
        echo -n "  Try using it anyway? (y/n, default=y): "
        read -r choice </dev/tty 2>/dev/null || choice="y"
        if [[ ! "$choice" =~ ^[Nn] ]]; then
            log_ok "Using pre-built binary: $BROWSER_BIN"
        else
            BROWSER_BIN=""
        fi
    fi
fi

# Fall back to native compile if no binary or --rebuild
if [ -z "$BROWSER_BIN" ]; then
    log_info "No pre-built binary available — compiling natively..."

    # Install build dependencies
    BUILD_DEPS="build-essential g++ make pkg-config libsdl2-dev libgles2-mesa-dev libegl1-mesa-dev"
    log_info "Installing build dependencies..."
    apt-get install -y $BUILD_DEPS 2>&1 | tail -3 || {
        log_err "Failed to install build dependencies"
        exit 1
    }

    if [ ! -f "$SCRIPT_DIR/Makefile" ] || [ ! -f "$SCRIPT_DIR/src/main.cpp" ]; then
        log_err "Source code not found (Makefile or src/main.cpp missing)"
        log_err "To compile, you need the full source tree."
        exit 1
    fi

    cd "$SCRIPT_DIR"
    make clean 2>/dev/null || true
    if make native 2>&1 | tail -10; then
        log_ok "Native build successful"
    else
        log_err "Build failed. Check compiler errors above."
        exit 1
    fi

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
fi

# Strip debug symbols for smaller binary
strip "$BROWSER_BIN" 2>/dev/null || true
log_ok "Binary ready: $BROWSER_BIN ($(du -h "$BROWSER_BIN" | cut -f1))"

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

cd /roms/fire4arkos 2>/dev/null || true

# Set performance governor for the browsing session
for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > "$gov" 2>/dev/null || true
done

# Launch the browser
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

ES_SYSTEM_BLOCK='  <!-- Fire4ArkOS Browser — added by install.sh -->\
  <system>\
    <name>fire4arkos</name>\
    <fullname>Fire4ArkOS Browser</fullname>\
    <path>/roms/fire4arkos</path>\
    <extension>.sh</extension>\
    <command>bash %ROM%</command>\
    <platform>pc</platform>\
    <theme>ports</theme>\
  </system>'

add_es_system() {
    local cfg="$1"

    if [ ! -f "$cfg" ]; then
        log_info "Skipping $cfg (file not found)"
        return
    fi

    if grep -q "<name>$SYSTEM_NAME</name>" "$cfg"; then
        log_ok "Already registered in $cfg"
        return
    fi

    cp "$cfg" "$cfg.bak.fire4arkos"
    log_info "Backed up $cfg → $cfg.bak.fire4arkos"

    if grep -q "</systemList>" "$cfg"; then
        sed -i "/<\/systemList>/i\\$ES_SYSTEM_BLOCK" "$cfg"
        log_ok "Registered $SYSTEM_NAME in $cfg"
    else
        log_warn "$cfg doesn't contain </systemList> — skipping"
    fi
}

add_es_system "$ES_CFG"
add_es_system "$ES_CFG_DUAL"

# ============================================================================
# Step 6: Verification
# ============================================================================
log_step "6/6" "Verifying installation..."

ERRORS=0

for check in \
    "browser binary:$BIN_DIR/browser" \
    "fire4arkos launcher:$BIN_DIR/fire4arkos" \
    "Python wrapper:$BIN_DIR/firefox-framebuffer-wrapper.py" \
    "Launch script:$LAUNCHER_SCRIPT"; do
    label="${check%%:*}"
    path="${check#*:}"
    if [ -f "$path" ]; then
        log_ok "$label: $path"
    else
        log_err "$label not found at $path"
        ERRORS=$((ERRORS + 1))
    fi
done

if command -v firefox &>/dev/null; then
    log_ok "Firefox: $(firefox --version 2>/dev/null || echo 'installed')"
else
    log_err "Firefox not found in PATH"
    ERRORS=$((ERRORS + 1))
fi

if command -v apulse &>/dev/null; then
    log_ok "apulse: $(which apulse)"
else
    log_warn "apulse not found — audio may not work"
fi

if [ -f "$ES_CFG" ] && grep -q "<name>$SYSTEM_NAME</name>" "$ES_CFG"; then
    log_ok "EmulationStation: registered"
else
    log_warn "EmulationStation: not registered (file may not exist yet)"
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
echo -e "  ${BOLD}Uninstall:${NC}  sudo bash $SCRIPT_DIR/install.sh --uninstall"
echo -e "  ${BOLD}Rebuild:${NC}    sudo bash $SCRIPT_DIR/install.sh --rebuild"
echo ""
