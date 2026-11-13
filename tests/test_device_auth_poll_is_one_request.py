"""Each device sign-in poll makes one token request and returns, so polls never pile up on threads."""

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

SRC = Path(__file__).resolve().parents[1] / "web" / "skills" / "m365-email" / "graph_client.py"
_spec = importlib.util.spec_from_file_location("graph_client_device_poll_under_test", SRC)
gcm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gcm)


def _http_error(error: str, description: str = "") -> urllib.error.HTTPError:
    body = json.dumps({"error": error, "error_description": description}).encode()
    return urllib.error.HTTPError("https://login.invalid", 400, "Bad Request", {}, io.BytesIO(body))


@pytest.fixture
def device_client(monkeypatch):
    def forbid_sleep(seconds):
        raise AssertionError("complete_auth must not sleep between token requests")

    monkeypatch.setattr(gcm.time, "sleep", forbid_sleep)
    gc = gcm.GraphClient.__new__(gcm.GraphClient)
    gc._client_id = "aigator-fake-api-key"
    gc._tenant_id = "organizations"
    return gc


@pytest.mark.parametrize("error", ["authorization_pending", "slow_down"])
def test_pending_sign_in_returns_after_one_request(device_client, monkeypatch, error):
    requests = []

    def urlopen(req, timeout=None):
        requests.append(req)
        raise _http_error(error)

    monkeypatch.setattr(gcm.urllib.request, "urlopen", urlopen)
    assert device_client.complete_auth("aigator-fake-api-key") == {"status": "pending"}
    assert len(requests) == 1


def test_expired_code_is_an_error_not_pending(device_client, monkeypatch):
    def urlopen(req, timeout=None):
        raise _http_error("expired_token", "The device code has expired.")

    monkeypatch.setattr(gcm.urllib.request, "urlopen", urlopen)
    result = device_client.complete_auth("aigator-fake-api-key")
    assert result["status"] == "error"
    assert "expired_token" in result["error"]


def test_completed_sign_in_saves_the_token(device_client, monkeypatch):
    saved = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"access_token": "aigator-fake-api-key", "expires_in": 3600}).encode()

    monkeypatch.setattr(gcm.urllib.request, "urlopen", lambda *a, **k: _Resp())
    monkeypatch.setattr(device_client, "_save_token", lambda: saved.append(True))
    assert device_client.complete_auth("aigator-fake-api-key")["status"] == "ok"
    assert saved == [True]


@pytest.fixture
def route_client(monkeypatch):
    from routes import auth
    import skills._m365.helpers as helpers

    app = FastAPI()
    app.include_router(auth.router)
    monkeypatch.setattr(helpers, "reset_graph_client", lambda: None)
    return TestClient(app), helpers, monkeypatch


def _fake_graph_client(result):
    class _Fake:
        _tenant_id = None

        def complete_auth(self, device_code):
            return result

    return _Fake


def test_route_reports_pending(route_client):
    client, helpers, monkeypatch = route_client
    monkeypatch.setattr(helpers, "GraphClient", _fake_graph_client({"status": "pending"}))
    body = client.post("/api/auth/device/poll", json={"device_code": "aigator-fake-api-key"}).json()
    assert body == {"ok": False, "pending": True}


def test_route_stops_polling_on_a_terminal_error(route_client):
    client, helpers, monkeypatch = route_client
    monkeypatch.setattr(
        helpers, "GraphClient", _fake_graph_client({"status": "error", "error": "expired_token: gone"})
    )
    body = client.post("/api/auth/device/poll", json={"device_code": "aigator-fake-api-key"}).json()
    assert body["ok"] is False
    assert body["pending"] is False
    assert "expired_token" in body["error"]
