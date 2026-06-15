"""Integrated terminal — WebSocket-backed PTY for in-browser shell."""

import asyncio
import json
import logging
import os
import sys

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


def _pick_windows_shell() -> str:
    """Return the best available shell on Windows.

    Prefer pwsh.exe (PowerShell 7) because its Clear-Host emits proper VT
    sequences through ConPTY so `clear` works in xterm. Fall back to the
    inbox Windows PowerShell, then cmd.exe.
    """
    import shutil
    for candidate in ("pwsh.exe", "powershell.exe", "cmd.exe"):
        if shutil.which(candidate):
            return candidate
    return os.environ.get("COMSPEC", "cmd.exe")


def _spawn_pty(cols: int, rows: int):
    """Spawn a shell PTY. Returns a uniform object exposing read/write/resize/close/isalive."""
    if sys.platform == "win32":
        from winpty import PtyProcess
        # Prefer PowerShell 7 (pwsh.exe) — its Clear-Host emits proper VT
        # sequences through ConPTY, so `clear` actually clears the xterm
        # viewport. Fall back to Windows PowerShell 5.1, then cmd.exe.
        shell = _pick_windows_shell()
        # pywinpty wants (rows, cols)
        proc = PtyProcess.spawn([shell], dimensions=(rows, cols))
        return _WinPtyAdapter(proc)
    else:
        return _PosixPty(cols, rows)


class _WinPtyAdapter:
    def __init__(self, proc):
        self._p = proc

    def read(self, n: int = 4096) -> str:
        # pywinpty.read returns str (decoded utf-8 with replacement)
        return self._p.read(n)

    def write(self, data: str) -> None:
        self._p.write(data)

    def resize(self, cols: int, rows: int) -> None:
        self._p.setwinsize(rows, cols)

    def isalive(self) -> bool:
        return self._p.isalive()

    def close(self) -> None:
        try:
            self._p.terminate(force=True)
        except Exception:
            pass


class _PosixPty:
    def __init__(self, cols: int, rows: int):
        import pty
        import fcntl
        import termios
        import struct
        import subprocess

        self._pty = pty
        self._fcntl = fcntl
        self._termios = termios
        self._struct = struct

        master, slave = pty.openpty()
        # set initial size
        fcntl.ioctl(master, termios.TIOCSWINSZ,
                    struct.pack("HHHH", rows, cols, 0, 0))

        shell = os.environ.get("SHELL", "/bin/bash")
        self._proc = subprocess.Popen(
            [shell],
            stdin=slave, stdout=slave, stderr=slave,
            preexec_fn=os.setsid,
            close_fds=True,
        )
        os.close(slave)
        self._master = master

    def read(self, n: int = 4096) -> str:
        data = os.read(self._master, n)
        return data.decode("utf-8", errors="replace")

    def write(self, data: str) -> None:
        os.write(self._master, data.encode("utf-8"))

    def resize(self, cols: int, rows: int) -> None:
        self._fcntl.ioctl(
            self._master, self._termios.TIOCSWINSZ,
            self._struct.pack("HHHH", rows, cols, 0, 0),
        )

    def isalive(self) -> bool:
        return self._proc.poll() is None

    def close(self) -> None:
        try:
            self._proc.terminate()
        except Exception:
            pass
        try:
            os.close(self._master)
        except Exception:
            pass


@router.websocket("/api/terminal/ws")
async def terminal_ws(ws: WebSocket):
    """Bidirectional PTY bridge.

    Client → server JSON messages:
      {"type": "input",  "data": "<text>"}
      {"type": "resize", "cols": N, "rows": N}

    Server → client JSON messages:
      {"type": "output", "data": "<text>"}
      {"type": "exit"}
    """
    await ws.accept()

    # Initial dimensions — client should send a resize immediately after connect,
    # but seed with sane defaults so the shell can start.
    pty = _spawn_pty(cols=80, rows=24)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    async def pump_pty_to_ws():
        while not stop.is_set() and pty.isalive():
            try:
                data = await loop.run_in_executor(None, pty.read, 4096)
            except (EOFError, OSError):
                break
            if not data:
                break
            try:
                await ws.send_text(json.dumps({"type": "output", "data": data}))
            except Exception:
                break
        stop.set()
        try:
            await ws.send_text(json.dumps({"type": "exit"}))
        except Exception:
            pass

    pump_task = asyncio.create_task(pump_pty_to_ws())

    try:
        while not stop.is_set():
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "input":
                data = msg.get("data", "")
                if data:
                    try:
                        pty.write(data)
                    except Exception:
                        break
            elif mtype == "resize":
                cols = int(msg.get("cols", 80))
                rows = int(msg.get("rows", 24))
                try:
                    pty.resize(cols, rows)
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("terminal websocket error")
    finally:
        stop.set()
        pty.close()
        pump_task.cancel()
        try:
            await ws.close()
        except Exception:
            pass
