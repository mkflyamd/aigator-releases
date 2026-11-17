from fastapi import FastAPI
from fastapi.testclient import TestClient

from pty_session import PtySession
from routes import terminal
from skills.code_agent import projects


class _DeadPty:
    def isalive(self):
        return False

    def read(self, n=4096):
        raise EOFError

    def close(self):
        pass


def test_agent_terminal_ws_records_active_pty_session(monkeypatch):
    saved = {}
    monkeypatch.setattr(projects, "_load_config", lambda: dict(saved))
    monkeypatch.setattr(projects, "_save_config", lambda cfg: saved.update(cfg))
    terminal._pty_sessions["sess-1"] = PtySession(_DeadPty())
    app = FastAPI()
    app.include_router(terminal.router)
    try:
        with TestClient(app).websocket_connect("/api/terminal/agent?session_id=sess-1") as ws:
            try:
                ws.receive_text()
            except Exception:
                pass
    finally:
        terminal._pty_sessions.pop("sess-1", None)
    assert projects.get_active_pty_session() == "sess-1"
