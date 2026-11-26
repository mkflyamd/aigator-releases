"""Deterministic skill bundles: the same files always produce the same zip bytes."""

import hashlib
import io
import re
import zipfile
from pathlib import Path

from marketplace.permissions import declared_permissions, files_digest, summarize_package
from marketplace.registry import _parse_skill_md_frontmatter

from .errors import ShareError

SCHEMA = 1
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_SCRIPT_SUFFIXES = (
    ".py", ".sh", ".ps1", ".bat", ".cmd", ".exe", ".js",
    ".vbs", ".wsf", ".psm1", ".mjs", ".cjs", ".rb", ".pl", ".dll", ".jar", ".msi", ".com",
)
_SKIP_DIRS = {"__pycache__", ".git"}
_SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".kdbx")
_SHARE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_RESERVED_NAMES = {"mine"}
INVALID_NAME_MESSAGE = (
    'A shared skill name must be 1-64 lowercase letters, digits or hyphens, starting with a letter or digit, and not "mine".'
)


def valid_share_name(name) -> bool:
    return isinstance(name, str) and bool(_SHARE_NAME.fullmatch(name)) and name not in _RESERVED_NAMES


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
    summary = summarize_package(files)
    if summary["has_tools"] or summary["hooks"] or summary["bin"] or summary["mcp_servers"]:
        return True
    for path in files:
        lowered = path.lower()
        if lowered.startswith(("scripts/", "bin/")) or "/scripts/" in lowered or "/bin/" in lowered:
            return True
        if lowered.endswith(_SCRIPT_SUFFIXES):
            return True
    return False


def _skip_reason(rel: Path) -> str:
    """Why a file is never shared, or "" when it is included. The contract: regular files only, no hidden
    files or folders, no caches or version-control data, no key or certificate files."""
    parts = rel.parts
    if any(part in _SKIP_DIRS for part in parts):
        return "cache or version-control data"
    if any(part.startswith(".") for part in parts):
        return "hidden file"
    if rel.name.lower().endswith(_SECRET_SUFFIXES):
        return "key or certificate file"
    return ""


def scan_skill_dir(skill_dir: Path) -> tuple[dict[str, bytes], list[dict]]:
    """Apply the inclusion contract. Returns (files that will be shared, [{path, reason}] left out)."""
    from marketplace import github_fetcher

    files: dict[str, bytes] = {}
    skipped: list[dict] = []
    total = 0
    for item in sorted(skill_dir.rglob("*")):
        rel = item.relative_to(skill_dir)
        if item.is_symlink():
            skipped.append({"path": rel.as_posix(), "reason": "link"})
            continue
        if not item.is_file():
            continue
        reason = _skip_reason(rel)
        if reason:
            skipped.append({"path": rel.as_posix(), "reason": reason})
            continue
        data = item.read_bytes()
        total += len(data)
        if len(files) + 1 > github_fetcher.MAX_FILES or total > github_fetcher.MAX_TOTAL_BYTES:
            raise ShareError("too_large", "This skill is too large to share.")
        files[rel.as_posix()] = data
    if "SKILL.md" not in files:
        raise ShareError("invalid", "This skill has no SKILL.md, so it cannot be shared.")
    return files, skipped


def read_skill_dir(skill_dir: Path) -> dict[str, bytes]:
    return scan_skill_dir(skill_dir)[0]


def inventory(skill_dir: Path) -> dict:
    """The exact files a publish would upload, plus the digest a publish must quote to prove it matches."""
    files, skipped = scan_skill_dir(skill_dir)
    return {
        "files": [{"path": path, "size": len(files[path])} for path in sorted(files)],
        "skipped": skipped,
        "total_bytes": sum(len(data) for data in files.values()),
        "inventory_digest": files_digest(files),
    }


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
