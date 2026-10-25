import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

import demo_media as dm
import demo_projects as dp
from tests.demo_media_ops.helpers import approve, make_video


def _load_pipeline():
    spec = importlib.util.spec_from_file_location("tts_pipeline_under_test", dm.TTS_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_tts(monkeypatch):
    """Replace Lemonade with a sine track of the requested length; run the real merge."""
    calls = {}

    def run(video, timeline_file, narration_file, out, work_dir, voice, soundtrack=None):
        narration = json.loads(Path(narration_file).read_text())
        calls["narration"] = narration
        calls["video"] = video
        calls["soundtrack"] = soundtrack
        ffmpeg, _ = dm.find_binaries()
        work_dir.mkdir(parents=True, exist_ok=True)
        audio = work_dir / "full_narration_synced.mp3"
        seconds = calls.get("audio_sec", narration[-1]["start_at"] + 3)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"sine=frequency=300:duration={seconds}", str(audio)], check=True)
        _load_pipeline().merge_audio_video(video, audio, out)

    monkeypatch.setattr(dm, "_run_tts_pipeline", run)
    return calls


def test_narration_longer_than_source_extends_video(project, fake_tts):
    pid, folder = project
    make_video(folder / "source" / "short.mp4", 10)
    dp.update_project(pid, raw="source/short.mp4")
    approve(pid, [{"text": "one", "start_at": 1}, {"text": "two", "start_at": 8}])
    fake_tts["audio_sec"] = 16
    result = dm.merge_narration(pid)
    assert result["video_extended_by_sec"] == pytest.approx(6.0, abs=0.6)
    assert result["sync_ok"] is True
    final = Path(result["output"]["path"])
    assert final.parent == folder / "final" and final.name == "Slack_Demo_v1.mp4"
    info = dm.probe(final)
    assert info.has_video and info.has_audio
    assert info.duration_sec == pytest.approx(16, abs=0.6)
    assert dm.read_media(pid)["output_version"] == 1
    assert not (folder / "source" / "video_extended.mp4").exists()


def test_intro_hold_shifts_narration_and_adds_duration(project, fake_tts):
    pid, folder = project
    make_video(folder / "source" / "short.mp4", 10)
    dp.update_project(pid, raw="source/short.mp4")
    approve(pid, [{"text": "one", "start_at": 0}, {"text": "two", "start_at": 4}],
            intro={"mode": "hold", "duration_sec": 3})
    fake_tts["audio_sec"] = 10
    result = dm.merge_narration(pid)
    assert [s["start_at"] for s in fake_tts["narration"]] == [3, 7]
    assert result["intro"]["applied"] and result["intro"]["source"] == "approved_flags"
    assert result["narration"]["first_start_sec"] == 3
    assert result["output"]["duration_sec"] >= 13 - 0.6
    assert result["sync_ok"]


def test_second_merge_archives_previous_and_bumps_version(project, fake_tts):
    pid, folder = project
    make_video(folder / "source" / "short.mp4", 6)
    dp.update_project(pid, raw="source/short.mp4")
    approve(pid, [{"text": "one", "start_at": 0}])
    fake_tts["audio_sec"] = 4
    dm.merge_narration(pid)
    second = dm.merge_narration(pid)
    assert second["output"]["version"] == 2
    assert [f.name for f in (folder / "final").iterdir()] == ["Slack_Demo_v2.mp4"]
    assert any(f.name.endswith("Slack_Demo_v1.mp4") for f in (folder / "previous").iterdir())


def test_narration_start_past_source_is_rejected(project, fake_tts):
    pid, folder = project
    approve(pid, [{"text": "late", "start_at": 390}])
    with pytest.raises(dm.MediaError) as exc:
        dm.merge_narration(pid)
    assert exc.value.code == "out_of_range"
    assert not list((folder / "final").iterdir())


def test_progress_file_tracks_success_and_failure(project, fake_tts, monkeypatch):
    pid, folder = project
    make_video(folder / "source" / "short.mp4", 6)
    dp.update_project(pid, raw="source/short.mp4")
    aid = approve(pid, [{"text": "one", "start_at": 0}])
    fake_tts["audio_sec"] = 4
    dm.merge_narration(pid)
    progress = json.loads((folder / "work/logs/merge_progress.json").read_text())
    assert (progress["approval_id"], progress["state"], progress["stage"]) == (aid, "done", "done")

    def boom(*a, **k):
        raise dm.MediaError("tts_failed", "Narration generation or merge failed.")

    monkeypatch.setattr(dm, "_run_tts_pipeline", boom)
    with pytest.raises(dm.MediaError):
        dm.merge_narration(pid)
    progress = json.loads((folder / "work/logs/merge_progress.json").read_text())
    assert progress["state"] == "failed" and "failed" in progress["error"]


def test_soundtrack_is_forwarded_only_when_timeline_ready(project):
    pid, folder = project
    assert dm._soundtrack(pid, folder) is None
    (folder / "work" / "soundtrack.m4a").write_bytes(b"x")
    dp.set_ext(pid, "clips", {"timeline": {"state": "building", "soundtrack": "work/soundtrack.m4a"}})
    assert dm._soundtrack(pid, folder) is None
    dp.set_ext(pid, "clips", {"timeline": {"state": "ready", "soundtrack": "work/soundtrack.m4a"}})
    assert dm._soundtrack(pid, folder) == folder / "work" / "soundtrack.m4a"


def test_pipeline_command_forwards_progress_file_and_soundtrack(project, monkeypatch):
    pid, folder = project
    work = folder / "work"
    dm._write_progress(folder, "appr_1_abcdef12", "running", "tts", "x")
    seen = {}

    def run(cmd, timeout=None):
        seen["cmd"] = cmd
        out = Path(cmd[cmd.index("--output") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(dm, "_run", run)
    dm._run_tts_pipeline(folder / "source" / "recording.mp4", work / "timeline.json",
                         work / "narration_final.json", work / "out" / "c.mp4", work / "tts",
                         "af_heart", work / "soundtrack.m4a")
    cmd = seen["cmd"]
    assert cmd[cmd.index("--progress-file") + 1] == str(work / "logs" / "merge_progress.json")
    assert cmd[cmd.index("--approval-id") + 1] == "appr_1_abcdef12"
    assert cmd[cmd.index("--soundtrack") + 1] == str(work / "soundtrack.m4a")


def test_failed_delivery_leaves_the_previous_final_in_place(project, fake_tts, monkeypatch):
    pid, folder = project
    make_video(folder / "source" / "short.mp4", 6)
    dp.update_project(pid, raw="source/short.mp4")
    approve(pid, [{"text": "one", "start_at": 0}])
    fake_tts["audio_sec"] = 4
    dm.merge_narration(pid)

    real_replace = dm.os.replace

    def failing_replace(src, dst):
        if Path(src).name == "final_candidate.mp4":
            raise PermissionError("the final folder is locked")
        return real_replace(src, dst)

    monkeypatch.setattr(dm.os, "replace", failing_replace)
    with pytest.raises(PermissionError):
        dm.merge_narration(pid)
    assert [f.name for f in (folder / "final").iterdir()] == ["Slack_Demo_v1.mp4"]
    assert not list((folder / "previous").iterdir())
