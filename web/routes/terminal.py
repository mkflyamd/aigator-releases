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
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import pty_client
from pty_session import PtySession
from pty_spawn import spawn_pty

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
# session_id → PtySession. Each session buffers its own output (reader thread
# started at creation) so reconnecting clients can replay what they missed.
_pty_sessions: dict[str, PtySession] = {}
_adopt_lock = threading.Lock()


def get_pty_session(session_id: str) -> PtySession | None:
    """The registered session, or one adopted from the PTY host. After a backend
    restart the registry is empty but the host still owns the PTYs, so a lookup
    that misses asks the host before giving up. Blocking (loopback socket)."""
    entry = _pty_sessions.get(session_id)
    if entry is not None:
        return entry
    return _adopt_pty_session(session_id)


def _adopt_pty_session(session_id: str) -> PtySession | None:
    if not pty_client.host_enabled():
        return None
    with _adopt_lock:
        entry = _pty_sessions.get(session_id)
        if entry is not None:
            return entry
        info = pty_client.find_host(pty_client.instance_key())
        if info is None:
            return None
        try:
            status = pty_client.host_request(info, {"op": "status", "id": session_id})
            if not status.get("exists"):
                return None
            remote = pty_client.RemotePty(info, session_id)
        except pty_client.HostError:
            logger.exception("could not adopt PTY session %s from the host", session_id)
            return None
        entry = PtySession(remote, start_offset=remote.start_offset)
        _pty_sessions[session_id] = entry
        return entry


def _create_remote_pty_session(
    session_id, cols, rows, command, env, cwd
) -> PtySession | None:
    info = pty_client.ensure_host(pty_client.instance_key())
    if info is None:
        return None
    request = {
        "op": "create",
        "id": session_id,
        "cols": cols,
        "rows": rows,
        "command": command,
        # The host's own environment is stale; send the backend's current one.
        "env": {**os.environ, **(env or {})},
        "cwd": os.path.abspath(cwd) if cwd else None,
    }
    try:
        reply = pty_client.host_request(info, request)
        if reply.get("error") == "exists":
            pty_client.host_request(info, {"op": "close", "id": session_id})
            reply = pty_client.host_request(info, request)
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error", "PTY host refused the session"))
        remote = pty_client.RemotePty(info, session_id)
    except pty_client.HostError:
        logger.exception("PTY host unavailable; falling back to an in-process PTY")
        return None
    return PtySession(remote, start_offset=remote.start_offset)


def create_pty_session(
    session_id: str,
    cols: int = 220,
    rows: int = 24,
    command: list[str] | None = None,
    env: dict | None = None,
    cwd: str | None = None,
) -> PtySession:
    """Spawn a PTY and register it under session_id. Returns the session.

    Pass `command`/`env` to run a specific process (e.g. `opencode attach`)
    instead of a bare shell - see pty_spawn.spawn_pty for why direct spawn is used
    instead of typing the command into a shell after the fact. `cwd` is
    unused by OpenCode's own attach (it talks to an already-running server
    over HTTP, so the PTY's working directory is irrelevant) - added for
    generic-agent CLIs (Claude Code, Codex, Crush) that operate on "the
    current directory" the way a human would after `cd`-ing into a repo.
    """
    entry = None
    if pty_client.host_enabled():
        entry = _create_remote_pty_session(session_id, cols, rows, command, env, cwd)
    if entry is None:
        pty = spawn_pty(cols=cols, rows=rows, command=command, env=env, cwd=cwd)
        entry = PtySession(pty)
    _pty_sessions[session_id] = entry
    return entry


def close_pty_session(session_id: str) -> None:
    entry = _pty_sessions.pop(session_id, None)
    if entry:
        try:
            entry.close()
        except Exception:
            pass


def is_pty_alive(session_id: str) -> bool:
    """True iff a PTY registered under session_id exists and its process is still
    running. Process-liveness only — see is_pty_viewed for the reaper's stronger
    'terminal actually on-screen' signal."""
    entry = get_pty_session(session_id)
    if not entry or entry.done:
        return False
    try:
        return bool(entry.isalive())
    except Exception:
        return False


def is_pty_viewed(session_id: str, grace_seconds: float = 90.0) -> bool:
    """True iff the PTY is alive AND its terminal is actually being viewed — a
    WebSocket is connected now, or was connected within `grace_seconds` (to bridge
    reconnect blips / tab refreshes). This is the signal the OpenCode reaper uses
    to protect an in-use terminal's server: gating on process-liveness alone would
    let a CLOSED browser tab (whose `opencode attach` process lingers) pin the
    server open forever, exhausting the port range. Gating on 'viewed' means a
    forgotten/closed terminal stops protecting its server once the grace lapses,
    so the normal idle reaper reclaims it."""
    if not is_pty_alive(session_id):
        return False
    entry = _pty_sessions.get(session_id)
    if not entry:
        return False
    if entry.ws_clients > 0:
        return True
    return (time.time() - entry.ws_disconnected_at) < grace_seconds


def write_pty_session(session_id: str, data: str) -> bool:
    """Write input to a named PTY. Returns False if session not found."""
    entry = get_pty_session(session_id)
    if not entry or entry.done:
        return False
    try:
        entry.write(data)
        return True
    except Exception:
        return False


@router.websocket("/api/terminal/agent")
async def agent_terminal_ws(ws: WebSocket, session_id: str, seq: int = 0):
    """Named PTY WebSocket for coding agent sessions.

    Connects to an existing named PTY (created by the code agent route).
    On reconnect, replays buffered output so the client sees what it missed.
    Multiple clients can connect to the same session (all read, all can write).

    Same message protocol as /api/terminal/ws.
    """
    entry = await asyncio.get_running_loop().run_in_executor(
        None, get_pty_session, session_id
    )
    if not entry:
        # NOT an exit: the PTY either hasn't been created yet (the client can
        # race the spawn, which squats a pool slot for ~15-20s) or it was
        # idle-reaped while the client kept the id in its session state.
        # Sending "exit" here made the client mark the session permanently dead
        # and skip its own reconnect backoff, so the terminal never painted and
        # only a manual restart recovered it. "notready" lets the client retry.
        await ws.accept()
        await ws.send_text(
            json.dumps({"type": "notready", "data": "Session not ready."})
        )
        await ws.close()
        return

    await ws.accept()

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    already_done = entry.done
    start_seq = seq

    # Mark this terminal as on-screen (a live viewer) for the reaper's
    # is_pty_viewed check. Decremented + timestamped in the finally below so a
    # closed tab stops protecting the server once the grace window lapses.
    entry.ws_clients += 1

    try:
        from skills.code_agent.projects import set_active_pty_session

        set_active_pty_session(session_id)
    except Exception:
        pass

    async def pump_pty_to_ws():
        # The session's own reader thread fills the buffer; this only forwards
        # it. Starting at the client's last seen seq replays just what it missed;
        # a fresh terminal (no seq) gets the whole buffer.
        wake = entry.subscribe(loop)
        # A seq past the stream's end belongs to a different stream: start over.
        # A negative seq means "from now": no replay, only new output.
        end = entry.read_from(max(start_seq, 0))[1]
        if start_seq < 0:
            seq = end
        else:
            seq = start_seq if start_seq <= end else 0
        try:
            while not stop.is_set():
                wake.clear()
                finished = entry.done
                data, seq = entry.read_from(seq)
                if data:
                    try:
                        await ws.send_text(
                            json.dumps({"type": "output", "data": data, "seq": seq})
                        )
                    except Exception:
                        return
                if finished:
                    break
                await wake.wait()
        finally:
            entry.unsubscribe(wake)
        stop.set()
        try:
            await ws.send_text(
                json.dumps(
                    {
                        "type": "exit",
                        "data": None
                        if already_done
                        else "OpenCode process exited unexpectedly.",
                    }
                )
            )
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
                        entry.write(data)
                    except Exception:
                        break
            elif mtype == "resize":
                try:
                    entry.resize(int(msg.get("cols", 80)), int(msg.get("rows", 24)))
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("agent terminal websocket error")
    finally:
        stop.set()
        pump_task.cancel()
        # This viewer is gone; record when so is_pty_viewed's grace window starts.
        # The session (and its reader) keeps running; only the viewer count
        # drops. Guard against a popped entry (close raced the disconnect).
        if _pty_sessions.get(session_id) is entry:
            entry.ws_clients = max(0, entry.ws_clients - 1)
            entry.ws_disconnected_at = time.time()
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
    pty = spawn_pty(cols=80, rows=24)
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
