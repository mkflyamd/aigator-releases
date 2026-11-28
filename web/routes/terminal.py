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
_ADOPT_REPLAY_TIMEOUT = 5.0


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
        # The host replays its retained output into the new buffer on a reader
        # thread. A client resuming at its last seq must not see a short stream
        # end and mistake it for a different stream, so wait for the replay. If
        # it does not arrive, fail the adopt: drop our connection (the agent keeps
        # running in the host) and let a later lookup try again.
        if not entry.wait_for_offset(remote.end_offset, _ADOPT_REPLAY_TIMEOUT):
            logger.warning(
                "PTY session %s: host replay did not finish in %.0fs; not adopting",
                session_id,
                _ADOPT_REPLAY_TIMEOUT,
            )
            remote.detach()
            return None
        _pty_sessions[session_id] = entry
        return entry


class HostUnreachable(Exception):
    """The PTY host is running but did not answer, so what it holds is unknown."""


def _list_host_sessions(strict: bool = False) -> list[dict]:
    """Sessions the host holds. A host that is off, or that never ran, holds none. A
    host that does not answer yields none too, unless `strict`, which raises
    HostUnreachable so a caller can tell "no sessions" from "could not ask"."""
    if not pty_client.host_enabled():
        return []
    key = pty_client.instance_key()
    info = pty_client.find_host(key)
    if info is None:
        if strict and pty_client.host_process_running(key):
            raise HostUnreachable("the PTY host did not answer")
        return []
    try:
        return pty_client.host_request(info, {"op": "list"}).get("sessions", [])
    except pty_client.HostError:
        logger.warning("could not ask the PTY host for sessions", exc_info=True)
        if strict:
            raise HostUnreachable("the PTY host did not answer") from None
        return []


def host_sessions() -> list[dict]:
    """Every session the PTY host holds. Raises HostUnreachable when the host does not
    answer. Blocking."""
    return _list_host_sessions(strict=True)


def host_session_labels(session_id: str, strict: bool = False) -> dict:
    """The labels the host holds for one session (empty if unknown). Blocking."""
    for s in _list_host_sessions(strict):
        if s["id"] == session_id:
            return s.get("meta") or {}
    return {}


def session_owner(session_id: str, strict: bool = False) -> dict[str, str] | None:
    """The project and agent labels a session was created with, or None when they
    are unknown. A session this backend created carries them; one adopted from the
    PTY host after a restart is looked up there. With `strict`, a host that does
    not answer raises HostUnreachable instead of reading as "no labels".
    Blocking (loopback socket)."""
    meta = getattr(_pty_sessions.get(session_id), "meta", None)
    return meta or host_session_labels(session_id, strict) or None


def find_host_session(owner: dict[str, str]) -> str | None:
    """Id of the newest live session the host holds for `owner` (the labels given
    when it was created), or None. After a backend restart this is how a project
    finds the agent that is still running for it. Blocking (loopback socket)."""
    listed = _list_host_sessions()
    # The host lists sessions in creation order; the last match is the newest.
    mine = [
        s["id"]
        for s in listed
        if not s.get("done")
        and all((s.get("meta") or {}).get(k) == v for k, v in owner.items())
    ]
    return mine[-1] if mine else None


def _create_remote_pty_session(
    session_id, cols, rows, command, env, cwd, meta=None
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
    if meta:
        request["meta"] = meta
    try:
        reply = pty_client.host_request(info, request, pty_client.CREATE_TIMEOUT)
        if reply.get("error") == "exists":
            pty_client.host_request(info, {"op": "close", "id": session_id})
            reply = pty_client.host_request(info, request, pty_client.CREATE_TIMEOUT)
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error", "PTY host refused the session"))
        remote = pty_client.RemotePty(info, session_id)
    except pty_client.HostError:
        logger.exception("PTY host unavailable; falling back to an in-process PTY")
        # The host may have spawned the process even though the reply was lost;
        # drop it so it does not run on under the same id with no owner.
        try:
            pty_client.host_request(info, {"op": "close", "id": session_id})
        except pty_client.HostError:
            pass
        return None
    return PtySession(remote, start_offset=remote.start_offset)


def create_pty_session(
    session_id: str,
    cols: int = 220,
    rows: int = 24,
    command: list[str] | None = None,
    env: dict | None = None,
    cwd: str | None = None,
    meta: dict[str, str] | None = None,
) -> PtySession:
    """Spawn a PTY and register it under session_id. Returns the session.

    `meta` labels who the session belongs to (project and agent). The PTY host
    keeps it, so a restarted backend can find the session again.

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
        entry = _create_remote_pty_session(
            session_id, cols, rows, command, env, cwd, meta
        )
    if entry is None:
        pty = spawn_pty(cols=cols, rows=rows, command=command, env=env, cwd=cwd)
        entry = PtySession(pty)
    entry.meta = dict(meta) if meta else None
    _pty_sessions[session_id] = entry
    return entry


def live_pty_labels(strict: bool = False) -> dict[str, dict]:
    """id -> labels for every live PTY: those the PTY host holds (including ones
    this backend has not adopted since a restart) and in-process ones. With `strict`,
    a host that does not answer raises HostUnreachable instead of reading as "none".
    Blocking."""
    found = {s["id"]: s.get("meta") or {} for s in _list_host_sessions(strict) if not s.get("done")}
    for session_id, entry in list(_pty_sessions.items()):
        if not entry.done and session_id not in found:
            found[session_id] = entry.meta or {}
    return found


def close_pty_session(session_id: str) -> bool:
    """Close a PTY. True when it is gone (or never existed), False when closing failed."""
    import agent_mcp

    closed = _close_pty_session(session_id)
    if closed:
        agent_mcp.revoke(session_id)
    return closed


def _close_pty_session(session_id: str) -> bool:
    entry = _pty_sessions.pop(session_id, None)
    if entry:
        try:
            entry.close()
        except Exception:
            logger.warning("could not close PTY session %s", session_id, exc_info=True)
            return False
        return True
    # Not adopted by this backend (it restarted since): the host still has it.
    info = pty_client.find_host(pty_client.instance_key()) if pty_client.host_enabled() else None
    if info is None:
        return True
    try:
        pty_client.host_request(info, {"op": "close", "id": session_id})
    except pty_client.HostError:
        logger.warning("could not close PTY session %s on the host", session_id)
        return False
    return True


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


def pty_alive_strict(session_id: str) -> bool:
    """is_pty_alive that never guesses: the PTY host is asked, and one that does not answer
    raises HostUnreachable instead of reading as "not running". An in-process PTY (no host
    behind it) is judged locally. Blocking."""
    for s in _list_host_sessions(strict=True):
        if s["id"] == session_id:
            return not s.get("done")
    entry = _pty_sessions.get(session_id)
    if entry is None or isinstance(entry.pty, pty_client.RemotePty) or entry.done:
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
    return is_pty_alive(session_id) and has_viewer(
        session_id, grace_seconds, visible_only=False
    )


def has_viewer(
    session_id: str, grace_seconds: float = 90.0, visible_only: bool = True
) -> bool:
    """True iff a WebSocket is connected to this backend's session now, or was
    within `grace_seconds`. A connection whose tab reported itself hidden does not
    count unless visible_only is False. Never adopts a session from the PTY host:
    one this backend has not adopted has no viewer."""
    entry = _pty_sessions.get(session_id)
    if not entry:
        return False
    connected = entry.ws_clients
    if visible_only:
        connected -= len(entry.ws_hidden)
    if connected > 0:
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


def _agent_exit_text(meta: dict | None) -> str:
    """The exit notice for an agent session, naming the agent when its labels are known."""
    agent = (meta or {}).get("agent")
    if not agent:
        return "The agent process exited unexpectedly."
    from generic_agent import agent_label

    return f"{agent_label(agent)} process exited unexpectedly."


def _suspended_payload(record: dict) -> dict:
    payload = {
        "type": "suspended",
        "data": "Suspended - click to resume",
        "session_id": record["session_id"],
    }
    if record.get("failed"):
        payload["failed"] = record["failed"]
    return payload


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
        import agent_suspend

        suspended = await asyncio.to_thread(agent_suspend.suspended_record, session_id)
        if suspended:
            await ws.accept()
            await ws.send_text(json.dumps(_suspended_payload(suspended)))
            await ws.close()
            return
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
    entry.size_owner = ws

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
        # The replay begins mid-stream when the buffer has already dropped what
        # this client would have seen next; tell it so it can repaint.
        if seq < entry.first_offset:
            try:
                await ws.send_text(json.dumps({"type": "truncated"}))
            except Exception:
                entry.unsubscribe(wake)
                return
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
        import agent_suspend

        # A suspend records the session before it kills the process, so a viewer
        # that attached in between is told to offer a resume, not "exited".
        suspended = await asyncio.to_thread(agent_suspend.suspended_record, session_id)
        try:
            if suspended:
                final = _suspended_payload(suspended)
            else:
                final = {
                    "type": "exit",
                    "data": None
                    if already_done
                    else _agent_exit_text(getattr(entry, "meta", None)),
                }
            await ws.send_text(json.dumps(final))
        except Exception:
            pass

    woken_by = (getattr(entry, "meta", None) or {}).get("woken_by")
    if woken_by:
        try:
            await ws.send_text(
                json.dumps(
                    {
                        "type": "woken",
                        "data": f"woken by {woken_by}",
                        "by": woken_by,
                        "at": entry.meta.get("woken_at", ""),
                        "preview": entry.meta.get("woken_preview", ""),
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
                    entry.size_owner = ws
                    entry.last_user_input = time.time()
                    try:
                        entry.write(data)
                    except Exception:
                        break
            elif mtype == "visible":
                if msg.get("value") is False:
                    entry.ws_hidden.add(ws)
                    if entry.ws_clients - len(entry.ws_hidden) <= 0:
                        entry.ws_disconnected_at = time.time()
                else:
                    entry.ws_hidden.discard(ws)
            elif mtype == "resize" and entry.size_owner in (None, ws):
                entry.size_owner = ws
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
        if entry.size_owner is ws:
            entry.size_owner = None
        # This viewer is gone; record when so is_pty_viewed's grace window starts.
        # The session (and its reader) keeps running; only the viewer count
        # drops. Guard against a popped entry (close raced the disconnect).
        entry.ws_hidden.discard(ws)
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
