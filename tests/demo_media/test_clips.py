import pytest

import demo_clips as clips


def _probe(kind="video", duration=10.0):
    video = kind == "video"
    return {"kind": kind, "duration": duration, "width": 1920 if video else None,
            "height": 1080 if video else None, "has_audio": True,
            "video_codec": "h264" if video else None, "audio_codec": "aac"}


@pytest.fixture
def pid(store):
    return store.create_project()["project_id"]


def _add(store, pid, name, kind="video", duration=10.0):
    part = store.project_path(pid) / "source" / f".upload_{name}.part"
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"data-" + name.encode())
    return clips.add_item(pid, part, name, _probe(kind, duration))


def test_load_blank_registry(pid):
    reg = clips.load(pid)
    assert reg["clips"] == [] and reg["audio"] == []
    assert reg["timeline"]["state"] == "idle"


def test_add_video_and_audio(store, pid):
    c = _add(store, pid, "intro.mp4")
    a = _add(store, pid, "bed.mp3", kind="audio", duration=95.0)
    assert c["id"] == "c1" and c["file"] == "source/c1_intro.mp4"
    assert c["trim_start"] == 0.0 and c["trim_end"] is None and c["width"] == 1920
    assert a["id"] == "a2" and a["file"] == "source/a2_bed.mp3" and "trim_start" not in a
    assert clips.abs_path(pid, c["file"]).is_file()
    stored = store.get_project(pid)["ext"]["clips"]
    assert [x["id"] for x in stored["clips"]] == ["c1"] and [x["id"] for x in stored["audio"]] == ["a2"]


def test_safe_name_strips_unsafe_characters():
    assert clips.safe_name("my demo (v2).mp4") == "my_demo_v2_.mp4"
    assert clips.safe_name("../../evil.mp4") == "evil.mp4"
    assert len(clips.safe_name("a" * 200 + ".mp4")) == 80


def test_clip_limit(store, pid):
    for i in range(8):
        _add(store, pid, f"c{i}.mp4")
    with pytest.raises(clips.ClipError) as exc:
        _add(store, pid, "ninth.mp4")
    assert exc.value.code == "too_many"


def test_audio_limit(store, pid):
    for i in range(4):
        _add(store, pid, f"a{i}.mp3", kind="audio")
    with pytest.raises(clips.ClipError) as exc:
        _add(store, pid, "fifth.mp3", kind="audio")
    assert exc.value.code == "too_many"


def test_ids_are_not_reused(store, pid):
    _add(store, pid, "a.mp4")
    clips.remove_item(pid, "c1")
    assert _add(store, pid, "b.mp4")["id"] == "c2"


def test_remove_deletes_file_and_entry(store, pid):
    c = _add(store, pid, "a.mp4")
    path = clips.abs_path(pid, c["file"])
    clips.remove_item(pid, "c1")
    assert not path.exists() and clips.load(pid)["clips"] == []
    with pytest.raises(clips.ClipError) as exc:
        clips.remove_item(pid, "c1")
    assert exc.value.code == "not_found"


def test_reorder(store, pid):
    _add(store, pid, "a.mp4")
    _add(store, pid, "b.mp4")
    clips.reorder(pid, ["c2", "c1"])
    assert [c["id"] for c in clips.load(pid)["clips"]] == ["c2", "c1"]


@pytest.mark.parametrize("ids", [["c1"], ["c1", "c1"], ["c1", "c3"], ["c1", "c2", "c3"]])
def test_reorder_rejects_non_permutation(store, pid, ids):
    _add(store, pid, "a.mp4")
    _add(store, pid, "b.mp4")
    with pytest.raises(clips.ClipError) as exc:
        clips.reorder(pid, ids)
    assert exc.value.code == "bad_order"


def test_set_trim(store, pid):
    _add(store, pid, "a.mp4", duration=10.0)
    clips.set_trim(pid, "c1", 1.0, 9.5)
    c = clips.load(pid)["clips"][0]
    assert (c["trim_start"], c["trim_end"]) == (1.0, 9.5)
    assert clips.effective_duration(c) == 8.5
    clips.set_trim(pid, "c1", 2.0, None)
    c = clips.load(pid)["clips"][0]
    assert c["trim_end"] is None and clips.effective_duration(c) == 8.0


@pytest.mark.parametrize("start,end", [(-1, None), (5, 4), (0, 11), (0, 0.2), (9.9, None)])
def test_set_trim_rejects_bad_ranges(store, pid, start, end):
    _add(store, pid, "a.mp4", duration=10.0)
    with pytest.raises(clips.ClipError) as exc:
        clips.set_trim(pid, "c1", start, end)
    assert exc.value.code == "bad_trim"


def test_set_trim_unknown_clip(store, pid):
    with pytest.raises(clips.ClipError) as exc:
        clips.set_trim(pid, "c9", 0, None)
    assert exc.value.code == "not_found"


def test_locked_stage_blocks_mutations(store, pid):
    _add(store, pid, "a.mp4")
    store.update_project(pid, stage="narration_approved")
    for call in (
        lambda: _add(store, pid, "b.mp4"),
        lambda: clips.remove_item(pid, "c1"),
        lambda: clips.reorder(pid, ["c1"]),
        lambda: clips.set_trim(pid, "c1", 0, None),
    ):
        with pytest.raises(clips.ClipError) as exc:
            call()
        assert exc.value.code == "project_locked"


def test_set_timeline_works_when_locked(store, pid):
    _add(store, pid, "a.mp4")
    store.update_project(pid, stage="delivered")
    clips.set_timeline(pid, state="ready")
    assert clips.load(pid)["timeline"]["state"] == "ready"


def test_fingerprint_tracks_order_trim_and_audio(store, pid):
    _add(store, pid, "a.mp4")
    _add(store, pid, "b.mp4")
    base = clips.fingerprint(pid, clips.load(pid))
    assert base == clips.fingerprint(pid, clips.load(pid))
    clips.reorder(pid, ["c2", "c1"])
    swapped = clips.fingerprint(pid, clips.load(pid))
    assert swapped != base
    clips.set_trim(pid, "c1", 1.0, None)
    trimmed = clips.fingerprint(pid, clips.load(pid))
    assert trimmed != swapped
    _add(store, pid, "bed.mp3", kind="audio")
    assert clips.fingerprint(pid, clips.load(pid)) != trimmed


def test_frame_times_examples():
    assert clips.frame_times([10, 20]) == [2.5, 7.5, 12.5, 17.5, 22.5, 27.5]
    assert clips.frame_times([3.0]) == [1.5]
    assert clips.frame_times([]) == []
    long = clips.frame_times([100])
    assert len(long) == 8 and long[-1] == 93.75
