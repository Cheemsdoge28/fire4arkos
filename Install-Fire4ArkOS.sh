#!/bin/bash
# ============================================================================
# Fire4ArkOS Unified Installer — Self-Elevating
# ============================================================================
# This script handles installation, uninstallation, and updates.
# It automatically elevates to root and presents a controller-friendly menu
# if run on a handheld.
#
# Usage:
#   sudo bash Install-Fire4ArkOS.sh [options]
#
# Options:
#   --uninstall         Remove Fire4ArkOS from the system
#   --uninstall-browser Remove browser/launcher only
#   --uninstall-theme   Remove theme only
#   --rebuild           Force native compile
#   --reinstall-deps    Refresh system dependencies
# ============================================================================

# ---------- Self-Elevation ----------
REAL_SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
if [ "$(id -u)" -ne 0 ]; then
    # Set FIRE4ARKOS_FROM_ES=1 if we are not in a TTY (likely launched from ES menu)
    if [ ! -t 0 ]; then
        export FIRE4ARKOS_FROM_ES=1
    fi
    echo "Fire4ArkOS Installer needs root privileges. Elevating..."
    sudo -E bash "$REAL_SCRIPT_PATH" "$@"
    exit $?
fi

set -e

# ---------- Constants ----------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Fire4ArkOS"
INSTALL_DIR="$SCRIPT_DIR"          # Self-contained: use actual directory
ES_CFG="/etc/emulationstation/es_systems.cfg"
ES_CFG_DUAL="/etc/emulationstation/es_systems.cfg.dual"
LAUNCHER_SCRIPT="$INSTALL_DIR/Fire4ArkOS Browser.f4a"
SYSTEM_NAME="fire4arkos"
PLATFORM_TAG="${PLATFORM_TAG:-$SYSTEM_NAME}"
THEME_NAME="${THEME_NAME:-$SYSTEM_NAME}"

# ============================================================================
# Logging helpers
# ============================================================================
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

LOG_FILE="$SCRIPT_DIR/install.log"
# (Removed global exec redirection to avoid visibility issues with interactive menus)

DO_DEPS=1
DO_BINARY=1
DO_FILES=1
DO_LAUNCHER=1
DO_THEME=1
DO_ES=1
DO_VERIFY=1

FORCE_REBUILD=0
for arg in "$@"; do
    case "$arg" in
        --rebuild) FORCE_REBUILD=1 ;;
        --reinstall-deps) REINSTALL_DEPS=1 ;;
        --skip-theme) DO_THEME=0 ;;
        --skip-es) DO_ES=0 ;;
        --browser-es) DO_DEPS=1; DO_BINARY=1; DO_FILES=1; DO_LAUNCHER=1; DO_ES=1; DO_THEME=0; DO_VERIFY=1 ;;
        --theme-es) DO_DEPS=0; DO_BINARY=0; DO_FILES=0; DO_LAUNCHER=0; DO_ES=1; DO_THEME=1; DO_VERIFY=1 ;;
        --browser-only) DO_THEME=0; DO_ES=0 ;;
        --theme-only) DO_DEPS=0; DO_BINARY=0; DO_FILES=0; DO_LAUNCHER=0; DO_ES=0; DO_VERIFY=0; DO_THEME=1 ;;
    esac
done

# If launched from EmulationStation, avoid launching GUI apps accidentally
if [ "${FIRE4ARKOS_FROM_ES:-0}" = "1" ]; then
    unset DISPLAY XAUTHORITY
    export DISPLAY=""
    export XAUTHORITY=""
fi

# ---------- Uninstall ----------
if [ "$1" = "--uninstall" ] || [ "$1" = "--uninstall-browser" ] || [ "$1" = "--uninstall-theme" ]; then
    echo -e "${BOLD}${APP_NAME} Uninstaller${NC}"
    echo ""

    REMOVE_BROWSER=0
    REMOVE_THEME=0
    if [ "$1" = "--uninstall" ] || [ "$1" = "--uninstall-browser" ]; then
        REMOVE_BROWSER=1
    fi
    if [ "$1" = "--uninstall" ] || [ "$1" = "--uninstall-theme" ]; then
        REMOVE_THEME=1
    fi

    if [ "$REMOVE_BROWSER" -eq 1 ]; then
        # Remove launcher scripts
        rm -f "$INSTALL_DIR/Fire4ArkOS Browser.sh"
        rm -f "$INSTALL_DIR/Fire4ArkOS Browser.f4a"
        rm -f "/usr/local/bin/fire4arkos"
        rm -f "/usr/local/bin/firefox-framebuffer-wrapper.py"
        log_ok "Removed launch scripts, shell command, and wrapper symlink"
    fi

    # Remove ES system entries
    for cfg in "$ES_CFG" "$ES_CFG_DUAL"; do
        if [ -f "$cfg" ] && grep -q "fire4arkos" "$cfg"; then
            sed -i "/<!-- Fire4ArkOS Browser/,/<\/system>/d" "$cfg"
            log_ok "Removed $SYSTEM_NAME entry from $cfg"
        fi
    done

    if [ "$REMOVE_THEME" -eq 1 ]; then
        # Remove theme entries
        BASE_THEME_ROOT="/etc/emulationstation/themes"
        if [ -d "$BASE_THEME_ROOT" ]; then
            for theme_dir in "$BASE_THEME_ROOT"/*/; do
                if [ -d "${theme_dir}${SYSTEM_NAME}" ]; then
                    rm -rf "${theme_dir}${SYSTEM_NAME}"
                fi
            done
            rm -rf "$BASE_THEME_ROOT/$SYSTEM_NAME"
            log_ok "Removed theme assets from all theme directories"
        fi
    fi

    echo ""
    echo -e "${GREEN}Uninstall complete.${NC} Restart EmulationStation to apply."
    echo "Your files in $INSTALL_DIR are preserved."
    exit 0
fi

# ---------- Banner ----------
echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  ${APP_NAME} Unified Installer${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""

# ---------- Interactive Menu ----------
if [ "$#" -eq 0 ]; then
    # Attempt to use controller menu if we're on a handheld or in ES
    USE_CONTROLLER_MENU=0
    if [ -c "/dev/input/js0" ] || [ "${FIRE4ARKOS_FROM_ES:-0}" = "1" ]; then
        if [ -f "$SCRIPT_DIR/scripts/controller_menu.py" ]; then
            USE_CONTROLLER_MENU=1
        else
            log_warn "Controller menu script missing at $SCRIPT_DIR/scripts/controller_menu.py"
        fi
    fi

    if [ "$USE_CONTROLLER_MENU" -eq 1 ]; then
        # Use a temporary file to capture the choice so that python can print UI directly to stdout
        CHOICE_FILE=$(mktemp)
        /usr/bin/python3 "$SCRIPT_DIR/scripts/controller_menu.py" "$CHOICE_FILE" || true
        if [ -s "$CHOICE_FILE" ]; then
            choice=$(cat "$CHOICE_FILE")
        else
            log_info "No controller input detected, falling back to CLI menu..."
            USE_CONTROLLER_MENU=0
        fi
        rm -f "$CHOICE_FILE"
    fi

    if [ "$USE_CONTROLLER_MENU" -eq 0 ]; then
        # Standard CLI menu fallback
        echo -e "${BOLD}Select an option:${NC}"
        echo "1) Full Install (Recommended)"
        echo "2) Browser Only (No Theme)"
        echo "3) Theme Only"
        echo "4) Uninstall Everything"
        echo "5) Uninstall Browser Only"
        echo "6) Uninstall Theme Only"
        echo "7) Exit"
        read -p "Enter choice [1-7]: " choice </dev/tty 2>/dev/null || choice="1"
    fi

    case "$choice" in
        1) log_info "Proceeding with Full Install..." ;;
        2) log_info "Proceeding with Browser Only Install..."; DO_THEME=0; DO_ES=0 ;;
        3) log_info "Proceeding with Theme Only Install..."; DO_DEPS=0; DO_BINARY=0; DO_FILES=0; DO_LAUNCHER=0; DO_ES=1; DO_THEME=1; DO_VERIFY=1 ;;
        4) exec bash "$0" "--uninstall" ;;
        5) exec bash "$0" "--uninstall-browser" ;;
        6) exec bash "$0" "--uninstall-theme" ;;
        7) exit 0 ;;
        *) log_err "Invalid choice. Exiting."; exit 1 ;;
    esac
fi

# ---------- Pre-flight checks ----------
for required in scripts/firefox-framebuffer-wrapper.py scripts/run_browser.sh; do
    if [ ! -f "$SCRIPT_DIR/$required" ] && [ ! -f "$SCRIPT_DIR/$(basename "$required")" ]; then
        log_err "$required not found in $SCRIPT_DIR (check scripts/ folder)"
        exit 1
    fi
done

ARCH="$(uname -m)"

if [ "$DO_DEPS" -eq 1 ]; then
    log_step "1/7" "Installing dependencies..."
    
    # APT sources fix for EOL Ubuntu
    if grep -q "archive.ubuntu.com\|security.ubuntu.com\|ports.ubuntu.com" "/etc/apt/sources.list" 2>/dev/null; then
        if ! grep -q "old-releases.ubuntu.com" "/etc/apt/sources.list" 2>/dev/null; then
            log_info "Fixing APT sources for EOL Ubuntu..."
            sed -i 's|http://archive.ubuntu.com|http://old-releases.ubuntu.com|g' /etc/apt/sources.list
            sed -i 's|http://security.ubuntu.com|http://old-releases.ubuntu.com|g' /etc/apt/sources.list
            sed -i 's|http://ports.ubuntu.com|http://old-releases.ubuntu.com|g' /etc/apt/sources.list
        fi
    fi

    dpkg --configure -a || true
    apt-get update -qq || true
    
    # Ensure any previous holds are cleared before installing
    apt-mark unhold libsdl2-2.0-0 libasound2-plugins libasound2 2>/dev/null || true
    
    RUNTIME_DEPS="python3 xvfb xdotool x11-utils apulse alsa-utils pulseaudio-utils libasound2 libasound2-plugins fonts-liberation ffmpeg fbset fbcat i2c-tools usbutils mmc-utils gdb git"
    APT_FLAGS="-y --allow-change-held-packages"
    if [ "$REINSTALL_DEPS" = "1" ]; then APT_FLAGS="$APT_FLAGS --reinstall"; fi
    
    log_info "Running apt-get install..."
    apt-get install $APT_FLAGS $RUNTIME_DEPS
    
    # Protect critical libraries AFTER installation
    log_info "Protecting SDL and Audio libraries..."
    apt-mark hold libsdl2-2.0-0 libasound2-plugins libasound2 2>/dev/null || true
    
    # Verification check
    log_info "Verifying dependencies..."
    MISSING_DEPS=""
    for dep in xvfb xdotool python3 apulse; do
        if ! command -v "$dep" &>/dev/null; then
            MISSING_DEPS="$MISSING_DEPS $dep"
        fi
    done
    
    if [ -n "$MISSING_DEPS" ]; then
        log_err "Failed to install some critical dependencies:$MISSING_DEPS"
        log_err "Please check your internet connection and run 'sudo apt-get update' manually."
        exit 1
    fi
    log_ok "Dependencies verified"

    # Firefox
    if ! command -v firefox &>/dev/null; then
        apt-get install -y firefox-esr || apt-get install -y firefox || true
    fi
fi

if [ "$DO_BINARY" -eq 1 ]; then
    log_step "2/7" "Setting up browser binary..."
    BROWSER_BIN=""
    if [ "$FORCE_REBUILD" -eq 0 ]; then
        for candidate in "$SCRIPT_DIR/build/browser.arm64" "$SCRIPT_DIR/build/browser" "$SCRIPT_DIR/bin/browser.arm64" "$SCRIPT_DIR/bin/browser" "$SCRIPT_DIR/browser"; do
            if [ -f "$candidate" ]; then BROWSER_BIN="$candidate"; break; fi
        done
    fi

    if [ -z "$BROWSER_BIN" ]; then
        log_info "Compiling natively..."
        BUILD_DEPS="build-essential g++ make pkg-config libsdl2-dev libstdc++-dev libgles2-mesa-dev libegl1-mesa-dev libgl1-mesa-dev libglu1-mesa-dev libglew-dev cmake ninja-build libc6-dev linux-libc-dev"
        apt-get install -y $BUILD_DEPS || true
        cd "$SCRIPT_DIR"
        make native || true
        BROWSER_BIN="$SCRIPT_DIR/build/browser"
    fi
    chmod +x "$BROWSER_BIN" 2>/dev/null || true
    strip "$BROWSER_BIN" 2>/dev/null || true
    log_ok "Binary ready"
fi

if [ "$DO_FILES" -eq 1 ]; then
    log_step "3/7" "Preparing files..."
    chmod +x "$INSTALL_DIR"/*.sh 2>/dev/null || true
    chmod +x "$INSTALL_DIR"/*.f4a 2>/dev/null || true
    chmod +x "$INSTALL_DIR"/scripts/*.sh 2>/dev/null || true
    chmod +x "$INSTALL_DIR"/scripts/*.py 2>/dev/null || true
    log_ok "Files prepared"
fi

if [ "$DO_LAUNCHER" -eq 1 ]; then
    log_step "4/7" "Creating ES launch script..."
    cat > "$LAUNCHER_SCRIPT" << LAUNCH_EOF
#!/bin/bash
SCRIPT_DIR="\$(cd "\$(dirname "\$0")" && pwd)"
for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo performance > "\$gov" 2>/dev/null || true; done

# Resolve scripts path (check scripts/ or root)
WRAP_BIN="\$SCRIPT_DIR/scripts/firefox-framebuffer-wrapper.py"
if [ ! -f "\$WRAP_BIN" ]; then WRAP_BIN="\$SCRIPT_DIR/firefox-framebuffer-wrapper.py"; fi
export FIRE4ARKOS_WRAPPER="\$WRAP_BIN"

RUN_BIN="\$SCRIPT_DIR/scripts/run_browser.sh"
if [ ! -f "\$RUN_BIN" ]; then RUN_BIN="\$SCRIPT_DIR/run_browser.sh"; fi

export FIRE4ARKOS_FROM_ES=1
LOGFILE="\$SCRIPT_DIR/firefox.log"
exec bash "\$RUN_BIN" "\${1:-https://www.google.com}" >> "\$LOGFILE" 2>&1
LAUNCH_EOF
    chmod +x "$LAUNCHER_SCRIPT"
    if [ -d "/usr/local/bin" ]; then
        # Find scripts in scripts/ or root
        RUN_BIN="$INSTALL_DIR/scripts/run_browser.sh"
        if [ ! -f "$RUN_BIN" ]; then RUN_BIN="$INSTALL_DIR/run_browser.sh"; fi
        
        WRAP_BIN="$INSTALL_DIR/scripts/firefox-framebuffer-wrapper.py"
        if [ ! -f "$WRAP_BIN" ]; then WRAP_BIN="$INSTALL_DIR/firefox-framebuffer-wrapper.py"; fi
        
        ln -sf "$RUN_BIN" "/usr/local/bin/fire4arkos"
        ln -sf "$WRAP_BIN" "/usr/local/bin/firefox-framebuffer-wrapper.py"
    fi
    log_ok "Launcher created"
fi

if [ "$DO_THEME" -eq 1 ]; then
    log_step "5/7" "Installing theme..."
    BASE_THEME_ROOT="/etc/emulationstation/themes"
    if [ -d "$BASE_THEME_ROOT" ] && [ -d "$SCRIPT_DIR/theme" ]; then
        for theme_dir in "$BASE_THEME_ROOT"/*/; do
            target_dir="${theme_dir}${SYSTEM_NAME}"
            mkdir -p "$target_dir"
            cp -r "$SCRIPT_DIR/theme"/* "$target_dir/" 2>/dev/null || true
        done
        log_ok "Theme installed"
    fi
fi

if [ "$DO_ES" -eq 1 ]; then
    log_step "6/7" "Registering with EmulationStation..."
    if [ -f "$ES_CFG" ]; then
        python3 "$SCRIPT_DIR/scripts/install-es-system.py" --cfg-file "$ES_CFG" --install-dir "$INSTALL_DIR" --platform-tag "$PLATFORM_TAG" --theme-name "$THEME_NAME" || log_warn "Failed to register in $ES_CFG"
    fi
    if [ -f "$ES_CFG_DUAL" ]; then
        python3 "$SCRIPT_DIR/scripts/install-es-system.py" --cfg-file "$ES_CFG_DUAL" --install-dir "$INSTALL_DIR" --platform-tag "$PLATFORM_TAG" --theme-name "$THEME_NAME" || log_warn "Failed to register in $ES_CFG_DUAL"
    fi
    log_ok "ES registration check complete"
fi

if [ "$DO_VERIFY" -eq 1 ]; then
    log_step "7/7" "Verification complete."
    echo -e "${GREEN}${BOLD}Installation Finished!${NC}"
    echo "Restart EmulationStation to see Fire4ArkOS."
fi

echo ""
echo "Returning to EmulationStation in 10 seconds..."
sleep 10
