param(
    [switch]$Setup
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$wslRepoRoot = "/mnt/" + $repoRoot.Substring(0,1).ToLower() + $repoRoot.Substring(2).Replace('\', '/')

if ($Setup) {
    wsl.exe bash -lc "cd '$wslRepoRoot' && chmod +x setup-wsl-cross.sh && ./setup-wsl-cross.sh"
    exit $LASTEXITCODE
}

wsl.exe bash -lc "cd '$wslRepoRoot' && chmod +x build-arm64-wsl.sh && ./build-arm64-wsl.sh"
exit $LASTEXITCODE
