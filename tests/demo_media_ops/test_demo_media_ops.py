import json

import pytest

import demo_media as dm
import demo_projects as dp
from tests.demo_media_ops.helpers import make_video


def test_probe_reports_real_duration(project):
    pid, folder = project
    info = dm.probe(folder / "source" / "recording.mp4")
    assert info.duration_sec == pytest.approx(62.2, abs=0.2)
    assert info.has_video and not info.has_audio
    assert (info.width, info.height) == (160, 90)


def test_check_time_bounds():
    assert dm.check_time(0, 62.2, field="t", rel="a.mp4") == 0
    assert dm.check_time(62.1, 62.2, field="t", rel="a.mp4") == 62.1
    for bad in (-1, 62.2, 390):
        with pytest.raises(dm.MediaError) as exc:
            dm.check_time(bad, 62.2, field="t", rel="a.mp4")
        assert exc.value.code == "out_of_range"
        assert exc.value.detail["duration_sec"] == 62.2
    with pytest.raises(dm.MediaError) as exc:
        dm.check_time("5", 62.2, field="t", rel="a.mp4")
    assert exc.value.code == "bad_argument"


def test_check_interval_rules():
    assert dm.check_interval(10, 20, 62.2, rel="a.mp4") == (10, 20)
    assert dm.check_interval(60, 62.23, 62.2, rel="a.mp4") == (60, 62.2)
    for args, code in (((10, 405), "out_of_range"), ((390, 405), "out_of_range"), ((20, 10), "bad_interval")):
        with pytest.raises(dm.MediaError) as exc:
            dm.check_interval(*args, 62.2, rel="a.mp4")
        assert exc.value.code == code


def test_record_op_appends_ledger_and_keeps_last_50(project):
    pid, folder = project
    for n in range(53):
        dm.record_op(pid, folder, {"operation": "inspect_frames", "n": n})
    lines = (folder / "work/logs/media_ops.jsonl").read_text().splitlines()
    assert len(lines) == 53
    ops = dm.read_media(pid)["ops"]
    assert len(ops) == 50 and ops[-1]["n"] == 52 and ops[0]["n"] == 3


def test_current_rel_follows_raw_until_an_edit_is_set(project):
    pid, folder = project
    assert dm.current_rel(pid, folder) == "source/recording.mp4"
    dm.set_current(pid, folder, "work/edits/edit_001.mp4")
    assert dm.current_rel(pid, folder) == "work/edits/edit_001.mp4"


def test_manifest_lists_real_files(project):
    pid, folder = project
    result = dm.manifest(pid)
    rels = [f["rel"] for f in result["files"]]
    assert "source/recording.mp4" in rels
    assert result["current"] == "source/recording.mp4"
    assert dm.read_media(pid)["manifest"]["files"]


def test_check_time_rejects_impossible_390s(project):
    pid, folder = project
    with pytest.raises(dm.MediaError) as exc:
        dm.inspect_frames(pid, "source/recording.mp4", [390])
    result = exc.value.to_result()
    assert result["error"] == "out_of_range"
    assert result["duration_sec"] == pytest.approx(62.2, abs=0.2)
    assert result["rejected"][0]["requested_sec"] == 390
    assert not list((folder / "work" / "frames").glob("*.png"))


def test_inspect_frames_returns_files_and_ledger(project):
    pid, folder = project
    result = dm.inspect_frames(pid, "source/recording.mp4", [0, 30.5])
    assert [f["time_sec"] for f in result["frames"]] == [0, 30.5]
    for f in result["frames"]:
        assert (folder / f["rel"]).stat().st_size > 0
    ledger = (folder / "work/logs/media_ops.jsonl").read_text().splitlines()
    assert json.loads(ledger[-1])["operation"] == "inspect_frames"


def test_replace_interval_proves_source_and_keeps_duration(project):
    pid, folder = project
    make_video(folder / "source" / "fix.mp4", 10, color="red")
    result = dm.replace_interval(pid, 20, 25, "source/fix.mp4", insert_start_sec=2)
    assert result["output"]["duration_sec"] == pytest.approx(62.2, abs=0.4)
    assert result["replaced_interval_sec"] == [20, 25]
    assert result["inserted_from"] == {"rel": "source/fix.mp4", "interval_sec": [2, 7]}
    assert result["timeline_shifted"] is False
    assert dm.read_media(pid)["current"] == result["output"]["rel"]
    entry = json.loads((folder / "work/logs/media_ops.jsonl").read_text().splitlines()[-1])
    assert entry["inserted_from"]["source_duration_sec"] == pytest.approx(10, abs=0.2)


def test_replace_rejects_out_of_range_interval_and_short_insert(project):
    pid, folder = project
    make_video(folder / "source" / "fix.mp4", 3, color="red")
    with pytest.raises(dm.MediaError) as exc:
        dm.replace_interval(pid, 390, 405, "source/fix.mp4")
    assert exc.value.code == "out_of_range"
    with pytest.raises(dm.MediaError) as exc:
        dm.replace_interval(pid, 20, 25, "source/fix.mp4")
    assert exc.value.code == "out_of_range" and exc.value.detail["needed_sec"] == 5


def test_append_clip_extends_duration(project):
    pid, folder = project
    make_video(folder / "source" / "outro.mp4", 4, color="green")
    result = dm.append_clip(pid, "source/outro.mp4")
    assert result["output"]["duration_sec"] == pytest.approx(66.2, abs=0.4)
    assert result["appended_at_sec"] == pytest.approx(62.2, abs=0.2)


def test_base_with_audio_is_refused(project):
    pid, folder = project
    make_video(folder / "source" / "with_audio.mp4", 5, audio=True)
    make_video(folder / "source" / "x.mp4", 5)
    with pytest.raises(dm.MediaError) as exc:
        dm.append_clip(pid, "source/x.mp4", base_rel="source/with_audio.mp4")
    assert exc.value.code == "base_has_audio"


def _dominant(folder, rel):
    from PIL import Image
    r, g, b = Image.open(folder / rel).convert("RGB").getpixel((80, 45))
    return "red" if r > 150 and b < 100 else "blue" if b > 150 and r < 100 else f"other{(r, g, b)}"


def test_replaced_interval_pixels_come_from_the_insert(project):
    pid, folder = project
    make_video(folder / "source" / "fix.mp4", 10, color="red")
    out = dm.replace_interval(pid, 20, 25, "source/fix.mp4")["output"]["rel"]
    frames = dm.inspect_frames(pid, out, [10, 22, 40])["frames"]
    assert [_dominant(folder, f["rel"]) for f in frames] == ["blue", "red", "blue"]


def test_edit_chain_is_discarded_when_the_raw_recording_changes(project):
    pid, folder = project
    make_video(folder / "source" / "fix.mp4", 10, color="red")
    edited = dm.replace_interval(pid, 20, 25, "source/fix.mp4")["output"]["rel"]
    assert dm.current_rel(pid, folder) == edited
    make_video(folder / "work" / "timeline.mp4", 30)
    dp.update_project(pid, raw="work/timeline.mp4")
    assert dm.current_rel(pid, folder) == "work/timeline.mp4"


def test_intro_hold_extends_and_card_draws_title(project):
    pid, folder = project
    make_video(folder / "source" / "short.mp4", 5)
    hold = dm.make_intro_video(pid, "source/short.mp4", {"mode": "hold", "duration_sec": 2})
    assert hold["output"]["duration_sec"] == pytest.approx(7, abs=0.4)
    card = dm.make_intro_video(pid, "source/short.mp4",
                               {"mode": "card", "duration_sec": 2, "title": "Slack: it's 50% done"})
    assert card["output"]["duration_sec"] == pytest.approx(7, abs=0.4)
    assert not list((folder / "work/edits").glob("intro_title.txt"))


def test_normalize_intro_rules():
    assert dm.normalize_intro(None)["mode"] == "none"
    assert dm.normalize_intro({"mode": "hold"})["duration_sec"] == 2.0
    for bad in ({"mode": "card"}, {"mode": "hold", "duration_sec": 0.1},
                {"mode": "hold", "duration_sec": 11}, {"mode": "spin"},
                {"mode": "card", "title": "x" * 81}):
        with pytest.raises(dm.MediaError):
            dm.normalize_intro(bad)
