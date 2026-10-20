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

# ── project helpers, media ext, ledger ───────────────────────────────────────

def project_for(project_id: str | None) -> tuple[str, Path]:
    pid = project_id or dp.get_active_id()
    if not pid:
        raise MediaError("no_project", "No active demo project. Record or open a demo first.")
    try:
        return pid, Path(dp.get_project(pid)["path"])
    except KeyError:
        raise MediaError("project_not_found", f"Unknown demo project {pid}.", project_id=pid) from None


def project_file(pid: str, rel: str) -> Path:
    try:
        path = dp.resolve_file(pid, rel)
    except ValueError:
        raise MediaError("path_outside_project", f"{rel} is outside the project folder.", rel=rel) from None
    if not path.is_file():
        raise MediaError("file_not_found", f"{rel} does not exist in the project.", rel=rel)
    return path


def rel_of(folder: Path, path: Path) -> str:
    return path.resolve().relative_to(folder.resolve()).as_posix()


def read_media(pid: str) -> dict:
    return dict((dp.get_project(pid).get("ext") or {}).get("media") or {})


def update_media(pid: str, mutate) -> dict:
    with _EXT_LOCK:
        media = read_media(pid)
        mutate(media)
        dp.set_ext(pid, "media", media)
        return media


def raw_rel(pid: str, folder: Path) -> str | None:
    raw = dp.get_project(pid).get("raw")
    return rel_of(folder, Path(raw)) if raw else None


def current_rel(pid: str, folder: Path) -> str | None:
    media, raw = read_media(pid), raw_rel(pid, folder)
    if media.get("current") and media.get("current_base") == raw:
        return media["current"]
    return raw


def set_current(pid: str, folder: Path, rel: str) -> None:
    raw = raw_rel(pid, folder)
    update_media(pid, lambda m: m.update(current=rel, current_base=raw))


def record_op(pid: str, folder: Path, entry: dict) -> dict:
    entry = {"op_id": uuid.uuid4().hex[:8], "at": _now(), **entry}
    ledger = folder / "work" / "logs" / "media_ops.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with _EXT_LOCK:
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def mutate(media: dict) -> None:
        ops = media.setdefault("ops", [])
        ops.append(entry)
        del ops[:-MAX_LEDGER_SUMMARIES]

    update_media(pid, mutate)
    return entry


def _next_path(folder: Path, sub: str, stem: str, suffix: str) -> Path:
    target = folder / "work" / sub
    target.mkdir(parents=True, exist_ok=True)
    n = 1
    while (target / f"{stem}_{n:03d}{suffix}").exists():
        n += 1
    return target / f"{stem}_{n:03d}{suffix}"


def _finish(partial: Path, out: Path, expected_sec: float) -> MediaInfo:
    info = probe(partial)
    if abs(info.duration_sec - expected_sec) > max(DURATION_TOL, 2 / max(info.fps, 1.0)):
        partial.unlink(missing_ok=True)
        raise MediaError(
            "output_verification_failed",
            f"Output is {info.duration_sec:.2f}s but {expected_sec:.2f}s was expected; it was discarded.",
            actual_sec=round(info.duration_sec, 3), expected_sec=round(expected_sec, 3),
        )
    os.replace(partial, out)
    return probe(out)


def _partial(out: Path) -> Path:
    return out.with_name(out.stem + ".partial" + out.suffix)


def _out_block(folder: Path, out: Path, info: MediaInfo) -> dict:
    return {"rel": rel_of(folder, out), "path": str(out), "duration_sec": round(info.duration_sec, 3)}

# ── manifest ─────────────────────────────────────────────────────────────────

def manifest(project_id: str | None = None) -> dict:
    with _OP_LOCK:
        pid, folder = project_for(project_id)
        files, seen = [], set()
        for sub in ("source", "work/normalized", "work/edits", "final"):
            for path in sorted((folder / sub).glob("*")) if (folder / sub).is_dir() else []:
                if not path.is_file() or path.suffix.lower() not in MEDIA_SUFFIXES or ".partial." in path.name:
                    continue
                rel = rel_of(folder, path)
                if rel in seen:
                    continue
                seen.add(rel)
                try:
                    files.append({"rel": rel, **probe(path).to_dict()})
                except MediaError as exc:
                    files.append({"rel": rel, "error": exc.code})
        current = current_rel(pid, folder)
        stamp = _now()
        update_media(pid, lambda m: m.update(manifest={"generated_at": stamp, "files": files}))
        return {"ok": True, "project_id": pid, "current": current, "files": files, "generated_at": stamp}

# ── frames ───────────────────────────────────────────────────────────────────

def inspect_frames(project_id: str | None, source_rel: str, times_sec: list) -> dict:
    with _OP_LOCK:
        pid, folder = project_for(project_id)
        if not isinstance(times_sec, list) or not times_sec:
            raise MediaError("bad_argument", "times_sec must be a non-empty list of seconds.", field="times_sec")
        if len(times_sec) > MAX_FRAMES:
            raise MediaError("too_many_frames", f"At most {MAX_FRAMES} frames per call.", max_frames=MAX_FRAMES)
        src = project_file(pid, source_rel)
        info = probe(src)
        if not info.has_video:
            raise MediaError("no_video", f"{source_rel} has no video stream.", rel=source_rel)
        times, rejected = [], []
        for value in times_sec:
            try:
                times.append(check_time(value, info.duration_sec, field="times_sec", rel=source_rel))
            except MediaError as exc:
                if exc.code != "out_of_range":
                    raise
                rejected.append({"requested_sec": exc.detail["requested_sec"]})
        if rejected:
            raise MediaError(
                "out_of_range",
                f"Requested times {[r['requested_sec'] for r in rejected]} are outside {source_rel}, "
                f"which is {info.duration_sec:.1f}s long. No frames were extracted.",
                file=source_rel, duration_sec=round(info.duration_sec, 3),
                valid_range_sec=[0, round(info.duration_sec, 3)], rejected=rejected, options=list(_OPTIONS),
            )
        frames_dir = folder / "work" / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        frames = []
        for t in times:
            out = frames_dir / f"{src.stem}_{t:.2f}s.png"
            out.unlink(missing_ok=True)
            _ffmpeg(["-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", str(out)])
            if not out.is_file() or out.stat().st_size == 0:
                raise MediaError("frame_not_extracted", f"No frame could be read at {t:g}s in {source_rel}.",
                                 requested_sec=t, file=source_rel)
            frames.append({"time_sec": t, "rel": rel_of(folder, out), "path": str(out),
                           "bytes": out.stat().st_size})
        op = record_op(pid, folder, {
            "operation": "inspect_frames", "source": {"rel": source_rel, "duration_sec": round(info.duration_sec, 3)},
            "times_sec": times, "frames": [f["rel"] for f in frames],
        })
        return {"ok": True, "operation": "inspect_frames", "source": source_rel,
                "duration_sec": round(info.duration_sec, 3), "frames": frames, "op_id": op["op_id"]}

# ── splice (replace interval, append clip) ───────────────────────────────────

def _assemble(inputs: list[Path], pieces: list[tuple[int, float, float]], info: MediaInfo, out: Path) -> None:
    chains, labels = [], []
    for n, (idx, a, b) in enumerate(pieces):
        chains.append(
            f"[{idx}:v]trim=start={a:.6f}:end={b:.6f},setpts=PTS-STARTPTS,"
            f"scale={info.width}:{info.height}:force_original_aspect_ratio=decrease,"
            f"pad={info.width}:{info.height}:(ow-iw)/2:(oh-ih)/2,fps={info.fps_expr},setsar=1,format=yuv420p[p{n}]"
        )
        labels.append(f"[p{n}]")
    chains.append("".join(labels) + f"concat=n={len(pieces)}:v=1:a=0[v]")
    args: list[str] = []
    for path in inputs:
        args += ["-i", str(path)]
    args += ["-filter_complex", ";".join(chains), "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "20", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(out)]
    _ffmpeg(args)


def _edit_base(pid: str, folder: Path, base_rel: str | None) -> tuple[str, Path, MediaInfo]:
    rel = base_rel or current_rel(pid, folder)
    if not rel:
        raise MediaError("no_video", "The project has no recording to edit yet.")
    path = project_file(pid, rel)
    info = probe(path)
    if not info.has_video:
        raise MediaError("no_video", f"{rel} has no video stream.", rel=rel)
    if info.has_audio:
        raise MediaError(
            "base_has_audio",
            f"{rel} already has an audio track. Edit the silent recording, then run demo_merge_narration again.",
            rel=rel,
        )
    return rel, path, info


def replace_interval(project_id: str | None, start_sec, end_sec, insert_rel: str,
                     insert_start_sec=0.0, base_rel: str | None = None) -> dict:
    with _OP_LOCK:
        pid, folder = project_for(project_id)
        base_rel, base, binfo = _edit_base(pid, folder, base_rel)
        ins = project_file(pid, insert_rel)
        iinfo = probe(ins)
        if not iinfo.has_video:
            raise MediaError("no_video", f"{insert_rel} has no video stream.", rel=insert_rel)
        s, e = check_interval(start_sec, end_sec, binfo.duration_sec, rel=base_rel)
        length = e - s
        i_start = check_time(insert_start_sec, iinfo.duration_sec, field="insert_start_sec", rel=insert_rel)
        if i_start + length > iinfo.duration_sec + EPS:
            raise MediaError(
                "out_of_range",
                f"{insert_rel} is {iinfo.duration_sec:.1f}s long; {length:.1f}s from {i_start:g}s needs "
                f"{i_start + length:.1f}s.",
                field="insert_start_sec", requested_sec=i_start, duration_sec=round(iinfo.duration_sec, 3),
                needed_sec=round(i_start + length, 3), file=insert_rel, options=list(_OPTIONS),
            )
        i_end = min(i_start + length, iinfo.duration_sec)
        pieces: list[tuple[int, float, float]] = []
        if s > EPS:
            pieces.append((0, 0.0, s))
        pieces.append((1, i_start, i_end))
        if e < binfo.duration_sec - EPS:
            pieces.append((0, e, binfo.duration_sec))
        expected = sum(b - a for _, a, b in pieces)
        out = _next_path(folder, "edits", "edit", ".mp4")
        partial = _partial(out)
        try:
            _assemble([base, ins], pieces, binfo, partial)
            oinfo = _finish(partial, out, expected)
        finally:
            partial.unlink(missing_ok=True)
        block = _out_block(folder, out, oinfo)
        op = record_op(pid, folder, {
            "operation": "replace_interval",
            "base": {"rel": base_rel, "duration_sec": round(binfo.duration_sec, 3)},
            "replaced_interval_sec": [round(s, 3), round(e, 3)],
            "inserted_from": {"rel": insert_rel, "interval_sec": [round(i_start, 3), round(i_end, 3)],
                              "source_duration_sec": round(iinfo.duration_sec, 3)},
            "inserted_audio_dropped": iinfo.has_audio,
            "output": block,
        })
        set_current(pid, folder, block["rel"])
        return {
            "ok": True, "operation": "replace_interval", "output": block,
            "base": {"rel": base_rel, "duration_sec": round(binfo.duration_sec, 3)},
            "replaced_interval_sec": [round(s, 3), round(e, 3)],
            "inserted_from": {"rel": insert_rel, "interval_sec": [round(i_start, 3), round(i_end, 3)]},
            "inserted_audio_dropped": iinfo.has_audio,
            "timeline_shifted": False, "op_id": op["op_id"],
        }


def append_clip(project_id: str | None, clip_rel: str, clip_start_sec=0.0, clip_end_sec=None,
                base_rel: str | None = None) -> dict:
    with _OP_LOCK:
        pid, folder = project_for(project_id)
        base_rel, base, binfo = _edit_base(pid, folder, base_rel)
        clip = project_file(pid, clip_rel)
        cinfo = probe(clip)
        if not cinfo.has_video:
            raise MediaError("no_video", f"{clip_rel} has no video stream.", rel=clip_rel)
        c_start, c_end = check_interval(
            clip_start_sec, cinfo.duration_sec if clip_end_sec is None else clip_end_sec,
            cinfo.duration_sec, rel=clip_rel,
        )
        pieces = [(0, 0.0, binfo.duration_sec), (1, c_start, c_end)]
        expected = binfo.duration_sec + (c_end - c_start)
        out = _next_path(folder, "edits", "edit", ".mp4")
        partial = _partial(out)
        try:
            _assemble([base, clip], pieces, binfo, partial)
            oinfo = _finish(partial, out, expected)
        finally:
            partial.unlink(missing_ok=True)
        block = _out_block(folder, out, oinfo)
        appended = {"rel": clip_rel, "interval_sec": [round(c_start, 3), round(c_end, 3)]}
        op = record_op(pid, folder, {
            "operation": "append_clip",
            "base": {"rel": base_rel, "duration_sec": round(binfo.duration_sec, 3)},
            "appended_from": appended, "appended_at_sec": round(binfo.duration_sec, 3),
            "inserted_audio_dropped": cinfo.has_audio, "output": block,
        })
        set_current(pid, folder, block["rel"])
        return {
            "ok": True, "operation": "append_clip", "output": block,
            "base": {"rel": base_rel, "duration_sec": round(binfo.duration_sec, 3)},
            "appended_from": appended, "appended_at_sec": round(binfo.duration_sec, 3),
            "inserted_audio_dropped": cinfo.has_audio, "timeline_shifted": False, "op_id": op["op_id"],
        }

# ── intro (hold first frame / title card) ────────────────────────────────────

def normalize_intro(intro: dict | None) -> dict:
    intro = intro or {}
    mode = intro.get("mode") or "none"
    if mode not in INTRO_MODES:
        raise MediaError("bad_argument", f"intro mode must be one of {list(INTRO_MODES)}.", field="intro_mode")
    if mode == "none":
        return {"mode": "none", "duration_sec": 0.0, "title": ""}
    raw = intro.get("duration_sec")
    duration = INTRO_DEFAULT_SEC if raw is None else _number(raw, "intro_duration_sec")
    if not INTRO_MIN_SEC <= duration <= INTRO_MAX_SEC:
        raise MediaError("bad_argument", f"intro duration must be {INTRO_MIN_SEC}-{INTRO_MAX_SEC} seconds.",
                         field="intro_duration_sec")
    title = str(intro.get("title") or "").strip()
    if len(title) > INTRO_TITLE_MAX:
        raise MediaError("bad_argument", f"intro title is limited to {INTRO_TITLE_MAX} characters.",
                         field="intro_title")
    if mode == "card" and not title:
        raise MediaError("bad_argument", "A title card needs a title.", field="intro_title")
    return {"mode": mode, "duration_sec": round(duration, 3), "title": title}


def _find_font() -> str:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise MediaError("font_missing", "No system font was found to draw the title. Use 'hold' without a title.")


def make_intro_video(project_id: str | None, video_rel: str, intro: dict) -> dict:
    with _OP_LOCK:
        pid, folder = project_for(project_id)
        intro = normalize_intro(intro)
        if intro["mode"] == "none":
            raise MediaError("bad_argument", "intro mode 'none' has nothing to render.", field="intro_mode")
        src = project_file(pid, video_rel)
        info = probe(src)
        if not info.has_video:
            raise MediaError("no_video", f"{video_rel} has no video stream.", rel=video_rel)
        d = intro["duration_sec"]
        if intro["mode"] == "card":
            pad = f"tpad=start_mode=add:start_duration={d}:color=0x111827"
        else:
            pad = f"tpad=start_mode=clone:start_duration={d}"
        chain = [pad]
        out = _next_path(folder, "edits", "intro", ".mp4")
        partial = _partial(out)
        title_file = out.parent / "intro_title.txt"
        font_file = out.parent / "intro_font.ttf"
        if intro["title"]:
            title_file.write_text(intro["title"], encoding="utf-8")
            shutil.copyfile(_find_font(), font_file)
            size = max(14, min(info.height // 14, int(info.width * 0.9 / (0.55 * len(intro["title"])))))
            chain.append(
                "drawtext=fontfile=intro_font.ttf:textfile=intro_title.txt:expansion=none:"
                f"fontcolor=white:fontsize={size}:borderw=2:bordercolor=black:"
                f"x=(w-text_w)/2:y=(h-text_h)/2:enable=lt(t\\,{d})"
            )
        chain.append("format=yuv420p")
        try:
            _ffmpeg(["-i", str(src), "-vf", ",".join(chain), "-c:v", "libx264", "-preset", "veryfast",
                     "-crf", "20", "-an", "-movflags", "+faststart", str(partial)], cwd=out.parent)
            oinfo = _finish(partial, out, info.duration_sec + d)
        finally:
            partial.unlink(missing_ok=True)
            title_file.unlink(missing_ok=True)
            font_file.unlink(missing_ok=True)
        block = _out_block(folder, out, oinfo)
        op = record_op(pid, folder, {
            "operation": "intro", "source": {"rel": video_rel, "duration_sec": round(info.duration_sec, 3)},
            "intro": intro, "output": block,
        })
        return {"ok": True, "operation": "intro", "intro": intro, "output": block,
                "source": {"rel": video_rel, "duration_sec": round(info.duration_sec, 3)},
                "offset_sec": d, "op_id": op["op_id"]}

# ── narration timeline and merge ─────────────────────────────────────────────

def build_timeline(segments: list, source_duration: float, intro: dict | None) -> dict:
    intro = normalize_intro(intro)
    offset = intro["duration_sec"]
    out, previous = [], 0.0
    for i, seg in enumerate(segments or []):
        text = str((seg or {}).get("text") or "").strip()
        if not text:
            raise MediaError("bad_argument", f"Narration segment {i} has no text.", field=f"segments[{i}].text")
        start = (seg or {}).get("start_at", (seg or {}).get("start"))
        if start is None:
            raise MediaError("bad_argument", f"Narration segment {i} has no start time.", field=f"segments[{i}].start_at")
        start = _number(start, f"segments[{i}].start_at")
        if start < 0 or start > source_duration:
            raise MediaError(
                "out_of_range",
                f"Narration segment {i} starts at {start:g}s but the recording is {source_duration:.1f}s long.",
                field=f"segments[{i}].start_at", requested_sec=start, duration_sec=round(source_duration, 3),
                valid_range_sec=[0, round(source_duration, 3)], options=list(_OPTIONS),
            )
        if start < previous:
            raise MediaError("bad_argument", "Narration start times must not decrease.", field=f"segments[{i}].start_at")
        previous = start
        out.append({**seg, "text": text, "start_at": start, "final_start_at": round(start + offset, 3)})
    if not out:
        raise MediaError("bad_argument", "There is no approved narration to merge.", field="segments")
    return {"intro": intro, "offset_sec": offset, "source_duration_sec": round(source_duration, 3), "segments": out}


def load_approved_narration(pid: str, folder: Path, approval_id: str | None = None) -> dict:
    approval = (dp.get_project(pid).get("ext") or {}).get("approval") or {}
    current = approval.get("current_id")
    if not current:
        raise MediaError("narration_not_approved", "No approved narration was found. Ask the user to approve it.")
    if approval_id and approval_id != current:
        raise MediaError("approval_superseded", "A newer narration approval exists; stop and let its turn handle it.",
                         requested=approval_id, current=current)
    if not re.fullmatch(r"appr_\d+_[0-9a-f]{8}", str(current)):
        raise MediaError("approval_corrupt", "The approval id is malformed.")
    try:
        record = json.loads((folder / "work" / "approvals" / f"{current}.json").read_text(encoding="utf-8"))
        digest = narration_approval.canonical_hash(record["segments"], record["flags"])
    except (OSError, ValueError, KeyError, TypeError):
        raise MediaError("approval_corrupt", "The approval record is unreadable. Ask the user to approve again.") from None
    if digest != approval.get("sha256"):
        raise MediaError("approval_corrupt", "The approval record does not match its hash. Ask the user to approve again.")
    expected = approval.get("media_fingerprint")
    if expected and narration_approval.media_fingerprint(narration_approval.pinned_media(dp.get_project(pid))) != expected:
        raise MediaError("approval_stale_media", "The recording changed after the narration was approved. Ask the user to approve again.")
    return record


# ---------------------------------------------------------------------------
# Merge narration
# ---------------------------------------------------------------------------

def _write_progress(folder: Path, approval_id: str, state: str, stage: str, message: str,
                    step: int = 0, total: int = 0, error: str | None = None) -> None:
    path = folder / "work" / "logs" / "merge_progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    dp.atomic_write_json(path, {
        "approval_id": approval_id, "state": state, "stage": stage, "step": step, "total": total,
        "message": message, "error": error, "updated_at": _now(),
    })


def _run_tts_pipeline(video: Path, timeline_file: Path, narration_file: Path, out: Path,
                      work_dir: Path, voice: str, soundtrack: Path | None = None) -> None:
    cmd = [sys.executable, str(TTS_SCRIPT), "--video", str(video), "--timeline", str(timeline_file),
           "--narration", str(narration_file), "--output", str(out), "--work-dir", str(work_dir),
           "--voice", voice]
    progress = work_dir.parent / "logs" / "merge_progress.json"
    try:
        approval_id = json.loads(progress.read_text(encoding="utf-8")).get("approval_id")
    except (OSError, ValueError, AttributeError):
        approval_id = None
    if approval_id:
        cmd += ["--progress-file", str(progress), "--approval-id", str(approval_id)]
    if soundtrack:
        cmd += ["--soundtrack", str(soundtrack)]
    result = _run(cmd, timeout=900)
    if result.returncode != 0 or not out.is_file():
        raise MediaError("tts_failed", "Narration generation or merge failed.",
                         stderr_tail=((result.stderr or "") + (result.stdout or ""))[-600:])


def _intro_request(intro_mode, intro_duration_sec, intro_title, flags: dict) -> tuple[dict, str]:
    if intro_mode:
        return {"mode": intro_mode, "duration_sec": intro_duration_sec, "title": intro_title}, "tool_argument"
    return {"mode": flags.get("intro_mode"), "duration_sec": flags.get("intro_duration_sec"),
            "title": flags.get("intro_title")}, "approved_flags"


def _soundtrack(pid: str, folder: Path) -> Path | None:
    timeline = ((dp.get_project(pid).get("ext") or {}).get("clips") or {}).get("timeline") or {}
    rel = timeline.get("soundtrack")
    if timeline.get("state") != "ready" or not rel:
        return None
    path = folder / rel
    return path if path.is_file() else None


def merge_narration(project_id: str | None = None, video_rel: str | None = None, intro_mode: str | None = None,
                    intro_duration_sec=None, intro_title: str | None = None, voice: str | None = None,
                    approval_id: str | None = None) -> dict:
    with _OP_LOCK:
        pid, folder = project_for(project_id)
        approved = load_approved_narration(pid, folder, approval_id)
        aid = approved["approval_id"]
        segments = approved.get("segments") or []
        total = len(segments)
        try:
            _write_progress(folder, aid, "running", "tts", f"Generating narration ({total} segments)...", 0, total)
            result = _merge(pid, folder, approved, video_rel, intro_mode, intro_duration_sec, intro_title, voice)
        except MediaError as exc:
            _write_progress(folder, aid, "failed", "done", str(exc), error=str(exc))
            raise
        except Exception as exc:
            _write_progress(folder, aid, "failed", "done", "Generation failed.", error=str(exc))
            raise
        _write_progress(folder, aid, "done", "done", "Done - your demo video is ready.", total, total)
        return result


def _merge(pid: str, folder: Path, approved: dict, video_rel, intro_mode, intro_duration_sec,
           intro_title, voice) -> dict:
    segments = approved.get("segments") or []
    intro_raw, intro_source = _intro_request(intro_mode, intro_duration_sec, intro_title,
                                             approved.get("flags") or {})
    voice = voice or (segments[0].get("voice") if segments else None) or "af_heart"
    if not re.fullmatch(r"[A-Za-z0-9_]{1,40}", voice):
        raise MediaError("bad_argument", "voice must be letters, digits or underscores.", field="voice")
    rel = video_rel or current_rel(pid, folder)
    if not rel:
        raise MediaError("no_video", "The project has no recording to merge narration into.")
    src = project_file(pid, rel)
    sinfo = probe(src)
    if not sinfo.has_video:
        raise MediaError("no_video", f"{rel} has no video stream.", rel=rel)
    timeline = build_timeline(segments, sinfo.duration_sec, intro_raw)
    intro = timeline["intro"]
    video, video_info = src, sinfo
    if intro["mode"] != "none":
        video = project_file(pid, make_intro_video(pid, rel, intro)["output"]["rel"])
        video_info = probe(video)
    work = folder / "work"
    (work / "out").mkdir(parents=True, exist_ok=True)
    timeline_file, narration_file = work / "timeline.json", work / "narration_final.json"
    dp.atomic_write_json(timeline_file, timeline)
    dp.atomic_write_json(narration_file, [{**s, "start_at": s["final_start_at"]} for s in timeline["segments"]])
    candidate = work / "out" / "final_candidate.mp4"
    candidate.unlink(missing_ok=True)
    _run_tts_pipeline(video, timeline_file, narration_file, candidate, work / "tts", voice, _soundtrack(pid, folder))
    oinfo = probe(candidate)
    if not (oinfo.has_video and oinfo.has_audio):
        raise MediaError("output_verification_failed", "The merged file is missing its video or audio stream.",
                         candidate=str(candidate))
    v_sec = oinfo.video_duration_sec or oinfo.duration_sec
    a_sec = oinfo.audio_duration_sec or oinfo.duration_sec
    if abs(v_sec - a_sec) > SYNC_TOL:
        raise MediaError(
            "sync_mismatch", f"Video is {v_sec:.1f}s but audio is {a_sec:.1f}s; the file was not delivered.",
            video_stream_sec=round(v_sec, 3), audio_stream_sec=round(a_sec, 3), candidate=str(candidate),
        )
    version = int(read_media(pid).get("output_version", 0)) + 1
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", dp.get_project(pid).get("name") or pid).strip("_") or pid
    dp.archive_final(pid)
    final_path = folder / "final" / f"{safe}_v{version}.mp4"
    os.replace(candidate, final_path)
    block = {**_out_block(folder, final_path, probe(final_path)), "version": version}
    extended = round(max(0.0, v_sec - video_info.duration_sec), 3)
    narration = {"segments": len(segments), "offset_sec": timeline["offset_sec"],
                 "first_start_sec": timeline["segments"][0]["final_start_at"]}
    op = record_op(pid, folder, {
        "operation": "merge_narration", "approval_id": approved["approval_id"],
        "video": {"rel": rel, "duration_sec": round(sinfo.duration_sec, 3)},
        "intro": intro, "intro_source": intro_source, "narration": narration,
        "video_extended_by_sec": extended, "video_stream_sec": round(v_sec, 3),
        "audio_stream_sec": round(a_sec, 3), "output": block,
    })
    update_media(pid, lambda m: m.update(output_version=version))
    return {
        "ok": True, "operation": "merge_narration", "output": block,
        "video": {"rel": rel, "duration_sec": round(sinfo.duration_sec, 3)},
        "intro": {**intro, "applied": intro["mode"] != "none", "source": intro_source},
        "narration": narration, "video_extended_by_sec": extended,
        "video_stream_sec": round(v_sec, 3), "audio_stream_sec": round(a_sec, 3),
        "sync_ok": True, "approval_id": approved["approval_id"], "op_id": op["op_id"],
    }
