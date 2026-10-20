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
    return TestClient(app)


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
