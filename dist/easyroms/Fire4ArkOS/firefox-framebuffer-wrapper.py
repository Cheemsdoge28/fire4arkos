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


FRAME_INTERVAL = 1.0 / float(os.environ.get("FPS", "12"))
XVFB_FBDIR = "/tmp"
XVFB_SCREEN_FILE = "/tmp/Xvfb_screen0"


class CommandBatcher:
    """Batch xdotool commands to minimize subprocess spawning overhead."""
    
    def __init__(self, display_num=":99"):
        self.display_num = display_num
        self.batch = []
        self.last_flush_time = time.time()
        self.max_batch_size = 10  # Flush after 10 commands
        self.max_batch_age = 0.02  # or 20ms
    
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
            # Build a single xdotool command with all batched operations
            cmd = ["xdotool"]
            env = os.environ.copy()
            env["DISPLAY"] = self.display_num
            
            for args in self.batch:
                cmd.extend(args)
            
            subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1.0)
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
        self.fps = int(os.environ.get("FPS", "12"))
        self.display = os.environ.get("DISPLAY")
        self.profile_dir = Path(f"/tmp/firefox_profile_{os.getpid()}")
        self.capture_backend = "placeholder"
        self.input_backend = "noop"
        self.is_linux = os.name != "nt"
        self.last_pointer_signature = None
        self.last_pointer_time = 0.0
        self.command_batcher = None  # Will be initialized after display is ready

    def log(self, message):
        print(f"[{time.ctime()}] {message}", flush=True)

    def which(self, name):
        return shutil.which(name)

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

    def _xwd_pixel_offset(self, path):
        """Return byte offset of raw pixel data in an XWD file, or None on failure."""
        try:
            with open(path, "rb") as f:
                raw = f.read(100)
            if len(raw) < 100:
                return None
            for endian in ("<", ">"):
                fields = struct.unpack(f"{endian}25I", raw)
                header_size, depth, width, height, ncolors = (
                    fields[0], fields[3], fields[4], fields[5], fields[20]
                )
                if 1 <= depth <= 32 and 1 <= width <= 4096 and 1 <= height <= 4096 and 100 <= header_size <= 65536:
                    offset = header_size + ncolors * 12
                    self.log(f"XWD: {width}x{height} depth={depth} pixel_offset={offset}")
                    return offset
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
            self.log(f"Input backend: xdotool (batched, high-performance)")
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
        env.setdefault("MOZ_ENABLE_WAYLAND", "0")
        return env

    def start_firefox(self):
        firefox_bin = self.find_firefox()
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        prefs = """user_pref("browser.startup.homepage", "about:blank");
user_pref("general.useragent.override", "Mozilla/5.0 (X11; Linux aarch64; rv:115.0) Gecko/20100101 Firefox/115.0");
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
user_pref("gfx.webrender.all", false);
user_pref("network.http.speculative-parallel-limit", 0);
user_pref("network.dns.disablePrefetch", true);
user_pref("browser.cache.disk.enable", false);
user_pref("browser.cache.memory.enable", true);
user_pref("browser.cache.memory.capacity", 131072);
user_pref("media.mediasource.enabled", true);
user_pref("media.mediasource.vp9.enabled", true);
user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 0);
"""
        (self.profile_dir / "prefs.js").write_text(prefs, encoding="utf-8")

        cmd = [
            firefox_bin,
            "--new-instance",
            "--no-remote",
            "-width", str(self.width),
            "-height", str(self.height),
            f"--profile={self.profile_dir}",
            self.initial_url,
        ]

        if not self.display:
            cmd.insert(1, "--headless")

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
                self.command_batcher.add_command("key", "Return")
        
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
            if signature == self.last_pointer_signature and now - self.last_pointer_time < 0.15:
                return
            self.last_pointer_signature = signature
            self.last_pointer_time = now
            
            if ":" in cmd:
                coords = cmd.split(":")[1].split(",")
                if len(coords) == 2:
                    self.xdotool_batch("mousemove", coords[0], coords[1])
            else:
                self.xdotool_batch("mousemove", str(self.width // 2), str(self.height // 2))
            
            self.xdotool_batch("click", "1")
        
        elif cmd.startswith("rightclick"):
            signature = cmd.strip()
            now = time.monotonic()
            if signature == self.last_pointer_signature and now - self.last_pointer_time < 0.15:
                return
            self.last_pointer_signature = signature
            self.last_pointer_time = now
            
            if ":" in cmd:
                coords = cmd.split(":")[1].split(",")
                if len(coords) == 2:
                    self.xdotool_batch("mousemove", coords[0], coords[1])
            
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
                self.command_batcher.add_command("type", "--delay", "0", text)
        
        elif cmd.startswith("key:"):
            key_name = self.normalize_key(cmd[4:])
            self.xdotool_batch("key", key_name)

    def read_commands(self):
        fd = None
        try:
            if not os.path.exists(self.cmd_pipe):
                return

            fd = os.open(self.cmd_pipe, os.O_RDONLY | os.O_NONBLOCK)
            pending = ""
            last_flush = time.time()
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

        pixel_offset = self._xwd_pixel_offset(XVFB_SCREEN_FILE)
        if pixel_offset is None:
            self.log("Could not parse XWD header; falling back to ffmpeg")
            self.capture_backend = "ffmpeg"
            return

        expected = self.width * self.height * 4
        full_size = pixel_offset + expected

        # Xvfb pre-allocates the full framebuffer file; wait up to 10s for it
        for _ in range(100):
            if os.path.getsize(XVFB_SCREEN_FILE) >= full_size:
                break
            time.sleep(0.1)

        actual_size = os.path.getsize(XVFB_SCREEN_FILE)
        self.log(f"XWD file size: {actual_size} bytes (need {full_size})")
        if actual_size < full_size:
            self.log("XWD file too small; falling back to ffmpeg")
            self.capture_backend = "ffmpeg"
            return

        with open(self.fb_pipe, "wb") as fb_file:
            self.log("fb_pipe opened for writing — streaming frames")
            try:
                with open(XVFB_SCREEN_FILE, "rb") as xwd_file:
                    with mmap.mmap(xwd_file.fileno(), full_size, access=mmap.ACCESS_READ) as mm:
                        frames_sent = 0
                        while self.running and self.firefox_process and self.firefox_process.poll() is None:
                            try:
                                data = mm[pixel_offset:pixel_offset + expected]
                                if len(data) == expected:
                                    fb_file.write(data)
                                    fb_file.flush()
                                    frames_sent += 1
                                    if frames_sent == 1 or frames_sent % 60 == 0:
                                        self.log(f"Framebuffer: {frames_sent} frames sent to pipe")
                            except Exception as exc:
                                self.log(f"fbdir read error: {exc}")
                                break
                            time.sleep(FRAME_INTERVAL)
                        ff_rc = self.firefox_process.poll() if self.firefox_process else None
                        self.log(f"fbdir stream ended: frames={frames_sent} firefox_rc={ff_rc}")
            except Exception as exc:
                self.log(f"fbdir mmap/open failed: {exc}; falling back to ffmpeg")
                self.capture_backend = "ffmpeg"

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
            if self.capture_backend == "fbdir":
                self.run_fbdir_stream()
            if self.capture_backend == "ffmpeg":
                self.run_ffmpeg_stream()
            elif self.capture_backend not in ("fbdir", "ffmpeg"):
                self.run_frame_capture_stream()
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

    def run(self):
        def signal_handler(_sig, _frame):
            self.running = False
            self.cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        self.log("Firefox Framebuffer Wrapper v1.1 started")

        self.create_pipes()
        self.start_virtual_display()
        self.detect_backends()

        if not self.start_firefox():
            self.cleanup()
            return 1

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
