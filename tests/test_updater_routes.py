import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from routes.updater import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_install_update_rejected_when_not_ready(client, monkeypatch):
    import updater

    updater._state = updater._UpdateState()
    updater._state.state = "error"

    called = {"launched": False}
    monkeypatch.setattr(updater, "launch_installer", lambda: called.__setitem__("launched", True))

    resp = client.post("/api/update/install")

    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "reason": "Update not ready"}
    assert called["launched"] is False


def test_install_update_launches_when_ready(client, monkeypatch):
    import updater

    updater._state = updater._UpdateState()
    updater._state.state = "ready"

    called = {"launched": False}
    monkeypatch.setattr(updater, "launch_installer", lambda: called.__setitem__("launched", True))

    resp = client.post("/api/update/install")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert called["launched"] is True
