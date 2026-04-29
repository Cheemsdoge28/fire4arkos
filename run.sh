#!/bin/bash
# Fire4ArkOS Browser - Performance optimized launcher with preset modes

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    cat << EOF
${GREEN}Fire4ArkOS Browser - Optimized Launcher${NC}

${YELLOW}Usage:${NC}
  ./run.sh [MODE] [URL]

${YELLOW}Modes:${NC}
  fast     - 400x300 @ 10 FPS (battery/mobile sites)
  balanced - 640x480 @ 12 FPS (default)
  quality  - 640x480 @ 15 FPS (more responsive)

${YELLOW}Examples:${NC}
  ./run.sh fast https://example.com
  ./run.sh balanced
  ./run.sh quality https://duckduckgo.com

${YELLOW}Default:${NC}
  ./run.sh           # Uses 'balanced' mode with Google
EOF
}

# Default values
MODE="${1:-balanced}"
URL="${2:-https://www.google.com}"

# Parse mode
case "$MODE" in
    fast)
        WIDTH=400
        HEIGHT=300
        FPS=10
        echo -e "${YELLOW}🚀 Fast Mode${NC} (400×300 @ 10 FPS) - Minimal bandwidth"
        ;;
    balanced)
        WIDTH=640
        HEIGHT=480
        FPS=12
        echo -e "${YELLOW}⚖️  Balanced Mode${NC} (640×480 @ 12 FPS) - Default"
        ;;
    quality)
        WIDTH=640
        HEIGHT=480
        FPS=15
        echo -e "${YELLOW}✨ Quality Mode${NC} (640×480 @ 15 FPS) - Responsive UI"
        ;;
    -h|--help)
        usage
        exit 0
        ;;
    *)
        echo -e "${RED}❌ Unknown mode: $MODE${NC}"
        usage
        exit 1
        ;;
esac

# If second arg looks like a URL, use it as URL
if [[ "$2" =~ ^https?:// ]]; then
    URL="$2"
fi

echo -e "${GREEN}📍 URL: $URL${NC}"
echo ""

# Set performance mode
if [ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
    echo -e "${YELLOW}📊 Setting CPU to performance mode...${NC}"
    echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null
fi

# Set SDL environment
export SDL_VIDEODRIVER=kmsdrm
export SDL_RENDER_DRIVER=opengles2
export SDL_HINT_FRAMEBUFFER_ACCELERATION=1
export WIDTH
export HEIGHT
export FPS
export PIXFMT=bgra

# Disable cursor
setterm -cursor off 2>/dev/null || true

# Stop EmulationStation if running
if systemctl list-units --full -all | grep -Fq "emulationstation.service"; then
    echo -e "${YELLOW}⏹️  Stopping EmulationStation...${NC}"
    sudo systemctl stop emulationstation 2>/dev/null || true
else
    if pgrep -x "emulationstation" > /dev/null; then
        killall -15 emulationstation 2>/dev/null || true
        sleep 1
        killall -9 emulationstation 2>/dev/null || true
    fi
fi

sleep 1
clear

echo -e "${GREEN}🔥 Fire4ArkOS Browser - Starting${NC}"
echo "Resolution: ${WIDTH}×${HEIGHT} @ ${FPS} FPS"
echo ""

# Determine which binary to run
BINARY=""
# Prefer the repo-local browser first so run.sh matches the shortcut behavior
if [ -x "./browser" ]; then
    BINARY="./browser"
elif [ -x "./build/browser" ]; then
    BINARY="./build/browser"
elif command -v browser > /dev/null; then
    BINARY=$(command -v browser)
elif command -v fire4arkos > /dev/null; then
    BINARY=$(command -v fire4arkos)
elif [ -x "/usr/local/bin/browser" ]; then
    BINARY="/usr/local/bin/browser"
else
    echo -e "${RED}❌ ERROR: Fire4ArkOS executable not found.${NC}"
    echo "Please run: sudo ./install-native.sh"
    exit 1
fi

echo -e "${GREEN}✓ Using binary: $BINARY${NC}"
echo ""

# Run browser (log runtime info and capture output for debugging)
LOG="/tmp/fire4arkos-run.log"
echo "=== Fire4ArkOS run.sh start: $(date) ===" > "$LOG"
echo "MODE=$MODE" >> "$LOG"
echo "WIDTH=$WIDTH HEIGHT=$HEIGHT FPS=$FPS PIXFMT=$PIXFMT" >> "$LOG"
echo "BINARY=$BINARY" >> "$LOG"
echo "URL=$URL" >> "$LOG"
echo "---- environment (filtered) ----" >> "$LOG"
env | grep -E "SDL|WIDTH|HEIGHT|FPS|PIXFMT|DISPLAY" >> "$LOG" || true
echo "--------------------------------" >> "$LOG"

"$BINARY" "$URL" 2>&1 | tee -a "$LOG"

# Cleanup
clear
echo -e "${YELLOW}🔄 Restarting EmulationStation...${NC}"

# Revert CPU governor
if [ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
    echo ondemand | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null
fi

# Restart EmulationStation
if systemctl list-units --full -all | grep -Fq "emulationstation.service"; then
    sudo systemctl start emulationstation 2>/dev/null || true
else
    nohup emulationstation > /dev/null 2>&1 &
fi

# Re-enable cursor
setterm -cursor on 2>/dev/null || true

echo -e "${GREEN}✓ Done${NC}"
