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
