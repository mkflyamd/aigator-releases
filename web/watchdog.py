"""Watchdog process — manages the uvicorn server on port 8000.

Runs on port 8001. Keeps running even when the main server is stopped,
allowing the UI to start/stop/restart the main server via fetch calls.

Usage: python3 web/watchdog.py
"""

import json
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """One thread per request so a slow or aborted connection (e.g. a browser
    closing a /ready poll mid-response) can never wedge the whole server.
    The single-threaded HTTPServer would stall every other endpoint when one
    request hung — which left the loading page polling a dead /ready forever."""
    daemon_threads = True

ROOT = Path(__file__).parent.parent
if sys.platform == "win32":
    _LOG_DIR = Path.home() / "AppData" / "Local" / "AIGator" / "logs"
elif sys.platform == "darwin":
    _LOG_DIR = Path.home() / "Library" / "Logs" / "AIGator"
else:
    _LOG_DIR = Path.home() / ".local" / "state" / "AIGator" / "logs"
LOG_FILE = _LOG_DIR / "aigator.log"
_proc = None

LOADING_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AI Gator — Starting...</title>
  <meta http-equiv="refresh" content="6;url=/go">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0a0f1a;
      color: #e2e8f0;
      font-family: system-ui, -apple-system, sans-serif;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100vh;
      gap: 28px;
    }
    .logo { font-size: 96px; display: inline-block; animation: chomp 0.8s ease-in-out infinite alternate; }
    @keyframes chomp {
      from { transform: scaleY(1) rotate(-5deg); }
      to   { transform: scaleY(0.8) rotate(5deg); }
    }
    .title { font-size: 28px; font-weight: 700; color: #4ade80; letter-spacing: -0.5px; }
    .msg { font-size: 15px; color: #94a3b8; min-height: 22px; transition: opacity 0.4s; }
    .bar { width: 320px; height: 4px; background: #1e293b; border-radius: 2px; overflow: hidden; }
    .fill {
      height: 100%;
      background: linear-gradient(90deg, #4ade80, #22d3ee);
      border-radius: 2px;
      animation: pulse-bar 2s ease-in-out infinite;
    }
    @keyframes pulse-bar {
      0%   { width: 20%; margin-left: 0%; }
      50%  { width: 60%; margin-left: 20%; }
      100% { width: 20%; margin-left: 60%; }
    }
    .trouble { font-size: 13px; color: #475569; display: none; }
    .trouble a { color: #4ade80; cursor: pointer; text-decoration: underline; }
  </style>
</head>
<body>
  <div class="logo">🐊</div>
  <div class="title">AI Gator</div>
  <div class="msg" id="msg">Waking up the gator...</div>
  <div class="bar"><div class="fill"></div></div>
  <div class="trouble" id="trouble">
    Taking longer than usual &mdash;
    <a onclick="window.location.reload()">retry</a> or check the Developer Console in the tray menu.
  </div>
  <script>
    const msgs = [
      "Waking up the gator...",
      "Sharpening those teeth...",
      "Loading your workspace tools...",
      "Connecting to Microsoft 365...",
      "Almost ready to chomp..."
    ];
    let i = 0;
    const el = document.getElementById('msg');
    setInterval(() => {
      el.style.opacity = '0';
      setTimeout(() => {
        i = (i + 1) % msgs.length;
        el.textContent = msgs[i];
        el.style.opacity = '1';
      }, 400);
    }, 2200);
    setTimeout(() => {
      document.getElementById('trouble').style.display = 'block';
    }, 30000);
    function poll() {
      fetch('/ready')
        .then(r => r.json())
        .then(d => {
          if (d.ready) { window.location.replace('http://localhost:8000'); return; }
          if (d.error) {
            document.getElementById('msg').textContent = '⚠️ ' + d.error;
            document.getElementById('msg').style.color = '#f87171';
            document.getElementById('trouble').style.display = 'block';
          }
        })
        .catch(() => {});
    }
    setInterval(poll, 500);
    setTimeout(poll, 5000);
  </script>
</body>
</html>"""


def _running() -> bool:
    return _proc is not None and _proc.poll() is None


def _rotate_log():
    max_bytes = 5 * 1024 * 1024  # 5 MB
    if not (LOG_FILE.exists() and LOG_FILE.stat().st_size > max_bytes):
        return
    backup = LOG_FILE.with_suffix(".1.log")
    backup.unlink(missing_ok=True)
    try:
        LOG_FILE.rename(backup)
    except OSError:
        # On Windows, rename fails if another process holds the file open
        # (WinError 32). Fall back to copy+truncate which works on open handles.
        import shutil
        try:
            shutil.copy2(LOG_FILE, backup)
            LOG_FILE.write_bytes(b"")
        except OSError:
            pass  # rotation is best-effort; never block startup


def _port_in_use(port: int) -> bool:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        result = s.connect_ex(("127.0.0.1", port))
        s.close()
        return result == 0
    except OSError:
        return False


def _free_port(port: int):
    """Kill whatever process is listening on port (best-effort, silent)."""
    try:
        if sys.platform == "win32":
            r = subprocess.run(
                'netstat -ano', capture_output=True, text=True, shell=True
            )
            for line in r.stdout.splitlines():
                if f':{port}' in line and 'LISTEN' in line:
                    pid = line.strip().split()[-1]
                    subprocess.run(
                        f'taskkill /PID {pid} /F',
                        shell=True, capture_output=True
                    )
        else:
            # macOS / Linux: lsof prints PIDs owning the port, kill them
            r = subprocess.run(
                ['lsof', '-ti', f':{port}'],
                capture_output=True, text=True
            )
            for pid in r.stdout.split():
                subprocess.run(['kill', '-9', pid.strip()], capture_output=True)
    except Exception:
        pass


def _preflight() -> tuple[bool, str]:
    """Check startup preconditions. Auto-recovers where possible.
    Returns (ok, user_friendly_error_message)."""
    # Check port 8000 — auto-kill if occupied, wait, then check again
    if _port_in_use(8000):
        _free_port(8000)
        time.sleep(1.5)  # give OS time to release the socket
        if _port_in_use(8000):
            return False, (
                "AI Gator couldn't start because something else is using its port. "
                "Try restarting your computer. If the problem persists, contact support."
            )
    # Check log dir is writable
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        test = LOG_FILE.parent / ".write_test"
        test.write_text("x")
        test.unlink()
    except OSError as e:
        return False, (
            f"AI Gator could not write to its log folder. "
            f"Try running as your normal user account, or contact support. (Detail: {e})"
        )
    return True, ""


_startup_error: str = ""


def _start() -> bool:
    global _proc, _startup_error
    if _running():
        return False
    ok, err = _preflight()
    if not ok:
        _startup_error = err
        return False
    _startup_error = ""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    try:
        _rotate_log()
    except Exception:
        pass
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        log_fh = open(LOG_FILE, "a")
    except OSError:
        log_fh = subprocess.DEVNULL
    _proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=str(ROOT),
        creationflags=flags,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    return True


def _stop() -> bool:
    global _proc
    if not _running():
        return False
    _proc.terminate()
    try:
        _proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _proc.kill()
    return True


def _restart() -> bool:
    _stop()
    time.sleep(1)
    return _start()


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/status":
            self._json({"running": _running(), "pid": _proc.pid if _running() else None,
                        "error": _startup_error or None})
        elif self.path == "/ready":
            import urllib.request as _req
            if _startup_error:
                self._json({"ready": False, "error": _startup_error})
                return
            try:
                _req.urlopen("http://localhost:8000/health", timeout=1)
                self._json({"ready": True})
            except Exception:
                self._json({"ready": False})
        elif self.path == "/go":
            import urllib.request as _req
            try:
                _req.urlopen("http://localhost:8000/health", timeout=1)
                self.send_response(302)
                self.send_header("Location", "http://localhost:8000")
                self.end_headers()
            except Exception:
                self.send_response(302)
                self.send_header("Location", "/loading")
                self.end_headers()
        elif self.path == "/loading":
            body = LOADING_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/start":
            ok = _start()
            self._json({"ok": ok or _running()})
        elif self.path == "/stop":
            self._json({"ok": _stop()})
        elif self.path == "/restart":
            self._json({"ok": _restart()})
        elif self.path == "/quit":
            self._json({"ok": True})
            _stop()
            import threading
            threading.Thread(target=_shutdown_server, daemon=True).start()
        else:
            self._json({"error": "not found"}, 404)

    def _json(self, data: dict, code: int = 200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # suppress request logs

    def handle_one_request(self):
        # Browsers routinely abort /ready and /status polls mid-response; that
        # raises ConnectionAbortedError/BrokenPipe deep in the handler and the
        # default server prints a full traceback. Swallow those — they're noise.
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True


_httpd = None

def _shutdown_server():
    time.sleep(0.5)
    if _httpd:
        _httpd.shutdown()

def _crash_report(exc: BaseException) -> Path:
    """Write a crash report to %TEMP% and return the path."""
    import traceback, tempfile
    ts = time.strftime("%Y%m%d-%H%M%S")
    p = Path(tempfile.gettempdir()) / f"aigator-crash-{ts}.log"
    try:
        p.write_text(
            f"AI Gator watchdog crash — {ts}\n\n"
            + traceback.format_exc(),
            encoding="utf-8",
        )
    except OSError:
        pass
    return p


def _show_crash_dialog(path: Path, exc: BaseException):
    msg = (
        f"AI Gator failed to start.\n\n"
        f"Error: {exc}\n\n"
        f"Crash log: {path}\n\n"
        f"Please send the crash log to support."
    )
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "AI Gator — Startup Error", 0x10)
            return
        except Exception:
            pass
    print(msg, file=sys.stderr)


if __name__ == "__main__":
    try:
        print("Starting main server...")
        _start()
        print("Watchdog listening on http://localhost:8001")
        print("Main app on     http://localhost:8000")
        print("Press Ctrl+C to stop everything.\n")
        try:
            _httpd = ThreadingHTTPServer(("0.0.0.0", 8001), Handler)
            _httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping...")
            _stop()
    except Exception as exc:
        path = _crash_report(exc)
        _show_crash_dialog(path, exc)
        sys.exit(1)
