#!/usr/bin/env bash
set -euo pipefail

UBUNTU_SOURCES="/etc/apt/sources.list.d/ubuntu.sources"
BACKUP_PATH="${UBUNTU_SOURCES}.fire4arkos.bak"

if [[ ! -f "$UBUNTU_SOURCES" ]]; then
    echo "Expected $UBUNTU_SOURCES to exist." >&2
    exit 1
fi

sudo cp "$UBUNTU_SOURCES" "$BACKUP_PATH"

sudo tee "$UBUNTU_SOURCES" >/dev/null <<'EOF'
Types: deb
URIs: http://archive.ubuntu.com/ubuntu
Suites: noble noble-updates noble-backports
Components: main restricted universe multiverse
Architectures: amd64
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: http://security.ubuntu.com/ubuntu
Suites: noble-security
Components: main restricted universe multiverse
Architectures: amd64
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: http://ports.ubuntu.com/ubuntu-ports
Suites: noble noble-updates noble-backports noble-security
Components: main restricted universe multiverse
Architectures: arm64
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF

sudo dpkg --add-architecture arm64
sudo apt-get update
sudo apt-get install -y \
    g++-aarch64-linux-gnu \
    binutils-aarch64-linux-gnu \
    pkg-config

echo "WSL host-side cross-compile dependencies installed."
echo "This script intentionally does not install libsdl2-dev:arm64 into the live WSL rootfs."
echo "Use a separate ARM64 SDL2 sysroot or a cross SDL2 package if available."
echo "Backup of original sources: $BACKUP_PATH"
