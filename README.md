# 🔥 Fire4ArkOS: Level 11 Performance Browser
![Platform](https://img.shields.io/badge/Platform-ArkOS%20%7C%20R36S%20%7C%20RG351MP-red)
![Backend](https://img.shields.io/badge/Engine-Firefox%20%7C%20SDL2-orange)
![Performance](https://img.shields.io/badge/Performance-Level%2011%20%2B%20Zero--Latency-brightgreen)

Fire4ArkOS is a heavily optimized, high-performance web browser shell designed specifically for RK3326-based handhelds (R36S, RG351MP). By combining a lightweight SDL2 frontend with a headless Firefox backend via zero-copy IPC, Fire4ArkOS delivers a desktop-class browsing experience on hardware with extremely limited resources.

## 🚀 Key "Level 11" Optimizations

### 1. Near-Zero Latency Input
- **Persistent Xdotool Pipe**: Eliminates the 15-20ms overhead of spawning a new process for every movement. Input commands are fed directly into a background instance via a persistent stdin pipe.
- **Quadratic Stick Physics**: Implements `stick^2` acceleration for pixel-perfect precision when nudging the stick, while maintaining high speed for full-screen navigation.
- **Click-Precedence Purging**: The IPC reader automatically nukes stale movement commands when a click is detected, eliminating "springing" or "rubber-banding."

### 2. High-Speed Framebuffer Streaming
- **Zero-Copy SHM**: Uses POSIX Shared Memory (`/dev/shm`) to transfer raw frames from Firefox to the SDL2 renderer. No disk I/O, no temporary files.
- **Identical Frame Skipping**: The C++ display engine performs a memory comparison of every incoming frame; if the page hasn't changed, the GPU upload and render pass are completely bypassed, saving ~30% CPU on static pages.

### 3. CPU Isolation & Memory Management
- **Core Reservation**: Firefox is pinned to Cores 0-2, reserving **Core 3** exclusively for input handling and system interrupts. This prevents browser "pinning" from causing input lag.
- **Ultra-Balanced Profile**: A custom `user.js` optimized for RK3326 that balances extreme performance (150ms layout batching) with modern site compatibility (WebM/VP9 restored for Reddit/YouTube).

## 🎮 Controls

| Button | Action |
|--------|--------|
| **Left Stick** | Quadratic Mouse Movement |
| **A / R1** | Left Click |
| **B / L1** | Back |
| **X** | Enter URL / Type Mode |
| **Y** | Refresh Page |
| **L2 / R2** | Zoom Out / In |
| **D-Pad** | Smooth Scrolling |
| **Select + Start** | Instant Exit |

## 🛠️ Installation & Setup

### Automated Install
The easiest way to install Fire4ArkOS on your device:
```bash
git clone https://github.com/Cheemsdoge28/fire4arkos.git
cd fire4arkos
sudo bash install.sh
```

### On-Device Rebuild
To apply the latest C++ physics and performance updates:
```bash
sudo bash install.sh --rebuild
```

### Run Parameters
Fire4ArkOS supports several environment variables for tuning:
- `FIRE4ARKOS_INTERNAL_SCALE=1`: Native 640x480 resolution (Sharpest).
- `FIRE4ARKOS_MAX_PERF=1`: Enables all Level 11 optimizations.
- `FPS=60`: Target UI refresh rate.

## 🏗️ Architecture

```
[ SDL2 Frontend (Core 3) ] <--- [ SHM /dev/shm/fire4arkos_fb ] <--- [ Firefox Backend (Cores 0-2) ]
          |                                                                   ^
          |---(Persistent Pipe)---> [ xdotool ] ------------------------------|
```

## 📜 Credits & License
- **Lead Developer**: Cheemsdoge28
- **Engine**: Mozilla Firefox (Headless Mode)
- **Frontend**: SDL2
- **License**: MIT
