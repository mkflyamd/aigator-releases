"""Backend-side client for the PTY host (see pty_host.py).

RemotePty looks like the object spawn_pty returns (blocking read, write, resize,
isalive, close), so PtySession can mirror a session that actually lives in the
host process.
"""

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from pty_host import (
    PROTOCOL_VERSION,
    host_command,
    host_file,
    host_log_file,
    probe,
    probe_state,
)

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 5.0
_START_TIMEOUT = 15.0
_spawn_lock = threading.Lock()


class HostError(Exception):
    pass


def host_enabled() -> bool:
    """GATOR_PTY_HOST=0/1 forces it off/on. By default it is on, except in frozen
    builds (a lingering host would hold install-dir files open and block updates)
    and under pytest (so tests never leave a detached host behind)."""
    forced = os.environ.get("GATOR_PTY_HOST")
    if forced in ("0", "1"):
        return forced == "1"
    return not getattr(sys, "frozen", False) and "PYTEST_CURRENT_TEST" not in os.environ


def instance_key() -> str:
    """Hosts are per backend instance so dev (:8003) and prod (:8000) never share."""
    explicit = os.environ.get("GATOR_PTY_HOST_KEY")
    if explicit:
        return explicit
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg == "--port" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--port="):
            return arg.split("=", 1)[1]
    return "8000"


def find_host(key: str) -> dict | None:
    """Connection info for a running host, or None. Never starts one."""
    if not host_file(key).exists():
        return None
    return probe(key)


def _launch_host(key: str) -> None:
    """Run the short-lived --detach launcher. The host it starts is orphaned when
    the launcher exits, so killing the backend's process tree cannot reach it."""
    cmd = [*host_command(key)[:2], "--detach", "--key", key]
    kwargs: dict = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(Path(__file__).parent),
        timeout=_START_TIMEOUT + 5,
    )
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.run(cmd, **kwargs)


def ensure_host(key: str) -> dict | None:
    """Connection info for this instance's host, starting it if needed. None means
    run PTYs in-process: the host could not start, or a host from another version
    of the app is still running and speaks a different protocol."""
    info = find_host(key)
    if info is not None:
        return info
    with _spawn_lock:
        info = find_host(key)
        if info is not None:
            return info
        if probe_state(key)[0] == "incompatible":
            logger.warning("PTY host for %s speaks another protocol; using in-process PTYs", key)
            return None
        try:
            _launch_host(key)
        except (OSError, subprocess.SubprocessError):
            logger.exception("could not start the PTY host")
            return None
        info = find_host(key)
        if info is not None:
            return info
    logger.error("PTY host did not come up; see %s", host_log_file(key))
    return None


def _connect(info: dict, timeout: float = _CONNECT_TIMEOUT):
    sock = socket.create_connection(("127.0.0.1", int(info["port"])), timeout)
    try:
        sock.settimeout(timeout)
        reader = sock.makefile("rb")
        _send(sock, {"op": "hello", "token": info["token"], "proto": PROTOCOL_VERSION})
        reply = _read(reader)
        if not reply.get("ok"):
            raise HostError(f"host refused connection: {reply.get('error')}")
        return sock, reader
    except BaseException:
        sock.close()
        raise


def _send(sock: socket.socket, obj: dict) -> None:
    sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))


def _read(reader) -> dict:
    line = reader.readline()
    if not line:
        raise HostError("host closed the connection")
    return json.loads(line)


def host_request(info: dict, msg: dict) -> dict:
    """One request on a short-lived connection."""
    try:
        sock, reader = _connect(info)
    except OSError as exc:
        raise HostError(f"cannot reach PTY host: {exc}") from exc
    try:
        _send(sock, msg)
        return _read(reader)
    except (OSError, ValueError) as exc:
        raise HostError(f"PTY host request failed: {exc}") from exc
    finally:
        sock.close()


class RemotePty:
    """A PTY that lives in the host. close() kills it there; detach() only drops
    this connection and leaves the process running."""

    def __init__(self, info: dict, session_id: str, offset: int = 0):
        self._info = info
        self._id = session_id
        self._wlock = threading.Lock()
        self._alive = True
        try:
            self._sock, self._reader = _connect(info)
            _send(self._sock, {"op": "attach", "id": session_id, "offset": offset})
            reply = _read(self._reader)
        except (OSError, ValueError) as exc:
            raise HostError(f"cannot attach to {session_id}: {exc}") from exc
        if not reply.get("ok"):
            self._sock.close()
            raise HostError(f"attach failed: {reply.get('error')}")
        self.start_offset = int(reply["start"])
        self._sock.settimeout(None)

    def read(self, n: int = 4096) -> str:
        while True:
            try:
                line = self._reader.readline()
            except (OSError, ValueError):
                line = b""
            if not line:
                self._alive = False
                raise EOFError
            msg = json.loads(line)
            kind = msg.get("t")
            if kind == "out":
                return msg["data"]
            if kind == "exit":
                self._alive = False
                raise EOFError

    def _write_msg(self, obj: dict) -> None:
        with self._wlock:
            _send(self._sock, obj)

    def write(self, data: str) -> None:
        self._write_msg({"op": "write", "data": data})

    def resize(self, cols: int, rows: int) -> None:
        self._write_msg({"op": "resize", "cols": cols, "rows": rows})

    def isalive(self) -> bool:
        return self._alive

    def detach(self) -> None:
        self._alive = False
        try:
            self._sock.shutdown(socket.SHUT_RDWR)  # wakes a reader blocked in read()
        except OSError:
            pass
        self._sock.close()

    def close(self) -> None:
        try:
            host_request(self._info, {"op": "close", "id": self._id})
        except HostError:
            logger.warning("could not close PTY session %s on the host", self._id)
        self.detach()
