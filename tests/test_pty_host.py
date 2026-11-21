import asyncio
import json
import os
import queue
import signal
import sys
import threading
import time

import pytest

import agent_liveness
import pty_client
import pty_host
from pty_host import PtyHost
from pty_session import PtySession
from routes import terminal

TOKEN = "aigator-fake-api-key"


class _FakePty:
    pid = 4242

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

    detach = close


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


def _api_client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from skills.code_agent import projects

    monkeypatch.setattr(projects, "_load_config", lambda: {})
    monkeypatch.setattr(projects, "_save_config", lambda cfg: None)
    app = FastAPI()
    app.include_router(terminal.router)
    return TestClient(app)


def test_adoption_waits_for_the_host_replay_so_a_resuming_client_keeps_its_seq(
    host, monkeypatch
):
    info, spawned = host
    _create(info, sid="sess-resume")
    pty = spawned[0][1]
    pty.feed("already shown|")
    pty.feed("missed")

    # The replay reaches the new backend slowly; adoption must still not return
    # a session whose buffer is shorter than what the client has already seen.
    real_read = pty_client.RemotePty.read

    def slow_read(self, n=4096):
        time.sleep(0.2)
        return real_read(self, n)

    monkeypatch.setattr(pty_client.RemotePty, "read", slow_read)
    monkeypatch.setattr(pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(pty_client, "find_host", lambda key: info)
    terminal._pty_sessions.pop("sess-resume", None)
    try:
        with _api_client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-resume&seq=14"
        ) as ws:
            assert json.loads(ws.receive_text()) == {
                "type": "output",
                "data": "missed",
                "seq": 20,
            }
    finally:
        terminal._pty_sessions.pop("sess-resume", None)
        pty.end()


def test_failed_adoption_does_not_register_a_session(host, monkeypatch):
    info, _ = host
    monkeypatch.setattr(pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(pty_client, "find_host", lambda key: info)

    def refuse(info, msg):
        raise pty_client.HostError("host went away")

    monkeypatch.setattr(pty_client, "host_request", refuse)
    terminal._pty_sessions.pop("sess-gone", None)
    assert terminal.get_pty_session("sess-gone") is None
    assert "sess-gone" not in terminal._pty_sessions


def test_adoption_that_times_out_waiting_for_the_replay_fails(host, monkeypatch):
    info, spawned = host
    _create(info, sid="sess-slow")
    pty = spawned[0][1]
    pty.feed("retained output")

    # The replay never arrives in time. Serving a buffer shorter than what the
    # host retains would hand a resuming client a stream it cannot trust, so
    # the adopt must fail rather than register that session.
    real_read = pty_client.RemotePty.read

    def stalled_read(self, n=4096):
        time.sleep(2)
        return real_read(self, n)

    monkeypatch.setattr(pty_client.RemotePty, "read", stalled_read)
    monkeypatch.setattr(terminal, "_ADOPT_REPLAY_TIMEOUT", 0.1)
    monkeypatch.setattr(pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(pty_client, "find_host", lambda key: info)
    terminal._pty_sessions.pop("sess-slow", None)
    try:
        assert terminal.get_pty_session("sess-slow") is None
        assert "sess-slow" not in terminal._pty_sessions
        # Giving up on the adopt only drops our connection; the agent keeps
        # running in the host, and a later lookup can adopt it.
        assert pty_client.host_request(info, {"op": "status", "id": "sess-slow"})[
            "exists"
        ]
        monkeypatch.setattr(pty_client.RemotePty, "read", real_read)
        assert terminal.get_pty_session("sess-slow") is not None
    finally:
        terminal._pty_sessions.pop("sess-slow", None)
        pty.end()


def test_generic_agent_route_spawns_off_the_event_loop(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import generic_agent
    from routes import generic_agent_routes
    from security import verify_csrf

    seen = {}

    def fake_create(session_id, **kwargs):
        try:
            asyncio.get_running_loop()
            seen["on_loop"] = True
        except RuntimeError:
            seen["on_loop"] = False
        seen["kwargs"] = kwargs

    monkeypatch.setattr(terminal, "create_pty_session", fake_create)
    monkeypatch.setattr(generic_agent, "is_supported", lambda agent: True)
    monkeypatch.setattr(generic_agent, "is_bare_terminal", lambda agent: True)
    monkeypatch.setattr(generic_agent, "set_active_session", lambda *a: None)
    app = FastAPI()
    app.include_router(generic_agent_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    reply = TestClient(app).post(
        "/api/generic-agent/terminal",
        json={
            "project_id": "p",
            "agent": "bash",
            "repo_path": ".",
            "force_new": True,
            "cols": 90,
            "rows": 30,
        },
    )
    assert reply.status_code == 200 and reply.json()["created"] is True
    assert seen["on_loop"] is False
    assert seen["kwargs"]["cols"] == 90 and seen["kwargs"]["rows"] == 30


def test_failed_host_create_closes_the_host_session_before_falling_back(monkeypatch):
    info = {"port": 1, "token": TOKEN}
    sent = []

    def fake_request(info, msg, timeout=5.0):
        sent.append(msg["op"])
        if msg["op"] == "create":
            raise pty_client.HostError("timed out waiting for the host")
        return {"ok": True}

    monkeypatch.setattr(pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(pty_client, "ensure_host", lambda key: info)
    monkeypatch.setattr(pty_client, "host_request", fake_request)
    fallback = _FakePty()
    monkeypatch.setattr(terminal, "spawn_pty", lambda **kw: fallback)
    try:
        entry = terminal.create_pty_session("sess-slow", command=["agent"])
        assert entry.pty is fallback
        assert sent == ["create", "close"]
    finally:
        terminal._pty_sessions.pop("sess-slow", None)
        fallback.end()


def test_create_waits_longer_than_a_normal_host_request(monkeypatch):
    info = {"port": 1, "token": TOKEN}
    timeouts = {}

    def fake_request(info, msg, timeout=5.0):
        timeouts[msg["op"]] = timeout
        raise pty_client.HostError("stop here")

    monkeypatch.setattr(pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(pty_client, "ensure_host", lambda key: info)
    monkeypatch.setattr(pty_client, "host_request", fake_request)
    monkeypatch.setattr(terminal, "spawn_pty", lambda **kw: _FakePty())
    try:
        terminal.create_pty_session("sess-timeout", command=["agent"])
    finally:
        terminal._pty_sessions.pop("sess-timeout", None)
    assert timeouts["create"] == pty_client.CREATE_TIMEOUT > 5.0


def test_status_and_list_report_the_child_pid_and_creation_time(host):
    info, spawned = host
    _create(info, sid="s-pid")
    status = pty_client.host_request(info, {"op": "status", "id": "s-pid"})
    assert status["pid"] == 4242 and isinstance(status["created_at"], float)
    listed = pty_client.host_request(info, {"op": "list"})["sessions"]
    assert listed == [
        {
            "id": "s-pid",
            "done": False,
            "pid": 4242,
            "created_at": status["created_at"],
            "meta": None,
        }
    ]


def test_adopted_session_keeps_the_creation_time_the_host_recorded(host, monkeypatch):
    info, spawned = host
    _create(info, sid="s-old")
    created = pty_client.host_request(info, {"op": "status", "id": "s-old"})["created_at"]
    time.sleep(0.05)
    monkeypatch.setattr(pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(pty_client, "find_host", lambda key: info)
    terminal._pty_sessions.pop("s-old", None)
    try:
        entry = terminal.get_pty_session("s-old")
        assert entry.created_at == created
    finally:
        terminal._pty_sessions.pop("s-old", None)
        spawned[0][1].end()


def test_pty_pid_map_includes_host_sessions_this_backend_has_not_adopted(host, monkeypatch):
    info, spawned = host
    _create(info, sid="s-unadopted")
    monkeypatch.setattr(pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(pty_client, "find_host", lambda key: info)
    terminal._pty_sessions.pop("s-unadopted", None)
    try:
        assert terminal.pty_pid_map() == {4242: "s-unadopted"}
        spawned[0][1].end()
        assert _wait(lambda: terminal.pty_pid_map() == {})
    finally:
        terminal._pty_sessions.pop("s-unadopted", None)


# ── Ownership across a backend restart ────────────────────────────────────────
# The backend's (project, agent) -> session map dies with it, so the host
# remembers who a session was created for and a restarted backend reclaims it.


def _meta(project="proj-own", agent="claude"):
    return {"project_id": project, "agent": agent}


def test_host_remembers_the_owner_metadata_it_was_given_at_create(host):
    info, _ = host
    _create(info, sid="a", meta=_meta())
    _create(info, sid="b")
    listed = {
        s["id"]: s
        for s in pty_client.host_request(info, {"op": "list"})["sessions"]
    }
    assert listed["a"]["meta"] == _meta()
    assert listed["b"]["meta"] is None
    pty_client.host_request(info, {"op": "close", "id": "a"})
    ids = [s["id"] for s in pty_client.host_request(info, {"op": "list"})["sessions"]]
    assert ids == ["b"]


@pytest.mark.parametrize(
    "bad",
    ["a string", ["a"], {"project_id": 1}, {"k" * 300: "v"}, {"project_id": "x" * 5000}],
)
def test_host_ignores_metadata_that_is_not_a_small_string_map(host, bad):
    info, _ = host
    _create(info, sid="a", meta=bad)
    [listed] = pty_client.host_request(info, {"op": "list"})["sessions"]
    assert listed["meta"] is None


def test_host_forgets_metadata_of_a_session_it_reaps():
    h = PtyHost(TOKEN, spawn=lambda **kw: _FakePty())
    pty = _FakePty()
    session = PtySession(pty)
    h.sessions["a"] = session
    h._meta["a"] = _meta()
    pty.end()
    assert _wait(lambda: session.done)
    now = time.time()
    h.reap(now, orphan_timeout=10**9, done_ttl=1)
    h.reap(now + 2, orphan_timeout=10**9, done_ttl=1)
    assert "a" not in h.sessions and "a" not in h._meta


def test_create_sends_the_owner_metadata_to_the_host(monkeypatch):
    info = {"port": 1, "token": TOKEN}
    sent = []

    def fake_request(info, msg, timeout=5.0):
        sent.append(msg)
        return {"ok": True}

    monkeypatch.setattr(pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(pty_client, "ensure_host", lambda key: info)
    monkeypatch.setattr(pty_client, "host_request", fake_request)

    class _Remote(_FakePty):
        start_offset = end_offset = 0

        def __init__(self, *args, **kwargs):
            super().__init__()

    monkeypatch.setattr(pty_client, "RemotePty", _Remote)
    try:
        terminal.create_pty_session("sess-meta", command=["agent"], meta=_meta())
    finally:
        terminal._pty_sessions.pop("sess-meta", None)
    assert sent[0]["meta"] == _meta()


@pytest.fixture
def restarted_backend(host, monkeypatch):
    """A fresh backend in front of a host that already holds sessions: its
    registries are empty and POSTs reach the real route."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import generic_agent
    from routes import generic_agent_routes
    from security import verify_csrf

    info, spawned = host
    monkeypatch.setattr(pty_client, "host_enabled", lambda: True)
    monkeypatch.setattr(pty_client, "find_host", lambda key: info)
    monkeypatch.setattr(pty_client, "ensure_host", lambda key: info)
    monkeypatch.setattr(generic_agent, "is_supported", lambda agent: True)
    monkeypatch.setattr(generic_agent, "is_bare_terminal", lambda agent: True)
    monkeypatch.setattr(generic_agent, "_active_sessions", {})
    monkeypatch.setattr(terminal, "_pty_sessions", {})
    app = FastAPI()
    app.include_router(generic_agent_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    client = TestClient(app)

    def open_terminal(project="proj-own", agent="claude", **extra):
        return client.post(
            "/api/generic-agent/terminal",
            json={"project_id": project, "agent": agent, "repo_path": ".", **extra},
        )

    yield info, spawned, open_terminal, generic_agent
    for entry in list(terminal._pty_sessions.values()):
        entry.pty.detach()


def test_reopening_a_project_after_a_restart_reattaches_the_running_agent(
    restarted_backend,
):
    info, spawned, open_terminal, generic_agent = restarted_backend
    _create(info, sid="old", meta=_meta())
    _create(info, sid="newest", meta=_meta())
    _create(info, sid="other-agent", meta=_meta(agent="codex"))
    _create(info, sid="other-project", meta=_meta(project="elsewhere"))

    reply = open_terminal()

    assert reply.status_code == 200
    assert reply.json() == {"pty_session_id": "newest", "created": False}
    assert len(spawned) == 4  # nothing new was started
    assert generic_agent.get_active_session("proj-own", "claude") == "newest"


def test_a_plus_tab_still_starts_a_new_agent_next_to_the_running_one(
    restarted_backend, monkeypatch
):
    info, spawned, open_terminal, _ = restarted_backend
    _create(info, sid="running", meta=_meta())

    reply = open_terminal(force_new=True)

    assert reply.json()["created"] is True
    assert reply.json()["pty_session_id"] != "running"
    assert len(spawned) == 2


def test_a_finished_session_is_not_reattached_after_a_restart(restarted_backend):
    info, spawned, open_terminal, _ = restarted_backend
    _create(info, sid="finished", meta=_meta())
    spawned[0][1].end()
    assert _wait(
        lambda: pty_client.host_request(info, {"op": "status", "id": "finished"})[
            "done"
        ]
    )

    reply = open_terminal()

    assert reply.json()["created"] is True
    assert reply.json()["pty_session_id"] != "finished"


def test_a_reattached_agent_stays_mapped_to_its_terminal_for_takeover(
    restarted_backend, monkeypatch
):
    info, spawned, open_terminal, _ = restarted_backend
    _create(info, sid="running", meta=_meta())
    assert terminal.pty_pid_map() == {4242: "running"}

    reply = open_terminal()

    assert reply.json() == {"pty_session_id": "running", "created": False}
    assert len(spawned) == 1
    assert terminal.pty_pid_map() == {4242: "running"}

    class _Proc:
        def __init__(self, pid, parents=()):
            self.pid = pid
            self._parents = list(parents)

        def parents(self):
            return self._parents

    shell = _Proc(4242)
    monkeypatch.setattr(
        "agent_liveness.psutil.Process", lambda pid: _Proc(pid, [shell]) if pid != 4242 else shell
    )
    assert agent_liveness.owning_pty(9001, terminal.pty_pid_map()) == "running"


def test_no_matching_session_in_the_host_starts_a_new_agent(restarted_backend):
    info, spawned, open_terminal, _ = restarted_backend
    _create(info, sid="other", meta=_meta(project="elsewhere"))
    _create(info, sid="unowned")

    reply = open_terminal()

    assert reply.json()["created"] is True
    assert len(spawned) == 3


def test_an_unreachable_host_starts_a_new_agent_as_before(restarted_backend, monkeypatch):
    _, spawned, open_terminal, _ = restarted_backend

    def unreachable(info, msg, timeout=5.0):
        raise pty_client.HostError("host went away")

    monkeypatch.setattr(pty_client, "host_request", unreachable)
    monkeypatch.setattr(terminal, "spawn_pty", lambda **kw: _FakePty())
    reply = open_terminal()
    assert reply.json()["created"] is True


def test_a_running_agent_that_cannot_be_reattached_is_not_duplicated_or_killed(
    restarted_backend, monkeypatch
):
    info, spawned, open_terminal, generic_agent = restarted_backend
    _create(info, sid="running", meta=_meta())
    monkeypatch.setattr(terminal, "_ADOPT_REPLAY_TIMEOUT", 0.1)
    real_read = pty_client.RemotePty.read
    spawned[0][1].feed("retained")

    def stalled(self, n=4096):
        time.sleep(2)
        return real_read(self, n)

    monkeypatch.setattr(pty_client.RemotePty, "read", stalled)

    reply = open_terminal()

    assert reply.status_code == 503
    assert len(spawned) == 1
    assert pty_client.host_request(info, {"op": "status", "id": "running"})["alive"]
    assert generic_agent.get_active_session("proj-own", "claude") is None


def test_packaged_builds_keep_their_ptys_in_the_backend(monkeypatch):
    # Not under pytest, as a real run would be.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("GATOR_PTY_HOST", raising=False)
    assert pty_client.host_enabled() is True  # a source checkout
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert pty_client.host_enabled() is False
    monkeypatch.setenv("GATOR_PTY_HOST", "1")
    assert pty_client.host_enabled() is True  # an explicit override still wins


def test_a_packaged_build_never_contacts_the_host(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("GATOR_PTY_HOST", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("a packaged build must not start or ask a PTY host")

    monkeypatch.setattr(pty_client, "ensure_host", forbidden)
    monkeypatch.setattr(pty_client, "find_host", forbidden)
    fallback = _FakePty()
    monkeypatch.setattr(terminal, "spawn_pty", lambda **kw: fallback)
    try:
        entry = terminal.create_pty_session("sess-frozen", command=["agent"])
        assert entry.pty is fallback
        assert terminal.get_pty_session("sess-unknown") is None
        assert terminal.find_host_session({"project_id": "p", "agent": "a"}) is None
    finally:
        terminal._pty_sessions.pop("sess-frozen", None)
        fallback.end()
