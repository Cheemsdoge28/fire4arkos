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
        self.proc = None
        self.start_process()

    def start_process(self):
        try:
            env = os.environ.copy()
            env["DISPLAY"] = self.display_num
            # Isolate xdotool from audio shims/preloads to prevent crashes
            env.pop("LD_PRELOAD", None)
            env.pop("LD_LIBRARY_PATH", None)
            # Capture stderr to see what xdotool is complaining about
            self.proc = subprocess.Popen(["xdotool", "-"], stdin=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                       env=env, bufsize=0, universal_newlines=True)
            
            # Start a thread to read stderr and log it
            def log_stderr(pipe, logger):
                for line in pipe:
                    logger(f"xdotool error: {line.strip()}")
            import threading
            threading.Thread(target=log_stderr, args=(self.proc.stderr, self.log_callback), daemon=True).start()
        except: pass

    def add_command(self, *args):
        if not self.proc or self.proc.poll() is not None: self.start_process()
        if self.proc and self.proc.stdin:
            try:
                cmd_line = " ".join(map(str, args))
                self.proc.stdin.write(cmd_line + "\n")
                self.proc.stdin.flush()
            except Exception as e:
                self.proc = None
    
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
        # Xvfb runs at scaled resolution for real CPU savings.
        # devPixelsPerPx tells Firefox to lay out as if it has more CSS pixels.
        self.width = max(1, self.display_width // self.internal_scale)
        self.height = max(1, self.display_height // self.internal_scale)
        self.fps = int(os.environ.get("FPS", "60"))
        self.max_perf = env_flag("FIRE4ARKOS_MAX_PERF", False)
        self.low_quality = env_flag("FIRE4ARKOS_LOW_QUALITY", True)
        self.no_sleep = env_flag("FIRE4ARKOS_NO_SLEEP", False)
        self.soc = os.environ.get("FIRE4ARKOS_SOC", "rk3326").lower()
        self.is_rk3326 = "rk3326" in self.soc
        self.display = os.environ.get("DISPLAY")
        self.root = Path(__file__).parent.absolute()
        # Use a local profile directory instead of /tmp to see if Firefox respects user.js better
        self.profile_dir = self.root / ".mozilla_profile"
        self.profile_dir.mkdir(parents=True, exist_ok=True)
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
        self.pulse_process = None  # PulseAudio daemon (started for Firefox audio)
        self.apulse_bin = None     # apulse binary path (preferred over PulseAudio daemon)

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
        # DPI MUST be 96 (standard). At 228 DPI, Firefox auto-calculates a high device
        # pixel ratio that overrides our devPixelsPerPx pref, causing the "zoomed in" look.
        # With DPI=96, Firefox's auto-detected ratio is 1.0, so our explicit
        # devPixelsPerPx="0.500" (at scale=2) takes effect cleanly.
        base_cmd = [xvfb, display_num, "-screen", "0", f"{self.width}x{self.height}x24",
                    "-nolisten", "tcp", "-dpi", "96", "-shmem"]

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
        
        # Force-kill pulseaudio and free the sound device
        try:
            subprocess.run(["pulseaudio", "--kill"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, timeout=2)
            # Use fuser to kick anything else off the sound card
            subprocess.run(["fuser", "-k", "/dev/snd/pcmC0D0p", "/dev/snd/controlC0"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, timeout=2)
            
            # Force RK817/Handheld mixer to Speakers and max volume
            subprocess.run(["amixer", "-c", "0", "sset", "Playback Path", "SPK"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            subprocess.run(["amixer", "-c", "0", "sset", "Playback", "100%"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        except: pass

        # If apulse is used, tell it which ALSA card to target.
        if self.apulse_bin:
            lib_path = None
            for p in ["/usr/lib/aarch64-linux-gnu/apulse", "/usr/lib/apulse", "/usr/lib/arm-linux-gnueabihf/apulse"]:
                if os.path.exists(os.path.join(p, "libpulse.so.0")) or os.path.exists(os.path.join(p, "libpulse.so")):
                    lib_path = p
                    break
            
            if lib_path:
                libs = [os.path.join(lib_path, l) for l in ["libpulse.so.0", "libpulse.so", "libpulse-simple.so.0", "libpulse-simple.so"] if os.path.exists(os.path.join(lib_path, l))]
                env["LD_PRELOAD"] = ":".join(libs)
                env["LD_LIBRARY_PATH"] = lib_path + (":" + env.get("LD_LIBRARY_PATH", "") if env.get("LD_LIBRARY_PATH") else "")
                env["LD_BIND_NOW"] = "1" 
                
                # plughw:0 is the most direct hardware path, bypassing pulse-tainted ALSA configs
                env["APULSE_PLAYBACK_DEVICE"] = "plughw:0"
                env["APULSE_LOG"] = "1"
                env["PULSE_PROP"] = "disable-shm=1"
                env["PULSE_LATENCY_MSEC"] = "200"
                env["PULSE_SERVER"] = "localhost" 
                env["PULSE_AUTOSPAWN"] = "0" # Block respawning during session
                
                # Refined Sandbox Disable - keep global sandbox but kill content/gmp
                env["MOZ_DISABLE_CONTENT_SANDBOX"] = "1"
                env["MOZ_DISABLE_GMP_SANDBOX"] = "1"
                env["MOZ_SANDBOX_LOGGING"] = "1"
                
                if not hasattr(self, '_logged_audio_routing'):
                    self.log(f"Audio: Hardened Fix active - plughw:0")
                    self._logged_audio_routing = True
            else:
                # Fallback to the wrapper script if we can't find the lib directly
                pass 
        env["FIRE4ARKOS_USER_AGENT"] = os.environ.get(
            "FIRE4ARKOS_USER_AGENT",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        env["FIRE4ARKOS_AUDIO_BACKEND"] = os.environ.get("FIRE4ARKOS_AUDIO_BACKEND", "auto")
        env["MOZ_ENABLE_WAYLAND"] = "0"
        env["MOZ_X11_EGL"] = os.environ.get("MOZ_X11_EGL", "1")
        env["GTK_USE_PORTAL"] = "0"
        env["MOZ_FORCE_DISABLE_E10S"] = "1"
        env["MOZ_DISABLE_CONTENT_SANDBOX"] = "1"
        env["MOZ_DISABLE_GMP_SANDBOX"] = "1"
        env["MOZ_SANDBOX_LOGGING"] = "1"
        # Use GLES2 for compositor — avoids full OpenGL driver stack on ARM
        env["MOZ_WEBRENDER"] = "0"        # WebRender needs a real GPU, disable for Xvfb
        env["MOZ_ACCELERATED"] = "0"      # No GPU acceleration in Xvfb
        env["LIBGL_ALWAYS_SOFTWARE"] = "0" # Allow driver to choose
        # Reduce GTK overhead
        env["GDK_BACKEND"] = "x11"
        env["GTK_OVERLAY_SCROLLING"] = "0"
        # Enable verbose cubeb audio debug logging to diagnose audio issues
        env["MOZ_LOG"] = "cubeb:5,raw:5,sync:5,sandbox:5"
        env["NSPR_LOG_MODULES"] = "cubeb:5,raw:5,sync:5,sandbox:5"
        
        # Let cubeb find PulseAudio (we start a daemon in start_firefox).
        # Remove any stale overrides that might block PulseAudio connection.
        env.pop("PULSE_SERVER", None)
        return env

    def ensure_pulseaudio(self):
        """Ensure Firefox can output audio.
        
        Firefox 78 ESR on ArkOS is compiled with PulseAudio as the ONLY cubeb
        backend. Without PulseAudio, cubeb fails and all audio is silent.
        
        Preferred order:
        1. apulse (LD_PRELOAD shim: PulseAudio API → ALSA, no daemon, ~zero overhead)
        2. PulseAudio daemon (full daemon, slight CPU/memory overhead)
        """
        if not self.is_linux:
            return
        
        # Prefer apulse — lightweight shim, no daemon needed
        apulse_bin = self.which("apulse")
        if apulse_bin and os.environ.get("FIRE4ARKOS_USE_APULSE", "1") == "1":
            self.apulse_bin = apulse_bin
            self.log(f"Audio: using apulse (ALSA direct, no daemon): {apulse_bin}")
            return
        
        # Check if PulseAudio is already running
        try:
            result = subprocess.run(
                ["pulseaudio", "--check"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=2
            )
            if result.returncode == 0:
                self.log("Audio: PulseAudio already running")
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        # Try to start PulseAudio daemon
        pulseaudio_bin = self.which("pulseaudio")
        if pulseaudio_bin:
            try:
                self.pulse_process = subprocess.Popen(
                    [pulseaudio_bin, "--start", "--exit-idle-time=-1",
                     "--log-level=error", "--disallow-exit"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                self.started_pulse_daemon = True
                self.log(f"Audio: started local PulseAudio daemon (PID {self.pulse_process.pid})")
                time.sleep(1.0) # Give it more time to initialize
                check = subprocess.run(
                    ["pulseaudio", "--check"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=2
                )
                if check.returncode == 0:
                    return
                else:
                    self.log("Audio: PulseAudio started but --check failed")
            except Exception as exc:
                self.log(f"Audio: failed to start PulseAudio: {exc}")
        
        self.log("WARNING: No apulse or PulseAudio — Firefox audio will not work!")
        self.log("Fix: sudo apt-get install apulse libasound2-plugins libasound2")

    def start_firefox(self):
        self.ensure_pulseaudio() # Must detect audio backend BEFORE generating prefs/env
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
        image_decode_threads = 1 if self.is_rk3326 else (2 if self.low_quality else 4)
        image_surfacecache = 8192 if self.low_quality else 16384
        image_decode_bytes = 1024 if self.low_quality else 4096
        image_downscale = "true" if self.low_quality else "false"
        session_history = 4 if self.is_rk3326 else 8
        tabs_max_mem = 256 if self.is_rk3326 else 384
        # When scaling, we want the UI to be slightly smaller than default to fit,
        # but NOT as small as (1/scale) which makes it unreadable at 320px.
        dev_pixels_per_px = 0.85 if self.internal_scale > 1 else 1.0
        user_agent_override = os.environ.get(
            "FIRE4ARKOS_USER_AGENT",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        audio_backend = os.environ.get("FIRE4ARKOS_AUDIO_BACKEND", "auto").strip().lower()
        # Firefox 78 on ArkOS only has PulseAudio compiled into cubeb.
        # When using apulse, we MUST tell Firefox to use the 'pulse' backend so the shim works.
        if self.apulse_bin:
            audio_backend_pref = 'user_pref("media.cubeb.backend", "pulse");\n'
            selected_audio_backend = "pulse (via apulse shim)"
        elif audio_backend in {"pulse", "jack", "sndio"}:
            audio_backend_pref = f'user_pref("media.cubeb.backend", "{audio_backend}");\n'
            selected_audio_backend = audio_backend
        else:
            # "auto" or "alsa" -> let cubeb use its default (pulse)
            audio_backend_pref = ""
            selected_audio_backend = "pulse (auto)"
            
        # Disable cubeb sandbox to ensure PulseAudio/apulse can communicate without permission issues
        audio_backend_pref += 'user_pref("media.cubeb.sandbox", false);\n'

        self.log(
            f"Scale config: display={self.display_width}x{self.display_height} "
            f"capture={self.width}x{self.height} internal_scale={self.internal_scale} "
            f"devPixelsPerPx={dev_pixels_per_px:.3f} audio_backend={selected_audio_backend}"
        )

        prefs = f"""user_pref("browser.startup.homepage", "about:blank");
user_pref("general.useragent.override", "{user_agent_override}");
user_pref("layout.css.devPixelsPerPx", "{dev_pixels_per_px:.3f}");
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
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

/* Max Level Perf: Disable accessibility and other heavy engines */
user_pref("accessibility.force_disabled", 1);
user_pref("browser.helperApps.deleteTempFileOnExit", true);
user_pref("browser.sessionstore.interval", 300000); /* 5 minutes - better safety than 1 hour */
user_pref("browser.sessionstore.max_tabs_undo", 2);
user_pref("browser.sessionstore.max_windows_undo", 1);
user_pref("browser.sessionhistory.max_entries", 5);

/* Cache: RAM (hot) + disk (cold, with limits) */
user_pref("browser.cache.disk.enable", true);
user_pref("browser.cache.disk.capacity", {disk_capacity});
user_pref("browser.cache.memory.enable", true);
user_pref("browser.cache.memory.capacity", {mem_capacity});
user_pref("browser.cache.memory.max_entry_size", {mem_max_entry});
user_pref("browser.cache.disk.max_entry_size", {disk_max_entry});

/* Disable gamepad/touch API to prevent double-handling */
user_pref("dom.gamepad.enabled", false);
user_pref("dom.w3c_touch_events.enabled", 0);
user_pref("dom.w3c_pointer_events.enabled", false);

/* Stability & Speed: Consolidated JIT Block */
user_pref("javascript.options.baselinejit", true);
user_pref("javascript.options.ion", true);
user_pref("javascript.options.asmjs", true);
user_pref("javascript.options.wasm", true);
user_pref("javascript.options.wasm_baselinejit", true);
user_pref("javascript.options.wasm_ionjit", true);
user_pref("dom.ipc.processCount", 1);
user_pref("dom.ipc.processCount.extension", 1);
user_pref("dom.ipc.processCount.webIsolated", 1);

/* Extreme Perf: Strip Firefox non-core features */
user_pref("extensions.pocket.enabled", false);
user_pref("reader.parse-on-load.enabled", false);
user_pref("browser.reader.detectedFirstRun", true);
user_pref("browser.safebrowsing.malware.enabled", false);
user_pref("browser.safebrowsing.phishing.enabled", false);
user_pref("browser.safebrowsing.downloads.enabled", false);
user_pref("browser.safebrowsing.downloads.remote.enabled", false);
user_pref("network.http.speculative-parallel-limit", 0);
user_pref("browser.pagethumbnails.capturing_disabled", true);

/* Reduce telemetry and background sync that cause writes */
user_pref("services.sync.enabled", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("app.update.enabled", false);
user_pref("browser.search.update", false);

/* Audio: default to Firefox's backend selection unless explicitly overridden.
   On some devices ALSA is preferred; on desktop Linux Pulse/PipeWire often works better. */
user_pref("media.cubeb.sandbox", false);
user_pref("security.sandbox.content.level", 0);
user_pref("security.sandbox.audio.main.enabled", false);
user_pref("media.sandbox.content.level", 0);
user_pref("media.audioipc.enabled", false);
user_pref("media.cubeb.backend", "pulse");
user_pref("media.cubeb.output_sample_rate", 48000);
user_pref("media.cubeb.output_latency_ms", 200);
user_pref("media.suspend-bkgnd-video.enabled", false);
user_pref("media.block-autoplay-until-in-foreground", false);
user_pref("media.volume_scale", "1.0");
user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 0);
user_pref("media.cubeb.logging", true);
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
user_pref("media.mediasource.vp9.enabled", true); /* Restored for Reddit/YouTube compatibility */
user_pref("media.mediasource.webm.enabled", true);
user_pref("media.mediasource.vp9.implicit.enabled", true);
user_pref("media.mediasource.av1.enabled", false);
user_pref("media.av1.enabled", false);
user_pref("media.ffmpeg.enabled", true);
user_pref("media.ffmpeg.vaapi.enabled", true);
user_pref("media.ffvpx.enabled", false);
/* Allow autoplay so media with sound can start without requiring manual permission. */
user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 0);
user_pref("media.memory_cache_max_size", 65536);
user_pref("media.cache_size", 524288);
user_pref("media.navigator.video.max_fps", {media_max_fps});
user_pref("media.video-max-decode-error", 0);
user_pref("layers.acceleration.disabled", false); /* Re-enable basic acceleration */
user_pref("layers.offmainthreadcomposition.enabled", true);
user_pref("gfx.webrender.all", false);
user_pref("gfx.webrender.software", true); /* Faster for RK3326 Mali than standard engine */
user_pref("image.mem.decode_on_draw", true);
user_pref("browser.tabs.remote.autostart", false); /* Save RAM by disabling multi-process for single-tab use */

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


/* Balanced reflow frequency (150ms instead of 1s) */
user_pref("content.notify.interval", 150000); 
user_pref("content.notify.ontimer", true);
user_pref("content.interrupt.parsing", true);
user_pref("content.switch.threshold", 150000);

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
        # Write user.js and make it read-only to prevent Firefox from ignoring it
        user_js = self.profile_dir / "user.js"
        if user_js.exists():
            os.chmod(user_js, 0o644)
        user_js.write_text(prefs, encoding="utf-8")
        os.chmod(user_js, 0o444)

        # Write userChrome.css to make the UI handheld-friendly (hide tabs, slim navbar)
        user_chrome = """
        /* Hide tab bar - saves vertical space */
        #TabsToolbar { visibility: collapse !important; }
        
        /* Slim down the nav bar and remove bulk */
        #nav-bar { 
            margin-top: -4px !important; 
            max-height: 34px !important; 
            border-top: none !important;
            padding: 0 !important;
        }
        
        #urlbar-container { 
            max-height: 30px !important; 
            margin-top: 0 !important;
        }
        
        .urlbar-input-box { font-size: 12px !important; }

        /* Hide non-essential icons to save horizontal width */
        #identity-box, 
        #tracking-protection-icon-container, 
        #pageActionButton, 
        #star-button-box, 
        #PanelUI-button,
        #alltabs-button,
        #tabbrowser-tabs { 
            display: none !important; 
        }

        #nav-bar-customization-target { padding-top: 0px !important; }
        
        /* Ensure the URL bar takes up as much space as possible */
        #urlbar {
            --urlbar-height: 28px !important;
            --urlbar-toolbar-height: 30px !important;
        }
        """

        chrome_dir = self.profile_dir / "chrome"
        chrome_dir.mkdir(exist_ok=True)
        (chrome_dir / "userChrome.css").write_text(user_chrome, encoding="utf-8")
        self.log("Injected Handheld userChrome.css for compact UI")
        
        # Handheld optimizations already written to userChrome.css above.
        
        # userContent.css: light performance hints that don't break layouts
        usercontent_css = """
        /* Custom web content styles */
        @-moz-document url-prefix() {
            /* Disable CSS animations on web content (saves CPU) */
            *, *::before, *::after {
                animation-duration: 0s !important;
                transition-duration: 0s !important;
            }
            
            /* Surgical DOM culling: skip rendering for off-screen posts/comments */
            article, section, .Post, .Comment, [role="article"] {
                contain: layout paint !important;
            }
            
            /* Constrain video height */
            video {
                max-height: 480px !important;
            }
        }
        """
        (chrome_dir / "userContent.css").write_text(usercontent_css, encoding="utf-8")
        
        # userContent.js: Viewport culling script for infinite-scroll sites (Reddit, Twitter, etc.)
        usercontent_js = (Path(__file__).parent / "firefox-viewport-culling.js").read_text(encoding="utf-8") \
                         if (Path(__file__).parent / "firefox-viewport-culling.js").exists() else """
(function() {
    'use strict';
    const VIEWPORT_HEIGHT = window.innerHeight;
    const CULL_THRESHOLD = VIEWPORT_HEIGHT * 2;
    let lastCullTime = 0;
    const CULL_INTERVAL = 5000;
    function cullOffscreenElements() {
        const now = performance.now();
        if (now - lastCullTime < CULL_INTERVAL) return;
        lastCullTime = now;
        try {
            const elements = document.querySelectorAll('div, article, section, li, p, img');
            let culled = 0;
            elements.forEach((el) => {
                if (!el || !el.offsetParent) return;
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
            if (culled > 10) console.log('[Fire4ArkOS] Culled ' + culled + ' elements');
        } catch (e) {}
    }
    window.addEventListener('scroll', () => { setTimeout(cullOffscreenElements, 100); }, { passive: true });
    setInterval(cullOffscreenElements, CULL_INTERVAL);
})();
"""
        (chrome_dir / "userContent.js").write_text(usercontent_js, encoding="utf-8")
        
        # Force policies via policies.json (applied before user.js and locks the preference)
        policies_dir = self.profile_dir / "distribution"
        policies_dir.mkdir(parents=True, exist_ok=True)
        policies_json = """{
  "policies": {
    "Preferences": {
      "media.cubeb.sandbox": { "Value": false, "Status": "locked" },
      "security.sandbox.content.level": { "Value": 0, "Status": "locked" },
      "media.audioipc.enabled": { "Value": false, "Status": "locked" },
      "media.cubeb.backend": { "Value": "pulse", "Status": "locked" }
    }
  }
}"""
        (policies_dir / "policies.json").write_text(policies_json, encoding="utf-8")
        
        # Enable userContent.js in Firefox prefs
        prefs = prefs.replace(
            'user_pref("browser.startup.homepage", "about:blank");',
            'user_pref("browser.startup.homepage", "about:blank");\nuser_pref("userChrome.inContentToolbars.enabled", true);'
        )

        # Ensure Firefox has an audio path (apulse or PulseAudio daemon)
        self.ensure_pulseaudio()

        # In max performance mode, let Firefox run across all available CPU cores.
        taskset = self.which("taskset")
        if taskset and self.is_linux:
            cpu_count = max(1, os.cpu_count() or 1)
            cpu_set = os.environ.get("FIRE4ARKOS_CPUSET", "").strip()
            if not cpu_set:
                if self.is_rk3326:
                    cpu_set = "0-2" # Use 3 cores, leave 1 for wrapper/system
                elif not self.max_perf:
                    cpu_set = "0-1"
                else:
                    cpu_set = f"0-{cpu_count - 1}"
            nice_level = "-5" if self.max_perf and hasattr(os, "geteuid") and os.geteuid() == 0 else "0"
            # apulse is now handled via manual LD_PRELOAD in firefox_env()
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
        env = self.firefox_env()
        # Audit critical audio variables
        audio_env = {k: v for k, v in env.items() if "PULSE" in k or "ALSA" in k or "MOZ_LOG" in k}
        self.log(f"Audio Environment Audit: {audio_env}")
        
        try:
            # Redirect both stdout and stderr to a log file to capture crashes/errors
            self.firefox_log = open("/tmp/fire4arkos_firefox.log", "w")
            self.firefox_process = subprocess.Popen(
                cmd,
                stdout=self.firefox_log,
                stderr=subprocess.STDOUT,
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

    def find_firefox_window(self):
        """Find the main Firefox window(s), cache it, and stabilize once."""
        if self.input_backend != "xdotool":
            return None
            
        # If we have a cached ID, check if it's still valid
        if hasattr(self, "_cached_win_id") and self._cached_win_id:
            try:
                subprocess.check_output(["xdotool", "getwindowname", self._cached_win_id], 
                                      env=self.firefox_env(), stderr=subprocess.DEVNULL)
                return self._cached_win_id
            except:
                self._cached_win_id = None

        try:
            # Search for visible firefox windows
            output = subprocess.check_output(
                ["xdotool", "search", "--onlyvisible", "--class", "firefox"], 
                env=self.firefox_env(), 
                stderr=subprocess.DEVNULL
            ).decode().strip().split("\n")
            
            win_ids = [wid for wid in output if wid.isdigit()]
            if win_ids:
                win_id = win_ids[0]
                # Stabilize ONCE per discovery to avoid focus fighting
                self.log(f"New window discovered: {win_id}. Stabilizing position/size.")
                subprocess.run([
                    "xdotool", 
                    "windowmap", win_id,
                    "windowmove", win_id, "0", "0",
                    "windowsize", win_id, str(self.width), str(self.height),
                    "windowraise", win_id,
                    "windowfocus", win_id
                ], env=self.firefox_env(), stderr=subprocess.DEVNULL)
                
                # Set root cursor just once
                subprocess.run(["xsetroot", "-cursor_name", "left_ptr"], 
                             env=self.firefox_env(), stderr=subprocess.DEVNULL)
                
                self._cached_win_id = win_id
                return win_id
        except Exception as e:
            self.debug(f"Window search error: {e}")
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

        # Enhanced logging for input debugging
        if cmd.startswith("text:") or cmd.startswith("key:"):
            self.log(f"Input Command: {cmd}")
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
            parts = cmd.split(":")
            button = "3" if "right" in cmd else "1"
            win_id = self.find_firefox_window()
            if len(parts) > 1:
                coords = parts[1].split(",")
                if len(coords) == 2:
                    x, y = coords[0], coords[1]
                    if win_id:
                        # Targeted relative click for absolute precision
                        self.xdotool_batch("mousemove", "--window", win_id, x, y)
                        self.xdotool_batch("click", "--window", win_id, button)
                    else:
                        self.xdotool_batch("mousemove", x, y)
                        self.xdotool_batch("click", button)
            else:
                if win_id:
                    self.xdotool_batch("click", "--window", win_id, button)
                else:
                    self.xdotool_batch("click", button)

        elif cmd.startswith("mousedown:") or cmd.startswith("mouseup:") or cmd.startswith("rightmousedown:") or cmd.startswith("rightmouseup:"):
            is_down = "down" in cmd
            is_right = "right" in cmd
            button = "3" if is_right else "1"
            win_id = self.find_firefox_window()
            
            parts = cmd.split(":")
            if len(parts) == 2:
                coords = parts[1].split(",")
                if len(coords) == 2:
                    x, y = coords[0], coords[1]
                    cmd_name = "mousedown" if is_down else "mouseup"
                    if win_id:
                        self.xdotool_batch("mousemove", "--window", win_id, x, y)
                        self.xdotool_batch(cmd_name, "--window", win_id, button)
                    else:
                        self.xdotool_batch("mousemove", x, y)
                        self.xdotool_batch(cmd_name, "--button", button)

        elif cmd.startswith("mousemove:"):
            coords = cmd[10:].split(",")
            if len(coords) == 2:
                x = coords[0]
                y = coords[1]
                win_id = self.find_firefox_window()
                if win_id:
                    self.xdotool_batch("mousemove", "--window", win_id, x, y)
                else:
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
                # Use cached window ID for silent injection
                win_id = self.find_firefox_window()
                if win_id:
                    self.command_batcher.add_command("type", "--window", win_id, "--clearmodifiers", "--delay", "200", text)
                else:
                    self.command_batcher.add_command("type", "--clearmodifiers", "--delay", "200", text)
        
        elif cmd.startswith("key:"):
            key_name = self.normalize_key(cmd[4:])
            self.debug(f"sending key: {key_name}")
            if self.command_batcher:
                win_id = self.find_firefox_window()
                if win_id:
                    self.command_batcher.add_command("key", "--window", win_id, "--clearmodifiers", key_name)
                else:
                    self.command_batcher.add_command("key", "--clearmodifiers", key_name)
            else:
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
                    # Collapsing logic: if we have multiple mousemoves in the queue,
                    # only process the latest one to save CPU.
                    chunk = os.read(fd, 4096)
                    if chunk:
                        pending += chunk.decode("utf-8", errors="ignore")
                        # Pre-process: collapse multiple mousemove commands
                        lines = pending.split("\n")
                        if len(lines) > 2:
                            # --- New High-Precision Collapse Logic ---
                            # Goal: If a click/drag is in the buffer, discard all moves before it.
                            # If multiple moves exist, only keep the latest one.
                            
                            processed_lines = []
                            last_mouse = None
                            
                            # 1. Identify if we have an 'atomic' event (click/mousedown/mouseup/key)
                            # We work backwards from the last complete line
                            important_idx = -1
                            for i in range(len(lines) - 2, -1, -1):
                                l = lines[i]
                                if any(x in l for x in ("click", "mousedown", "mouseup", "key:", "scroll:")):
                                    important_idx = i
                                    break
                            
                            # 2. If we found an important event, discard moves before it to prevent 'springing'
                            start_idx = 0
                            if important_idx != -1:
                                start_idx = important_idx
                                
                            # 3. Process remaining lines with latest-only mouse logic
                            for i in range(start_idx, len(lines) - 1):
                                line = lines[i]
                                if line.startswith("mousemove:"):
                                    last_mouse = line
                                else:
                                    if last_mouse:
                                        processed_lines.append(last_mouse)
                                        last_mouse = None
                                    processed_lines.append(line)
                            
                            if last_mouse:
                                processed_lines.append(last_mouse)
                                
                            pending = "\n".join(processed_lines) + "\n" + lines[-1]
                            
                        while "\n" in pending:
                            line, pending = pending.split("\n", 1)
                            self.handle_command(line.strip())
                except BlockingIOError:
                    pass
                except Exception as exc:
                    self.log(f"Command reader error: {exc}")
                
                time.sleep(0.006 if self.max_perf else 0.01)
        finally:
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
                            capture_time = time.perf_counter() - capture_start

                            # Quick change detection: compare first 256 bytes (no hash() overhead)
                            detect_start = time.perf_counter()
                            current_sample = bytes(reuse_buf[:sample_end])
                            frame_changed = current_sample != last_sample
                            detect_time = time.perf_counter() - detect_start

                            # SHM: write every frame (memcpy is near-free, sequence counter must update for reader)
                            # FIFO: write only on change (write+flush has kernel overhead)
                            write_start = time.perf_counter()
                            if use_shm:
                                self.shm_producer.write_frame(reuse_buf)
                                frames_sent += 1
                            elif frame_changed or no_change_count < 3:
                                fb_file.write(bytes(reuse_buf))
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
        if hasattr(self, "firefox_log") and self.firefox_log:
            try:
                self.firefox_log.close()
            except:
                pass

        # KEEP profile for debugging if it exists
        # if self.profile_dir.exists():
        #     shutil.rmtree(self.profile_dir, ignore_errors=True)

        for pipe in [self.fb_pipe, self.cmd_pipe]:
            try:
                if os.path.exists(pipe):
                    os.remove(pipe)
            except Exception:
                pass

        if hasattr(self, 'started_pulse_daemon') and self.started_pulse_daemon:
            self.log("Stopping local PulseAudio daemon...")
            try:
                subprocess.run(["pulseaudio", "--kill"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as exc:
                self.log(f"Warning: could not kill PulseAudio: {exc}")
    
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
                result = self.find_firefox_window()
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
        rc = self.firefox_process.poll() if self.firefox_process else "unknown"
        self.log(f"Firefox process ended or interrupted (rc={rc})")
        
        if rc is not None and rc != 0:
            # Check kernel log for Segfaults/OOMs
            try:
                dmesg = subprocess.run(["dmesg", "|", "tail", "-n", "10"], 
                                     capture_output=True, text=True, shell=True)
                if dmesg.stdout:
                    self.log("Recent kernel messages:")
                    for line in dmesg.stdout.splitlines():
                        if "firefox" in line.lower() or "segfault" in line.lower() or "oom" in line.lower():
                            self.log(f"  [KERNEL] {line}")
            except:
                pass

        self.cleanup()
        return 0


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    pipe_base = sys.argv[2] if len(sys.argv) > 2 else "fire4arkos"
    wrapper = FirefoxFramebufferWrapper(url, pipe_base)
    sys.exit(wrapper.run())
