"""File operations skill — read, write, list, glob, grep local files."""

import base64
import fnmatch
import glob as _glob
import mimetypes
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from sandbox.paths import PROTECTED_MSG, is_secrets_path

SKILL_ID = "file_ops"

_MAX_READ_BYTES = 5 * 1024 * 1024  # 5 MB
_MAX_GLOB = 200
_MAX_GREP = 100
# glob_files always does a recursive descent from base_path under the hood
# (both branches below inject/require a literal "**" in the final pattern),
# and glob.glob(recursive=True) has no built-in bound — it fully walks the
# tree before returning anything. A generic skill's instructions once told
# the model to search from a nonexistent "/skills" path, which resolved to
# a filesystem root and triggered a multi-minute (apparent hang) full-disk
# scan. _GLOB_TIME_BUDGET_SECONDS/_GLOB_DIR_CAP bound the common case (no
# path separator in `pattern`) via our own os.walk instead of glob.glob, so
# the time check runs once per directory visited — not once per match,
# which would never fire at all for a huge tree with zero/few matches.
_GLOB_TIME_BUDGET_SECONDS = 5.0
_GLOB_DIR_CAP = 50_000
_GLOB_TIME_CHECK_INTERVAL = 200  # check the wall clock every N dirs, not every one (syscall cost)


def _is_filesystem_root(path: Path) -> bool:
    """True for a drive/filesystem root (C:\\, /, //server/share) — no
    further parent directory to ascend to."""
    resolved = path.resolve()
    return resolved.parent == resolved


def _tool_read_file(path: str, encoding: str = "") -> dict:
    """Read a file. Returns text content or base64-encoded binary."""
    if is_secrets_path(path):
        return {"error": PROTECTED_MSG}
    p = Path(path)
    if not p.exists() or not p.is_file():
        return {"error": f"File not found: {path}"}

    size = p.stat().st_size
    mime_type, _ = mimetypes.guess_type(str(p))
    mime_type = mime_type or "application/octet-stream"

    if size > _MAX_READ_BYTES:
        return {
            "error": f"File too large to read ({size:,} bytes). Max is {_MAX_READ_BYTES // 1024 // 1024} MB.",
            "size_bytes": size,
        }

    # Skip text decode for known binary types
    _binary_prefixes = (
        "image/",
        "audio/",
        "video/",
        "application/octet-stream",
        "application/pdf",
        "application/zip",
    )
    is_binary_mime = any(mime_type.startswith(p) for p in _binary_prefixes)

    if not is_binary_mime:
        for enc in [encoding] if encoding else ["utf-8", "latin-1"]:
            try:
                content = p.read_text(encoding=enc)
                return {"content": content, "size_bytes": size, "mime_type": mime_type}
            except (UnicodeDecodeError, LookupError):
                continue

    # Binary fallback
    raw = p.read_bytes()
    return {
        "binary": True,
        "base64": base64.b64encode(raw).decode("ascii"),
        "size_bytes": size,
        "mime_type": mime_type,
    }


# delete_file is intentionally disabled — deletion is not supported via any skill.
# Users must delete files manually. Keeping the implementation here for reference.
#
# def _tool_delete_file(path: str, confirmed: bool = False) -> dict:
#     p = Path(path)
#     if not p.exists():
#         return {"error": f"File not found: {path}"}
#     if not p.is_file():
#         return {"error": f"Path is not a file: {path}. Directories cannot be deleted with this tool."}
#     if not confirmed:
#         return {
#             "hitl_required": True,
#             "path": str(p),
#             "message": (
#                 f"This will permanently delete: {path}\n"
#                 "This action is irreversible. Re-call delete_file with confirmed=True "
#                 "only after the user has explicitly approved the deletion."
#             ),
#         }
#     try:
#         p.unlink()
#         return {"ok": True, "deleted": str(p)}
#     except Exception as exc:
#         return {"ok": False, "error": str(exc)}


def _tool_edit_file(
    path: str, old_str: str, new_str: str, encoding: str = "utf-8"
) -> dict:
    """Replace an exact string in a file. Fails if old_str is not found or is not unique."""
    if is_secrets_path(path):
        return {"error": PROTECTED_MSG}
    p = Path(path)
    if not p.exists() or not p.is_file():
        return {"error": f"File not found: {path}"}
    try:
        content = p.read_text(encoding=encoding)
    except Exception as exc:
        return {"error": f"Could not read file: {exc}"}
    count = content.count(old_str)
    if count == 0:
        return {"error": "old_str not found in file — no changes made."}
    if count > 1:
        return {
            "error": f"old_str appears {count} times — must be unique. Add more surrounding context to make it unambiguous."
        }
    new_content = content.replace(old_str, new_str, 1)
    try:
        p.write_text(new_content, encoding=encoding)
    except Exception as exc:
        return {"error": f"Could not write file: {exc}"}
    return {"ok": True, "path": str(p), "size_bytes": p.stat().st_size}


def _tool_write_file(path: str, content: str, encoding: str = "utf-8") -> dict:
    """Write text content to a file. Creates parent directories automatically."""
    if is_secrets_path(path):
        return {"ok": False, "error": PROTECTED_MSG}
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return {"ok": True, "path": str(p), "size_bytes": p.stat().st_size}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _tool_list_dir(path: str) -> dict:
    """List directory contents — dirs first then files, both sorted alphabetically."""
    if is_secrets_path(path):
        return {"error": PROTECTED_MSG}
    p = Path(path)
    if not p.exists() or not p.is_dir():
        return {"error": f"Directory not found: {path}"}

    entries = []
    for item in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        stat = item.stat()
        modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        entries.append(
            {
                "name": item.name,
                "type": "file" if item.is_file() else "dir",
                "size_bytes": stat.st_size if item.is_file() else 0,
                "modified_iso": modified,
            }
        )

    return {"entries": entries, "count": len(entries)}


def _tool_glob_files(pattern: str, base_path: str = "") -> dict:
    """Find files matching a glob pattern. Always a recursive descent from
    base_path — bounded so a broad/mistaken starting point can't hang the
    server walking the whole disk (see module-level note on _GLOB_*)."""
    base = Path(base_path or os.path.expanduser("~"))
    if not base.exists():
        return {"matches": [], "count": 0, "error": f"base_path not found: {base}"}
    if _is_filesystem_root(base):
        return {
            "matches": [],
            "count": 0,
            "error": (
                f"Refusing to search from filesystem root '{base}' — this would "
                "walk the entire disk. Pass a more specific base_path."
            ),
        }

    timed_out = False
    if "/" not in pattern and "\\" not in pattern:
        # Common case (plain filename pattern, e.g. "*.py", "SKILL.md"): walk
        # base ourselves with os.walk so the time-budget check runs once per
        # directory visited, bounding wall-clock time even when the tree is
        # huge and matches are sparse or absent (glob.glob's own recursion
        # has no such check-point between directories).
        start = time.monotonic()
        matches: list[str] = []
        dirs_scanned = 0
        for root, _dirnames, filenames in os.walk(base):
            dirs_scanned += 1
            if dirs_scanned >= _GLOB_DIR_CAP or (
                dirs_scanned % _GLOB_TIME_CHECK_INTERVAL == 0
                and time.monotonic() - start > _GLOB_TIME_BUDGET_SECONDS
            ):
                timed_out = True
                break
            for name in filenames:
                if fnmatch.fnmatch(name, pattern):
                    matches.append(os.path.join(root, name))
            if len(matches) >= _MAX_GLOB * 5:
                break
    else:
        # Pattern already carries a subpath (e.g. "sub/**/*.py") — needs real
        # glob semantics, not filename-only fnmatch. Root rejection above still
        # applies; this path is inherently rarer and lower-risk since the
        # caller already scoped the pattern to a subdirectory shape.
        full_pattern = os.path.join(str(base), pattern) if "**" in pattern else os.path.join(str(base), "**", pattern)
        try:
            matches = _glob.glob(full_pattern, recursive=True)
        except Exception as exc:
            return {"matches": [], "count": 0, "error": str(exc)}

    truncated = len(matches) > _MAX_GLOB
    matches = [m for m in sorted(matches)[:_MAX_GLOB] if not is_secrets_path(m)]
    result = {"matches": matches, "count": len(matches)}
    if truncated:
        result["truncated"] = True
    if timed_out:
        result["timed_out"] = True
        result["error"] = (
            f"Search exceeded its time/scan budget under '{base}' — narrow "
            "base_path to a smaller directory and try again."
        )
    return result


def _tool_grep_files(
    pattern: str,
    path: str,
    file_glob: str = "",
    max_results: int = _MAX_GREP,
) -> dict:
    """Search file contents for a regex pattern."""
    if is_secrets_path(path):
        return {"matches": [], "count": 0, "error": PROTECTED_MSG}
    search_path = Path(path)
    if not search_path.exists():
        return {"matches": [], "count": 0, "error": f"Path not found: {path}"}

    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return {"matches": [], "count": 0, "error": f"Invalid regex: {exc}"}

    if search_path.is_file():
        files = [search_path]
    else:
        glob_pat = file_glob or "*"
        files = [
            Path(f)
            for f in _glob.glob(str(search_path / "**" / glob_pat), recursive=True)
            if Path(f).is_file()
        ]

    matches = []
    truncated = False
    for f in files:
        if is_secrets_path(f):
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for lineno, line in enumerate(lines, start=1):
            if compiled.search(line):
                matches.append(
                    {"file": str(f), "line_number": lineno, "line": line.rstrip()}
                )
                if len(matches) >= max_results:
                    truncated = True
                    break
        if truncated:
            break

    result = {"matches": matches, "count": len(matches)}
    if truncated:
        result["truncated"] = True
    return result


TOOL_DEFS = [
    {
        "name": "read_file",
        "description": (
            "Read a local file. Text files return content string. Binary files "
            "(images, PDFs) return binary=true and base64-encoded content. "
            "Max file size 5 MB. Do not paste binary base64 into chat."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"},
                "encoding": {
                    "type": "string",
                    "description": "Text encoding override (optional, e.g. 'latin-1')",
                },
            },
            "required": ["path"],
        },
    },
    # delete_file intentionally omitted — deletion is not supported via any skill.
    {
        "name": "edit_file",
        "description": (
            "Make a targeted edit to a file by replacing an exact string with new content. "
            "Safer than write_file for large files — only the changed region is touched. "
            "Fails if old_str is not found or appears more than once (add more surrounding context to make it unique). "
            "Prefer this over write_file whenever you are changing part of an existing file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"},
                "old_str": {
                    "type": "string",
                    "description": "Exact string to replace — must appear exactly once in the file",
                },
                "new_str": {
                    "type": "string",
                    "description": "String to replace it with",
                },
                "encoding": {
                    "type": "string",
                    "description": "Text encoding (default utf-8, optional)",
                },
            },
            "required": ["path", "old_str", "new_str"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write text content to a local file. Creates parent directories automatically. "
            "Overwrites existing files. Delete is not supported — tell the user to delete manually."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to write to"},
                "content": {"type": "string", "description": "Text content to write"},
                "encoding": {
                    "type": "string",
                    "description": "Text encoding (default utf-8)",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": (
            "List directory contents. Returns name, type (file/dir), size_bytes, modified_iso. "
            "Directories first, then files, both sorted alphabetically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "glob_files",
        "description": (
            "Find files matching a glob pattern (e.g. '*.py', '**/*.json'). "
            "Returns absolute paths. Caps at 200 results. base_path defaults to user home."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern, e.g. '*.py'",
                },
                "base_path": {
                    "type": "string",
                    "description": "Directory to search from (optional)",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_files",
        "description": (
            "Search file contents for a regex pattern. Returns file, line_number, line for each match. "
            "file_glob filters which files to search (e.g. '*.py'). Default max_results is 100."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search in",
                },
                "file_glob": {
                    "type": "string",
                    "description": "Filter files to search, e.g. '*.py' (optional)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max matches to return (default 100)",
                },
            },
            "required": ["pattern", "path"],
        },
    },
]

TOOL_STATUS = {
    "read_file": "Reading file...",
    "edit_file": "Editing file...",
    "write_file": "Writing file...",
    # "delete_file": "Deleting file...",  # disabled
    "list_dir": "Listing directory...",
    "glob_files": "Searching files...",
    "grep_files": "Searching file contents...",
}

TOOL_HANDLERS = {
    "read_file": _tool_read_file,
    "edit_file": _tool_edit_file,
    "write_file": _tool_write_file,
    # "delete_file": _tool_delete_file,  # disabled
    "list_dir": _tool_list_dir,
    "glob_files": _tool_glob_files,
    "grep_files": _tool_grep_files,
}
