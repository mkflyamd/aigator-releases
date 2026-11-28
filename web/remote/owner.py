"""One backend owns a channel's self-chat at a time. A second backend on the same machine (a dev
server beside the installed app, or a worker that has not exited yet) would read the same messages
and post every reply twice, so the owner holds an OS file lock and the others stay silent."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from remote.state import default_path

_log = logging.getLogger(__name__)


def _try_lock(handle) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


class ChannelOwner:
    """`acquire()` is true while this process owns the channel. The lock dies with the process."""

    def __init__(self, channel: str, directory: Path | None = None):
        self._path = (directory or default_path().parent) / f"remote_control_owner_{channel}.lock"
        self._handle = None
        self._refused_logged = False

    def acquire(self) -> bool:
        if self._handle is not None:
            return True
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a+b")
        if not _try_lock(handle):
            handle.close()
            if not self._refused_logged:
                self._refused_logged = True
                _log.warning("Remote control stays idle here: another AI Gator backend owns %s", self._path.name)
            return False
        self._handle = handle
        self._refused_logged = False
        return True

    def release(self) -> None:
        if self._handle is None:
            return
        _unlock(self._handle)
        self._handle.close()
        self._handle = None
