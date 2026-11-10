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


def _available_state(install_supported):
    import updater

    updater._state = updater._UpdateState()
    updater._state.state = "available"
    updater._state.info = updater.UpdateInfo(
        version="1.1.0",
        url="https://github.com/mkflyamd/aigator-releases/releases/download/v1.1.0/AI-Gator-1.1.0-Windows-x64.exe",
        sha256="a" * 64,
        notes="",
        install_supported=install_supported,
    )


def test_status_reports_install_support_and_release_page(client):
    import updater

    _available_state(False)
    data = client.get("/api/update/status").json()

    assert data["available"] is True
    assert data["install_supported"] is False
    assert data["release_url"] == updater.RELEASE_PAGE_URL


def test_download_refused_when_release_cannot_be_installed_in_app(client):
    import updater

    _available_state(False)
    resp = client.post("/api/update/download")

    assert resp.json()["ok"] is False
    assert updater._state.state == "available"
