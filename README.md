# <img src="res/logo.png" height="200" valign="middle"> Fire4ArkOS Browser
![Platform](https://img.shields.io/badge/Platform-ArkOS%20%7C%20R36S%20%7C%20RG351MP-blue)
![Backend](https://img.shields.io/badge/Engine-Firefox%20%7C%20SDL2-orange)
![License](https://img.shields.io/badge/License-GPL--3.0-green)

Fire4ArkOS is a lightweight SDL2 frontend for the Firefox web browser, specifically optimized for handheld devices running ArkOS (RK3326). It provides a full desktop-class browsing experience while maintaining the responsiveness required for handheld gaming devices.

## 🛠️ Installation

### 1. Download & Prepare
- Download the latest `Fire4ArkOS-XXXXXXXX.zip` from the [Releases](https://github.com/Cheemsdoge28/fire4arkos/releases) page.
- Extract the zip file on your computer.
- You will see a folder named `Fire4ArkOS`.

### 2. Copy to Handheld
- Connect your ArkOS SD card (EASYROMS partition) to your computer.
- Copy the `Fire4ArkOS` folder into the `tools` directory on your SD card.
- The path should look like: `EASYROMS/tools/Fire4ArkOS/`

### 3. Run Installer
- Insert the SD card back into your handheld and boot ArkOS.
- Navigate to the **Options** or **Tools** section in EmulationStation.
- Find and run **Fire4ArkOS Installer**.
- *Alternatively*, if you have SSH access, run:
  ```bash
  cd /roms/tools/Fire4ArkOS
  sudo bash install.sh
  ```

Once installed, "Fire4ArkOS" will appear as a new system in your EmulationStation menu.

## 🎮 Controls

| Button | Action |
|--------|--------|
| **Left Stick** | Mouse Cursor |
| **A / R1** | Left Click |
| **B / L1** | Back (Previous Page) |
| **X** | URL Entry / Virtual Keyboard |
| **Y** | Refresh Page |
| **L2 / R2** | Zoom Out / Zoom In |
| **D-Pad** | Scroll Up/Down/Left/Right |
| **Select + Start** | Exit Browser |

## 💡 Usage Tips
- **Stability**: The browser uses a custom performance profile to ensure smooth operation on the RK3326 SoC. If a page feels unresponsive, give it a moment to process heavy JavaScript.
- **Audio**: Audio is supported via a custom PulseAudio/apulse shim. Ensure your volume is turned up before launching.
- **Stick Drift**: If your cursor moves on its own, you can adjust the deadzone in `src/main.cpp` and run `sudo bash install.sh --rebuild`.

## 🏗️ Architecture
Fire4ArkOS works by running a headless instance of Firefox in the background. It captures the browser's output via Shared Memory (SHM) and renders it to the screen using SDL2. Input from your handheld's buttons is translated into mouse and keyboard events and sent to Firefox via a high-performance IPC pipe.

## 📜 License
GPL-3.0 License. See [LICENSE](LICENSE) for details.
