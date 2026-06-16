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
from pathlib import Path

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
        .then(d => { if (d.ready) window.location.replace('http://localhost:8000'); })
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
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > max_bytes:
        backup = LOG_FILE.with_suffix(".1.log")
        backup.unlink(missing_ok=True)
        LOG_FILE.rename(backup)


def _start() -> bool:
    global _proc
    if _running():
        return False
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _rotate_log()
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    _proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=str(ROOT),
        creationflags=flags,
        stdout=open(LOG_FILE, "a"),
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
            self._json({"running": _running(), "pid": _proc.pid if _running() else None})
        elif self.path == "/ready":
            import urllib.request as _req
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


_httpd = None

def _shutdown_server():
    time.sleep(0.5)
    if _httpd:
        _httpd.shutdown()

if __name__ == "__main__":
    print("Starting main server...")
    _start()
    print("Watchdog listening on http://localhost:8001")
    print("Main app on     http://localhost:8000")
    print("Press Ctrl+C to stop everything.\n")
    try:
        _httpd = HTTPServer(("0.0.0.0", 8001), Handler)
        _httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
        _stop()
