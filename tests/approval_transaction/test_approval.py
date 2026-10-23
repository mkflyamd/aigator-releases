import json
import os
from pathlib import Path

import pytest

import narration_approval as na

SEGS = [{"text": "Open the app", "start": 0.0}, {"text": "Click save", "start": 2.5}]
FLAGS = {"music": False}


def _project_with_raw(store, data=b"raw-bytes-one"):
    p = store.create_project()
    raw = Path(p["path"]) / "source" / "rec.mp4"
    raw.write_bytes(data)
    store.update_project(p["project_id"], raw=str(raw))
    return p["project_id"], raw


def test_canonical_hash_is_key_order_insensitive():
    a = na.canonical_hash([{"text": "x", "start": 1}], {"a": 1, "b": 2})
    b = na.canonical_hash([{"start": 1, "text": "x"}], {"b": 2, "a": 1})
    assert a == b and len(a) == 64


def test_canonical_hash_changes_with_text():
    assert na.canonical_hash(SEGS, FLAGS) != na.canonical_hash(
        [{"text": "Open the application", "start": 0.0}, SEGS[1]], FLAGS)


def test_fingerprint_none_without_file(tmp_path):
    assert na.media_fingerprint(None) is None
    assert na.media_fingerprint(tmp_path / "missing.mp4") is None


def test_fingerprint_ignores_mtime_and_tracks_content(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(b"A" * 200_000)
    first = na.media_fingerprint(f)
    os.utime(f, (1, 1))
    assert na.media_fingerprint(f) == first
    f.write_bytes(b"A" * 199_999 + b"B")
    assert na.media_fingerprint(f) != first


def test_fingerprint_small_file(tmp_path):
    f = tmp_path / "s.mp4"
    f.write_bytes(b"tiny")
    assert len(na.media_fingerprint(f)) == 64


def test_approve_writes_record_mirror_ext_and_stage(store):
    pid, _ = _project_with_raw(store)
    out = na.approve(pid, SEGS, FLAGS)
    a = out["approval"]
    assert a["version"] == 1 and a["reused"] is False and a["segment_count"] == 2
    assert a["approval_id"] == f"appr_1_{a['sha256'][:8]}"
    root = Path(out["path"])
    record = json.loads((root / "work" / "approvals" / f"{a['approval_id']}.json").read_text("utf-8"))
    assert record["segments"] == SEGS and record["project_id"] == pid
    assert record["media_fingerprint"] == na.media_fingerprint(out["raw"])
    mirror = json.loads((root / "work" / "narration.json").read_text("utf-8"))
    assert mirror["approval_id"] == a["approval_id"] and mirror["segments"] == SEGS
    ext = store.get_project(pid)["ext"]["approval"]
    assert ext["current_id"] == a["approval_id"] and ext["version"] == 1
    assert out["stage"] == "narration_approved"


def test_identical_reapproval_is_reused(store):
    pid, _ = _project_with_raw(store)
    first = na.approve(pid, SEGS, FLAGS)["approval"]
    second = na.approve(pid, SEGS, FLAGS)["approval"]
    assert second["reused"] is True
    assert second["approval_id"] == first["approval_id"] and second["version"] == 1


def test_text_change_bumps_version_and_keeps_old_record(store):
    pid, _ = _project_with_raw(store)
    first = na.approve(pid, SEGS, FLAGS)["approval"]
    second = na.approve(pid, [{"text": "Changed"}], FLAGS)["approval"]
    assert second["version"] == 2 and second["approval_id"] != first["approval_id"]
    root = Path(store.get_project(pid)["path"])
    assert (root / "work" / "approvals" / f"{first['approval_id']}.json").is_file()
    assert (root / "work" / "approvals" / f"{second['approval_id']}.json").is_file()


def test_media_change_bumps_version_even_with_same_text(store):
    pid, raw = _project_with_raw(store)
    first = na.approve(pid, SEGS, FLAGS)["approval"]
    raw.write_bytes(b"different raw bytes here")
    second = na.approve(pid, SEGS, FLAGS)["approval"]
    assert second["version"] == 2 and second["reused"] is False
    assert second["sha256"] == first["sha256"]


@pytest.mark.parametrize("segments,flags", [
    ([], {}),
    (None, {}),
    ("nope", {}),
    ([{"start": 1}], {}),
    ([{"text": 5}], {}),
    (["x"], {}),
    (SEGS, []),
])
def test_validation_rejects_bad_input(store, segments, flags):
    pid, _ = _project_with_raw(store)
    with pytest.raises(na.ApprovalError):
        na.approve(pid, segments, flags)


def test_unknown_project_raises_keyerror(store):
    with pytest.raises(KeyError):
        na.approve("demo_19990101_000000", SEGS, FLAGS)


def test_legacy_mirror_written_next_to_index(store):
    pid, _ = _project_with_raw(store)
    na.approve(pid, SEGS, FLAGS)
    legacy = store.INDEX_PATH.parent / "narration_pending.json"
    data = json.loads(legacy.read_text("utf-8"))
    assert data["segments"] == SEGS and data["flags"] == FLAGS


def test_approval_without_raw_has_null_fingerprint(store):
    p = store.create_project()
    out = na.approve(p["project_id"], SEGS, FLAGS)
    record = json.loads((Path(out["path"]) / "work" / "approvals" /
                         f"{out['approval']['approval_id']}.json").read_text("utf-8"))
    assert record["media_fingerprint"] is None
