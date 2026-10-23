import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "web" / "skills" / "gator-demo-recorder" / "scripts" / "tts_pipeline.py"
MIX = "[2:a]volume=0.25[bg];[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]"


def _load():
    spec = importlib.util.spec_from_file_location("tts_pipeline_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_merge_argv_without_soundtrack_maps_narration_explicitly():
    mod = _load()
    assert mod.build_merge_argv("ff", "v.mp4", "n.mp3", "out.mp4") == [
        "ff", "-y", "-i", "v.mp4", "-i", "n.mp3", "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", "out.mp4"]


def test_merge_argv_with_soundtrack_mixes_under_narration():
    mod = _load()
    assert mod.build_merge_argv("ff", "v.mp4", "n.mp3", "out.mp4", soundtrack="s.m4a") == [
        "ff", "-y", "-i", "v.mp4", "-i", "n.mp3", "-i", "s.m4a", "-filter_complex", MIX,
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", "out.mp4"]


def _patched(mod, monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(list(argv))
        Path(argv[-1]).write_bytes(b"x")

    monkeypatch.setattr(mod, "get_ffmpeg_path", lambda: "ff")
    monkeypatch.setattr(mod, "get_duration", lambda path: 10.0)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return seen


def test_merge_audio_video_passes_soundtrack(tmp_path, monkeypatch):
    mod = _load()
    seen = _patched(mod, monkeypatch)
    mod.merge_audio_video("v.mp4", "n.mp3", tmp_path / "out.mp4", soundtrack="s.m4a")
    assert seen[-1][seen[-1].index("-filter_complex") + 1] == MIX
    seen.clear()
    mod.merge_audio_video("v.mp4", "n.mp3", tmp_path / "out2.mp4")
    assert "-filter_complex" not in seen[-1] and "1:a:0" in seen[-1]


def test_cli_soundtrack_flag_reaches_merge(tmp_path, monkeypatch):
    mod = _load()
    (tmp_path / "t.json").write_text("[]", encoding="utf-8")
    (tmp_path / "n.json").write_text(json.dumps([]), encoding="utf-8")
    got = {}
    monkeypatch.setattr(mod, "build_synced_audio", lambda *a, **k: tmp_path / "a.mp3")
    monkeypatch.setattr(mod, "merge_audio_video", lambda video, audio, out, soundtrack=None: got.update(soundtrack=soundtrack))
    base = ["tts_pipeline.py", "--video", str(tmp_path / "v.mp4"), "--timeline", str(tmp_path / "t.json"),
            "--narration", str(tmp_path / "n.json"), "--output", str(tmp_path / "o.mp4")]
    monkeypatch.setattr(sys, "argv", base + ["--soundtrack", "s.m4a"])
    mod.main()
    assert got["soundtrack"] == "s.m4a"
    monkeypatch.setattr(sys, "argv", base)
    mod.main()
    assert got["soundtrack"] is None
