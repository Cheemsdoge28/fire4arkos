# EasyRoms Deploy

Use this when you want to copy the app directly onto the ArkOS SD card partition mounted as `/easyroms`.

## Current Limitation

This repo does not currently have a built ARM64 Linux binary on this machine.

You need one of these before staging:

- `build/browser.arm64`
- `browser.arm64`
- or pass `-BinaryPath` to the staging script

The existing `build/browser.exe` is the Windows build and will not run on ArkOS.

## Stage The Folder

From PowerShell in the repo:

```powershell
.\stage-easyroms.ps1 -BinaryPath D:\path\to\browser.arm64
```

This creates:

```text
dist\easyroms\Fire4ArkOS
```

## Copy To The SD Card

If your SD card partition is mounted in Windows, you can copy directly:

```powershell
.\stage-easyroms.ps1 -EasyRomsRoot E:\easyroms -BinaryPath D:\path\to\browser.arm64
```

That produces:

```text
E:\easyroms\Fire4ArkOS
```

If `E:\easyroms` does not exist and the mounted partition itself is the EasyRoms partition, use:

```powershell
.\stage-easyroms.ps1 -EasyRomsRoot E:\ -BinaryPath D:\path\to\browser.arm64
```

Then move the resulting `Fire4ArkOS` folder into the correct `/easyroms` location if needed.

## On The Device

Run:

```bash
cd /easyroms/Fire4ArkOS
bash install-from-easyroms.sh
```

That installs the runtime files into `/opt/fire4arkos` and creates `/usr/local/bin/fire4arkos`.

## Runtime Packages

For real Firefox pixels and text injection, ArkOS still needs:

- `firefox`
- `python3`
- `Xvfb`
- `ffmpeg` or ImageMagick `import`
- `xdotool`
