# Release Notes - 2026-05-07 (v1.5.33)

This update resolves the long-standing menu focus issue and improves overall stability.

### Input & Focus
- **Smart Window Stabilization**: Re-introduced a menu-aware stabilization worker. It ensures the browser stays focused without "fighting" with open dropdowns or popups, making menus fully functional again.
- **Removed Focus Nudge**: Replaced the previous one-shot focus nudge with a persistent, intelligent focus-management system.

### Project
- **Documentation Update**: Removed the "Known Limitation" about popup menus from the README as it is now fully resolved.

---

# Release Notes - 2026-05-07 (v1.5.32)

This update improves UI clarity, controller bindings, and focus stability in Firefox.

### Input & Focus
- **A/L3 Unification**: Physical A now mirrors L3 left-click behavior for consistent dragging.
- **Right Click Binding**: Dedicated R3 right-click with updated on-screen hints.
- **Focus Nudge**: Optional one-shot focus stabilization after first frame render to prevent menus from closing.

### UI & UX
- **Minimal Overlay Refresh**: Cleaner keyboard, status bar, and loading overlay palettes.
- **Improved Text Legibility**: Subtle shadowing for small-scale readability.
- **Tighter Keyboard Layout**: More compact spacing for a modern, less bulky panel.

### Installer & Scripts
- **ES-Friendly Installers**: `install-browser.sh` and `install-theme.sh` now split browser vs. theme installs.
- **Targeted Uninstallers**: `uninstall-browser.sh` and `uninstall-theme.sh` for safe cleanup.

---

# Release Notes - 2026-05-06 (v1.5.31)

This "Installer Resilience" update focuses on protecting the system's graphics stack from accidental package manager downgrades.

### Installer & System Stability
- **SDL Protection**: The installer now uses `apt-mark hold` to lock the `libsdl2-2.0-0` library, preventing `apt` from downgrading it to older versions.
- **Symlink Auto-Repair**: Implemented an intelligent symlink repair system that scans for the newest SDL library on disk and restores broken links to ensure maximum performance.
- **Dependency Isolation**: Removed conflicting `libsdl2-dev` from the automated build dependency list to avoid repository conflicts on ArkOS.
- **One-Click Installer Refinement**: Improved the non-interactive `install-from-es.sh` workflow for smoother deployment from the Tools menu.

---

# Release Notes - 2026-05-04 (v1.5.30)

This update includes technical refinements to input handling, CPU resource management, and browser configuration for RK3326-based devices.

### Input Handling
- Implemented persistent xdotool pipe to reduce input command overhead.
- Added logic to purge pending move commands when a click is detected.
- Implemented quadratic stick acceleration for finer cursor control.
- Added 150ms coordinate freeze after click events to improve positional accuracy.
- Increased joystick deadzone to 10,000 to mitigate hardware drift.

### CPU & Memory
- Set CPU affinity for the browser process to Cores 0-2; Core 3 is reserved for system and input wrapper.
- Implemented frame-buffer comparison in the display engine to skip redundant GPU uploads on static content.
- Adjusted layout notification interval to 150ms.
- Limited image decoding to a single thread to reduce peak CPU contention.

### Audio & Media
- Adjusted autoplay blocking policy to allow immediate media playback.
- Re-enabled WebM and VP9 codec support in the browser profile.
- Disabled GMP sandbox to improve apulse/ALSA compatibility.

### UI & Presentation
- **"Colorful" Theme Overhaul**: Implemented a new premium system theme inspired by the "Colorful 2.0" aesthetic, featuring a solid pastel blue background and a photorealistic handheld render.
- **Universal Theme Installation**: The installer now automatically injects Fire4ArkOS skin assets into every theme folder in `/etc/emulationstation/themes/`.
- **True Transparent Branding**: Replaced the previous logo with a true transparent PNG and added a professional drop-shadow effect in the theme layout.
- **Enhanced README**: Updated the project documentation with a high-resolution logo and clearer installation instructions.

### Project
- Project license changed to GPL-3.0.
- Repository maintenance: Cleaned up untracked files and optimized asset storage.
