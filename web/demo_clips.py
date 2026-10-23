"""Clip registry for multi-clip demo projects, stored in project.json ext["clips"]."""

import copy
import hashlib
import json
import os
import re
import threading
from pathlib import Path

import demo_projects as dp
from demo_media_probe import MAX_AUDIO_ASSETS, MAX_VIDEO_CLIPS

NAMESPACE = "clips"
SPEC_VERSION = 1
MAX_FRAMES = 8
MIN_FRAME_GAP = 5.0
MIN_CLIP_SECONDS = 0.5
LOCKED_STAGES = ("narration_approved", "delivered")

_LOCK = threading.RLock()


class ClipError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def safe_name(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(str(name)).name)
    stem, ext = os.path.splitext(base)
    return stem[: max(1, 80 - len(ext))] + ext


def _blank() -> dict:
    return {
        "version": SPEC_VERSION, "next_id": 1, "clips": [], "audio": [],
        "timeline": {"state": "idle", "fingerprint": None, "file": None, "soundtrack": None,
                     "duration": 0.0, "clips": [], "frame_times": [], "error": None},
    }


def load(pid: str) -> dict:
    stored = dp.get_project(pid).get("ext", {}).get(NAMESPACE)
    return copy.deepcopy(stored) if stored else _blank()


def abs_path(pid: str, rel: str) -> Path:
    return dp.project_path(pid) / rel


def _assert_unlocked(pid: str) -> None:
    if dp.get_project(pid)["stage"] in LOCKED_STAGES:
        raise ClipError("project_locked", "This demo's narration is already approved. Start a new demo to change clips.")


def _find(reg: dict, item_id: str):
    for bucket in ("clips", "audio"):
        for index, item in enumerate(reg[bucket]):
            if item["id"] == item_id:
                return bucket, index
    raise ClipError("not_found", "No such clip or audio file in this project.")


def add_item(pid: str, tmp_path: Path, original_name: str, probe: dict) -> dict:
    with _LOCK:
        _assert_unlocked(pid)
        reg = load(pid)
        is_video = probe["kind"] == "video"
        bucket = reg["clips" if is_video else "audio"]
        limit = MAX_VIDEO_CLIPS if is_video else MAX_AUDIO_ASSETS
        if len(bucket) >= limit:
            raise ClipError("too_many", f"At most {limit} {'video clips' if is_video else 'audio files'} per demo.")
        item_id = f"{'c' if is_video else 'a'}{reg['next_id']}"
        reg["next_id"] += 1
        rel = f"source/{item_id}_{safe_name(original_name)}"
        dest = abs_path(pid, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_path, dest)
        item = {"id": item_id, "name": Path(original_name).name, "file": rel, "duration": probe["duration"]}
        if is_video:
            item.update(width=probe["width"], height=probe["height"], has_audio=probe["has_audio"],
                        trim_start=0.0, trim_end=None)
        bucket.append(item)
        dp.set_ext(pid, NAMESPACE, reg)
        return item


def remove_item(pid: str, item_id: str) -> None:
    with _LOCK:
        _assert_unlocked(pid)
        reg = load(pid)
        bucket, index = _find(reg, item_id)
        item = reg[bucket].pop(index)
        abs_path(pid, item["file"]).unlink(missing_ok=True)
        dp.set_ext(pid, NAMESPACE, reg)


def reorder(pid: str, ids: list) -> None:
    with _LOCK:
        _assert_unlocked(pid)
        reg = load(pid)
        current = [c["id"] for c in reg["clips"]]
        if len(ids) != len(current) or set(ids) != set(current):
            raise ClipError("bad_order", "The order must list every clip exactly once.")
        by_id = {c["id"]: c for c in reg["clips"]}
        reg["clips"] = [by_id[i] for i in ids]
        dp.set_ext(pid, NAMESPACE, reg)


def effective_duration(clip: dict) -> float:
    end = clip["duration"] if clip["trim_end"] is None else clip["trim_end"]
    return max(0.0, end - clip["trim_start"])


def set_trim(pid: str, clip_id: str, start: float, end: float | None) -> None:
    with _LOCK:
        _assert_unlocked(pid)
        reg = load(pid)
        bucket, index = _find(reg, clip_id)
        if bucket != "clips":
            raise ClipError("not_found", "Only video clips can be trimmed.")
        clip = reg["clips"][index]
        effective_end = clip["duration"] if end is None else end
        if start < 0 or effective_end > clip["duration"] + 0.001 or effective_end - start < MIN_CLIP_SECONDS:
            raise ClipError("bad_trim", f"Pick a range inside 0-{clip['duration']:.1f}s, at least {MIN_CLIP_SECONDS}s long.")
        clip["trim_start"] = round(float(start), 3)
        clip["trim_end"] = None if end is None else round(float(end), 3)
        dp.set_ext(pid, NAMESPACE, reg)


def set_timeline(pid: str, **fields) -> dict:
    with _LOCK:
        reg = load(pid)
        reg["timeline"].update(fields)
        dp.set_ext(pid, NAMESPACE, reg)
        return reg


def fingerprint(pid: str, reg: dict) -> str:
    parts: list = [SPEC_VERSION]
    for clip in reg["clips"]:
        stat = abs_path(pid, clip["file"]).stat()
        parts.append([clip["id"], stat.st_size, stat.st_mtime_ns, clip["trim_start"], clip["trim_end"]])
    for audio in reg["audio"]:
        stat = abs_path(pid, audio["file"]).stat()
        parts.append(["audio", audio["id"], stat.st_size, stat.st_mtime_ns])
    return hashlib.sha1(json.dumps(parts).encode("utf-8"), usedforsecurity=False).hexdigest()


def frame_times(durations: list) -> list:
    total = sum(durations)
    if total <= 0:
        return []
    count = min(MAX_FRAMES, max(1, int(total // MIN_FRAME_GAP)))
    return [round((i + 0.5) * total / count, 3) for i in range(count)]
