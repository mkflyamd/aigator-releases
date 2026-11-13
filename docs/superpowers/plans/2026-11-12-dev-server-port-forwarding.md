# Dev Server Port Forwarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user preview a long-lived local dev server (for example `npm run dev` for a Slidev deck) while the server stays inside the Windows AppContainer sandbox, by forwarding one localhost port to it.

**Architecture:** One long-lived Python relay runs inside the sandbox as the parent of the dev server (same process tree, same Job Object), and talks to AI Gator over its stdin/stdout pipes using a small framed protocol. In the backend, a `ForwardedProcess` owns an asyncio listener on `127.0.0.1` and turns each browser connection into `OPEN`/`DATA`/`CLOSE` frames. `run_shell(background=true)` gains a sandboxed path that goes through the existing approval card, then starts the relay through a new streaming launcher.

**Tech Stack:** Python 3.12/3.13 stdlib (`asyncio`, `struct`, `socket`, `threading`), `ctypes` Windows AppContainer launcher (existing), FastAPI routes (existing), vanilla JS in `web/static`, pytest (`asyncio_mode = auto`), node-based JS tests.

Spec: `docs/superpowers/specs/2026-11-12-dev-server-port-forwarding-design.md`

## Global Constraints

- Windows only in v1. `run_shell(background=true)` is allowed while the sandbox is on, and always runs sandboxed. Foreground commands are unchanged. On other platforms, and when the sandbox is off, background commands behave as today.
- The forwarding listener binds `127.0.0.1` only, and uses the same port number as the dev server when that is free, otherwise a free port.
- One port: v1 forwards the first localhost port the server prints.
- Existing cap of 10 background processes.
- At most 64 open forwarded connections per process.
- Max payload 64 KB.
- `policy.require_sandbox` is satisfied because the run is sandboxed.
- Unattended runs are refused for `background=true`.
- The Job Object has kill-on-close; no pid file for sandboxed processes.
- No new telemetry fields; reuse `sandbox.telemetry_record`, with no command, paths or output.
- Out of scope: more than one forwarded port per process, macOS and Linux, static build preview, a UI to choose the port.
- Project rules (CLAUDE.md): the project is called **AI Gator**, never a POC. Do not add `Co-Authored-By` lines to commit messages. The only fake credential in tests, examples and docs is `aigator-fake-api-key`. Every new POST/PUT/PATCH/DELETE route uses `dependencies=[Depends(verify_csrf)]` from `web/security.py`, and nothing is added to `tests/csrf_route_baseline.txt`. All LLM calls go through `llm.gateway` (this feature makes none). Email, Teams and Slack messages never auto-send.
- Frontend rule: in `web/static/app.js`, do not add top-level `const`s that are read during startup (use function-local regexes); keep `tests/startup_const_order.test.js` passing. No `innerHTML`, no inline `on*=` handlers.

---

## Deviations from the spec (decided during planning)

- `SandboxProcess` exposes fd-backed binary `stdin`/`stdout` (via `msvcrt.open_osfhandle`).
- The Node runtime copy folder is `<folder>-<mtime>-<hash8>` (not `<name>-<version>`) with a 1 GB size cap.
- `_bg_sandbox_supported()` is a small seam in the shell tool so tests can run on any OS.
- `url` in the tool result and card is `http://127.0.0.1:<listen_port>` (the listener binds 127.0.0.1 only).
- A background run always shows an approval card (it ignores task and saved coverage) and never offers "Always".
- `relay.py` and `wire.py` are installed to `~/.gator/sandbox/relay/` in all modes (source and frozen); the command goes to the relay in the `AIGATOR_RELAY_COMMAND` env var as JSON.
- Stop is graceful first (close the relay's stdin, the relay kills its child), then the Job Object is terminated.
- Port detection scans complete lines only; a running process with no url still gets a status card (`url: None`).
- `app.js` gets one shared `_postBackgroundStop(pid)` used by the status card and `agents-pane.js`.
- Unreadable runtime paths are dropped and replaced by readable copies for background runs.
- The EXIT payload is a signed 64-bit int (`!q`).

## File structure

| File | Change | Responsibility |
|---|---|---|
| `web/sandbox/wire.py` | create | Frame encode/decode shared by relay and forwarder (stdlib only) |
| `web/sandbox/relay.py` | create | Runs in the sandbox: starts the command, pumps output as LOG, carries loopback connections |
| `web/sandbox/forward.py` | create | Backend: `ForwardedProcess`, port detection, asyncio listener |
| `web/sandbox/runtime_copy.py` | create | Readable copies of tool folders the container cannot read; installs the relay |
| `web/sandbox/launcher_windows.py` | modify | Held-grant bookkeeping, `_prepare`/`_finish`, streaming `_run_contained`, `SandboxProcess`, `start`, `readable_or_grantable` |
| `web/sandbox/__init__.py` | modify | `start_sandboxed`, `container_readable` |
| `web/sandbox/approvals.py` | modify | `background` flag on requests |
| `web/skills/shell_runner/tools.py` | modify | Gate, `_start_background`, stop guard, orphan check, tool text |
| `web/routes/tasks.py`, `tests/csrf_route_baseline.txt` | modify | Stop route CSRF + 404; list route `url` |
| `web/agent_loop.py` | modify | `dev_server` event and two SSE forwarders |
| `web/static/app.js`, `web/static/agents-pane.js` | modify | Card line, status card, CSRF stop |
| `packaging/aigator-backend.spec`, `docs/BUILD_INSTRUCTIONS.md`, `docs/security/threatmodel-remediation.md` | modify | Frozen build files and docs |
| `tests/code_sandbox/*`, `tests/shell_runner/*`, `tests/*.test.js` | create/modify | Tests per task |

Test commands: Python `python -m pytest <path> -v` (from the worktree root; `pythonpath = web .`). JS `node tests/<name>.test.js`.

---

### Task 1: Wire format

**Files:**
- Create: `web/sandbox/wire.py`
- Test: `tests/code_sandbox/test_wire.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `wire.OPEN, DATA, CLOSE, LOG, EXIT` (ints 1..5), `wire.MAX_PAYLOAD`, `wire.HEADER_SIZE`, `wire.WireError(ValueError)`, `wire.encode(kind, conn, payload=b"") -> bytes`, `wire.Decoder().feed(data) -> list[tuple[int, int, bytes]]`, `wire.open_payload(port)`, `wire.parse_open(payload) -> int`, `wire.exit_payload(code)`, `wire.parse_exit(payload) -> int`, `wire.read_some(stream, n) -> bytes`.

- [ ] **Step 1: Write the failing test**

Create `tests/code_sandbox/test_wire.py`:

```python
import struct

import pytest

from sandbox import wire


def test_round_trip():
    data = wire.encode(wire.DATA, 7, b"hello") + wire.encode(wire.CLOSE, 7)
    frames = wire.Decoder().feed(data)
    assert frames == [(wire.DATA, 7, b"hello"), (wire.CLOSE, 7, b"")]


def test_frame_split_across_reads():
    data = wire.encode(wire.LOG, 0, b"abcdef")
    decoder = wire.Decoder()
    out = []
    for i in range(len(data)):
        out += decoder.feed(data[i:i + 1])
    assert out == [(wire.LOG, 0, b"abcdef")]


def test_oversized_payload_rejected_on_encode():
    with pytest.raises(wire.WireError):
        wire.encode(wire.DATA, 1, b"x" * (wire.MAX_PAYLOAD + 1))


def test_oversized_length_rejected_on_decode():
    bad = struct.pack("!BII", wire.DATA, 1, wire.MAX_PAYLOAD + 1)
    with pytest.raises(wire.WireError):
        wire.Decoder().feed(bad)


def test_unknown_kind_rejected():
    with pytest.raises(wire.WireError):
        wire.Decoder().feed(struct.pack("!BII", 99, 0, 0))
    with pytest.raises(wire.WireError):
        wire.encode(99, 0)


def test_open_and_exit_payloads():
    assert wire.parse_open(wire.open_payload(3030)) == 3030
    assert wire.parse_exit(wire.exit_payload(-9)) == -9
    assert wire.parse_exit(wire.exit_payload(3)) == 3
    with pytest.raises(wire.WireError):
        wire.parse_open(b"x")
    with pytest.raises(wire.WireError):
        wire.parse_exit(b"")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/code_sandbox/test_wire.py -v`
Expected: FAIL with `ImportError: cannot import name 'wire' from 'sandbox'`.

- [ ] **Step 3: Write minimal implementation**

Create `web/sandbox/wire.py`:

```python
"""Frame format shared by the in-sandbox relay and the backend forwarder.

Stdlib only: relay.py imports this file from the sandbox, so it must not
depend on anything else in AI Gator.

Frame: !BII (kind, connection id, payload length) then the payload.
"""
from __future__ import annotations

import struct

OPEN, DATA, CLOSE, LOG, EXIT = 1, 2, 3, 4, 5
_KINDS = frozenset((OPEN, DATA, CLOSE, LOG, EXIT))
MAX_PAYLOAD = 64 * 1024
_HEADER = struct.Struct("!BII")
HEADER_SIZE = _HEADER.size


class WireError(ValueError):
    pass


def encode(kind: int, conn: int, payload: bytes = b"") -> bytes:
    if kind not in _KINDS:
        raise WireError(f"unknown frame kind {kind}")
    if len(payload) > MAX_PAYLOAD:
        raise WireError("payload too large")
    return _HEADER.pack(kind, conn, len(payload)) + bytes(payload)


class Decoder:
    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, int, bytes]]:
        buf = self._buf
        buf += data
        frames = []
        while len(buf) >= HEADER_SIZE:
            kind, conn, length = _HEADER.unpack_from(buf)
            if kind not in _KINDS:
                raise WireError(f"unknown frame kind {kind}")
            if length > MAX_PAYLOAD:
                raise WireError("payload too large")
            end = HEADER_SIZE + length
            if len(buf) < end:
                break
            frames.append((kind, conn, bytes(buf[HEADER_SIZE:end])))
            del buf[:end]
        return frames


def open_payload(port: int) -> bytes:
    return struct.pack("!H", port)


def parse_open(payload: bytes) -> int:
    if len(payload) != 2:
        raise WireError("bad OPEN payload")
    return struct.unpack("!H", payload)[0]


def exit_payload(code: int) -> bytes:
    return struct.pack("!q", code)


def parse_exit(payload: bytes) -> int:
    if len(payload) != 8:
        raise WireError("bad EXIT payload")
    return struct.unpack("!q", payload)[0]


def read_some(stream, n: int) -> bytes:
    """Whatever is available (at most n bytes) without waiting to fill n; b"" at EOF."""
    return (getattr(stream, "read1", None) or stream.read)(n)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/code_sandbox/test_wire.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/wire.py tests/code_sandbox/test_wire.py
git commit -m "feat: add the relay wire format"
```

### Task 2: Relay (runs in the sandbox) and test support

**Files:**
- Create: `web/sandbox/relay.py`
- Create: `tests/code_sandbox/relay_support.py`
- Test: `tests/code_sandbox/test_relay.py`

**Interfaces:**
- Consumes: Task 1 `wire`.
- Produces: `relay.py` script contract: env var `AIGATOR_RELAY_COMMAND` (JSON argv list); stdin/stdout carry wire frames; stdout LOG frames (conn 0) carry the child's merged output; one EXIT frame when the child ends; stdin EOF kills the child and ends the relay with code 0; a malformed frame ends it with code 2. Test helpers in `relay_support`: `RELAY` (Path), `start_relay(argv) -> Popen`, `free_port() -> int`, `wait_for(pred, timeout=10) -> bool`, `http_get(port, path="/", timeout=15) -> (head: bytes, body: bytes)`, `RelayClient(argv)` with `.proc`, `.send(kind, conn, payload=b"")`, `.collect(until, timeout=15) -> list[frame]`, `.close()`, and `write_server(folder) -> Path` (a tiny dev server script run as `python -u dev_server.py <mode> <port>`; modes `serve`, `print-only`, `exit3`; paths `/` `/slow` `/hang` `/big`).

- [ ] **Step 1: Write the test support and the failing tests**

Create `tests/code_sandbox/relay_support.py`:

```python
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
        try:
            self.proc.kill()
        except OSError:
            pass
        self.proc.wait(10)
```

Create `tests/code_sandbox/test_relay.py`:

```python
import struct
import sys

import pytest

from sandbox import wire
from tests.code_sandbox.relay_support import RelayClient, free_port, write_server


@pytest.fixture
def client():
    made = []

    def make(argv):
        c = RelayClient(argv)
        made.append(c)
        return c

    yield make
    for c in made:
        c.close()


def _log(frames):
    return b"".join(p for k, _c, p in frames if k == wire.LOG)


def test_log_and_exit(client):
    c = client([sys.executable, "-c", "print('hi'); import sys; sys.exit(4)"])
    frames = c.collect(lambda seen: any(k == wire.EXIT for k, _c, _p in seen))
    assert b"hi" in _log(frames)
    assert wire.parse_exit(frames[-1][2]) == 4


def test_open_data_close_round_trip(client, tmp_path):
    port = free_port()
    c = client([sys.executable, "-u", str(write_server(tmp_path)), "serve", str(port)])
    c.collect(lambda seen: b"Local:" in _log(seen))
    c.send(wire.OPEN, 1, wire.open_payload(port))
    c.send(wire.DATA, 1, b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
    frames = c.collect(lambda seen: any(k == wire.CLOSE and cid == 1 for k, cid, _p in seen))
    body = b"".join(p for k, cid, p in frames if k == wire.DATA and cid == 1)
    assert b"hello from dev server" in body


def test_stdin_eof_ends_relay(client):
    c = client([sys.executable, "-c", "import time; time.sleep(60)"])
    c.proc.stdin.close()
    assert c.proc.wait(10) == 0


def test_malformed_frame_ends_relay_with_2(client):
    c = client([sys.executable, "-c", "import time; time.sleep(60)"])
    c.proc.stdin.write(struct.pack("!BII", 99, 0, 0))
    c.proc.stdin.flush()
    assert c.proc.wait(10) == 2


def test_spawn_failure_reports_exit_127(client):
    c = client(["definitely-not-a-real-program-xyz"])
    frames = c.collect(lambda seen: any(k == wire.EXIT for k, _c, _p in seen))
    assert b"Could not start" in _log(frames)
    assert wire.parse_exit(frames[-1][2]) == 127


def test_open_to_closed_port_sends_close(client):
    c = client([sys.executable, "-c", "import time; time.sleep(60)"])
    c.send(wire.OPEN, 5, wire.open_payload(free_port()))
    frames = c.collect(lambda seen: any(k == wire.CLOSE and cid == 5 for k, cid, _p in seen))
    assert (wire.CLOSE, 5, b"") in frames
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/code_sandbox/test_relay.py -v`
Expected: FAIL (relay.py does not exist, so the relay process exits at once and the assertions time out or fail).

- [ ] **Step 3: Write the relay**

Create `web/sandbox/relay.py`:

```python
"""Runs inside the sandbox. Starts the user's command and carries loopback
connections to it over stdin/stdout. Stdlib only.

AIGATOR_RELAY_COMMAND (JSON argv list) is the command. Frames: see wire.py.
"""
import json
import os
import queue
import socket
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wire  # noqa: E402

_out_lock = threading.Lock()
_conns = {}
_conns_lock = threading.Lock()


def send(kind, conn, payload=b""):
    try:
        data = wire.encode(kind, conn, payload)
        with _out_lock:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    except (OSError, ValueError):
        os._exit(1)


class _Conn:
    def __init__(self, conn_id, port):
        self.id = conn_id
        self.port = port
        self.queue = queue.Queue()
        self.sock = None
        self.done = False
        self.lock = threading.Lock()

    def finish(self, notify):
        with self.lock:
            if self.done:
                return
            self.done = True
            sock = self.sock
        with _conns_lock:
            _conns.pop(self.id, None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        self.queue.put(None)
        if notify:
            send(wire.CLOSE, self.id)

    def run(self):
        try:
            sock = socket.create_connection(("localhost", self.port), timeout=10)
        except OSError:
            self.finish(True)
            return
        sock.settimeout(None)
        with self.lock:
            if self.done:
                sock.close()
                return
            self.sock = sock
        threading.Thread(target=self._read, daemon=True).start()
        while True:
            item = self.queue.get()
            if item is None:
                self.finish(False)
                return
            try:
                sock.sendall(item)
            except OSError:
                self.finish(True)
                return

    def _read(self):
        sock = self.sock
        while True:
            try:
                data = sock.recv(wire.MAX_PAYLOAD)
            except OSError:
                break
            if not data:
                break
            send(wire.DATA, self.id, data)
        self.finish(True)


def _kill(child):
    try:
        child.kill()
    except OSError:
        pass


def _dispatch(kind, conn_id, payload):
    if kind == wire.OPEN:
        conn = _Conn(conn_id, wire.parse_open(payload))
        with _conns_lock:
            _conns[conn_id] = conn
        threading.Thread(target=conn.run, daemon=True).start()
        return
    with _conns_lock:
        conn = _conns.get(conn_id)
    if conn is None:
        return
    if kind == wire.DATA:
        conn.queue.put(payload)
    elif kind == wire.CLOSE:
        conn.queue.put(None)


def main():
    argv = json.loads(os.environ.pop("AIGATOR_RELAY_COMMAND"))
    try:
        child = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
    except OSError as exc:
        send(wire.LOG, 0, f"Could not start the command: {exc}\n".encode("utf-8", "replace"))
        send(wire.EXIT, 0, wire.exit_payload(127))
        return

    def pump():
        try:
            while True:
                data = child.stdout.read1(4096)
                if not data:
                    break
                send(wire.LOG, 0, data)
        except (OSError, ValueError):
            pass

    pump_thread = threading.Thread(target=pump, daemon=True)
    pump_thread.start()

    def wait():
        code = child.wait()
        pump_thread.join(2)
        send(wire.EXIT, 0, wire.exit_payload(code))
        os._exit(0)

    threading.Thread(target=wait, daemon=True).start()

    stdin = sys.stdin.buffer
    decoder = wire.Decoder()
    while True:
        try:
            data = wire.read_some(stdin, 65536)
        except (OSError, ValueError):
            data = b""
        if not data:
            _kill(child)
            os._exit(0)
        try:
            for kind, conn_id, payload in decoder.feed(data):
                _dispatch(kind, conn_id, payload)
        except wire.WireError:
            _kill(child)
            os._exit(2)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/code_sandbox/test_relay.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/relay.py tests/code_sandbox/relay_support.py tests/code_sandbox/test_relay.py
git commit -m "feat: add the in-sandbox relay"
```

### Task 3: Forwarder (backend side) and port detection

**Files:**
- Create: `web/sandbox/forward.py`
- Test: `tests/code_sandbox/test_forward.py`

**Interfaces:**
- Consumes: Task 1 `wire`; Task 2 `relay_support` (`write_server`, `start_relay`, `free_port`, `wait_for`, `http_get`).
- Produces: `forward.detect_port(text) -> int | None`, `forward.strip_ansi`, `forward.MAX_CONNS = 64`, and `forward.ForwardedProcess(proc, log_file, on_close=None)` where `proc` has `pid`, `stdin`, `stdout`, `poll()`, `terminate()`. Methods: `.start() -> self`, `.wait_ready(timeout) -> bool` (True when `url` is set), `.poll() -> int | None`, `.terminate()`. Attributes: `pid`, `url` (`http://127.0.0.1:<listen_port>` or None), `listen_port`, `exit_code`, `closed` (threading.Event, set after full shutdown and after `on_close` ran).

- [ ] **Step 1: Write the failing tests**

Create `tests/code_sandbox/test_forward.py`:

```python
import asyncio
import socket
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sandbox import forward
from sandbox.forward import ForwardedProcess, detect_port
from tests.code_sandbox.relay_support import free_port, http_get, start_relay, wait_for, write_server


@pytest.fixture
def forward_server(tmp_path):
    made = []
    server = write_server(tmp_path)

    def make(mode="serve", port=None, on_close=None):
        port = port or free_port()
        popen = start_relay([sys.executable, "-u", str(server), mode, str(port)])
        fp = ForwardedProcess(popen, str(tmp_path / f"log{len(made)}.txt"), on_close=on_close).start()
        made.append(fp)
        assert fp.wait_ready(15)
        return fp, port

    yield make
    for fp in made:
        fp.terminate()


def test_browser_connection_reaches_dev_server(forward_server):
    fp, port = forward_server()
    head, body = http_get(fp.listen_port)
    assert head.startswith(b"HTTP/1.0 200")
    assert body == b"hello from dev server"
    assert fp.url == f"http://127.0.0.1:{fp.listen_port}"
    assert f"http://localhost:{port}" in Path(fp._log_path).read_text(errors="replace")


def test_listener_binds_loopback_only(forward_server):
    fp, _port = forward_server()
    assert fp._server.sockets[0].getsockname()[0] == "127.0.0.1"


def test_falls_back_to_a_free_port_when_taken(forward_server):
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        taken = held.getsockname()[1]
        fp, _ = forward_server("print-only", port=taken)
        assert fp.listen_port not in (None, taken)


def test_prefers_the_dev_server_port(forward_server):
    port = free_port()
    fp, _ = forward_server("print-only", port=port)
    assert fp.listen_port == port


def test_many_connections_at_once(forward_server):
    fp, _ = forward_server()
    with ThreadPoolExecutor(10) as pool:
        results = list(pool.map(lambda _i: http_get(fp.listen_port, "/slow"), range(20)))
    assert all(head.startswith(b"HTTP/1.0 200") and body == b"hello from dev server" for head, body in results)


def test_connection_cap(forward_server, monkeypatch):
    monkeypatch.setattr(forward, "MAX_CONNS", 2)
    fp, _ = forward_server()
    held = []
    try:
        for _ in range(2):
            s = socket.create_connection(("127.0.0.1", fp.listen_port), 5)
            s.sendall(b"GET /hang HTTP/1.0\r\n\r\n")
            held.append(s)
        assert wait_for(lambda: len(fp._conns) == 2)
        third = socket.create_connection(("127.0.0.1", fp.listen_port), 5)
        third.settimeout(5)
        try:
            data = third.recv(10)
        except ConnectionResetError:
            data = b""
        third.close()
        assert data == b""
    finally:
        for s in held:
            s.close()


def test_close_from_either_side_frees_the_connection(forward_server):
    fp, _ = forward_server()
    s = socket.create_connection(("127.0.0.1", fp.listen_port), 5)
    s.sendall(b"GET /hang HTTP/1.0\r\n\r\n")
    assert wait_for(lambda: len(fp._conns) == 1)
    s.close()
    assert wait_for(lambda: len(fp._conns) == 0)
    http_get(fp.listen_port)
    assert wait_for(lambda: len(fp._conns) == 0)


def test_event_loop_not_blocked_while_streaming(forward_server):
    fp, _ = forward_server()
    out = {}

    def fetch():
        out["result"] = http_get(fp.listen_port, "/big", timeout=30)

    t = threading.Thread(target=fetch)
    t.start()
    worst = 0.0
    while t.is_alive():
        start = time.monotonic()
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0), fp._loop).result(timeout=1)
        worst = max(worst, time.monotonic() - start)
        time.sleep(0.01)
    t.join()
    assert len(out["result"][1]) == 8 * 1024 * 1024
    assert worst < 0.5


def test_exit_frame_ends_everything(forward_server):
    calls = []
    fp, _ = forward_server("exit3", on_close=lambda: calls.append(1))
    assert fp.closed.wait(10)
    assert fp.poll() == 3
    assert calls == [1]


class _FakeProc:
    pid = 1

    def __init__(self, payload):
        import io
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(payload)
        self.terminated = False

    def poll(self):
        return 1 if self.terminated else None

    def terminate(self):
        self.terminated = True


def test_malformed_frame_closes_the_process(tmp_path):
    proc = _FakeProc(struct.pack("!BII", 99, 0, 0))
    fp = ForwardedProcess(proc, str(tmp_path / "log.txt")).start()
    assert fp.closed.wait(5)
    assert proc.terminated


@pytest.mark.parametrize("text,expected", [
    ("\x1b[32m➜\x1b[39m  \x1b[1mLocal\x1b[22m:   \x1b[36mhttp://localhost:\x1b[1m5173\x1b[22m/\x1b[39m", 5173),
    ("see http://localhost.evil.com:80/", None),
    ("no url here", None),
    ("http://localhost:0/", None),
    ("http://localhost:99999/", None),
    ("http://[::1]:4000/", 4000),
    ("at http://127.0.0.1:3030", 3030),
    ("http://localhost:123456", None),
])
def test_detect_port(text, expected):
    assert detect_port(text) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/code_sandbox/test_forward.py -v`
Expected: FAIL with `ImportError: cannot import name 'forward' from 'sandbox'`.

- [ ] **Step 3: Write the forwarder**

Create `web/sandbox/forward.py`:

```python
"""Backend side of dev-server port forwarding.

ForwardedProcess wraps a started sandbox process that is running relay.py.
Pipe reads and writes run on threads; the browser-facing listener is an asyncio
server on its own loop thread, so the app's event loop is never involved.
"""
from __future__ import annotations

import asyncio
import codecs
import logging
import queue
import re
import threading
import time

from . import wire

_log = logging.getLogger("sandbox.forward")

MAX_CONNS = 64
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\]):(\d{1,5})(?!\w)")
_SCAN_TAIL = 8192


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def detect_port(text: str) -> int | None:
    for match in _URL.finditer(strip_ansi(text)):
        port = int(match.group(1))
        if 1 <= port <= 65535:
            return port
    return None


class ForwardedProcess:
    def __init__(self, proc, log_file: str, on_close=None):
        self._proc = proc
        self.pid = proc.pid
        self._log_path = log_file
        self._on_close = on_close
        self.url: str | None = None
        self.listen_port: int | None = None
        self.exit_code: int | None = None
        self.closed = threading.Event()
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._server = None
        self._conns: dict[int, asyncio.StreamWriter] = {}
        self._tasks: set = set()
        self._next_conn = 0
        self._writes: queue.Queue = queue.Queue()
        self._dev_port: int | None = None
        self._shut = False
        self._shut_lock = threading.Lock()
        self._log_handle = None
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._scan = ""

    def start(self) -> "ForwardedProcess":
        self._log_handle = open(self._log_path, "ab")
        threading.Thread(target=self._run_loop, daemon=True).start()
        if not self._loop_ready.wait(5):
            self._log_handle.close()
            raise OSError("The port forwarder did not start.")
        threading.Thread(target=self._read_pipe, daemon=True).start()
        threading.Thread(target=self._write_pipe, daemon=True).start()
        return self

    def poll(self) -> int | None:
        if self.exit_code is not None:
            return self.exit_code
        return self._proc.poll()

    def wait_ready(self, timeout: float) -> bool:
        self._ready.wait(timeout)
        return self.url is not None

    def terminate(self) -> None:
        self._writes.put(None)
        self._shutdown()
        self.closed.wait(5)

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        loop.call_soon(self._loop_ready.set)
        try:
            loop.run_forever()
        finally:
            loop.close()

    def _read_pipe(self) -> None:
        decoder = wire.Decoder()
        try:
            while True:
                data = wire.read_some(self._proc.stdout, 65536)
                if not data:
                    break
                for kind, conn, payload in decoder.feed(data):
                    if kind == wire.LOG:
                        self._on_log(payload)
                    elif kind == wire.DATA:
                        self._post(self._deliver, conn, payload)
                    elif kind == wire.CLOSE:
                        self._post(self._drop, conn)
                    elif kind == wire.EXIT:
                        self.exit_code = wire.parse_exit(payload)
                        self._shutdown()
                        return
        except (OSError, ValueError):
            pass
        try:
            self._proc.terminate()
        except OSError:
            pass
        self._shutdown()

    def _write_pipe(self) -> None:
        stream = self._proc.stdin
        try:
            while True:
                frame = self._writes.get()
                if frame is None:
                    break
                stream.write(frame)
                stream.flush()
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    def _on_log(self, payload: bytes) -> None:
        try:
            self._log_handle.write(payload)
            self._log_handle.flush()
        except (OSError, ValueError):
            pass
        if self._dev_port is not None:
            return
        self._scan += self._decoder.decode(payload)
        cut = self._scan.rfind("\n") + 1
        if not cut:
            self._scan = self._scan[-_SCAN_TAIL:]
            return
        port = detect_port(self._scan[:cut])
        self._scan = self._scan[cut:][-_SCAN_TAIL:]
        if port is None:
            return
        self._dev_port = port
        try:
            asyncio.run_coroutine_threadsafe(self._listen(port), self._loop)
        except RuntimeError:
            self._ready.set()

    def _post(self, fn, *args) -> None:
        try:
            self._loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:
            pass

    async def _listen(self, port: int) -> None:
        try:
            for candidate in (port, 0):
                try:
                    server = await asyncio.start_server(self._accept, "127.0.0.1", candidate)
                except OSError:
                    continue
                if self._shut:
                    server.close()
                    break
                self._server = server
                self.listen_port = server.sockets[0].getsockname()[1]
                self.url = f"http://127.0.0.1:{self.listen_port}"
                break
        finally:
            self._ready.set()

    async def _accept(self, reader, writer) -> None:
        task = asyncio.current_task()
        self._tasks.add(task)
        conn = None
        try:
            if self._shut or len(self._conns) >= MAX_CONNS:
                return
            self._next_conn += 1
            conn = self._next_conn
            self._conns[conn] = writer
            self._send(wire.OPEN, conn, wire.open_payload(self._dev_port))
            while True:
                data = await reader.read(wire.MAX_PAYLOAD)
                if not data:
                    break
                self._send(wire.DATA, conn, data)
        except OSError:
            pass
        finally:
            if conn is not None and self._conns.pop(conn, None) is not None:
                self._send(wire.CLOSE, conn)
            writer.close()
            self._tasks.discard(task)

    def _deliver(self, conn: int, payload: bytes) -> None:
        writer = self._conns.get(conn)
        if writer is not None:
            writer.write(payload)

    def _drop(self, conn: int) -> None:
        writer = self._conns.pop(conn, None)
        if writer is not None:
            writer.close()

    def _send(self, kind: int, conn: int, payload: bytes = b"") -> None:
        self._writes.put(wire.encode(kind, conn, payload))

    async def _close_all(self) -> None:
        if self._server is not None:
            self._server.close()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for writer in list(self._conns.values()):
            writer.close()
        self._conns.clear()

    def _shutdown(self) -> None:
        """Idempotent; never call from the loop thread."""
        with self._shut_lock:
            if self._shut:
                return
            self._shut = True
        self._ready.set()
        loop = self._loop
        try:
            asyncio.run_coroutine_threadsafe(self._close_all(), loop).result(3)
        except Exception:
            pass
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass
        self._writes.put(None)
        deadline = time.monotonic() + 2
        while self._proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if self._proc.poll() is None:
            try:
                self._proc.terminate()
            except OSError:
                pass
        try:
            self._log_handle.close()
        except (OSError, ValueError):
            pass
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception as exc:
                _log.warning("forward: on_close failed (%s)", type(exc).__name__)
        self.closed.set()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/code_sandbox/test_forward.py -v`
Expected: all pass. If `test_falls_back_to_a_free_port_when_taken` or the connection tests are flaky, that is a real bug in `_listen`/`_accept`; fix it there, do not loosen the test.

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/forward.py tests/code_sandbox/test_forward.py
git commit -m "feat: add the dev server port forwarder"
```

### Task 4: Streaming sandbox launcher and `start_sandboxed`

**Files:**
- Modify: `web/sandbox/launcher_windows.py` (imports and constants near the top; `_LEDGER_LOCK` at line 57; `_sweep_locked` at 679; `_run_contained` at 733; `launch` at 900 to the end of the file)
- Modify: `web/sandbox/__init__.py` (add after `launch_sandboxed`, lines 120-123)
- Test: append to `tests/code_sandbox/test_launcher_windows.py`; create `tests/code_sandbox/test_start_sandboxed.py`

**Interfaces:**
- Consumes: existing `launcher_windows` helpers (`acl_grants`, `ensure_profile`, `_grant`, `_revoke_ok`, `_scrub_container`, `_ledger_*`, `_api`), `SandboxRequest`, `SandboxUnavailable`, `SandboxRunError`, `SandboxPathNotGrantable`.
- Produces:
  - `launcher_windows.start(req: SandboxRequest) -> SandboxProcess`. Same profile, grants and Job Object as `launch`, but stdin is a pipe, it returns right after `ResumeThread`, and the grants stay in place until the process exits.
  - `launcher_windows.SandboxProcess(started, on_exit)` with `pid: int`, `stdin` and `stdout` (binary file objects), `poll() -> int | None`, `wait(timeout=None) -> int` (raises `subprocess.TimeoutExpired`), `terminate()` (closes the Job Object, which kills the whole tree).
  - `launcher_windows._Started = namedtuple("_Started", "proc job out_rd in_wr pid")`.
  - `launcher_windows.readable_or_grantable(path: Path) -> bool`.
  - `sandbox.start_sandboxed(req)` (raises `SandboxUnavailable` when not enforced, `NotImplementedError` when the platform launcher has no `start`) and `sandbox.container_readable(path) -> bool` (True when the sandbox is not enforced or the platform is not Windows).

- [ ] **Step 1: Write the failing tests**

Append to `tests/code_sandbox/test_launcher_windows.py` (it already defines the `fake` fixture; do not redefine it):

```python
# ---- start(): long-running sandboxed process ----
from types import SimpleNamespace as _NS

from sandbox import SandboxRunError as _SandboxRunError

_STARTED = lw._Started(1, 2, 3, 4, 99)


class _Spy:
    def __init__(self, started, on_exit):
        self.started, self.on_exit = started, on_exit


def _streaming(monkeypatch, result="done"):
    lw._HELD.clear()
    monkeypatch.setattr(lw, "SandboxProcess", _Spy)
    monkeypatch.setattr(lw, "_run_contained", lambda *a, stream=False, **k: _STARTED if stream else result)


def test_start_holds_grants_until_the_process_exits(fake, monkeypatch):
    _streaming(monkeypatch)
    spy = lw.start(fake.req(write=[fake.run]))
    held = lw._ledger_load()["per_run"]
    assert held and fake.revokes == []
    spy.on_exit()
    assert len(fake.revokes) == len(held)
    assert lw._ledger_load()["per_run"] == []


def test_later_foreground_launch_leaves_held_grants_alone(fake, monkeypatch):
    _streaming(monkeypatch)
    spy = lw.start(fake.req(write=[fake.run]))
    held = {tuple(e) for e in lw._ledger_load()["per_run"]}
    assert lw.launch(fake.req(write=[fake.run])) == "done"
    assert fake.revokes == []
    assert {tuple(e) for e in lw._ledger_load()["per_run"]} == held
    spy.on_exit()
    assert lw._ledger_load()["per_run"] == []


def test_start_frees_the_profile_sid_once(fake, monkeypatch):
    _streaming(monkeypatch)
    freed = []
    monkeypatch.setattr(lw, "_api", lambda: _NS(adv=_NS(FreeSid=freed.append)))
    lw.start(fake.req(write=[fake.run]))
    assert freed == [None]


def test_start_failure_releases_everything(fake, monkeypatch):
    lw._HELD.clear()

    def boom(*a, **k):
        raise lw._run_error(True, "x")

    monkeypatch.setattr(lw, "_run_contained", boom)
    with pytest.raises(_SandboxRunError):
        lw.start(fake.req(write=[fake.run]))
    assert fake.revokes
    assert lw._ledger_load()["per_run"] == []
    assert lw._HELD == {}
```

Create `tests/code_sandbox/test_start_sandboxed.py`:

```python
from pathlib import Path

import pytest

import sandbox
from sandbox import SandboxRequest, SandboxUnavailable


def _req():
    return SandboxRequest(argv=["x"], cwd=Path("."), env={}, runtime_paths=[], read_paths=[],
                          write_paths=[], network=False, timeout=1)


def test_refused_when_not_enforced(monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "off")
    monkeypatch.setattr(sandbox, "sandbox_unavailable_reason", lambda: "turned off")
    with pytest.raises(SandboxUnavailable, match="turned off"):
        sandbox.start_sandboxed(_req())


def test_platform_without_start_is_not_implemented(monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "enforced")
    monkeypatch.setattr(sandbox, "_launcher", lambda: object())
    with pytest.raises(NotImplementedError):
        sandbox.start_sandboxed(_req())


def test_delegates_to_the_launcher(monkeypatch):
    seen = []

    class L:
        def start(self, req):
            seen.append(req)
            return "proc"

    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "enforced")
    monkeypatch.setattr(sandbox, "_launcher", lambda: L())
    req = _req()
    assert sandbox.start_sandboxed(req) == "proc"
    assert seen == [req]


def test_container_readable_is_true_when_not_enforced(monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "off")
    assert sandbox.container_readable(Path("C:/anything")) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/code_sandbox/test_launcher_windows.py tests/code_sandbox/test_start_sandboxed.py -v`
Expected: the new tests FAIL (`AttributeError: ... has no attribute '_Started'` / `'start_sandboxed'`). The existing tests in `test_launcher_windows.py` still pass.

- [ ] **Step 3: Implement**

Read `web/sandbox/launcher_windows.py` first, then make these edits in order.

**3a. Imports and constants.** Add `from collections import namedtuple` above `from pathlib import Path`. Next to `GENERIC_READ = 0x80000000` add:

```python
GENERIC_WRITE = 0x40000000
INFINITE = 0xFFFFFFFF
```

Change `_LEDGER_LOCK = threading.Lock()` (line 57) to `_LEDGER_LOCK = threading.RLock()` and add directly below it:

```python
_HELD: dict[tuple[str, str], int] = {}
_Started = namedtuple("_Started", "proc job out_rd in_wr pid")


def _held_key(sid: str, path) -> tuple[str, str]:
    return (sid, os.path.normcase(str(path)))


def _is_held(sid: str, path) -> bool:
    with _LEDGER_LOCK:
        return _held_key(sid, path) in _HELD


def _hold(sid: str, path) -> None:
    with _LEDGER_LOCK:
        key = _held_key(sid, path)
        _HELD[key] = _HELD.get(key, 0) + 1


def _unhold(sid: str, path) -> None:
    with _LEDGER_LOCK:
        key = _held_key(sid, path)
        count = _HELD.get(key, 0)
        if count <= 1:
            _HELD.pop(key, None)
        else:
            _HELD[key] = count - 1
```

**3b. The sweep must not revoke grants a running process still needs.** In `_sweep_locked` replace the `kept = ...` line and the return line:

```python
        kept = [[sid, path] for sid, path in entries
                if _is_held(sid, path) or not _revoke_ok(sid, Path(path))]
```
```python
        return len(entries) - len(kept), sum(1 for sid, path in kept if not _is_held(sid, path))
```

**3c. `_run_contained` gets `stream: bool = False`.** Add it as the last parameter. Replace the nested `pipe` helper:

```python
    def pipe(parent_reads=True):
        rd, wr = own(HANDLE()), own(HANDLE())
        if not k32.CreatePipe(ctypes.byref(rd), ctypes.byref(wr), ctypes.byref(sa), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        k32.SetHandleInformation(rd if parent_reads else wr, HANDLE_FLAG_INHERIT, 0)
        return rd, wr
```

Replace the block that creates the three std handles (`out_rd, out_wr = pipe()` through the `if not _valid(hin): raise ...` check) with:

```python
        if stream:
            out_rd, out_wr = pipe()
            hin, in_wr = pipe(parent_reads=False)
            err_wr = own(HANDLE(k32.CreateFileW("NUL", GENERIC_WRITE, FILE_SHARE_READ_WRITE, ctypes.byref(sa),
                                                OPEN_EXISTING, 0, None)))
            if not _valid(err_wr):
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            out_rd, out_wr = pipe()
            err_rd, err_wr = pipe()
            hin = own(HANDLE(k32.CreateFileW("NUL", GENERIC_READ, FILE_SHARE_READ_WRITE, ctypes.byref(sa),
                                             OPEN_EXISTING, 0, None)))
            if not _valid(hin):
                raise ctypes.WinError(ctypes.get_last_error())
```

Directly after the line `resumed = True` add:

```python
        if stream:
            started = _Started(proc.value, job.value, out_rd.value, in_wr.value, pi.dwProcessId)
            for handle in (proc, job, out_rd, in_wr):
                handle.value = None
            finished = True
            return started
```

The `finally` that closes the thread handle and the child-side handles stays as is. In stream mode `err_rd` is never created or read; the pumps are skipped because we return first.

**3d. Replace `launch` (from its `def launch(` line to the end of the file)** with the code below. `_prepare` is the old `launch` body up to the grant loop, unchanged except for the `stuck` message (held entries are excluded) and the `scrubbed` flag; `_finish` is the old `finally`.

```python
class _Prepared:
    def __init__(self, psid, sid):
        self.psid, self.sid = psid, sid
        self.attempted: list[Path] = []
        self.scrubbed = False
        self._freed = False

    def free_sid(self) -> None:
        if not self._freed:
            self._freed = True
            _api().adv.FreeSid(self.psid)


def _release(sid: str, paths, unhold: bool = False) -> None:
    for path in paths:
        try:
            if unhold:
                _unhold(sid, path)
            if _is_held(sid, path):
                continue
            if _revoke_ok(sid, path):
                _ledger_remove_per_run(sid, path)
        except Exception as exc:
            _log.warning("sandbox: could not update the grant ledger (%s)", type(exc).__name__)


def _release_locked(sid: str, paths) -> None:
    with _RUN_LOCK:
        _release(sid, paths, unhold=True)


def _finish(prep: _Prepared) -> None:
    try:
        _release(prep.sid, prep.attempted)
        if prep.scrubbed:
            _scrub_container(prep.sid)
    finally:
        prep.free_sid()


def _prepare(req: SandboxRequest) -> _Prepared:
    """Give the sandbox its access for one run. The caller holds _RUN_LOCK."""
    runtime, per_run = acl_grants(req)
    runtime_dirs = [str(path) for path, _perm in runtime]
    for path, _perm in runtime + per_run + ([(Path(req.scratch_path), "M")] if req.scratch_path else []):
        try:
            _check_icacls_path(str(path))
        except ValueError as exc:
            raise SandboxUnavailable(str(exc)) from exc
    for path, perm in per_run:
        if perm != "RX" and any(_same_path(path, d) for d in runtime_dirs):
            raise SandboxUnavailable(f"{path} is a runtime directory and cannot also be a writable path.")
    _cleared, remaining = _sweep_locked()
    if remaining:
        stuck = ", ".join(sorted({path for sid, path in _ledger_load()["per_run"] if not _is_held(sid, path)}))
        raise SandboxUnavailable(
            f"Access granted to an earlier sandboxed run could not be removed from {stuck}, so the sandbox "
            "is paused until it can be. Restarting AI Gator retries the removal; if it keeps failing, fix the "
            "permissions on that folder (the sandbox's access entry must be removable by your account)."
        )
    try:
        psid, sid = ensure_profile(PROFILE_NAME + SHELL_PROFILE_SUFFIX if req.scratch_path else PROFILE_NAME)
    except OSError as exc:
        raise SandboxUnavailable(f"Windows could not create the AppContainer sandbox profile ({exc}).") from exc
    prep = _Prepared(psid, sid)
    try:
        _ensure_runtime_grants(sid, [path for path, _perm in runtime])
        granted = _ledger_load()["runtime"].get(sid, [])
        try:
            _ensure_package_inheritance(sid, _site_package_dirs(), granted)
        except Exception as exc:
            _log.warning("sandbox: could not refresh package access (%s)", type(exc).__name__)
        per_run = [(p, perm) for p, perm in per_run if not (perm == "RX" and _covered_by(p, granted))]
        if req.scratch_path is not None and _ensure_scratch_grant(sid, Path(req.scratch_path)):
            per_run = [(p, perm) for p, perm in per_run if not _covered_by(p, [str(req.scratch_path)])]
        per_run = [(p, perm) for p, perm in per_run if not (perm == "RX" and _container_can_read(p, sid))]
        blocked = [p for p, _perm in per_run if not _can_change_acl(p)]
        if blocked:
            raise SandboxPathNotGrantable(blocked)
        _scrub_container(sid)
        prep.scrubbed = True
        for path, perm in per_run:
            _ledger_add_per_run(sid, path)
            prep.attempted.append(path)
            rc, out = _grant(path, sid, perm)
            if rc != 0:
                raise SandboxUnavailable(f"The sandbox could not be given access to {path} ({out}).")
        return prep
    except BaseException:
        _finish(prep)
        raise


def launch(req: SandboxRequest) -> SandboxResult:
    with _RUN_LOCK:
        prep = _prepare(req)
        try:
            return _run_contained(req.argv, req.cwd, req.env, prep.psid, req.timeout, req.network)
        finally:
            _finish(prep)


class SandboxProcess:
    def __init__(self, started, on_exit):
        import msvcrt

        self.pid = started.pid
        self.stdout = os.fdopen(msvcrt.open_osfhandle(started.out_rd, os.O_RDONLY | os.O_BINARY), "rb")
        self.stdin = os.fdopen(msvcrt.open_osfhandle(started.in_wr, os.O_WRONLY | os.O_BINARY), "wb")
        self._proc, self._job = started.proc, started.job
        self._on_exit = on_exit
        self._returncode: int | None = None
        self._done = threading.Event()
        self._lock = threading.Lock()
        threading.Thread(target=self._watch, daemon=True).start()

    def terminate(self) -> None:
        with self._lock:
            job, self._job = self._job, None
        if job is not None:
            a = _api()
            a.k32.TerminateJobObject(a.wt.HANDLE(job), 1)
            a.k32.CloseHandle(a.wt.HANDLE(job))

    def poll(self) -> int | None:
        return self._returncode

    def wait(self, timeout: float | None = None) -> int:
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired("sandboxed process", timeout)
        return self._returncode

    def _watch(self) -> None:
        a = _api()
        a.k32.WaitForSingleObject(a.wt.HANDLE(self._proc), INFINITE)
        code = a.wt.DWORD()
        a.k32.GetExitCodeProcess(a.wt.HANDLE(self._proc), ctypes.byref(code))
        self.terminate()
        a.k32.CloseHandle(a.wt.HANDLE(self._proc))
        self._returncode = int(code.value)
        try:
            self._on_exit()
        except Exception as exc:
            _log.warning("sandbox: could not release a finished run (%s)", type(exc).__name__)
        self._done.set()


def start(req: SandboxRequest) -> SandboxProcess:
    """Start a long-running sandboxed process. Its grants are released when it exits."""
    with _RUN_LOCK:
        prep = _prepare(req)
        try:
            started = _run_contained(req.argv, req.cwd, req.env, prep.psid, req.timeout, req.network, stream=True)
        except BaseException:
            _finish(prep)
            raise
        for path in prep.attempted:
            _hold(prep.sid, path)
        prep.free_sid()
    sid, paths = prep.sid, list(prep.attempted)
    try:
        return SandboxProcess(started, on_exit=lambda: _release_locked(sid, paths))
    except BaseException:
        a = _api()
        a.k32.TerminateJobObject(a.wt.HANDLE(started.job), 1)
        a.k32.CloseHandle(a.wt.HANDLE(started.job))
        _release_locked(sid, paths)
        raise


def readable_or_grantable(path: Path) -> bool:
    psid, sid = ensure_profile(PROFILE_NAME + SHELL_PROFILE_SUFFIX)
    try:
        return _container_can_read(path, sid) or _can_change_acl(path)
    finally:
        _api().adv.FreeSid(psid)
```

**3e. `web/sandbox/__init__.py`.** Directly after `launch_sandboxed` add:

```python
def start_sandboxed(req):
    if sandbox_level() != "enforced":
        raise SandboxUnavailable(sandbox_unavailable_reason() or "The sandbox is unavailable.")
    start = getattr(_launcher(), "start", None)
    if start is None:
        raise NotImplementedError("Long-running sandboxed processes are only supported on Windows.")
    return start(req)


def container_readable(path) -> bool:
    if sys.platform != "win32" or sandbox_level() != "enforced":
        return True
    from . import launcher_windows
    return launcher_windows.readable_or_grantable(Path(path))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/code_sandbox -v -m "not real_sandbox"`
Expected: all pass, including every pre-existing launcher test unmodified (notably `test_launch_removes_ledger_entries_when_revoke_succeeds`, which asserts the revoke order).

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/launcher_windows.py web/sandbox/__init__.py tests/code_sandbox/test_launcher_windows.py tests/code_sandbox/test_start_sandboxed.py
git commit -m "feat: start long-running sandboxed processes that hold their grants until they exit"
```

### Task 5: Real AppContainer check of the streaming path (Windows only)

This task proves the two things the spike did not: frames really flow through the streaming launcher's stdin and stdout pipes, and the Job Object ends the whole tree. It carries no production code, so there is no red step; if it fails, the bug is in Task 2 or Task 4 and must be fixed there, at the root.

**Files:**
- Test: `tests/code_sandbox/test_forward_real_sandbox.py`

**Interfaces:**
- Consumes: `windows_container` (session fixture in `tests/conftest.py`; it yields the `launcher_windows` module with a throwaway AppContainer profile and ledger), `launcher_windows.start`, `ForwardedProcess` (Task 3), `relay_support.write_server`, `free_port`, `http_get` (Task 2).
- Produces: nothing.

- [ ] **Step 1: Write the test**

Create `tests/code_sandbox/test_forward_real_sandbox.py`:

```python
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

import sandbox
from sandbox import SandboxRequest, build_env
from sandbox.forward import ForwardedProcess
from tests.code_sandbox.relay_support import free_port, http_get, write_server

pytestmark = [
    pytest.mark.real_sandbox,
    pytest.mark.skipif(sys.platform != "win32", reason="AppContainer is Windows only"),
]


def test_dev_server_in_the_sandbox_is_reachable_through_the_forwarder(windows_container, tmp_path):
    import psutil

    src = Path(sandbox.__file__).resolve().parent
    relay_dir = tmp_path / "relay"
    relay_dir.mkdir()
    for name in ("relay.py", "wire.py"):
        shutil.copy2(src / name, relay_dir / name)
    run = tmp_path / "run"
    run.mkdir()
    server = write_server(run)
    port = free_port()
    env = build_env(os.environ, run, None)
    env["AIGATOR_RELAY_COMMAND"] = json.dumps([sys.executable, "-u", str(server), "serve", str(port)])
    req = SandboxRequest(
        argv=[sys.executable, "-X", "utf8", str(relay_dir / "relay.py")],
        cwd=run,
        env=env,
        runtime_paths=sorted({Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}, key=str),
        read_paths=[relay_dir],
        write_paths=[],
        network=False,
        timeout=0,
    )
    sp = windows_container.start(req)
    fp = ForwardedProcess(sp, str(tmp_path / "log.txt")).start()
    children = []
    try:
        assert fp.wait_ready(30), (tmp_path / "log.txt").read_text(errors="replace")
        children = psutil.Process(sp.pid).children(recursive=True)
        assert children
        head, body = http_get(fp.listen_port)
        assert head.startswith(b"HTTP/1.0 200")
        assert body == b"hello from dev server"
    finally:
        fp.terminate()
    _gone, alive = psutil.wait_procs(children, timeout=10)
    assert alive == []
    assert isinstance(sp.wait(60), int)
    assert json.loads(windows_container.ledger_path().read_text())["per_run"] == []
```

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/code_sandbox/test_forward_real_sandbox.py -v -m real_sandbox`
Expected: PASS. A failure on `wait_ready` means the relay or the pipes are not carrying frames (read the log printed in the assertion message); a surviving child means the Job Object is not being closed by `SandboxProcess.terminate`; a non-empty ledger means `_release_locked` did not run from the watcher.

- [ ] **Step 3: Run the whole sandbox suite**

Run: `python -m pytest tests/code_sandbox -v`
Expected: all pass, real sandbox tests included.

- [ ] **Step 4: Commit**

```bash
git add tests/code_sandbox/test_forward_real_sandbox.py
git commit -m "test: verify the streaming sandbox path and tree kill in a real AppContainer"
```

### Task 6: Readable copies of tools the sandbox cannot read

**Files:**
- Create: `web/sandbox/runtime_copy.py`
- Test: `tests/code_sandbox/test_runtime_copy.py`

**Interfaces:**
- Consumes: the stdlib only. The `usable` callback passed in is `sandbox.container_readable` (Task 4).
- Produces:
  - `runtime_copy.RuntimeCopyError(RuntimeError)`, `runtime_copy.MAX_COPY_BYTES = 1024 ** 3`.
  - `runtime_copy.runtime_dir() -> Path` (`~/.gator/sandbox/runtime`) and `runtime_copy.relay_dir() -> Path` (`~/.gator/sandbox/relay`).
  - `runtime_copy.tool_names(command: str) -> list[str]`.
  - `runtime_copy.readable_copies(command: str, search_path: str, usable: Callable[[Path], bool], root: Path) -> list[Path]`: for each tool the command names, the folder of the resolved program; if `usable(folder)` is False the folder is copied once into `root` and the copy is returned.
  - `runtime_copy.install_relay(root: Path | None = None) -> Path`: copies `relay.py` and `wire.py` next to each other and returns the path of `relay.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/code_sandbox/test_runtime_copy.py`:

```python
import os

import pytest

from sandbox import runtime_copy


def _tool(folder, name="mytool"):
    folder.mkdir(parents=True)
    exe = folder / (name + (".cmd" if os.name == "nt" else ""))
    exe.write_text("@echo off\n" if os.name == "nt" else "#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


def test_unreadable_tool_folder_is_copied_once_and_reused(tmp_path):
    exe = _tool(tmp_path / "prog")
    root = tmp_path / "root"
    first = runtime_copy.readable_copies("mytool --serve", str(exe.parent), lambda p: False, root)
    assert len(first) == 1 and (first[0] / exe.name).exists()
    (first[0] / "sentinel").write_text("kept")
    second = runtime_copy.readable_copies("mytool --serve", str(exe.parent), lambda p: False, root)
    assert second == first and (first[0] / "sentinel").read_text() == "kept"


def test_readable_tool_is_not_copied(tmp_path):
    exe = _tool(tmp_path / "prog")
    root = tmp_path / "root"
    assert runtime_copy.readable_copies("mytool", str(exe.parent), lambda p: True, root) == []
    assert not root.exists()


def test_unknown_program_is_skipped(tmp_path):
    assert runtime_copy.readable_copies("echo hi", str(tmp_path), lambda p: False, tmp_path / "root") == []


@pytest.mark.parametrize("command,expected", [
    ("cd app && npm run dev", ["cd", "npm", "node"]),
    ("node server.js", ["node"]),
    ("npx vite", ["npx", "node"]),
    ("npm i && npm run dev", ["npm", "node"]),
    ('"python" -m http.server', ["python"]),
])
def test_tool_names(command, expected):
    assert runtime_copy.tool_names(command) == expected


def test_too_large_folder_is_refused(tmp_path, monkeypatch):
    exe = _tool(tmp_path / "prog")
    (exe.parent / "big.bin").write_bytes(b"x" * 10)
    monkeypatch.setattr(runtime_copy, "MAX_COPY_BYTES", 1)
    with pytest.raises(runtime_copy.RuntimeCopyError):
        runtime_copy.readable_copies("mytool", str(exe.parent), lambda p: False, tmp_path / "root")
    assert not (tmp_path / "root").exists() or not any((tmp_path / "root").iterdir())


def test_install_relay_copies_both_files(tmp_path):
    relay = runtime_copy.install_relay(tmp_path / "r")
    assert relay == tmp_path / "r" / "relay.py"
    assert (tmp_path / "r" / "wire.py").exists()
    assert runtime_copy.install_relay(tmp_path / "r") == relay
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/code_sandbox/test_runtime_copy.py -v`
Expected: FAIL with `ImportError: cannot import name 'runtime_copy' from 'sandbox'`.

- [ ] **Step 3: Write the module**

Create `web/sandbox/runtime_copy.py`:

```python
"""Readable copies of tools the AppContainer cannot read (for example Node under Program Files)."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
from pathlib import Path

MAX_COPY_BYTES = 1024 ** 3
_COPY_LOCK = threading.Lock()
_SPLIT = re.compile(r"&&|\|\||[;|&]")


class RuntimeCopyError(RuntimeError):
    pass


def runtime_dir() -> Path:
    return Path.home() / ".gator" / "sandbox" / "runtime"


def relay_dir() -> Path:
    return Path.home() / ".gator" / "sandbox" / "relay"


def tool_names(command: str) -> list[str]:
    names: list[str] = []
    for segment in _SPLIT.split(command):
        words = segment.strip().split()
        if not words:
            continue
        name = words[0].strip("\"'")
        if name and name not in names:
            names.append(name)
    if "node" not in names and any(os.path.splitext(n.lower())[0] in ("npm", "npx") for n in names):
        names.append("node")
    return names


def _tree_size(folder: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(folder):
        for name in files:
            total += os.path.getsize(os.path.join(dirpath, name))
            if total > MAX_COPY_BYTES:
                return total
    return total


def _copy_once(folder: Path, root: Path) -> Path:
    digest = hashlib.sha1(os.path.normcase(str(folder)).encode("utf-8")).hexdigest()[:8]
    target = root / f"{folder.name}-{int(folder.stat().st_mtime)}-{digest}"
    partial = target.with_name(target.name + ".partial")
    with _COPY_LOCK:
        if target.exists():
            return target
        try:
            if _tree_size(folder) > MAX_COPY_BYTES:
                raise RuntimeCopyError(f"{folder} is too large to copy for the sandbox.")
            root.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(partial, ignore_errors=True)
            shutil.copytree(folder, partial)
            partial.rename(target)
        except OSError as exc:
            shutil.rmtree(partial, ignore_errors=True)
            raise RuntimeCopyError(
                f"Could not copy {folder} so the sandbox can read it ({type(exc).__name__})."
            ) from exc
    return target


def readable_copies(command: str, search_path: str, usable, root: Path) -> list[Path]:
    copies: list[Path] = []
    for name in tool_names(command):
        found = shutil.which(name, path=search_path)
        if not found:
            continue
        folder = Path(found).resolve().parent
        if usable(folder):
            continue
        copy = _copy_once(folder, root)
        if copy not in copies:
            copies.append(copy)
    return copies


def install_relay(root: Path | None = None) -> Path:
    root = root or relay_dir()
    src = Path(__file__).resolve().parent
    try:
        root.mkdir(parents=True, exist_ok=True)
        for name in ("relay.py", "wire.py"):
            data = (src / name).read_bytes()
            dest = root / name
            if not dest.exists() or dest.read_bytes() != data:
                dest.write_bytes(data)
    except OSError as exc:
        raise RuntimeCopyError(f"Could not prepare the sandbox relay ({type(exc).__name__}).") from exc
    return root / "relay.py"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/code_sandbox/test_runtime_copy.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/runtime_copy.py tests/code_sandbox/test_runtime_copy.py
git commit -m "feat: copy tools the sandbox cannot read to a folder it can"
```

### Task 7: Background approvals and the shell gate

**Files:**
- Modify: `web/sandbox/approvals.py` (dataclass line 42, `create` 65-77, `lookup` 80-106, `decide` 124-127)
- Modify: `web/skills/shell_runner/tools.py` (add `_BG_APPROVAL_MSG` after line 579; `_shell_gate` 671-711)
- Test: `tests/code_sandbox/test_approvals.py` (append), `tests/shell_runner/test_run_shell_sandbox.py` (append)

**Interfaces:**
- Consumes: existing `approvals.create/lookup/decide`, `_shell_gate`.
- Produces:
  - `approvals.ApprovalRequest.background: bool = False`; `approvals.create(..., background=False)`; `approvals.lookup(..., background=False)` matches only requests with the same `background` value. `approvals.decide` leaves a background approval at `scope == "once"` whatever scope was asked for, so it never creates a task grant or a saved permission.
  - `shell_runner.tools._BG_APPROVAL_MSG: str`.
  - `shell_runner.tools._shell_gate(cr, command, read_paths, write_paths, hosts, context_id, policy, background=False)`. With `background=True` it always asks (even when no extra paths were requested), returns `"approved"` once the matching card was approved, never consults task grants or saved permissions, builds a non-saveable request, and adds `"background": True` to the `_sandbox_approval` card and `_BG_APPROVAL_MSG` as the message.

- [ ] **Step 1: Write the failing tests**

Append to `tests/code_sandbox/test_approvals.py`:

```python
def test_background_request_is_matched_separately():
    fg = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="npm run dev", programs=("npm",), saveable=True)
    bg = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="npm run dev", background=True)
    assert approvals.lookup("t", R, [], [], now=101.0, tool="run_shell", command="npm run dev", background=True)[1].id == bg.id
    assert approvals.lookup("t", R, [], [], now=101.0, tool="run_shell", command="npm run dev")[1].id == fg.id


@pytest.mark.parametrize("scope", ["task", "always"])
def test_background_approval_never_widens_beyond_once(scope):
    bg = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="npm run dev", background=True)
    assert approvals.decide(bg.id, "t", True, now=101.0, scope=scope).scope == "once"
```

Append to `tests/shell_runner/test_run_shell_sandbox.py`:

```python
def test_background_gate_asks_even_with_no_paths_and_approval_is_single_use(env):
    from sandbox import approvals as sandbox_approvals

    policy = sh.load_policy()
    out = sh._shell_gate(cr, "npm run dev", [], [], [], "tab", policy, background=True)
    assert out["approval_required"] is True
    assert out["message"] == sh._BG_APPROVAL_MSG and "background=true" in out["message"]
    card = out["_sandbox_approval"]
    assert card["background"] is True and card["saveable"] is False
    sandbox_approvals.decide(out["request_id"], "tab", True, scope="always")
    assert sh._shell_gate(cr, "npm run dev", [], [], [], "tab", policy, background=True) == "approved"
    again = sh._shell_gate(cr, "npm run dev", [], [], [], "tab", policy, background=True)
    assert isinstance(again, dict) and again["approval_required"] is True


def test_foreground_gate_is_unchanged_when_nothing_is_requested(env):
    assert sh._shell_gate(cr, "echo hi", [], [], [], "tab", sh.load_policy()) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/code_sandbox/test_approvals.py tests/shell_runner/test_run_shell_sandbox.py -v`
Expected: the new tests FAIL (`TypeError: ... unexpected keyword argument 'background'`).

- [ ] **Step 3: Implement**

In `web/sandbox/approvals.py`:

Dataclass: after the `scope` line add

```python
    background: bool = False  # a long-running run_shell started with background=true; never saved or task-wide
```

`create`: change the signature tail and the constructor call:

```python
def create(context_id: str, read_paths, write_paths, network_hosts, now: float | None = None, *,
           tool: str = "run_python", command: str = "", programs=None, saveable: bool = False,
           background: bool = False) -> ApprovalRequest:
```
```python
        tool=tool, command=command, programs=None if programs is None else tuple(programs), saveable=saveable,
        background=background,
```

`lookup`: add `command: str = "", background: bool = False` to the keyword-only parameters and one filter line:

```python
            and (tool != "run_shell" or r.command == command)
            and r.background == background
```

`decide`: replace the two scope branches with

```python
        if approve and scope == "task" and not req.background:
            req.scope = "task"
        elif approve and scope == "always" and req.tool == "run_shell" and not req.background:
            req.scope = "always" if req.saveable and allow_saved else "task"
```

In `web/skills/shell_runner/tools.py`, directly after the `_SHELL_APPROVAL_MSG` definition add:

```python
_BG_APPROVAL_MSG = _SHELL_APPROVAL_MSG.replace(
    "extra_write_paths and network_hosts", "extra_write_paths, network_hosts and background=true"
)
```

Replace `_shell_gate` with:

```python
def _shell_gate(cr, command, read_paths, write_paths, hosts, context_id, policy, background=False):
    """An approval decision string (None when no access was needed), or a result dict to return as is."""
    if not background and not (read_paths or write_paths or hosts):
        return None
    tab = context_id or "default"
    read_s, write_s = [str(p) for p in read_paths], [str(p) for p in write_paths]

    def telemetry(decision: str) -> dict:
        return sandbox.telemetry_record("", "run_shell", "enforced", bool(hosts),
                                        len(read_paths), len(write_paths), decision)

    status, req = sandbox_approvals.lookup(tab, read_s, write_s, hosts, tool="run_shell", command=command,
                                           background=background)
    if status == "approved":
        if background:
            return "approved"
        return {"once": "approved", "task": "task_approved", "always": "saved_created"}[req.scope]
    if status == "denied":
        return _shell_error(cr._DENIED_MSG, _sandbox_telemetry=telemetry("denied"))
    if status == "expired":
        return _shell_error(cr._EXPIRED_MSG, _sandbox_telemetry=telemetry("expired"))
    programs = programs_in(command)
    if not background:
        if task_grants.covers(tab, read_s, write_s, hosts):
            return "task_approved"
        if policy.saved_permissions != "deny" and saved_permissions.covers(read_s, write_s, hosts, programs):
            return "saved"
    if req is None:
        req = sandbox_approvals.create(
            tab, read_s, write_s, hosts, tool="run_shell", command=command,
            programs=None if programs is None else tuple(sorted(programs)),
            saveable=not background and bool(programs) and policy.saved_permissions != "deny",
            background=background,
        )
    card = {
        "request_id": req.id, "read_paths": list(req.read_paths), "write_paths": list(req.write_paths),
        "network_hosts": list(req.network_hosts), "context_id": req.context_id, "tool": "run_shell",
        "command": req.command[:2000], "saveable": bool(req.saveable),
        "programs": list(req.programs or ()),
    }
    if background:
        card["background"] = True
    return {
        "approval_required": True, "request_id": req.id, "read_paths": card["read_paths"],
        "write_paths": card["write_paths"], "network_hosts": card["network_hosts"],
        "message": _BG_APPROVAL_MSG if background else _SHELL_APPROVAL_MSG, "_sandbox_approval": card,
        "_sandbox_telemetry": telemetry("requested"),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/code_sandbox/test_approvals.py tests/shell_runner tests/test_sandbox_routes.py -v`
Expected: all pass (the existing foreground gate tests are unchanged).

- [ ] **Step 5: Commit**

```bash
git add web/sandbox/approvals.py web/skills/shell_runner/tools.py tests/code_sandbox/test_approvals.py tests/shell_runner/test_run_shell_sandbox.py
git commit -m "feat: approval requests for background shell commands"
```

### Task 8: Start background commands in the sandbox

**Files:**
- Modify: `web/skills/shell_runner/tools.py` (imports, constants, `cleanup_orphan_bg_procs`, `_spawn_background_locked`, `_tool_stop_shell_process`, `_run_sandboxed`, `TOOL_DEFS`)
- Modify: `tests/shell_runner/test_run_shell_sandbox.py` (replace `test_background_refused_when_enforced`, add the background tests)

**Interfaces:**
- Consumes: `ForwardedProcess(proc, log_file, on_close=None)` with `.start()`, `.wait_ready(timeout) -> bool`, `.url`, `.pid`, `.poll()`, `.terminate()` (Task 3); `sandbox.start_sandboxed(request)` and `sandbox.container_readable(path) -> bool` (Task 4); `runtime_copy.readable_copies(command, search_path, usable, root)`, `runtime_copy.runtime_dir()`, `runtime_copy.install_relay()`, `runtime_copy.RuntimeCopyError` (Task 6); `_shell_gate(..., background=False)` (Task 7); the relay reads its command from `AIGATOR_RELAY_COMMAND` (Task 2).
- Produces: `_run_sandboxed` returns `{"background": True, "pid", "log_file", "shell_used", "url", "_dev_server": {"pid", "url", "command"}, ...}` for a started background command (Task 9 reads `url` through the registry entry's `popen`, Task 10 reads `_dev_server`); `_BG_REGISTRY[pid]` entries with `"sandboxed": True`; `_tool_stop_shell_process` refuses a pid that is not in `_BG_REGISTRY`.

- [ ] **Step 1: Replace the old refusal test with the new tests**

In `tests/shell_runner/test_run_shell_sandbox.py`, change the imports at the top to:

```python
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

import config
import sandbox
from sandbox import approvals, runtime_copy, saved_permissions, task_grants
from sandbox.policy import Policy
from skills.code_runner import tools as cr
from skills.shell_runner import tools as sh
```

Delete `test_background_refused_when_enforced` (lines 140-142) and put this in its place:

```python
class _FakeForwarded:
    def __init__(self, proc, log_file, on_close=None):
        self.pid = 4242
        self.url = "http://127.0.0.1:3030"
        self.terminated = False

    def start(self):
        return self

    def wait_ready(self, timeout):
        return True

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True


@pytest.fixture
def bg(env):
    started = []

    def fake_start(request):
        started.append(request)
        return types.SimpleNamespace(pid=4242, terminate=lambda: None)

    relay = env.tmp / "relay" / "relay.py"
    env.mp.setattr(sh, "_bg_sandbox_supported", lambda: True)
    env.mp.setattr(sh, "ForwardedProcess", _FakeForwarded)
    env.mp.setattr(sh, "_bg_log_path", lambda: env.tmp / "bg.log")
    env.mp.setattr(sandbox, "start_sandboxed", fake_start)
    env.mp.setattr(sandbox, "container_readable", lambda p: True)
    env.mp.setattr(runtime_copy, "readable_copies", lambda *a, **k: [])
    env.mp.setattr(runtime_copy, "install_relay", lambda root=None: relay)
    yield types.SimpleNamespace(started=started, relay=relay)
    sh._BG_REGISTRY.pop(4242, None)


def test_background_refused_where_the_platform_cannot_stream(env):
    env.mp.setattr(sh, "_bg_sandbox_supported", lambda: False)
    out = _run(background=True)
    assert sh._BACKGROUND_REFUSED_MSG in out["error"] and env.fake.requests == []


def test_background_asks_first_and_starts_nothing_until_approved(env, bg):
    proj = _project(env)
    first = _run("npm run dev", background=True, cwd=str(proj))
    assert first["approval_required"] is True
    assert first["_sandbox_approval"]["background"] is True
    assert bg.started == []
    approvals.decide(first["request_id"], "tab", True)
    out = _run("npm run dev", background=True, cwd=str(proj))
    assert out["url"] == "http://127.0.0.1:3030" and out["pid"] == 4242 and out["background"] is True
    assert out["_dev_server"] == {"pid": 4242, "url": "http://127.0.0.1:3030", "command": "npm run dev"}
    assert out["sandbox"] == "enforced" and "_sandbox_telemetry" in out
    assert sh._BG_REGISTRY[4242]["sandboxed"] is True
    request = bg.started[0]
    assert json.loads(request.env["AIGATOR_RELAY_COMMAND"])[-1] == "npm run dev"
    assert request.cwd == proj and request.network is False and request.timeout == 0
    assert bg.relay.parent in request.runtime_paths
    assert env.fake.requests == []


def test_background_unattended_is_refused(env, bg):
    out = _run("npm run dev", background=True, _context_id="")
    assert "cannot run unattended" in out["error"] and bg.started == []


def test_background_cap_is_enforced(env, bg):
    sh._BG_REGISTRY[7001] = {"popen": _FakeForwarded(None, ""), "command": "x", "started_at": 0, "log_file": ""}
    try:
        env.mp.setattr(sh, "_MAX_BG_PROCS", 1)
        proj = _project(env)
        first = _run("npm run dev", background=True, cwd=str(proj))
        approvals.decide(first["request_id"], "tab", True)
        out = _run("npm run dev", background=True, cwd=str(proj))
        assert out["error"] == "BACKGROUND_PROCESS_CAP_REACHED" and bg.started == []
    finally:
        sh._BG_REGISTRY.pop(7001, None)


def test_background_runtime_copy_failure_runs_nothing(env, bg):
    def boom(*a, **k):
        raise runtime_copy.RuntimeCopyError("Node is too large to copy.")

    env.mp.setattr(runtime_copy, "readable_copies", boom)
    proj = _project(env)
    first = _run("npm run dev", background=True, cwd=str(proj))
    approvals.decide(first["request_id"], "tab", True)
    out = _run("npm run dev", background=True, cwd=str(proj))
    assert "Node is too large to copy." in out["error"] and bg.started == []


def test_background_without_a_url_yet_says_so(env, bg):
    env.mp.setattr(_FakeForwarded, "wait_ready", lambda self, timeout: False)
    proj = _project(env)
    first = _run("npm run dev", background=True, cwd=str(proj))
    approvals.decide(first["request_id"], "tab", True)
    out = _run("npm run dev", background=True, cwd=str(proj))
    assert "url" not in out and "no URL yet" in out["message"] and out["pid"] == 4242
    assert out["_dev_server"]["url"] is None


def test_background_that_exits_before_printing_an_address_is_an_error(env, bg):
    env.mp.setattr(_FakeForwarded, "wait_ready", lambda self, timeout: False)
    env.mp.setattr(_FakeForwarded, "poll", lambda self: 1)
    (env.tmp / "bg.log").write_text("boom: port in use", encoding="utf-8")
    proj = _project(env)
    first = _run("npm run dev", background=True, cwd=str(proj))
    approvals.decide(first["request_id"], "tab", True)
    out = _run("npm run dev", background=True, cwd=str(proj))
    assert "exited with code 1" in out["error"] and "port in use" in out["error"]


def test_stop_refuses_a_pid_that_was_not_started_by_run_shell():
    out = sh._tool_stop_shell_process(999999)
    assert out["stopped"] is False and "was not started by run_shell" in out["message"]


def test_stop_terminates_a_sandboxed_entry():
    fake = _FakeForwarded(None, "")
    sh._BG_REGISTRY[4243] = {"popen": fake, "command": "npm run dev", "sandboxed": True}
    try:
        out = sh._tool_stop_shell_process(4243)
        assert out["stopped"] is True and fake.terminated is True
    finally:
        sh._BG_REGISTRY.pop(4243, None)


def _sleeper():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])


def _record(pidfile, pid, command):
    pidfile.write_text(json.dumps({str(pid): {"command": command, "log_file": "", "started_at": 0}}))


def test_orphan_cleanup_leaves_a_pid_alone_when_the_command_does_not_match(env):
    proc = _sleeper()
    try:
        pidfile = env.tmp / "bg-pids.json"
        env.mp.setattr(sh, "_bg_pid_file", lambda: pidfile)
        _record(pidfile, proc.pid, "npm run dev")
        sh.cleanup_orphan_bg_procs()
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()


def test_orphan_cleanup_kills_a_pid_whose_command_matches(env):
    proc = _sleeper()
    try:
        pidfile = env.tmp / "bg-pids.json"
        env.mp.setattr(sh, "_bg_pid_file", lambda: pidfile)
        _record(pidfile, proc.pid, '-c "import time; time.sleep(30)"')
        sh.cleanup_orphan_bg_procs()
        proc.wait(timeout=10)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tests/shell_runner/test_run_shell_sandbox.py -v -k "background or stop or orphan"`
Expected: FAIL (`AttributeError: ... has no attribute '_bg_sandbox_supported'`, and the orphan test for a non-matching command fails because the process is killed).

- [ ] **Step 3: Add the imports and constants**

In `web/skills/shell_runner/tools.py`, change the import block at the top. Add `import json` after `import itertools`, and add the two sandbox imports after `from sandbox import saved_permissions, task_grants`:

```python
import functools
import itertools
import json
import os
```

```python
from sandbox import approvals as sandbox_approvals
from sandbox import runtime_copy, saved_permissions, task_grants
from sandbox.forward import ForwardedProcess
```

Add this right after `_BACKGROUND_REFUSED_MSG = (...)` (the constant ending at the line `")"` before `_SHELL_APPROVAL_MSG`):

```python
_BG_READY_TIMEOUT = 30
_BG_UNATTENDED_MSG = (
    "A background command needs a person in a chat tab to approve it and to use the forwarded port, so it "
    "cannot run unattended. Do not retry."
)


def _bg_sandbox_supported() -> bool:
    return os.name == "nt"
```

- [ ] **Step 4: Verify the command line before killing an orphan**

In `cleanup_orphan_bg_procs`, replace

```python
    for pid_str, info in list(existing.items()):
        pid = int(pid_str)
        try:
            proc = psutil.Process(pid)
            # Only kill if it's actually still running and looks like a bg task
            if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
```

with

```python
    for pid_str, info in list(existing.items()):
        pid = int(pid_str)
        try:
            proc = psutil.Process(pid)
            recorded = _norm_cmd(info.get("command", ""))
            if not recorded or recorded not in _norm_cmd(" ".join(proc.cmdline())):
                continue
            # Only kill if it's actually still running and looks like a bg task
            if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
```

and add this helper directly above `def cleanup_orphan_bg_procs():`:

```python
def _norm_cmd(text: str) -> str:
    return re.sub(r"[\s\"\\']+", "", text or "")
```

The inner `import json, psutil` in `cleanup_orphan_bg_procs` can stay as it is.

- [ ] **Step 5: Extract the cap check so both spawn paths share it**

In `_spawn_background_locked`, replace the block from `# Count currently running background processes` through the closing `}` of the cap-reached return:

```python
    # Count currently running background processes
    running_procs = [
        {"pid": pid, "command": e.get("command", "")[:80],
         "started_at": e.get("started_at", 0), "log_file": e.get("log_file", "")}
        for pid, e in _BG_REGISTRY.items()
        if e.get("popen") and e["popen"].poll() is None and not e.get("stopped")
    ]
    if len(running_procs) >= _MAX_BG_PROCS:
        return {
            "error": "BACKGROUND_PROCESS_CAP_REACHED",
            "cap": _MAX_BG_PROCS,
            "running": running_procs,
            "background": True, "pid": 0, "log_file": "", "shell_used": shell_used,
        }
```

with

```python
    capped = _bg_cap_error(shell_used)
    if capped:
        return capped
```

and add this above `def _spawn_background(`:

```python
def _bg_cap_error(shell_used: str) -> dict | None:
    running_procs = [
        {"pid": pid, "command": e.get("command", "")[:80],
         "started_at": e.get("started_at", 0), "log_file": e.get("log_file", "")}
        for pid, e in _BG_REGISTRY.items()
        if e.get("popen") and e["popen"].poll() is None and not e.get("stopped")
    ]
    if len(running_procs) < _MAX_BG_PROCS:
        return None
    return {
        "error": "BACKGROUND_PROCESS_CAP_REACHED",
        "cap": _MAX_BG_PROCS,
        "running": running_procs,
        "background": True, "pid": 0, "log_file": "", "shell_used": shell_used,
    }
```

- [ ] **Step 6: Make stop refuse unknown pids and terminate sandboxed ones**

In `_tool_stop_shell_process`, directly after `entry = _BG_REGISTRY.get(pid)` add:

```python
    if entry is None:
        return {
            "stopped": False,
            "pid": pid,
            "message": f"Process {pid} was not started by run_shell(background=true), so it will not be stopped.",
        }
    if entry.get("sandboxed"):
        entry["popen"].terminate()
        entry["stopped"] = True
        return {"stopped": True, "pid": pid, "message": f"Stopped process {pid} and its child processes."}
```

The later `if entry is not None:` check in the `psutil.NoSuchProcess` branch stays as it is.

- [ ] **Step 7: Start the relay from `_run_sandboxed`**

Replace the first two lines of `_run_sandboxed`

```python
    if background:
        return _shell_error(_BACKGROUND_REFUSED_MSG)
```

with

```python
    if background and not _bg_sandbox_supported():
        return _shell_error(_BACKGROUND_REFUSED_MSG)
    if background and not context_id:
        return _shell_error(_BG_UNATTENDED_MSG)
```

Pass the flag to the gate. Replace

```python
    gate = _shell_gate(cr, command, read_paths, write_paths, hosts, context_id, policy)
```

with

```python
    gate = _shell_gate(cr, command, read_paths, write_paths, hosts, context_id, policy, background=background)
```

Replace

```python
    runtime_paths = cr._runtime_paths(None, npm_root)
    if any(cr._runtime_path_refused(p) for p in runtime_paths):
```

with

```python
    runtime_paths = cr._runtime_paths(None, npm_root)
    copies: list = []
    relay = None
    if background:
        try:
            runtime_paths = [p for p in runtime_paths if sandbox.container_readable(p)]
            copies = runtime_copy.readable_copies(
                command, os.environ.get("PATH", ""), sandbox.container_readable, runtime_copy.runtime_dir())
            relay = runtime_copy.install_relay()
        except runtime_copy.RuntimeCopyError as exc:
            return _shell_error(f"{exc} Nothing was run.", shell_used)
        runtime_paths = [*runtime_paths, *copies, relay.parent]
    if any(cr._runtime_path_refused(p) for p in runtime_paths):
```

Insert this between the `tags = {...}` line and `watch_dirs = watched_output_dirs(str(run_cwd))`:

```python
    if background:
        relay_env = sandbox.build_env(os.environ, env_dir, npm_root, path_prepend=[*copies, *cr._skill_bin_dirs()])
        relay_env["AIGATOR_RELAY_COMMAND"] = json.dumps(argv_prefix + [command])
        request = sandbox.SandboxRequest(
            argv=cr._python_command(relay), cwd=run_cwd, env=relay_env, runtime_paths=runtime_paths,
            read_paths=list(read_paths), write_paths=sandbox_write, network=bool(hosts), timeout=0,
            scratch_path=scratch,
        )
        return _start_background(cr, request, command, shell_used, env_dir, in_scratch, tags)
```

Add `_start_background` directly above `def _run_unsandboxed(`:

```python
def _start_background(cr, request, command, shell_used, env_dir, in_scratch, tags) -> dict:
    cleanup = None if in_scratch else (lambda: shutil.rmtree(env_dir, ignore_errors=True))
    handed_off = False
    try:
        with _BG_SPAWN_LOCK:
            capped = _bg_cap_error(shell_used)
            if capped:
                return {**capped, **tags}
            try:
                log_path = _bg_log_path()
            except OSError as exc:
                return _shell_error(f"Could not prepare background log dir: {exc}", shell_used,
                                    background=True, pid=0, log_file="", **tags)
            try:
                proc = sandbox.start_sandboxed(request)
            except sandbox.SandboxUnavailable as exc:
                return _shell_error(cr._launch_refusal_message(exc), shell_used, **tags)
            except sandbox.SandboxRunError:
                return _shell_error(cr._RUN_ERROR_MSG, shell_used, **tags)
            except (NotImplementedError, OSError) as exc:
                return _shell_error(f"Could not start the command in the sandbox ({type(exc).__name__}). "
                                    "Nothing was run.", shell_used, **tags)
            try:
                fp = ForwardedProcess(proc, str(log_path), on_close=cleanup).start()
            except OSError as exc:
                proc.terminate()
                return _shell_error(f"Could not open background log file: {exc}", shell_used,
                                    background=True, pid=0, log_file=str(log_path), **tags)
            handed_off = True
            _BG_REGISTRY[fp.pid] = {
                "popen": fp, "command": command, "log_file": str(log_path), "cwd": str(request.cwd),
                "shell_used": shell_used, "started_at": time.time(), "sandboxed": True,
            }
    finally:
        if cleanup and not handed_off:
            cleanup()

    result = {"background": True, "pid": fp.pid, "log_file": str(log_path), "shell_used": shell_used, **tags}
    if fp.wait_ready(_BG_READY_TIMEOUT):
        result["url"] = fp.url
        result["_dev_server"] = {"pid": fp.pid, "url": fp.url, "command": command[:200]}
        result["message"] = (f"Started in the sandbox and available at {fp.url}. Tell the user this address. "
                             f"Use stop_shell_process({fp.pid}) to stop it.")
    elif fp.poll() is None:
        result["_dev_server"] = {"pid": fp.pid, "url": None, "command": command[:200]}
        result["message"] = (f"Started in the sandbox (pid {fp.pid}), no URL yet. "
                             f"Use check_shell_process({fp.pid}).")
    else:
        tail = _read_log_tail(str(log_path))
        result["error"] = f"The command exited with code {fp.poll()} before it printed a local address. {tail}".strip()
    return result
```

- [ ] **Step 8: Update the tool description**

In `TOOL_DEFS`, replace

```python
            "background=true is not available with the sandbox on. "
            "Use file_ops tools for simple read/write/list — use run_shell when you need a full command pipeline. "
            "Only when the sandbox is off: for a long-running process that does not exit on its own — an LLM "
            'inference server, a dev server (`npm run dev`), a foreground `docker run`, or `ssh host "<server>"` — '
            "set background=true. It returns "
            "immediately with a pid + log_file instead of blocking until timeout. Then use check_shell_process(pid) "
            "to confirm it started (e.g. look for a 'listening on port' line in log_tail) and stop_shell_process(pid) "
            "to stop it."
```

with

```python
            "Inspect a project with list_dir, read_file and grep_files and change it with write_file or edit_file; "
            "use run_shell when you need a full command pipeline. "
            "For a long-running process that does not exit on its own — an LLM "
            'inference server, a dev server (`npm run dev`), a foreground `docker run`, or `ssh host "<server>"` — '
            "set background=true. It returns "
            "immediately with a pid + log_file instead of blocking until timeout. Then use check_shell_process(pid) "
            "to confirm it started (e.g. look for a 'listening on port' line in log_tail) and stop_shell_process(pid) "
            "to stop it. On Windows with the sandbox on, background=true runs the command in the sandbox after the "
            "user approves it, forwards the first localhost port the command prints, and returns url once the "
            "server prints its address (it waits up to 30s). Tell the user the url so they can open it."
```

Replace the `background` property description

```python
                        "Only when the sandbox is off (refused with the sandbox on): run the command "
                        "detached/non-blocking instead of waiting for it to exit. Use for servers "
                        "and other long-running processes. Returns immediately with {pid, log_file} — poll with "
                        "check_shell_process, stop with stop_shell_process. Default false."
```

with

```python
                        "Run the command detached/non-blocking instead of waiting for it to exit. Use for servers "
                        "and other long-running processes. With the sandbox on (Windows) it needs a person in a "
                        "chat tab, shows the approval card, and returns {pid, log_file, url}. Poll with "
                        "check_shell_process, stop with stop_shell_process. Default false."
```

- [ ] **Step 9: Run the tests to see them pass**

Run: `python -m pytest tests/shell_runner web/tests/test_shell_background.py tests/code_sandbox/test_approvals.py -v`
Expected: PASS. `web/tests/test_shell_background.py` runs with the sandbox off and every pid it stops is registered, so the new stop guard does not change it.

- [ ] **Step 10: Commit**

```bash
git add web/skills/shell_runner/tools.py tests/shell_runner/test_run_shell_sandbox.py
git commit -m "feat: run background shell commands in the sandbox and forward their localhost port"
```

### Task 9: Guard the stop route and list the forwarded url

**Files:**
- Modify: `web/routes/tasks.py:252-281`
- Modify: `tests/csrf_route_baseline.txt` (delete line 85)
- Create: `tests/test_background_process_routes.py`

**Interfaces:**
- Consumes: `_BG_REGISTRY` entries from Task 8, whose `popen` is a `ForwardedProcess` with a `url` attribute (plain `Popen` objects have none).
- Produces: `GET /api/shell/background-processes` items carry `"url": str | None`; `POST /api/shell/background-processes/{pid}/stop` needs the CSRF token and returns 404 for a pid that is not in `_BG_REGISTRY` (Task 11 sends the token and reads `url`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_background_process_routes.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi.testclient import TestClient

from app import app
from skills.shell_runner import tools as sh


class _Proc:
    def __init__(self, url=None):
        self.url = url
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def csrf():
    from security import get_csrf_token

    return {"X-CSRF-Token": get_csrf_token("testserver")}


@pytest.fixture
def registered():
    forwarded = _Proc("http://127.0.0.1:3030")
    plain = _Proc()
    sh._BG_REGISTRY[5001] = {"popen": forwarded, "command": "npm run dev", "sandboxed": True, "started_at": 1}
    sh._BG_REGISTRY[5002] = {"popen": plain, "command": "sleep 5", "started_at": 1}
    yield forwarded
    sh._BG_REGISTRY.pop(5001, None)
    sh._BG_REGISTRY.pop(5002, None)


def test_list_carries_the_forwarded_url(client, registered):
    procs = {p["pid"]: p for p in client.get("/api/shell/background-processes").json()["processes"]}
    assert procs[5001]["url"] == "http://127.0.0.1:3030"
    assert procs[5002]["url"] is None


def test_stop_needs_the_csrf_token(client, registered):
    assert client.post("/api/shell/background-processes/5001/stop").status_code == 403
    assert registered.terminated is False


def test_stop_unknown_pid_is_404(client, csrf):
    assert client.post("/api/shell/background-processes/999999/stop", headers=csrf).status_code == 404


def test_stop_terminates_a_sandboxed_process(client, csrf, registered):
    r = client.post("/api/shell/background-processes/5001/stop", headers=csrf)
    assert r.status_code == 200 and r.json()["stopped"] is True
    assert registered.terminated is True
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tests/test_background_process_routes.py -v`
Expected: FAIL (`KeyError: 'url'`, the stop without a token returns 200, the unknown pid returns 200).

- [ ] **Step 3: Implement the route changes**

In `web/routes/tasks.py`, add `"url": getattr(popen, "url", None),` after the `"shell_used"` line of the list entry:

```python
            "shell_used": e.get("shell_used", ""),
            "url": getattr(popen, "url", None),
        })
```

Replace the stop route with:

```python
@router.post("/api/shell/background-processes/{pid}/stop", dependencies=[Depends(verify_csrf)])
async def stop_background_process(pid: int):
    """Stop a specific background process by PID."""
    from skills.shell_runner.tools import _BG_REGISTRY, _tool_stop_shell_process
    import asyncio
    if pid not in _BG_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown background process")
    result = await asyncio.to_thread(_tool_stop_shell_process, pid)
    return result
```

Delete the line `POST /api/shell/background-processes/{pid}/stop` (line 85) from `tests/csrf_route_baseline.txt`. Do not add anything to that file.

- [ ] **Step 4: Run the tests to see them pass**

Run: `python -m pytest tests/test_background_process_routes.py tests/test_csrf_route_inventory.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/routes/tasks.py tests/csrf_route_baseline.txt tests/test_background_process_routes.py
git commit -m "feat: require the CSRF token to stop a background process and list its forwarded url"
```

### Task 10: Send the dev server result to the chat stream

**Files:**
- Modify: `web/agent_loop.py:1059-1060` (tool runner), `web/agent_loop.py:1538-1539` and `web/agent_loop.py:2098-2099` (the two SSE forwarders)
- Test: `tests/test_agent_loop_sandbox.py`

**Interfaces:**
- Consumes: a tool result with `"_dev_server": {"pid": int, "url": str | None, "command": str}` (Task 8).
- Produces: an SSE message `{"dev_server": {"pid", "url", "command"}}` on both chat streams (Task 11 renders it).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_loop_sandbox.py`, after `test_both_stream_loops_forward_sandbox_approval`:

```python
def test_runner_emits_dev_server_event():
    info = {"pid": 4242, "url": "http://127.0.0.1:3030", "command": "npm run dev"}

    async def fake_execute(name, inputs, **kw):
        return {"background": True, "pid": 4242, "url": info["url"], "_dev_server": info}

    run_tool_block, _, _ = _make_tool_runner(fake_execute, set(), {}, lambda n, r: None, "__slack_safe__")

    async def go():
        q = asyncio.Queue()
        await run_tool_block(SimpleNamespace(name="run_shell", inputs={"command": "npm run dev"}, id="c1"), q)
        return [q.get_nowait() for _ in range(q.qsize())]

    loop = asyncio.new_event_loop()
    try:
        events = loop.run_until_complete(go())
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())
    assert {"kind": "dev_server", "data": info} in events


def test_both_stream_loops_forward_dev_server():
    src = (pathlib.Path(__file__).parent.parent / "web" / "agent_loop.py").read_text(encoding="utf-8")
    assert src.count("yield f\"data: {json.dumps({'dev_server': evt.get('data', {})})}\\n\\n\"") == 2
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tests/test_agent_loop_sandbox.py -v -k dev_server`
Expected: FAIL (the event is missing, the count is 0).

- [ ] **Step 3: Implement**

In `web/agent_loop.py`, after the `_sandbox_approval` emit (line 1060) add:

```python
        if isinstance(result, dict) and "_dev_server" in result:
            await event_queue.put({"kind": "dev_server", "data": result["_dev_server"]})
```

At both forwarders (the `elif kind == "sandbox_approval":` branches near lines 1538 and 2098), add directly after the two `sandbox_approval` lines:

```python
                elif kind == "dev_server":
                    yield f"data: {json.dumps({'dev_server': evt.get('data', {})})}\n\n"
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `python -m pytest tests/test_agent_loop_sandbox.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/agent_loop.py tests/test_agent_loop_sandbox.py
git commit -m "feat: stream the started dev server to the chat"
```

### Task 11: Frontend: background card line, running-server card, CSRF-aware Stop

**Files:**
- Modify: `web/static/app.js` (`_showSandboxApproval` ~10197-10402; new functions placed directly after it; SSE chain at ~14179)
- Modify: `web/static/agents-pane.js:270` (Stop button)
- Create: `tests/dev_server_card.test.js`
- Modify: `tests/sandbox_ui.test.js` (add a background-card block before the `// ── Settings: Saved permissions ──` line)

**Interfaces:**
- Consumes: the `_sandbox_approval` card payload with `background: true` (Task 7); the chat stream message `{"dev_server": {"pid": int, "url": str|null, "command": str}}` (Task 10); `GET /api/shell/background-processes` returning `{"processes": [{"pid", "running", ...}], "count"}` and `POST /api/shell/background-processes/{pid}/stop` (Task 9).
- Produces (all plain top-level function declarations in `app.js`, so `agents-pane.js`, loaded after it, sees them):
  - `async function _postBackgroundStop(pid)`: POSTs the stop route with `X-CSRF-Token`; on 403 refreshes the token from `/api/csrf` and retries once; returns the `Response`.
  - `function _devServerUrl(url)`: returns `url` when it is a string matching `^https?://(localhost|127.0.0.1|[::1]):<1-5 digits>(/|$)`, else `''`. The regex is local to the function, so nothing new is read during startup (see `tests/startup_const_order.test.js`).
  - `function _showDevServerCard(data, ownerTabId)`: draws the status card.

- [ ] **Step 1: Write the failing tests**

Create `tests/dev_server_card.test.js`:

```js
// Dev server status card: where it runs, an Open link only for localhost URLs, Stop with the CSRF
// token, and polling that turns the card into "Stopped". Functions are extracted from app.js
// and run against a tiny fake DOM, as in sandbox_ui.test.js.

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'static', 'app.js'), 'utf8');
const panes = fs.readFileSync(
  path.join(__dirname, '..', 'web', 'static', 'agents-pane.js'),
  'utf8',
);

function extract(name) {
  const match = source.match(
    new RegExp(`(?:async )?function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`),
  );
  assert(match, `${name} not found in app.js`);
  return match[0];
}

function makeEl(tag) {
  return {
    tag,
    children: [],
    dataset: {},
    listeners: {},
    className: '',
    disabled: false,
    isConnected: true,
    _text: '',
    set innerHTML(_v) {
      throw new Error('innerHTML must never be used for the dev server card');
    },
    set textContent(v) {
      this._text = String(v);
      this.children = [];
    },
    get textContent() {
      return this._text + this.children.map((c) => c.textContent).join('');
    },
    appendChild(c) {
      this.children.push(c);
      c.parent = this;
      return c;
    },
    append(...cs) {
      cs.forEach((c) => this.appendChild(c));
    },
    addEventListener(type, fn) {
      this.listeners[type] = fn;
    },
    remove() {
      this.isConnected = false;
      if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this);
    },
    scrollIntoView() {},
  };
}

function walk(el, out = []) {
  out.push(el);
  el.children.forEach((c) => walk(c, out));
  return out;
}

function makeEnv({ activeTab = 'tab-1', processes = [] } = {}) {
  const messages = makeEl('div');
  const toasts = [];
  const fetches = [];
  const timers = [];
  const state = { processes, stopStatus: 200 };
  const ctx = {
    document: {
      createElement: makeEl,
      getElementById: (id) => (id === 'messages' ? messages : null),
      querySelectorAll: () => walk(messages).filter((e) => e.dataset && e.dataset.devServerPid),
    },
    window: { __CSRF_TOKEN__: 'aigator-fake-api-key' },
    _activeTabId: activeTab,
    _showConnectivityToast: (msg, type) => toasts.push({ msg, type }),
    setInterval: (fn, ms) => {
      timers.push({ fn, ms, cleared: false });
      return timers.length - 1;
    },
    clearInterval: (id) => {
      if (timers[id]) timers[id].cleared = true;
    },
    fetch: async (url, opts = {}) => {
      fetches.push({ url, method: opts.method || 'GET', headers: opts.headers });
      if (url === '/api/shell/background-processes') {
        return { ok: true, status: 200, json: async () => ({ processes: state.processes }) };
      }
      return { ok: state.stopStatus < 400, status: state.stopStatus, json: async () => ({}) };
    },
    encodeURIComponent,
    Number,
    String,
    Array,
    Promise,
  };
  vm.createContext(ctx);
  ['_postBackgroundStop', '_devServerUrl', '_showDevServerCard'].forEach((n) =>
    vm.runInContext(extract(n), ctx),
  );
  return { ctx, messages, toasts, fetches, timers, state };
}

const titleOf = (env) => walk(env.messages).find((e) => e.className === 'gcc-title')._text;
const buttonsOf = (env) => walk(env.messages).filter((e) => e.tag === 'button');
const linkOf = (env) => walk(env.messages).find((e) => e.tag === 'a');
const click = { stopPropagation() {} };

(async () => {
  const url = 'http://127.0.0.1:3030';

  // Only plain localhost origins pass; look-alike hosts and other schemes do not.
  const probe = makeEnv();
  for (const ok of [url, 'http://localhost:5173/', 'http://[::1]:8080', 'https://localhost:443/x']) {
    assert.strictEqual(probe.ctx._devServerUrl(ok), ok);
  }
  for (const bad of [
    'http://localhost.evil.com:80',
    'http://evil.com:3000',
    'http://localhost:3030@evil.com',
    'http://localhost:3030.evil.com',
    'http://localhost',
    'javascript:alert(1)',
    '',
    undefined,
    null,
    42,
  ]) {
    assert.strictEqual(probe.ctx._devServerUrl(bad), '', String(bad));
  }

  // With a url: title, an Open link that leaves the app safely, and a Stop button. Drawn once.
  const a = makeEnv();
  a.ctx._showDevServerCard({ pid: 7, url, command: 'npm run dev' }, 'tab-1');
  assert.strictEqual(a.messages.children.length, 1);
  assert.strictEqual(titleOf(a), `Running at ${url}`);
  const link = linkOf(a);
  assert.strictEqual(link.href, url);
  assert.strictEqual(link.target, '_blank');
  assert.match(link.rel, /noopener/);
  assert.strictEqual(link.textContent, 'Open');
  assert.deepStrictEqual(
    buttonsOf(a).map((b) => b.textContent),
    ['Stop'],
  );
  assert.strictEqual(a.fetches.length, 0, 'drawing the card sends nothing');
  assert.strictEqual(a.timers.length, 1);
  assert.strictEqual(a.timers[0].ms, 5000);
  a.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  assert.strictEqual(a.messages.children.length, 1, 'same pid is not drawn twice');
  assert.strictEqual(a.timers.length, 1);

  // A url that is not localhost is shown without a link; no url shows the pid.
  const evil = makeEnv();
  evil.ctx._showDevServerCard({ pid: 8, url: 'http://localhost.evil.com:80' }, 'tab-1');
  assert.strictEqual(titleOf(evil), 'Running (pid 8)');
  assert.strictEqual(linkOf(evil), undefined);
  const bare = makeEnv();
  bare.ctx._showDevServerCard({ pid: 9, url: null }, 'tab-1');
  assert.strictEqual(titleOf(bare), 'Running (pid 9)');
  assert.strictEqual(linkOf(bare), undefined);
  assert.deepStrictEqual(
    buttonsOf(bare).map((b) => b.textContent),
    ['Stop'],
  );

  // Nothing is drawn without a pid, or for a tab the user is not looking at.
  const none = makeEnv();
  none.ctx._showDevServerCard({}, 'tab-1');
  assert.strictEqual(none.messages.children.length, 0);
  const other = makeEnv({ activeTab: 'tab-2' });
  other.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  assert.strictEqual(other.messages.children.length, 0);
  assert.strictEqual(other.toasts.length, 1);

  // Stop: CSRF POST for this pid, then the card says Stopped and drops its buttons.
  const s = makeEnv();
  s.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  await buttonsOf(s)[0].listeners.click(click);
  assert.strictEqual(s.fetches[0].url, '/api/shell/background-processes/7/stop');
  assert.strictEqual(s.fetches[0].method, 'POST');
  assert.strictEqual(s.fetches[0].headers['X-CSRF-Token'], 'aigator-fake-api-key');
  assert.strictEqual(titleOf(s), 'Stopped');
  assert.strictEqual(buttonsOf(s).length, 0);
  assert.strictEqual(linkOf(s), undefined);
  assert.strictEqual(s.timers[0].cleared, true);

  // A failed Stop keeps the card, re-enables the button and says so. 404 means already gone.
  const f = makeEnv();
  f.state.stopStatus = 500;
  f.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  const stop = buttonsOf(f)[0];
  await stop.listeners.click(click);
  assert.strictEqual(stop.disabled, false);
  assert.strictEqual(titleOf(f), `Running at ${url}`);
  assert.strictEqual(f.toasts.length, 1);
  f.state.stopStatus = 404;
  await stop.listeners.click(click);
  assert.strictEqual(titleOf(f), 'Stopped');

  // Polling: a running pid leaves the card alone; a missing or not-running pid ends it.
  const p = makeEnv({ processes: [{ pid: 7, running: true }] });
  p.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  await p.timers[0].fn();
  assert.strictEqual(p.fetches[0].url, '/api/shell/background-processes');
  assert.strictEqual(titleOf(p), `Running at ${url}`);
  p.state.processes = [{ pid: 7, running: false }];
  await p.timers[0].fn();
  assert.strictEqual(titleOf(p), 'Stopped');
  assert.strictEqual(p.timers[0].cleared, true);
  const gone = makeEnv({ processes: [] });
  gone.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  await gone.timers[0].fn();
  assert.strictEqual(titleOf(gone), 'Stopped');

  // A card that left the page stops polling; a failed poll changes nothing.
  const left = makeEnv();
  left.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  left.messages.children[0].remove();
  await left.timers[0].fn();
  assert.strictEqual(left.fetches.length, 0);
  assert.strictEqual(left.timers[0].cleared, true);
  const down = makeEnv();
  down.ctx._showDevServerCard({ pid: 7, url }, 'tab-1');
  down.ctx.fetch = async () => {
    throw new Error('offline');
  };
  await down.timers[0].fn();
  assert.strictEqual(titleOf(down), `Running at ${url}`);

  // A stale CSRF token is refreshed once and the stop is retried with the new one.
  const r = makeEnv();
  const seen = [];
  let posts = 0;
  r.ctx.fetch = async (u, opts = {}) => {
    seen.push({ u, token: opts.headers && opts.headers['X-CSRF-Token'] });
    if (u === '/api/csrf') {
      return { ok: true, status: 200, json: async () => ({ csrf_token: 'fresh-token' }) };
    }
    posts += 1;
    return { ok: posts > 1, status: posts > 1 ? 200 : 403, json: async () => ({}) };
  };
  const res = await r.ctx._postBackgroundStop(7);
  assert.strictEqual(res.status, 200);
  assert.deepStrictEqual(
    seen.map((x) => x.u),
    [
      '/api/shell/background-processes/7/stop',
      '/api/csrf',
      '/api/shell/background-processes/7/stop',
    ],
  );
  assert.strictEqual(seen[0].token, 'aigator-fake-api-key');
  assert.strictEqual(seen[2].token, 'fresh-token');

  // Wiring and safety.
  for (const name of ['_postBackgroundStop', '_devServerUrl', '_showDevServerCard']) {
    assert(!/innerHTML/.test(extract(name)), `${name} must not use innerHTML`);
  }
  assert(source.includes('_showDevServerCard(msg.dev_server, requestTabId)'));
  assert(panes.includes('_postBackgroundStop(proc.pid)'), 'agents pane stops through the helper');
  assert(!/background-processes\/\$\{proc\.pid\}\/stop/.test(panes), 'no bare stop fetch left');

  console.log('dev_server_card: all assertions passed');
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

In `tests/sandbox_ui.test.js`, replace the single line `  // ── Settings: Saved permissions ──` with this block followed by that same line:

```js
  // A background run says where the server will be reachable, and its Allow button does not
  // claim a tab-long grant (the server keeps a background approval single-use).
  const envB = makeEnv('tab-1');
  envB.ctx._showSandboxApproval(
    { ...shellCard, request_id: 'sh5', background: true, saveable: false, network_hosts: [] },
    'tab-1',
  );
  const allB = walk(envB.messages);
  assert(
    allB.some((e) => e._text === 'Runs in the sandbox and is made available at localhost.'),
    'background card says it is made available at localhost',
  );
  assert.deepStrictEqual(
    allB.filter((e) => e.tag === 'button').map((b) => b.textContent),
    ['Allow', 'Deny'],
  );
  assert(!allB.some((e) => /Allowed until you close this tab/.test(e._text)));
  assert(
    !allS.some((e) => /made available at localhost/.test(e._text)),
    'a plain command card does not say it',
  );

  // ── Settings: Saved permissions ──
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `node tests/dev_server_card.test.js`
Expected: FAIL with `_postBackgroundStop not found in app.js`.

Run: `node tests/sandbox_ui.test.js`
Expected: FAIL at "background card says it is made available at localhost".

- [ ] **Step 3: Implement**

All edits in `web/static/app.js`.

3a. In `_showSandboxApproval`, directly after `const tool = isShell ? 'run_shell' : 'run_python';` add:

```js
  const isBackground = isShell && data.background === true;
```

3b. Directly after the `body.appendChild(risk);` block (the closing `}` of the `if` that adds the Always-allow risk note, before `const actions = document.createElement('div');`) add:

```js
  if (isBackground) {
    const where = document.createElement('div');
    where.className = 'gcc-refine';
    where.textContent = 'Runs in the sandbox and is made available at localhost.';
    body.appendChild(where);
  }
```

3c. Replace `approve.textContent = 'Allow for this tab';` with:

```js
  approve.textContent = isBackground ? 'Allow' : 'Allow for this tab';
```

3d. Replace the `footNote.textContent = ...` statement (the two-line one that starts `footNote.textContent =` and ends `'Allowed until you close this tab. Unanswered requests expire after 10 minutes.';`) with:

```js
  footNote.textContent = isBackground
    ? 'Unanswered requests expire after 10 minutes.'
    : 'Allowed until you close this tab. Unanswered requests expire after 10 minutes.';
```

3e. Replace `} else outcome = 'Allowed for this tab.';` with:

```js
        } else outcome = isBackground ? 'Allowed.' : 'Allowed for this tab.';
```

3f. Directly after the closing `}` of `_showSandboxApproval` (just before the `// Navigate the relevant native app after a draft is approved` comment) add:

```js
async function _postBackgroundStop(pid) {
  const post = () =>
    fetch(`/api/shell/background-processes/${encodeURIComponent(pid)}/stop`, {
      method: 'POST',
      headers: { 'X-CSRF-Token': window.__CSRF_TOKEN__ || '' },
    });
  let res = await post();
  if (res.status === 403) {
    // The token is per server process; a page loaded before a restart holds a stale one.
    const fresh = await fetch('/api/csrf')
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
    if (fresh?.csrf_token) window.__CSRF_TOKEN__ = fresh.csrf_token;
    res = await post();
  }
  return res;
}

function _devServerUrl(url) {
  return typeof url === 'string' && /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\]):\d{1,5}(\/|$)/.test(url)
    ? url
    : '';
}

function _showDevServerCard(data, ownerTabId) {
  const pid = data && Number.isInteger(data.pid) ? data.pid : 0;
  if (!pid) return;
  if (ownerTabId && ownerTabId !== _activeTabId) {
    _showConnectivityToast('A dev server started in another tab.', 'info');
    return;
  }
  const seen = Array.from(document.querySelectorAll('[data-dev-server-pid]')).some(
    (el) => el.dataset.devServerPid === String(pid),
  );
  if (seen) return;
  const url = _devServerUrl(data.url);

  const card = document.createElement('div');
  card.className = 'message assistant';
  card.dataset.devServerPid = String(pid);
  const bubble = document.createElement('div');
  bubble.className = 'bubble card-bubble';
  const box = document.createElement('div');
  box.className = 'gator-compose-card gator-draft-card';
  const header = document.createElement('div');
  header.className = 'gcc-header';
  const title = document.createElement('div');
  title.className = 'gcc-title';
  title.textContent = url ? `Running at ${url}` : `Running (pid ${pid})`;
  header.appendChild(title);

  const actions = document.createElement('div');
  actions.className = 'gcc-actions';
  let openLink = null;
  if (url) {
    openLink = document.createElement('a');
    openLink.className = 'btn-secondary';
    openLink.href = url;
    openLink.target = '_blank';
    openLink.rel = 'noopener noreferrer';
    openLink.textContent = 'Open';
    actions.appendChild(openLink);
  }
  const stop = document.createElement('button');
  stop.className = 'btn-secondary';
  stop.textContent = 'Stop';
  actions.appendChild(stop);

  box.append(header, actions);
  bubble.appendChild(box);
  card.appendChild(bubble);

  let timer = null;
  const markStopped = () => {
    clearInterval(timer);
    title.textContent = 'Stopped';
    stop.remove();
    if (openLink) openLink.remove();
  };
  stop.addEventListener('click', async (e) => {
    e.stopPropagation();
    stop.disabled = true;
    try {
      const res = await _postBackgroundStop(pid);
      if (!res.ok && res.status !== 404) throw new Error(`HTTP ${res.status}`);
      markStopped();
    } catch (err) {
      stop.disabled = false;
      _showConnectivityToast(`Could not stop the server: ${err.message}`, 'warn');
    }
  });
  timer = setInterval(async () => {
    if (!card.isConnected) {
      clearInterval(timer);
      return;
    }
    try {
      const res = await fetch('/api/shell/background-processes');
      if (!res.ok) return;
      const body = await res.json();
      const alive = (body.processes || []).some((p) => p.pid === pid && p.running);
      if (!alive) markStopped();
    } catch (_) {
      /* the next tick tries again */
    }
  }, 5000);

  document.getElementById('messages')?.appendChild(card);
  card.scrollIntoView({ behavior: 'smooth', block: 'end' });
}
```

3g. In the chat SSE chain, directly after

```js
            } else if (msg.sandbox_approval) {
              _showSandboxApproval(msg.sandbox_approval, requestTabId);
```

add:

```js
            } else if (msg.dev_server) {
              _showDevServerCard(msg.dev_server, requestTabId);
```

3h. In `web/static/agents-pane.js` line 270 replace

```js
        await fetch(`/api/shell/background-processes/${proc.pid}/stop`, { method: 'POST' });
```

with

```js
        await _postBackgroundStop(proc.pid);
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `node tests/dev_server_card.test.js && node tests/sandbox_ui.test.js && node tests/startup_const_order.test.js`
Expected: `dev_server_card: all assertions passed`, `sandbox_ui: all assertions passed`, `startup_const_order: PASS`.

Then run every JS test to catch regressions: `for f in tests/*.test.js; do node "$f" || { echo "FAILED: $f"; break; }; done`
Expected: no `FAILED:` line.

- [ ] **Step 5: Commit**

```bash
git add web/static/app.js web/static/agents-pane.js tests/dev_server_card.test.js tests/sandbox_ui.test.js
git commit -m "feat: show a running dev server card with Open and Stop"
```

### Task 12: Ship the relay in the packaged backend and update the docs

**Files:**
- Modify: `packaging/aigator-backend.spec` (datas ~9-17, sandbox hiddenimports ~54-59)
- Modify: `docs/BUILD_INSTRUCTIONS.md:311`
- Modify: `docs/security/threatmodel-remediation.md:16` (only the phrase "background commands are refused")
- Test: `tests/test_desktop_packaging.py`

**Interfaces:**
- Consumes: `runtime_copy.install_relay()` (Task 6) reads `relay.py` and `wire.py` from the folder of `runtime_copy.py`. In a frozen build that folder is `_MEIPASS/sandbox/`, so both files must be data files there. They are also listed as imports of the backend so the forwarder side (`sandbox.wire`, `sandbox.forward`, `sandbox.runtime_copy`) is in the bundle.
- Produces: nothing used by later tasks.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_desktop_packaging.py`:

```python
def test_packaged_backend_ships_the_sandbox_relay_and_docs_match():
    spec = (ROOT / "packaging" / "aigator-backend.spec").read_text(encoding="utf-8")
    for name in ("relay.py", "wire.py"):
        assert f'(str(web / "sandbox" / "{name}"), "sandbox")' in spec
    for module in ("sandbox.wire", "sandbox.forward", "sandbox.runtime_copy"):
        assert f'"{module}"' in spec

    build = (ROOT / "docs" / "BUILD_INSTRUCTIONS.md").read_text(encoding="utf-8")
    threat = (ROOT / "docs" / "security" / "threatmodel-remediation.md").read_text(encoding="utf-8")
    assert "is refused while the sandbox is enforced" not in build
    assert "background commands are refused" not in threat
    assert "forwards one loopback port" in threat
```

- [ ] **Step 2: Run the test to see it fail**

Run: `python -m pytest tests/test_desktop_packaging.py -v -k sandbox_relay`
Expected: FAIL on the first `assert` (the spec has no relay data entry).

- [ ] **Step 3: Implement**

3a. In `packaging/aigator-backend.spec`, add two entries to `datas` after the `version.txt` line:

```python
    (str(root / "version.txt"), "."),
    (str(web / "sandbox" / "relay.py"), "sandbox"),
    (str(web / "sandbox" / "wire.py"), "sandbox"),
]
```

3b. In the sandbox `hiddenimports` list, add a line after the launcher line:

```python
hiddenimports += [
    "sandbox", "sandbox.policy", "sandbox.paths", "sandbox.approvals",
    "sandbox.launcher_windows", "sandbox.launcher_macos", "sandbox.launcher_linux",
    "sandbox.wire", "sandbox.forward", "sandbox.runtime_copy",
]
```

3c. In `docs/BUILD_INSTRUCTIONS.md` replace line 311

```
- `background=true` is refused while the sandbox is enforced.
```

with

```
- `background=true` runs inside the sandbox on Windows, after the same approval card as a foreground command (it is never saved with "Always allow" and is refused for unattended runs). AI Gator forwards one localhost port, the first address the server prints, so the user can open it in a browser; Stop and closing AI Gator end the server. A tool the sandbox cannot read, such as the default Node under `C:\Program Files`, is copied once to `~/.gator/sandbox/runtime/` (about 100 MB for Node). On macOS and Linux `background=true` is still refused while the sandbox is enforced.
```

3d. In `docs/security/threatmodel-remediation.md` line 16 replace only the phrase

```
background commands are refused, credentialed commands
```

with

```
background commands are not refused: a long-running command runs inside the sandbox under the same approval as a foreground run, and AI Gator forwards one loopback port to it, so the server never runs with user access (Windows; elsewhere still refused while the sandbox is enforced), credentialed commands
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `python -m pytest tests/test_desktop_packaging.py tests/test_packaging_skill_imports.py -v`
Expected: PASS.

Then the whole affected Python suite once, to catch cross-task breakage: `python -m pytest tests/code_sandbox tests/shell_runner tests/test_background_process_routes.py tests/test_agent_loop_sandbox.py tests/test_csrf_route_inventory.py web/tests/test_shell_background.py -q`
Expected: PASS (the `real_sandbox` tests are skipped off Windows or run on Windows).

- [ ] **Step 5: Commit**

```bash
git add packaging/aigator-backend.spec docs/BUILD_INSTRUCTIONS.md docs/security/threatmodel-remediation.md tests/test_desktop_packaging.py
git commit -m "feat: ship the sandbox relay in the packaged backend and update the docs"
```

---

## Self-Review

**Spec coverage** (each spec item and the task that implements it):

| Spec item | Task |
|---|---|
| Wire format, 64 KB cap, frame split, malformed frame | 1 |
| Relay: starts the command, `LOG`/`EXIT`, `OPEN`/`DATA`/`CLOSE`, one writer lock | 2 |
| Forwarder: reader thread, log file, port detection, listener on `127.0.0.1`, same port or free port, 64 connection cap, event loop never blocked, `url`/`ready` | 3 |
| Streaming launcher `start_sandboxed`, Job Object, other platforms `NotImplementedError` | 4 |
| Real AppContainer run: frames over the pipes, tree ends with the handle (the two items the spec lists as unverified) | 5 |
| Runtime copy of unreadable tool folders, reuse, `PATH` first, relay install | 6 |
| Same gate and card, exact command, no task or saved coverage, never "Always" | 7 |
| `run_shell(background=true)` in the sandbox, unattended refusal, 10 process cap, 30 s wait, no-url and early-exit results, stop guard, tool text, telemetry (`sandbox.telemetry_record`, no new fields) | 8 |
| Orphan cleanup verifies the command line | 8 |
| Stop route CSRF and 404, baseline line removed, list carries `url` | 9 |
| Result reaches the chat stream | 10 |
| Card line, status card (Open, Stop, poll, Stopped), Open restricted to localhost, `agents-pane.js` Stop with CSRF retry | 11 |
| Packaging of `relay.py`/`wire.py`, H_06 row, `BUILD_INSTRUCTIONS.md` | 12 |
| Windows-only test on a real machine (dev server reachable, Stop ends `node.exe`, backend kill ends it) | 5 (relay path); the Slidev run through the chat is the manual check in the spec |

**Placeholder scan:** no "TBD", "TODO", "similar to Task N" or code-less steps. Every code step shows the code or the exact replacement text.

**Type consistency:**
- Wire kinds and `encode`/`decode`/`FrameDecoder` names come from Task 1 and are used unchanged in Tasks 2 and 3.
- `ForwardedProcess(proc, log_path, on_close=None).start()`, `.wait_ready(timeout) -> bool`, `.url`, `.pid`, `.poll()`, `.terminate()` (Task 3) are what Tasks 8 and 9 call and what the Task 8 fake implements.
- `SandboxProcess` and `start_sandboxed(request)` (Task 4) are what Task 3's forwarder wraps and Task 8 calls.
- `runtime_copy.readable_copies`, `install_relay`, `RuntimeCopyError` (Task 6) match their uses in Task 8.
- `approvals.create/lookup(..., background=...)` and `_shell_gate(..., background=False)` (Task 7) match the call in Task 8. The card key is `background` in Tasks 7 and 11.
- The result key `_dev_server` is `{pid, url, command}` in Task 8, forwarded as `dev_server` in Task 10 and read as `msg.dev_server` in Task 11.
- The list route returns `{"processes": [{"pid", "running", "url", ...}]}` (Task 9); the Task 11 poll reads exactly `processes[].pid` and `running`.
- `_postBackgroundStop(pid)` is defined once in `app.js` (Task 11) and used by the status card and `agents-pane.js`.

**Gaps found and fixed in this review:** added the "no URL yet" and "exited before printing an address" tests to Task 8, because the spec requires both results and nothing covered them.

**Order note:** after Task 9 the stop route needs the CSRF token. The agents pane already gets the token from the page's global `fetch` wrapper, so Stop keeps working between Tasks 9 and 11. Task 11 only adds the stale-token retry.

