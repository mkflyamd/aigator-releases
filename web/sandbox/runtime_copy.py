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


def tool_names(command: str) -> list[str]:
    names: list[str] = []
    for segment in _SPLIT.split(command):
        words = segment.strip().split()
        if not words:
            continue
        name = words[0].strip("\"'")
        if name and name not in names:
            names.append(name)
    if "node" not in names and any(os.path.splitext(n.lower())[0] in ("npm", "npx") for n in names):
        names.append("node")
    return names


def _tree_size(folder: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(folder):
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
            shutil.copytree(folder, partial)
            partial.rename(target)
        except OSError as exc:
            shutil.rmtree(partial, ignore_errors=True)
            raise RuntimeCopyError(
                f"Could not copy {folder} so the sandbox can read it ({type(exc).__name__})."
            ) from exc
    return target


def readable_copies(command: str, search_path: str, usable, root: Path) -> list[Path]:
    copies: list[Path] = []
    for name in tool_names(command):
        found = shutil.which(name, path=search_path)
        if not found:
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
