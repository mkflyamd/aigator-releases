import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import secure_store
from routes import sandbox_routes
from sandbox import approvals, saved_permissions, task_grants
from security import verify_csrf


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(sandbox_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    approvals._reset()
    task_grants._reset()
    yield TestClient(app)
    approvals._reset()
    task_grants._reset()


def _shell_request(tmp_path, saveable=True, hosts=()):
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    return proj, approvals.create("tab", [], [str(proj)], list(hosts), tool="run_shell", command="git pull",
                                  programs=("git",), saveable=saveable)


def test_approve_task_adds_task_grant(client, tmp_path):
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "task"})
    assert r.status_code == 200 and r.json()["scope"] == "task" and r.json()["saved"] is False
    assert task_grants.covers("tab", [], [str(proj)], [])


def test_approve_always_saves_and_adds_no_task_grant(client, tmp_path):
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.json()["scope"] == "always" and r.json()["saved"] is True
    assert saved_permissions.covers([], [str(proj)], [], None)
    assert not task_grants.covers("tab", [], [str(proj)], [])


def test_always_on_unsaveable_request_becomes_task(client, tmp_path):
    proj, req = _shell_request(tmp_path, saveable=False)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.json()["scope"] == "task" and r.json()["saved"] is False
    assert saved_permissions.list_entries() == []
    assert task_grants.covers("tab", [], [str(proj)], [])


def test_policy_deny_blocks_saving(client, tmp_path, monkeypatch):
    from sandbox.policy import Policy
    monkeypatch.setattr(sandbox_routes, "load_policy", lambda: Policy(saved_permissions="deny"))
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.json()["scope"] == "task" and saved_permissions.list_entries() == []


def test_save_failure_falls_back_to_task(client, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("store down")
    monkeypatch.setattr(saved_permissions, "add", boom)
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.status_code == 200 and r.json()["scope"] == "task" and r.json()["saved"] is False
    assert task_grants.covers("tab", [], [str(proj)], [])


def test_unreadable_store_falls_back_to_task(client, tmp_path):
    secure_store.set_json(saved_permissions._NAME, {"version": 999, "entries": []})
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.status_code == 200 and r.json()["scope"] == "task" and r.json()["saved"] is False
    assert task_grants.covers("tab", [], [str(proj)], [])


def test_run_python_approval_unchanged(client):
    req = approvals.create("tab", [], ["/x"], [])
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.json()["scope"] == "once" and r.json()["saved"] is False
    assert saved_permissions.list_entries() == []


def test_deny_creates_nothing(client, tmp_path):
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/deny", json={"context_id": "tab", "scope": "task"})
    assert r.json()["status"] == "denied"
    assert not task_grants.covers("tab", [], [str(proj)], [])


def test_list_and_remove_saved_permissions(client, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    first = saved_permissions.add([], [str(a)], False, [])
    saved_permissions.add([], [str(b)], False, [])
    body = client.get("/api/sandbox/saved-permissions").json()
    assert len(body["entries"]) == 2 and set(body["entries"][0]) == {"id", "description", "created"}
    assert client.delete(f"/api/sandbox/saved-permissions/{first['id']}").json() == {"ok": True}
    assert client.delete("/api/sandbox/saved-permissions/nope").status_code == 404
    assert len(client.get("/api/sandbox/saved-permissions").json()["entries"]) == 1
    assert client.delete("/api/sandbox/saved-permissions").json() == {"ok": True}
    assert client.get("/api/sandbox/saved-permissions").json()["entries"] == []


def test_new_routes_require_csrf():
    app = FastAPI()
    app.include_router(sandbox_routes.router)
    c = TestClient(app)
    assert c.get("/api/sandbox/saved-permissions").status_code in (401, 403)
    assert c.delete("/api/sandbox/saved-permissions").status_code in (401, 403)
    assert c.delete("/api/sandbox/saved-permissions/x").status_code in (401, 403)
