#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$REPO_ROOT/build"
OUTPUT="$BUILD_DIR/browser.arm64"

mkdir -p "$BUILD_DIR"

# 🔥 FULL SYSROOT
SYSROOT="${SYSROOT:-/mnt/d/C/sysroot-debian10}"

if [[ ! -d "$SYSROOT/usr" ]]; then
    echo "Invalid SYSROOT: $SYSROOT" >&2
    exit 1
fi

if ! command -v aarch64-linux-gnu-g++ >/dev/null 2>&1; then
    echo "Missing aarch64-linux-gnu-g++" >&2
    exit 1
fi

echo "Using sysroot: $SYSROOT"
echo ""

# 🔥 FORCE TOOLCHAIN TO USE SYSROOT (THIS WAS YOUR MISSING PIECE)
GCC_FLAGS=(
    --sysroot="$SYSROOT"
    -B"$SYSROOT/usr/lib/aarch64-linux-gnu"
    -B"$SYSROOT/lib/aarch64-linux-gnu"
)

INCLUDE_FLAGS=(
    -I"$SYSROOT/usr/include"
    -I"$SYSROOT/usr/include/aarch64-linux-gnu"
)

LIB_FLAGS=(
    -L"$SYSROOT/usr/lib/aarch64-linux-gnu"
    -L"$SYSROOT/lib/aarch64-linux-gnu"
    -Wl,-rpath-link,"$SYSROOT/usr/lib/aarch64-linux-gnu"
    -Wl,-rpath-link,"$SYSROOT/lib/aarch64-linux-gnu"
    -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1
)

aarch64-linux-gnu-g++ \
    "${GCC_FLAGS[@]}" \
    -std=c++17 -O2 -Wall -Wextra -Wpedantic \
    -mcpu=cortex-a53 -mtune=cortex-a53 \
    "${INCLUDE_FLAGS[@]}" \
    "$REPO_ROOT/src/main.cpp" \
    -o "$OUTPUT" \
    "${LIB_FLAGS[@]}" \
    -lSDL2 \
    -static-libstdc++ -static-libgcc

# Strip
aarch64-linux-gnu-strip "$OUTPUT"

echo ""
echo "=== Build Complete ==="
file "$OUTPUT"
ls -lh "$OUTPUT"

echo ""
echo "=== GLIBC Check ==="
readelf -s "$OUTPUT" | grep GLIBC || true