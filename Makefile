# Fire4ArkOS Browser - Cross-Platform Makefile
# Supports: Windows (MinGW), ARM64 (aarch64-linux-gnu), Linux native

TARGET ?= browser
SRC := src/main.cpp
XSHM_CAPTURE_SRC := src/xshm_capture.cpp
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
    CXX ?= aarch64-linux-gnu-g++
    SDL2DIR ?= /usr/aarch64-linux-gnu
    PKG_CONFIG_PATH := /usr/aarch64-linux-gnu/lib/pkgconfig
    SDL_CFLAGS ?= $(shell PKG_CONFIG_PATH=$(PKG_CONFIG_PATH) pkg-config --cflags sdl2 2>/dev/null || echo "-I$(SDL2DIR)/include/SDL2")
    SDL_LIBS ?= $(shell PKG_CONFIG_PATH=$(PKG_CONFIG_PATH) pkg-config --libs sdl2 SDL2_ttf 2>/dev/null || echo "-L$(SDL2DIR)/lib -lSDL2 -lSDL2_ttf")
    CXXFLAGS += -mcpu=cortex-a53 -mtune=cortex-a53
    TARGET_SUFFIX := .arm64
    STRIP ?= aarch64-linux-gnu-strip

else
    # Linux native
    CXX ?= g++
    PKG_CONFIG ?= pkg-config
    SDL_CFLAGS ?= $(shell $(PKG_CONFIG) --cflags sdl2 2>/dev/null)
    SDL_LIBS ?= $(shell $(PKG_CONFIG) --libs sdl2 SDL2_ttf 2>/dev/null)
    XSHM_LIBS ?= -lX11 -lXext
    
    ifeq ($(strip $(SDL_CFLAGS)),)
        SDL_CFLAGS := -I/usr/include/SDL2
    endif
    
    ifeq ($(strip $(SDL_LIBS)),)
        SDL_LIBS := -lSDL2 -lSDL2_ttf
    endif
    
    STRIP ?= strip
endif

# Build target with suffix
BUILD_TARGET := $(BUILD_DIR)/$(TARGET)$(TARGET_SUFFIX)
XSHM_CAPTURE_TARGET := $(BUILD_DIR)/xshm-capture

# Default target
all: $(BUILD_TARGET)
ifneq ($(PLATFORM),windows)
all: $(XSHM_CAPTURE_TARGET)
endif

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

ifneq ($(PLATFORM),windows)
$(XSHM_CAPTURE_TARGET): $(XSHM_CAPTURE_SRC) | $(BUILD_DIR)
	@echo "[$(PLATFORM)] Building $(XSHM_CAPTURE_TARGET)"
	$(CXX) $(CXXFLAGS) $< -o $@ $(XSHM_LIBS)
	@echo "Build complete: $@"
	@ls -lh $@
endif

# Strip debug symbols for deployment
strip: $(BUILD_TARGET)
	$(STRIP) $(BUILD_TARGET)

# Install to system (Linux only)
install: $(BUILD_TARGET)
ifneq ($(PLATFORM),windows)
install: $(XSHM_CAPTURE_TARGET)
endif
	@if [ "$(PLATFORM)" = "windows" ]; then \
		echo "Install not supported on Windows. Copy $(BUILD_TARGET) manually."; \
	else \
		install -D $(BUILD_TARGET) $(INSTALL_DIR)/$(TARGET); \
        if [ -x "$(XSHM_CAPTURE_TARGET)" ]; then install -D $(XSHM_CAPTURE_TARGET) $(INSTALL_DIR)/xshm-capture; fi; \
		echo "Installed to $(INSTALL_DIR)/$(TARGET)"; \
	fi

# Clean
clean:
	rm -rf $(BUILD_DIR)
	@echo "Cleaned"

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
