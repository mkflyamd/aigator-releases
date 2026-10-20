import pytest
from fastapi.testclient import TestClient

from app import app
from security import get_csrf_token


@pytest.fixture
def client(store):
    c = TestClient(app)
    c.headers["X-CSRF-Token"] = get_csrf_token("testserver")
    return c


def test_create_list_get_active(client):
    r = client.post("/api/demo-projects", json={"name": "Quarterly demo"})
    assert r.status_code == 200
    pid = r.json()["project_id"]
    assert r.json()["name"] == "Quarterly demo"
    assert client.get("/api/demo-projects/active").json()["project_id"] == pid
    assert client.get(f"/api/demo-projects/{pid}").json()["stage"] == "created"
    assert [p["project_id"] for p in client.get("/api/demo-projects").json()["projects"]] == [pid]


def test_settings_not_shadowed_and_round_trip(client, tmp_path):
    r = client.get("/api/demo-projects/settings")
    assert r.status_code == 200 and r.json()["is_default"] is True
    target = tmp_path / "chosen"
    r = client.put("/api/demo-projects/settings", json={"root": str(target)})
    assert r.status_code == 200 and r.json()["default_root"] == str(target)
    assert client.get("/api/demo-projects/settings").json()["is_default"] is False
    assert client.put("/api/demo-projects/settings", json={"root": None}).json()["is_default"] is True


def test_settings_rejects_relative_root(client):
    assert client.put("/api/demo-projects/settings", json={"root": "rel/dir"}).status_code == 400


def test_unknown_project_404(client):
    assert client.get("/api/demo-projects/demo_19990101_000000").status_code == 404
    assert client.post("/api/demo-projects/demo_19990101_000000/activate").status_code == 404


def test_activate(client):
    a = client.post("/api/demo-projects", json={}).json()["project_id"]
    b = client.post("/api/demo-projects", json={}).json()["project_id"]
    assert client.get("/api/demo-projects/active").json()["project_id"] == b
    assert client.post(f"/api/demo-projects/{a}/activate").status_code == 200
    assert client.get("/api/demo-projects/active").json()["project_id"] == a


def test_narration_writes_file_and_stage(client, store):
    pid = client.post("/api/demo-projects", json={}).json()["project_id"]
    r = client.post(f"/api/demo-projects/{pid}/narration",
                    json={"segments": [{"text": "hi"}], "flags": {"music": False}})
    assert r.status_code == 200 and r.json()["stage"] == "narration_approved"
    assert (store.project_path(pid) / "work" / "narration.json").exists()


def test_file_route_serves_inside_and_blocks_outside(client, store):
    pid = client.post("/api/demo-projects", json={}).json()["project_id"]
    (store.project_path(pid) / "final" / "demo.mp4").write_bytes(b"vid")
    ok = client.get(f"/api/demo-projects/{pid}/file", params={"rel": "final/demo.mp4"})
    assert ok.status_code == 200 and ok.content == b"vid"
    assert ok.headers["content-type"] == "video/mp4"
    assert client.get(f"/api/demo-projects/{pid}/file", params={"rel": "../x"}).status_code == 403
    assert client.get(f"/api/demo-projects/{pid}/file", params={"rel": "final/none.mp4"}).status_code == 404


def test_file_route_serves_png_frames_with_their_media_type(client, store):
    pid = client.post("/api/demo-projects", json={}).json()["project_id"]
    frames = store.project_path(pid) / "work" / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    (frames / "f_0001.png").write_bytes(b"\x89PNG")
    ok = client.get(f"/api/demo-projects/{pid}/file", params={"rel": "work/frames/f_0001.png"})
    assert ok.status_code == 200 and ok.content == b"\x89PNG"
    assert ok.headers["content-type"] == "image/png"
    assert client.get(f"/api/demo-projects/{pid}/file", params={"rel": "../f_0001.png"}).status_code == 403


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/demo-projects", {}),
    ("put", "/api/demo-projects/settings", {"root": None}),
    ("post", "/api/demo-projects/demo_19990101_000000/activate", None),
    ("post", "/api/demo-projects/demo_19990101_000000/narration", {"segments": []}),
])
def test_mutating_routes_require_csrf(store, method, path, body):
    c = TestClient(app)
    r = getattr(c, method)(path, json=body) if body is not None else getattr(c, method)(path)
    assert r.status_code == 403


@pytest.fixture
def deleted_project(client):
    import shutil

    created = client.post("/api/demo-projects", json={}).json()
    shutil.rmtree(created["path"])
    return created["project_id"]


@pytest.mark.parametrize("method,path,body", [
    ("get", "", None),
    ("get", "/summary", None),
    ("get", "/progress", None),
    ("get", "/file?rel=final/x.mp4", None),
    ("post", "/activate", None),
    ("post", "/narration", {"segments": [{"text": "a"}], "flags": {}}),
])
def test_deleted_project_folder_is_404_not_500(client, deleted_project, method, path, body):
    res = getattr(client, method)(f"/api/demo-projects/{deleted_project}{path}", **({"json": body} if body else {}))
    assert res.status_code == 404
    assert res.json()["detail"] == "Project not found"


def test_deleted_active_project_legacy_shims_are_404(client, deleted_project):
    assert client.get("/api/recorder/latest-output").status_code == 404
    res = client.post("/api/recorder/narration-approved", json={"segments": [{"text": "a"}], "flags": {}})
    assert res.status_code == 404


def test_deleted_project_vanishes_from_the_list(client, deleted_project):
    assert client.get("/api/demo-projects").json()["projects"] == []


def test_activating_a_deleted_project_keeps_the_previous_active_one(client, deleted_project):
    other = client.post("/api/demo-projects", json={}).json()["project_id"]
    assert client.post(f"/api/demo-projects/{deleted_project}/activate").status_code == 404
    assert client.get("/api/demo-projects/active").json()["project_id"] == other
