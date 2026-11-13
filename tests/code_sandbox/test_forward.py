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
