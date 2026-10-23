import json
import re

import pytest


def test_create_builds_layout_and_project_json(store, tmp_path):
    p = store.create_project()
    assert re.fullmatch(r"demo_\d{8}_\d{6}", p["project_id"])
    folder = tmp_path / "demos" / p["project_id"]
    for sub in ("final", "previous", "source", "work/normalized", "work/frames", "work/tts", "work/logs"):
        assert (folder / sub).is_dir(), sub
    data = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["stage"] == "created"
    assert data["segments"] == [] and data["raw"] is None and data["ext"] == {}
    assert store.get_active_id() == p["project_id"]


def test_create_collision_gets_suffix(store, monkeypatch):
    class _Fixed:
        @staticmethod
        def now(tz=None):
            from datetime import datetime
            return datetime(2026, 10, 19, 14, 30, 12)
    monkeypatch.setattr(store, "datetime", _Fixed)
    a = store.create_project()
    b = store.create_project()
    assert a["project_id"] == "demo_20261019_143012"
    assert b["project_id"] == "demo_20261019_143012_2"


def test_create_with_custom_root_is_found_via_index(store, tmp_path):
    root = tmp_path / "elsewhere"
    p = store.create_project(root=root)
    assert store.project_path(p["project_id"]) == root / p["project_id"]


def test_atomic_write_leaves_no_temp_files(store, tmp_path):
    target = tmp_path / "x" / "a.json"
    store.atomic_write_json(target, {"a": 1})
    store.atomic_write_json(target, {"a": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}
    assert [f.name for f in target.parent.iterdir()] == ["a.json"]


def test_update_stores_relative_paths_and_get_expands(store):
    p = store.create_project()
    pid = p["project_id"]
    folder = store.project_path(pid)
    (folder / "source" / "seg_00.mp4").write_bytes(b"x")
    store.update_project(pid, segments=[folder / "source" / "seg_00.mp4"],
                         raw=folder / "source" / "seg_00.mp4", stage="recorded")
    on_disk = json.loads((folder / "project.json").read_text(encoding="utf-8"))
    assert on_disk["segments"] == ["source/seg_00.mp4"]
    assert on_disk["raw"] == "source/seg_00.mp4"
    got = store.get_project(pid)
    assert got["segments"] == [str(folder / "source" / "seg_00.mp4")]
    assert got["raw"] == str(folder / "source" / "seg_00.mp4")
    assert got["final"] is None and got["stage"] == "recorded"


def test_update_rejects_unknown_field_and_bad_stage(store):
    pid = store.create_project()["project_id"]
    with pytest.raises(ValueError):
        store.update_project(pid, bogus=1)
    with pytest.raises(ValueError):
        store.update_project(pid, stage="nope")


def test_update_rejects_path_outside_project(store, tmp_path):
    pid = store.create_project()["project_id"]
    with pytest.raises(ValueError):
        store.update_project(pid, raw=tmp_path / "elsewhere.mp4")


def test_final_is_derived_from_disk_and_marks_delivered(store):
    pid = store.create_project()["project_id"]
    folder = store.project_path(pid)
    store.update_project(pid, stage="recorded")
    (folder / "final" / "demo.mp4").write_bytes(b"x")
    got = store.get_project(pid)
    assert got["final"] == str(folder / "final" / "demo.mp4")
    assert got["stage"] == "delivered"
    assert got["final_dir"] == str(folder / "final")


def test_archive_final_moves_files_to_previous(store):
    pid = store.create_project()["project_id"]
    folder = store.project_path(pid)
    (folder / "final" / "demo.mp4").write_bytes(b"x")
    moved = store.archive_final(pid)
    assert len(moved) == 1 and moved[0].parent == folder / "previous"
    assert moved[0].name.endswith("_demo.mp4")
    assert list((folder / "final").iterdir()) == []


def test_set_ext_namespaces(store):
    pid = store.create_project()["project_id"]
    store.set_ext(pid, "approval", {"ok": True})
    store.set_ext(pid, "media", {"n": 2})
    assert store.get_project(pid)["ext"] == {"approval": {"ok": True}, "media": {"n": 2}}


def test_resolve_file_blocks_traversal(store):
    pid = store.create_project()["project_id"]
    folder = store.project_path(pid)
    assert store.resolve_file(pid, "source/seg_00.mp4") == (folder / "source" / "seg_00.mp4").resolve()
    for bad in ("../x.mp4", "source/../../x.mp4", "/etc/passwd"):
        with pytest.raises(ValueError):
            store.resolve_file(pid, bad)


def test_set_active_unknown_project_raises(store):
    with pytest.raises(KeyError):
        store.set_active("demo_19990101_000000")


def test_index_trims_to_50_and_drops_missing_folders(store):
    ids = []
    for i in range(52):
        ids.append(store._register_for_test(f"demo_20260101_{i:06d}"))
    idx = json.loads(store.INDEX_PATH.read_text(encoding="utf-8"))
    assert len(idx["projects"]) == 50


def test_begin_session_creates_then_reuses(store):
    a = store.begin_session()
    assert store.get_active_id() == a["project_id"]
    other = store.create_project()
    again = store.begin_session(a["project_id"])
    assert again["project_id"] == a["project_id"]
    assert store.get_active_id() == a["project_id"]
    assert other["project_id"] != a["project_id"]


def test_save_narration_writes_file_and_stage(store):
    pid = store.create_project()["project_id"]
    out = store.save_narration(pid, [{"text": "hi"}], {"music": True})
    folder = store.project_path(pid)
    data = json.loads((folder / "work" / "narration.json").read_text(encoding="utf-8"))
    assert data["segments"] == [{"text": "hi"}] and data["flags"] == {"music": True}
    assert out["stage"] == "narration_approved"
    assert out["narration"]["approved_at"]


def test_missing_project_folder_raises_key_error(store):
    import shutil

    p = store.create_project()
    shutil.rmtree(p["path"])
    for call in (lambda: store.get_project(p["project_id"]),
                 lambda: store.update_project(p["project_id"], name="x"),
                 lambda: store.set_ext(p["project_id"], "media", {})):
        with pytest.raises(KeyError):
            call()


def test_archive_final_can_keep_the_file_just_delivered(store):
    pid = store.create_project()["project_id"]
    folder = store.project_path(pid)
    old, new = folder / "final" / "demo_v1.mp4", folder / "final" / "demo_v2.mp4"
    old.write_bytes(b"x")
    new.write_bytes(b"y")
    moved = store.archive_final(pid, keep=new)
    assert [m.name.endswith("_demo_v1.mp4") for m in moved] == [True]
    assert list((folder / "final").iterdir()) == [new]
