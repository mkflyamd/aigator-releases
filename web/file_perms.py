"""Owner-only file permissions for local data (logs, telemetry, task and scheduler databases)."""
from __future__ import annotations

import getpass
import logging
import os
import subprocess
from pathlib import Path

_log = logging.getLogger(__name__)
_done: set[str] = set()


def restrict_to_owner(path: Path, *, directory: bool = False) -> None:
    """Limit *path* to the current user. POSIX: chmod 600/700. Windows: remove inherited ACEs, grant the user only.

    Raises OSError when the restriction cannot be applied, so callers can fail closed.
    Each path is hardened once per process; call forget(path) after a file is recreated.
    """
    path = Path(path)
    key = str(path)
    if key in _done or not path.exists():
        return
    if os.name == "posix":
        os.chmod(path, 0o700 if directory else 0o600)
    else:
        grant = f"{getpass.getuser()}:" + ("(OI)(CI)F" if directory else "F")
        try:
            result = subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", grant],
                capture_output=True, text=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise OSError(f"icacls failed ({type(exc).__name__})") from exc
        if result.returncode != 0:
            raise OSError(f"icacls exited with {result.returncode}")
    _done.add(key)


def forget(path: Path) -> None:
    _done.discard(str(path))


def restrict_database(path: Path) -> bool:
    """Harden a SQLite file and its -wal/-shm sidecars. Logs an error and returns False on failure."""
    try:
        for suffix in ("", "-wal", "-shm"):
            restrict_to_owner(Path(str(path) + suffix))
        return True
    except OSError as exc:
        _log.error("Could not restrict %s to the current user: %s", Path(path).name, exc)
        return False
