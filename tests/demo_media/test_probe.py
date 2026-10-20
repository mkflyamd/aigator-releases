import types
from pathlib import Path

import pytest

import demo_media_probe as probe


def test_extension_kind():
    assert probe.extension_kind("Demo.MP4") == "video"
    assert probe.extension_kind("a.flac") == "audio"
    assert probe.extension_kind("a.exe") is None
    assert probe.extension_kind("noext") is None


def test_video_accepted(fake_ffprobe):
    fake_ffprobe(duration=12.5)
    assert probe.probe_media("clip.mp4") == {
        "kind": "video", "duration": 12.5, "width": 1920, "height": 1080,
        "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
    }


def test_video_without_audio(fake_ffprobe):
    fake_ffprobe(has_audio=False)
    info = probe.probe_media("clip.mp4")
    assert info["has_audio"] is False and info["audio_codec"] is None


@pytest.mark.parametrize("kwargs,name,code", [
    ({}, "x.exe", "unsupported_type"),
    ({"kind": "audio"}, "x.mp4", "no_video_stream"),
    ({"kind": "audio", "attached_pic": True}, "x.mp4", "no_video_stream"),
    ({"vcodec": "prores"}, "x.mov", "codec_unsupported"),
    ({"duration": 0}, "x.mp4", "zero_duration"),
    ({"duration": 1801}, "x.mp4", "too_long"),
    ({"width": 7681}, "x.mp4", "too_big_dimensions"),
    ({"height": 7681}, "x.mp4", "too_big_dimensions"),
])
def test_video_rejections(fake_ffprobe, kwargs, name, code):
    fake_ffprobe(**kwargs)
    with pytest.raises(probe.MediaRejected) as exc:
        probe.probe_media(name)
    assert exc.value.code == code


def test_video_audio_codec_is_not_checked(fake_ffprobe):
    fake_ffprobe(acodec="wmav2")
    assert probe.probe_media("clip.mp4")["kind"] == "video"


def test_audio_accepted(fake_ffprobe):
    fake_ffprobe(kind="audio", duration=95.0, acodec="mp3")
    info = probe.probe_media("bed.mp3")
    assert info == {"kind": "audio", "duration": 95.0, "width": None, "height": None,
                    "has_audio": True, "video_codec": None, "audio_codec": "mp3"}


def test_audio_with_cover_art_accepted(fake_ffprobe):
    fake_ffprobe(kind="audio", attached_pic=True)
    assert probe.probe_media("bed.m4a")["kind"] == "audio"


def test_audio_rejections(fake_ffprobe):
    fake_ffprobe(kind="video", has_audio=False)
    with pytest.raises(probe.MediaRejected) as exc:
        probe.probe_media("bed.mp3")
    assert exc.value.code == "no_audio_stream"
    fake_ffprobe(kind="audio", acodec="wmav2")
    with pytest.raises(probe.MediaRejected) as exc:
        probe.probe_media("bed.mp3")
    assert exc.value.code == "codec_unsupported"


def test_name_overrides_path_for_extension(fake_ffprobe):
    fake_ffprobe()
    assert probe.probe_media(Path("x.part"), name="clip.mp4")["kind"] == "video"


def test_run_ffprobe_nonzero_is_unreadable(monkeypatch):
    monkeypatch.setattr(probe, "ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(probe.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="bad"))
    with pytest.raises(probe.MediaRejected) as exc:
        probe._run_ffprobe(Path("x.mp4"))
    assert exc.value.code == "unreadable"


def test_run_ffprobe_bad_json_is_unreadable(monkeypatch):
    monkeypatch.setattr(probe, "ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(probe.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="not json", stderr=""))
    with pytest.raises(probe.MediaRejected) as exc:
        probe._run_ffprobe(Path("x.mp4"))
    assert exc.value.code == "unreadable"


def test_run_ffprobe_missing_tool(monkeypatch):
    monkeypatch.setattr(probe, "ffprobe_path", lambda: None)
    with pytest.raises(probe.MediaRejected) as exc:
        probe._run_ffprobe(Path("x.mp4"))
    assert exc.value.code == "tools_missing"
