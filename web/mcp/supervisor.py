"""Background supervisor for spawned preset MCP servers.

Preset servers like Google Workspace run as detached HTTP processes that
this app does not own as child processes. When they die (crash, machine
restart, OAuth token expiry), nothing restarts them — the user has to
manually Disconnect and Connect again.

This module runs a daemon thread that pings each spawned server every
_SUPERVISOR_INTERVAL seconds. If a server is down, it respawns it from
the persisted spawn spec. This keeps the server alive without user
intervention.

Startup respawn (respawn_all_on_startup) is called from app.py's lifespan
to handle the "machine rebooted, processes orphaned" case. The supervisor
thread then keeps them alive for the rest of the session.
"""
from __future__ import annotations

import logging
import threading
import time

from config import load_config

_log = logging.getLogger(__name__)

_SUPERVISOR_INTERVAL = 60.0  # seconds between health checks
_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _port_from_url(url: str) -> int | None:
    from urllib.parse import urlparse
    if not url:
        return None
    try:
        parsed = urlparse(url)
        if parsed.port:
            return parsed.port
    except Exception:
        pass
    return None


def _is_server_alive(spec: dict) -> bool:
    """Quick TCP port check — cheaper than a full MCP health_check ping."""
    port = _port_from_url(spec.get("url", ""))
    if not port:
        return False
    return _port_open("127.0.0.1", port, timeout=2.0)


def _respawn(spec: dict) -> bool:
    """Respawn a server from its persisted spawn spec. Returns True on success."""
    from routes.mcp_routes import _spawn_server_process
    command = spec.get("command", "")
    args = spec.get("args", [])
    env = spec.get("env", {})
    url = spec.get("url", "")
    if not command or not args:
        _log.warning("[supervisor] skipping respawn — missing command/args in spec: %r", spec)
        return False
    result = _spawn_server_process(command, args, env, url, wait_for_port=False)
    if result.get("ok"):
        _log.info("[supervisor] respawned %s %s (pid=%s)", command, ' '.join(args), result.get("pid"))
        return True
    _log.warning("[supervisor] respawn failed for %s %s: %s", command, ' '.join(args), result.get("error"))
    return False


def _check_and_respawn_all() -> None:
    """Ping every persisted spawn spec; respawn any that are down."""
    try:
        specs = list(load_config().get("mcp_spawn_specs", {}).values())
    except Exception:
        return
    for spec in specs:
        try:
            if not _is_server_alive(spec):
                _log.info("[supervisor] server down, respawning: %s", spec.get("command", "?"))
                _respawn(spec)
        except Exception:
            _log.debug("[supervisor] error checking spec", exc_info=True)


def _supervisor_loop() -> None:
    """Background loop: ping every _SUPERVISOR_INTERVAL seconds, respawn dead servers."""
    _log.info("[supervisor] started (interval=%ds)", int(_SUPERVISOR_INTERVAL))
    while not _stop_event.is_set():
        try:
            _check_and_respawn_all()
        except Exception:
            _log.debug("[supervisor] unexpected error in loop", exc_info=True)
        _stop_event.wait(_SUPERVISOR_INTERVAL)
    _log.info("[supervisor] stopped")


def respawn_all_on_startup() -> None:
    """Respawn all persisted spawn spec servers whose port is not open.

    Called from app.py lifespan at startup. Handles the "machine rebooted"
    case — the spawned processes are gone but the spawn specs are on disk.
    Does NOT wait for ports to bind (the supervisor will verify on its
    next tick), so this doesn't block startup.
    """
    try:
        specs = list(load_config().get("mcp_spawn_specs", {}).values())
    except Exception:
        return
    if not specs:
        return
    _log.info("[supervisor] startup respawn: checking %d spawn spec(s)", len(specs))
    for spec in specs:
        try:
            if _is_server_alive(spec):
                _log.info("[supervisor] startup: %s already alive on port, skipping",
                          spec.get("command", "?"))
                continue
            _respawn(spec)
        except Exception:
            _log.debug("[supervisor] startup respawn error for spec", exc_info=True)


def start_supervisor() -> None:
    """Start the background supervisor thread. Idempotent — safe to call
    multiple times (only starts one thread). Called from app.py lifespan."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_supervisor_loop, daemon=True, name="mcp-supervisor")
    _thread.start()


def stop_supervisor() -> None:
    """Signal the supervisor thread to stop. Called from app.py lifespan shutdown."""
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=5)
