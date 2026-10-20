import json
from pathlib import Path

SEGS = [{"text": "Open the app"}, {"text": "Click save"}]


def test_narration_route_returns_approval(client, store):
    pid = store.create_project()["project_id"]
    r = client.post(f"/api/demo-projects/{pid}/narration", json={"segments": SEGS, "flags": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["approval"]["version"] == 1 and body["approval"]["segment_count"] == 2
    assert body["stage"] == "narration_approved"


def test_narration_route_empty_segments_is_400(client, store):
    pid = store.create_project()["project_id"]
    r = client.post(f"/api/demo-projects/{pid}/narration", json={"segments": [], "flags": {}})
    assert r.status_code == 400


def test_narration_route_unknown_project_is_404(client):
    r = client.post("/api/demo-projects/demo_19990101_000000/narration",
                    json={"segments": SEGS, "flags": {}})
    assert r.status_code == 404


def test_narration_route_requires_csrf(client, store):
    pid = store.create_project()["project_id"]
    r = client.post(f"/api/demo-projects/{pid}/narration", json={"segments": SEGS, "flags": {}},
                    headers={"X-CSRF-Token": ""})
    assert r.status_code == 403


def test_reapproval_same_content_reports_reused(client, store):
    pid = store.create_project()["project_id"]
    client.post(f"/api/demo-projects/{pid}/narration", json={"segments": SEGS, "flags": {}})
    r = client.post(f"/api/demo-projects/{pid}/narration", json={"segments": SEGS, "flags": {}})
    assert r.json()["approval"]["reused"] is True


def test_legacy_shim_uses_transaction(client, store):
    pid = store.create_project()["project_id"]
    r = client.post("/api/recorder/narration-approved", json={"segments": SEGS, "flags": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["project_id"] == pid
    assert body["approval"]["version"] == 1
    root = Path(store.get_project(pid)["path"])
    mirror = json.loads((root / "work" / "narration.json").read_text("utf-8"))
    assert mirror["approval_id"] == body["approval"]["approval_id"]


def test_legacy_shim_rejects_empty_segments(client, store):
    store.create_project()
    r = client.post("/api/recorder/narration-approved", json={"segments": [], "flags": {}})
    assert r.status_code == 400 and r.json()["ok"] is False
