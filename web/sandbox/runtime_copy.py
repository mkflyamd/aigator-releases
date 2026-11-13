"""Readable copies of tools the AppContainer cannot read (for example Node under Program Files)."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
from pathlib import Path

MAX_COPY_BYTES = 1024 ** 3
_COPY_LOCK = threading.Lock()
_SPLIT = re.compile(r"&&|\|\||[;|&]")


class RuntimeCopyError(RuntimeError):
    pass


def runtime_dir() -> Path:
    return Path.home() / ".gator" / "sandbox" / "runtime"


def relay_dir() -> Path:
    return Path.home() / ".gator" / "sandbox" / "relay"


def _segments(command: str) -> list[str]:
    """Split on unquoted ; | & operators; the & of 2>&1 and &> is a redirect, not an operator."""
    segments: list[str] = []
    current: list[str] = []
    quote = ""
    for i, ch in enumerate(command):
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            current.append(ch)
        elif ch in ";|&" and not (ch == "&" and ((current and current[-1] == ">") or command[i + 1:i + 2] == ">")):
            segments.append("".join(current))
            current = []
        else:
            current.append(ch)
    segments.append("".join(current))
    return segments


def _words(segment: str) -> list[str]:
    words: list[str] = []
    current: list[str] = []
    quote = ""
    started = False
    for ch in segment:
        if quote:
            if ch == quote:
                quote = ""
            else:
                current.append(ch)
        elif ch in "\"'":
            quote = ch
            started = True
        elif ch.isspace():
            if started:
                words.append("".join(current))
                current, started = [], False
        else:
            current.append(ch)
            started = True
    if started:
        words.append("".join(current))
    return words


def _is_bare(name: str) -> bool:
    return bool(name) and name not in (".", "..") and not any(c in name for c in "/\:")


def tool_names(command: str) -> list[str]:
    names: list[str] = []
    for segment in _segments(command):
        words = _words(segment)
        while words and re.match(r"[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words.pop(0)
        if words and words[0] not in names:
            names.append(words[0])
    if "node" not in names and any(
        _is_bare(n) and os.path.splitext(n.lower())[0] in ("npm", "npx") for n in names
    ):
        names.append("node")
    return names


def _is_link(path: str) -> bool:
    if os.path.islink(path):
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction and isjunction(path))


def _tree_size(folder: Path) -> int:
    """Size of exactly what will be copied; refuses folders holding a symlink or junction."""
    total = 0
    for dirpath, dirs, files in os.walk(folder, followlinks=False):
        for name in dirs + files:
            if _is_link(os.path.join(dirpath, name)):
                raise RuntimeCopyError(f"{folder} contains a link, so it is not copied for the sandbox.")
        for name in files:
            total += os.path.getsize(os.path.join(dirpath, name))
            if total > MAX_COPY_BYTES:
                return total
    return total


def _copy_once(folder: Path, root: Path) -> Path:
    digest = hashlib.sha1(os.path.normcase(str(folder)).encode("utf-8")).hexdigest()[:8]
    target = root / f"{folder.name}-{int(folder.stat().st_mtime)}-{digest}"
    partial = target.with_name(target.name + ".partial")
    with _COPY_LOCK:
        if target.exists():
            return target
        try:
            if _tree_size(folder) > MAX_COPY_BYTES:
                raise RuntimeCopyError(f"{folder} is too large to copy for the sandbox.")
            root.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(partial, ignore_errors=True)
            shutil.copytree(folder, partial, symlinks=True)
            try:
                partial.rename(target)
            except OSError:
                if not target.is_dir():
                    raise
                shutil.rmtree(partial, ignore_errors=True)
        except OSError as exc:
            shutil.rmtree(partial, ignore_errors=True)
            raise RuntimeCopyError(
                f"Could not copy {folder} so the sandbox can read it ({type(exc).__name__})."
            ) from exc
    return target


def _search_dirs(search_path: str) -> set[str]:
    return {os.path.normcase(str(Path(p).resolve())) for p in search_path.split(os.pathsep) if p}


def readable_copies(command: str, search_path: str, usable, root: Path) -> list[Path]:
    copies: list[Path] = []
    allowed = _search_dirs(search_path)
    for name in tool_names(command):
        if not _is_bare(name):
            continue
        found = shutil.which(name, path=search_path)
        if not found:
            continue
        # which() may also look in the process cwd; only programs found on search_path count.
        if os.path.normcase(str(Path(os.path.abspath(found)).parent.resolve())) not in allowed:
            continue
        folder = Path(found).resolve().parent
        if usable(folder):
            continue
        copy = _copy_once(folder, root)
        if copy not in copies:
            copies.append(copy)
    return copies


def install_relay(root: Path | None = None) -> Path:
    root = root or relay_dir()
    src = Path(__file__).resolve().parent
    try:
        root.mkdir(parents=True, exist_ok=True)
        for name in ("relay.py", "wire.py"):
            data = (src / name).read_bytes()
            dest = root / name
            if not dest.exists() or dest.read_bytes() != data:
                dest.write_bytes(data)
    except OSError as exc:
        raise RuntimeCopyError(f"Could not prepare the sandbox relay ({type(exc).__name__}).") from exc
    return root / "relay.py"
