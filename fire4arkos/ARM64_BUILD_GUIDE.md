# Fire4ArkOS Browser - ARM64 Cross-Compilation Guide

## Quick Start

### For Windows (MinGW)
```bash
make windows
```

### For ARM64 (ArkOS/R36S)
Requires `aarch64-linux-gnu-g++` toolchain:
```bash
make arm64
# Output: build/browser.arm64
```

### For Linux (Native)
```bash
make native
# Or just: make
```

---

## Prerequisites

### 1. ARM64 Cross-Compiler (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install \
    gcc-aarch64-linux-gnu \
    g++-aarch64-linux-gnu \
    pkg-config \
    libsdl2-dev:arm64
```

### 2. ARM64 SDL2 Development Libraries
```bash
# Option A: Install from repo
sudo dpkg --add-architecture arm64
sudo apt update
sudo apt install libsdl2-dev:arm64

# Option B: Cross-compile SDL2 from source
# See: https://github.com/libsdl-org/SDL/blob/main/docs/INSTALL.md
```

### 3. Verify Toolchain
```bash
aarch64-linux-gnu-gcc --version
aarch64-linux-gnu-g++ --version
aarch64-linux-gnu-strip --help
```

---

## Building

### Build for ARM64
```bash
cd Fire4ArkOS
make arm64
```

This generates:
- `build/browser.arm64` — Executable
- Size: ~204KB (stripped)

### Build with Optimizations
```bash
make arm64 CXXFLAGS="-std=c++17 -O3 -march=armv8-a -mtune=cortex-a53"
```

### Build and Strip
```bash
make arm64 && make strip
```

---

## File Structure for Deployment

```
/opt/fire4arkos/                    # Installation directory
├── browser.arm64                    # Main executable
├── firefox-framebuffer-wrapper.py   # Firefox integration script
└── README.md                        # Documentation
```

---

## Preparing ArkOS Device

### Option 1: Using SCP (SSH)
On your development machine:
```bash
# Copy files to device
scp build/browser.arm64 root@192.168.1.100:/opt/fire4arkos/
scp firefox-framebuffer-wrapper.py root@192.168.1.100:/opt/fire4arkos/
scp arkos-deploy.sh root@192.168.1.100:/tmp/

# SSH into device and run deployment
ssh root@192.168.1.100
bash /tmp/arkos-deploy.sh /opt/fire4arkos
```

### Option 2: USB Drive
1. Create a USB partition with the files
2. Mount on ArkOS device
3. Run deployment script

### Option 3: Direct Cross-Compile on Device
```bash
# On ARM64 Linux device
git clone <repo>
cd Fire4ArkOS
sudo make arm64 install
```

---

## Testing on Device

### Check Dependencies
```bash
# On ArkOS device
ldd /opt/fire4arkos/browser.arm64
```

### Run Browser
```bash
# Launch with default URL
./browser.arm64

# Launch with specific URL
./browser.arm64 https://example.com
```

### Troubleshooting

#### "missing SDL2"
```bash
opkg update
opkg install libsdl2
# Or: sudo apt install libsdl2-2.0
```

#### "Python not found"
```bash
opkg install python3
```

#### "Firefox not found"
```bash
# Install headless Firefox for ArkOS
opkg install firefox
# Or build from source: https://firefox-source-docs.mozilla.org/
```

#### "Permission denied"
```bash
chmod +x /opt/fire4arkos/browser.arm64
chmod +x /opt/fire4arkos/firefox-framebuffer-wrapper.py
```

---

## Performance Tuning for ArkOS (RK3326)

### Memory Optimization
```bash
# Limit memory usage (in launcher script)
ulimit -v 1048576  # 1GB virtual
ulimit -m 524288   # 512MB physical
```

### CPU Optimization
```bash
# Set CPU governor to performance
echo performance | sudo tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor

# Or use: powersave, conservative, ondemand, schedutil
```

### SDL2 Optimization
```bash
export SDL_VIDEODRIVER=opengles2
export SDL_RENDER_DRIVER=opengles2
export SDL_HINT_FRAMEBUFFER_ACCELERATION=1
```

### Firefox Optimization
```bash
export MOZ_ENABLE_WAYLAND=0
export GTK_THEME=Adwaita
```

---

## Building Firefox from Source (Optional)

For custom optimization on RK3326:

```bash
# Clone Mozilla source
git clone https://github.com/mozilla/mozilla-unified.git
cd mozilla-unified

# Create ARM64 cross-compile config
cat > .mozconfig << 'EOF'
ac_add_options --target=aarch64-linux-gnu
ac_add_options --host=aarch64-linux-gnu
ac_add_options --enable-optimize="-O3 -march=armv8-a -mtune=cortex-a53"
ac_add_options --enable-application=browser
ac_add_options --enable-official-branding
ac_add_options --disable-tests
ac_add_options --disable-debug
ac_add_options --prefix=/opt/firefox
EOF

# Build (takes several hours)
./mach build
./mach package
```

---

## Makefile Targets

```bash
make              # Build for current platform
make windows      # Windows x86-64 (MinGW)
make arm64        # ARM64 (aarch64-linux-gnu)
make native       # Linux native build
make clean        # Remove build artifacts
make strip        # Strip debug symbols
make install      # Install to system
make config       # Show build configuration
```

---

## Architecture Compatibility

| Target | Toolchain | Arch | Notes |
|--------|-----------|------|-------|
| Windows | MinGW64 | x86-64 | Development |
| Linux | GCC | x86-64 | Testing |
| ArkOS | aarch64-linux-gnu | ARM64 (v8) | Deployment |
| R36S | aarch64-linux-gnu | ARM64 (Cortex-A53) | Primary target |

---

## Size Optimization

### Unoptimized
```bash
make arm64
# Size: ~204KB
```

### Optimized
```bash
make arm64 CXXFLAGS="-std=c++17 -O3 -flto"
make strip
# Size: ~140KB
```

### Using UPX (Ultra Packing)
```bash
sudo apt install upx
upx --best build/browser.arm64 -o build/browser.arm64.upx
# Size: ~80KB (at cost of startup time)
```

---

## References

- [GNU Cross-Compiler](https://gcc.gnu.org/onlinedocs/)
- [SDL2 Documentation](https://wiki.libsdl.org/SDL2/Introduction)
- [ArkOS Documentation](https://github.com/jbouze/ArkOS)
- [Firefox Headless](https://firefox-source-docs.mozilla.org/remote/)
- [ARM64 Optimization](https://developer.arm.com/tools-and-software/tools/compiler/arm-compiler-for-linux)

---

## Building Docker Image (Alternative)

For consistent cross-compilation environment:

```dockerfile
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y \
    gcc-aarch64-linux-gnu \
    g++-aarch64-linux-gnu \
    libsdl2-dev:arm64 \
    pkg-config \
    make
WORKDIR /build
COPY . .
RUN make arm64
```

Build with:
```bash
docker build -t fire4arkos-builder .
docker run --rm -v $(pwd)/build:/build/build fire4arkos-builder
```

---
