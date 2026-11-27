import json
import queue
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pty_session import PtySession, _complete_prefix_length
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


def test_offsets_are_characters_so_a_resume_can_start_mid_chunk():
    pty = _FakePty()
    session = PtySession(pty)
    pty.feed("hello ")
    pty.feed("world")
    assert _wait(lambda: session.read_from(0)[1] == 11)
    assert session.read_from(3) == ("lo world", 11)
    assert session.read_from(6) == ("world", 11)
    assert session.read_from(11) == ("", 11)
    pty.end()


def test_offsets_continue_from_start_offset_and_old_offsets_clamp_to_the_window():
    pty = _FakePty()
    session = PtySession(pty, max_chunks=2, start_offset=100)
    for chunk in ("aaaa", "bb", "cccccc"):
        pty.feed(chunk)
    assert _wait(lambda: session.read_from(0)[1] == 112)
    assert session.first_offset == 104
    assert session.read_from(0) == ("bbcccccc", 112)
    assert session.read_from(106) == ("cccccc", 112)
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
        assert _wait(lambda: session.read_from(0)[1] == len("printed while the browser was away"))
        with _client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-replay"
        ) as ws:
            msg = json.loads(ws.receive_text())
            replayed = "printed while the browser was away"
            assert msg == {"type": "output", "data": replayed, "seq": len(replayed)}
            pty.feed("live")
            assert json.loads(ws.receive_text()) == {
                "type": "output",
                "data": "live",
                "seq": len(replayed) + 4,
            }
    finally:
        terminal._pty_sessions.pop("sess-replay", None)
        pty.end()


def test_ws_resumes_after_the_clients_seq_instead_of_replaying_everything(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty)
    terminal._pty_sessions["sess-resume"] = session
    try:
        pty.feed("already shown|")
        pty.feed("missed")
        assert _wait(lambda: session.read_from(0)[1] == 20)
        client = _client(monkeypatch)
        with client.websocket_connect(
            "/api/terminal/agent?session_id=sess-resume&seq=14"
        ) as ws:
            assert json.loads(ws.receive_text()) == {
                "type": "output",
                "data": "missed",
                "seq": 20,
            }
        # a seq from some other stream (past this one's end) starts over
        with client.websocket_connect(
            "/api/terminal/agent?session_id=sess-resume&seq=9999"
        ) as ws:
            msg = json.loads(ws.receive_text())
            assert msg["data"] == "already shown|missed"
    finally:
        terminal._pty_sessions.pop("sess-resume", None)
        pty.end()


def test_ws_with_negative_seq_starts_at_the_live_end_without_replay(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty)
    terminal._pty_sessions["sess-live"] = session
    try:
        pty.feed("old output")
        assert _wait(lambda: session.read_from(0)[1] == 10)
        with _client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-live&seq=-1"
        ) as ws:
            pty.feed("fresh")
            assert json.loads(ws.receive_text()) == {
                "type": "output",
                "data": "fresh",
                "seq": 15,
            }
    finally:
        terminal._pty_sessions.pop("sess-live", None)
        pty.end()


def test_ws_flags_a_fresh_attach_whose_replay_starts_mid_stream(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty, max_chunks=2)
    terminal._pty_sessions["sess-trim"] = session
    try:
        for chunk in ("aaaa", "bb", "cccccc"):
            pty.feed(chunk)
        assert _wait(lambda: session.read_from(0)[1] == 12)
        client = _client(monkeypatch)
        with client.websocket_connect("/api/terminal/agent?session_id=sess-trim") as ws:
            assert json.loads(ws.receive_text()) == {"type": "truncated"}
            assert json.loads(ws.receive_text()) == {
                "type": "output",
                "data": "bbcccccc",
                "seq": 12,
            }
        # a client whose last seen offset was trimmed away also lost output
        with client.websocket_connect(
            "/api/terminal/agent?session_id=sess-trim&seq=2"
        ) as ws:
            assert json.loads(ws.receive_text()) == {"type": "truncated"}
        # a client that is still inside the window gets a clean resume
        with client.websocket_connect(
            "/api/terminal/agent?session_id=sess-trim&seq=6"
        ) as ws:
            assert json.loads(ws.receive_text())["type"] == "output"
    finally:
        terminal._pty_sessions.pop("sess-trim", None)
        pty.end()


def test_ws_does_not_flag_an_untrimmed_or_live_attach(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty, max_chunks=2)
    terminal._pty_sessions["sess-notrim"] = session
    try:
        for chunk in ("aaaa", "bb", "cccccc"):
            pty.feed(chunk)
        assert _wait(lambda: session.read_from(0)[1] == 12)
        with _client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-notrim&seq=-1"
        ) as ws:
            pty.feed("x")
            assert json.loads(ws.receive_text())["type"] == "output"
    finally:
        terminal._pty_sessions.pop("sess-notrim", None)
        pty.end()


def test_only_the_viewer_that_last_attached_or_typed_resizes_the_pty(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty)
    terminal._pty_sessions["sess-owner"] = session
    try:
        client = _client(monkeypatch)
        with client.websocket_connect(
            "/api/terminal/agent?session_id=sess-owner"
        ) as first:
            first.send_text(json.dumps({"type": "resize", "cols": 100, "rows": 30}))
            assert _wait(lambda: pty.size == (100, 30))
            with client.websocket_connect(
                "/api/terminal/agent?session_id=sess-owner"
            ) as second:
                second.send_text(json.dumps({"type": "resize", "cols": 60, "rows": 20}))
                assert _wait(lambda: pty.size == (60, 20))
                # the earlier viewer is no longer the size owner
                first.send_text(json.dumps({"type": "resize", "cols": 90, "rows": 25}))
                first.send_text(json.dumps({"type": "input", "data": "x"}))
                assert _wait(lambda: pty.written == ["x"])
                assert pty.size == (60, 20)
                # typing takes ownership back
                first.send_text(json.dumps({"type": "resize", "cols": 90, "rows": 25}))
                assert _wait(lambda: pty.size == (90, 25))
    finally:
        terminal._pty_sessions.pop("sess-owner", None)
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


def _hidden(session):
    return len(session.ws_hidden)


def test_a_connection_that_reports_hidden_is_not_a_viewer_until_the_grace_lapses(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty)
    session.ws_disconnected_at = 0.0  # long past: no grace to lean on
    terminal._pty_sessions["sess-hidden"] = session
    try:
        with _client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-hidden"
        ) as ws:
            assert _wait(lambda: session.ws_clients == 1)
            assert terminal.has_viewer("sess-hidden")  # never reported: viewing
            ws.send_text(json.dumps({"type": "visible", "value": False}))
            assert _wait(lambda: _hidden(session) == 1)
            assert terminal.has_viewer("sess-hidden")  # the 90s grace starts now
            session.ws_disconnected_at = time.time() - 91
            assert not terminal.has_viewer("sess-hidden")
            assert terminal.is_pty_viewed("sess-hidden")  # still connected for the reaper
            ws.send_text(json.dumps({"type": "visible", "value": True}))
            assert _wait(lambda: _hidden(session) == 0)
            assert terminal.has_viewer("sess-hidden")
        assert _wait(lambda: session.ws_clients == 0)
    finally:
        terminal._pty_sessions.pop("sess-hidden", None)
        pty.end()


def test_one_visible_connection_keeps_the_terminal_watched(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty)
    session.ws_disconnected_at = 0.0
    terminal._pty_sessions["sess-two"] = session
    client = _client(monkeypatch)
    try:
        with client.websocket_connect("/api/terminal/agent?session_id=sess-two") as a, client.websocket_connect(
            "/api/terminal/agent?session_id=sess-two"
        ):
            assert _wait(lambda: session.ws_clients == 2)
            a.send_text(json.dumps({"type": "visible", "value": False}))
            assert _wait(lambda: _hidden(session) == 1)
            assert terminal.has_viewer("sess-two")
        assert _wait(lambda: session.ws_clients == 0 and _hidden(session) == 0)
    finally:
        terminal._pty_sessions.pop("sess-two", None)
        pty.end()


def test_a_viewer_who_attaches_as_the_terminal_is_suspended_is_told_so_not_that_it_crashed(
    monkeypatch, tmp_path
):
    import agent_suspend

    monkeypatch.setattr(agent_suspend, "STATE_FILE", tmp_path / "suspended-agents.json")
    pty = _FakePty()
    session = PtySession(pty)
    terminal._pty_sessions["sess-susp"] = session
    try:
        agent_suspend._remember(
            "sess-susp",
            {"agent": "claude", "project_id": "demo", "session_id": "claude-sess-9", "at": time.time()},
            time.time(),
        )
        with _client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-susp"
        ) as ws:
            assert _wait(lambda: session.ws_clients == 1)
            pty.end()
            assert json.loads(ws.receive_text()) == {
                "type": "suspended",
                "data": "Suspended - click to resume",
                "session_id": "claude-sess-9",
            }
    finally:
        terminal._pty_sessions.pop("sess-susp", None)


def test_a_viewer_of_a_failed_wake_is_told_why_and_gets_the_unsent_message(monkeypatch, tmp_path):
    import agent_suspend

    monkeypatch.setattr(agent_suspend, "STATE_FILE", tmp_path / "suspended-agents.json")
    pty = _FakePty()
    session = PtySession(pty)
    terminal._pty_sessions["sess-failed"] = session
    failure = {"reason": "The stored session is gone.", "message": "please look", "sender": "Turn issues", "at": 1.0}
    try:
        now = time.time()
        agent_suspend._remember(
            "sess-failed",
            {"agent": "claude", "project_id": "demo", "session_id": "claude-sess-9", "at": now, "failed": failure},
            now,
        )
        with _client(monkeypatch).websocket_connect("/api/terminal/agent?session_id=sess-failed") as ws:
            assert _wait(lambda: session.ws_clients == 1)
            pty.end()
            payload = json.loads(ws.receive_text())
        assert payload["type"] == "suspended" and payload["session_id"] == "claude-sess-9"
        assert payload["failed"] == failure
    finally:
        terminal._pty_sessions.pop("sess-failed", None)


def test_a_viewer_of_a_woken_terminal_is_told_who_woke_it(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty)
    session.meta = {
        "agent": "claude",
        "woken_by": "Turn issues",
        "woken_preview": "please look",
        "woken_at": "1764181620000",
    }
    terminal._pty_sessions["sess-woken"] = session
    try:
        with _client(monkeypatch).websocket_connect("/api/terminal/agent?session_id=sess-woken") as ws:
            assert json.loads(ws.receive_text()) == {
                "type": "woken",
                "data": "woken by Turn issues",
                "by": "Turn issues",
                "at": "1764181620000",
                "preview": "please look",
            }
    finally:
        terminal._pty_sessions.pop("sess-woken", None)
        pty.end()


def test_an_ordinary_terminal_sends_no_woken_message(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty)
    session.meta = {"agent": "claude"}
    terminal._pty_sessions["sess-plain"] = session
    try:
        with _client(monkeypatch).websocket_connect("/api/terminal/agent?session_id=sess-plain") as ws:
            pty.feed("hello")
            assert "woken" not in ws.receive_text()
    finally:
        terminal._pty_sessions.pop("sess-plain", None)
        pty.end()


ESC = "\x1b"


def _stored(session):
    return list(session._chunks)


def test_a_csi_sequence_split_across_reads_is_stored_whole():
    pty = _FakePty()
    session = PtySession(pty)
    pty.feed("ab" + ESC + "[3")
    pty.feed("1mcd")
    assert _wait(lambda: session.read_from(0)[1] == len("ab" + ESC + "[31mcd"))
    assert _stored(session) == ["ab", ESC + "[31mcd"]
    pty.end()


def test_an_osc_sequence_ended_by_bel_or_st_is_stored_whole():
    pty = _FakePty()
    session = PtySession(pty)
    pty.feed("x" + ESC + "]0;ti")
    pty.feed("tle\x07y" + ESC + "]8;;http")
    st = ESC + "\\"
    pty.feed("://a" + st + "z")
    assert _wait(
        lambda: session.read_from(0)[1]
        == len("x" + ESC + "]0;title\x07y" + ESC + "]8;;http://a" + st + "z")
    )
    assert _stored(session) == [
        "x",
        ESC + "]0;title\x07y",
        ESC + "]8;;http://a" + st + "z",
    ]
    pty.end()


def test_a_window_that_starts_mid_stream_never_starts_inside_a_sequence():
    pty = _FakePty()
    session = PtySession(pty, max_chunks=1)
    pty.feed("aaa" + ESC + "[3")
    pty.feed("1mbbb")
    total = len("aaa" + ESC + "[31mbbb")
    assert _wait(lambda: session.read_from(0)[1] == total)
    assert session.first_offset == 3
    assert session.read_from(0) == (ESC + "[31mbbb", total)
    pty.end()


def test_a_held_back_tail_is_released_after_a_short_wait():
    pty = _FakePty()
    session = PtySession(pty)
    pty.feed("abc" + ESC)
    assert _wait(lambda: session.read_from(0)[0] == "abc")
    assert session.read_from(0)[0] == "abc"
    assert _wait(lambda: session.read_from(0)[0] == "abc" + ESC, timeout=2.0)
    pty.end()


def test_a_held_back_tail_is_released_when_the_process_ends():
    pty = _FakePty()
    session = PtySession(pty)
    pty.feed("abc" + ESC + "[")
    assert _wait(lambda: session.read_from(0)[1] == 3)
    pty.end()
    assert _wait(lambda: session.done)
    assert session.read_from(0) == ("abc" + ESC + "[", 5)


def test_a_stale_release_does_not_flush_a_tail_that_has_since_grown():
    pty = _FakePty()
    session = PtySession(pty)
    pty.feed("a" + ESC)
    assert _wait(lambda: session._held == ESC)
    stale = session._held_gen
    pty.feed("[3")
    assert _wait(lambda: session._held == ESC + "[3")
    session._flush_held(stale)
    assert session.read_from(0) == ("a", 1)
    pty.end()


def test_a_very_long_unterminated_sequence_is_not_held_back_forever():
    pty = _FakePty()
    session = PtySession(pty)
    text = ESC + "]0;" + "a" * 6000
    pty.feed(text)
    assert _wait(lambda: session.read_from(0)[1] == len(text))
    pty.end()


def test_output_without_escapes_is_stored_as_read():
    pty = _FakePty()
    session = PtySession(pty)
    pty.feed("hello ")
    pty.feed("world")
    assert _wait(lambda: session.read_from(0)[1] == 11)
    assert _stored(session) == ["hello ", "world"]
    pty.end()


def test_resizes_are_recorded_at_the_offset_where_they_happened():
    pty = _FakePty()
    session = PtySession(pty, initial_size=(120, 40))
    pty.feed("aaaa")
    assert _wait(lambda: session.read_from(0)[1] == 4)
    session.resize(100, 30)
    session.resize(100, 30)  # no change: nothing to replay
    pty.feed("bb")
    assert _wait(lambda: session.read_from(0)[1] == 6)
    session.resize(80, 24)
    pty.feed("cc")
    assert _wait(lambda: session.read_from(0)[1] == 8)
    assert pty.size == (80, 24)
    assert session.size_at(0) == (120, 40)
    assert session.size_at(3) == (120, 40)
    assert session.size_at(4) == (100, 30)
    assert session.size_at(5) == (100, 30)
    assert session.size_at(6) == (80, 24)
    assert session.size_events(0, 8) == [(4, 100, 30), (6, 80, 24)]
    assert session.size_events(4, 8) == [(6, 80, 24)]
    assert session.size_events(0, 6) == [(4, 100, 30)]
    assert [s[1:] for s in session.sizes_after(1)] == [(4, 100, 30), (6, 80, 24)]
    pty.end()


def test_a_session_that_never_resized_has_no_sizes_to_replay():
    pty = _FakePty()
    session = PtySession(pty)
    pty.feed("aaaa")
    assert _wait(lambda: session.read_from(0)[1] == 4)
    assert session.size_at(0) is None
    assert session.size_events(0, 4) == []
    pty.end()


def test_sizes_older_than_the_window_collapse_to_the_one_the_window_starts_at():
    pty = _FakePty()
    session = PtySession(pty, max_chunks=2, initial_size=(120, 40))
    pty.feed("aa")
    assert _wait(lambda: session.read_from(0)[1] == 2)
    session.resize(100, 30)
    pty.feed("bb")
    assert _wait(lambda: session.read_from(0)[1] == 4)
    session.resize(90, 20)
    pty.feed("cc")
    pty.feed("dd")
    assert _wait(lambda: session.read_from(0)[1] == 8)
    assert session.first_offset == 4
    assert session.size_at(session.first_offset) == (90, 20)
    assert [s[1:] for s in session.sizes_after(0)] == [(4, 90, 20)]
    pty.end()


def test_the_size_log_is_capped(monkeypatch):
    import pty_session

    monkeypatch.setattr(pty_session, "PTY_SIZES_MAX", 3)
    pty = _FakePty()
    session = PtySession(pty, initial_size=(100, 30))
    for i, cols in enumerate((90, 80, 70, 60, 50), start=1):
        pty.feed("x")
        assert _wait(lambda: session.read_from(0)[1] == i)
        session.resize(cols, 30)
    assert [s[2] for s in session.sizes_after(0)] == [70, 60, 50]
    pty.end()


def _replay_messages(ws, count):
    return [json.loads(ws.receive_text()) for _ in range(count)]


def _resized_session():
    pty = _FakePty()
    session = PtySession(pty, initial_size=(120, 40))
    pty.feed("aaaa")
    assert _wait(lambda: session.read_from(0)[1] == 4)
    session.resize(100, 30)
    pty.feed("bb")
    assert _wait(lambda: session.read_from(0)[1] == 6)
    session.resize(80, 24)
    pty.feed("cc")
    assert _wait(lambda: session.read_from(0)[1] == 8)
    return pty, session


def test_ws_replays_the_recorded_resizes_between_the_output_they_apply_to(monkeypatch):
    pty, session = _resized_session()
    terminal._pty_sessions["sess-sizes"] = session
    try:
        with _client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-sizes"
        ) as ws:
            assert _replay_messages(ws, 7) == [
                {"type": "replay_size", "cols": 120, "rows": 40},
                {"type": "output", "data": "aaaa", "seq": 4},
                {"type": "replay_size", "cols": 100, "rows": 30},
                {"type": "output", "data": "bb", "seq": 6},
                {"type": "replay_size", "cols": 80, "rows": 24},
                {"type": "output", "data": "cc", "seq": 8},
                {"type": "replay_end"},
            ]
            # a resize after the replay is the viewer's own business: only output follows
            session.resize(60, 20)
            pty.feed("live")
            assert json.loads(ws.receive_text()) == {"type": "output", "data": "live", "seq": 12}
    finally:
        terminal._pty_sessions.pop("sess-sizes", None)
        pty.end()


def test_ws_reconnect_mid_stream_replays_only_the_resizes_it_missed(monkeypatch):
    pty, session = _resized_session()
    terminal._pty_sessions["sess-sizes-mid"] = session
    try:
        with _client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-sizes-mid&seq=4"
        ) as ws:
            assert _replay_messages(ws, 5) == [
                {"type": "replay_size", "cols": 100, "rows": 30},
                {"type": "output", "data": "bb", "seq": 6},
                {"type": "replay_size", "cols": 80, "rows": 24},
                {"type": "output", "data": "cc", "seq": 8},
                {"type": "replay_end"},
            ]
        # a resume after the last resize has nothing to relay out
        with _client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-sizes-mid&seq=7"
        ) as ws:
            assert json.loads(ws.receive_text()) == {"type": "output", "data": "c", "seq": 8}
    finally:
        terminal._pty_sessions.pop("sess-sizes-mid", None)
        pty.end()


def test_ws_replay_of_a_truncated_window_starts_at_the_size_that_window_was_drawn_for(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty, max_chunks=2, initial_size=(120, 40))
    for chunk in ("aa", "bb"):
        pty.feed(chunk)
    assert _wait(lambda: session.read_from(0)[1] == 4)
    session.resize(90, 20)
    for chunk in ("cc", "dd"):
        pty.feed(chunk)
    assert _wait(lambda: session.read_from(0)[1] == 8)
    terminal._pty_sessions["sess-sizes-trunc"] = session
    try:
        with _client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-sizes-trunc"
        ) as ws:
            assert _replay_messages(ws, 4) == [
                {"type": "truncated"},
                {"type": "replay_size", "cols": 90, "rows": 20},
                {"type": "output", "data": "ccdd", "seq": 8},
                {"type": "replay_end"},
            ]
    finally:
        terminal._pty_sessions.pop("sess-sizes-trunc", None)
        pty.end()


def test_ws_sends_no_replay_messages_when_the_session_never_had_a_size(monkeypatch):
    pty = _FakePty()
    session = PtySession(pty)
    terminal._pty_sessions["sess-nosize"] = session
    try:
        pty.feed("abc")
        assert _wait(lambda: session.read_from(0)[1] == 3)
        with _client(monkeypatch).websocket_connect(
            "/api/terminal/agent?session_id=sess-nosize"
        ) as ws:
            assert json.loads(ws.receive_text()) == {"type": "output", "data": "abc", "seq": 3}
            pty.feed("d")
            assert json.loads(ws.receive_text())["data"] == "d"
    finally:
        terminal._pty_sessions.pop("sess-nosize", None)
        pty.end()


def _transcript():
    path = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "claude_transcript.json"
    return json.loads(path.read_text(encoding="utf-8"))["chunks"]


def _feed_in_awkward_pieces(pty, text, size=97):
    for i in range(0, len(text), size):
        pty.feed(text[i : i + size])


def test_a_real_transcript_read_in_awkward_pieces_is_stored_without_loss():
    full = "".join(_transcript())
    pty = _FakePty()
    session = PtySession(pty)
    _feed_in_awkward_pieces(pty, full)
    assert _wait(lambda: session.read_from(0)[1] == len(full))
    assert session.read_from(0)[0] == full
    pty.end()


def test_a_real_transcript_window_never_starts_inside_an_escape_sequence():
    full = "".join(_transcript())
    pty = _FakePty()
    session = PtySession(pty, max_chunks=25)
    _feed_in_awkward_pieces(pty, full)
    assert _wait(lambda: session.read_from(0)[1] == len(full))
    start = session.first_offset
    assert 0 < start < len(full)
    assert session.read_from(0)[0] == full[start:]
    assert _complete_prefix_length(full[:start]) == start
    for chunk in _stored(session):
        assert _complete_prefix_length(chunk) == len(chunk)
    pty.end()
