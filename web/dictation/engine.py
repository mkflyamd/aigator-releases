"""Speech-to-text engine interface and registry."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol


class Engine(Protocol):
    def load(self, model_dir: Path) -> None: ...

    def transcribe(self, pcm16: bytes) -> str:
        """16 kHz mono PCM16 little-endian bytes in, transcript text out."""
        ...


def _faster_whisper() -> Engine:
    from dictation.faster_whisper_engine import FasterWhisperEngine
    return FasterWhisperEngine()


_ENGINES: dict[str, Callable[[], Engine]] = {"faster-whisper": _faster_whisper}


def register_engine(name: str, factory: Callable[[], Engine]) -> None:
    _ENGINES[name] = factory


def create_engine(name: str) -> Engine:
    try:
        factory = _ENGINES[name]
    except KeyError:
        raise KeyError(f"unknown dictation engine '{name}'") from None
    return factory()
