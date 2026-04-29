param(
    [string]$EasyRomsRoot = "",
    [string]$BinaryPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$stageRoot = Join-Path $repoRoot "dist\easyroms"
$appRoot = Join-Path $stageRoot "Fire4ArkOS"

function Write-UnixTextFile {
    param(
        [string]$Path,
        [string]$Content
    )

    $normalized = $Content -replace "`r`n", "`n"
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $normalized, $encoding)
}

if (-not $BinaryPath) {
    $candidates = @(
        (Join-Path $repoRoot "build\browser.arm64"),
        (Join-Path $repoRoot "browser.arm64")
    )

    $BinaryPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if (-not $BinaryPath) {
    throw "No ARM64 browser binary found. Put browser.arm64 in the repo root or build\browser.arm64, or pass -BinaryPath explicitly."
}

$BinaryPath = (Resolve-Path $BinaryPath).Path

$filesToCopy = @(
    @{ Source = $BinaryPath; Destination = "browser" },
    @{ Source = (Join-Path $repoRoot "firefox-framebuffer-wrapper.py"); Destination = "firefox-framebuffer-wrapper.py" },
    @{ Source = (Join-Path $repoRoot "arkos-deploy.sh"); Destination = "arkos-deploy.sh" },
    @{ Source = (Join-Path $repoRoot "README.md"); Destination = "README.md" },
    @{ Source = (Join-Path $repoRoot "QUICK_START.md"); Destination = "QUICK_START.md" },
    @{ Source = (Join-Path $repoRoot "SDCARD_DEPLOY.md"); Destination = "SDCARD_DEPLOY.md" }
)

Remove-Item -Recurse -Force $stageRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $appRoot -Force | Out-Null

foreach ($entry in $filesToCopy) {
    if (-not (Test-Path $entry.Source)) {
        throw "Missing required file: $($entry.Source)"
    }

    $destinationPath = Join-Path $appRoot $entry.Destination
    $extension = [System.IO.Path]::GetExtension($entry.Destination).ToLowerInvariant()

    if ($extension -in @(".sh", ".py", ".md", ".txt")) {
        $content = [System.IO.File]::ReadAllText($entry.Source)
        Write-UnixTextFile -Path $destinationPath -Content $content
    } else {
        Copy-Item -LiteralPath $entry.Source -Destination $destinationPath -Force
    }
}

$installScript = @'
#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="/opt/fire4arkos"

mkdir -p "$APP_DIR"
cp "$SCRIPT_DIR/browser" "$APP_DIR/browser"
cp "$SCRIPT_DIR/firefox-framebuffer-wrapper.py" "$APP_DIR/firefox-framebuffer-wrapper.py"
cp "$SCRIPT_DIR/arkos-deploy.sh" "$APP_DIR/arkos-deploy.sh"
chmod +x "$APP_DIR/browser" "$APP_DIR/firefox-framebuffer-wrapper.py" "$APP_DIR/arkos-deploy.sh"

bash "$APP_DIR/arkos-deploy.sh" "$APP_DIR"
'@

Write-UnixTextFile -Path (Join-Path $appRoot "install-from-easyroms.sh") -Content $installScript

$readme = @'
Copy this entire Fire4ArkOS folder to the /easyroms partition on the SD card.

On the device, run:
  cd /easyroms/Fire4ArkOS
  bash install-from-easyroms.sh

This installs the app into /opt/fire4arkos and creates /usr/local/bin/fire4arkos.
'@

Write-UnixTextFile -Path (Join-Path $appRoot "COPY_TO_EASYROMS.txt") -Content $readme

if ($EasyRomsRoot) {
    $resolvedRoot = (Resolve-Path $EasyRomsRoot).Path
    $targetRoot = Join-Path $resolvedRoot "Fire4ArkOS"
    Remove-Item -Recurse -Force $targetRoot -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
    Copy-Item -Path (Join-Path $appRoot "*") -Destination $targetRoot -Recurse -Force
    Write-Host "Copied staged files to: $targetRoot"
} else {
    Write-Host "Staged files at: $appRoot"
}

Write-Host "Manual copy target on the SD card: /easyroms/Fire4ArkOS"
