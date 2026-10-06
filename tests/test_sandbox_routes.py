import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import pytest
from fastapi.testclient import TestClient

import config
import sandbox
from app import app
from sandbox import approvals
from sandbox.policy import Policy
import routes.sandbox_routes as sandbox_routes


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def csrf():
    from security import get_csrf_token

    return {"X-CSRF-Token": get_csrf_token()}


@pytest.fixture(autouse=True)
def _fresh():
    approvals._reset()
    yield
    approvals._reset()


@pytest.fixture
def cfg(monkeypatch):
    store = {}

    def update(mutator):
        result = mutator(dict(store))
        store.clear()
        store.update(result if result is not None else {})
        return dict(store)

    monkeypatch.setattr(config, "load_config", lambda: dict(store))
    monkeypatch.setattr(config, "update_config", update)
    return store


def test_approve_requires_csrf(client):
    req = approvals.create("tab-1", ["C:/data"], [], [])
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab-1"})
    assert r.status_code == 403
    assert approvals._REQUESTS[req.id].status == "pending"


def test_approve_and_deny(client, csrf):
    a = approvals.create("tab-1", ["C:/a"], [], [])
    d = approvals.create("tab-1", ["C:/d"], [], [])
    r = client.post(f"/api/sandbox/requests/{a.id}/approve", json={"context_id": "tab-1"}, headers=csrf)
    assert r.status_code == 200 and r.json() == {"ok": True, "request_id": a.id, "status": "approved"}
    r = client.post(f"/api/sandbox/requests/{d.id}/deny", json={"context_id": "tab-1"}, headers=csrf)
    assert r.json()["status"] == "denied"


def test_wrong_tab_unknown_and_repeat(client, csrf):
    a = approvals.create("tab-1", ["C:/a"], [], [])
    assert client.post(f"/api/sandbox/requests/{a.id}/approve", json={"context_id": "tab-2"}, headers=csrf).status_code == 409
    assert client.post("/api/sandbox/requests/nope/approve", json={"context_id": "tab-1"}, headers=csrf).status_code == 404
    client.post(f"/api/sandbox/requests/{a.id}/approve", json={"context_id": "tab-1"}, headers=csrf)
    assert client.post(f"/api/sandbox/requests/{a.id}/deny", json={"context_id": "tab-1"}, headers=csrf).status_code == 409


def test_expired_is_410(client, csrf):
    a = approvals.create("tab-1", ["C:/a"], [], [])
    a.created_at -= 601
    assert client.post(f"/api/sandbox/requests/{a.id}/approve", json={"context_id": "tab-1"}, headers=csrf).status_code == 410


def test_status(client, cfg, monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "unavailable")
    monkeypatch.setattr(sandbox, "sandbox_unavailable_reason", lambda: "install bubblewrap")
    cfg["code_runner_sandbox"] = "off"
    r = client.get("/api/sandbox/status")
    assert r.status_code == 200
    assert r.json() == {
        "level": "unavailable", "reason": "install bubblewrap", "opted_out": True,
        "policy": {"code_runner": "enabled", "network": "ask", "filesystem": "ask", "require_sandbox": False},
    }


def test_opt_out_requires_csrf_and_round_trips(client, csrf, cfg):
    assert client.post("/api/sandbox/opt-out", json={"opted_out": True}).status_code == 403
    assert "code_runner_sandbox" not in cfg
    assert client.post("/api/sandbox/opt-out", json={"opted_out": True}, headers=csrf).json() == {"ok": True, "opted_out": True}
    assert cfg["code_runner_sandbox"] == "off"
    client.post("/api/sandbox/opt-out", json={"opted_out": False}, headers=csrf)
    assert "code_runner_sandbox" not in cfg


def test_opt_out_refused_when_policy_requires_sandbox(client, csrf, cfg, monkeypatch):
    monkeypatch.setattr(sandbox_routes, "load_policy", lambda: Policy(require_sandbox=True))
    r = client.post("/api/sandbox/opt-out", json={"opted_out": True}, headers=csrf)
    assert r.status_code == 409
    assert "code_runner_sandbox" not in cfg


def test_opt_out_is_not_patchable_through_generic_config_route():
    assert "code_runner_sandbox" not in config.PATCHABLE_CONFIG_KEYS
