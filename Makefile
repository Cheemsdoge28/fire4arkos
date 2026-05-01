# Fire4ArkOS Browser - Cross-Platform Makefile
# Supports: Windows (MinGW), ARM64 (aarch64-linux-gnu), Linux native

TARGET ?= browser
SRC := src/main.cpp
BUILD_DIR ?= build
INSTALL_DIR ?= /usr/local/bin

# Detect platform
UNAME_S := $(shell uname -s)
UNAME_M := $(shell uname -m)

# Target platform (can be overridden: make PLATFORM=arm64)
PLATFORM ?= native
ifeq ($(UNAME_S),MINGW64_NT-10.0)
    PLATFORM ?= windows
endif

# Default flags
CXXFLAGS ?= -std=c++17 -O3 -flto -ffast-math -Wall -Wextra -Wpedantic
LDFLAGS ?= -flto
SDL_CFLAGS ?=
SDL_LIBS ?=

# Platform-specific configuration
ifeq ($(PLATFORM),windows)
    # Windows (MinGW)
    CXX ?= g++
    SDL2DIR ?= /mingw64
    SDL_CFLAGS ?= -I$(SDL2DIR)/include/SDL2 -Dmain=SDL_main
    SDL_LIBS ?= -L$(SDL2DIR)/lib -lmingw32 -lSDL2main -lSDL2 -lSDL2_ttf
    TARGET_SUFFIX := .exe
    STRIP ?= strip

else ifeq ($(PLATFORM),arm64)
    # ARM64 Cross-compilation (aarch64-linux-gnu)
    # R36S uses Rockchip RK3326 with 4x Cortex-A35 @ 1.3GHz
    # cortex-a53 is the closest widely-supported safe target; armv8-a+simd enables NEON
    CXX ?= aarch64-linux-gnu-g++
    SDL2DIR ?= /usr/aarch64-linux-gnu
    PKG_CONFIG_PATH := /usr/aarch64-linux-gnu/lib/pkgconfig
    SDL_CFLAGS ?= $(shell PKG_CONFIG_PATH=$(PKG_CONFIG_PATH) pkg-config --cflags sdl2 2>/dev/null || echo "-I$(SDL2DIR)/include/SDL2")
    SDL_LIBS ?= $(shell PKG_CONFIG_PATH=$(PKG_CONFIG_PATH) pkg-config --libs sdl2 SDL2_ttf 2>/dev/null || echo "-L$(SDL2DIR)/lib -lSDL2 -lSDL2_ttf") -lrt
    CXXFLAGS += -march=armv8-a+simd -mcpu=cortex-a53 -mtune=cortex-a53
    TARGET_SUFFIX := .arm64
    STRIP ?= aarch64-linux-gnu-strip

else
    # Linux native (builds directly on the R36S or any Linux host)
    CXX ?= g++
    PKG_CONFIG ?= pkg-config
    SDL_CFLAGS ?= $(shell $(PKG_CONFIG) --cflags sdl2 2>/dev/null)
    SDL_LIBS ?= $(shell $(PKG_CONFIG) --libs sdl2 SDL2_ttf 2>/dev/null)

    ifeq ($(strip $(SDL_CFLAGS)),)
        SDL_CFLAGS := -I/usr/include/SDL2
    endif

    ifeq ($(strip $(SDL_LIBS)),)
        SDL_LIBS := -lSDL2 -lSDL2_ttf
    endif

    # Add -lrt for POSIX shared memory (shm_open/mmap)
    SDL_LIBS += -lrt

    # When building natively on ARM, tune for the actual host CPU.
    # -march=native enables NEON SIMD for the memcpy-heavy SHM framebuffer path.
    UNAME_M_NATIVE := $(shell uname -m)
    ifeq ($(UNAME_M_NATIVE),aarch64)
        # RK3326 is Cortex-A35. We use -mcpu=cortex-a35 for best optimization.
        CXXFLAGS += -march=armv8-a+crc -mcpu=cortex-a35 -mtune=cortex-a35
    endif

    STRIP ?= strip
endif

# Build target with suffix
BUILD_TARGET := $(BUILD_DIR)/$(TARGET)$(TARGET_SUFFIX)

# Default target
all: $(BUILD_TARGET)

# Create build directory
$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

# Compile
$(BUILD_TARGET): $(SRC) | $(BUILD_DIR)
	@echo "[$(PLATFORM)] Building $(BUILD_TARGET)"
	@echo "  CXX: $(CXX)"
	@echo "  SDL_CFLAGS: $(SDL_CFLAGS)"
	@echo "  SDL_LIBS: $(SDL_LIBS)"
	$(CXX) $(CXXFLAGS) $(SDL_CFLAGS) $(LDFLAGS) $< -o $@ $(SDL_LIBS)
	@echo "Build complete: $@"
	@ls -lh $@

# Strip debug symbols for deployment
strip: $(BUILD_TARGET)
	$(STRIP) $(BUILD_TARGET)

# Install to system (Linux only)
install: $(BUILD_TARGET)
	@if [ "$(PLATFORM)" = "windows" ]; then \
		echo "Install not supported on Windows. Copy $(BUILD_TARGET) manually."; \
	else \
		install -D $(BUILD_TARGET) $(INSTALL_DIR)/$(TARGET); \
		echo "Installed to $(INSTALL_DIR)/$(TARGET)"; \
	fi

# Clean
clean:
	rm -rf $(BUILD_DIR)
	rm -f browser browser.exe browser.arm64 fire4arkos.log
	@echo "Cleaned build artifacts and stale logs."

# Cross-compile for ARM64
arm64: PLATFORM=arm64
arm64: $(BUILD_TARGET)
	@echo "ARM64 build complete: $<"

# Windows MinGW build
windows: PLATFORM=windows
windows: $(BUILD_TARGET)
	@echo "Windows build complete: $<"

# Native build
native: PLATFORM=native
native: $(BUILD_TARGET)
	@echo "Native build complete: $<"

# Show current configuration
config:
	@echo "=== Fire4ArkOS Browser Build Configuration ==="
	@echo "Platform: $(PLATFORM)"
	@echo "Compiler: $(CXX)"
	@echo "CXXFLAGS: $(CXXFLAGS)"
	@echo "SDL_CFLAGS: $(SDL_CFLAGS)"
	@echo "SDL_LIBS: $(SDL_LIBS)"
	@echo "Target: $(BUILD_TARGET)"
	@echo ""

.PHONY: all strip install clean arm64 windows native config
