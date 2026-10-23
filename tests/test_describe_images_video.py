import types
from pathlib import Path

import pytest

from routes import recorder as rec
from skills._always_on import tools as ao

HANDLER = ao.TOOL_HANDLERS["describe_images"]


async def test_analyze_sequence_rejects_more_than_eight_frames():
    paths = [f"/tmp/code_runner_out/frames/frame_{i:04d}.png" for i in range(42)]
    r = await HANDLER(task="analyze_sequence", image_paths=paths)

    assert r["ok"] is False
    assert "at most 8" in r["error"] and "analyze_video" in r["error"]
    assert "do not exist" not in r["error"]


async def test_analyze_sequence_with_eight_missing_frames_still_reports_missing():
    paths = [f"/tmp/code_runner_out/frames/frame_{i:04d}.png" for i in range(8)]
    r = await HANDLER(task="analyze_sequence", image_paths=paths)

    assert r["ok"] is False
    assert "do not exist" in r["error"]


@pytest.fixture
def media(monkeypatch, tmp_path):
    video = tmp_path / "demo_final.mp4"
    video.write_bytes(b"video")
    state = types.SimpleNamespace(video=video, duration="210.0\n", calls=[], analyzed=[], frame_dirs=[],
                                  frame_returncode=0)

    def fake_run(cmd, **kwargs):
        state.calls.append((list(cmd), kwargs))
        if "ffprobe" in str(cmd[0]):
            return types.SimpleNamespace(returncode=0, stdout=state.duration, stderr="")
        if state.frame_returncode == 0:
            Path(cmd[-1]).write_bytes(b"png")
        return types.SimpleNamespace(returncode=state.frame_returncode, stdout="", stderr="decode error")

    async def fake_analyze(paths, fps):
        state.analyzed.append((list(paths), fps))
        state.frame_dirs.append(Path(paths[0]).parent)
        return {"ok": True, "task": "analyze_sequence", "timeline": []}

    monkeypatch.setattr(rec, "_FFMPEG", "ffmpeg-aigator")
    monkeypatch.setattr(rec, "_FFPROBE", "ffprobe-aigator")
    monkeypatch.setattr(ao.subprocess, "run", fake_run)
    monkeypatch.setattr(ao, "_analyze_frame_sequence", fake_analyze)
    return state


async def test_analyze_video_extracts_eight_evenly_spaced_frames(media):
    r = await HANDLER(task="analyze_video", video_path=str(media.video))

    assert r["ok"] is True
    paths, fps = media.analyzed[0]
    assert len(paths) == 8
    assert fps == pytest.approx(1 / 26.25)

    probe = media.calls[0][0]
    assert probe[0] == "ffprobe-aigator" and probe[-1] == str(media.video)
    frame_cmds = [c for c, _ in media.calls[1:]]
    assert [c[c.index("-ss") + 1] for c in frame_cmds] == [f"{i * 26.25:.3f}" for i in range(8)]
    for cmd, kwargs in media.calls:
        assert isinstance(cmd, list) and not kwargs.get("shell")
    assert not media.frame_dirs[0].exists(), "temporary frames are removed"


async def test_analyze_video_short_clip_uses_one_frame_per_five_seconds(media):
    media.duration = "12.0\n"
    await HANDLER(task="analyze_video", video_path=str(media.video))

    frame_cmds = [c for c, _ in media.calls[1:]]
    assert [c[c.index("-ss") + 1] for c in frame_cmds] == ["0.000", "4.000", "8.000"]


async def test_analyze_video_requires_video_path():
    r = await HANDLER(task="analyze_video")
    assert r["ok"] is False and "video_path" in r["error"]


async def test_analyze_video_reports_missing_file(media, tmp_path):
    r = await HANDLER(task="analyze_video", video_path=str(tmp_path / "nope.mp4"))
    assert r["ok"] is False and "not found" in r["error"].lower()
    assert media.calls == []


async def test_analyze_video_reports_missing_ffmpeg(media, monkeypatch):
    monkeypatch.setattr(rec, "_FFMPEG", None)
    monkeypatch.setattr(rec, "_FFPROBE", None)
    monkeypatch.setattr(rec, "_find_ffmpeg", lambda: None)
    monkeypatch.setattr(rec, "_find_ffprobe", lambda: None)
    r = await HANDLER(task="analyze_video", video_path=str(media.video))

    assert r["ok"] is False and "ffmpeg" in r["error"]
    assert media.calls == []


async def test_analyze_video_reports_frame_extraction_failure_and_cleans_up(media):
    media.frame_returncode = 1
    r = await HANDLER(task="analyze_video", video_path=str(media.video))

    assert r["ok"] is False and "could not extract a frame" in r["error"]
    assert media.analyzed == []


async def test_analyze_video_refuses_secrets_path(media, monkeypatch):
    import sandbox.paths as sp
    monkeypatch.setattr(sp, "is_secrets_path", lambda p: True)
    r = await HANDLER(task="analyze_video", video_path=str(media.video))

    assert r == {"ok": False, "error": sp.PROTECTED_MSG}
    assert media.calls == []
