"""Normalization of model-requested extra paths and hosts, and the never-grantable deny list."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HOME_DENY = (
    ".ssh", ".aws", ".azure", ".kube", ".gnupg", ".config/gcloud",
    # Autostart / persistence locations: a write here runs code outside the sandbox later.
    ".bashrc", ".profile", ".bash_profile", ".zshrc", ".zprofile",
    "Library/LaunchAgents", ".config/autostart",
    "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup",
)
MAC_DATA_VOLUME = "/System/Volumes/Data"
_DRIVE_RE = re.compile(r"[A-Za-z]:(?:\\.*)?", re.DOTALL)

_HOST_RE = re.compile(r"(?:\[[0-9a-f:.]+\]|[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?):([0-9]{1,5})")


class PathNotGrantable(ValueError):
    """The path can never be granted, or is not a valid absolute existing path."""


def _key(path: Path) -> str:
    """Comparison key. Windows and macOS file systems are case-insensitive by default."""
    text = os.path.normpath(str(path))
    if sys.platform == "darwin":
        return text.casefold()
    return os.path.normcase(text)


def is_within(child: Path, parent: Path) -> bool:
    c, p = _key(child), _key(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def _forms(path: Path) -> list[Path]:
    """The literal path and its symlink-resolved form (when different)."""
    forms = [path]
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        return forms
    if _key(resolved) != _key(path):
        forms.append(resolved)
    return forms


def windows_plain_path(text: str) -> str:
    r"""A Windows path as a plain drive path ("X:\..."), or PathNotGrantable.

    Pure (any OS). The extended-length prefix \\?\X:\ is stripped; every other
    \\-prefixed form (UNC shares, \\?\UNC, volume GUIDs, \\.\ devices) and any
    ':' after the drive letter (NTFS alternate data streams) is refused, because the
    deny list compares strings and those spellings would slip past it."""
    t = text.replace("/", "\\")
    if t.startswith("\\\\?\\"):
        t = t[4:]
        if not _DRIVE_RE.fullmatch(t):
            raise PathNotGrantable(f"{text} is a device or network path and can never be granted.")
    elif t.startswith("\\\\"):
        raise PathNotGrantable(f"{text} is a network or device path and can never be granted.")
    if not _DRIVE_RE.fullmatch(t):
        raise PathNotGrantable(f"{text} is not a drive path such as C:\\folder.")
    if ":" in t[2:]:
        raise PathNotGrantable(f"{text} names an alternate data stream and can never be granted.")
    # Win32 trims a trailing dot or space from a name (".ssh." opens ".ssh"), and a verbatim
    # \\?\ path is left literal by resolve(), so such a component (including "." and "..")
    # would slip past the string comparison. A trailing separator (empty last part) is fine.
    parts = t[3:].split("\\")
    if parts and parts[-1] == "":
        parts.pop()
    if any(p == "" or p.endswith((".", " ")) for p in parts):
        raise PathNotGrantable(f"{text} has a name ending in a dot or space and can never be granted.")
    return t


def data_volume_form(text: str) -> str | None:
    """macOS: the firmlinked /System/Volumes/Data spelling of an absolute path (pure, any OS)."""
    if not text.startswith("/") or text == MAC_DATA_VOLUME or text.startswith(MAC_DATA_VOLUME + "/"):
        return None
    return MAC_DATA_VOLUME + text


def _drive_type(root: str) -> int:
    import ctypes

    return ctypes.windll.kernel32.GetDriveTypeW(root)


def _is_remote_drive(path: Path) -> bool:
    """Windows: True for a mapped network drive (GetDriveTypeW == DRIVE_REMOTE).
    Fails closed: if the drive type cannot be read, the path is treated as remote."""
    try:
        return _drive_type(str(path)[:2] + "\\") == 4
    except Exception:  # noqa: BLE001 - any failure refuses the grant
        return True


def _plain(path: Path) -> Path:
    return Path(windows_plain_path(str(path))) if os.name == "nt" else path


def _with_data_volume(paths: list[Path]) -> list[Path]:
    if sys.platform != "darwin":
        return paths
    extra = [Path(f) for f in (data_volume_form(str(p)) for p in paths) if f]
    return [*paths, *extra]


def check_grantable(path: Path, home: Path) -> None:
    path = _plain(path)
    if path.parent == path:
        raise PathNotGrantable(f"{path} is a filesystem or drive root and can never be granted.")
    if any(is_within(h, path) for h in _with_data_volume([home])):
        raise PathNotGrantable(f"{path} is the home folder or contains it and can never be granted.")
    outputs = _with_data_volume(_forms(home / ".gator" / "outputs"))
    for protected_path in [home / ".gator", *(home / d for d in HOME_DENY)]:
        # Compare against the literal and the symlink-resolved protected location,
        # so `~/.ssh -> /data/ssh` is denied through either spelling (and, on macOS,
        # through the firmlinked /System/Volumes/Data spelling).
        for protected in _with_data_volume(_forms(protected_path)):
            inside = is_within(path, protected) and not any(is_within(path, o) for o in outputs)
            if inside or is_within(protected, path):
                raise PathNotGrantable(f"{path} is a protected location and can never be granted.")


def normalize_grant_paths(raw, home: Path | None = None) -> list[Path]:
    """Absolute, resolved, existing, deduplicated, sorted. Raises PathNotGrantable."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise PathNotGrantable("Extra paths must be a list of absolute paths.")
    home_resolved = (Path(home) if home is not None else Path.home()).resolve()
    found: dict[str, Path] = {}
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise PathNotGrantable("Extra paths must be non-empty strings.")
        candidate = Path(os.path.expanduser(item.strip()))
        if not candidate.is_absolute():
            raise PathNotGrantable(f"{item} is not an absolute path.")
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise PathNotGrantable(f"{item} cannot be resolved ({type(exc).__name__}).") from exc
        resolved = _plain(resolved)
        check_grantable(resolved, home_resolved)
        if os.name == "nt" and _is_remote_drive(resolved):
            raise PathNotGrantable(f"{resolved} is on a network drive and can never be granted.")
        if not resolved.exists():
            raise PathNotGrantable(f"{resolved} does not exist. Request an existing file or its folder.")
        found.setdefault(_key(resolved), resolved)
    return [found[k] for k in sorted(found)]


def normalize_hosts(raw) -> list[str]:
    """Lower-cased, validated host:port strings, deduplicated and sorted. Raises ValueError."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise ValueError("network_hosts must be a list of host:port strings.")
    hosts = set()
    for item in raw:
        text = item.strip().lower() if isinstance(item, str) else ""
        match = _HOST_RE.fullmatch(text)
        if not match or not 0 < int(match.group(1)) < 65536:
            raise ValueError(f"{item!r} is not a host:port value such as api.example.com:443.")
        host, _, port = text.rpartition(":")
        hosts.add(f"{host}:{int(port)}")  # zero-padded ports collapse to one entry
    return sorted(hosts)


def paths_covered(read, write, granted_read, granted_write) -> bool:
    gw = [Path(p) for p in granted_write]
    gr = gw + [Path(p) for p in granted_read]
    return (all(any(is_within(Path(p), g) for g in gw) for p in write)
            and all(any(is_within(Path(p), g) for g in gr) for p in read))
