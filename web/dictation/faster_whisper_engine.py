"""faster-whisper (CTranslate2) engine adapter."""
from __future__ import annotations

from pathlib import Path


class FasterWhisperEngine:
    def __init__(self) -> None:
        self._model = None

    def load(self, model_dir: Path) -> None:
        from faster_whisper import WhisperModel
        self._model = WhisperModel(str(model_dir), device="cpu", compute_type="int8")

    def transcribe(self, pcm16: bytes) -> str:
        import numpy as np
        audio = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            audio, language="en", beam_size=5, vad_filter=True
        )
        return " ".join(s.text.strip() for s in segments).strip()
