#!/usr/bin/env python3
"""Load and verify the current narration approval for a demo project. Standard library only."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

_EDGE = 65536


class ApprovalError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def canonical_hash(segments, flags):
    blob = json.dumps({"segments": segments, "flags": flags}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def media_fingerprint(path):
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


def _read_json(path, code, message):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ApprovalError(code, message) from None


def load(project_dir, approval_id=None):
    root = Path(project_dir)
    project = _read_json(root / "project.json", "missing", "project.json not found or unreadable")
    ext = (project.get("ext") or {}).get("approval")
    if not ext or not ext.get("current_id"):
        raise ApprovalError("missing", "no narration approval is recorded for this project")
    current = ext["current_id"]
    if approval_id and approval_id != current:
        raise ApprovalError("superseded", f"approval {approval_id} was replaced by {current}")
    record = _read_json(root / "work" / "approvals" / f"{current}.json", "corrupt",
                        f"approval record {current} is missing or unreadable")
    segments, flags = record.get("segments"), record.get("flags")
    if (not isinstance(segments, list) or not isinstance(flags, dict)
            or canonical_hash(segments, flags) != record.get("sha256")):
        raise ApprovalError("corrupt", f"approval record {current} failed its integrity check")
    raw = project.get("raw")
    if media_fingerprint(root / raw if raw else None) != record.get("media_fingerprint"):
        raise ApprovalError("stale_media",
                            "the recording changed after this approval; approve the narration again")
    return record


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--approval-id")
    ap.add_argument("--segments-out")
    args = ap.parse_args(argv)
    try:
        record = load(args.project_dir, args.approval_id)
    except ApprovalError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "error": str(exc)}))
        return 2
    if args.segments_out:
        out = Path(args.segments_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record["segments"], ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "ok": True, "approval_id": record["approval_id"], "version": record["version"],
        "approved_at": record["approved_at"], "segment_count": len(record["segments"]),
        "flags": record["flags"], "segments_out": args.segments_out,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
