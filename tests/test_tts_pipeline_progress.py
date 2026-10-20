import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "web" / "skills" / "gator-demo-recorder" / "scripts" / "tts_pipeline.py"
)
APPROVAL = "appr_1_abcd1234"


def _load():
    spec = importlib.util.spec_from_file_location("tts_pipeline_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def pipe(monkeypatch, tmp_path):
    mod = _load()

    def fake_tts(text, out_path, *a, **k):
        Path(out_path).write_bytes(b"x")
        return 1

    monkeypatch.setattr(mod, "get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(mod, "generate_tts", fake_tts)
    monkeypatch.setattr(mod, "get_duration", lambda *a, **k: 2.0)
    monkeypatch.setattr(mod, "create_silence", lambda *a, **k: None)
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(mod, "merge_audio_video", lambda *a, **k: None)
    (tmp_path / "timeline.json").write_text("[]", encoding="utf-8")
    (tmp_path / "narration.json").write_text(
        json.dumps([{"start_at": 0, "text": "a"}, {"start_at": 3, "text": "b"}]), encoding="utf-8"
    )
    (tmp_path / "rec.mp4").write_bytes(b"x")
    return mod


def _argv(tmp_path, progress):
    argv = [
        "tts_pipeline.py",
        "--video", str(tmp_path / "rec.mp4"),
        "--timeline", str(tmp_path / "timeline.json"),
        "--narration", str(tmp_path / "narration.json"),
        "--output", str(tmp_path / "final.mp4"),
        "--work-dir", str(tmp_path / "work"),
    ]
    if progress:
        argv += ["--progress-file", str(progress), "--approval-id", APPROVAL]
    return argv


def _spy(pipe, monkeypatch):
    records = []
    real = pipe.write_progress

    def spy(path, *a, **k):
        real(path, *a, **k)
        if path:
            records.append(json.loads(Path(path).read_text(encoding="utf-8")))

    monkeypatch.setattr(pipe, "write_progress", spy)
    return records


def test_successful_run_reports_each_stage(pipe, monkeypatch, tmp_path):
    progress = tmp_path / "work" / "logs" / "merge_progress.json"
    records = _spy(pipe, monkeypatch)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, progress))
    pipe.main()
    assert [(r["state"], r["stage"]) for r in records] == [
        ("running", "tts"), ("running", "tts"), ("running", "merge"), ("done", "done"),
    ]
    assert records[0]["message"] == "Generating speech 1 of 2"
    assert (records[0]["step"], records[0]["total"]) == (1, 2)
    assert records[2]["message"] == "Merging audio and video"
    assert all(r["approval_id"] == APPROVAL for r in records)
    assert all(isinstance(r["updated_at"], float) for r in records)


def test_merge_failure_is_recorded_and_reraised(pipe, monkeypatch, tmp_path):
    progress = tmp_path / "work" / "logs" / "merge_progress.json"
    records = _spy(pipe, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(pipe, "merge_audio_video", boom)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, progress))
    with pytest.raises(RuntimeError, match="ffmpeg exploded"):
        pipe.main()
    last = records[-1]
    assert (last["state"], last["stage"]) == ("failed", "merge")
    assert last["error"] == "ffmpeg exploded"
    assert last["message"] == "Generation failed"


def test_tts_failure_reports_tts_stage(pipe, monkeypatch, tmp_path):
    progress = tmp_path / "work" / "logs" / "merge_progress.json"
    records = _spy(pipe, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("lemonade down")

    monkeypatch.setattr(pipe, "generate_tts", boom)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, progress))
    with pytest.raises(RuntimeError, match="lemonade down"):
        pipe.main()
    assert (records[-1]["state"], records[-1]["stage"]) == ("failed", "tts")


def test_no_progress_file_writes_nothing(pipe, monkeypatch, tmp_path):
    records = _spy(pipe, monkeypatch)
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, None))
    pipe.main()
    assert records == []
    assert not list(tmp_path.rglob("merge_progress.json*"))


def test_write_progress_is_atomic_and_none_is_noop(pipe, tmp_path):
    target = tmp_path / "logs" / "p.json"
    pipe.write_progress(target, APPROVAL, "running", "tts", 1, 3, "Generating speech 1 of 3")
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["approval_id"] == APPROVAL and data["step"] == 1 and data["total"] == 3
    assert data["error"] is None
    assert not (tmp_path / "logs" / "p.json.tmp").exists()
    pipe.write_progress(None, APPROVAL, "running", "tts")
    assert sorted(p.name for p in (tmp_path / "logs").iterdir()) == ["p.json"]
