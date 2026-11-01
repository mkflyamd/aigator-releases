import asyncio
import json
import os
import queue
import signal
import sys
import threading
import time

import pytest

import pty_client
import pty_host
from pty_host import PtyHost
from pty_session import PtySession
from routes import terminal

TOKEN = "aigator-fake-api-key"


class _FakePty:
    def __init__(self):
        self._q = queue.Queue()
        self._alive = True
        self.written = []
        self.size = None

    def feed(self, data):
        self._q.put(data)

    def end(self):
        self._alive = False
        self._q.put(None)

    def read(self, n=4096):
        data = self._q.get()
        if data is None:
            raise EOFError
        return data

    def write(self, data):
        self.written.append(data)

    def resize(self, cols, rows):
        self.size = (cols, rows)

    def isalive(self):
        return self._alive

    def close(self):
        self.end()


def _wait(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def host():
    spawned = []

    def fake_spawn(**kwargs):
        pty = _FakePty()
        spawned.append((kwargs, pty))
        return pty

    ready = threading.Event()
    box = {}

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        server = loop.run_until_complete(
            asyncio.start_server(
                PtyHost(TOKEN, spawn=fake_spawn).handle, "127.0.0.1", 0
            )
        )
        box["loop"] = loop
        box["port"] = server.sockets[0].getsockname()[1]
        ready.set()
        loop.run_forever()
        server.close()
        loop.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(5)
    info = {"port": box["port"], "token": TOKEN}
    yield info, spawned
    box["loop"].call_soon_threadsafe(box["loop"].stop)
    thread.join(5)


def _create(info, sid="s1", **extra):
    reply = pty_client.host_request(
        info, {"op": "create", "id": sid, "cols": 100, "rows": 30, **extra}
    )
    assert reply == {"ok": True}


def test_wrong_token_is_refused(host):
    info, _ = host
    with pytest.raises(pty_client.HostError):
        pty_client.host_request({**info, "token": "wrong"}, {"op": "list"})


def test_create_passes_spawn_arguments_through(host):
    info, spawned = host
    _create(info, command=["agent", "--x"], env={"A": "1"}, cwd="/work")
    kwargs, _ = spawned[0]
    assert kwargs == {
        "cols": 100,
        "rows": 30,
        "command": ["agent", "--x"],
        "env": {"A": "1"},
        "cwd": "/work",
    }
    assert pty_client.host_request(info, {"op": "status", "id": "s1"})["alive"]
    assert not pty_client.host_request(info, {"op": "status", "id": "nope"})["exists"]


def test_attach_streams_output_and_forwards_input_and_resize(host):
    info, spawned = host
    _create(info)
    pty = spawned[0][1]
    remote = pty_client.RemotePty(info, "s1")
    pty.feed("hello")
    assert remote.read() == "hello"
    remote.write("ls\r")
    remote.resize(120, 40)
    assert _wait(lambda: pty.written == ["ls\r"] and pty.size == (120, 40))
    remote.detach()


def test_reattach_replays_only_what_the_offset_has_not_seen(host):
    info, spawned = host
    _create(info)
    pty = spawned[0][1]
    first = pty_client.RemotePty(info, "s1")
    pty.feed("abc")
    assert first.read() == "abc"
    first.detach()
    pty.feed("def")  # printed while no backend was attached

    again = pty_client.RemotePty(info, "s1", offset=0)
    assert again.start_offset == 0
    assert again.read() == "abcdef"
    again.detach()

    resumed = pty_client.RemotePty(info, "s1", offset=3)
    assert resumed.start_offset == 3
    assert resumed.read() == "def"
    resumed.detach()


def test_process_exit_reaches_the_client_as_eof(host):
    info, spawned = host
    _create(info)
    remote = pty_client.RemotePty(info, "s1")
    spawned[0][1].end()
    with pytest.raises(EOFError):
        remote.read()
    assert not remote.isalive()


def test_close_kills_the_session_on_the_host(host):
    info, spawned = host
    _create(info)
    remote = pty_client.RemotePty(info, "s1")
    remote.close()
    assert _wait(lambda: not spawned[0][1].isalive())
    assert not pty_client.host_request(info, {"op": "status", "id": "s1"})["exists"]


def test_attach_to_a_missing_session_fails(host):
    info, _ = host
    with pytest.raises(pty_client.HostError):
        pty_client.RemotePty(info, "nope")


def test_backend_restart_adopts_the_session_from_the_host(host, monkeypatch):
    info, spawned = host
    _create(info, sid="sess-adopt")
    pty = spawned[0][1]
    pty.feed("output from before the restart")

    monkeypatch.setattr(pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(pty_client, "find_host", lambda key: info)
    terminal._pty_sessions.pop("sess-adopt", None)  # the new backend starts empty
    try:
        entry = terminal.get_pty_session("sess-adopt")
        assert isinstance(entry, PtySession)
        assert _wait(
            lambda: entry.read_from(0)[0] == "output from before the restart"
        )
        assert terminal.get_pty_session("sess-adopt") is entry
        assert terminal.get_pty_session("unknown") is None
    finally:
        terminal._pty_sessions.pop("sess-adopt", None)
        pty.end()


def test_create_through_the_host_registers_a_mirror_session(host, monkeypatch):
    info, spawned = host
    monkeypatch.setattr(pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(pty_client, "ensure_host", lambda key: info)
    monkeypatch.setattr(pty_client, "find_host", lambda key: info)
    try:
        entry = terminal.create_pty_session("sess-new", command=["agent"])
        assert terminal.get_pty_session("sess-new") is entry
        spawned[0][1].feed("hi")
        assert _wait(lambda: entry.read_from(0)[0] == "hi")
        entry.write("x")
        assert _wait(lambda: spawned[0][1].written == ["x"])
        terminal.close_pty_session("sess-new")
        assert _wait(lambda: not spawned[0][1].isalive())
    finally:
        terminal._pty_sessions.pop("sess-new", None)


def test_real_detached_host_keeps_a_session_across_a_backend_restart(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("GATOR_PTY_HOST", "1")
    key = f"test{os.getpid()}"
    info = pty_client.ensure_host(key)
    assert info is not None
    try:
        assert pty_host.host_file(key).parent == tmp_path / ".gator"
        script = (
            "import sys\n"
            "print('READY', flush=True)\n"
            "line = sys.stdin.readline()\n"
            "print('GOT:' + line.strip(), flush=True)\n"
            "sys.stdin.readline()\n"
        )
        reply = pty_client.host_request(
            info,
            {
                "op": "create",
                "id": "real",
                "cols": 100,
                "rows": 30,
                "command": [sys.executable, "-c", script],
                "env": dict(os.environ),
            },
        )
        assert reply == {"ok": True}, reply

        first = PtySession(
            (remote := pty_client.RemotePty(info, "real")),
            start_offset=0,
        )
        assert _wait(lambda: "READY" in first.read_from(0)[0], timeout=15)

        # the backend goes away; the program inside keeps running
        remote.detach()
        assert _wait(lambda: first.done)
        status = pty_client.host_request(info, {"op": "status", "id": "real"})
        assert status["alive"]

        remote2 = pty_client.RemotePty(info, "real")
        second = PtySession(remote2, start_offset=remote2.start_offset)
        assert _wait(lambda: "READY" in second.read_from(0)[0], timeout=15)
        second.write("ping\r")
        assert _wait(lambda: "GOT:ping" in second.read_from(0)[0], timeout=15)
        remote2.close()
    finally:
        try:
            os.kill(info["pid"], signal.SIGTERM)
        except OSError:
            pass


def _bare_host():
    return PtyHost(TOKEN, spawn=lambda **kwargs: _FakePty())


def _add_session(host, sid):
    pty = _FakePty()
    host.sessions[sid] = PtySession(pty)
    return pty


def test_reap_drops_finished_sessions_only_after_the_ttl():
    host = _bare_host()
    live = _add_session(host, "live")
    dead = _add_session(host, "dead")
    dead.end()
    assert _wait(lambda: host.sessions["dead"].done)
    host._connections = 1  # a backend is connected, so the host itself stays

    now = time.time()
    assert host.reap(now, orphan_timeout=600, done_ttl=100) is False
    assert "dead" in host.sessions  # the clock for it starts now
    host.reap(now + 99, orphan_timeout=600, done_ttl=100)
    assert "dead" in host.sessions
    host.reap(now + 100, orphan_timeout=600, done_ttl=100)
    assert "dead" not in host.sessions
    assert "live" in host.sessions
    live.end()


def test_reap_keeps_a_finished_session_someone_is_still_attached_to():
    host = _bare_host()
    dead = _add_session(host, "dead")
    dead.end()
    assert _wait(lambda: host.sessions["dead"].done)
    host._connections = 1
    host._attached["dead"] = 1

    now = time.time()
    host.reap(now, orphan_timeout=600, done_ttl=10)
    host.reap(now + 1000, orphan_timeout=600, done_ttl=10)
    assert "dead" in host.sessions


def test_host_asks_to_exit_only_after_no_backend_for_the_orphan_timeout():
    host = _bare_host()
    t0 = host._last_connection
    assert host.reap(t0 + 599, orphan_timeout=600, done_ttl=100) is False
    assert host.reap(t0 + 600, orphan_timeout=600, done_ttl=100) is True
    host._connections = 1
    assert host.reap(t0 + 10_000, orphan_timeout=600, done_ttl=100) is False


def test_attach_counts_are_released_when_the_backend_disconnects(host):
    info, spawned = host
    _create(info)
    remote = pty_client.RemotePty(info, "s1")
    pty_client.host_request(info, {"op": "status", "id": "s1"})
    remote.detach()
    # a fresh attach still works after the first connection is gone
    again = pty_client.RemotePty(info, "s1")
    spawned[0][1].feed("x")
    assert again.read() == "x"
    again.detach()


def test_a_host_speaking_another_protocol_is_reported_and_not_replaced(
    tmp_path, monkeypatch
):
    import socket

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("GATOR_PTY_HOST", "1")
    key = "other-proto"

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    port = server.getsockname()[1]

    def serve():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                conn.makefile("rb").readline()
                conn.sendall(b'{"ok": false, "error": "proto", "proto": 99}\n')

    threading.Thread(target=serve, daemon=True).start()
    pty_host._write_host_file(key, {"pid": 1, "port": port, "token": TOKEN, "proto": 99})
    launched = []
    monkeypatch.setattr(pty_client, "_launch_host", lambda k: launched.append(k))
    try:
        assert pty_host.probe_state(key)[0] == "incompatible"
        assert pty_client.ensure_host(key) is None
        assert launched == []
    finally:
        server.close()


def test_probe_state_is_down_when_there_is_no_state_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert pty_host.probe_state("nothing-here") == ("down", None)
