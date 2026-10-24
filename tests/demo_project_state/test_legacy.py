import json


def _legacy(root, pid="demo_20260101_101010"):
    d = root / pid
    d.mkdir(parents=True)
    (d / "seg_00.mp4").write_bytes(b"a")
    (d / "seg_01.mp4").write_bytes(b"b")
    (d / "ffmpeg_log.txt").write_text("log", encoding="utf-8")
    (d / f"{pid}_final.mp4").write_bytes(b"stitched")
    (d / "notes.txt").write_text("keep", encoding="utf-8")
    return d


def test_adopt_moves_files_into_layout(store, tmp_path):
    d = _legacy(tmp_path / "demos")
    p = store.adopt_legacy_folder(d)
    assert (d / "source" / "seg_00.mp4").read_bytes() == b"a"
    assert (d / "source" / "seg_01.mp4").read_bytes() == b"b"
    assert (d / "work" / "logs" / "ffmpeg_log.txt").read_text(encoding="utf-8") == "log"
    assert (d / "source" / "recording.mp4").read_bytes() == b"stitched"
    assert (d / "notes.txt").exists()
    assert not (d / "seg_00.mp4").exists()
    data = json.loads((d / "project.json").read_text(encoding="utf-8"))
    assert data["segments"] == ["source/seg_00.mp4", "source/seg_01.mp4"]
    assert data["raw"] == "source/recording.mp4" and data["stage"] == "recorded"
    assert p["project_id"] == "demo_20260101_101010"


def test_adopt_is_idempotent(store, tmp_path):
    d = _legacy(tmp_path / "demos")
    store.adopt_legacy_folder(d)
    before = (d / "project.json").read_text(encoding="utf-8")
    store.adopt_legacy_folder(d)
    assert (d / "project.json").read_text(encoding="utf-8") == before


def test_list_adopts_legacy_and_orders_recent_first(store, tmp_path):
    _legacy(tmp_path / "demos", "demo_20260101_101010")
    new = store.create_project()
    ids = [p["project_id"] for p in store.list_projects()]
    assert set(ids) == {"demo_20260101_101010", new["project_id"]}
    assert ids[0] == new["project_id"]


def test_list_drops_entries_for_missing_folders(store, tmp_path):
    p = store.create_project()
    import shutil
    shutil.rmtree(store.project_path(p["project_id"]))
    assert store.list_projects() == []


def test_list_ignores_non_demo_folders(store, tmp_path):
    (tmp_path / "demos" / "random").mkdir(parents=True)
    assert store.list_projects() == []
