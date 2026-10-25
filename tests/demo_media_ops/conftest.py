import os
from pathlib import Path

import pytest

import demo_media as dm
import demo_projects as dp
from tests.demo_media_ops.helpers import make_video


def _need_ffmpeg():
    try:
        dm.find_binaries()
    except dm.MediaError:
        if os.environ.get("GATOR_REQUIRE_FFMPEG") == "1":
            raise
        pytest.skip("ffmpeg and ffprobe are not installed")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "INDEX_PATH", tmp_path / "index.json")
    monkeypatch.setattr(dp, "DEFAULT_ROOT", tmp_path / "demos")
    cfg = {}
    monkeypatch.setattr(dp, "load_config", lambda: dict(cfg))
    monkeypatch.setattr(dp, "save_config", lambda d: cfg.update(d))
    return tmp_path


@pytest.fixture
def project(store):
    _need_ffmpeg()
    info = dp.create_project("Slack Demo")
    pid = info["project_id"]
    raw = make_video(Path(info["path"]) / "source" / "recording.mp4", 62.2)
    dp.update_project(pid, raw=str(raw), stage="recorded")
    return pid, Path(info["path"])
