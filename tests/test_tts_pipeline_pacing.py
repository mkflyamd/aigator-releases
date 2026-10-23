import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "web" / "skills" / "gator-demo-recorder" / "scripts" / "tts_pipeline.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("tts_pipeline_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def recorded(monkeypatch, tmp_path):
    pipe = _load()
    silences = []

    def fake_tts(text, out_path, *a, **k):
        Path(out_path).write_bytes(b"x")
        return 1

    monkeypatch.setattr(pipe, "get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(pipe, "generate_tts", fake_tts)
    monkeypatch.setattr(pipe, "get_duration", lambda *a, **k: 2.0)
    monkeypatch.setattr(pipe, "create_silence", lambda dur, out, ff: silences.append(round(dur, 2)))
    monkeypatch.setattr(pipe.subprocess, "run", lambda *a, **k: None)

    def run(narration):
        silences.clear()
        pipe.build_synced_audio(narration, tmp_path / "work", "http://x", "kokoro-v1", "af_heart")
        return list(silences)

    return pipe, run


def test_pause_is_inserted_and_absorbs_gap(recorded):
    _, run = recorded
    # seg0 ends at 2.0, pause 1.5 -> 3.5, next start_at 3 is already past: no extra silence.
    assert run([{"start_at": 0, "text": "a", "pause_after": 1.5}, {"start_at": 3, "text": "b"}]) == [1.5]


def test_later_start_at_still_adds_remaining_gap(recorded):
    _, run = recorded
    # seg0 ends at 2.0, pause 0.5 -> 2.5, next start_at 6 -> 3.5s pre-silence.
    assert run([{"start_at": 0, "text": "a", "pause_after": 0.5}, {"start_at": 6, "text": "b"}]) == [0.5, 3.5]


def test_numeric_string_is_accepted(recorded):
    _, run = recorded
    assert run([{"start_at": 0, "text": "a", "pause_after": "1.5"}]) == [1.5]


@pytest.mark.parametrize("bad", ["abc", None, -2, float("nan"), float("-inf")])
def test_invalid_values_mean_no_pause(recorded, bad):
    _, run = recorded
    assert run([{"start_at": 0, "text": "a", "pause_after": bad}]) == []


def test_missing_key_means_no_pause(recorded):
    _, run = recorded
    assert run([{"start_at": 0, "text": "a"}]) == []


def test_huge_value_is_capped(recorded):
    _, run = recorded
    assert run([{"start_at": 0, "text": "a", "pause_after": 99}]) == [10.0]


def test_pause_after_unit():
    pipe = _load()
    assert pipe._pause_after({"pause_after": 1.26}) == 1.26
    assert pipe._pause_after({"pause_after": "2"}) == 2.0
    assert pipe._pause_after({"pause_after": 10.5}) == 10.0
    assert pipe._pause_after({}) == 0.0
    assert pipe._pause_after({"pause_after": float("inf")}) == 0.0
