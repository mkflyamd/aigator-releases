"""Which OS processes currently hold a coding-agent session open.

Gator only knows about the terminals it spawned itself. A probe asks the agent's own
on-disk registry about every process on this machine, so a session resumed from another
window is seen too. Each live process is a dict:

    {"pid": int, "session_id": str, "name": str | None, "started_at": float, "source": str}

To support another agent, write ``def probe(session_id=None) -> list[dict]`` and add it
to ``PROBES``. Nothing else needs to change.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Callable

import psutil

logger = logging.getLogger(__name__)

_FILETIME_UNIX_EPOCH = 11644473600
_START_TOLERANCE_S = 2.0

Probe = Callable[..., list]


def _filetime_to_epoch(filetime: int) -> float:
    return filetime / 1e7 - _FILETIME_UNIX_EPOCH


def _same_process(entry: dict) -> bool:
    """True if the pid is alive and is the process that wrote the entry, not a reused pid."""
    try:
        created = psutil.Process(int(entry["pid"])).create_time()
    except (psutil.Error, KeyError, TypeError, ValueError):
        return False
    proc_start = entry.get("procStart")
    if proc_start is not None:
        try:
            return abs(created - _filetime_to_epoch(int(proc_start))) <= _START_TOLERANCE_S
        except (TypeError, ValueError):
            return False
    started_ms = entry.get("startedAt")
    if isinstance(started_ms, (int, float)):
        return created <= started_ms / 1000 + _START_TOLERANCE_S
    return False


def _claude_probe(session_id: str | None = None) -> list[dict]:
    root = Path.home() / ".claude" / "sessions"
    try:
        files = sorted(root.glob("*.json"))
    except OSError:
        return []
    found = []
    for path in files:
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(entry, dict) or not entry.get("sessionId") or "pid" not in entry:
            continue
        if session_id is not None and entry["sessionId"] != session_id:
            continue
        domain = entry.get("pidDomain")
        if sys.platform == "win32" and isinstance(domain, str) and not domain.startswith("win32:"):
            continue
        if not _same_process(entry):
            continue
        started = entry.get("startedAt")
        found.append({
            "pid": int(entry["pid"]),
            "session_id": entry["sessionId"],
            "name": entry.get("name") or None,
            "started_at": started / 1000 if isinstance(started, (int, float)) else 0.0,
            "source": "claude-registry",
        })
    return found


def _no_registry(session_id: str | None = None) -> list[dict]:
    return []


PROBES: dict[str, Probe] = {
    "claude": _claude_probe,
    "codex": _no_registry,
    "crush": _no_registry,
}


def owning_pty(pid: int, pty_pids: dict[int, str]) -> str | None:
    """The Gator PTY whose child process is pid or one of its ancestors, else None."""
    if not pty_pids:
        return None
    try:
        proc = psutil.Process(pid)
        chain = [proc, *proc.parents()]
    except psutil.Error:
        return None
    for p in chain:
        owner = pty_pids.get(p.pid)
        if owner:
            return owner
    return None


# Executable names (lowercase, no .exe) of the programs an agent can run under.
_APPS = {
    "orca": "Orca",
    "claude": "Claude desktop",
    "windowsterminal": "Windows Terminal",
    "code": "VS Code",
    "cursor": "Cursor",
    "gnome-terminal-server": "Terminal",
    "konsole": "Terminal",
    "iterm2": "iTerm",
    "terminal": "Terminal",
}
_SHELLS = {"pwsh": "PowerShell", "powershell": "PowerShell", "cmd": "Command Prompt"}


def _exe_stem(name: str) -> str:
    name = name.lower()
    return name[:-4] if name.endswith(".exe") else name


def location_label(pid: int) -> str | None:
    """The app a live agent process runs under (Orca, Claude desktop, ...), from its ancestry."""
    try:
        names = [_exe_stem(p.name()) for p in psutil.Process(pid).parents()]
    except psutil.Error:
        return None
    for name in names:
        if name in _APPS:
            return _APPS[name]
    for name in names:
        if name in _SHELLS:
            return _SHELLS[name]
    return None


class TakeoverError(Exception):
    """A session open outside Gator could not be closed; the message is safe to show the user."""


_EXIT_WAIT_S = 5.0


def _safe_parents(pid: int) -> list:
    try:
        return psutil.Process(pid).parents()
    except psutil.Error:
        return []


def _end(proc: psutil.Process, hard: bool) -> None:
    try:
        proc.kill() if hard else proc.terminate()
    except psutil.NoSuchProcess:
        pass
    except psutil.Error as exc:
        raise TakeoverError(f"Gator could not close process {proc.pid} ({exc}). Close it yourself, then try again.")


def takeover(agent: str, session_id: str, owners: dict[int, str]) -> list[int]:
    """End the processes outside Gator that hold session_id open, and return their pids.

    The agent's own registry decides what is ended (live_processes re-checks that the pid is
    the registered process and that the registry session matches). Only that process and its
    children are ended: never a Gator-owned PTY, this server, or anything above either.
    """
    targets = []
    for entry in live_processes(agent, session_id):
        if owning_pty(entry["pid"], owners):
            continue
        try:
            targets.append(psutil.Process(entry["pid"]))
        except psutil.Error:
            continue
    own = {os.getpid(), *(p.pid for p in _safe_parents(os.getpid()))}
    victims = []
    for proc in targets:
        try:
            tree = [proc, *proc.children(recursive=True)]
        except psutil.Error:
            continue
        if own & {p.pid for p in tree}:
            raise TakeoverError("This session is running in the same process tree as Gator, so Gator cannot close it.")
        victims.extend(tree)
    for proc in victims:
        _end(proc, hard=False)
    _, alive = psutil.wait_procs(victims, timeout=_EXIT_WAIT_S)
    for proc in alive:
        _end(proc, hard=True)
    _, alive = psutil.wait_procs(alive, timeout=_EXIT_WAIT_S)
    if alive:
        raise TakeoverError(f"Gator could not close process {alive[0].pid}. Close it yourself, then try again.")
    return [p.pid for p in targets]


def live_processes(agent: str, session_id: str | None = None) -> list[dict]:
    probe = PROBES.get(agent)
    if probe is None:
        return []
    try:
        return probe(session_id)
    except Exception:
        logger.exception("live-session probe failed for %s", agent)
        return []
