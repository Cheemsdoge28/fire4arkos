# SD Card Deploy

Use this when SSH is unavailable and you want to move the browser to the ArkOS SD card directly from Windows.

## What You Need

- An ARM64 build named `build/browser.arm64` or `browser.arm64`
- The SD card mounted on Windows

## Stage Files

From PowerShell in the repo:

```powershell
.\stage-sdcard.ps1
```

This creates a staging directory at:

```text
dist\sdcard\opt\fire4arkos
```

## Copy Straight To The SD Card

If the SD card is mounted, pass its drive or target folder:

```powershell
.\stage-sdcard.ps1 -SdRoot E:\
```

That writes the deployable files to:

```text
E:\Fire4ArkOS
```

## Install On The R36S

After inserting the card into the device, open a terminal or file-manager-based launcher and run:

```bash
cd /path/to/Fire4ArkOS
bash install-from-sd.sh
```

The installer copies files into `/opt/fire4arkos` and then runs `arkos-deploy.sh`.

## Runtime Packages

For real captured Firefox pixels and text injection, the device should have:

- `firefox`
- `python3`
- `Xvfb`
- `ffmpeg` or ImageMagick `import`
- `xdotool`

Without those extra tools, the app will still launch, but it may fall back to placeholder frames or limited input behavior.
