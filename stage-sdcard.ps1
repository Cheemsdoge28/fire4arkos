param(
    [string]$SdRoot = "",
    [string]$BinaryPath = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$stageRoot = Join-Path $repoRoot "dist\sdcard"
$appRoot = Join-Path $stageRoot "opt\fire4arkos"

if (-not $BinaryPath) {
    $candidates = @(
        (Join-Path $repoRoot "build\browser.arm64"),
        (Join-Path $repoRoot "browser.arm64")
    )

    $BinaryPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if (-not $BinaryPath) {
    throw "No ARM64 browser binary found. Build or copy browser.arm64 first, or pass -BinaryPath explicitly."
}

$BinaryPath = (Resolve-Path $BinaryPath).Path

$filesToCopy = @(
    @{ Source = $BinaryPath; Destination = "browser" },
    @{ Source = (Join-Path $repoRoot "firefox-framebuffer-wrapper.py"); Destination = "firefox-framebuffer-wrapper.py" },
    @{ Source = (Join-Path $repoRoot "arkos-deploy.sh"); Destination = "arkos-deploy.sh" },
    @{ Source = (Join-Path $repoRoot "README.md"); Destination = "README.md" },
    @{ Source = (Join-Path $repoRoot "QUICK_START.md"); Destination = "QUICK_START.md" }
)

Remove-Item -Recurse -Force $stageRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $appRoot -Force | Out-Null

foreach ($entry in $filesToCopy) {
    if (-not (Test-Path $entry.Source)) {
        throw "Missing required file: $($entry.Source)"
    }

    Copy-Item -LiteralPath $entry.Source -Destination (Join-Path $appRoot $entry.Destination) -Force
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

Set-Content -LiteralPath (Join-Path $appRoot "install-from-sd.sh") -Value $installScript -Encoding ascii

if ($SdRoot) {
    $resolvedSdRoot = (Resolve-Path $SdRoot).Path
    $targetRoot = Join-Path $resolvedSdRoot "Fire4ArkOS"
    Remove-Item -Recurse -Force $targetRoot -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
    Copy-Item -Path (Join-Path $appRoot "*") -Destination $targetRoot -Recurse -Force
    Write-Host "Copied staged files to SD card at: $targetRoot"
} else {
    Write-Host "Staged files at: $appRoot"
}

Write-Host "Next step on ArkOS: run install-from-sd.sh from the copied Fire4ArkOS directory."
