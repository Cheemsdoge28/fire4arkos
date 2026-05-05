# WSL Cross-Compile

Use this when you want to produce `browser.arm64` on this Windows machine through WSL Ubuntu.

## One-Time Setup

From PowerShell in the repo:

```powershell
.\crosscompile-arm64.ps1 -Setup
```

This script:

- rewrites WSL Ubuntu's `ubuntu.sources` so `arm64` uses `ports.ubuntu.com`
- enables `arm64` multiarch
- installs:
  - `g++-aarch64-linux-gnu`
  - `binutils-aarch64-linux-gnu`
  - `pkg-config`

It also keeps a backup of the original source file as:

```text
/etc/apt/sources.list.d/ubuntu.sources.fire4arkos.bak
```

## Build

After setup:

```powershell
.\crosscompile-arm64.ps1
```

Before the build, you must provide an ARM64 SDL2 sysroot and point `SDL2_SYSROOT` at it inside WSL.

Expected contents:

```text
$SDL2_SYSROOT/include/SDL2/SDL.h
$SDL2_SYSROOT/lib/libSDL2.so
```

Expected output:

```text
build\browser.arm64
```

## Stage To /easyroms

Once `build\browser.arm64` exists:

```powershell
.\stage-easyroms.ps1 -EasyRomsRoot E:\easyroms
```

That creates:

```text
E:\easyroms\Fire4ArkOS
```
