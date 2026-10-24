import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import demo_project_delivery as delivery
from app import app
from security import get_csrf_token


@pytest.fixture
def client():
    c = TestClient(app)
    c.headers["X-CSRF-Token"] = get_csrf_token("testserver")
    return c


def _project(store):
    proj = store.create_project("Delivery demo")
    return proj["project_id"], Path(proj["path"])


def test_summary_without_final(store):
    pid, root = _project(store)
    s = delivery.project_summary(pid)
    assert s["project_id"] == pid
    assert s["final"] is None and s["final_rel"] is None
    assert s["source_count"] == 0
    assert Path(s["final_dir"]).name == "final"


def test_summary_raw_rel_is_project_relative(store):
    pid, root = _project(store)
    (root / "source").mkdir(parents=True, exist_ok=True)
    raw = root / "source" / "raw.mp4"
    raw.write_bytes(b"v")
    store.update_project(pid, raw=str(raw))
    assert delivery.project_summary(pid)["raw_rel"] == "source/raw.mp4"


def test_summary_raw_rel_none_without_a_raw_video(store):
    pid, root = _project(store)
    assert delivery.project_summary(pid)["raw_rel"] is None


def test_summary_with_final_sources_and_work_bytes(store):
    pid, root = _project(store)
    base = delivery.project_summary(pid)["work_bytes"]
    (root / "final").mkdir(parents=True, exist_ok=True)
    (root / "final" / "AI_Gator_Demo.mp4").write_bytes(b"abc")
    (root / "work" / "tts").mkdir(parents=True, exist_ok=True)
    (root / "work" / "logs").mkdir(parents=True, exist_ok=True)
    (root / "work" / "tts" / "a.mp3").write_bytes(b"x" * 1000)
    (root / "work" / "logs" / "b.log").write_bytes(b"y" * 24)
    (root / "source").mkdir(parents=True, exist_ok=True)
    sources = []
    for i in range(3):
        f = root / "source" / f"s{i}.mp4"
        f.write_bytes(b"v")
        sources.append(str(f))
    store.update_project(pid, segments=sources)

    s = delivery.project_summary(pid)
    assert s["final_rel"] == "final/AI_Gator_Demo.mp4"
    assert Path(s["final"]).name == "AI_Gator_Demo.mp4"
    assert s["source_count"] == 3
    assert s["work_bytes"] - base == 1024


def test_read_progress_states(store):
    pid, root = _project(store)
    assert delivery.read_progress(pid) == {"state": "none"}
    target = root / "work" / "logs" / "merge_progress.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"approval_id": "a1", "state": "running", "message": "Merging"}), encoding="utf-8")
    assert delivery.read_progress(pid)["approval_id"] == "a1"
    target.write_text("{not json", encoding="utf-8")
    assert delivery.read_progress(pid) == {"state": "none"}
    target.write_text("[1, 2]", encoding="utf-8")
    assert delivery.read_progress(pid) == {"state": "none"}


def test_routes(store, client):
    pid, root = _project(store)
    (root / "final").mkdir(parents=True, exist_ok=True)
    (root / "final" / "AI_Gator_Demo.mp4").write_bytes(b"abc")
    r = client.get(f"/api/demo-projects/{pid}/summary")
    assert r.status_code == 200
    assert r.json()["final_rel"] == "final/AI_Gator_Demo.mp4"
    r = client.get(f"/api/demo-projects/{pid}/progress")
    assert r.status_code == 200
    assert r.json() == {"state": "none"}


def test_unknown_project_is_404(store, client):
    assert client.get("/api/demo-projects/demo_missing/summary").status_code == 404
    assert client.get("/api/demo-projects/demo_missing/progress").status_code == 404
