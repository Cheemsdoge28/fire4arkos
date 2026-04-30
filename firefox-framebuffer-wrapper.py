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
CLICK_DEBOUNCE = 0.25  # seconds: debounce rapid duplicate clicks


class CommandBatcher:
    """Batch xdotool commands to minimize subprocess spawning overhead."""
    
    def __init__(self, display_num=":99"):
        self.display_num = display_num
        self.batch = []
        self.last_flush_time = time.time()
        self.max_batch_size = 8  # Flush after 8 commands (more responsive)
        self.max_batch_age = 0.015  # or 15ms (faster responsiveness)
    
    def add_command(self, *args):
        """Add a command to the batch."""
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

            # Execute each queued xdotool subcommand separately to avoid
            # xdotool parsing ambiguities (e.g. option tokens being
            # interpreted as typed text when multiple subcommands are
            # concatenated). This preserves ordering and correctness.
            for args in self.batch:
                cmd = ["xdotool"] + list(args)
                try:
                    subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=0.5)
                except subprocess.TimeoutExpired:
                    print(f"Subcommand timeout: {' '.join(cmd)}", flush=True)
                except Exception as e:
                    print(f"Subcommand error ({' '.join(cmd)}): {e}", flush=True)

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
        self.width = 640
        self.height = 480
        self.fps = int(os.environ.get("FPS", "60"))
        self.display = os.environ.get("DISPLAY")
        self.profile_dir = Path(f"/tmp/firefox_profile_{os.getpid()}")
        self.capture_backend = "placeholder"
        self.input_backend = "noop"
        self.is_linux = os.name != "nt"
        self.last_pointer_signature = None
        self.last_pointer_time = 0.0
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
        base_cmd = [xvfb, display_num, "-screen", "0", f"{self.width}x{self.height}x24", "-nolisten", "tcp"]

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
        env["MOZ_ENABLE_WAYLAND"] = "0"
        env["MOZ_X11_EGL"] = "1"
        env["GTK_USE_PORTAL"] = "0"
        env["MOZ_FORCE_DISABLE_E10S"] = "0" # Ensure E10S is on (process separation)
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

        prefs = """user_pref("browser.startup.homepage", "about:blank");
user_pref("general.useragent.override", "Mozilla/5.0 (X11; Linux aarch64; rv:115.0) Gecko/20100101 Firefox/115.0");
user_pref("layout.css.devPixelsPerPx", "1.0");
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
user_pref("layers.acceleration.disabled", true);
user_pref("network.http.max-connections", 32);
user_pref("network.http.max-persistent-connections-per-server", 4);
user_pref("network.http.max-urgent-unused-idle-connections", 0);

/* Cache: RAM (hot) + disk (cold, with limits) */
user_pref("browser.cache.disk.enable", true);
user_pref("browser.cache.disk.capacity", 65536);
user_pref("browser.cache.memory.enable", true);
user_pref("browser.cache.memory.capacity", 32768);
user_pref("browser.cache.memory.max_entry_size", 2048);
user_pref("browser.cache.disk.max_entry_size", 4096);
user_pref("browser.sessionstore.max_tabs_undo", 0);
user_pref("browser.sessionstore.max_windows_undo", 0);

/* Keep localStorage/IndexedDB enabled - many modern sites require them */
user_pref("dom.storage.enabled", true);
user_pref("dom.indexedDB.enabled", true);
user_pref("dom.max_script_run_time", 10);
user_pref("dom.max_chrome_script_run_time", 10);

/* Reduce telemetry and background sync that cause writes */
user_pref("services.sync.enabled", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("app.update.enabled", false);

user_pref("media.mediasource.enabled", true);
user_pref("media.mediasource.vp9.enabled", true);
user_pref("media.autoplay.default", 5);
user_pref("media.autoplay.blocking_policy", 2);

/* Prevent CPU stall on heavy pages: limit content processes + GC tuning */
user_pref("dom.ipc.processCount", 1);
user_pref("dom.ipc.processCount.webIsolated", 1);
user_pref("dom.ipc.processCount.file", 1);
user_pref("browser.tabs.remote.autostart", true);
user_pref("javascript.options.mem.gc_incremental", true);
user_pref("javascript.options.mem.gc_per_zone", true);
user_pref("javascript.options.mem.gc_incremental_slice_ms", 15);
user_pref("javascript.options.mem.high_water_mark", 32);
user_pref("javascript.options.mem.max", 131072);
user_pref("dom.ipc.tabs.shutdownTimeoutSecs", 5);
user_pref("javascript.options.baselinejit", true);
user_pref("javascript.options.ion", false);
user_pref("image.mem.surfacecache.max_size_kb", 8192);
user_pref("image.mem.discardable", true);
user_pref("image.mem.decode_bytes_at_a_time", 1024);
user_pref("image.multithreaded_decoding.limit", 1);
user_pref("image.high_quality_upscaling.enabled", false);
user_pref("image.high_quality_downscaling.enabled", false);
user_pref("image.animation_mode", "none");
user_pref("gfx.canvas.accelerated", false);
user_pref("layers.offmainthreadcomposition.enabled", true);
user_pref("layers.async-pan-zoom.enabled", true);
user_pref("browser.low_commit_space_threshold_mb", 96);
user_pref("browser.sessionhistory.max_entries", 3);
user_pref("image.mem.min_discard_timeout_ms", 500);
user_pref("dom.image.lazy_loading.enabled", true);
user_pref("browser.tabs.max_memory_usage_mb", 112);
user_pref("dom.max_script_run_time", 3);
"""
        (self.profile_dir / "prefs.js").write_text(prefs, encoding="utf-8")
        
        # userChrome.css: performance-safe tweaks only (no layout breaking)
        chrome_dir = self.profile_dir / "chrome"
        chrome_dir.mkdir(exist_ok=True)
        
        userchrome_css = """
/* Performance: disable CSS animations/transitions in Firefox chrome UI */
* {
    animation-duration: 0s !important;
    transition-duration: 0s !important;
}
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
        contain-intrinsic-size: 1px 200px;
    }
    
    /* Constrain media elements to viewport size */
    video, iframe {
        max-height: 480px !important;
        max-width: 640px !important;
    }
    
    /* Hide some heavy dynamic sidebars on common sites */
    [aria-label="Trending"], [aside], .sidebar {
        display: none !important;
    }
}
"""
        (chrome_dir / "userContent.css").write_text(usercontent_css, encoding="utf-8")

        # Prepend 'nice -n 5' to prevent Firefox from starving the system during heavy loads
        cmd = [
            "nice", "-n", "5",
            firefox_bin,
            "--new-instance",
            "--no-remote",
            "-width", str(self.width),
            "-height", str(self.height),
            f"--profile={self.profile_dir}",
            self.initial_url,
        ]

        if not self.display:
            #Headless mode doesn't need 'nice' as much but we keep it for consistency
            cmd.insert(3, "--headless")

        self.log(f"Starting Firefox (niced): {' '.join(cmd)}")
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

    def handle_command(self, cmd):
        if not cmd:
            return

        # self.log(f"Command: {cmd}")  # Disabled for performance
        
        if cmd.startswith("load:"):
            url = cmd[5:]
            if self.input_backend == "xdotool" and self.command_batcher:
                self.command_batcher.add_command("search", "--sync", "--onlyvisible", "--class", "firefox", "windowactivate")
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
        
        elif cmd.startswith("click"):
            signature = cmd.strip()
            now = time.monotonic()
            if signature == self.last_pointer_signature and now - self.last_pointer_time < CLICK_DEBOUNCE:
                return
            self.last_pointer_signature = signature
            self.last_pointer_time = now
            
            if ":" in cmd:
                coords = cmd.split(":")[1].split(",")
                if len(coords) == 2:
                    self.xdotool_batch("mousemove", coords[0], coords[1])
            else:
                self.xdotool_batch("mousemove", str(self.width // 2), str(self.height // 2))
            
            if self.command_batcher:
                self.command_batcher.add_command("search", "--sync", "--onlyvisible", "--class", "firefox", "windowactivate")
                self.command_batcher.flush()
                time.sleep(0.01)

            # Click after pointer move has been issued
            self.xdotool_batch("click", "1")
        
        elif cmd.startswith("rightclick"):
            signature = cmd.strip()
            now = time.monotonic()
            if signature == self.last_pointer_signature and now - self.last_pointer_time < CLICK_DEBOUNCE:
                return
            self.last_pointer_signature = signature
            self.last_pointer_time = now
            
            if ":" in cmd:
                coords = cmd.split(":")[1].split(",")
                if len(coords) == 2:
                    self.xdotool_batch("mousemove", coords[0], coords[1])
            
            if self.command_batcher:
                self.command_batcher.add_command("search", "--sync", "--onlyvisible", "--class", "firefox", "windowactivate")
                self.command_batcher.flush()
                time.sleep(0.01)

            self.xdotool_batch("click", "3")
        
        elif cmd.startswith("mousemove:"):
            coords = cmd[10:].split(",")
            if len(coords) == 2:
                self.xdotool_batch("mousemove", coords[0], coords[1])
        
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
                self.width = max(320, int(width))
                self.height = max(240, int(height))
            except ValueError:
                return
        
        elif cmd.startswith("text:"):
            text = urllib.parse.unquote(cmd[5:])
            if text and self.input_backend == "xdotool" and self.command_batcher:
                # Activate Firefox window, flush to ensure activation, then type
                self.debug(f"received text payload (len={len(text)})")
                self.command_batcher.add_command("search", "--sync", "--onlyvisible", "--class", "firefox", "windowactivate")
                # Flush activation immediately and give X a tiny moment to focus
                self.command_batcher.flush()
                time.sleep(0.02)
                self.command_batcher.add_command("type", "--delay", "0", text)
                # Let batcher flush on its own cycle
        
        elif cmd.startswith("key:"):
            key_name = self.normalize_key(cmd[4:])
            # Activate window and clear modifiers before sending key events
            self.debug(f"sending key: {key_name}")
            if self.command_batcher:
                self.command_batcher.add_command("search", "--sync", "--onlyvisible", "--class", "firefox", "windowactivate")
                self.command_batcher.flush()
                time.sleep(0.02)
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
                
                time.sleep(0.01)
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
            producer = ShmFrameProducer(self.width, self.height, logger=self.log)
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

                    # Pre-allocate reusable buffer (NO per-frame malloc)
                    reuse_buf = bytearray(expected)
                    # Pre-compute row offsets once
                    src_offsets = [pixel_offset + (row * source_stride) for row in range(source_height)]
                    dest_offsets = [row * row_bytes for row in range(source_height)]
                    # For quick change detection: sample offset into pixel data
                    sample_end = min(256, expected)
                    last_sample = b""
                    # Optimization: if stride == row_bytes, use single-slice read (no loop)
                    use_fast_path = (source_stride == row_bytes)
                    fast_src_start = pixel_offset
                    fast_src_end = pixel_offset + source_height * row_bytes
                    if use_fast_path:
                        self.log(f"Using fast single-slice mmap read (stride={source_stride} == row_bytes={row_bytes})")

                    while self.running and self.firefox_process and self.firefox_process.poll() is None:
                        try:
                            # Copy pixel data using pre-computed offsets (header parsed once)
                            if use_fast_path:
                                # FAST PATH: single contiguous slice (no Python loop!)
                                reuse_buf[:expected] = mm[fast_src_start:fast_src_end]
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

                            # Quick change detection: compare first 256 bytes (no hash() overhead)
                            current_sample = bytes(reuse_buf[:sample_end])
                            frame_changed = current_sample != last_sample

                            # SHM path: ALWAYS write every frame (memcpy is near-free)
                            # FIFO path: gate on change detection (write+flush has kernel overhead)
                            if use_shm:
                                self.shm_producer.write_frame(reuse_buf)
                                frames_sent += 1
                            elif frame_changed or no_change_count < 3:
                                fb_file.write(bytes(reuse_buf))
                                fb_file.flush()
                                frames_sent += 1

                            if frame_changed:
                                no_change_count = 0
                                adaptive_sleep = FRAME_INTERVAL
                                last_sample = current_sample
                                if frames_sent % 60 == 1:
                                    self.log(f"Framebuffer: {frames_sent} frames sent ({'shm' if use_shm else 'fifo'})")
                            else:
                                no_change_count += 1
                                if no_change_count > 5 and not use_shm:
                                    # Only back off sleep for FIFO (SHM is cheap, keep pumping)
                                    adaptive_sleep = min(0.05, FRAME_INTERVAL * 2)
                        except Exception as exc:
                            self.log(f"fbdir read error: {exc}")
                            break

                        time.sleep(adaptive_sleep)

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
            self.cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        self.log("Firefox Framebuffer Wrapper v1.2 started (optimized with batching + cache management)")

        self.create_pipes()
        self.start_virtual_display()
        self.detect_backends()

        if not self.start_firefox():
            self.cleanup()
            return 1

        # Periodic cache cleanup thread
        def cleanup_worker():
            cleanup_interval = 300  # Every 5 minutes
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

        try:
            self.firefox_process.wait()
        except KeyboardInterrupt:
            pass

        self.running = False
        self.log("Firefox process ended")
        self.cleanup()
        return 0


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    pipe_base = sys.argv[2] if len(sys.argv) > 2 else "fire4arkos"
    wrapper = FirefoxFramebufferWrapper(url, pipe_base)
    sys.exit(wrapper.run())
