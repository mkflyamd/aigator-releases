"""Which OS processes currently hold a coding-agent session open.

Gator only knows about the terminals it spawned itself. A probe asks the agent's own
on-disk registry about every process on this machine, so a session resumed from another
window is seen too. Each live process is a dict:

    {"pid": int, "session_id": str, "name": str | None, "started_at": float,
     "created": float, "source": str}

``created`` is the OS creation time of the process. With ``pid`` it names exactly one
process, which is what a takeover confirmation is bound to.

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


def _registered_create_time(entry: dict) -> float | None:
    """The process's creation time if the pid is alive and is the process that wrote the
    entry, not a reused pid; otherwise None."""
    try:
        created = psutil.Process(int(entry["pid"])).create_time()
    except (psutil.Error, KeyError, TypeError, ValueError):
        return None
    proc_start = entry.get("procStart")
    if proc_start is not None:
        try:
            ok = abs(created - _filetime_to_epoch(int(proc_start))) <= _START_TOLERANCE_S
        except (TypeError, ValueError):
            return None
        return created if ok else None
    started_ms = entry.get("startedAt")
    if isinstance(started_ms, (int, float)) and created <= started_ms / 1000 + _START_TOLERANCE_S:
        return created
    return None


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
        created = _registered_create_time(entry)
        if created is None:
            continue
        started = entry.get("startedAt")
        found.append({
            "pid": int(entry["pid"]),
            "session_id": entry["sessionId"],
            "name": entry.get("name") or None,
            "started_at": started / 1000 if isinstance(started, (int, float)) else 0.0,
            "created": created,
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
    """A session open outside Gator could not be closed; the message is safe to show the user.

    code is "process_changed" when the process the user confirmed no longer holds the session,
    "not_closable" when Gator does not close that kind of process, else "takeover_failed".
    """

    def __init__(self, message: str, code: str = "takeover_failed"):
        super().__init__(message)
        self.code = code


_EXIT_WAIT_S = 5.0
_CREATE_TOLERANCE_S = 0.01

# Per agent, the executables Gator will end on its own. A node or bun runtime only counts when
# its command line names the agent.
_AGENT_EXES = {"claude": {"claude"}}
_RUNTIME_EXES = {"node", "bun"}


def _create_time_matches(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= _CREATE_TOLERANCE_S


def closable(agent: str, pid: int) -> tuple[bool, str | None]:
    """Whether Gator may end pid on its own and, if not, why (a sentence for the user)."""
    exes = _AGENT_EXES.get(agent)
    try:
        proc = psutil.Process(pid)
        stem = _exe_stem(proc.name())
        cmdline = " ".join(proc.cmdline()).lower() if stem in _RUNTIME_EXES else ""
    except psutil.Error:
        return False, "Gator could not inspect this process. Close it yourself, then try again."
    known = bool(exes) and (stem in exes or (stem in _RUNTIME_EXES and any(e in cmdline for e in exes)))
    if not known:
        return False, "Gator does not recognise this process as the agent. Close it yourself, then try again."
    if location_label(pid) is None:
        return False, "Gator cannot tell which app this session is running in. Close it yourself, then try again."
    return True, None


def describe(agent: str, proc: dict, owners_known: bool = True) -> dict:
    """What the user sees and confirms before a takeover: the process, where it runs, and
    whether Gator may close it."""
    ok, reason = closable(agent, proc["pid"])
    if ok and not owners_known:
        ok, reason = False, "Gator could not check its own terminals. Try again."
    return {
        "app": location_label(proc["pid"]),
        "pid": proc["pid"],
        "created": proc.get("created"),
        "session_id": proc["session_id"],
        "can_close": ok,
        "reason": reason,
    }


def _safe_parents(pid: int) -> list:
    try:
        return psutil.Process(pid).parents()
    except psutil.Error:
        return []


def _end(proc: psutil.Process, hard: bool) -> None:
    try:
        if not proc.is_running():
            return
        proc.kill() if hard else proc.terminate()
    except psutil.NoSuchProcess:
        pass
    except psutil.Error as exc:
        raise TakeoverError(f"Gator could not close process {proc.pid} ({exc}). Close it yourself, then try again.")


def _running(procs: list) -> list:
    """The procs that are still executing. A zombie has exited and only awaits its parent's wait()."""
    out = []
    for proc in procs:
        try:
            if proc.status() != psutil.STATUS_ZOMBIE:
                out.append(proc)
        except psutil.NoSuchProcess:
            pass
    return out


def _changed() -> TakeoverError:
    return TakeoverError(
        "This session is no longer open in the process you confirmed. Check where it is open now, then try again.",
        code="process_changed",
    )


def _confirmed_process(pid: int, created: float) -> psutil.Process:
    """The live process for pid, only if it was created at `created`."""
    try:
        proc = psutil.Process(pid)
        matches = _create_time_matches(proc.create_time(), created)
    except psutil.Error:
        raise _changed()
    if not matches:
        raise _changed()
    return proc


def takeover(agent: str, session_id: str, owners: dict[int, str], pid: int, created: float) -> list[int]:
    """End the one process (pid, created) holding session_id open outside Gator, and its
    children. Return [pid].

    Only the process the user confirmed is ended: if the agent's registry no longer shows
    exactly that process for the session, nothing is ended ("process_changed"). The pid and
    creation time are checked again before the tree is enumerated and again before anything is
    signalled. Never a Gator-owned PTY, this server, or anything above either.
    """
    entry = next(
        (
            e
            for e in live_processes(agent, session_id)
            if e["pid"] == pid and _create_time_matches(e.get("created", -1.0), created)
        ),
        None,
    )
    if entry is None:
        raise _changed()
    if owning_pty(pid, owners):
        raise TakeoverError("This session is open in a Gator terminal, so Gator will not close it.")
    ok, reason = closable(agent, pid)
    if not ok:
        raise TakeoverError(reason, code="not_closable")
    target = _confirmed_process(pid, created)
    try:
        tree = [target, *target.children(recursive=True)]
    except psutil.Error:
        raise _changed()
    own = {os.getpid(), *(p.pid for p in _safe_parents(os.getpid()))}
    if own & {p.pid for p in tree}:
        raise TakeoverError("This session is running in the same process tree as Gator, so Gator cannot close it.")
    _confirmed_process(pid, created)
    logger.warning("takeover of %s session %s: ending pids %s", agent, session_id, [p.pid for p in tree])
    for proc in tree:
        _end(proc, hard=False)
    _, alive = psutil.wait_procs(tree, timeout=_EXIT_WAIT_S)
    alive = _running(alive)
    for proc in alive:
        _end(proc, hard=True)
    _, alive = psutil.wait_procs(alive, timeout=_EXIT_WAIT_S)
    alive = _running(alive)
    if alive:
        raise TakeoverError(f"Gator could not close process {alive[0].pid}. Close it yourself, then try again.")
    return [pid]


def live_processes(agent: str, session_id: str | None = None) -> list[dict]:
    probe = PROBES.get(agent)
    if probe is None:
        return []
    try:
        return probe(session_id)
    except Exception:
        logger.exception("live-session probe failed for %s", agent)
        return []
