"""Deterministic skill bundles: the same files always produce the same zip bytes."""

import hashlib
import io
import zipfile
from pathlib import Path

from marketplace.permissions import declared_permissions, files_digest
from marketplace.registry import _parse_skill_md_frontmatter

from .errors import ShareError

SCHEMA = 1
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_SCRIPT_SUFFIXES = (".py", ".sh", ".ps1", ".bat", ".cmd", ".exe", ".js")
_SKIP_DIRS = {"__pycache__", ".git"}


def build_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            zf.writestr(info, files[path])
    return buf.getvalue()


def bundle_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def has_scripts(files: dict[str, bytes]) -> bool:
    for path in files:
        if path.startswith(("scripts/", "bin/")) or "/scripts/" in path or "/bin/" in path:
            return True
        if path.lower().endswith(_SCRIPT_SUFFIXES):
            return True
    return False


def read_skill_dir(skill_dir: Path) -> dict[str, bytes]:
    from marketplace import github_fetcher

    files: dict[str, bytes] = {}
    total = 0
    for item in sorted(skill_dir.rglob("*")):
        rel = item.relative_to(skill_dir)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if item.is_symlink() or not item.is_file():
            continue
        data = item.read_bytes()
        total += len(data)
        if len(files) + 1 > github_fetcher.MAX_FILES or total > github_fetcher.MAX_TOTAL_BYTES:
            raise ShareError("too_large", "This skill is too large to share.")
        files[rel.as_posix()] = data
    if "SKILL.md" not in files:
        raise ShareError("invalid", "This skill has no SKILL.md, so it cannot be shared.")
    return files


def build_manifest(
    skill_id: str,
    version: int,
    files: dict[str, bytes],
    zip_bytes: bytes,
    *,
    author: str,
    created_at: str,
) -> dict:
    front = _parse_skill_md_frontmatter(files["SKILL.md"].decode("utf-8", errors="replace"))
    return {
        "schema": SCHEMA,
        "name": skill_id,
        "title": str(front.get("name") or skill_id),
        "description": str(front.get("description") or ""),
        "version": version,
        "author": author,
        "created_at": created_at,
        "bundle": "bundle.zip",
        "bundle_sha256": bundle_sha256(zip_bytes),
        "files_digest": files_digest(files),
        "has_scripts": has_scripts(files),
        "requested_tools": declared_permissions(files).to_dict(),
    }
