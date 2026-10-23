"""Resolves the active dictation model and runs transcription."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from dictation import engine as engine_mod

MANIFEST_PATH = Path(__file__).with_name("models.json")
USER_MODELS_DIR = Path.home() / ".gator" / "models" / "dictation"
SOURCE_MODELS_DIR = Path(__file__).resolve().parents[2] / "models" / "dictation"
MAX_PCM_BYTES = 640_000  # 20 s of 16 kHz mono PCM16

_lock = threading.Lock()
_loaded: tuple[str, engine_mod.Engine] | None = None


class DictationUnavailable(Exception):
    """The configured model or engine cannot be used."""


def reset() -> None:
    global _loaded
    with _lock:
        _loaded = None


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def active_model_id(cfg: dict | None = None) -> str:
    if cfg is None:
        import shared
        cfg = shared.cfg
    manifest = _manifest()
    model_id = (cfg.get("dictation") or {}).get("model") or manifest["default"]
    if model_id not in manifest["models"]:
        known = ", ".join(sorted(manifest["models"]))
        raise DictationUnavailable(f"unknown dictation model '{model_id}' (known: {known})")
    return model_id


def resolve_model_dir(model_id: str) -> Path | None:
    dirname = _manifest()["models"][model_id]["dir"]
    roots = [USER_MODELS_DIR]
    bundled = os.environ.get("AIGATOR_MODELS_DIR")
    if bundled:
        roots.append(Path(bundled))
    roots.append(SOURCE_MODELS_DIR)
    for root in roots:
        candidate = root / dirname
        if (candidate / "model.bin").is_file():
            return candidate
    return None


def _engine_for(model_id: str) -> engine_mod.Engine:
    global _loaded
    if _loaded and _loaded[0] == model_id:
        return _loaded[1]
    model_dir = resolve_model_dir(model_id)
    if model_dir is None:
        raise DictationUnavailable(f"dictation model '{model_id}' is not installed")
    try:
        eng = engine_mod.create_engine(_manifest()["models"][model_id]["engine"])
        eng.load(model_dir)
    except Exception as e:
        raise DictationUnavailable(f"dictation model '{model_id}' failed to load: {e}") from e
    _loaded = (model_id, eng)
    return eng


def transcribe(pcm16: bytes, cfg: dict | None = None) -> str:
    model_id = active_model_id(cfg)
    with _lock:
        return _engine_for(model_id).transcribe(pcm16)
