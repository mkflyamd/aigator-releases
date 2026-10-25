from pathlib import Path

import pytest

import demo_clips as clips
import demo_compose as compose


class _Inline:
    def submit(self, fn, *args):
        fn(*args)


@pytest.fixture
def env(store, tmp_path, monkeypatch):
    calls = []

    def fake_run(argv):
        calls.append(list(argv))
        Path(argv[-1]).write_bytes(b"out")

    monkeypatch.setattr(compose, "_ffmpeg", lambda: "ff")
    monkeypatch.setattr(compose, "_run", fake_run)
    monkeypatch.setattr(compose, "_EXECUTOR", _Inline())
    pid = store.create_project(name="Demo")["project_id"]
    return store, pid, calls, tmp_path


def _add(pid, tmp_path, name, kind="video", duration=10.0):
    tmp = tmp_path / f"upload_{name}"
    tmp.write_bytes(b"x" * 10)
    probe = {"kind": kind, "duration": duration, "width": 1280, "height": 720, "has_audio": True}
    return clips.add_item(pid, tmp, name, probe)


def test_build_with_no_clips_resets_to_idle(env):
    store, pid, calls, tmp_path = env
    assert compose.build(pid) == "idle"
    assert clips.load(pid)["timeline"]["state"] == "idle"
    assert calls == []


def test_build_publishes_timeline_and_raw(env):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4", duration=10.0)
    _add(pid, tmp_path, "b.mp4", duration=20.0)
    assert compose.build(pid) == "ready"
    tl = clips.load(pid)["timeline"]
    assert tl["state"] == "ready" and tl["file"] == "work/timeline.mp4"
    assert tl["duration"] == 30.0 and tl["soundtrack"] is None and tl["error"] is None
    assert [c["id"] for c in tl["clips"]] == ["c1", "c2"]
    assert (tl["clips"][1]["start"], tl["clips"][1]["end"]) == (10.0, 30.0)
    assert tl["frame_times"] == [2.5, 7.5, 12.5, 17.5, 22.5, 27.5]
    project = store.get_project(pid)
    assert (Path(project["path"]) / "work" / "timeline.mp4").read_bytes() == b"out"
    assert project["raw"] == str(Path(project["path"]) / "work" / "timeline.mp4")
    assert project["stage"] == "recorded"
    assert calls[-1][:4] == ["ff", "-y", "-f", "concat"]
    assert sum(1 for argv in calls if "-ss" in argv) == 2


def test_build_keeps_a_later_stage(env):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    store.update_project(pid, stage="recording")
    compose.build(pid)
    assert store.get_project(pid)["stage"] == "recording"


def test_second_build_is_cached(env):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    compose.build(pid)
    count = len(calls)
    assert compose.build(pid) == "ready"
    assert len(calls) == count


def test_trim_change_rebuilds_and_removes_stale_normalized(env):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    compose.build(pid)
    norm = Path(store.get_project(pid)["path"]) / "work" / "normalized"
    before = {p.name for p in norm.iterdir()}
    clips.set_trim(pid, "c1", 1.0, 6.0)
    assert compose.build(pid) == "ready"
    after = {p.name for p in norm.iterdir()}
    assert len(after) == 1 and after != before
    assert clips.load(pid)["timeline"]["duration"] == 5.0


def test_audio_builds_soundtrack_and_removal_deletes_it(env):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    audio = _add(pid, tmp_path, "m.mp3", kind="audio", duration=40.0)
    compose.build(pid)
    folder = Path(store.get_project(pid)["path"])
    assert clips.load(pid)["timeline"]["soundtrack"] == "work/soundtrack.m4a"
    assert (folder / "work" / "soundtrack.m4a").exists()
    clips.remove_item(pid, audio["id"])
    compose.build(pid)
    assert clips.load(pid)["timeline"]["soundtrack"] is None
    assert not (folder / "work" / "soundtrack.m4a").exists()


def test_failure_records_error_and_is_not_retried_until_inputs_change(env, monkeypatch):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")

    def boom(argv):
        raise compose.ComposeError("Invalid data found")

    monkeypatch.setattr(compose, "_run", boom)
    assert compose.build(pid) == "failed"
    tl = clips.load(pid)["timeline"]
    assert tl["state"] == "failed" and "Invalid data" in tl["error"]

    scheduled = []
    monkeypatch.setattr(compose, "schedule", scheduled.append)
    compose.ensure_current(pid)
    assert scheduled == []
    clips.set_trim(pid, "c1", 0.0, 5.0)
    compose.ensure_current(pid)
    assert scheduled == [pid]


def test_missing_ffmpeg_fails_the_build(env, monkeypatch):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    monkeypatch.setattr(compose, "_ffmpeg", lambda: None)
    assert compose.build(pid) == "failed"
    assert "ffmpeg" in clips.load(pid)["timeline"]["error"].lower()


def test_edit_during_build_is_superseded_then_rebuilt(env, monkeypatch):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    fired = []

    def edit_midway(argv):
        calls.append(list(argv))
        Path(argv[-1]).write_bytes(b"out")
        if not fired:
            fired.append(True)
            clips.set_trim(pid, "c1", 0.0, 4.0)

    monkeypatch.setattr(compose, "_run", edit_midway)
    assert compose.build(pid) == "superseded"
    assert clips.load(pid)["timeline"]["state"] == "building"

    compose.schedule(pid)
    tl = clips.load(pid)["timeline"]
    assert tl["state"] == "ready" and tl["duration"] == 4.0


def test_schedule_while_inflight_only_marks_dirty(env, monkeypatch):
    store, pid, calls, tmp_path = env
    submitted = []
    monkeypatch.setattr(compose, "_EXECUTOR", type("E", (), {"submit": lambda self, fn, *a: submitted.append(a)})())
    compose._inflight.add(pid)
    try:
        compose.schedule(pid)
        assert submitted == [] and pid in compose._dirty
    finally:
        compose._inflight.discard(pid)
        compose._dirty.discard(pid)


def test_ensure_current_schedules_a_stuck_building_state(env, monkeypatch):
    store, pid, calls, tmp_path = env
    _add(pid, tmp_path, "a.mp4")
    clips.set_timeline(pid, state="building")
    scheduled = []
    monkeypatch.setattr(compose, "schedule", scheduled.append)
    compose.ensure_current(pid)
    assert scheduled == [pid]
