"""Deliverables must not point at, or carry, the raw recording they were built from."""

import importlib
import subprocess

import demo_media as dm
from tests.demo_media_ops.helpers import make_video

tools = importlib.import_module("skills.gator-demo-recorder.tools")


def _kinds(result):
    return sorted(f["kind"] for f in result["findings"])


def test_clean_project_has_no_findings(project):
    pid, folder = project
    make_video(folder / "final" / "demo_v1.mp4", 3)
    (folder / "final" / "index.html").write_text("<video src='demo_v1.mp4'></video>", encoding="utf-8")
    result = dm.leak_check(pid)
    assert result == {"ok": True, "project_id": pid, "checked": result["checked"], "findings": []}
    assert result["checked"] >= 2


def test_text_file_naming_the_source_recording_is_flagged(project):
    pid, folder = project
    (folder / "final" / "index.html").write_text("<video src='../source/recording.mp4'></video>", encoding="utf-8")
    (folder / "final" / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    result = dm.leak_check(pid)
    assert not result["ok"]
    assert _kinds(result) == ["source_reference"]
    assert result["findings"][0]["rel"] == "final/index.html"
    assert result["findings"][0]["matched"] == "recording.mp4"


def test_source_media_copied_into_the_served_folder_is_flagged(project):
    pid, folder = project
    make_video(folder / "final" / "recording.mp4", 3)
    result = dm.leak_check(pid)
    assert _kinds(result) == ["source_media_in_served"]
    assert result["findings"][0]["rel"] == "final/recording.mp4"


def test_media_metadata_naming_the_source_is_flagged(project):
    pid, folder = project
    out = folder / "final" / "demo_v1.mp4"
    ffmpeg, _ = dm.find_binaries()
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(folder / "source" / "recording.mp4"),
                    "-c", "copy", "-metadata", "comment=edited from source/recording.mp4", str(out)], check=True)
    result = dm.leak_check(pid)
    assert _kinds(result) == ["source_in_metadata"]
    assert result["findings"][0]["rel"] == "final/demo_v1.mp4"


def test_source_and_work_folders_are_never_scanned(project):
    pid, folder = project
    (folder / "work").mkdir(exist_ok=True)
    (folder / "work" / "notes.json").write_text('{"raw": "source/recording.mp4"}', encoding="utf-8")
    (folder / "source" / "notes.txt").write_text("recording.mp4", encoding="utf-8")
    assert dm.leak_check(pid)["ok"]


def test_tool_layer_returns_the_same_result(project):
    pid, folder = project
    (folder / "final" / "index.html").write_text("recording.mp4", encoding="utf-8")
    result = tools.TOOL_HANDLERS["demo_leak_check"](project_id=pid)
    assert not result["ok"] and result["findings"][0]["kind"] == "source_reference"
    assert tools.TOOL_HANDLERS["demo_leak_check"](project_id="nope")["error"] == "project_not_found"
