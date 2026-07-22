"""Integrated terminal — WebSocket-backed PTY for in-browser shell.

Named sessions: pass ?session_id=<uuid> to /api/terminal/ws to get a
persistent PTY that survives WebSocket reconnects. The coding agent uses
this to embed its own in-memory trace stream in the chat session card
(see /api/terminal/agent below) — not a real subprocess PTY for that path.
"""

import asyncio
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()

# Dedicated pool for blocking terminal/OpenCode work, kept OFF asyncio's
# default executor. A terminal's pty.read blocks a worker for the terminal's
# whole lifetime (it parks until the process emits output), and a cold
# `opencode serve` spawn squats one for ~15-20s. On the shared default pool
# those starved unrelated endpoints - git/status, LLM streaming, health
# checks all use asyncio.to_thread against that same small pool - until enough
# terminals/spawns piled up that the pool was exhausted and the whole app
# hung. Isolating them here means terminal/OpenCode load can never drain the
# pool the rest of the app depends on. Sized generously because these workers
# are almost always parked in a blocking read, not burning CPU: it's a ceiling
# on concurrent terminals+spawns, not a steady-state cost. Imported by
# opencode_routes.py for its spawn calls so all such work shares this ceiling.
OPENCODE_POOL = ThreadPoolExecutor(max_workers=64, thread_name_prefix="opencode-pty")


def _find_venv_activate() -> str | None:
    """Return the shell command to activate Gator's venv, or None if not found."""
    import sys
    from pathlib import Path
    # Look for venv relative to this file (web/routes/terminal.py → project root)
    root = Path(__file__).parent.parent.parent
    if sys.platform == "win32":
        activate = root / ".venv" / "Scripts" / "Activate.ps1"
        if activate.exists():
            # PowerShell: use & to run the script
            return f'& "{activate}"'
        activate_bat = root / ".venv" / "Scripts" / "activate.bat"
        if activate_bat.exists():
            return f'"{activate_bat}"'
    else:
        activate = root / ".venv" / "bin" / "activate"
        if activate.exists():
            return f'source "{activate}"'
    return None

# ── Named PTY session registry ────────────────────────────────────────────────
# session_id → {"pty": PTY, "output_buf": list[str], "done": bool}
# Output is buffered so reconnecting clients can replay recent output.
_pty_sessions: dict[str, dict] = {}
_PTY_BUF_MAX = 5000  # max output lines to buffer per session


def get_pty_session(session_id: str) -> dict | None:
    return _pty_sessions.get(session_id)


def create_pty_session(
    session_id: str, cols: int = 220, rows: int = 24,
    command: list[str] | None = None, env: dict | None = None, cwd: str | None = None,
) -> dict:
    """Spawn a PTY and register it under session_id. Returns the session dict.

    Pass `command`/`env` to run a specific process (e.g. `opencode attach`)
    instead of a bare shell - see _spawn_pty for why direct spawn is used
    instead of typing the command into a shell after the fact. `cwd` is
    unused by OpenCode's own attach (it talks to an already-running server
    over HTTP, so the PTY's working directory is irrelevant) - added for
    generic-agent CLIs (Claude Code, Codex, Crush) that operate on "the
    current directory" the way a human would after `cd`-ing into a repo.
    """
    pty = _spawn_pty(cols=cols, rows=rows, command=command, env=env, cwd=cwd)
    entry = {"pty": pty, "output_buf": [], "done": False, "waiters": []}
    _pty_sessions[session_id] = entry
    return entry


def close_pty_session(session_id: str) -> None:
    entry = _pty_sessions.pop(session_id, None)
    if entry:
        try:
            entry["pty"].close()
        except Exception:
            pass


def write_pty_session(session_id: str, data: str) -> bool:
    """Write input to a named PTY. Returns False if session not found."""
    entry = _pty_sessions.get(session_id)
    if not entry or entry["done"]:
        return False
    try:
        entry["pty"].write(data)
        return True
    except Exception:
        return False


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


def _spawn_pty(cols: int, rows: int, command: list[str] | None = None, env: dict | None = None, cwd: str | None = None):
    """Spawn a PTY. Returns a uniform object exposing read/write/resize/close/isalive.

    Runs a bare shell by default (the manual terminal). Pass `command` to run
    a specific process directly instead — used by the OpenCode terminal to
    run `opencode attach ...` as the PTY's actual process, rather than typing
    that command into a shell after the fact. Direct spawn is the reliable
    option: no dependency on shell-prompt timing, no risk of the command
    landing in the wrong place if the shell isn't ready yet. `cwd` defaults to
    None (inherit this process's cwd, exactly today's behavior) for every
    existing caller - only generic-agent spawns pass it explicitly.
    """
    if sys.platform == "win32":
        from winpty import PtyProcess
        if command:
            # env=<partial dict> would REPLACE the child's entire environment,
            # not extend it - found via real testing: passing just
            # {"OPENCODE_SERVER_PASSWORD": ...} produced a near-silent,
            # barely-rendering process (missing PATH and everything else a
            # real program needs). Merge onto the current environment instead,
            # matching what _PosixPty already does correctly below.
            proc_env = {**os.environ, **env} if env else None
            proc = PtyProcess.spawn(command, dimensions=(rows, cols), env=proc_env, cwd=cwd)
        else:
            # Prefer PowerShell 7 (pwsh.exe) — its Clear-Host emits proper VT
            # sequences through ConPTY, so `clear` actually clears the xterm
            # viewport. Fall back to Windows PowerShell 5.1, then cmd.exe.
            shell = _pick_windows_shell()
            proc = PtyProcess.spawn([shell], dimensions=(rows, cols), cwd=cwd)
        return _WinPtyAdapter(proc)
    else:
        return _PosixPty(cols, rows, command=command, env=env, cwd=cwd)


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
    def __init__(self, cols: int, rows: int, command: list[str] | None = None, env: dict | None = None, cwd: str | None = None):
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

        argv = command if command else [os.environ.get("SHELL", "/bin/bash")]
        proc_env = {**os.environ, **env} if env else None
        self._proc = subprocess.Popen(
            argv,
            stdin=slave, stdout=slave, stderr=slave,
            preexec_fn=os.setsid,
            close_fds=True,
            env=proc_env,
            cwd=cwd,
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


@router.websocket("/api/terminal/agent")
async def agent_terminal_ws(ws: WebSocket, session_id: str):
    """Named PTY WebSocket for coding agent sessions.

    Connects to an existing named PTY (created by the code agent route).
    On reconnect, replays buffered output so the client sees what it missed.
    Multiple clients can connect to the same session (all read, all can write).

    Same message protocol as /api/terminal/ws.
    """
    entry = _pty_sessions.get(session_id)
    if not entry:
        await ws.accept()
        await ws.send_text(json.dumps({"type": "exit", "data": "Session not found."}))
        await ws.close()
        return

    await ws.accept()

    pty = entry["pty"]
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    # Replay buffered output so reconnecting clients catch up
    if entry["output_buf"]:
        replay = "".join(entry["output_buf"])
        try:
            await ws.send_text(json.dumps({"type": "output", "data": replay}))
        except Exception:
            return

    if entry["done"]:
        try:
            await ws.send_text(json.dumps({"type": "exit"}))
        except Exception:
            pass
        await ws.close()
        return

    async def pump_pty_to_ws():
        # Check if this is an in-memory buffer session (no real PTY process)
        # vs a real PTY session. In-memory sessions tail the output_buf list.
        has_real_pty = hasattr(pty, '_p') or hasattr(pty, '_proc') or hasattr(pty, '_master')
        process_died = False

        if has_real_pty:
            # Real PTY — read blocking from the process
            while not stop.is_set() and pty.isalive():
                try:
                    data = await loop.run_in_executor(OPENCODE_POOL, pty.read, 4096)
                except (EOFError, OSError):
                    break
                if not data:
                    break
                entry["output_buf"].append(data)
                if len(entry["output_buf"]) > _PTY_BUF_MAX:
                    entry["output_buf"] = entry["output_buf"][-_PTY_BUF_MAX:]
                try:
                    await ws.send_text(json.dumps({"type": "output", "data": data}))
                except Exception:
                    break
            # Real bug found via code review, not assumed: this loop exiting
            # for its OWN reasons (pty.isalive() went False, EOF, a read
            # error) previously never marked entry["done"] - only the
            # in-memory branch below ever did that. A crashed OpenCode
            # process (opencode attach exiting because the server died, or
            # crashing outright) left this WebSocket open with nothing left
            # to ever send - no "exit" message, no client-side signal
            # anything had gone wrong. The client's terminal just went
            # silent forever. `stop.is_set()` is only true here if the
            # OUTER handler's client-disconnect path set it first - in that
            # case the client already knows it disconnected, so only the
            # "loop ended on its own" case needs reporting.
            if not stop.is_set():
                process_died = True
        else:
            # In-memory session — tail the output_buf for new items
            sent_idx = len(entry["output_buf"])  # already replayed above
            while not stop.is_set():
                buf = entry["output_buf"]
                if sent_idx < len(buf):
                    chunk = "".join(buf[sent_idx:])
                    sent_idx = len(buf)
                    try:
                        await ws.send_text(json.dumps({"type": "output", "data": chunk}))
                    except Exception:
                        break
                if entry["done"]:
                    break
                await asyncio.sleep(0.1)

        stop.set()
        if process_died:
            entry["done"] = True
        # Only mark done and send exit if the session is truly finished.
        # For in-memory sessions the thread controls entry["done"], not the WS pump.
        if entry.get("done"):
            try:
                await ws.send_text(json.dumps({
                    "type": "exit",
                    "data": "OpenCode process exited unexpectedly." if process_died else None,
                }))
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
                        # In-memory PTY: route input to the agent thread's queue
                        if hasattr(pty, "write_input"):
                            pty.write_input(data)
                        else:
                            pty.write(data)
                    except Exception:
                        break
            elif mtype == "resize":
                try:
                    pty.resize(int(msg.get("cols", 80)), int(msg.get("rows", 24)))
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("agent terminal websocket error")
    finally:
        stop.set()
        pump_task.cancel()
        try:
            await ws.close()
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
                data = await loop.run_in_executor(OPENCODE_POOL, pty.read, 4096)
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
