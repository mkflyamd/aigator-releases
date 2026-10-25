import json

import pytest
from fastapi.testclient import TestClient

from app import app
from security import get_csrf_token


@pytest.fixture
def client(store):
    c = TestClient(app)
    c.headers["X-CSRF-Token"] = get_csrf_token("testserver")
    return c


def test_latest_output_404_without_project(client):
    assert client.get("/api/recorder/latest-output").status_code == 404


def test_latest_output_derived_from_active_project(client, store):
    pid = store.create_project()["project_id"]
    folder = store.project_path(pid)
    (folder / "source" / "recording.mp4").write_bytes(b"r")
    store.update_project(pid, raw=folder / "source" / "recording.mp4", stage="recorded")
    (folder / "final" / "demo.mp4").write_bytes(b"f")
    body = client.get("/api/recorder/latest-output").json()
    assert body["project_id"] == pid
    assert body["raw"] == str(folder / "source" / "recording.mp4")
    assert body["final"] == str(folder / "final" / "demo.mp4")


def test_narration_approved_writes_project_and_legacy_file(client, store, tmp_path):
    pid = store.create_project()["project_id"]
    r = client.post("/api/recorder/narration-approved", json={"segments": [{"text": "hi"}], "flags": {}})
    assert r.status_code == 200
    assert (store.project_path(pid) / "work" / "narration.json").exists()
    legacy = json.loads((store.INDEX_PATH.parent / "narration_pending.json").read_text(encoding="utf-8"))
    assert legacy["segments"] == [{"text": "hi"}]


def test_set_output_shim(client, store):
    pid = store.create_project()["project_id"]
    folder = store.project_path(pid)
    assert client.post("/api/recorder/set-output", json={"final": str(folder / "final" / "d.mp4")}).status_code == 200
    assert client.post("/api/recorder/set-output", json={"final": "C:/elsewhere/d.mp4"}).status_code == 400


def test_serve_file_allows_any_project_folder(client, store, tmp_path):
    pid = store.create_project(root=tmp_path / "other")["project_id"]
    f = store.project_path(pid) / "final" / "d.mp4"
    f.write_bytes(b"vid")
    assert client.get("/api/recorder/serve-file", params={"path": str(f)}).status_code == 200
    assert client.get("/api/recorder/serve-file", params={"path": str(tmp_path / "x.mp4")}).status_code == 403


def test_serve_file_serves_png_frames_but_not_outside_projects(client, store, tmp_path):
    pid = store.create_project(root=tmp_path / "other")["project_id"]
    frames = store.project_path(pid) / "work" / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    f = frames / "f_0001.png"
    f.write_bytes(b"\x89PNG")
    ok = client.get("/api/recorder/serve-file", params={"path": str(f)})
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    outside = tmp_path / "x.png"
    outside.write_bytes(b"\x89PNG")
    assert client.get("/api/recorder/serve-file", params={"path": str(outside)}).status_code == 403
