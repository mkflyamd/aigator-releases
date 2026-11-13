import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from sandbox import wire

RELAY = Path(__file__).resolve().parents[2] / "web" / "sandbox" / "relay.py"

_SERVER_SOURCE = '''
import os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self):
        if self.path == "/hang":
            time.sleep(60)
        if self.path == "/slow":
            time.sleep(0.3)
        body = b"x" * (8 * 1024 * 1024) if self.path == "/big" else b"hello from dev server"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


mode, port = sys.argv[1], int(sys.argv[2])
if mode == "print-only":
    print("  Local:   http://localhost:%d/" % port, flush=True)
    time.sleep(120)
else:
    server = ThreadingHTTPServer(("127.0.0.1", port), H)
    server.daemon_threads = True
    print("  Local:   http://localhost:%d/" % port, flush=True)
    if mode == "exit3":
        threading.Timer(1.0, lambda: os._exit(3)).start()
    server.serve_forever()
'''


def write_server(folder) -> Path:
    path = Path(folder) / "dev_server.py"
    path.write_text(_SERVER_SOURCE, encoding="utf-8")
    return path


def start_relay(argv):
    return subprocess.Popen(
        [sys.executable, "-X", "utf8", str(RELAY)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={**os.environ, "AIGATOR_RELAY_COMMAND": json.dumps(argv)},
    )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(pred, timeout=10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return bool(pred())


def http_get(port, path="/", timeout=15):
    with socket.create_connection(("127.0.0.1", port), timeout) as s:
        s.sendall(f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode())
        chunks = []
        while True:
            try:
                data = s.recv(65536)
            except ConnectionResetError:
                break
            if not data:
                break
            chunks.append(data)
    head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
    return head, body


class RelayClient:
    def __init__(self, argv):
        self.proc = start_relay(argv)
        self.frames = queue.Queue()
        self._decoder = wire.Decoder()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                data = wire.read_some(self.proc.stdout, 65536)
                if not data:
                    break
                for frame in self._decoder.feed(data):
                    self.frames.put(frame)
        except (OSError, ValueError):
            pass
        finally:
            self.frames.put(None)

    def send(self, kind, conn, payload=b""):
        self.proc.stdin.write(wire.encode(kind, conn, payload))
        self.proc.stdin.flush()

    def collect(self, until, timeout=15):
        seen = []
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise AssertionError(f"timed out; frames so far: {seen}")
            try:
                frame = self.frames.get(timeout=left)
            except queue.Empty:
                continue
            if frame is None:
                self.frames.put(None)
                return seen
            seen.append(frame)
            if until(seen):
                return seen

    def close(self):
        # Closing stdin makes the relay kill its child; killing the relay alone
        # would orphan the dev server on Windows.
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(10)
