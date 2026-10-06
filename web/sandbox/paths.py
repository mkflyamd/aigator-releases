"""Normalization of model-requested extra paths and hosts, and the never-grantable deny list."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HOME_DENY = (".ssh", ".aws", ".azure", ".kube", ".gnupg", ".config/gcloud")

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


def check_grantable(path: Path, home: Path) -> None:
    if path.parent == path:
        raise PathNotGrantable(f"{path} is a filesystem or drive root and can never be granted.")
    if is_within(home, path):
        raise PathNotGrantable(f"{path} is the home folder or contains it and can never be granted.")
    outputs = _forms(home / ".gator" / "outputs")
    for protected_path in [home / ".gator", *(home / d for d in HOME_DENY)]:
        # Compare against the literal and the symlink-resolved protected location,
        # so `~/.ssh -> /data/ssh` is denied through either spelling.
        for protected in _forms(protected_path):
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
        check_grantable(resolved, home_resolved)
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
