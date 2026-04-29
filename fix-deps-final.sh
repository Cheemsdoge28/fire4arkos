#!/bin/bash
set -e
SYSROOT="/mnt/d/C/sysroot-debian10"

echo "Resetting sysroot..."
rm -rf "$SYSROOT"
mkdir -p "$SYSROOT"

echo "Downloading Debian 10 Buster rootfs..."
rm -f /tmp/rootfs.tar.xz
# Grab buster from a different working commit 
wget -qO /tmp/rootfs.tar.xz https://github.com/debuerreotype/docker-debian-artifacts/raw/1826b52dc349b1ff80e5e0134f5aa7c5417094b8/arm64v8/buster/rootfs.tar.xz || \
wget -qO /tmp/rootfs.tar.xz https://github.com/debuerreotype/docker-debian-artifacts/raw/b024a792c752a5c6faa456a00a124c1303ba7f21/arm64v8/buster/rootfs.tar.xz || \
wget -qO /tmp/rootfs.tar.xz https://github.com/debuerreotype/docker-debian-artifacts/raw/de91cf237b6defb24d77dd0d02b8d009bda4eb53/arm64v8/buster/rootfs.tar.xz

echo "Extracting rootfs..."
tar -xf /tmp/rootfs.tar.xz -C "$SYSROOT" || true

# Set up a clean apt sandbox
rm -rf /tmp/apt-sandbox
mkdir -p /tmp/apt-sandbox/etc/apt/sources.list.d
mkdir -p /tmp/apt-sandbox/etc/apt/preferences.d
mkdir -p /tmp/apt-sandbox/var/lib/apt/lists/partial
mkdir -p /tmp/apt-sandbox/var/cache/apt/archives/partial
mkdir -p /tmp/apt-sandbox/var/lib/dpkg

cat << 'CFG' > /tmp/apt-sandbox/apt.conf
Apt::Architecture "arm64";
Apt::Architectures { "arm64"; };
Dir "/tmp/apt-sandbox";
Dir::State::status "/tmp/apt-sandbox/var/lib/dpkg/status";
Acquire::Languages "none";
Acquire::PDiffs "false";
Acquire::Check-Valid-Until "false";
CFG

touch /tmp/apt-sandbox/var/lib/dpkg/status

cat << 'SRC' > /tmp/apt-sandbox/etc/apt/sources.list
deb [arch=arm64 trusted=yes] http://archive.debian.org/debian/ buster main
deb [arch=arm64 trusted=yes] http://archive.debian.org/debian-security buster/updates main
SRC

echo "Updating sandbox apt..."
apt-get -c /tmp/apt-sandbox/apt.conf update >/dev/null 2>&1

cd /tmp/apt-sandbox/var/cache/apt/archives

PACKAGES=(
  libc6-dev libc6
  libsdl2-dev libsdl2-2.0-0 libwayland-egl1-mesa libwayland-dev libwayland-client0 libwayland-cursor0 libwayland-egl1
  libxkbcommon-dev libxkbcommon0
  libpulse-dev libpulse0 libpulse-mainloop-glib0
  libasound2-dev libasound2
  libdrm-dev libdrm2
  libgbm-dev libgbm1
  libegl1-mesa-dev libegl1-mesa libegl1 libegl-mesa0
  libgl1-mesa-dev libgl1-mesa-glx libgl1 libglx-mesa0 libglapi-mesa
  libgles2-mesa-dev libgles2-mesa libgles2
  libx11-dev libx11-6 libx11-xcb1
  libxext-dev libxext6
  libxcursor-dev libxcursor1
  libxi-dev libxi6
  libxrandr-dev libxrandr2
  libxss-dev libxss1
  libasyncns0 libcap2 libffi6 libice6 libsm6 libxau6 libxdmcp6 libxinerama1 libxrender1 libxtst6 libxxf86vm1 libsndio7.0 libwrap0 libdbus-1-3 libsndfile1 libsystemd0
  libsamplerate0 libxfixes3 libxcb1 libexpat1 libapparmor1 libflac8 libvorbis0a libvorbisenc2 libopus0 libogg0 libmpg123-0 libmp3lame0 libgcrypt20 liblz4-1 liblzma5 libzstd1 libsamplerate0-dev
  libbsd0 libuuid1 libnsl-dev libnsl2 libgpg-error0 uuid-dev
)

for pkg in "${PACKAGES[@]}"; do
  apt-get -c /tmp/apt-sandbox/apt.conf download "$pkg" 2>/dev/null || echo "Failed to get $pkg"
done

echo "Extracting packages..."
for deb in *.deb; do
  if [ -f "$deb" ]; then
    dpkg-deb -x "$deb" "$SYSROOT"
  fi
done

echo "Fixing symlinks..."
cd "$SYSROOT/usr/lib/aarch64-linux-gnu" 2>/dev/null || true
for link in *.so; do
    if [ -L "$link" ]; then
        target=$(readlink "$link")
        if [[ $target == /* ]]; then
            ln -snf "../../..$target" "$link"
        fi
    fi
done

cd "$SYSROOT/lib/aarch64-linux-gnu" 2>/dev/null || true
for link in *.so; do
    if [ -L "$link" ]; then
        target=$(readlink "$link")
        if [[ $target == /* ]]; then
            ln -snf "../../..$target" "$link"
        fi
    fi
done

# Fix absolute paths in linker scripts replacing /usr/lib with our sysroot location for cross compilation
for linker_script in "$SYSROOT/usr/lib/aarch64-linux-gnu"/lib*.so; do
  if grep -q "GROUP ( /lib" "$linker_script" 2>/dev/null; then
    echo "Fixing script $linker_script"
    sed -i 's| /lib/| /mnt/d/C/sysroot-debian10/lib/|g; s| /usr/lib/| /mnt/d/C/sysroot-debian10/usr/lib/|g' "$linker_script"
  fi
done

echo "Sysroot rebuilt and dependencies added!"
