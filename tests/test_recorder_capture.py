import os
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import demo_projects as dp
from routes import recorder as rec


def test_is_windows_constant_matches_platform():
    assert rec._IS_WINDOWS == (os.name == "nt")


SCREENS = [
    {"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080, "label": "Display 1", "primary": True},
    {"index": 1, "x": 1920, "y": 0, "width": 2560, "height": 1440, "label": "Display 2", "primary": False},
]
CROP = {"screen_index": 1, "crop_x": 100, "crop_y": 50, "crop_w": 640, "crop_h": 480}


class FakeProc:
    _next_pid = 4000

    def __init__(self, exit_code=None):
        FakeProc._next_pid += 1
        self.pid = FakeProc._next_pid
        self.exit_code = exit_code
        self.signals = []

    def poll(self):
        return self.exit_code

    def send_signal(self, sig):
        self.signals.append(sig)

    def terminate(self):
        self.exit_code = 0

    def kill(self):
        self.exit_code = -9

    def wait(self, timeout=None):
        if self.exit_code is None:
            self.exit_code = 0
        return self.exit_code


@pytest.fixture
def env(monkeypatch, tmp_path):
    e = types.SimpleNamespace(
        argvs=[], runs=[], borders=[], border_stops=[],
        fail_next_start=False, segment_bytes=b"segment-bytes",
        concat_returncode=0, concat_stderr="",
    )

    def fake_popen(cmd, **kwargs):
        e.argvs.append(list(cmd))
        if e.fail_next_start:
            e.fail_next_start = False
            return FakeProc(exit_code=1)
        Path(cmd[-1]).write_bytes(e.segment_bytes)
        return FakeProc()

    def fake_run(cmd, **kwargs):
        e.runs.append(list(cmd))
        if e.concat_returncode == 0:
            Path(cmd[-1]).write_bytes(b"joined-bytes")
        return types.SimpleNamespace(returncode=e.concat_returncode, stdout="", stderr=e.concat_stderr)

    cfg: dict = {}
    monkeypatch.setattr(dp, "INDEX_PATH", tmp_path / "gator" / "demo_projects.json")
    monkeypatch.setattr(dp, "DEFAULT_ROOT", tmp_path / "demos")
    monkeypatch.setattr(dp, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(dp, "save_config", lambda d: (cfg.clear(), cfg.update(d)))
    monkeypatch.setattr(rec, "_FFMPEG", "ffmpeg")
    monkeypatch.setattr(rec, "_IS_WINDOWS", True)
    monkeypatch.setattr(rec, "_list_screens_windows", lambda: SCREENS)
    monkeypatch.setattr(rec, "_list_screens_mac", lambda: SCREENS)
    monkeypatch.setattr(rec.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rec.subprocess, "run", fake_run)
    monkeypatch.setattr(rec.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(rec.signal, "CTRL_BREAK_EVENT", 1, raising=False)
    monkeypatch.setattr(rec.signal, "SIGSTOP", 19, raising=False)
    monkeypatch.setattr(rec.signal, "SIGCONT", 18, raising=False)
    monkeypatch.setattr(rec, "_start_recording_border",
                        lambda screen, crop: e.borders.append((screen["label"], crop)))
    monkeypatch.setattr(rec, "_stop_recording_border", lambda: e.border_stops.append(1))
    for name, value in {
        "_ffmpeg_proc": None, "_recording_path": None, "_recording_start": None,
        "_paused_at": None, "_paused_elapsed": 0.0, "_segments": [],
        "_session_dir": None, "_session_tag": None,
        "_last_screen_index": 0, "_last_crop": None,
        "_last_start_req": rec.StartRequest(),
    }.items():
        monkeypatch.setattr(rec, name, value, raising=False)
    return e


@pytest.fixture
def client(env):
    app = FastAPI()
    app.include_router(rec.router)
    from security import get_csrf_token

    return TestClient(app, headers={"X-CSRF-Token": get_csrf_token("testserver")})


def _start(client, **overrides):
    r = client.post("/api/recorder/start", json={**CROP, **overrides})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    return r.json()


def _flag(argv, name):
    return argv[argv.index(name) + 1]


def test_resume_restarts_on_selected_screen_and_crop(client, env):
    _start(client)
    assert client.post("/api/recorder/pause").json()["ok"] is True
    assert client.post("/api/recorder/resume").json()["ok"] is True

    first, resumed = env.argvs
    for argv in (first, resumed):
        assert _flag(argv, "-offset_x") == "2020"
        assert _flag(argv, "-offset_y") == "50"
        assert _flag(argv, "-video_size") == "640x480"
    assert resumed[-1].endswith("seg_01.mp4")


@pytest.mark.parametrize("is_windows", [True, False])
def test_resume_restores_border_on_selected_screen(client, env, monkeypatch, is_windows):
    monkeypatch.setattr(rec, "_IS_WINDOWS", is_windows)
    _start(client)
    assert client.post("/api/recorder/pause").json()["ok"] is True
    assert client.post("/api/recorder/resume").json()["ok"] is True

    expected = ("Display 2", {"x": 100, "y": 50, "w": 640, "h": 480})
    assert env.borders == [expected, expected]


def test_resume_uses_the_clamped_request(client, env):
    _start(client, crop_w=5000, crop_h=5000)
    assert client.post("/api/recorder/pause").json()["ok"] is True
    assert client.post("/api/recorder/resume").json()["ok"] is True

    first, resumed = env.argvs
    assert _flag(first, "-video_size") == "2460x1390"
    assert _flag(resumed, "-video_size") == "2460x1390"


def _pause_resume(client):
    assert client.post("/api/recorder/pause").json()["ok"] is True
    assert client.post("/api/recorder/resume").json()["ok"] is True


def test_stop_joins_segments_with_concat_and_cleans_up(client, env):
    started = _start(client)
    _pause_resume(client)
    r = client.post("/api/recorder/stop")
    body = r.json()

    assert r.status_code == 200 and body["ok"] is True and body["segments"] == 2
    argv = env.runs[0]
    assert argv[:6] == ["ffmpeg", "-y", "-f", "concat", "-safe", "0"]
    assert argv[-3:-1] == ["-c", "copy"] and argv[-1] == body["path"]
    assert body["size_bytes"] == len(b"joined-bytes")
    assert not (Path(body["path"]).parent / "concat_list.txt").exists()
    project = dp.get_project(started["project_id"])
    assert project["stage"] == "recorded" and project["raw"] == body["path"]


def test_stopping_a_new_recording_drops_the_edit_of_the_old_one(client, env):
    started = _start(client)
    pid = started["project_id"]
    assert client.post("/api/recorder/stop").json()["ok"] is True
    dp.set_ext(pid, "media", {"current": "work/edit_1.mp4", "current_base": "source/recording.mp4", "ops": [{"op_id": "a"}]})
    _start(client, project_id=pid)
    assert client.post("/api/recorder/stop").json()["ok"] is True
    media = dp.get_project(pid)["ext"]["media"]
    assert "current" not in media and "current_base" not in media
    assert media["ops"] == [{"op_id": "a"}]


def test_stop_with_one_segment_needs_no_ffmpeg_run(client, env):
    _start(client)
    body = client.post("/api/recorder/stop").json()

    assert body["ok"] is True and body["size_bytes"] == len(b"segment-bytes")
    assert env.runs == []


def test_stop_reports_concat_failure_and_writes_nothing(client, env):
    started = _start(client)
    _pause_resume(client)
    env.concat_returncode = 1
    env.concat_stderr = "Invalid data found when processing input"
    r = client.post("/api/recorder/stop")
    body = r.json()

    assert r.status_code == 500 and body["ok"] is False and body["status"] == "idle"
    assert "Invalid data found" in body["error"]
    assert len(body["segments"]) == 2
    assert body["session_dir"] == str(rec._session_dir)
    project = dp.get_project(started["project_id"])
    assert project["stage"] == "recording" and project["raw"] is None
    assert rec._paused_at is None and env.border_stops
    assert not (rec._session_dir / "source" / "concat_list.txt").exists()


def test_stop_with_no_captured_video_is_an_error(client, env):
    env.segment_bytes = b""
    started = _start(client)
    r = client.post("/api/recorder/stop")

    assert r.status_code == 500
    assert "No video was captured" in r.json()["error"]
    assert dp.get_project(started["project_id"])["raw"] is None


def test_failed_restart_stays_paused_and_can_be_retried(client, env):
    _start(client)
    assert client.post("/api/recorder/pause").json()["ok"] is True

    env.fail_next_start = True
    r = client.post("/api/recorder/resume")
    body = r.json()
    assert r.status_code == 500 and body["ok"] is False
    assert "ffmpeg_log.txt" in body["error"] and body["log"].endswith("ffmpeg_log.txt")
    assert len(rec._segments) == 1
    assert rec._paused_at is not None
    assert rec._ffmpeg_proc is None

    retry = client.post("/api/recorder/resume")
    assert retry.json()["ok"] is True
    assert len(rec._segments) == 2
    assert env.argvs[-1][-1].endswith("seg_01.mp4")


SCALED = [
    {"index": 0, "x": 0, "y": 0, "width": 1280, "height": 800, "primary": True,
     "capture": {"x": 0, "y": 0, "width": 1920, "height": 1200}, "label": "Display 1 (1920x1200)"},
    {"index": 1, "x": 1920, "y": 0, "width": 1600, "height": 900, "primary": False,
     "capture": {"x": 2880, "y": 0, "width": 2400, "height": 1350}, "label": "Display 2 (2400x1350)"},
]


def _gdigrab_argv(screens, **req):
    return rec._build_ffmpeg_cmd("ffmpeg", Path("out.mp4"), rec.StartRequest(**req), screens)


def test_full_screen_capture_uses_the_physical_size_not_the_logical_one(monkeypatch):
    monkeypatch.setattr(rec, "_IS_WINDOWS", True)
    argv = _gdigrab_argv(SCALED, screen_index=0)
    assert _flag(argv, "-video_size") == "1920x1200"
    assert (_flag(argv, "-offset_x"), _flag(argv, "-offset_y")) == ("0", "0")


def test_crop_is_scaled_to_physical_pixels_on_the_selected_monitor(monkeypatch):
    monkeypatch.setattr(rec, "_IS_WINDOWS", True)
    argv = _gdigrab_argv(SCALED, screen_index=1, crop_x=100, crop_y=50, crop_w=800, crop_h=450)
    assert (_flag(argv, "-offset_x"), _flag(argv, "-offset_y")) == ("3030", "75")
    assert _flag(argv, "-video_size") == "1200x674"


def test_capture_size_is_always_even_for_yuv420p(monkeypatch):
    monkeypatch.setattr(rec, "_IS_WINDOWS", True)
    argv = _gdigrab_argv(SCALED, screen_index=0, crop_x=0, crop_y=0, crop_w=333, crop_h=201)
    w, h = (int(v) for v in _flag(argv, "-video_size").split("x"))
    assert w % 2 == 0 and h % 2 == 0


def test_screens_without_a_capture_rect_are_used_as_is(monkeypatch):
    monkeypatch.setattr(rec, "_IS_WINDOWS", True)
    argv = _gdigrab_argv(SCREENS, screen_index=1, crop_x=100, crop_y=50, crop_w=640, crop_h=480)
    assert (_flag(argv, "-offset_x"), _flag(argv, "-offset_y"), _flag(argv, "-video_size")) == ("2020", "50", "640x480")


def test_border_sits_on_the_selected_display_for_a_screen_relative_crop():
    left = {"x": -1920, "y": 0, "width": 1920, "height": 1080}
    crop = {"x": 300, "y": 120, "w": 640, "h": 480}
    assert rec._border_rect(left, crop) == (-1620, 120, 640, 480)
    assert rec._border_rect(left, None) == (-1920, 0, 1920, 1080)
    primary = {"x": 0, "y": 0, "width": 1280, "height": 800}
    assert rec._border_rect(primary, crop) == (300, 120, 640, 480)


def test_widget_sends_the_screen_relative_crop_the_picker_returns():
    skill = (Path(__file__).parent.parent / "web" / "skills" / "gator-demo-recorder" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "_crop = {x:data.screen_x, y:data.screen_y, w:data.w, h:data.h};" in skill
    assert "gator:recorder-waiting" in skill and "Waiting for you to click Allow above" in skill


def test_start_that_dies_at_once_leaves_no_dead_segment(client, env):
    env.fail_next_start = True
    r = client.post("/api/recorder/start", json=CROP)
    body = r.json()
    assert r.status_code == 500 and body["ok"] is False
    assert rec._segments == [] and rec._ffmpeg_proc is None and rec._recording_start is None
    project = dp.get_project(rec._session_tag)
    assert project["stage"] == "created" and project["segments"] == []

    retry = _start(client, project_id=rec._session_tag)
    assert retry["ok"] is True and env.argvs[-1][-1].endswith("seg_00.mp4")


def test_stitch_list_escapes_a_quote_in_a_segment_path(env, tmp_path, monkeypatch):
    listed = {}

    def read_list(cmd, **kwargs):
        listed["text"] = Path(cmd[cmd.index("-i") + 1]).read_text(encoding="utf-8")
        Path(cmd[-1]).write_bytes(b"joined")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rec.subprocess, "run", read_list)
    segs = [tmp_path / "it's a demo" / "seg_00.mp4", tmp_path / "plain" / "seg_01.mp4"]
    rec._stitch_segments("ffmpeg", segs, tmp_path / "out.mp4")
    assert f"file '{str(segs[0]).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" in listed["text"]
    assert f"file '{segs[1]}'" in listed["text"]


def test_serve_file_serves_a_project_file_without_reading_every_project(client, env, monkeypatch):
    started = _start(client)
    monkeypatch.setattr(dp, "list_projects", lambda: pytest.fail("serve-file must not re-read every project"))
    inside = Path(started["session_dir"]) / "source" / "seg_00.mp4"
    assert client.get("/api/recorder/serve-file", params={"path": str(inside)}).status_code == 200
    outside = Path(started["session_dir"]).parent.parent / "elsewhere.mp4"
    outside.write_bytes(b"x")
    assert client.get("/api/recorder/serve-file", params={"path": str(outside)}).status_code == 403


@pytest.mark.parametrize("action", ["select-screen", "pick-region", "start", "pause", "resume", "stop"])
def test_capture_controls_reject_a_caller_without_the_csrf_token(env, action):
    app = FastAPI()
    app.include_router(rec.router)
    bare = TestClient(app)
    assert bare.post(f"/api/recorder/{action}", json={}).status_code == 403
