# Fire4ArkOS Installation Guide

## Overview

Fire4ArkOS is now **self-contained**: all files stay in one directory (`/roms/ports/Fire4ArkOS` or `/roms/tools/Fire4ArkOS`), and the installer registers it properly with EmulationStation.

## Installation Steps

### Option A: SSH Installation (Recommended)

1. **Copy the release to your device:**
   ```bash
   # On your PC:
   rsync -avP dist/release/Fire4ArkOS/ user@device:/roms/ports/Fire4ArkOS
   
   # OR use scp:
   scp -r dist/release/Fire4ArkOS user@device:/roms/ports/
   ```

2. **SSH into your device and run the installer:**
   ```bash
   ssh user@device
   cd /roms/ports/Fire4ArkOS
   sudo bash install.sh
   ```

3. **Restart EmulationStation:**
   - In EmulationStation: `Start → Quit → Restart EmulationStation`
   - Or on device: `sudo systemctl restart emulationstation`

4. **Launch the app:**
   - EmulationStation main menu should now show **"Fire4ArkOS Browser"**
   - Select it and press A to launch

### Option B: EmulationStation Installer Entry (Advanced)

If you want to run the installer directly from EmulationStation:

1. **Copy the release:**
   ```bash
   rsync -avP dist/release/Fire4ArkOS/ user@device:/roms/ports/Fire4ArkOS
   ```

2. **Temporarily create an ES Installer entry:**
   - SSH into device: `ssh user@device`
   - Edit `/etc/emulationstation/es_systems.cfg`
   - Add this entry before `</systemList>`:
     ```xml
     <!-- Fire4ArkOS Installer (temporary) -->
     <system>
       <name>fire4arkos_install</name>
       <fullname>Fire4ArkOS Installer</fullname>
       <path>/roms/ports/Fire4ArkOS</path>
       <extension>.sh</extension>
       <command>sudo bash %ROM%/install-from-es.sh</command>
       <platform>pc</platform>
       <theme>ports</theme>
     </system>
     ```

3. **Restart EmulationStation** and select **"Fire4ArkOS Installer"**
   - This will attempt to escalate privileges and run `install.sh`

4. **After installation completes:**
   - Remove the installer entry from `es_systems.cfg`
   - **"Fire4ArkOS Browser"** entry will now be present (added by `install.sh`)
   - Restart EmulationStation again
   - Select **"Fire4ArkOS Browser"** to launch

## What the Installer Does

When you run `sudo bash install.sh` from the Fire4ArkOS directory:

1. **Installs runtime dependencies:**
   - Python 3, Xvfb, xdotool, Firefox, apulse (Pulse Audio shim)
   - Fixes APT sources if running on EOL Ubuntu

2. **Prepares the browser binary:**
   - Uses pre-built `bin/browser.arm64` if available
   - Falls back to native compilation if needed (with `--rebuild`)

3. **Creates a launcher script:**
   - `Fire4ArkOS Browser.sh` in the same directory
   - Sets performance governor, env variables, launches the browser

4. **Registers with EmulationStation:**
   - Adds **"Fire4ArkOS Browser"** system entry to `es_systems.cfg`
   - Points to the launcher script in your installation directory

5. **Verifies the installation:**
   - Checks for required files and dependencies

## Uninstallation

To remove Fire4ArkOS:

```bash
cd /roms/ports/Fire4ArkOS
sudo bash install.sh --uninstall
```

This removes:
- The EmulationStation system entry
- The launcher script
- Your application files in `/roms/ports/Fire4ArkOS` are **preserved** (you can delete manually if desired)

## Troubleshooting

### "Firefox not found" error

If Firefox isn't installed or detected:
```bash
sudo apt-get install firefox-esr
```

Then re-run the installer:
```bash
sudo bash install.sh --rebuild
```

### Audio not working

Ensure apulse is installed:
```bash
sudo apt-get install apulse
```

If you have PulseAudio running on the device, you may need to use `FIRE4ARKOS_AUDIO_BACKEND=pulse` when launching.

### EmulationStation doesn't show "Fire4ArkOS Browser"

1. Check that the installer completed without errors
2. Verify `es_systems.cfg` contains the Fire4ArkOS entry:
   ```bash
   grep -A5 "<name>fire4arkos</name>" /etc/emulationstation/es_systems.cfg
   ```
3. Restart EmulationStation
4. If still missing, check permissions and ES backup files:
   ```bash
   ls -la /etc/emulationstation/es_systems.cfg*
   ```

### Cursor stuck in corner or window zoomed in

Set the internal scaling via the launcher script or environment:
```bash
FIRE4ARKOS_INTERNAL_SCALE=1 bash Fire4ArkOS\ Browser.sh
```

Valid values: `1`, `2`, or higher depending on your device resolution.

## Launching from Command Line

You can also launch the browser directly:

```bash
cd /roms/ports/Fire4ArkOS
bash "Fire4ArkOS Browser.sh" "https://example.com"
```

Or set custom environment variables:
```bash
cd /roms/ports/Fire4ArkOS
FIRE4ARKOS_INTERNAL_SCALE=2 FIRE4ARKOS_AUDIO_BACKEND=alsa bash "Fire4ArkOS Browser.sh"
```

## Environment Variables

- `FIRE4ARKOS_INTERNAL_SCALE`: Framebuffer scaling (1, 2, etc.; default: 2)
- `FIRE4ARKOS_AUDIO_BACKEND`: ALSA or Pulse backend (default: auto-detect)
- `FIRE4ARKOS_FRAME_SKIP`: Skip N frames (default: 0)
- `FIRE4ARKOS_SET_GOVERNOR`: Set CPU governor (default: 1)

---

**Enjoy Fire4ArkOS!**
