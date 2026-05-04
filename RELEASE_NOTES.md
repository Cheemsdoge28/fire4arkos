# Release Notes - 2026-05-04

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
