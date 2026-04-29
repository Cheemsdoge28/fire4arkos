#!/usr/bin/env python3
"""
Firefox framebuffer wrapper for Fire4ArkOS.

Linux path:
- Launch Firefox in an Xvfb display when available
- Capture real pixels with a direct XShm helper process
- Inject navigation/text with xdotool when available

Fallback path:
- Launch Firefox headless and stream a placeholder frame
"""

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path


FRAME_MAGIC = 0xFB000001
FRAME_INTERVAL = 1.0 / float(os.environ.get("FPS", "12"))


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
        self.wrapper_dir = Path(__file__).resolve().parent
        self.profile_dir = Path(f"/tmp/firefox_profile_{os.getpid()}")
        self.capture_backend = "placeholder"
        self.input_backend = "noop"
        self.is_linux = os.name != "nt"
        self.capture_process = None

    def log(self, message):
        print(f"[{time.ctime()}] {message}", flush=True)

    def which(self, name):
        return shutil.which(name)

    def find_capture_helper(self):
        env_helper = os.environ.get("FIRE4ARKOS_XSHM_CAPTURE")
        if env_helper and os.path.exists(env_helper) and os.access(env_helper, os.X_OK):
            return env_helper

        candidates = [
            self.wrapper_dir / "xshm-capture",
            self.wrapper_dir.parent / "xshm-capture",
            Path.cwd() / "xshm-capture",
            Path("/usr/local/bin/xshm-capture"),
            Path("/opt/fire4arkos/xshm-capture"),
        ]

        for candidate in candidates:
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)

        return None

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

        self.display = ":99"
        cmd = [
            xvfb,
            self.display,
            "-screen",
            "0",
            f"{self.width}x{self.height}x24",
            "-nolisten",
            "tcp",
        ]
        self.log(f"Starting Xvfb: {' '.join(cmd)}")
        self.xvfb_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )

        for _ in range(20):
            if self.xvfb_process.poll() is not None:
                self.log("Xvfb exited early")
                self.xvfb_process = None
                return False
            time.sleep(0.10)

        return True

    def detect_backends(self):
        if not self.is_linux or not self.display:
            self.capture_backend = "placeholder"
            self.input_backend = "noop"
            return

        if self.find_capture_helper():
            self.capture_backend = "xshm"
        else:
            self.capture_backend = "placeholder"

        self.input_backend = "xdotool" if self.which("xdotool") else "noop"
        self.log(f"Capture backend: {self.capture_backend}")
        self.log(f"Input backend: {self.input_backend}")

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
user_pref("general.useragent.override", "Mozilla/5.0 (Android 13; Mobile; rv:115.0) Gecko/115.0 Firefox/115.0");
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

    def run_command(self, args):
        return subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            check=False,
            env=self.firefox_env(),
        )

    def xdotool(self, *args):
        if self.input_backend != "xdotool":
            return
        cmd = ["xdotool"] + list(args)
        self.run_command(cmd)

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

        self.log(f"Command: {cmd}")
        if cmd.startswith("load:"):
            url = cmd[5:]
            if self.input_backend == "xdotool":
                self.xdotool("search", "--sync", "--onlyvisible", "--class", "firefox", "windowactivate")
                self.xdotool("key", "--clearmodifiers", "ctrl+l")
                self.xdotool("type", "--delay", "0", url)
                self.xdotool("key", "Return")
        elif cmd.startswith("scroll:"):
            try:
                delta = int(cmd[7:])
            except ValueError:
                return
            button = "5" if delta > 0 else "4"
            for _ in range(min(abs(delta), 8)):
                self.xdotool("click", button)
        elif cmd.startswith("click"):
            if self.input_backend == "xdotool":
                if ":" in cmd:
                    coords = cmd.split(":")[1].split(",")
                    if len(coords) == 2:
                        self.xdotool("mousemove", coords[0], coords[1])
                else:
                    self.xdotool("mousemove", str(self.width // 2), str(self.height // 2))
                self.xdotool("click", "1")
        elif cmd.startswith("rightclick"):
            if self.input_backend == "xdotool":
                if ":" in cmd:
                    coords = cmd.split(":")[1].split(",")
                    if len(coords) == 2:
                        self.xdotool("mousemove", coords[0], coords[1])
                self.xdotool("click", "3")
        elif cmd.startswith("mousemove:"):
            if self.input_backend == "xdotool":
                coords = cmd[10:].split(",")
                if len(coords) == 2:
                    self.xdotool("mousemove", coords[0], coords[1])
        elif cmd == "zoom:in":
            if self.input_backend == "xdotool":
                self.xdotool("key", "ctrl+plus")
        elif cmd == "zoom:out":
            if self.input_backend == "xdotool":
                self.xdotool("key", "ctrl+minus")
        elif cmd == "back":
            self.xdotool("key", "Alt_L+Left")
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
            if text and self.input_backend == "xdotool":
                self.xdotool("type", "--delay", "0", text)
        elif cmd.startswith("key:"):
            key_name = self.normalize_key(cmd[4:])
            self.xdotool("key", key_name)

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
                time.sleep(0.01)
        finally:
            if fd is not None:
                os.close(fd)

    def run_xshm_stream(self, helper):
        self.log("Starting direct XShm framebuffer stream...")
        with open(self.fb_pipe, "wb") as fb_file:
            capture_proc = subprocess.Popen(
                [helper, self.display or ":99", str(self.width), str(self.height), str(self.fps)],
                stdout=fb_file,
                stderr=sys.stderr,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )
            self.capture_process = capture_proc

            while self.running and self.firefox_process and self.firefox_process.poll() is None:
                time.sleep(1)
                if capture_proc.poll() is not None:
                    self.log("XShm stream ended prematurely!")
                    break

            self.terminate_process(capture_proc)
            self.capture_process = None

    def run_placeholder_stream(self):
        self.log("Starting placeholder framebuffer stream...")
        placeholder_frame = bytes([0x1A, 0x1A, 0x1A, 0xFF]) * (self.width * self.height)
        with open(self.fb_pipe, "wb") as fb_file:
            while self.running and self.firefox_process and self.firefox_process.poll() is None:
                fb_file.write(placeholder_frame)
                fb_file.flush()
                time.sleep(FRAME_INTERVAL)

    def generate_framebuffer(self):
        try:
            if self.capture_backend == "xshm":
                helper = self.find_capture_helper()
                if not helper:
                    self.log("XShm capture helper not found; falling back to placeholder frames")
                    self.capture_backend = "placeholder"
                else:
                    self.run_xshm_stream(helper)
                    return

            self.run_placeholder_stream()
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
        self.terminate_process(self.capture_process)
        self.terminate_process(self.firefox_process)
        self.terminate_process(self.xvfb_process)
        self.firefox_process = None
        self.xvfb_process = None
        self.capture_process = None

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
