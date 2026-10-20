"""Combine imported clips into one normalized timeline with ffmpeg."""

import hashlib
import json
from pathlib import Path

from demo_clips import SPEC_VERSION

TARGET_FPS = 30
MAX_OUT_W = 1920
MAX_OUT_H = 1080
AUDIO_RATE = 48000


def canvas_size(clips: list) -> tuple:
    width, height = clips[0]["width"], clips[0]["height"]
    scale = min(1.0, MAX_OUT_W / width, MAX_OUT_H / height)
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def video_filter(w: int, h: int) -> str:
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={TARGET_FPS},format=yuv420p"
    )


def normalize_argv(ffmpeg, src: Path, dst: Path, start: float, length: float, w: int, h: int) -> list:
    return [str(ffmpeg), "-y", "-ss", str(start), "-t", str(length), "-i", str(src), "-an",
            "-vf", video_filter(w, h), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(dst)]


def normalized_name(clip: dict, src: Path, w: int, h: int) -> str:
    stat = Path(src).stat()
    key = json.dumps([SPEC_VERSION, stat.st_size, stat.st_mtime_ns,
                      clip["trim_start"], clip["trim_end"], w, h])
    return f"{clip['id']}_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:8]}.mp4"


def concat_list_text(files: list) -> str:
    return "".join("file '" + Path(f).as_posix().replace("'", "'\\''") + "'\n" for f in files)


def concat_argv(ffmpeg, list_file: Path, dst: Path) -> list:
    return [str(ffmpeg), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-movflags", "+faststart", str(dst)]


def soundtrack_argv(ffmpeg, srcs: list, dst: Path) -> list:
    argv = [str(ffmpeg), "-y"]
    for src in srcs:
        argv += ["-i", str(src)]
    legs = [f"[{i}:a]aresample={AUDIO_RATE},aformat=channel_layouts=stereo[a{i}]" for i in range(len(srcs))]
    joined = "".join(f"[a{i}]" for i in range(len(srcs)))
    graph = ";".join(legs) + f";{joined}concat=n={len(srcs)}:v=0:a=1[a]"
    return argv + ["-filter_complex", graph, "-map", "[a]", "-c:a", "aac", "-b:a", "128k", str(dst)]
