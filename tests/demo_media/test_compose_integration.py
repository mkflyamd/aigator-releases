import subprocess
from pathlib import Path

import pytest

import demo_clips as clips
import demo_compose as compose
import demo_media_probe as probe

pytestmark = pytest.mark.skipif(
    not (compose._ffmpeg() and probe.ffprobe_path()), reason="ffmpeg/ffprobe not available"
)


def _make(out: Path, *args: str) -> Path:
    subprocess.run([compose._ffmpeg(), "-y", *args, str(out)], check=True, capture_output=True)
    return out


def _video(out: Path, size: str, seconds: int) -> Path:
    return _make(
        out,
        "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", str(seconds), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac",
    )


def _tone(out: Path, seconds: int) -> Path:
    return _make(out, "-f", "lavfi", "-i", "sine=frequency=220", "-t", str(seconds))


def _add(pid, path: Path):
    return clips.add_item(pid, path, path.name, probe.probe_media(path))


@pytest.fixture
def pid(store):
    return store.create_project(name="Integration")["project_id"]


def test_two_clips_and_a_music_bed_build_one_timeline(store, pid, tmp_path):
    _add(pid, _video(tmp_path / "a.mp4", "640x360", 2))
    _add(pid, _video(tmp_path / "b.mp4", "320x240", 3))
    _add(pid, _tone(tmp_path / "bed.mp3", 5))

    assert compose.build(pid) == "ready"

    project = store.get_project(pid)
    timeline = Path(project["raw"])
    assert timeline.name == "timeline.mp4"
    info = probe._run_ffprobe(timeline)
    kinds = {s["codec_type"] for s in info["streams"]}
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert kinds == {"video"}
    assert video["codec_name"] == "h264"
    assert (video["width"], video["height"]) == (640, 360)
    assert float(info["format"]["duration"]) == pytest.approx(5.0, abs=0.4)

    soundtrack = Path(project["path"]) / "work" / "soundtrack.m4a"
    assert soundtrack.exists()
    assert {s["codec_type"] for s in probe._run_ffprobe(soundtrack)["streams"]} == {"audio"}


def test_trim_changes_the_timeline_length(store, pid, tmp_path):
    _add(pid, _video(tmp_path / "a.mp4", "640x360", 3))
    _add(pid, _video(tmp_path / "b.mp4", "640x360", 3))
    clips.set_trim(pid, "c1", 0.5, 1.5)

    assert compose.build(pid) == "ready"

    info = probe._run_ffprobe(Path(store.get_project(pid)["raw"]))
    assert float(info["format"]["duration"]) == pytest.approx(4.0, abs=0.4)
    assert clips.load(pid)["timeline"]["duration"] == pytest.approx(4.0, abs=0.01)
