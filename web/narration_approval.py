"""Narration approval transaction: immutable, versioned approvals per demo project."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import demo_projects as dp

_LOCK = threading.Lock()
_EDGE = 65536


class ApprovalError(ValueError):
    pass


def canonical_hash(segments: list, flags: dict) -> str:
    blob = json.dumps({"segments": segments, "flags": flags}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def media_fingerprint(path) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    size = p.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with p.open("rb") as f:
        h.update(f.read(_EDGE))
        if size > _EDGE:
            f.seek(max(size - _EDGE, _EDGE))
            h.update(f.read(_EDGE))
    return h.hexdigest()


def _validate(segments, flags) -> None:
    if not isinstance(segments, list) or not segments:
        raise ApprovalError("segments must be a non-empty list")
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict) or not isinstance(seg.get("text"), str):
            raise ApprovalError(f"segment {i} needs a text string")
    if not isinstance(flags, dict):
        raise ApprovalError("flags must be an object")


def _write_legacy_mirror(segments: list, flags: dict, approved_at: str) -> None:
    try:
        dp.atomic_write_json(dp.INDEX_PATH.parent / "narration_pending.json",
                             {"segments": segments, "flags": flags, "timestamp": approved_at})
    except OSError:
        pass


def approve(project_id: str, segments: list, flags: dict) -> dict:
    _validate(segments, flags)
    sha = canonical_hash(segments, flags)
    with _LOCK:
        project = dp.get_project(project_id)
        root = Path(project["path"])
        fingerprint = media_fingerprint(project.get("raw"))
        current = (project.get("ext") or {}).get("approval") or {}
        approvals = root / "work" / "approvals"
        reusable = (
            current.get("current_id")
            and current.get("sha256") == sha
            and current.get("media_fingerprint") == fingerprint
            and (approvals / f"{current['current_id']}.json").is_file()
        )
        if reusable:
            reused = True
            version = current["version"]
            approval_id = current["current_id"]
            approved_at = current["approved_at"]
        else:
            reused = False
            version = int(current.get("version") or 0) + 1
            approval_id = f"appr_{version}_{sha[:8]}"
            approved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            approvals.mkdir(parents=True, exist_ok=True)
            dp.atomic_write_json(approvals / f"{approval_id}.json", {
                "approval_id": approval_id, "version": version, "project_id": project_id,
                "approved_at": approved_at, "segments": segments, "flags": flags,
                "sha256": sha, "media_fingerprint": fingerprint,
            })
            dp.atomic_write_json(root / "work" / "narration.json", {
                "segments": segments, "flags": flags, "timestamp": approved_at,
                "approval_id": approval_id, "version": version,
            })
            dp.update_project(project_id, stage="narration_approved",
                              narration={"approved_at": approved_at})
            dp.set_ext(project_id, "approval", {
                "current_id": approval_id, "version": version, "sha256": sha,
                "approved_at": approved_at, "media_fingerprint": fingerprint,
            })
    _write_legacy_mirror(segments, flags, approved_at)
    result = dp.get_project(project_id)
    result["approval"] = {
        "approval_id": approval_id, "version": version, "approved_at": approved_at,
        "sha256": sha, "segment_count": len(segments), "reused": reused,
    }
    return result
