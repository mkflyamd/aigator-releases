"""Runs the bundled model end to end. Skipped when faster-whisper or the model is absent."""
import os
from pathlib import Path

import pytest

from dictation import service

pytest.importorskip("faster_whisper")

REPO_MODELS = Path(__file__).resolve().parent.parent / "models" / "dictation"


@pytest.fixture(autouse=True)
def _models_dir(monkeypatch):
    monkeypatch.setenv("AIGATOR_MODELS_DIR", os.environ.get("AIGATOR_MODELS_DIR", str(REPO_MODELS)))
    service.reset()
    yield
    service.reset()


def test_silence_transcribes_to_empty_text():
    if service.resolve_model_dir(service.active_model_id({})) is None:
        pytest.skip("dictation model not installed")
    one_second_of_silence = b"\x00\x00" * 16000
    assert service.transcribe(one_second_of_silence, cfg={}) == ""
