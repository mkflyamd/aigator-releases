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
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "tab"})
    assert r.status_code == 200 and r.json()["scope"] == "tab" and r.json()["saved"] is False
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
    assert r.json()["scope"] == "tab" and r.json()["saved"] is False
    assert saved_permissions.list_entries() == []
    assert task_grants.covers("tab", [], [str(proj)], [])


def test_policy_deny_blocks_saving(client, tmp_path, monkeypatch):
    from sandbox.policy import Policy
    monkeypatch.setattr(sandbox_routes, "load_policy", lambda: Policy(saved_permissions="deny"))
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.json()["scope"] == "tab" and saved_permissions.list_entries() == []


def test_save_failure_falls_back_to_task(client, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("store down")
    monkeypatch.setattr(saved_permissions, "add", boom)
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.status_code == 200 and r.json()["scope"] == "tab" and r.json()["saved"] is False
    assert task_grants.covers("tab", [], [str(proj)], [])


def test_unreadable_store_falls_back_to_task(client, tmp_path):
    secure_store.set_json(saved_permissions._NAME, {"version": 999, "entries": []})
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.status_code == 200 and r.json()["scope"] == "tab" and r.json()["saved"] is False
    assert task_grants.covers("tab", [], [str(proj)], [])


def test_run_python_approval_can_never_be_saved(client):
    req = approvals.create("tab", [], ["/x"], [])
    r = client.post(f"/api/sandbox/requests/{req.id}/approve", json={"context_id": "tab", "scope": "always"})
    assert r.json()["scope"] == "once" and r.json()["saved"] is False
    assert saved_permissions.list_entries() == []
    assert not task_grants.covers("tab", [], ["/x"], [])


def test_run_python_task_approval_adds_task_grant_and_once_does_not(client, tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    task = approvals.create("tab", [str(folder)], [], ["api.example.com:443"])
    r = client.post(f"/api/sandbox/requests/{task.id}/approve", json={"context_id": "tab", "scope": "tab"})
    assert r.json()["scope"] == "tab" and r.json()["saved"] is False
    assert task_grants.covers("tab", [str(folder)], [], ["api.example.com:443"])
    assert saved_permissions.list_entries() == []
    task_grants._reset()
    once = approvals.create("tab", [str(folder)], [], [])
    r = client.post(f"/api/sandbox/requests/{once.id}/approve", json={"context_id": "tab", "scope": "once"})
    assert r.json()["scope"] == "once"
    assert not task_grants.covers("tab", [str(folder)], [], [])


def test_deny_creates_nothing(client, tmp_path):
    proj, req = _shell_request(tmp_path)
    r = client.post(f"/api/sandbox/requests/{req.id}/deny", json={"context_id": "tab", "scope": "tab"})
    assert r.json()["status"] == "denied"
    assert not task_grants.covers("tab", [], [str(proj)], [])


def test_a_saved_shell_set_is_listed_and_removed_with_the_other_permissions(client, tmp_path):
    import permissions
    from routes import permissions_routes

    app = FastAPI()
    app.include_router(permissions_routes.router)
    app.dependency_overrides[verify_csrf] = lambda: None
    api = TestClient(app)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    first = saved_permissions.add([], [str(a)], False, [])
    saved_permissions.add([], [str(b)], False, [])
    permissions.remember("browser")

    rules = api.get("/api/permissions").json()["rules"]
    shell = [r for r in rules if r["category"] == "sandbox:shell"]
    assert len(shell) == 2 and {r["label"] for r in shell} == {"Shell command access"}
    assert any(str(a) in r["subject"] for r in shell)
    assert len(rules) == 3

    assert api.delete(f"/api/permissions/rules/{first['id']}").json() == {"ok": True}
    assert api.delete("/api/permissions/rules/nope").status_code == 404
    assert len(saved_permissions.list_entries()) == 1
    assert api.delete("/api/permissions/rules").json() == {"ok": True}
    assert saved_permissions.list_entries() == [] and api.get("/api/permissions").json()["rules"] == []


def test_the_separate_saved_permissions_routes_are_gone():
    app = FastAPI()
    app.include_router(sandbox_routes.router)
    c = TestClient(app)
    assert c.get("/api/sandbox/saved-permissions").status_code == 404
    assert c.delete("/api/sandbox/saved-permissions").status_code in (404, 405)


def test_sandbox_cards_come_from_the_permission_registry(monkeypatch):
    import permissions
    from sandbox.policy import Policy

    assert permissions.sandbox_card("run_shell", saveable=True) == {"scopes": ["always", "tab"], "primary": "tab"}
    assert permissions.sandbox_card("run_shell", saveable=False) == {"scopes": ["tab"], "primary": "tab"}
    assert permissions.sandbox_card("run_python") == {"scopes": ["tab", "once"], "primary": "tab"}
    monkeypatch.setattr(permissions, "load_policy", lambda: Policy(persistent_permissions="deny"))
    assert permissions.sandbox_card("run_shell", saveable=True) == {"scopes": ["tab"], "primary": "tab"}
