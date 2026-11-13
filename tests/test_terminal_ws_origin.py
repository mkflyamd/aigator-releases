import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from routes import terminal
from security import websocket_origin_allowed

HOST = "127.0.0.1:8000"


def _client():
    app = FastAPI()
    app.include_router(terminal.router)
    return TestClient(app)


@pytest.mark.parametrize("path", ["/api/terminal/ws", "/api/terminal/agent?session_id=missing"])
def test_cross_origin_handshake_is_refused(path, monkeypatch):
    monkeypatch.setattr(terminal, "_spawn_pty", lambda **_: pytest.fail("PTY spawned for a foreign origin"))
    with pytest.raises(WebSocketDisconnect) as exc:
        with _client().websocket_connect(path, headers={"host": HOST, "origin": "http://127.0.0.1:3030"}):
            pass
    assert exc.value.code == 1008


def test_same_origin_handshake_is_accepted():
    with _client().websocket_connect(
        "/api/terminal/agent?session_id=missing", headers={"host": HOST, "origin": f"http://{HOST}"}
    ) as ws:
        assert "notready" in ws.receive_text()


def test_helper_matches_origin_rules():
    assert websocket_origin_allowed(HOST, f"http://{HOST}")
    assert websocket_origin_allowed(HOST, None)
    assert not websocket_origin_allowed(HOST, "http://127.0.0.1:3030")
    assert not websocket_origin_allowed(HOST, "https://evil.example")
