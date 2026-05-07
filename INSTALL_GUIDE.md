# Fire4ArkOS Installation Guide

This guide covers the recommended way to install Fire4ArkOS on your ArkOS handheld (R36S, RG351MP, etc.).

## 📋 Prerequisites
- A handheld running **ArkOS**.
- A computer with an SD card reader.
- The latest **Fire4ArkOS Release** (`.zip` file).

---

## 🛠️ Installation Steps

### 1. Download and Extract
Download the latest release zip from the GitHub releases page. Extract it on your computer; you should see a folder named `Fire4ArkOS`.

### 2. Copy to the 'tools' Directory
Connect your handheld's **EASYROMS** SD card to your computer.
- Navigate to the `tools` folder.
- Copy the entire `Fire4ArkOS` folder into `tools`.
- **Final Path Check**: You should have a file at `EASYROMS/tools/Fire4ArkOS/install-from-es.sh`.

### 3. Run the Installer from EmulationStation
1. Insert the SD card back into your device and boot into ArkOS.
2. Navigate to the **Options** (or **Tools**) system in the main menu.
3. Select **install-from-es** and press **A**.
4. The screen will turn black for a few moments as it installs dependencies and registers the browser.
5. Once it finishes, it will return to the menu.

Optional named scripts:
- `install-browser` installs dependencies and the browser only.
- `install-es-integration` registers EmulationStation and installs the theme.
- `launch-browser` starts the browser from shell.

### 4. Restart EmulationStation
- Press **Start** → **Quit** → **Restart EmulationStation**.
- A new system called **"Fire4ArkOS Browser"** will now appear in your main carousel.

---

## 🖥️ Advanced: Manual Installation (SSH)
If you prefer using the terminal, you can install Fire4ArkOS via SSH:

1. Connect to your device via SSH.
2. Navigate to the folder:
   ```bash
   cd /roms/tools/Fire4ArkOS
   ```
3. Run the installer script with root privileges:
   ```bash
   sudo bash install.sh
   ```
4. Restart EmulationStation to see the changes.

---

## 🧹 Uninstallation
To completely remove Fire4ArkOS:
1. Run the installer again and select the Uninstall option (if available), or run via SSH:
   ```bash
   cd /roms/tools/Fire4ArkOS
   sudo bash install.sh --uninstall
   ```
2. You can then safely delete the `Fire4ArkOS` folder from your `tools` directory.

You can also run:
```bash
cd /roms/tools/Fire4ArkOS
sudo bash uninstall.sh
```

---

## ❓ Troubleshooting

### Browser doesn't launch
- Ensure you are running at `FIRE4ARKOS_INTERNAL_SCALE=1` if you have display issues.
- Check the log files at `/roms/tools/Fire4ArkOS/install.log` and `/roms/tools/Fire4ArkOS/firefox.log` for errors.

### No Audio
- Audio is handled by `apulse`. If you hear nothing, ensure your system volume is not muted in the ArkOS main settings.
- If issues persist, try a rebuild: `sudo bash install.sh --rebuild`.

### Stick Drift
- R36S analog sticks can vary in quality. If the cursor drifts, we have set a generous deadzone of 10000. If you still experience drift, you may need to increase the `DEADZONE` value in `src/main.cpp` and run a rebuild.
