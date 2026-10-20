"""Deterministic Demo project media operations with provenance.

FastAPI-free. Every operation probes its inputs with ffprobe, runs one ffmpeg
command, probes the output, and returns a result built only from those probes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import demo_projects as dp
import narration_approval

EPS = 0.05
DURATION_TOL = 0.30
SYNC_TOL = 1.0
MAX_FRAMES = 8
MAX_LEDGER_SUMMARIES = 50
INTRO_MODES = ("none", "hold", "card")
INTRO_MIN_SEC, INTRO_MAX_SEC, INTRO_DEFAULT_SEC = 0.5, 10.0, 2.0
INTRO_TITLE_MAX = 80
MEDIA_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".mp3", ".m4a", ".wav"}
TTS_SCRIPT = Path(__file__).parent / "skills" / "gator-demo-recorder" / "scripts" / "tts_pipeline.py"

_OP_LOCK = threading.RLock()
_EXT_LOCK = threading.Lock()

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)

_OPTIONS = [
    "Choose a start and end inside the real recording.",
    "Provide another clip to append or use as the replacement.",
    "Re-record the missing part.",
]


class MediaError(Exception):
    def __init__(self, code: str, message: str, **detail):
        super().__init__(message)
        self.code = code
        self.detail = detail

    def to_result(self) -> dict:
        return {"error": self.code, "message": str(self), **self.detail}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

# ── binaries and subprocess seam ─────────────────────────────────────────────

def _find_binary(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if os.name == "nt":
        base = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
        if base.exists():
            for candidate in sorted(base.glob(f"*/*/bin/{name}.exe"), reverse=True):
                return str(candidate)
    for folder in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"):
        candidate = Path(folder) / name
        if candidate.exists():
            return str(candidate)
    return None


def find_binaries() -> tuple[str, str]:
    ffmpeg, ffprobe = _find_binary("ffmpeg"), _find_binary("ffprobe")
    if not ffmpeg or not ffprobe:
        raise MediaError(
            "ffmpeg_missing",
            "ffmpeg and ffprobe are required. Install with: winget install Gyan.FFmpeg (Windows) "
            "or brew install ffmpeg (macOS).",
        )
    return ffmpeg, ffprobe


def _run(cmd: list[str], timeout: int = 900, cwd: Path | None = None,
         env: dict | None = None) -> subprocess.CompletedProcess:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=flags, cwd=str(cwd) if cwd else None, env=env,
    )


def _ffmpeg(args: list[str], cwd: Path | None = None) -> None:
    ffmpeg, _ = find_binaries()
    result = _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args], cwd=cwd)
    if result.returncode != 0:
        raise MediaError("ffmpeg_failed", "ffmpeg failed.", stderr_tail=(result.stderr or "")[-600:])

# ── probing ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MediaInfo:
    duration_sec: float
    video_duration_sec: float | None
    audio_duration_sec: float | None
    width: int
    height: int
    fps: float
    fps_expr: str
    has_video: bool
    has_audio: bool
    size_bytes: int

    def to_dict(self) -> dict:
        return {
            "duration_sec": round(self.duration_sec, 3), "width": self.width, "height": self.height,
            "fps": round(self.fps, 3), "has_video": self.has_video, "has_audio": self.has_audio,
            "size_bytes": self.size_bytes,
        }


def _float(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out > 0 else None


def _fps(expr: str | None) -> tuple[float, str]:
    try:
        num, den = (expr or "0/1").split("/")
        value = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return 0.0, "0/1"
    return value, expr or "0/1"


def probe(path: Path) -> MediaInfo:
    _, ffprobe = find_binaries()
    result = _run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    if result.returncode != 0:
        raise MediaError("unreadable_media", f"ffprobe could not read {path.name}.",
                         stderr_tail=(result.stderr or "")[-300:])
    data = json.loads(result.stdout or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    video_dur = _float(video.get("duration")) if video else None
    audio_dur = _float(audio.get("duration")) if audio else None
    duration = _float((data.get("format") or {}).get("duration")) or video_dur or audio_dur
    if not duration:
        raise MediaError("unreadable_media", f"{path.name} has no readable duration.")
    fps, fps_expr = _fps(video.get("avg_frame_rate") if video else None)
    return MediaInfo(
        duration_sec=duration,
        video_duration_sec=video_dur or (duration if video else None),
        audio_duration_sec=audio_dur or (duration if audio else None),
        width=int(video.get("width", 0)) if video else 0,
        height=int(video.get("height", 0)) if video else 0,
        fps=fps, fps_expr=fps_expr,
        has_video=video is not None, has_audio=audio is not None,
        size_bytes=path.stat().st_size,
    )

# ── time validation ──────────────────────────────────────────────────────────

def _number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        raise MediaError("bad_argument", f"{field} must be a number of seconds.", field=field)
    return float(value)


def check_time(value, duration: float, *, field: str, rel: str) -> float:
    t = _number(value, field)
    if t < 0 or t >= duration:
        raise MediaError(
            "out_of_range",
            f"{field}={t:g}s is outside {rel}, which is {duration:.1f}s long.",
            field=field, requested_sec=t, duration_sec=round(duration, 3),
            valid_range_sec=[0, round(duration, 3)], file=rel, options=list(_OPTIONS),
        )
    return t


def check_interval(start, end, duration: float, *, rel: str) -> tuple[float, float]:
    s = check_time(start, duration, field="start_sec", rel=rel)
    e = _number(end, "end_sec")
    if e > duration + EPS:
        raise MediaError(
            "out_of_range",
            f"end_sec={e:g}s is outside {rel}, which is {duration:.1f}s long.",
            field="end_sec", requested_sec=e, duration_sec=round(duration, 3),
            valid_range_sec=[0, round(duration, 3)], file=rel, options=list(_OPTIONS),
        )
    if e <= s:
        raise MediaError("bad_interval", "end_sec must be greater than start_sec.",
                         start_sec=s, end_sec=e)
    return s, min(e, duration)
