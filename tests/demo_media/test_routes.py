from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import demo_compose as compose
import demo_media_probe as probe

BASE = "/api/demo-media"


@pytest.fixture
def client(store):
    from app import app
    from security import get_csrf_token

    c = TestClient(app)
    c.headers["X-CSRF-Token"] = get_csrf_token("testserver")
    return c


@pytest.fixture
def scheduled(monkeypatch):
    calls = []
    monkeypatch.setattr(compose, "schedule", calls.append)
    return calls


def _upload(client, name="a.mp4", data=b"x" * 64, **params):
    return client.post(f"{BASE}/upload", params={"filename": name, **params}, content=data,
                       headers={"Content-Type": "application/octet-stream"})


def test_mutating_routes_require_csrf(store):
    from app import app

    bare = TestClient(app)
    assert bare.post(f"{BASE}/upload", params={"filename": "a.mp4"}, content=b"x").status_code == 403
    assert bare.put(f"{BASE}/p/order", json={"ids": []}).status_code == 403
    assert bare.patch(f"{BASE}/p/clips/c1", json={}).status_code == 403
    assert bare.delete(f"{BASE}/p/items/c1").status_code == 403


def test_upload_creates_project_and_registers_clip(client, store, fake_ffprobe, scheduled):
    fake_ffprobe(duration=12.0)
    res = _upload(client)
    assert res.status_code == 200
    body = res.json()
    pid = body["project_id"]
    folder = Path(store.get_project(pid)["path"])
    assert pid == store.get_active_id()
    assert body["item"]["id"] == "c1" and body["item"]["duration"] == 12.0
    saved = folder / "source" / "c1_a.mp4"
    assert body["path"] == str(saved) and saved.read_bytes() == b"x" * 64
    assert [c["id"] for c in body["clips"]["clips"]] == ["c1"]
    assert list((folder / "source").glob(".upload_*")) == []
    assert scheduled == [pid]


def test_second_upload_joins_the_same_project(client, store, fake_ffprobe, scheduled):
    fake_ffprobe()
    first = _upload(client).json()
    second = _upload(client, name="b.mp4").json()
    assert second["project_id"] == first["project_id"]
    assert second["item"]["id"] == "c2"


def test_audio_upload_lands_in_audio_list(client, fake_ffprobe, scheduled):
    fake_ffprobe(kind="audio", duration=60.0, acodec="mp3")
    body = _upload(client, name="bed.mp3").json()
    assert body["item"]["id"] == "a1"
    assert [a["id"] for a in body["clips"]["audio"]] == ["a1"] and body["clips"]["clips"] == []


def test_upload_starts_a_new_project_after_recording_began(client, store, fake_ffprobe, scheduled):
    fake_ffprobe()
    old = store.create_project()["project_id"]
    store.update_project(old, stage="recording")
    assert _upload(client).json()["project_id"] != old


def test_upload_adopts_an_untouched_created_project(client, store, fake_ffprobe, scheduled):
    fake_ffprobe()
    existing = store.create_project()["project_id"]
    assert _upload(client).json()["project_id"] == existing


def test_unsupported_extension_is_415(client, scheduled):
    res = _upload(client, name="notes.txt")
    assert res.status_code == 415 and res.json()["code"] == "unsupported_type"
    assert res.json()["ok"] is False and scheduled == []


def test_oversize_body_is_413_and_cleans_up(client, store, fake_ffprobe, scheduled, monkeypatch):
    fake_ffprobe()
    monkeypatch.setattr(probe, "MAX_FILE_BYTES", 10)
    pid = store.create_project()["project_id"]
    res = _upload(client, project_id=pid)
    assert res.status_code == 413 and res.json()["code"] == "too_large"
    source = Path(store.get_project(pid)["path"]) / "source"
    assert list(source.iterdir()) == []


def test_probe_rejection_is_422_and_cleans_up(client, store, fake_ffprobe, scheduled):
    fake_ffprobe(kind="audio")
    pid = store.create_project()["project_id"]
    res = _upload(client, name="x.mp4", project_id=pid)
    assert res.status_code == 422 and res.json()["code"] == "no_video_stream"
    assert list((Path(store.get_project(pid)["path"]) / "source").iterdir()) == []
    assert scheduled == []


def test_locked_project_is_409(client, store, fake_ffprobe, scheduled):
    fake_ffprobe()
    pid = store.create_project()["project_id"]
    store.update_project(pid, stage="narration_approved")
    res = _upload(client, project_id=pid)
    assert res.status_code == 409 and res.json()["code"] == "project_locked"
    assert client.delete(f"{BASE}/{pid}/items/c1").status_code == 409


def test_ninth_clip_is_409(client, fake_ffprobe, scheduled):
    fake_ffprobe()
    for i in range(8):
        assert _upload(client, name=f"c{i}.mp4").status_code == 200
    res = _upload(client, name="extra.mp4")
    assert res.status_code == 409 and res.json()["code"] == "too_many"


def test_get_unknown_project_is_404(client):
    res = client.get(f"{BASE}/demo_19990101_000000")
    assert res.status_code == 404 and res.json()["code"] == "not_found"


def test_get_returns_registry_and_reschedules(client, fake_ffprobe, scheduled):
    fake_ffprobe()
    pid = _upload(client).json()["project_id"]
    scheduled.clear()
    body = client.get(f"{BASE}/{pid}").json()
    assert body["ok"] is True and body["project_id"] == pid and body["stage"] == "created"
    assert [c["id"] for c in body["clips"]["clips"]] == ["c1"]
    assert scheduled == [pid]


def test_get_without_clips_does_not_schedule(client, store, scheduled):
    pid = store.create_project()["project_id"]
    assert client.get(f"{BASE}/{pid}").json()["clips"]["clips"] == []
    assert scheduled == []


def test_order_trim_and_delete(client, store, fake_ffprobe, scheduled):
    fake_ffprobe(duration=10.0)
    pid = _upload(client).json()["project_id"]
    _upload(client, name="b.mp4")
    scheduled.clear()

    res = client.put(f"{BASE}/{pid}/order", json={"ids": ["c2", "c1"]})
    assert [c["id"] for c in res.json()["clips"]["clips"]] == ["c2", "c1"]
    bad = client.put(f"{BASE}/{pid}/order", json={"ids": ["c1"]})
    assert bad.status_code == 422 and bad.json()["code"] == "bad_order"

    res = client.patch(f"{BASE}/{pid}/clips/c1", json={"trim_start": 1.0, "trim_end": 6.0})
    clip = next(c for c in res.json()["clips"]["clips"] if c["id"] == "c1")
    assert (clip["trim_start"], clip["trim_end"]) == (1.0, 6.0)
    bad = client.patch(f"{BASE}/{pid}/clips/c1", json={"trim_start": 5.0, "trim_end": 5.2})
    assert bad.status_code == 422 and bad.json()["code"] == "bad_trim"
    assert client.patch(f"{BASE}/{pid}/clips/zz", json={"trim_start": 0.0}).status_code == 404

    res = client.delete(f"{BASE}/{pid}/items/c2")
    assert [c["id"] for c in res.json()["clips"]["clips"]] == ["c1"]
    assert not (Path(store.get_project(pid)["path"]) / "source" / "c2_b.mp4").exists()
    assert client.delete(f"{BASE}/{pid}/items/c2").status_code == 404
    assert scheduled == [pid] * 3


def test_deleted_project_folder_is_404(client, store, scheduled):
    import shutil

    created = store.create_project()
    shutil.rmtree(created["path"])
    assert client.get(f"{BASE}/{created['project_id']}").status_code == 404
    res = _upload(client, project_id=created["project_id"])
    assert res.status_code == 404


def test_client_disconnect_mid_upload_leaves_nothing_behind(client, store, fake_ffprobe, scheduled, monkeypatch):
    from starlette.requests import ClientDisconnect, Request

    fake_ffprobe()
    first = _upload(client).json()
    pid = first["project_id"]
    folder = Path(store.get_project(pid)["path"])
    scheduled.clear()

    async def cut_off(self):
        yield b"x" * 32
        raise ClientDisconnect()

    with monkeypatch.context() as patch:
        patch.setattr(Request, "stream", cut_off)
        res = _upload(client, name="b.mp4")

    assert res.status_code == 499 and res.json()["code"] == "cancelled"
    assert list((folder / "source").glob(".upload_*")) == []
    assert not list((folder / "source").glob("c2_*"))
    assert scheduled == []
    assert [c["id"] for c in client.get(f"{BASE}/{pid}").json()["clips"]["clips"]] == ["c1"]
