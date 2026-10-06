"""Normalization of model-requested extra paths and hosts, and the never-grantable deny list."""
from __future__ import annotations

import os
import re
from pathlib import Path

HOME_DENY = (".ssh", ".aws", ".azure", ".kube", ".gnupg", ".config/gcloud")

_HOST_RE = re.compile(r"^(?:\[[0-9a-f:.]+\]|[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?):(\d{1,5})$")


class PathNotGrantable(ValueError):
    """The path can never be granted, or is not a valid absolute existing path."""


def _key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def is_within(child: Path, parent: Path) -> bool:
    c, p = _key(child), _key(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def check_grantable(path: Path, home: Path) -> None:
    if path.parent == path:
        raise PathNotGrantable(f"{path} is a filesystem or drive root and can never be granted.")
    if is_within(home, path):
        raise PathNotGrantable(f"{path} is the home folder or contains it and can never be granted.")
    outputs = home / ".gator" / "outputs"
    for protected in [home / ".gator", *(home / d for d in HOME_DENY)]:
        inside = is_within(path, protected) and not is_within(path, outputs)
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
        resolved = candidate.resolve()
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
        match = _HOST_RE.match(text)
        if not match or not 0 < int(match.group(1)) < 65536:
            raise ValueError(f"{item!r} is not a host:port value such as api.example.com:443.")
        hosts.add(text)
    return sorted(hosts)
