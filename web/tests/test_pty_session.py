import json
import queue
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pty_session import PtySession
from routes import terminal
from skills.code_agent import projects


class _FakePty:
    """Blocking-read PTY stand-in: feed() is the process printing, end() is exit."""

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


def _wait(cond, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_output_is_captured_with_no_viewer_connected():
    pty = _FakePty()
    session = PtySession(pty)
    pty.feed("hello ")
    pty.feed("world")
    assert _wait(lambda: session.read_from(0)[0] == "hello world")
    pty.end()


def test_read_from_resumes_after_a_sequence_number():
    pty = _FakePty()
    session = PtySession(pty)
    pty.feed("a")
    pty.feed("b")
    pty.feed("c")
    assert _wait(lambda: session.read_from(0)[1] == 3)
    assert session.read_from(1) == ("bc", 3)
    assert session.read_from(3) == ("", 3)
    pty.end()


def test_buffer_keeps_only_the_newest_chunks():
    pty = _FakePty()
    session = PtySession(pty, max_chunks=3)
    for ch in "abcde":
        pty.feed(ch)
    assert _wait(lambda: session.read_from(0)[1] == 5)
    assert session.read_from(0) == ("cde", 5)
    assert session.read_from(4) == ("e", 5)
    pty.end()


def test_session_is_done_once_the_process_ends():
    pty = _FakePty()
    session = PtySession(pty)
    assert not session.done
    pty.end()
    assert _wait(lambda: session.done)


def _client(monkeypatch):
    monkeypatch.setattr(projects, "_load_config", lambda: {})
    monkeypatch.setattr(projects, "_save_config", lambda cfg: None)
    app = FastAPI()
    app.include_router(terminal.router)
    return TestClient(app)


def test_ws_replays_output_produced_while_no_viewer_was_connected(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty)
    terminal._pty_sessions["sess-replay"] = session
    try:
        pty.feed("printed while the browser was away")
        assert _wait(lambda: session.read_from(0)[1] == 1)
        with _client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-replay"
        ) as ws:
            msg = json.loads(ws.receive_text())
            assert msg == {"type": "output", "data": "printed while the browser was away"}
            pty.feed("live")
            assert json.loads(ws.receive_text()) == {"type": "output", "data": "live"}
    finally:
        terminal._pty_sessions.pop("sess-replay", None)
        pty.end()


def test_ws_sends_exit_when_the_process_ends_and_forwards_input(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty)
    terminal._pty_sessions["sess-exit"] = session
    try:
        with _client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-exit"
        ) as ws:
            ws.send_text(json.dumps({"type": "input", "data": "ls\r"}))
            ws.send_text(json.dumps({"type": "resize", "cols": 100, "rows": 30}))
            assert _wait(lambda: pty.written == ["ls\r"] and pty.size == (100, 30))
            pty.end()
            assert json.loads(ws.receive_text())["type"] == "exit"
    finally:
        terminal._pty_sessions.pop("sess-exit", None)


def test_viewer_count_tracks_connections(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty)
    terminal._pty_sessions["sess-viewed"] = session
    try:
        with _client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-viewed"
        ):
            assert _wait(lambda: session.ws_clients == 1)
            assert terminal.is_pty_viewed("sess-viewed")
        assert _wait(lambda: session.ws_clients == 0)
        assert terminal.is_pty_viewed("sess-viewed")  # inside the 90s grace window
    finally:
        terminal._pty_sessions.pop("sess-viewed", None)
        pty.end()
