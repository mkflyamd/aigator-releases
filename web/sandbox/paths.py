"""Normalization of model-requested extra paths and hosts, and the never-grantable deny list."""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

HOME_DENY = (
    ".ssh", ".aws", ".azure", ".kube", ".gnupg", ".config/gcloud",
    # Autostart / persistence locations: a write here runs code outside the sandbox later.
    ".bashrc", ".profile", ".bash_profile", ".zshrc", ".zprofile",
    "Library/LaunchAgents", ".config/autostart",
    "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup",
    # Credential stores and browser profiles (cookies, saved logins).
    "AppData/Roaming/Microsoft/Credentials", "AppData/Roaming/Microsoft/Protect",
    "AppData/Local/Microsoft/Credentials", "AppData/Local/Google/Chrome/User Data",
    "AppData/Local/Microsoft/Edge/User Data", "AppData/Local/BraveSoftware",
    "AppData/Roaming/Mozilla", ".mozilla",
    "Library/Keychains", "Library/Application Support/Google/Chrome", "Library/Application Support/Firefox",
)
# Too broad to grant as a whole (a Windows grant walks every file below it), but folders inside are fine.
HOME_BROAD = ("AppData", "AppData/Local", "AppData/Roaming", "AppData/LocalLow", "Library/Application Support")
ACL_GRANTS_WALK_TREE = os.name == "nt"
MAX_GRANT_ENTRIES = 100_000
GRANT_WALK_SECONDS = 5.0
MAC_DATA_VOLUME = "/System/Volumes/Data"
_DRIVE_RE = re.compile(r"[A-Za-z]:(?:\\.*)?", re.DOTALL)

APP_DIR_ENV = "AIGATOR_APP_DIR"
APP_FOLDER_REFUSAL = (
    "Giving the sandbox access there would stop AI Gator from starting. "
    "Choose a folder that is separate from the AI Gator install or source folder."
)

CHOOSE_FOLDER = "Choose the specific folder the command needs."

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


def app_protected_dirs() -> list[Path]:
    """Folders that hold AI Gator's own Electron files (the shell sets APP_DIR_ENV to its executable's folder)."""
    dirs = []
    env = os.environ.get(APP_DIR_ENV)
    if env:
        dirs.append(Path(env))
    root = Path(__file__).resolve().parents[2]
    dirs += [root / "shell", root / "electron"]
    return dirs


def protects_app(path: Path) -> bool:
    """Windows only: a sandbox ACE on, above or inside an Electron folder makes Electron crash on launch."""
    if os.name != "nt":
        return False
    path = _plain(Path(path))
    return any(is_within(form, path) or is_within(path, form)
               for app_dir in app_protected_dirs() for form in _forms(app_dir))


def check_grantable(path: Path, home: Path) -> None:
    path = _plain(path)
    if protects_app(path):
        raise PathNotGrantable(
            f"{path} contains or is inside the AI Gator program files. {APP_FOLDER_REFUSAL}"
        )
    if path.parent == path:
        raise PathNotGrantable(f"{path} is a filesystem or drive root and can never be granted.")
    if any(is_within(h, path) for h in _with_data_volume([home])):
        raise PathNotGrantable(f"{path} is the home folder or contains it and can never be granted.")
    for broad_path in (home / d for d in HOME_BROAD):
        if any(_key(path) == _key(broad) for broad in _with_data_volume(_forms(broad_path))):
            raise PathNotGrantable(f"{path} is too broad to approve. {CHOOSE_FOLDER}")
    outputs = _with_data_volume(_forms(home / ".gator" / "outputs"))
    for protected_path in [home / ".gator", *(home / d for d in HOME_DENY)]:
        # Compare against the literal and the symlink-resolved protected location,
        # so `~/.ssh -> /data/ssh` is denied through either spelling (and, on macOS,
        # through the firmlinked /System/Volumes/Data spelling).
        for protected in _with_data_volume(_forms(protected_path)):
            inside = is_within(path, protected) and not any(is_within(path, o) for o in outputs)
            if inside or is_within(protected, path):
                raise PathNotGrantable(f"{path} is a protected location and can never be granted.")


def _is_link(entry: os.DirEntry) -> bool:
    return entry.is_symlink() or bool(getattr(entry, "is_junction", lambda: False)())


def check_grant_size(paths, max_entries: int | None = None, budget_seconds: float | None = None) -> None:
    """Refuse a folder too big to grant. A Windows grant and its revoke walk every file below the
    folder, so a huge one (AppData\\Local) would stall the run for a long time. The walk is bounded,
    does not follow links, and counts running out of time as too big."""
    if not ACL_GRANTS_WALK_TREE:
        return
    max_entries = MAX_GRANT_ENTRIES if max_entries is None else max_entries
    budget_seconds = GRANT_WALK_SECONDS if budget_seconds is None else budget_seconds
    for path in paths:
        deadline = time.monotonic() + budget_seconds
        stack, seen = [str(path)], 0
        while stack:
            try:
                with os.scandir(stack.pop()) as entries:
                    for entry in entries:
                        seen += 1
                        if seen > max_entries or time.monotonic() > deadline:
                            raise PathNotGrantable(f"{path} is too broad to approve: it holds too many files. {CHOOSE_FOLDER}")
                        if not _is_link(entry) and entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
            except (NotADirectoryError, FileNotFoundError, PermissionError):
                continue


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


PROTECTED_MSG = "That location is protected."


def _same_folder_by_identity(path: Path, root: Path) -> bool:
    """Windows UNC/device spellings (\\\\localhost\\C$, \\\\?\\GLOBALROOT) do not resolve to a
    drive path, so compare file identity of each existing ancestor with the folder."""
    import secure_store

    secure_store._ensure_root()
    root_stat = os.stat(root)
    for item in (path, *path.parents):
        try:
            if os.path.samestat(os.stat(item), root_stat):
                return True
        except (FileNotFoundError, NotADirectoryError):
            continue
    return False


def is_secrets_path(path) -> bool:
    """True when path names the AI Gator secrets folder or anything in it. Fails closed."""
    try:
        import secure_store

        root = secure_store._root()
        text = os.path.expanduser(os.fspath(path))
        if os.name == "nt":
            text = text.replace("/", "\\")
            plain = text[4:] if text.startswith("\\\\?\\") and _DRIVE_RE.fullmatch(text[4:]) else text
            body = plain[2:] if re.match(r"[A-Za-z]:", plain) else plain
            # A stream name on a folder part ("secrets::$INDEX_ALLOCATION\\x") opens the folder.
            if ":" in os.path.dirname(body.rstrip("\\")):
                return True
        else:
            plain = text
        literal = os.path.abspath(plain)
        candidates = {literal, os.path.realpath(literal)}
        roots = {os.path.abspath(root), os.path.realpath(root)}
        if any(is_within(Path(c), Path(r)) for c in candidates for r in roots):
            return True
        if os.name == "nt" and any(c.startswith("\\\\") for c in (text, *candidates)):
            return _same_folder_by_identity(Path(text), Path(root))
        return False
    except Exception:  # noqa: BLE001 - an unresolvable path is treated as protected
        return True


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
