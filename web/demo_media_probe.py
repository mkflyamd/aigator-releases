"""Validate user-supplied video/audio before it reaches ffmpeg."""

import json
import subprocess
from pathlib import Path

from proc_utils import no_window_kwargs

VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")
AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac")
VIDEO_CODECS = {"h264", "hevc", "vp8", "vp9", "av1", "mpeg4"}
AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis", "flac", "pcm_s16le", "pcm_s24le", "pcm_f32le"}
MAX_FILE_BYTES = 2 * 1024**3
MAX_CLIP_SECONDS = 1800
MAX_VIDEO_CLIPS = 8
MAX_AUDIO_ASSETS = 4
MAX_DIMENSION = 7680


class MediaRejected(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def extension_kind(name: str) -> str | None:
    ext = Path(str(name)).suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def ffprobe_path() -> str | None:
    from routes.recorder import _find_ffprobe

    return _find_ffprobe()


def _run_ffprobe(path: Path) -> dict:
    exe = ffprobe_path()
    if not exe:
        raise MediaRejected("tools_missing", "ffprobe was not found. Install ffmpeg and try again.")
    try:
        proc = subprocess.run(
            [exe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60, **no_window_kwargs(),
        )
    except subprocess.TimeoutExpired:
        raise MediaRejected("unreadable", "That file could not be read as media.") from None
    if proc.returncode != 0:
        raise MediaRejected("unreadable", "That file could not be read as media.")
    try:
        return json.loads(proc.stdout or "{}")
    except ValueError:
        raise MediaRejected("unreadable", "That file could not be read as media.") from None


def probe_media(path, name: str | None = None) -> dict:
    kind = extension_kind(name or str(path))
    if kind is None:
        raise MediaRejected(
            "unsupported_type",
            "Supported video: " + ", ".join(VIDEO_EXTS) + ". Supported audio: " + ", ".join(AUDIO_EXTS) + ".",
        )
    data = _run_ffprobe(Path(path))
    streams = data.get("streams") or []
    video = next(
        (s for s in streams
         if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")),
        None,
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0

    if kind == "video":
        if video is None:
            raise MediaRejected("no_video_stream", "That file has no video stream.")
        if video.get("codec_name") not in VIDEO_CODECS:
            raise MediaRejected("codec_unsupported", f"Video codec '{video.get('codec_name')}' is not supported.")
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            raise MediaRejected("too_big_dimensions", f"Video is larger than {MAX_DIMENSION}px on a side.")
    else:
        if audio is None:
            raise MediaRejected("no_audio_stream", "That file has no audio stream.")
        if audio.get("codec_name") not in AUDIO_CODECS:
            raise MediaRejected("codec_unsupported", f"Audio codec '{audio.get('codec_name')}' is not supported.")
        width = height = None

    if duration <= 0:
        raise MediaRejected("zero_duration", "That file has no playable duration.")
    if duration > MAX_CLIP_SECONDS:
        raise MediaRejected("too_long", f"Files longer than {MAX_CLIP_SECONDS // 60} minutes are not supported.")

    return {
        "kind": kind,
        "duration": duration,
        "width": width,
        "height": height,
        "has_audio": audio is not None,
        "video_codec": video.get("codec_name") if kind == "video" else None,
        "audio_codec": audio.get("codec_name") if audio is not None else None,
    }
