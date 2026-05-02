#!/usr/bin/env python3
"""
Firefox framebuffer wrapper for Fire4ArkOS.
Optimized with command batching for zero subprocess overhead per input event.

Linux path:
- Launch Firefox in an Xvfb display when available
- Capture real pixels via Xvfb fbdir (mmap), ffmpeg x11grab, or ImageMagick import
- Inject input via batched xdotool commands (single subprocess per batch, not per event)

Fallback path:
- Launch Firefox headless and stream a placeholder frame
"""

import ctypes
import mmap
import os
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path


FRAME_INTERVAL = 1.0 / float(os.environ.get("FPS", "60"))
XVFB_FBDIR = "/tmp"
XVFB_SCREEN_FILE = "/tmp/Xvfb_screen0"
CLICK_DEBOUNCE = 0.30  # seconds: debounce rapid duplicate clicks


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off", "")


class CommandBatcher:
    """Batch xdotool commands to minimize subprocess spawning overhead."""
    
    def __init__(self, display_num=":99"):
        self.display_num = display_num
        self.batch = []
        self.last_flush_time = time.time()
        # In max performance mode, favor fewer subprocess launches.
        # Balanced: smaller batches for responsive input, gentle on CPU
        self.max_batch_size = 10 if env_flag("FIRE4ARKOS_MAX_PERF", False) else 8
        self.max_batch_age = 0.012 if env_flag("FIRE4ARKOS_MAX_PERF", False) else 0.015
    
    def add_command(self, *args):
        """Add a command to the batch. Flush immediately for non-motion commands."""
        # Non-motion commands like 'type' can swallow subsequent arguments if batched.
        is_motion = args[0] in ("mousemove", "mousemove_relative")
        if not is_motion:
            self.flush()
            self.batch.append(list(args))
            self.flush()
        else:
            self.batch.append(list(args))
            if len(self.batch) >= self.max_batch_size:
                self.flush()
    
    def flush(self):
        """Execute all batched commands in a single xdotool invocation."""
        if not self.batch:
            return True
        try:
            env = os.environ.copy()
            env["DISPLAY"] = self.display_num

            # Concatenate all queued commands into a single xdotool invocation.
            # This is significantly faster than spawning one process per command.
            full_args = []
            for args in self.batch:
                full_args.extend(list(args))
            
            if not full_args:
                self.batch = []
                return True

            cmd = ["xdotool"] + full_args
            try:
                # Use a 1.0s timeout for the entire batch.
                subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1.0)
            except subprocess.TimeoutExpired:
                print(f"Batch timeout: {' '.join(cmd)}", flush=True)
            except Exception as e:
                print(f"Batch error ({' '.join(cmd)}): {e}", flush=True)

            self.batch = []
            self.last_flush_time = time.time()
            return True
        except Exception as e:
            print(f"Batch flush error: {e}", flush=True)
            self.batch = []
            return False
    
    def maybe_flush(self):
        """Flush if batch is old enough."""
        if self.batch and (time.time() - self.last_flush_time) > self.max_batch_age:
            self.flush()


# --- Shared memory frame producer (zero-copy transfer to C++ consumer) ---
SHM_NAME = "/fire4arkos_fb"
SHM_MAGIC = 0x46425348  # 'FBSH'
SHM_HEADER_SIZE = 32  # magic(4) + width(4) + height(4) + stride(4) + frame_seq(8) + flags(4) + reserved(4)


class ShmFrameProducer:
    """Write frames into a POSIX shared memory segment for zero-copy reading by C++."""

    def __init__(self, width, height, logger=None):
        self.width = width
        self.height = height
        self.stride = width * 4
        self.pixel_bytes = width * height * 4
        self.total_size = SHM_HEADER_SIZE + self.pixel_bytes
        self.frame_seq = 0
        self.shm_fd = -1
        self.mm = None
        self.log = logger or (lambda m: print(m, flush=True))

    def open(self):
        """Create or open the shared memory segment. Returns True on success."""
        try:
            # Remove stale segment if present
            try:
                fd = os.open(f"/dev/shm{SHM_NAME}", os.O_RDWR)
                os.close(fd)
                os.unlink(f"/dev/shm{SHM_NAME}")
            except OSError:
                pass

            self.shm_fd = os.open(
                f"/dev/shm{SHM_NAME}",
                os.O_CREAT | os.O_RDWR | os.O_TRUNC,
                0o666,
            )
            os.ftruncate(self.shm_fd, self.total_size)
            self.mm = mmap.mmap(self.shm_fd, self.total_size)

            # Write header
            header = struct.pack(
                "<IIIIqI4x",
                SHM_MAGIC,
                self.width,
                self.height,
                self.stride,
                0,  # frame_seq
                0,  # flags
            )
            self.mm[:SHM_HEADER_SIZE] = header
            self.log(f"SHM producer opened: {SHM_NAME} ({self.total_size} bytes)")
            return True
        except Exception as exc:
            self.log(f"SHM open failed: {exc}")
            return False

    def write_frame(self, data):
        """Write pixel data and bump the sequence counter."""
        if self.mm is None:
            return False
        try:
            self.mm[SHM_HEADER_SIZE : SHM_HEADER_SIZE + self.pixel_bytes] = data[: self.pixel_bytes]
            self.frame_seq += 1
            # Update frame_seq in header (offset 16, 8 bytes little-endian)
            struct.pack_into("<q", self.mm, 16, self.frame_seq)
            return True
        except Exception as exc:
            self.log(f"SHM write error: {exc}")
            return False

    def close(self):
        if self.mm is not None:
            try:
                self.mm.close()
            except Exception:
                pass
            self.mm = None
        if self.shm_fd >= 0:
            try:
                os.close(self.shm_fd)
            except Exception:
                pass
            self.shm_fd = -1
        # Unlink so it's cleaned up
        try:
            os.unlink(f"/dev/shm{SHM_NAME}")
        except OSError:
            pass


class FirefoxFramebufferWrapper:
    def __init__(self, initial_url="https://example.com", pipe_base="fire4arkos"):
        self.initial_url = initial_url
        self.pipe_base = pipe_base
        self.fb_pipe = f"/tmp/{pipe_base}_fb"
        self.cmd_pipe = f"/tmp/{pipe_base}_in"
        self.firefox_process = None
        self.xvfb_process = None
        self.running = True
        self.display_width = 640
        self.display_height = 480
        try:
            self.internal_scale = max(1, int(os.environ.get("FIRE4ARKOS_INTERNAL_SCALE", "1")))
        except ValueError:
            self.internal_scale = 1
        # Xvfb ALWAYS runs at full display resolution so Firefox renders normally.
        # internal_scale only affects SHM frame size (less data to transfer to C++).
        self.width = self.display_width    # Xvfb / Firefox window resolution
        self.height = self.display_height  # Xvfb / Firefox window resolution
        self.shm_width = max(1, self.display_width // self.internal_scale)   # SHM output size
        self.shm_height = max(1, self.display_height // self.internal_scale) # SHM output size
        self.fps = int(os.environ.get("FPS", "60"))
        self.max_perf = env_flag("FIRE4ARKOS_MAX_PERF", False)
        self.low_quality = env_flag("FIRE4ARKOS_LOW_QUALITY", True)
        self.no_sleep = env_flag("FIRE4ARKOS_NO_SLEEP", False)
        self.soc = os.environ.get("FIRE4ARKOS_SOC", "rk3326").lower()
        self.is_rk3326 = "rk3326" in self.soc
        self.display = os.environ.get("DISPLAY")
        self.profile_dir = Path(f"/tmp/firefox_profile_{os.getpid()}")
        self.capture_backend = "placeholder"
        self.input_backend = "noop"
        self.is_linux = os.name != "nt"
        self.last_pointer_signature = None
        self.last_pointer_time = 0.0
        self.last_click_time = 0.0
        self.tmpfs_cache_dir = Path("/tmp/firefox_cache")
        self.disk_cache_dir = None
        self.command_batcher = None  # Will be initialized after display is ready
        self.shm_producer = None  # ShmFrameProducer instance (set in run_fbdir_stream)

    def log(self, message):
        print(f"[{time.ctime()}] {message}", flush=True)

    def debug(self, message):
        if os.environ.get("FIRE4ARKOS_INPUT_DEBUG"):
            self.log("[INPUT_DEBUG] " + message)

    def which(self, name):
        return shutil.which(name)

    def resolve_disk_cache_dir(self):
        candidates = [
            Path("/mnt/sdcard/firefox_cache"),
            Path("/tmp/firefox_cache_disk"),
            self.profile_dir / "cache",
        ]

        for candidate in candidates:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                if os.access(str(candidate), os.W_OK):
                    return candidate
            except Exception:
                continue

        fallback = self.profile_dir / "cache"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def create_pipes(self):
        for pipe in [self.fb_pipe, self.cmd_pipe]:
            try:
                os.mkfifo(pipe, 0o666)
                self.log(f"Created pipe: {pipe}")
            except FileExistsError:
                pass
            except Exception as exc:
                self.log(f"Warning: could not create pipe {pipe}: {exc}")

    def find_firefox(self):
        candidates = [
            "/usr/bin/firefox",
            "/usr/local/bin/firefox",
            "/opt/firefox/firefox",
            "firefox",
        ]
        for path in candidates:
            if os.path.exists(path) and os.access(path, os.X_OK):
                return path
        return "firefox"

    def _cleanup_stale_display(self, display_num):
        num = display_num.lstrip(":")
        lock_file = f"/tmp/.X{num}-lock"

        # Kill the process listed in the lock file before removing it
        try:
            with open(lock_file, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            self.log(f"Sent SIGTERM to stale Xvfb PID {pid}")
            time.sleep(0.3)
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        except (OSError, ValueError):
            pass

        for path in (lock_file, f"/tmp/.X11-unix/X{num}", XVFB_SCREEN_FILE):
            try:
                os.remove(path)
                self.log(f"Removed stale file: {path}")
            except OSError:
                pass

    def start_virtual_display(self):
        if not self.is_linux:
            return False
        if self.display:
            self.log(f"Using existing display {self.display}")
            return True

        xvfb = self.which("Xvfb")
        if not xvfb:
            self.log("Xvfb not found; capture will fall back to placeholder frames")
            return False

        display_num = ":99"
        # -dpi 228: R36S physical panel density (3.5" @ 640x480 = ~228 PPI)
        # Matches devPixelsPerPx=1.0 for correct font/UI scaling at physical size.
        # When FIRE4ARKOS_INTERNAL_SCALE > 1, Firefox/Xvfb runs at a smaller
        # internal framebuffer and the SDL app upscales it to the display.
        # -shmem: enables MIT-SHM extension so Firefox can share surfaces directly
        # NOTE: do NOT add -nocursor — Firefox changes the X11 cursor interactively
        # (text caret, pointer, resize handles) and those are composited into the captured frame.
        # Keep physical DPI constant at 228 (R36S native density).
        # We will use layout.css.devPixelsPerPx to handle the internal scaling instead
        # of changing the DPI, which avoids conflicting scaling calculations in Firefox.
        base_cmd = [xvfb, display_num, "-screen", "0", f"{self.width}x{self.height}x24",
                    "-nolisten", "tcp", "-dpi", "228", "-shmem"]

        # Try with -fbdir first (direct mmap capture); fall back to plain Xvfb + ffmpeg
        for extra in (["-fbdir", XVFB_FBDIR], []):
            self._cleanup_stale_display(display_num)
            cmd = base_cmd + extra
            label = "with fbdir" if extra else "without fbdir"
            self.log(f"Starting Xvfb {label}: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )

            for _ in range(20):
                if proc.poll() is not None:
                    break
                time.sleep(0.10)

            if proc.poll() is None:
                self.xvfb_process = proc
                self.display = display_num
                self.log(f"Xvfb started {label}")
                return True

            self.log(f"Xvfb exited early {label}")

        self.log("Xvfb could not start")
        return False

    def _xwd_layout(self, path):
        """Return XWD pixel layout metadata or None on failure."""
        try:
            with open(path, "rb") as f:
                raw = f.read(100)
            if len(raw) < 100:
                return None
            for endian in ("<", ">"):
                fields = struct.unpack(f"{endian}25I", raw)
                header_size, depth, width, height, bits_per_pixel, bytes_per_line, ncolors = (
                    fields[0], fields[3], fields[4], fields[5], fields[11], fields[12], fields[19]
                )
                if 1 <= depth <= 32 and 1 <= width <= 4096 and 1 <= height <= 4096 and 100 <= header_size <= 65536:
                    offset = header_size + ncolors * 12
                    if bytes_per_line == 0:
                        bytes_per_line = width * 4 if bits_per_pixel >= 24 else width * ((bits_per_pixel + 7) // 8)
                    self.log(
                        f"XWD: {width}x{height} depth={depth} bpp={bits_per_pixel} "
                        f"stride={bytes_per_line} pixel_offset={offset}"
                    )
                    return {
                        "offset": offset,
                        "width": width,
                        "height": height,
                        "bits_per_pixel": bits_per_pixel,
                        "bytes_per_line": bytes_per_line,
                    }
        except Exception as exc:
            self.log(f"XWD parse error: {exc}")
        return None

    def detect_backends(self):
        if not self.is_linux or not self.display:
            self.capture_backend = "placeholder"
            self.input_backend = "noop"
            return

        # Try xdotool first (available on most X11 systems)
        if self.which("xdotool"):
            self.input_backend = "xdotool"
            self.command_batcher = CommandBatcher(self.display)
            self.log("Input backend: xdotool (batched, high-performance)")
        else:
            self.input_backend = "noop"
            self.log("Input backend: noop (no input capability)")

        # fbdir: direct mmap read from Xvfb's framebuffer file — fastest, no extra process
        if os.path.exists(XVFB_SCREEN_FILE):
            self.capture_backend = "fbdir"
        elif self.which("ffmpeg"):
            self.capture_backend = "ffmpeg"
        elif self.which("import"):
            self.capture_backend = "import"
        else:
            self.capture_backend = "placeholder"

        self.log(f"Capture backend: {self.capture_backend}")

    def firefox_env(self):
        env = os.environ.copy()
        if self.display:
            env["DISPLAY"] = self.display
        env["ALSA_CARD"] = os.environ.get("ALSA_CARD", "0")
        # ALSA device routing — cubeb alsa backend respects AUDIODEV.
        env["MOZ_ALSA_DEVICE"] = "default"
        env["AUDIODEV"] = "default"
        env["SDL_AUDIODRIVER"] = "alsa"
        # Do NOT set PULSE_SERVER=disabled — it causes cubeb to abort entirely
        # instead of falling back to ALSA. Remove any inherited PulseAudio override.
        env.pop("PULSE_SERVER", None)
        env["FIRE4ARKOS_USER_AGENT"] = os.environ.get(
            "FIRE4ARKOS_USER_AGENT",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        env["FIRE4ARKOS_AUDIO_BACKEND"] = os.environ.get("FIRE4ARKOS_AUDIO_BACKEND", "auto")
        env["MOZ_ENABLE_WAYLAND"] = "0"
        env["MOZ_X11_EGL"] = "1"          # Use EGL over GLX (lower overhead on ARM)
        env["GTK_USE_PORTAL"] = "0"
        env["MOZ_FORCE_DISABLE_E10S"] = "0"
        # Use GLES2 for compositor — avoids full OpenGL driver stack on ARM
        env["MOZ_WEBRENDER"] = "0"        # WebRender needs a real GPU, disable for Xvfb
        env["MOZ_ACCELERATED"] = "0"      # No GPU acceleration in Xvfb
        env["LIBGL_ALWAYS_SOFTWARE"] = "0" # Allow hardware GL if available
        # Reduce GTK overhead
        env["GDK_BACKEND"] = "x11"
        env["GTK_OVERLAY_SCROLLING"] = "0"
        return env

    def start_firefox(self):
        firefox_bin = self.find_firefox()
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        # Setup hybrid cache: tmpfs (hot) + disk (large assets, with aggressive culling)
        cache_dir = self.tmpfs_cache_dir
        try:
            cache_dir.mkdir(exist_ok=True)
            # Try to mount as tmpfs if not already mounted (requires root or sudo)
            result = subprocess.run(
                ["mount", "-t", "tmpfs", "-o", "size=512M", "tmpfs", str(cache_dir)],
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                timeout=2
            )
            if result.returncode == 0:
                self.log(f"Mounted tmpfs cache at {cache_dir} (512MB hot)")
                self.has_tmpfs = True
            else:
                # If mount fails, just use /tmp (which is often tmpfs anyway)
                cache_dir = Path("/tmp")
                self.log("Using /tmp for cache (may already be tmpfs)")
                self.has_tmpfs = False
        except Exception as e:
            cache_dir = Path("/tmp")
            self.log(f"Cache mount setup: {e}, using /tmp")
            self.has_tmpfs = False

        # Setup disk cache on SD card when available, otherwise use a writable fallback
        disk_cache_dir = self.resolve_disk_cache_dir()
        self.disk_cache_dir = disk_cache_dir
        disk_cache_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"Disk cache directory: {disk_cache_dir}")

        http_max_connections = 48 if self.is_rk3326 else 96
        http_persistent = 6 if self.is_rk3326 else 8
        disk_capacity = 131072 if self.is_rk3326 else 262144
        mem_capacity = 65536 if self.is_rk3326 else 196608
        mem_max_entry = 8192 if self.is_rk3326 else 16384
        disk_max_entry = 8192 if self.is_rk3326 else 32768
        media_max_fps = 24 if self.low_quality else (30 if self.is_rk3326 else 60)
        ipc_count = 1 if self.is_rk3326 else 2
        js_high_water = 64 if self.is_rk3326 else 128
        js_max_mem = 196608 if self.is_rk3326 else 393216
        image_decode_threads = 1 if self.low_quality else (2 if self.is_rk3326 else 4)
        image_surfacecache = 8192 if self.low_quality else 16384
        image_decode_bytes = 1024 if self.low_quality else 4096
        image_downscale = "true" if self.low_quality else "false"
        session_history = 4 if self.is_rk3326 else 8
        tabs_max_mem = 256 if self.is_rk3326 else 384
        dev_pixels_per_px = 1.0 / float(self.internal_scale)
        user_agent_override = os.environ.get(
            "FIRE4ARKOS_USER_AGENT",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        audio_backend = os.environ.get("FIRE4ARKOS_AUDIO_BACKEND", "auto").strip().lower()
        # On ArkOS/RK3326, ALSA is the most reliable backend. Force it if 'auto' or unspecified.
        if audio_backend in {"", "auto", "default"} and self.is_rk3326:
            audio_backend = "alsa"
            
        if audio_backend in {"alsa", "pulse", "jack", "sndio"}:
            audio_backend_pref = f'user_pref("media.cubeb.backend", "{audio_backend}");\n'
        else:
            if audio_backend not in {"", "auto", "default"}:
                self.log(f"Unknown FIRE4ARKOS_AUDIO_BACKEND={audio_backend!r}; leaving cubeb backend on Firefox default")
            audio_backend_pref = ""
        selected_audio_backend = audio_backend
        self.log(
            f"Scale config: display={self.display_width}x{self.display_height} "
            f"capture={self.width}x{self.height} internal_scale={self.internal_scale} "
            f"devPixelsPerPx={dev_pixels_per_px:.3f} audio_backend={selected_audio_backend}"
        )

        prefs = f"""user_pref("browser.startup.homepage", "about:blank");
    user_pref("general.useragent.override", "{user_agent_override}");
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.tabs.closeWindowWithLastTab", false);
user_pref("font.default.x-western", "sans-serif");
user_pref("font.name-list.sans-serif.x-western", "Noto Sans, Noto Sans CJK SC, Noto Sans CJK TC, Noto Sans CJK JP, Noto Sans CJK KR");
user_pref("toolkit.cosmeticAnimations.enabled", false);
user_pref("general.smoothScroll", false);
user_pref("network.http.max-connections", {http_max_connections});
user_pref("network.http.max-persistent-connections-per-server", {http_persistent});
user_pref("network.http.max-urgent-unused-idle-connections", 0);
user_pref("network.dns.disablePrefetch", false);
user_pref("network.prefetch-next", true);

/* Cache: RAM (hot) + disk (cold, with limits) */
user_pref("browser.cache.disk.enable", true);
user_pref("browser.cache.disk.capacity", {disk_capacity});
user_pref("browser.cache.memory.enable", true);
user_pref("browser.cache.memory.capacity", {mem_capacity});
user_pref("browser.cache.memory.max_entry_size", {mem_max_entry});
user_pref("browser.cache.disk.max_entry_size", {disk_max_entry});
user_pref("browser.sessionstore.max_tabs_undo", 0);
user_pref("browser.sessionstore.max_windows_undo", 0);

/* Disable gamepad API to prevent Firefox from double-handling controller inputs */
user_pref("dom.gamepad.enabled", false);
user_pref("dom.gamepad.non_standard_events.enabled", false);

/* Disable touch and pointer events to force pure legacy mouse behavior */
user_pref("dom.w3c_touch_events.enabled", 0);
user_pref("dom.w3c_pointer_events.enabled", false);
    user_pref("dom.max_script_run_time", 30);
    user_pref("dom.max_chrome_script_run_time", 30);

/* Reduce telemetry and background sync that cause writes */
user_pref("services.sync.enabled", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("app.update.enabled", false);

/* Audio: default to Firefox's backend selection unless explicitly overridden.
   On some devices ALSA is preferred; on desktop Linux Pulse/PipeWire often works better. */
user_pref("media.cubeb.sandbox", false);
user_pref("security.sandbox.content.level", 0);
user_pref("media.cubeb.output_sample_rate", 48000);
user_pref("media.volume_scale", "1.0");
user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 0);
{audio_backend_pref}

/* UI Compactness and Scaling */
user_pref("browser.uidensity", 1); /* Compact mode to save vertical space */
user_pref("browser.compactmode.show", true);
user_pref("browser.tabs.drawInTitlebar", true);

/* Prevent jitter from dismissing menus (VERY IMPORTANT for handhelds) */
user_pref("ui.popup.disable_autohide", true);

/* --- MEDIA PERFORMANCE ---
   VP9 / WebM are software-decode only on this ARM SoC.
   Force H.264 (AVC) via MSE + system ffmpeg which has hardware-assisted paths. */
user_pref("media.mediasource.enabled", true);
user_pref("media.mediasource.mp4.enabled", true);
user_pref("media.mediasource.vp9.enabled", false);
user_pref("media.mediasource.webm.enabled", false);
user_pref("media.mediasource.vp9.implicit.enabled", false);
user_pref("media.mediasource.av1.enabled", false);
user_pref("media.av1.enabled", false);
user_pref("media.ffmpeg.enabled", true);
user_pref("media.ffmpeg.vaapi.enabled", true);
user_pref("media.ffvpx.enabled", false);
/* Allow autoplay so media with sound can start without requiring manual permission. */
user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 2);
user_pref("media.memory_cache_max_size", 65536);
user_pref("media.cache_size", 524288);
user_pref("media.navigator.video.max_fps", {media_max_fps});
user_pref("media.video-max-decode-error", 0);

/* Prevent CPU stall on heavy pages: limit content processes + GC tuning */
user_pref("dom.ipc.processCount", {ipc_count});
user_pref("dom.ipc.processCount.webIsolated", {ipc_count});
user_pref("dom.ipc.processCount.file", {ipc_count});
user_pref("browser.tabs.remote.autostart", true);
user_pref("javascript.options.mem.gc_incremental", true);
user_pref("javascript.options.mem.gc_per_zone", true);
user_pref("javascript.options.mem.gc_incremental_slice_ms", 25);
user_pref("javascript.options.mem.high_water_mark", {js_high_water});
user_pref("javascript.options.mem.max", {js_max_mem});
user_pref("dom.ipc.tabs.shutdownTimeoutSecs", 5);

/* Ion JIT MUST be on — sites like Reddit use heavy React bundles.
   Baseline-only is 2-3x slower for hot JS loops. */
user_pref("javascript.options.baselinejit", true);
user_pref("javascript.options.ion", true);
user_pref("javascript.options.native_regexp", true);

/* Reduce reflow frequency during page load (less layout thrash) */
user_pref("content.notify.interval", 750000);

user_pref("image.downscale-during-decode.enabled", {image_downscale});
user_pref("image.mem.surfacecache.max_size_kb", {image_surfacecache});
user_pref("image.mem.discardable", true);
user_pref("image.mem.decode_bytes_at_a_time", {image_decode_bytes});
user_pref("image.multithreaded_decoding.limit", {image_decode_threads});
user_pref("image.high_quality_upscaling.enabled", false);
user_pref("image.high_quality_downscaling.enabled", false);
user_pref("image.animation_mode", "none");
user_pref("image.mem.min_discard_timeout_ms", 250);
user_pref("gfx.canvas.accelerated", false);
user_pref("layers.mlgpu.enabled", false);
user_pref("layers.offmainthreadcomposition.enabled", true);
user_pref("layers.async-pan-zoom.enabled", true);
user_pref("browser.low_commit_space_threshold_mb", 96);
user_pref("browser.sessionhistory.max_entries", {session_history});
user_pref("dom.image.lazy_loading.enabled", true);
user_pref("browser.tabs.max_memory_usage_mb", {tabs_max_mem});
"""
        # Write to user.js instead of prefs.js to ensure these settings are 
        # always applied and not overwritten by Firefox's internal state.
        (self.profile_dir / "user.js").write_text(prefs, encoding="utf-8")
        
        # userChrome.css: performance-safe tweaks only (no layout breaking)
        chrome_dir = self.profile_dir / "chrome"
        chrome_dir.mkdir(exist_ok=True)
        
        userchrome_css = f"""
/* Enable compact mode and shrink chrome for {self.width}x{self.height} display */
* {{
    animation-duration: 0s !important;
    transition-duration: 0s !important;
}}

/* Merge title bar into tab bar */
#titlebar {{
    -moz-appearance: none !important;
}}

/* Shrink tab bar */
#TabsToolbar {{
    min-height: 22px !important;
    max-height: 22px !important;
}}
.tabbrowser-tab {{
    min-height: 22px !important;
    max-height: 22px !important;
}}
.tab-content {{
    padding: 1px 4px !important;
}}
.tab-label {{
    font-size: 9px !important;
    line-height: 1.1 !important;
}}

/* Shrink navigation bar */
#nav-bar {{
    min-height: 24px !important;
    padding-top: 1px !important;
    padding-bottom: 1px !important;
}}
#urlbar {{
    min-height: 20px !important;
    --urlbar-min-height: 20px !important;
}}
#urlbar-input-container {{
    min-height: 18px !important;
    padding: 0 !important;
}}
.urlbarView {{
    font-size: 10px !important;
}}

/* Hide rarely-used buttons to save space */
#back-button, #forward-button {{
    min-width: 22px !important;
    max-width: 22px !important;
}}
#stop-reload-button {{
    min-width: 22px !important;
    max-width: 22px !important;
}}
/* Hide sidebar and new-tab buttons to save space */
#sidebar-button,
#tabs-newtab-button {{
    display: none !important;
}}
"""
        (chrome_dir / "userChrome.css").write_text(userchrome_css, encoding="utf-8")
        
        # userContent.css: light performance hints that don't break layouts
        usercontent_css = """
@-moz-document url-prefix() {
    /* Disable CSS animations on web content (saves CPU) */
    *, *::before, *::after {
        animation-duration: 0s !important;
        transition-duration: 0s !important;
    }
    
    /* Surgical DOM culling: skip rendering for off-screen posts/comments */
    /* This prevents 'DOM explosion' freezes on sites like Reddit/Twitter */
    article, section, .Post, .Comment, [role="article"] {
        content-visibility: auto !important;
        /* auto: lets browser measure real size; avoids layout thrash on tall cards */
        contain-intrinsic-block-size: auto 300px;
    }
    
    /* Constrain video height only — width is already constrained by the 640px viewport */
    video {
        max-height: 480px !important;
    }
    
    /* Hide heavy dynamic sidebars on common sites */
    [aria-label="Trending"], aside:not([role]), .sidebar {
        display: none !important;
    }
}
"""
        (chrome_dir / "userContent.css").write_text(usercontent_css, encoding="utf-8")
        
        # userContent.js: Viewport culling script for infinite-scroll sites (Reddit, Twitter, etc.)
        usercontent_js = """
(function() {
    'use strict';
    const VIEWPORT_HEIGHT = window.innerHeight;
    const CULL_THRESHOLD = VIEWPORT_HEIGHT * 2;
    let lastCullTime = 0;
    const CULL_INTERVAL = 5000; // Every 5 seconds
    
    function cullOffscreenElements() {
        const now = performance.now();
        if (now - lastCullTime < CULL_INTERVAL) return;
        lastCullTime = now;
        
        try {
            const elements = document.querySelectorAll('article, section, li, div[role="article"], .Post, .Comment');
            let culled = 0;
            elements.forEach((el) => {
                if (!el || !el.offsetParent) return;
                if (el.matches('[role="progressbar"], [aria-busy="true"], .loader, .Loading, .loading, [data-testid*="loading"], [data-testid*="spinner"]')) return;
                const rect = el.getBoundingClientRect();
                if (rect.bottom < -CULL_THRESHOLD || rect.top > VIEWPORT_HEIGHT + CULL_THRESHOLD) {
                    if (!el.dataset.culled) {
                        el.style.display = 'none';
                        el.dataset.culled = 'true';
                        culled++;
                    }
                } else if (el.dataset.culled === 'true') {
                    el.style.display = '';
                    delete el.dataset.culled;
                }
            });
            if (culled > 10) console.log('[Fire4ArkOS] Culled ' + culled + ' DOM elements');
        } catch (e) {}
    }
    
    window.addEventListener('scroll', () => { setTimeout(cullOffscreenElements, 100); }, { passive: true });
    setInterval(cullOffscreenElements, CULL_INTERVAL);
})();
"""
        (chrome_dir / "userContent.js").write_text(usercontent_js, encoding="utf-8")
        
        # Enable userContent.js in Firefox prefs
        prefs = prefs.replace(
            'user_pref("browser.startup.homepage", "about:blank");',
            'user_pref("browser.startup.homepage", "about:blank");\nuser_pref("userChrome.inContentToolbars.enabled", true);'
        )

        # In max performance mode, let Firefox run across all available CPU cores.
        taskset = self.which("taskset")
        if taskset and self.is_linux:
            cpu_count = max(1, os.cpu_count() or 1)
            cpu_set = os.environ.get("FIRE4ARKOS_CPUSET", "").strip()
            if not cpu_set:
                if self.is_rk3326 or not self.max_perf:
                    cpu_set = "0-1"
                else:
                    cpu_set = f"0-{cpu_count - 1}"
            nice_level = "-5" if self.max_perf and hasattr(os, "geteuid") and os.geteuid() == 0 else "0"
            cmd = [taskset, "-c", cpu_set, "nice", "-n", nice_level, firefox_bin]
        else:
            cmd = ["nice", "-n", "0", firefox_bin]
        cmd += [
            "--new-instance",
            "--no-remote",
            "-width", str(self.width),
            "-height", str(self.height),
            f"--profile={self.profile_dir}",
            self.initial_url,
        ]

        if not self.display:
            cmd.insert(cmd.index(firefox_bin) + 1, "--headless")

        self.log(f"Starting Firefox: {' '.join(cmd)}")
        try:
            self.firefox_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=sys.stderr,
                env=self.firefox_env(),
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )
            self.log(f"Firefox PID: {self.firefox_process.pid}")
            return True
        except Exception as exc:
            self.log(f"Error starting Firefox: {exc}")
            return False

    def xdotool_batch(self, *args):
        """Add command to batch instead of executing immediately."""
        if self.command_batcher and self.input_backend == "xdotool":
            self.command_batcher.add_command(*args)
    
    def normalize_key(self, key_name):
        mapping = {
            "Return": "Return",
            "Tab": "Tab",
            "BackSpace": "BackSpace",
            "Escape": "Escape",
            "space": "space",
        }
        return mapping.get(key_name, key_name)

    def stabilize_window(self):
        """Force Firefox window to be at (0,0), full size, and focused."""
        if self.input_backend != "xdotool":
            return
            
        try:
            # Find the main Firefox window(s)
            output = subprocess.check_output(
                ["xdotool", "search", "--class", "firefox"], 
                env=self.firefox_env(), 
                stderr=subprocess.DEVNULL
            ).decode().strip().split("\n")
            
            # Filter out empty or non-numeric results
            win_ids = [wid for wid in output if wid.isdigit()]
            
            if win_ids:
                # Check if the currently focused window is already one of ours
                try:
                    focused_win = subprocess.check_output(
                        ["xdotool", "getwindowfocus"], 
                        env=self.firefox_env(), 
                        stderr=subprocess.DEVNULL
                    ).decode().strip()
                    if focused_win in win_ids:
                        return focused_win
                except:
                    pass

                # Target the first one (usually the main window)
                win_id = win_ids[0]
                # Force position, size, and focus
                # windowmap, windowraise and windowfocus are critical for input routing
                subprocess.run([
                    "xdotool", 
                    "windowmap", win_id,
                    "windowmove", win_id, "0", "0",
                    "windowsize", win_id, str(self.width), str(self.height),
                    "windowraise", win_id,
                    "windowfocus", win_id
                ], env=self.firefox_env(), stderr=subprocess.DEVNULL)
                
                # Also ensure the root cursor isn't a cross, as it's distracting 
                # and indicates focus issues.
                subprocess.run(["xsetroot", "-cursor_name", "left_ptr"], 
                             env=self.firefox_env(), stderr=subprocess.DEVNULL)
                
                return win_id
        except Exception as e:
            self.debug(f"Stabilization error: {e}")
        return None

    def handle_command(self, cmd):
        if not cmd:
            return

        # Deduplicate rapid-fire mouse button events that might cause double-clicks
        if any(x in cmd for x in ("click", "mousedown", "mouseup")):
            now = time.monotonic()
            # If the same button action arrives within 150ms, ignore it as noise/chatter
            if hasattr(self, "_last_cmd_time") and self._last_cmd_time.get(cmd, 0) > now - 0.150:
                return
            if not hasattr(self, "_last_cmd_time"):
                self._last_cmd_time = {}
            self._last_cmd_time[cmd] = now

        # self.log(f"Command: {cmd}")  # Disabled for performance
        
        if cmd.startswith("load:"):
            url = cmd[5:]
            if self.input_backend == "xdotool" and self.command_batcher:
                self.command_batcher.add_command("key", "--clearmodifiers", "ctrl+l")
                self.command_batcher.add_command("type", "--delay", "0", url)
                # Use --clearmodifiers for reliability so modifier keys don't stick
                self.command_batcher.add_command("key", "--clearmodifiers", "Return")
        
        elif cmd.startswith("scroll:"):
            try:
                delta = int(cmd[7:])
            except ValueError:
                return
            button = "5" if delta > 0 else "4"
            for _ in range(min(abs(delta), 8)):
                self.xdotool_batch("click", button)
        
        elif cmd.startswith("click") or cmd.startswith("rightclick"):
            # Format: click:x,y or rightclick:x,y
            # CRITICAL: Flush any pending mousemove commands FIRST
            # This ensures stick movement doesn't interfere with click targeting
            if self.command_batcher:
                self.command_batcher.flush()
            
            # Use a SINGLE xdotool invocation for move+click — this is atomic.
            # Splitting into two batch commands risks an intervening mousemove
            # (from the motion batcher) firing between them, which dismisses menus.
            parts = cmd.split(":")
            button = "3" if "right" in cmd else "1"
            env = self.firefox_env()
            if len(parts) > 1:
                coords = parts[1].split(",")
                if len(coords) == 2:
                    # Scale coordinates if internal_scale > 1 (display space -> capture space)
                    x = str(int(int(coords[0]) / self.internal_scale))
                    y = str(int(int(coords[1]) / self.internal_scale))
                    subprocess.run(
                        ["xdotool", "mousemove", x, y, "click", button],
                        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=1.0
                    )
            else:
                subprocess.run(
                    ["xdotool", "click", button],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=1.0
                )

        elif cmd == "maximize":
            # Force window to fill Xvfb exactly
            subprocess.run([
                "xdotool", "search", "--class", "firefox", 
                "windowmove", "0", "0", "windowsize", str(self.width), str(self.height)
            ], env=self.firefox_env())
        
        elif cmd.startswith("mousedown:") or cmd.startswith("mouseup:") or cmd.startswith("rightmousedown:") or cmd.startswith("rightmouseup:"):
            # Parse command: "mousedown:x,y", "rightmousedown:x,y", etc.
            is_down = "down" in cmd
            is_right = "right" in cmd
            button = "3" if is_right else "1"  # Button 1 = left, 3 = right
            
            # Extract coordinates
            parts = cmd.split(":")
            if len(parts) == 2:
                coords = parts[1].split(",")
                if len(coords) == 2:
                    # Xvfb is always at full 640x480 - coordinates pass through directly
                    x = coords[0]
                    y = coords[1]
                    # Always move cursor to position first (needed for accurate drag start)
                    self.xdotool_batch("mousemove", x, y)
                    # Flush pending mousemove, then send mousedown/mouseup (must happen immediately after)
                    if self.command_batcher:
                        self.command_batcher.flush()
                    
                    # Send mousedown/mouseup as subprocess call (can't batch with movement)
                    try:
                        env = os.environ.copy()
                        if self.display:
                            env["DISPLAY"] = self.display
                        cmd_name = "mousedown" if is_down else "mouseup"
                        subprocess.run(["xdotool", cmd_name, "--button", button], 
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1.0)
                    except Exception as e:
                        self.log(f"mousedown/up error: {e}")

        elif cmd.startswith("mousemove:"):
            coords = cmd[10:].split(",")
            if len(coords) == 2:
                # Xvfb is always at full 640x480 - coordinates pass through directly
                x = coords[0]
                y = coords[1]
                self.xdotool_batch("mousemove", x, y)
        
        elif cmd == "zoom:in":
            self.xdotool_batch("key", "ctrl+plus")
        
        elif cmd == "zoom:out":
            self.xdotool_batch("key", "ctrl+minus")
        
        elif cmd == "back":
            self.xdotool_batch("key", "Alt_L+Left")
        
        elif cmd.startswith("resize:"):
            dims = cmd[7:]
            try:
                width, height = dims.split(",")
                if self.internal_scale <= 1:
                    self.width = max(320, int(width))
                    self.height = max(240, int(height))
                else:
                    self.debug(
                        f"ignoring resize {width}x{height} while internal scale is {self.internal_scale}x "
                        f"(capture remains {self.width}x{self.height})"
                    )
            except ValueError:
                return
        
        elif cmd.startswith("text:"):
            text = urllib.parse.unquote(cmd[5:])
            if text and self.input_backend == "xdotool" and self.command_batcher:
                self.debug(f"received text payload (len={len(text)})")
                self.command_batcher.add_command("type", "--delay", "0", text)
        
        elif cmd.startswith("key:"):
            key_name = self.normalize_key(cmd[4:])
            self.debug(f"sending key: {key_name}")
            if self.command_batcher:
                self.command_batcher.add_command("key", "--clearmodifiers", key_name)
            else:
                # Best-effort fallback
                self.xdotool_batch("key", "--clearmodifiers", key_name)

    def read_commands(self):
        fd = None
        try:
            if not os.path.exists(self.cmd_pipe):
                return

            fd = os.open(self.cmd_pipe, os.O_RDONLY | os.O_NONBLOCK)
            pending = ""
            while self.running:
                try:
                    chunk = os.read(fd, 4096)
                    if chunk:
                        pending += chunk.decode("utf-8", errors="ignore")
                        while "\n" in pending:
                            line, pending = pending.split("\n", 1)
                            self.handle_command(line.strip())
                except BlockingIOError:
                    pass
                except Exception as exc:
                    self.log(f"Command reader error: {exc}")
                
                # Periodically flush command batch (every 20ms or when idle)
                if self.command_batcher:
                    self.command_batcher.maybe_flush()
                
                time.sleep(0.006 if self.max_perf else 0.01)
        finally:
            # Final flush before closing
            if self.command_batcher:
                self.command_batcher.flush()
            if fd is not None:
                os.close(fd)

    def run_fbdir_stream(self):
        self.log("Starting Xvfb fbdir framebuffer stream...")

        for _ in range(50):
            if os.path.exists(XVFB_SCREEN_FILE) and os.path.getsize(XVFB_SCREEN_FILE) > 100:
                break
            time.sleep(0.1)
        else:
            self.log("Xvfb_screen0 not found; falling back to ffmpeg")
            self.capture_backend = "ffmpeg"
            return

        # Parse XWD header ONCE — reuse offsets for all subsequent frames
        layout = self._xwd_layout(XVFB_SCREEN_FILE)
        if layout is None:
            self.log("Could not parse XWD header; falling back to ffmpeg")
            self.capture_backend = "ffmpeg"
            return

        pixel_offset = layout["offset"]
        source_stride = layout["bytes_per_line"]
        source_height = layout["height"]
        row_bytes = layout["width"] * 4

        expected = self.width * self.height * 4
        full_size = pixel_offset + source_stride * source_height
        slack_bytes = 16384

        # Xvfb can lag a little behind the computed size; wait up to 10s and allow a small tail slack.
        for _ in range(100):
            if os.path.getsize(XVFB_SCREEN_FILE) + slack_bytes >= full_size:
                break
            time.sleep(0.1)

        actual_size = os.path.getsize(XVFB_SCREEN_FILE)
        self.log(f"XWD file size: {actual_size} bytes (need {full_size})")
        if actual_size + slack_bytes < full_size:
            self.log("XWD file too small; falling back to ffmpeg")
            self.capture_backend = "ffmpeg"
            return

        if actual_size <= pixel_offset:
            self.log("XWD file does not contain pixel data yet; falling back to ffmpeg")
            self.capture_backend = "ffmpeg"
            return

        # --- Try POSIX shared memory (zero-copy path) ---
        use_shm = False
        if self.is_linux:
            producer = ShmFrameProducer(self.shm_width, self.shm_height, logger=self.log)
            if producer.open():
                self.shm_producer = producer
                use_shm = True
                self.log("Using POSIX shared memory for framebuffer (zero-copy)")
            else:
                self.log("SHM unavailable; falling back to FIFO pipe")

        # Open FIFO pipe as fallback (or primary on non-Linux)
        fb_file = None
        if not use_shm:
            fb_file = open(self.fb_pipe, "wb")
            self.log("fb_pipe opened for writing — streaming frames (FIFO mode)")

        try:
            with open(XVFB_SCREEN_FILE, "rb") as xwd_file:
                with mmap.mmap(xwd_file.fileno(), actual_size, access=mmap.ACCESS_READ) as mm:
                    frames_sent = 0
                    no_change_count = 0
                    adaptive_sleep = FRAME_INTERVAL

                    # Pre-allocate reusable buffer for full capture (NO per-frame malloc)
                    full_expected = self.width * self.height * 4
                    reuse_buf = bytearray(full_expected)
                    # SHM output buffer (may be downsampled)
                    shm_expected = self.shm_width * self.shm_height * 4
                    shm_buf = bytearray(shm_expected)
                    scale = self.internal_scale
                    # Pre-compute row offsets once
                    src_offsets = [pixel_offset + (row * source_stride) for row in range(source_height)]
                    dest_offsets = [row * row_bytes for row in range(source_height)]
                    # For quick change detection: sample offset into pixel data
                    sample_end = min(256, full_expected)
                    last_sample = b""
                    
                    # Performance Telemetry
                    frame_latencies = []
                    loop_count = 0
                    
                    # Optimization: if stride == row_bytes, use single-slice read (no loop)
                    use_fast_path = (source_stride == row_bytes)
                    fast_src_start = pixel_offset
                    fast_src_end = pixel_offset + source_height * row_bytes
                    if use_fast_path:
                        self.log(f"Using fast single-slice mmap read (stride={source_stride} == row_bytes={row_bytes})")

                    while self.running and self.firefox_process and self.firefox_process.poll() is None:
                        loop_count += 1
                        frame_start_time = time.perf_counter()
                        try:
                            # Copy pixel data using pre-computed offsets (header parsed once)
                            capture_start = time.perf_counter()
                            if use_fast_path:
                                # FAST PATH: single contiguous slice (no Python loop!)
                                reuse_buf[:full_expected] = mm[fast_src_start:fast_src_end]
                            else:
                                # SLOW PATH: row-by-row for mismatched strides
                                for i in range(source_height):
                                    src_start = src_offsets[i]
                                    if src_start >= actual_size:
                                        break
                                    src_end = min(src_start + row_bytes, actual_size)
                                    dest_start = dest_offsets[i]
                                    chunk_len = src_end - src_start
                                    copy_len = min(chunk_len, row_bytes)
                                    reuse_buf[dest_start:dest_start + copy_len] = mm[src_start:src_start + copy_len]
                            capture_time = time.perf_counter() - capture_start

                            # Downsample to shm_width x shm_height if internal_scale > 1.
                            # Uses row/column stride skipping via slice assignment (C-speed, no pixel loop).
                            if scale > 1:
                                src_row_bytes = self.width * 4
                                dst_row_bytes = self.shm_width * 4
                                src_px = scale * 4  # bytes to advance per output pixel in source row
                                for dy in range(self.shm_height):
                                    src_row = reuse_buf[(dy * scale) * src_row_bytes : (dy * scale + 1) * src_row_bytes]
                                    dst_off = dy * dst_row_bytes
                                    # Take every scale-th pixel from the source row
                                    for dx in range(self.shm_width):
                                        shm_buf[dst_off + dx*4 : dst_off + dx*4 + 4] = src_row[dx * src_px : dx * src_px + 4]
                                out_buf = shm_buf
                            else:
                                out_buf = reuse_buf

                            # Quick change detection: compare first 256 bytes (no hash() overhead)
                            detect_start = time.perf_counter()
                            current_sample = bytes(reuse_buf[:sample_end])
                            frame_changed = current_sample != last_sample
                            detect_time = time.perf_counter() - detect_start

                            # SHM: write every frame (memcpy is near-free, sequence counter must update for reader)
                            # FIFO: write only on change (write+flush has kernel overhead)
                            write_start = time.perf_counter()
                            if use_shm:
                                self.shm_producer.write_frame(out_buf)
                                frames_sent += 1
                            elif frame_changed or no_change_count < 3:
                                fb_file.write(bytes(out_buf))
                                fb_file.flush()
                                frames_sent += 1
                            write_time = time.perf_counter() - write_start

                            if frame_changed:
                                no_change_count = 0
                                adaptive_sleep = 0.0 if self.no_sleep else (0.008 if use_shm else FRAME_INTERVAL)
                                last_sample = current_sample
                            else:
                                no_change_count += 1
                                if self.no_sleep:
                                    adaptive_sleep = 0.0
                                elif use_shm:
                                    adaptive_sleep = min(0.033, adaptive_sleep * 1.2)
                                elif no_change_count > 5:
                                    adaptive_sleep = min(0.05, FRAME_INTERVAL * 2)
                        except Exception as exc:
                            self.log(f"fbdir read error: {exc}")
                            break

                        sleep_start = time.perf_counter()
                        if adaptive_sleep > 0.0:
                            time.sleep(adaptive_sleep)
                        sleep_time = time.perf_counter() - sleep_start

                        total_time = time.perf_counter() - frame_start_time
                        frame_latencies.append((total_time, capture_time, detect_time, write_time, sleep_time))
                        if len(frame_latencies) > 100:
                            frame_latencies.pop(0)

                        if loop_count % 100 == 0 and frame_latencies:
                            avg_total = sum(t[0] for t in frame_latencies) / len(frame_latencies) * 1000
                            avg_capture = sum(t[1] for t in frame_latencies) / len(frame_latencies) * 1000
                            avg_detect = sum(t[2] for t in frame_latencies) / len(frame_latencies) * 1000
                            avg_write = sum(t[3] for t in frame_latencies) / len(frame_latencies) * 1000
                            avg_sleep = sum(t[4] for t in frame_latencies) / len(frame_latencies) * 1000
                            loop_fps = 1000.0 / avg_total if avg_total > 0 else 0
                            sys.stderr.write(
                                f"\r[PERF] LoopFPS:{loop_fps:5.1f} Total:{avg_total:5.1f}ms "
                                f"[Capture:{avg_capture:3.1f}ms Detect:{avg_detect:2.1f}ms Write:{avg_write:2.1f}ms Sleep:{avg_sleep:4.1f}ms] "
                                f"Frames:{frames_sent}\x1b[K"
                            )
                            sys.stderr.flush()

                    ff_rc = self.firefox_process.poll() if self.firefox_process else None
                    self.log(f"fbdir stream ended: frames={frames_sent} firefox_rc={ff_rc}")
        except Exception as exc:
            self.log(f"fbdir mmap/open failed: {exc}; falling back to ffmpeg")
            self.capture_backend = "ffmpeg"
        finally:
            if fb_file is not None:
                try:
                    fb_file.close()
                except Exception:
                    pass
            if self.shm_producer is not None:
                self.shm_producer.close()
                self.shm_producer = None

    def run_ffmpeg_stream(self):
        self.log("Starting ffmpeg x11grab stream...")
        proc = subprocess.Popen([
            "ffmpeg",
            "-loglevel", "warning",
            "-f", "x11grab",
            "-draw_mouse", "0",
            "-video_size", f"{self.width}x{self.height}",
            "-framerate", str(self.fps),
            "-i", f"{self.display}.0+0,0",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-pix_fmt", "bgra",
            "-f", "rawvideo",
            "-y", self.fb_pipe,
        ], stderr=sys.stderr)

        while self.running and self.firefox_process and self.firefox_process.poll() is None:
            time.sleep(1)
            if proc.poll() is not None:
                self.log("ffmpeg stream ended prematurely!")
                break
        self.terminate_process(proc)

    def run_frame_capture_stream(self):
        self.log("Starting frame-by-frame capture stream...")
        with open(self.fb_pipe, "wb") as fb_file:
            while self.running and self.firefox_process and self.firefox_process.poll() is None:
                if self.capture_backend == "import":
                    cmd = ["import", "-display", self.display, "-window", "root", "-depth", "8", "rgba:-"]
                    result = self.run_command(cmd)
                    expected = self.width * self.height * 4
                    frame = result.stdout if len(result.stdout) == expected else bytes([0x1A, 0x1A, 0x1A, 0xFF]) * (self.width * self.height)
                else:
                    frame = bytes([0x1A, 0x1A, 0x1A, 0xFF]) * (self.width * self.height)
                fb_file.write(frame)
                fb_file.flush()
                time.sleep(FRAME_INTERVAL)

    def generate_framebuffer(self):
        try:
            while self.running and self.firefox_process and self.firefox_process.poll() is None:
                if self.capture_backend == "fbdir":
                    self.run_fbdir_stream()
                    if self.running and self.firefox_process and self.firefox_process.poll() is None and self.capture_backend == "fbdir":
                        self.log("fbdir stream ended unexpectedly; retrying")
                        time.sleep(0.5)
                        continue
                if self.capture_backend == "ffmpeg":
                    self.run_ffmpeg_stream()
                elif self.capture_backend not in ("fbdir", "ffmpeg"):
                    self.run_frame_capture_stream()
                break
        except Exception as exc:
            self.log(f"Framebuffer stream error: {exc}")

    def terminate_process(self, process):
        if not process or process.poll() is not None:
            return
        try:
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def cleanup(self):
        self.log("Cleaning up")
        self.terminate_process(self.firefox_process)
        self.terminate_process(self.xvfb_process)
        self.firefox_process = None
        self.xvfb_process = None

        if self.profile_dir.exists():
            shutil.rmtree(self.profile_dir, ignore_errors=True)

        for pipe in [self.fb_pipe, self.cmd_pipe]:
            try:
                if os.path.exists(pipe):
                    os.remove(pipe)
            except Exception:
                pass
    
    def cleanup_cache(self):
        """Periodic cache cleanup: aggressive culling to prevent wear and crashes."""
        try:
            # Cleanup tmpfs (hot cache) - aggressive
            cache_dir = self.tmpfs_cache_dir
            if cache_dir.exists():
                total_size = sum(f.stat().st_size for f in cache_dir.rglob('*') if f.is_file())
                # If cache exceeds 300MB, clean up oldest 75% (keep only newest 25%)
                if total_size > 300 * 1024 * 1024:
                    files = sorted(
                        (f for f in cache_dir.rglob('*') if f.is_file()),
                        key=lambda f: f.stat().st_mtime
                    )
                    for f in files[:int(len(files) * 0.75)]:
                        try:
                            f.unlink()
                        except:
                            pass
                    self.log(f"Tmpfs cleanup: {total_size / 1024 / 1024:.1f}MB → {sum(f.stat().st_size for f in cache_dir.rglob('*') if f.is_file()) / 1024 / 1024:.1f}MB")
            
            # Cleanup disk cache (SD card) - very aggressive to reduce wear
            disk_cache_dirs = [
                self.disk_cache_dir,
                Path("/mnt/sdcard/firefox_cache"),
                Path("/tmp/firefox_cache_disk"),
                Path("/home/.cache/firefox"),
            ]
            
            for disk_cache_dir in disk_cache_dirs:
                if disk_cache_dir and disk_cache_dir.exists():
                    try:
                        total_size = sum(f.stat().st_size for f in disk_cache_dir.rglob('*') if f.is_file())
                        # If disk cache exceeds 150MB, delete oldest 90% (keep only newest 10%)
                        if total_size > 150 * 1024 * 1024:
                            files = sorted(
                                (f for f in disk_cache_dir.rglob('*') if f.is_file()),
                                key=lambda f: f.stat().st_mtime
                            )
                            deleted = 0
                            for f in files[:int(len(files) * 0.90)]:
                                try:
                                    f.unlink()
                                    deleted += 1
                                except:
                                    pass
                            if deleted > 0:
                                remaining = sum(f.stat().st_size for f in disk_cache_dir.rglob('*') if f.is_file()) if disk_cache_dir.exists() else 0
                                self.log(f"Disk cache cleanup: deleted {deleted} files → {remaining / 1024 / 1024:.1f}MB remaining")
                    except Exception as e:
                        self.log(f"Disk cache cleanup error: {e}")
        except Exception as e:
            self.log(f"Cache cleanup error: {e}")

    def run(self):
        def signal_handler(_sig, _frame):
            self.running = False
            # Don't call cleanup() here to avoid reentrant print() calls
            # The main loop will handle cleanup after firefox_process.wait() returns
            # or is interrupted by the same signal.

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        self.log("Firefox Framebuffer Wrapper v1.2 started (optimized with batching + cache management)")

        self.create_pipes()
        self.start_virtual_display()
        self.detect_backends()

        if not self.start_firefox():
            self.cleanup()
            return 1
        
        # Synchronous window focus at startup to fix input initialization race
        # (don't wait for async stabilizer thread)
        if self.input_backend == "xdotool":
            for _ in range(3):
                result = self.stabilize_window()
                if result:
                    self.log(f"Window focused synchronously: {result}")
                    break
                time.sleep(0.5)

        # Periodic cache cleanup thread
        def cleanup_worker():
            cleanup_interval = 300
            next_cleanup = time.time() + cleanup_interval
            while self.running:
                if time.time() >= next_cleanup:
                    self.cleanup_cache()
                    next_cleanup = time.time() + cleanup_interval
                time.sleep(10)
        
        cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        cleanup_thread.start()

        cmd_thread = threading.Thread(target=self.read_commands, daemon=True)
        fb_thread = threading.Thread(target=self.generate_framebuffer, daemon=True)
        cmd_thread.start()
        fb_thread.start()

        # Window stabilization thread: keep Firefox focused and filling the screen
        def stabilizer_worker():
            # Initial wait for Firefox to start
            time.sleep(5)
            while self.running:
                # Only stabilize if needed or less frequently to avoid closing menus
                self.stabilize_window()
                time.sleep(15) # Every 15 seconds is enough
        
        stab_thread = threading.Thread(target=stabilizer_worker, daemon=True)
        stab_thread.start()

        try:
            while self.running and self.firefox_process and self.firefox_process.poll() is None:
                try:
                    self.firefox_process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    continue
        except KeyboardInterrupt:
            pass

        self.running = False
        self.log("Firefox process ended or interrupted")
        self.cleanup()
        return 0


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    pipe_base = sys.argv[2] if len(sys.argv) > 2 else "fire4arkos"
    wrapper = FirefoxFramebufferWrapper(url, pipe_base)
    sys.exit(wrapper.run())
