# Fire4ArkOS Release Notes - May 4, 2026
## "Level 11 Performance & Stability Update"

This major update transforms Fire4ArkOS into a production-ready browser for RK3326 handhelds (R36S, RG351MP), focusing on sub-millisecond input response, multi-core CPU efficiency, and reliable media playback.

### 🚀 Input Performance ("Level 11")
- **Persistent Xdotool Pipe**: Replaced the legacy subprocess model with a persistent stdin pipe. This eliminates the 20ms "spawning lag" per movement, delivering near-instant cursor response.
- **Atomic Click Precedence**: The input reader now purges pending movement commands whenever a click is detected. This eliminates the "coiled spring" effect where the cursor would fly away after a click.
- **Quadratic Physics**: Implemented exponential stick acceleration for surgical precision when nudging and high velocity for full-screen sweeps.
- **Freeze-on-Click**: The cursor now physically freezes for 150ms post-click to ensure high-latency websites don't "fling" the cursor coordinate during the load event.

### 🧠 CPU & System Optimization
- **Core Isolation (Affinity)**: Firefox is now restricted to CPU Cores 0, 1, and 2. **Core 3** is reserved exclusively for the SDL2 frontend and input wrapper, ensuring the interface remains responsive even during 100% browser load.
- **Identical Frame Skipping**: The C++ display engine now compares incoming frame buffers; if the content is identical, the GPU upload pass is bypassed, reducing CPU overhead by ~30% on static pages.
- **Ultra-Balanced Profile**: A refined `user.js` profile that enables 150ms layout batching (down from 1s), restoring responsiveness on modern JS-heavy sites like Reddit.

### 🔊 Audio & Media
- **Autoplay Restored**: Fixed a configuration conflict that was blocking all automatic audio/video playback.
- **WebM/VP9 Compatibility**: Re-enabled modern software codecs to ensure YouTube and Reddit clips play without specialized H.264 extensions.
- **Sandbox Resolution**: Forced `MOZ_DISABLE_GMP_SANDBOX` to allow audio codecs to communicate with the `apulse` ALSA shim reliably.

### ⚖️ Project & Legal
- **License Transition**: The project is now officially licensed under **GPL-3.0**, ensuring it remains free and open-source for the entire handheld community.
- **Documentation Overhaul**: Cleaned up technical clutter in favor of a professional, user-centric README and Installation Guide.

---
**Installation**: Download the latest release, extract to `EASYROMS/tools`, and run the installer from the EmulationStation tools menu.
**On-Device Update**: `git pull && sudo bash install.sh --rebuild`
