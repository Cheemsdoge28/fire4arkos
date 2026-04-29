#!/usr/bin/env python3
"""
Firefox framebuffer wrapper for Fire4ArkOS.

Linux path:
- Launch Firefox in an Xvfb display when available
- Capture real pixels with ffmpeg or ImageMagick import
- Inject navigation/text with xdotool when available

Fallback path:
- Launch Firefox headless and stream a placeholder frame
"""

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


FRAME_MAGIC = 0xFB000001
FRAME_INTERVAL = 0.10


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
        self.display = os.environ.get("DISPLAY")
        self.profile_dir = Path(f"/tmp/firefox_profile_{os.getpid()}")
        self.capture_backend = "placeholder"
        self.input_backend = "noop"
        self.is_linux = os.name != "nt"

    def log(self, message):
        print(f"[{time.ctime()}] {message}", flush=True)

    def which(self, name):
        return shutil.which(name)

    def create_pipes(self):
        for pipe in [self.fb_pipe, self.cmd_pipe]:
            try:
                if os.path.exists(pipe):
                    os.remove(pipe)
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

        if self.which("ffmpeg"):
            self.capture_backend = "ffmpeg"
        elif self.which("import"):
            self.capture_backend = "import"
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
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.tabs.closeWindowWithLastTab", false);
"""
        (self.profile_dir / "prefs.js").write_text(prefs, encoding="utf-8")

        cmd = [
            firefox_bin,
            "--new-instance",
            "--no-remote",
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
        elif cmd == "click":
            if self.input_backend == "xdotool":
                self.xdotool("mousemove", str(self.width // 2), str(self.height // 2))
                self.xdotool("click", "1")
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

    def capture_rgba_frame(self):
        if self.capture_backend == "ffmpeg":
            cmd = [
                "ffmpeg",
                "-loglevel",
                "error",
                "-f",
                "x11grab",
                "-video_size",
                f"{self.width}x{self.height}",
                "-i",
                f"{self.display}.0+0,0",
                "-frames:v",
                "1",
                "-pix_fmt",
                "rgba",
                "-f",
                "rawvideo",
                "-",
            ]
            result = self.run_command(cmd)
            expected = self.width * self.height * 4
            if len(result.stdout) == expected:
                return result.stdout

        if self.capture_backend == "import":
            cmd = [
                "import",
                "-display",
                self.display,
                "-window",
                "root",
                "-depth",
                "8",
                "rgba:-",
            ]
            result = self.run_command(cmd)
            expected = self.width * self.height * 4
            if len(result.stdout) == expected:
                return result.stdout

        return bytes([0x1A, 0x1A, 0x1A, 0xFF]) * (self.width * self.height)

    def generate_framebuffer(self):
        try:
            with open(self.fb_pipe, "wb") as fb_file:
                while self.running and self.firefox_process and self.firefox_process.poll() is None:
                    frame = self.capture_rgba_frame()
                    fb_file.write(struct.pack("<III", FRAME_MAGIC, self.width, self.height))
                    fb_file.write(frame)
                    fb_file.flush()
                    time.sleep(FRAME_INTERVAL)
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
