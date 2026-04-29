#!/bin/bash
set -e

echo "Updating package lists..."
sudo apt-get update

echo "Installing required development tools and dependencies..."
sudo apt-get install --reinstall -y \
    gdb libc6-dev libsdl2-dev linux-libc-dev g++ libstdc++-9-dev \
    libsdl2-ttf-dev git python3 ninja-build cmake make \
    i2c-tools usbutils fbcat fbset mmc-utils \
    libglew-dev libegl1-mesa-dev libgl1-mesa-dev \
    libgles2-mesa-dev libglu1-mesa-dev fonts-liberation \
    xvfb ffmpeg xdotool firefox x11-utils

echo "Building native Fire4ArkOS browser..."
make native

echo "Installing Fire4ArkOS natively..."
sudo make install

echo "Native install complete!"