# 🚀 Fire4ArkOS Browser

A high-performance, framebuffer-optimized Firefox environment for ArkOS (R36S, RG351MP, RK3326).

![Downloads](https://img.shields.io/github/downloads/Cheemsdoge28/fire4arkos/total?style=for-the-badge&color=green)
![Release](https://img.shields.io/github/v/release/Cheemsdoge28/fire4arkos?style=for-the-badge&color=blue)
[![Sponsors](https://img.shields.io/github/sponsors/Cheemsdoge28?style=for-the-badge&color=ea4aaa&logo=github-sponsors)](https://github.com/sponsors/Cheemsdoge28)

## 📱 Supported Devices
Fire4ArkOS is optimized specifically for **RK3326** based handhelds running **ArkOS**:
- **R36S** (Highly Recommended)
- **RG351MP / RG351P / RG351M**
- **Powkiddy RGB10 / RGB10S**
- **RK2020**
- **Gameforce Chi**
- Any other RK3326 device on ArkOS/TheRA.

## 🛠️ Installation

**Fire4ArkOS v1.5.33** refines input bindings, adds smart focus stabilization, and introduces a cleaner UI style for RK3326-based devices.

### 1. Download & Prepare
- Download the latest `Fire4ArkOS.zip` from the [Releases](https://github.com/Cheemsdoge28/fire4arkos/releases) page.
- Extract the zip file on your computer. You will see a `Fire4ArkOS` folder.

### 2. Copy to Handheld
- Connect your ArkOS SD card (EASYROMS partition) to your computer.
- Copy the `Fire4ArkOS` folder into the `tools` directory on your SD card.
- Path: `EASYROMS/tools/Fire4ArkOS/`

### 3. One-Click Install
- Insert the SD card back into your device and boot ArkOS.
- Navigate to the **Tools** (or Options) section in EmulationStation.
- Find and run **Install-Fire4ArkOS.sh**.
- Follow the on-screen prompts to choose your installation type (Full, Browser Only, or Theme Only).
- Wait for the installer to finish, then **reboot your device**.

Once rebooted, a new system named **"Fire4ArkOS"** will appear in your frontend list!

### 🔄 How to Upgrade
Upgrading is easy and **will not delete your browser data** (bookmarks, history, etc.):
1. Delete the old `Fire4ArkOS` folder from your SD card.
2. Copy the new `Fire4ArkOS` folder to the same location.
3. Run **Install-Fire4ArkOS.sh** and follow the prompts.
4. Reboot your device.

> **Audio Status**: While the audio pipeline is now "Ironclad" (Direct ALSA via apulse), some hardware revisions remain silent. We are currently investigating this as a kernel-level issue.

## 🎮 Controls

| Button | Action |
|--------|--------|
| **Left Stick** | Mouse Cursor |
| **A / L3** | Left Click (drag with hold using L3) |
| **R3** | Right Click |
| **B** | Back (Previous Page) |
| **X** | Reload Page |
| **Y** | URL Entry / Virtual Keyboard |
| **L1** | Page Text Input |
| **R1** | Toggle UI |
| **L2 / R2** | Zoom Out / Zoom In |
| **D-Pad** | Scroll Up/Down/Left/Right |
| **Select + Start** | Exit Browser |

- **Stability**: The browser uses a custom performance profile to ensure smooth operation on the RK3326 SoC. If a page feels unresponsive, give it a moment to process heavy JavaScript.
- **Audio**: Audio is supported via a custom PulseAudio/apulse shim. Ensure your volume is turned up before launching.
- **Manual Installation (SSH)**:
   ```bash
   cd /roms/ports/Fire4ArkOS
   sudo bash Install-Fire4ArkOS.sh
   ```
- **Stick Drift**: If your cursor moves on its own, you can adjust the deadzone in `src/main.cpp` and run `sudo bash Install-Fire4ArkOS.sh --rebuild`.

## 🧾 Logs
- `install.log` is created in the Fire4ArkOS folder during installation.
- `firefox.log` is created alongside the app when the browser runs.

## 🤝 Support & Contribution
Feel free to open an issue or pull request if you find bugs or want to improve the performance!
