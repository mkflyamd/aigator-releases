import importlib
import json

import pytest

import demo_media as dm
from tests.demo_media_ops.helpers import approve, make_video

tools = importlib.import_module("skills.gator-demo-recorder.tools")


def _dominant(folder, rel):
    from PIL import Image
    r, g, b = Image.open(folder / rel).convert("RGB").getpixel((80, 45))
    return "red" if r > 150 and b < 100 else "blue" if b > 150 and r < 100 else f"other{(r, g, b)}"


def _red_at_20_to_25(pid, folder):
    make_video(folder / "source" / "fix.mp4", 10, color="red")
    return dm.replace_interval(pid, 20, 25, "source/fix.mp4")["output"]["rel"]


def test_cut_shortens_and_reports_a_time_map(project):
    pid, folder = project
    _red_at_20_to_25(pid, folder)
    result = dm.cut_intervals(pid, [[8, 15], [30, 38]])
    assert result["timeline_shifted"] is True
    assert result["cut_intervals_sec"] == [[8, 15], [30, 38]]
    assert result["removed_sec"] == 15
    assert result["output"]["duration_sec"] == pytest.approx(62.2 - 15, abs=0.4)
    assert [m["old_sec"] for m in result["time_map"]] == [[0, 8], [15, 30], [38, 62.2]]
    assert [m["new_sec"][0] for m in result["time_map"]] == [0, 8, 23]
    assert dm.read_media(pid)["current"] == result["output"]["rel"]
    entry = json.loads((folder / "work/logs/media_ops.jsonl").read_text().splitlines()[-1])
    assert entry["operation"] == "cut_intervals" and entry["cut_intervals_sec"] == [[8, 15], [30, 38]]


def test_cut_removes_the_chosen_footage(project):
    pid, folder = project
    _red_at_20_to_25(pid, folder)
    out = dm.cut_intervals(pid, [[10, 20]])["output"]["rel"]
    frames = dm.inspect_frames(pid, out, [5, 12, 20])["frames"]
    assert [_dominant(folder, f["rel"]) for f in frames] == ["blue", "red", "blue"]


def test_cut_sorts_intervals_given_out_of_order(project):
    pid, _ = project
    result = dm.cut_intervals(pid, [[30, 35], [5, 10]])
    assert result["cut_intervals_sec"] == [[5, 10], [30, 35]]


@pytest.mark.parametrize("intervals,code", [
    ([[10, 20], [15, 25]], "overlapping_intervals"),
    ([[10, 405]], "out_of_range"),
    ([[390, 405]], "out_of_range"),
    ([[20, 10]], "bad_interval"),
    ([[0, 62.2]], "nothing_left"),
    ([], "bad_argument"),
    ([[1, 2, 3]], "bad_argument"),
    ("5-10", "bad_argument"),
])
def test_cut_rejects_bad_intervals_and_leaves_the_recording_alone(project, intervals, code):
    pid, folder = project
    with pytest.raises(dm.MediaError) as exc:
        dm.cut_intervals(pid, intervals)
    assert exc.value.code == code
    assert dm.current_rel(pid, folder) == "source/recording.mp4"
    assert not list((folder / "work" / "edits").glob("edit_*.mp4"))


def test_speed_interval_compresses_the_range(project):
    pid, folder = project
    _red_at_20_to_25(pid, folder)
    result = dm.speed_interval(pid, 20, 25, 5)
    assert result["saved_sec"] == 4
    assert result["sped_interval_sec"] == [20, 25]
    assert result["output"]["duration_sec"] == pytest.approx(62.2 - 4, abs=0.4)
    assert result["time_map"][1] == {"old_sec": [20, 25], "new_sec": [20, 21], "speed": 5.0}
    frames = dm.inspect_frames(pid, result["output"]["rel"], [10, 20.5, 30])["frames"]
    assert [_dominant(folder, f["rel"]) for f in frames] == ["blue", "red", "blue"]


@pytest.mark.parametrize("speed", [1, 1.2, 17, 0, -2, "fast", True])
def test_speed_interval_rejects_unusable_speeds(project, speed):
    pid, _ = project
    with pytest.raises(dm.MediaError) as exc:
        dm.speed_interval(pid, 10, 20, speed)
    assert exc.value.code == "bad_argument"


def test_retime_refuses_a_base_that_already_has_audio(project):
    pid, folder = project
    make_video(folder / "source" / "with_audio.mp4", 8, audio=True)
    with pytest.raises(dm.MediaError) as exc:
        dm.cut_intervals(pid, [[1, 2]], base_rel="source/with_audio.mp4")
    assert exc.value.code == "base_has_audio"


def test_a_cut_makes_the_existing_approval_stale(project):
    pid, folder = project
    approve(pid, [{"text": "one", "start_at": 0}])
    dm.cut_intervals(pid, [[8, 15]])
    with pytest.raises(dm.MediaError) as exc:
        dm.load_approved_narration(pid, folder)
    assert exc.value.code == "approval_stale_media"


def test_retime_through_the_tool_layer(project):
    pid, _ = project
    cut = tools.TOOL_HANDLERS["demo_cut_intervals"](intervals=[[8, 15]], project_id=pid)
    assert "error" not in cut and cut["removed_sec"] == 7
    fast = tools.TOOL_HANDLERS["demo_speed_interval"](start_sec=0, end_sec=10, speed=2, project_id=pid)
    assert "error" not in fast and fast["saved_sec"] == 5
    bad = tools.TOOL_HANDLERS["demo_cut_intervals"](intervals=[[390, 405]], project_id=pid)
    assert bad["error"] == "out_of_range"
