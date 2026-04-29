#!/bin/bash
# Fire4ArkOS - URL Loading Diagnostic Script

echo "🔍 Fire4ArkOS Diagnostic Report"
echo "================================"
echo ""

# Check network
echo "📡 Network Status:"
ip link show 2>/dev/null | grep -E "wlan|eth" || echo "  No network interfaces found"
ip addr show 2>/dev/null | grep -E "inet " || echo "  No IP addresses assigned"
ping -c 1 8.8.8.8 >/dev/null 2>&1 && echo "  ✓ Internet connectivity OK" || echo "  ✗ No internet connectivity"
echo ""

# Check dependencies
echo "📦 Dependencies:"
for cmd in xdotool xvfb ffmpeg firefox python3 pkg-config; do
    if command -v "$cmd" &> /dev/null; then
        echo "  ✓ $cmd: $(command -v $cmd)"
    else
        echo "  ✗ $cmd: NOT FOUND"
    fi
done
echo ""

# Check SDL2
echo "📺 SDL2:"
pkg-config --modversion sdl2 2>/dev/null && echo "  ✓ SDL2 found" || echo "  ✗ SDL2 not found"
pkg-config --modversion SDL2_ttf 2>/dev/null && echo "  ✓ SDL2_ttf found" || echo "  ✗ SDL2_ttf not found"
echo ""

# Check build
echo "🔨 Build Status:"
if [ -f "build/browser" ]; then
    echo "  ✓ Binary exists: build/browser"
    ls -lh build/browser
else
    echo "  ✗ Binary not found. Run: make native"
fi
echo ""

# Check wrapper
echo "🐍 Python Wrapper:"
if [ -f "firefox-framebuffer-wrapper.py" ]; then
    echo "  ✓ Wrapper exists"
    python3 -m py_compile firefox-framebuffer-wrapper.py 2>/dev/null && echo "  ✓ Python syntax OK" || echo "  ✗ Python syntax error"
else
    echo "  ✗ Wrapper not found"
fi
echo ""

# Test xdotool specifically
echo "🎹 xdotool Test:"
if command -v xdotool &> /dev/null; then
    echo "  Testing keyboard simulation..."
    xdotool key ctrl+l 2>/dev/null && echo "  ✓ xdotool key works" || echo "  ✗ xdotool key failed"
else
    echo "  ✗ xdotool not installed"
    echo "  Install: sudo apt-get install xdotool"
fi
echo ""

# Network diagnostic
echo "🌐 Network Diagnostic:"
echo "  Testing DNS resolution:"
nslookup google.com 2>/dev/null | grep -q "Name:" && echo "    ✓ DNS works" || echo "    ✗ DNS not working"
echo "  Testing HTTP connectivity:"
curl -s -m 2 http://example.com >/dev/null && echo "    ✓ HTTP works" || echo "    ✗ HTTP failed"
echo ""

echo "================================"
echo "💡 Next Steps:"
echo ""
echo "If network is failing:"
echo "  1. Check WiFi: nmtui or iwconfig"
echo "  2. Verify DHCP: dhclient wlan0"
echo "  3. Check gateway: ip route"
echo ""
echo "If xdotool is missing:"
echo "  sudo apt-get install xdotool"
echo ""
echo "If all looks good, test the browser:"
echo "  ./run.sh balanced https://example.com"
echo ""
