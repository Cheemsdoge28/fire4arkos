#!/bin/bash
# Firefox Headless Framebuffer Wrapper
# Launches Firefox in headless mode and pipes framebuffer stream to named pipe
# Usage: firefox-framebuffer-wrapper.sh <initial_url> [pipe_path]

set -e

INITIAL_URL="${1:-https://example.com}"
PIPE_BASE="${2:-fire4arkos}"
FB_PIPE="/tmp/${PIPE_BASE}_fb"
CMD_PIPE="/tmp/${PIPE_BASE}_in"

# Create named pipes if they don't exist
mkfifo "$CMD_PIPE" 2>/dev/null || true
mkfifo "$FB_PIPE" 2>/dev/null || true

# Firefox configuration
PROFILE_DIR="/tmp/firefox_profile_$$"
mkdir -p "$PROFILE_DIR"

# Prefs to enable remote debugging and headless rendering
cat > "$PROFILE_DIR/prefs.js" << 'EOF'
user_pref("devtools.debugger.remote-enabled", true);
user_pref("devtools.chrome.enabled", true);
user_pref("browser.startup.homepage", "about:blank");
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("dom.disable_unload_asr", true);
EOF

# Function to capture and stream framebuffer
stream_framebuffer() {
    local width=$1
    local height=$2
    
    # Magic: 0xFB000001 (little-endian)
    printf '\x01\x00\x00\xfb' > "$FB_PIPE"
    
    # Width (little-endian 32-bit)
    printf "$(printf '\\x%02x' $((width & 0xFF)) $(((width >> 8) & 0xFF)) $(((width >> 16) & 0xFF)) $(((width >> 24) & 0xFF)))" >> "$FB_PIPE"
    
    # Height (little-endian 32-bit)  
    printf "$(printf '\\x%02x' $((height & 0xFF)) $(((height >> 8) & 0xFF)) $(((height >> 16) & 0xFF)) $(((height >> 24) & 0xFF)))" >> "$FB_PIPE"
    
    # Generate placeholder framebuffer (black ARGB8888 pixels)
    # In real implementation, this would capture from Firefox's offscreen rendering
    python3 << PYEOF
import struct
import sys

width, height = $width, $height
fb_size = width * height * 4

# Write black pixels (ARGB)
for y in range(height):
    for x in range(width):
        sys.stdout.buffer.write(struct.pack('<I', 0xFF1A1A1A))  # Dark gray ARGB
PYEOF
}

# Start Firefox headless
echo "[$(date)] Starting Firefox headless on $INITIAL_URL"
firefox --headless --new-instance "$INITIAL_URL" \
    -profile "$PROFILE_DIR" \
    --no-sandbox \
    2>/dev/null &

FIREFOX_PID=$!

# Cleanup on exit
cleanup() {
    echo "[$(date)] Cleaning up Firefox (PID $FIREFOX_PID)"
    kill $FIREFOX_PID 2>/dev/null || true
    wait $FIREFOX_PID 2>/dev/null || true
    rm -rf "$PROFILE_DIR"
    rm "$CMD_PIPE" "$FB_PIPE" 2>/dev/null || true
}

trap cleanup EXIT

# Monitor command pipe and stream framebuffer
echo "[$(date)] Framebuffer wrapper started, streaming to $FB_PIPE"

# For now, stream placeholder framebuffer
# In real deployment, integrate with Firefox rendering backend
while kill -0 $FIREFOX_PID 2>/dev/null; do
    # Read commands from the command pipe (non-blocking)
    if [ -p "$CMD_PIPE" ]; then
        # Try to read a command with timeout
        if read -t 0 cmd < "$CMD_PIPE"; then
            echo "[$(date)] Command: $cmd"
            case $cmd in
                load:*)
                    url="${cmd#load:}"
                    echo "[$(date)] Loading: $url"
                    ;;
                scroll:*)
                    delta="${cmd#scroll:}"
                    echo "[$(date)] Scrolling: $delta"
                    ;;
                click)
                    echo "[$(date)] Click"
                    ;;
                back)
                    echo "[$(date)] Back"
                    ;;
                resize:*)
                    dims="${cmd#resize:}"
                    echo "[$(date)] Resizing: $dims"
                    ;;
                screenshot:*)
                    path="${cmd#screenshot:}"
                    echo "[$(date)] Screenshot: $path"
                    ;;
                *)
                    echo "[$(date)] Unknown command: $cmd"
                    ;;
            esac
        fi
    fi
    
    # Stream placeholder framebuffer every 33ms (30 FPS)
    stream_framebuffer 640 480
    sleep 0.033
done

echo "[$(date)] Firefox process ended"
