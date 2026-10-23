"""Combine imported clips into one normalized timeline with ffmpeg."""

import hashlib
import json
import logging
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import demo_clips as clips_mod
import demo_projects as dp
from demo_clips import SPEC_VERSION
from proc_utils import no_window_kwargs

log = logging.getLogger(__name__)

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
    return f"{clip['id']}_{hashlib.sha1(key.encode('utf-8'), usedforsecurity=False).hexdigest()[:8]}.mp4"


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


TIMELINE_REL = "work/timeline.mp4"
SOUNDTRACK_REL = "work/soundtrack.m4a"
RUN_TIMEOUT_SECONDS = 1800


class ComposeError(Exception):
    pass


def _ffmpeg():
    from routes.recorder import _find_ffmpeg
    return _find_ffmpeg()


def _run(argv: list) -> None:
    proc = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                          timeout=RUN_TIMEOUT_SECONDS, **no_window_kwargs())
    if proc.returncode != 0:
        raise ComposeError((proc.stderr or "ffmpeg failed").strip()[-400:])


def _replace_via_part(final: Path, argv_builder) -> None:
    part = final.with_name(final.stem + ".part" + final.suffix)
    _run(argv_builder(part))
    os.replace(part, final)


def _compose(pid: str, reg: dict, ffmpeg: str) -> dict:
    folder = dp.project_path(pid)
    norm_dir = folder / "work" / "normalized"
    norm_dir.mkdir(parents=True, exist_ok=True)
    width, height = canvas_size(reg["clips"])
    files, spans, cursor = [], [], 0.0
    for clip in reg["clips"]:
        src = clips_mod.abs_path(pid, clip["file"])
        dst = norm_dir / normalized_name(clip, src, width, height)
        length = clips_mod.effective_duration(clip)
        if not dst.exists():
            _replace_via_part(dst, lambda out, c=clip, s=src, n=length: normalize_argv(
                ffmpeg, s, out, c["trim_start"], n, width, height))
        files.append(dst)
        spans.append({"id": clip["id"], "name": clip["name"],
                      "start": round(cursor, 3), "end": round(cursor + length, 3), "length": length})
        cursor += length
    keep = {f.name for f in files}
    for stale in norm_dir.iterdir():
        if stale.name not in keep:
            stale.unlink(missing_ok=True)

    list_file = folder / "work" / "concat.txt"
    list_file.write_text(concat_list_text(files), encoding="utf-8")
    _replace_via_part(folder / TIMELINE_REL, lambda out: concat_argv(ffmpeg, list_file, out))

    soundtrack_final = folder / SOUNDTRACK_REL
    soundtrack = None
    if reg["audio"]:
        srcs = [clips_mod.abs_path(pid, a["file"]) for a in reg["audio"]]
        _replace_via_part(soundtrack_final, lambda out: soundtrack_argv(ffmpeg, srcs, out))
        soundtrack = SOUNDTRACK_REL
    else:
        soundtrack_final.unlink(missing_ok=True)

    return {"duration": round(cursor, 3), "soundtrack": soundtrack,
            "clips": [{k: s[k] for k in ("id", "name", "start", "end")} for s in spans],
            "frame_times": clips_mod.frame_times([s["length"] for s in spans])}


def build(pid: str) -> str:
    with clips_mod._LOCK:
        reg = clips_mod.load(pid)
        if not reg["clips"]:
            clips_mod.set_timeline(pid, state="idle", fingerprint=None, file=None, soundtrack=None,
                                   duration=0.0, clips=[], frame_times=[], error=None)
            return "idle"
        fp = clips_mod.fingerprint(pid, reg)
    tl = reg["timeline"]
    if tl["state"] == "ready" and tl["fingerprint"] == fp and clips_mod.abs_path(pid, tl["file"]).exists():
        return "ready"

    ffmpeg = _ffmpeg()
    if not ffmpeg:
        clips_mod.set_timeline(pid, state="failed", fingerprint=fp, error="ffmpeg was not found on this machine.")
        return "failed"

    clips_mod.set_timeline(pid, state="building", fingerprint=fp, error=None)
    try:
        result = _compose(pid, reg, ffmpeg)
    except (ComposeError, OSError, subprocess.SubprocessError) as exc:
        clips_mod.set_timeline(pid, state="failed", fingerprint=fp, error=str(exc)[-400:])
        return "failed"

    try:
        with clips_mod._LOCK:
            if clips_mod.fingerprint(pid, clips_mod.load(pid)) != fp:
                return "superseded"
            clips_mod.set_timeline(pid, state="ready", fingerprint=fp, file=TIMELINE_REL, error=None, **result)
    except OSError:
        return "superseded"

    fields = {"raw": dp.project_path(pid) / TIMELINE_REL}
    if dp.get_project(pid)["stage"] == "created":
        fields["stage"] = "recorded"
    dp.update_project(pid, **fields)
    return "ready"


_STATE = threading.Lock()
_inflight: set = set()
_dirty: set = set()
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="demo-compose")


def _mark_failed(pid: str, exc: Exception) -> None:
    try:
        clips_mod.set_timeline(pid, state="failed", error=str(exc)[-400:])
    except Exception:
        log.exception("could not record the compose failure for %s", pid)


def _job(pid: str) -> None:
    while True:
        try:
            outcome = build(pid)
        except Exception as exc:
            log.exception("demo timeline build crashed for %s", pid)
            _mark_failed(pid, exc)
            outcome = "failed"
        with _STATE:
            again = outcome == "superseded" or pid in _dirty
            _dirty.discard(pid)
            if not again:
                _inflight.discard(pid)
                return


def schedule(pid: str) -> None:
    with _STATE:
        if pid in _inflight:
            _dirty.add(pid)
            return
        _inflight.add(pid)
    _EXECUTOR.submit(_job, pid)


def ensure_current(pid: str) -> None:
    reg = clips_mod.load(pid)
    if not reg["clips"]:
        return
    tl = reg["timeline"]
    try:
        fp = clips_mod.fingerprint(pid, reg)
    except OSError:
        fp = None
    if fp is not None and tl["fingerprint"] == fp:
        if tl["state"] == "failed":
            return
        if tl["state"] == "ready" and tl["file"] and clips_mod.abs_path(pid, tl["file"]).exists():
            return
    schedule(pid)
