"""Native shell execution — run_shell tool (bash/WSL -> PowerShell -> cmd)."""

import functools
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import sandbox
from sandbox import approvals as sandbox_approvals
from sandbox import runtime_copy, saved_permissions, task_grants
from sandbox.forward import ForwardedProcess
from sandbox.command_programs import programs_in
from sandbox.paths import PathNotGrantable, is_within, normalize_grant_paths
from sandbox.policy import load_policy

from proc_utils import (
    no_window_kwargs,
    watched_output_dirs,
    snapshot_outputs,
    diff_outputs,
)

SKILL_ID = "shell_runner"
# Foundational capability: gh/git/CLI access must be visible on every turn, not
# gated behind skill selection/inference (the brittle path that kept hiding it).
ALWAYS_ON = True

# ── Shell auto-detection (checked once at import time) ──────────────────────


def _detect_shell() -> tuple:
    """Return (shell_name, argv_prefix). Checked in priority order."""
    if os.name != "nt":
        bash = shutil.which("bash")
        if bash:
            return "bash", [bash, "-c"]
        sh = shutil.which("sh")
        if sh:
            return "sh", [sh, "-c"]
        raise RuntimeError("No supported shell found. Install bash or sh.")

    try:
        r = subprocess.run(
            ["wsl.exe", "bash", "--version"],
            capture_output=True,
            timeout=3,
            **no_window_kwargs(),
        )
        if r.returncode == 0:
            return "bash", ["wsl.exe", "bash", "-c"]
    except Exception:
        pass

    git_bash = r"C:\Program Files\Git\bin\bash.exe"
    if os.path.isfile(git_bash):
        try:
            r = subprocess.run(
                [git_bash, "--version"],
                capture_output=True,
                timeout=3,
                **no_window_kwargs(),
            )
            if r.returncode == 0:
                return "bash", [git_bash, "-c"]
        except Exception:
            pass

    try:
        r = subprocess.run(
            ["powershell.exe", "-Command", "$PSVersionTable"],
            capture_output=True,
            timeout=5,
            **no_window_kwargs(),
        )
        if r.returncode == 0:
            return "powershell", ["powershell.exe", "-Command"]
    except Exception:
        pass

    return "cmd", [os.environ.get("COMSPEC", "cmd.exe"), "/c"]


_DETECTED_SHELL, _DETECTED_ARGV = _detect_shell()

_PYTHON_COMMAND_RE = re.compile(
    r'^(?P<leading>\s*)(?P<quote>["\']?)(?P<executable>[^\s"\']+)(?P=quote)(?P<tail>\s+.*)?$',
    re.DOTALL,
)
_PYTHON_EXECUTABLES = {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}


def _quote_shell_argument(value: str, shell_used: str) -> str:
    if shell_used == "cmd":
        return subprocess.list2cmdline([value])
    if shell_used == "powershell":
        return "'" + value.replace("'", "''") + "'"
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _route_frozen_python(command: str, shell_used: str) -> str:
    if not getattr(sys, "frozen", False):
        return command
    match = _PYTHON_COMMAND_RE.match(command)
    if not match:
        return command
    executable = match.group("executable").replace("\\", "/").rsplit("/", 1)[-1].lower()
    if executable not in _PYTHON_EXECUTABLES:
        return command
    tail = match.group("tail") or ""
    return (
        match.group("leading")
        + _quote_shell_argument(sys.executable, shell_used)
        + " --run-python "
        + tail
    )


# Delete-op blocklist — statement-level check, not substring (issue #76).
# Substring match false-positived on heredoc bodies and command arguments
# that merely *mention* these words (e.g. "echo 'rm is dangerous'").
_DELETE_COMMANDS = {
    "rm",
    "del",
    "rmdir",
    "rd",
    "deltree",
    "format",
    "remove-item",
    "ri",
}

# Strip heredoc bodies before scanning. Matches: <<EOF ... \nEOF, <<'EOF' ... \nEOF, <<-EOF ... \n\tEOF
_HEREDOC_RE = re.compile(
    r"<<-?\s*['\"]?(\w+)['\"]?.*?\n.*?^\s*\1\s*$",
    re.DOTALL | re.MULTILINE,
)

# Shell statement separators — split command into individual statements
_STATEMENT_SEP_RE = re.compile(r"(?:;|&&|\|\||\||\n|\r)")


def _find_delete_command(command: str):
    """Find a destructive command invocation in `command`.

    Strips heredoc bodies, splits on shell separators, and checks the first
    token of each statement against the delete-command set. This avoids
    false positives from heredoc text or command arguments that merely
    mention these words.

    Returns (matched_token, position) where matched_token is the offending
    command name as it appeared in the source and position is its character
    offset in the original command, or (None, -1) if nothing matched.
    """
    stripped = _HEREDOC_RE.sub("", command)
    for stmt in _STATEMENT_SEP_RE.split(stripped):
        stmt = stmt.strip()
        if not stmt:
            continue
        # Strip leading env-var assignments and sudo/command prefixes
        tokens = stmt.split()
        idx = 0
        while idx < len(tokens) and (
            "=" in tokens[idx]
            and not tokens[idx].startswith(("-", "/"))
            or tokens[idx] in ("sudo", "command", "exec", "time", "nohup")
        ):
            idx += 1
        if idx >= len(tokens):
            continue
        raw = tokens[idx]
        first = raw.lower().lstrip("\\/")
        # Handle path-prefixed commands like /usr/bin/rm or ./rm
        first = first.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if first in _DELETE_COMMANDS:
            return raw, command.find(raw)
    return None, -1


def _has_delete_command(command: str) -> bool:
    """Boolean wrapper around _find_delete_command."""
    token, _ = _find_delete_command(command)
    return token is not None


# ── Background process support ───────────────────────────────────────────────
# run_shell normally blocks on subprocess.run(..., timeout=N). That's wrong for
# anything that doesn't exit on its own (an LLM inference server, `npm run dev`,
# a foreground `docker run`, `ssh host "<long-running server>"`) — the tool call
# blocks the whole turn, the chat goes silent, and it eventually just times out.
# background=True instead does subprocess.Popen (non-blocking), redirects
# stdout+stderr to a log file, and hands back a pid immediately. Mirrors Claude
# Code's own run_in_background design.
#
# Registry is in-memory/module-level and session-scoped: it is lost on app
# restart. A process started before a restart keeps running (it's detached),
# but check_shell_process/stop_shell_process fall back to psutil-only,
# best-effort handling for pids not present in the registry (see below) — the
# log_file/command fields just won't be known.
_BG_REGISTRY: dict[int, dict] = {}
_BG_LOG_COUNTER = itertools.count(1)

# ── Persistent PID file — survives server restarts so orphans can be cleaned ──
def _bg_pid_file():
    from config import WORK_DIR
    return WORK_DIR / "bg-pids.json"

def _persist_bg_pid(pid: int, command: str, log_file: str):
    """Record a background PID to disk so stop.ps1/startup can clean it up."""
    import json
    pf = _bg_pid_file()
    try:
        pf.parent.mkdir(parents=True, exist_ok=True)
        existing = json.loads(pf.read_text()) if pf.exists() else {}
        existing[str(pid)] = {"command": command[:120], "log_file": log_file,
                               "started_at": time.time()}
        pf.write_text(json.dumps(existing))
    except Exception:
        pass

def _remove_bg_pid(pid: int):
    import json
    pf = _bg_pid_file()
    try:
        if not pf.exists():
            return
        existing = json.loads(pf.read_text())
        existing.pop(str(pid), None)
        pf.write_text(json.dumps(existing))
    except Exception:
        pass


def _norm_cmd(text: str) -> str:
    return re.sub(r"[\s\"\\']+", "", text or "")


def cleanup_orphan_bg_procs():
    """Called at server startup — kill any background PIDs that survived a restart."""
    import json, psutil
    pf = _bg_pid_file()
    if not pf.exists():
        return
    try:
        existing = json.loads(pf.read_text())
    except Exception:
        return
    for pid_str, info in list(existing.items()):
        pid = int(pid_str)
        try:
            proc = psutil.Process(pid)
            recorded = _norm_cmd(info.get("command", ""))
            if not recorded or recorded not in _norm_cmd(" ".join(proc.cmdline())):
                continue
            # Only kill if it's actually still running and looks like a bg task
            if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                import logging
                logging.getLogger("shell_runner").warning(
                    "Killing orphaned background process PID %d: %s", pid, info.get("command", "")
                )
                try:
                    children = proc.children(recursive=True)
                    for c in children:
                        try: c.kill()
                        except Exception: pass
                    proc.kill()
                except Exception:
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    # Clear the file after cleanup
    try:
        pf.write_text("{}")
    except Exception:
        pass

# Run orphan cleanup at import time (server startup)
try:
    cleanup_orphan_bg_procs()
except Exception:
    pass


def _bg_log_path():
    """Return a fresh, guaranteed-unique path for a background command's log.

    Filenames combine our own pid + a monotonic counter + a nanosecond
    timestamp, since the child's pid isn't known until *after* Popen()
    returns (we need the path before spawning, to open it as the stdout
    handle).
    """
    from config import WORK_DIR

    log_dir = WORK_DIR / "bg-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    n = next(_BG_LOG_COUNTER)
    return log_dir / f"bg-{os.getpid()}-{n}-{time.time_ns()}.log"


def _read_log_tail(log_file: str, max_chars: int = 4000, max_lines: int = 50) -> str:
    """Best-effort tail of a background command's log file. Never raises —
    the file may not exist yet (process just started) or be locked."""
    if not log_file:
        return ""
    try:
        with open(log_file, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_chars * 4), os.SEEK_SET)
            data = f.read()
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()[-max_lines:]
        tail = "\n".join(lines)
        return tail[-max_chars:] if len(tail) > max_chars else tail
    except OSError:
        return ""


_MAX_BG_PROCS = 10
_BG_SPAWN_LOCK = threading.Lock()


def _bg_cap_error(shell_used: str) -> dict | None:
    running_procs = [
        {"pid": pid, "command": e.get("command", "")[:80],
         "started_at": e.get("started_at", 0), "log_file": e.get("log_file", "")}
        for pid, e in _BG_REGISTRY.items()
        if e.get("popen") and e["popen"].poll() is None and not e.get("stopped")
    ]
    if len(running_procs) < _MAX_BG_PROCS:
        return None
    return {
        "error": "BACKGROUND_PROCESS_CAP_REACHED",
        "cap": _MAX_BG_PROCS,
        "running": running_procs,
        "background": True, "pid": 0, "log_file": "", "shell_used": shell_used,
    }


def _spawn_background(
    command: str, argv_prefix: list, shell_used: str, cwd_path: str
) -> dict:
    """Start `command` detached/non-blocking, log its output to a file, and
    register it for later polling/killing. Returns immediately."""
    with _BG_SPAWN_LOCK:
        return _spawn_background_locked(command, argv_prefix, shell_used, cwd_path)


def _spawn_background_locked(command: str, argv_prefix: list, shell_used: str, cwd_path: str) -> dict:
    """Actual spawn logic — must only be called while holding _BG_SPAWN_LOCK."""
    capped = _bg_cap_error(shell_used)
    if capped:
        return capped
    try:
        log_path = _bg_log_path()
    except OSError as exc:
        return {
            "error": f"Could not prepare background log dir: {exc}",
            "background": True,
            "pid": 0,
            "log_file": "",
            "shell_used": shell_used,
        }

    try:
        log_handle = open(log_path, "wb")
    except OSError as exc:
        return {
            "error": f"Could not open background log file: {exc}",
            "background": True,
            "pid": 0,
            "log_file": str(log_path),
            "shell_used": shell_used,
        }

    popen_kwargs = dict(
        cwd=cwd_path,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    popen_kwargs.update(
        no_window_kwargs()
    )  # CREATE_NO_WINDOW on Windows, no-op elsewhere

    if os.name == "nt":
        # CREATE_NEW_PROCESS_GROUP detaches the child from our console/Ctrl+C
        # signal group so it survives independently of this tool call — while
        # remaining a perfectly normal, killable Windows process (verified: a
        # spawned test process keeps running after this call returns, and
        # psutil.Process(pid).terminate()/.kill() still work on it — see the
        # cross-platform test in tests/test_shell_background.py). Combined with
        # CREATE_NO_WINDOW (above) so no console window flashes.
        popen_kwargs["creationflags"] = (
            popen_kwargs.get("creationflags", 0) | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        # POSIX (macOS/Linux, and Git-Bash's underlying posix_spawn path):
        # start a new session so the child isn't in our process group and
        # doesn't get killed if our own controlling terminal/session goes away.
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(argv_prefix + [command], **popen_kwargs)
    except Exception as exc:
        log_handle.close()
        return {
            "error": str(exc),
            "background": True,
            "pid": 0,
            "log_file": str(log_path),
            "shell_used": shell_used,
        }
    finally:
        # The child inherited its own duplicate of the handle; our copy can
        # (and should) be closed now so we don't hold the file open forever.
        log_handle.close()

    # NOTE — WSL caveat: when shell_used == "bash" via wsl.exe, `proc.pid` here
    # is the Windows-side wsl.exe wrapper's pid, not the pid of the real
    # process running inside the WSL VM. Windows-side psutil (used by
    # check_shell_process/stop_shell_process) can only see/kill that wrapper —
    # it has no visibility into the WSL VM's process tree. This is a
    # fundamental cross-boundary limitation, not a bug: killing the wrapper
    # does tear down the wsl.exe invocation, but a process that double-forks
    # inside WSL could outlive it. macOS, Git Bash, PowerShell, and cmd don't
    # have this extra virtualization layer, so liveness/kill are exact there.
    log_file_str = str(log_path.resolve()) if log_path.exists() else str(log_path)
    _BG_REGISTRY[proc.pid] = {
        "popen": proc,
        "command": command,
        "log_file": log_file_str,
        "cwd": cwd_path,
        "shell_used": shell_used,
        "started_at": time.time(),
    }
    _persist_bg_pid(proc.pid, command, log_file_str)
    return {
        "background": True,
        "pid": proc.pid,
        "log_file": _BG_REGISTRY[proc.pid]["log_file"],
        "shell_used": shell_used,
        "message": (
            f"Started in background (pid {proc.pid}). "
            "Poll with check_shell_process, stop with stop_shell_process."
        ),
    }


def _tool_check_shell_process(pid: int) -> dict:
    """Poll a background process: is it running, what's its exit code (if any),
    and the tail of its log. Works for pids started by run_shell(background=True);
    for other pids, falls back to psutil-only liveness (no log/command known)."""
    pid = int(pid)
    entry = _BG_REGISTRY.get(pid)
    popen = entry.get("popen") if entry else None

    running = False
    exit_code = None
    note = None

    if popen is not None:
        rc = popen.poll()
        if rc is None:
            running = True
        else:
            running = False
            exit_code = rc
    else:
        note = "pid not tracked by this tool (started elsewhere, or the app restarted since it was launched) — liveness only, no known log/command."
        try:
            import psutil

            if psutil.pid_exists(pid):
                try:
                    running = psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    running = False
        except Exception:
            running = False

    log_file = entry.get("log_file", "") if entry else ""
    result = {
        "running": running,
        "exit_code": exit_code,
        "pid": pid,
        "log_file": log_file,
        "command": entry.get("command", "") if entry else "",
        "log_tail": _read_log_tail(log_file),
    }
    if note:
        result["note"] = note
    return result


def _tool_stop_shell_process(pid: int) -> dict:
    """Kill a background process AND its child tree (a shell-launched server
    commonly spawns children — killing only the top pid would orphan the real
    server). Never raises; every psutil call is guarded."""
    pid = int(pid)
    entry = _BG_REGISTRY.get(pid)
    if entry is None:
        return {
            "stopped": False,
            "pid": pid,
            "message": f"Process {pid} was not started by run_shell(background=true), so it will not be stopped.",
        }
    if entry.get("sandboxed"):
        entry["popen"].terminate()
        entry["stopped"] = True
        return {"stopped": True, "pid": pid, "message": f"Stopped process {pid} and its child processes."}

    try:
        import psutil
    except Exception:
        return {
            "stopped": False,
            "pid": pid,
            "message": "psutil is unavailable; cannot stop this process.",
        }

    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        if entry is not None:
            entry["stopped"] = True
        return {
            "stopped": True,
            "pid": pid,
            "message": f"Process {pid} was already gone.",
        }
    except psutil.AccessDenied as exc:
        return {
            "stopped": False,
            "pid": pid,
            "message": f"Access denied trying to stop pid {pid}: {exc}",
        }
    except Exception as exc:
        return {"stopped": False, "pid": pid, "message": str(exc)}

    try:
        children = proc.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = []
    targets = children + [proc]

    for p in targets:
        try:
            p.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    try:
        _gone, alive = psutil.wait_procs(targets, timeout=3)
    except Exception:
        alive = targets

    for p in alive:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        psutil.wait_procs(alive, timeout=2)
    except Exception:
        pass

    if entry is not None:
        # Reflect the exit into our Popen record (reaps the child on POSIX so
        # it doesn't linger as a zombie) so a subsequent check_shell_process
        # sees running=False/exit_code immediately instead of racing psutil.
        if entry.get("popen") is not None:
            try:
                entry["popen"].poll()
            except Exception:
                pass
        entry["stopped"] = (
            True  # mark, don't drop — check_shell_process still needs log_file/command
        )

    _remove_bg_pid(pid)
    return {
        "stopped": True,
        "pid": pid,
        "message": f"Stopped process {pid} and its child processes.",
    }


_BACKGROUND_REFUSED_MSG = (
    "Background commands are not available while the command sandbox is on. Run the command in the "
    "foreground with a timeout, or ask the user to start it themselves."
)
_BG_READY_TIMEOUT = 30
_BG_UNATTENDED_MSG = (
    "A background command needs a person in a chat tab to approve it and to use the forwarded port, so it "
    "cannot run unattended. Do not retry."
)


def _bg_sandbox_supported() -> bool:
    return os.name == "nt"


_SHELL_APPROVAL_MSG = (
    "The user must approve this access first; an approval card is now shown in the chat. Tell the user "
    "briefly what access you asked for and why, then stop and wait. When the user says they approved, "
    "call run_shell again with exactly the same command, cwd, extra_read_paths, extra_write_paths and "
    "network_hosts. If they deny, do not retry."
)
_BG_APPROVAL_MSG = _SHELL_APPROVAL_MSG.replace(
    "extra_write_paths and network_hosts", "extra_write_paths, network_hosts and background=true"
)
_SHELL_HINT = (
    "[sandbox] This command can only use its working folder and has no network. If it really needs more, "
    "re-call run_shell with cwd, extra_read_paths, extra_write_paths or network_hosts; the user will be "
    "asked to approve. git push and ssh need credentials the sandbox does not have: ask the user to "
    "run them. gh does not work here either: use the github_gh tool, which runs gh outside the sandbox "
    "with the user's own login (or the other github_* tools)."
)
_WINDOWS_SHELL_HINT = (
    "On Windows the sandboxed shell is cmd.exe: dir and git cannot run in it; use the file tools to list "
    "files and ask the user to run git."
)


def _shell_error(message: str, shell_used: str = "", **extra) -> dict:
    return {"error": message, "stdout": "", "stderr": "", "exit_code": -1,
            "shell_used": shell_used, "runtime_ms": 0, **extra}


@functools.lru_cache(maxsize=1)
def _npm_global_root() -> str | None:
    root = None
    try:
        root = subprocess.run("npm root -g", capture_output=True, text=True, timeout=5, shell=True,
                              **no_window_kwargs()).stdout.strip()
        if not root or not Path(root).is_dir():
            root = None
    except Exception:
        root = None
    if not root:
        fallback = Path.home() / "AppData" / "Roaming" / "npm" / "node_modules"
        if fallback.is_dir():
            root = str(fallback)
    return root


def _sandbox_shell(shell: str, is_windows: bool | None = None):
    """(argv_prefix, shell_used), or an error string. WSL is never used: it reaches the whole profile."""
    windows = os.name == "nt" if is_windows is None else is_windows
    if windows:
        if shell in ("bash", "powershell"):
            return ("With the sandbox on, commands run in cmd.exe on Windows (bash, WSL and PowerShell "
                    "cannot be sandboxed). Omit shell or use cmd, and write the command for cmd.exe.")
        comspec = os.environ.get("COMSPEC") or os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")
        return [comspec, "/c"], "cmd"
    if shell in ("powershell", "cmd"):
        return f"{shell} is not available with the sandbox on; commands run in {_DETECTED_SHELL}."
    if shell == "bash" and _DETECTED_SHELL != "bash":
        bash = shutil.which("bash")
        return ([bash, "-c"], "bash") if bash else "Bash is not available on this system."
    return list(_DETECTED_ARGV), _DETECTED_SHELL


def _drop_nested(paths) -> list:
    kept: list = []
    for path in sorted({Path(p) for p in paths}, key=lambda p: len(str(p))):
        if not any(is_within(path, k) for k in kept):
            kept.append(path)
    return kept


def _locate_cwd(cwd: str, policy, cr):
    """(run_cwd, project_to_grant_or_None, scratch), or an error string."""
    from config import WORK_DIR

    try:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        scratch = WORK_DIR.resolve()
    except OSError:
        return "The AI Gator working folder is not available; nothing was run."
    if not cwd:
        return scratch, None, scratch
    try:
        resolved = Path(cwd).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return "The working folder is not valid. Do not retry with this value."
    if is_within(resolved, scratch):
        if not resolved.is_dir():
            return "The working folder must be an existing folder. Do not retry with this value."
        return resolved, None, scratch
    if policy.filesystem == "strict":
        return cr._FS_REFUSED_MSG
    try:
        (project,) = normalize_grant_paths([cwd])
    except (PathNotGrantable, ValueError) as exc:
        return f"{exc} Do not retry with this value."
    if not project.is_dir():
        return "The working folder must be an existing folder. Do not retry with this value."
    return project, project, scratch


def _shell_gate(cr, command, read_paths, write_paths, hosts, context_id, policy, background=False):
    """An approval decision string (None when no access was needed), or a result dict to return as is."""
    if not background and not (read_paths or write_paths or hosts):
        return None
    tab = context_id or "default"
    read_s, write_s = [str(p) for p in read_paths], [str(p) for p in write_paths]

    def telemetry(decision: str) -> dict:
        return sandbox.telemetry_record("", "run_shell", "enforced", bool(hosts),
                                        len(read_paths), len(write_paths), decision)

    status, req = sandbox_approvals.lookup(tab, read_s, write_s, hosts, tool="run_shell", command=command,
                                           background=background)
    if status == "approved":
        if background:
            return "approved"
        return {"once": "approved", "task": "task_approved", "always": "saved_created"}[req.scope]
    if status == "denied":
        return _shell_error(cr._DENIED_MSG, _sandbox_telemetry=telemetry("denied"))
    if status == "expired":
        return _shell_error(cr._EXPIRED_MSG, _sandbox_telemetry=telemetry("expired"))
    programs = programs_in(command)
    if not background:
        if task_grants.covers(tab, read_s, write_s, hosts):
            return "task_approved"
        if policy.saved_permissions != "deny" and saved_permissions.covers(read_s, write_s, hosts, programs):
            return "saved"
    if req is None:
        req = sandbox_approvals.create(
            tab, read_s, write_s, hosts, tool="run_shell", command=command,
            programs=None if programs is None else tuple(sorted(programs)),
            saveable=not background and bool(programs) and policy.saved_permissions != "deny",
            background=background,
        )
    card = {
        "request_id": req.id, "read_paths": list(req.read_paths), "write_paths": list(req.write_paths),
        "network_hosts": list(req.network_hosts), "context_id": req.context_id, "tool": "run_shell",
        "command": req.command[:2000], "saveable": bool(req.saveable),
        "programs": list(req.programs or ()),
    }
    if background:
        card["background"] = True
    return {
        "approval_required": True, "request_id": req.id, "read_paths": card["read_paths"],
        "write_paths": card["write_paths"], "network_hosts": card["network_hosts"],
        "message": _BG_APPROVAL_MSG if background else _SHELL_APPROVAL_MSG, "_sandbox_approval": card,
        "_sandbox_telemetry": telemetry("requested"),
    }


def _with_shell_hint(cr, stderr: str) -> str:
    if stderr and (cr._PERMISSION_PATTERNS.search(stderr) or "Unable to read current working directory" in stderr):
        hint = _SHELL_HINT + (" " + _WINDOWS_SHELL_HINT if os.name == "nt" else "")
        return stderr.rstrip("\n") + "\n" + hint + "\n"
    return stderr


def _run_sandboxed(cr, command, shell, cwd, timeout, background, requested, policy, context_id) -> dict:
    if background and not _bg_sandbox_supported():
        return _shell_error(_BACKGROUND_REFUSED_MSG)
    if background and not context_id:
        return _shell_error(_BG_UNATTENDED_MSG)
    picked = _sandbox_shell(shell)
    if isinstance(picked, str):
        return _shell_error(picked, shell)
    argv_prefix, shell_used = picked
    if os.name == "nt":
        command = re.sub(r"\bpython3\b", "python", command)
    command = _route_frozen_python(command, shell_used)

    read_paths, write_paths, hosts = requested
    located = _locate_cwd(cwd, policy, cr)
    if isinstance(located, str):
        return _shell_error(located, shell_used)
    run_cwd, project, scratch = located
    if project is not None and project not in write_paths:
        write_paths = [*write_paths, project]

    gate = _shell_gate(cr, command, read_paths, write_paths, hosts, context_id, policy, background=background)
    if isinstance(gate, dict):
        return gate
    approval = gate

    npm_root = _npm_global_root()
    runtime_paths = cr._runtime_paths(None, npm_root)
    copies: list = []
    relay = None
    if background:
        try:
            runtime_paths = [p for p in runtime_paths if sandbox.container_readable(p)]
            copies = runtime_copy.readable_copies(
                command, os.environ.get("PATH", ""), sandbox.container_readable, runtime_copy.runtime_dir())
            relay = runtime_copy.install_relay()
        except runtime_copy.RuntimeCopyError as exc:
            return _shell_error(f"{exc} Nothing was run.", shell_used)
        runtime_paths = [*runtime_paths, *copies, relay.parent]
    if any(cr._runtime_path_refused(p) for p in runtime_paths):
        return _shell_error("The command sandbox refused to start because a runtime folder is not allowed. "
                            "Nothing was run. Tell the user; do not retry automatically.", shell_used)
    if os.name != "nt":
        for name in ("git", "npm"):
            found = shutil.which(name)
            if found and not cr._runtime_path_refused(Path(found).resolve().parent):
                runtime_paths.append(Path(found).resolve().parent)
        runtime_paths = _drop_nested(runtime_paths)

    run_id = uuid4().hex[:12]
    in_scratch = is_within(run_cwd, scratch)
    env_dir = run_cwd if in_scratch else scratch / f".run-{run_id}"
    sandbox_write = [p for p in write_paths if os.path.normcase(str(p)) != os.path.normcase(str(run_cwd))]
    try:
        if not in_scratch:
            env_dir.mkdir(parents=True, exist_ok=True)
            sandbox_write.append(env_dir)
    except OSError:
        return _shell_error("The command sandbox could not prepare its temporary folder; nothing was run.",
                            shell_used)

    telemetry = sandbox.telemetry_record(run_id, "run_shell", "enforced", bool(hosts),
                                         len(read_paths), len(write_paths), approval)
    tags = {"sandbox": "enforced", "_sandbox_telemetry": telemetry}
    if background:
        relay_env = sandbox.build_env(os.environ, env_dir, npm_root, path_prepend=[*copies, *cr._skill_bin_dirs()])
        relay_env["AIGATOR_RELAY_COMMAND"] = json.dumps(argv_prefix + [command])
        request = sandbox.SandboxRequest(
            argv=cr._python_command(relay), cwd=run_cwd, env=relay_env, runtime_paths=runtime_paths,
            read_paths=list(read_paths), write_paths=sandbox_write, network=bool(hosts), timeout=0,
            scratch_path=scratch,
        )
        return _start_background(cr, request, command, shell_used, env_dir, in_scratch, tags)
    watch_dirs = watched_output_dirs(str(run_cwd))
    before = snapshot_outputs(watch_dirs)
    request = sandbox.SandboxRequest(
        argv=argv_prefix + [command], cwd=run_cwd, env=sandbox.build_env(os.environ, env_dir, npm_root, path_prepend=cr._skill_bin_dirs()),
        runtime_paths=runtime_paths, read_paths=list(read_paths), write_paths=sandbox_write,
        network=bool(hosts), timeout=timeout, scratch_path=scratch,
    )
    start = time.monotonic()
    try:
        res = sandbox.launch_sandboxed(request)
    except sandbox.SandboxUnavailable as exc:
        return _shell_error(cr._launch_refusal_message(exc), shell_used, **tags)
    except sandbox.SandboxRunError:
        return _shell_error(cr._RUN_ERROR_MSG, shell_used, **tags)
    except OSError as exc:
        return _shell_error(f"The command sandbox could not start ({type(exc).__name__}) and nothing was run. "
                            "Tell the user; do not retry automatically.", shell_used, **tags)
    finally:
        if not in_scratch:
            shutil.rmtree(env_dir, ignore_errors=True)

    result = {
        "stdout": res.stdout or "", "stderr": _with_shell_hint(cr, res.stderr or ""),
        "exit_code": res.returncode, "shell_used": shell_used,
        "runtime_ms": int((time.monotonic() - start) * 1000), **tags,
    }
    new_files = diff_outputs(before, watch_dirs)
    if new_files:
        result["output_files"] = new_files
    if res.timed_out:
        result["error"] = f"Command timed out after {timeout}s."
    elif res.returncode != 0:
        tail = (res.stderr or res.stdout or "").strip().splitlines()
        reason = " ".join(tail[-3:]) if tail else ""
        result["error"] = (f"Command exited with code {res.returncode}: {reason}" if reason
                           else f"Command exited with code {res.returncode}")
    return result


def _start_background(cr, request, command, shell_used, env_dir, in_scratch, tags) -> dict:
    cleanup = None if in_scratch else (lambda: shutil.rmtree(env_dir, ignore_errors=True))
    handed_off = False
    try:
        with _BG_SPAWN_LOCK:
            capped = _bg_cap_error(shell_used)
            if capped:
                return {**capped, **tags}
            try:
                log_path = _bg_log_path()
            except OSError as exc:
                return _shell_error(f"Could not prepare background log dir: {exc}", shell_used,
                                    background=True, pid=0, log_file="", **tags)
            try:
                proc = sandbox.start_sandboxed(request)
            except sandbox.SandboxUnavailable as exc:
                return _shell_error(cr._launch_refusal_message(exc), shell_used, **tags)
            except sandbox.SandboxRunError:
                return _shell_error(cr._RUN_ERROR_MSG, shell_used, **tags)
            except (NotImplementedError, OSError) as exc:
                return _shell_error(f"Could not start the command in the sandbox ({type(exc).__name__}). "
                                    "Nothing was run.", shell_used, **tags)
            try:
                fp = ForwardedProcess(proc, str(log_path), on_close=cleanup).start()
            except OSError as exc:
                proc.terminate()
                return _shell_error(f"Could not open background log file: {exc}", shell_used,
                                    background=True, pid=0, log_file=str(log_path), **tags)
            handed_off = True
            _BG_REGISTRY[fp.pid] = {
                "popen": fp, "command": command, "log_file": str(log_path), "cwd": str(request.cwd),
                "shell_used": shell_used, "started_at": time.time(), "sandboxed": True,
            }
    finally:
        if cleanup and not handed_off:
            cleanup()

    result = {"background": True, "pid": fp.pid, "log_file": str(log_path), "shell_used": shell_used, **tags}
    if fp.wait_ready(_BG_READY_TIMEOUT):
        result["url"] = fp.url
        result["_dev_server"] = {"pid": fp.pid, "url": fp.url, "command": command[:200]}
        result["message"] = (f"Started in the sandbox and available at {fp.url}. Tell the user this address. "
                             f"Use stop_shell_process({fp.pid}) to stop it.")
    elif fp.poll() is None and fp.forward_error:
        result["_dev_server"] = {"pid": fp.pid, "url": None, "command": command[:200]}
        result["message"] = (f"Started in the sandbox (pid {fp.pid}), but its port could not be forwarded: "
                             f"{fp.forward_error} Tell the user, and use stop_shell_process({fp.pid}) to stop it.")
    elif fp.poll() is None:
        result["_dev_server"] = {"pid": fp.pid, "url": None, "command": command[:200]}
        result["message"] = (f"Started in the sandbox (pid {fp.pid}), no URL yet. "
                             f"Use check_shell_process({fp.pid}).")
    else:
        tail = _read_log_tail(str(log_path))
        result["error"] = f"The command exited with code {fp.poll()} before it printed a local address. {tail}".strip()
    return result


def _run_unsandboxed(command, shell, cwd, timeout, background) -> dict:
    # Windows auto-correct: `python3` doesn't exist on Windows (it opens the
    # Microsoft Store stub). The model often uses `python3` out of habit from
    # Linux/macOS. Replace with `python` on Windows only — `python` is the
    # correct command on Windows (python.org installer adds it to PATH).
    if sys.platform == "win32":
        command = re.sub(r'\bpython3\b', 'python', command)

    # Resolve which shell to use
    if shell == "bash":
        bash = shutil.which("bash")
        if _DETECTED_SHELL == "bash":
            argv_prefix = _DETECTED_ARGV
        elif bash:
            argv_prefix = [bash, "-c"]
        else:
            return {
                "error": "Bash is not available on this system.",
                "stdout": "", "stderr": "", "exit_code": -1,
                "shell_used": "bash", "runtime_ms": 0,
            }
        shell_used = "bash"
    elif shell == "powershell":
        powershell = shutil.which("pwsh") or shutil.which("powershell.exe")
        if not powershell:
            return {
                "error": "PowerShell is not available on this system.",
                "stdout": "", "stderr": "", "exit_code": -1,
                "shell_used": "powershell", "runtime_ms": 0,
            }
        argv_prefix = [powershell, "-Command"]
        shell_used = "powershell"
    elif shell == "cmd":
        if os.name != "nt":
            return {
                "error": "cmd is only available on Windows.",
                "stdout": "", "stderr": "", "exit_code": -1,
                "shell_used": "cmd", "runtime_ms": 0,
            }
        argv_prefix = [os.environ.get("COMSPEC", "cmd.exe"), "/c"]
        shell_used = "cmd"
    else:
        argv_prefix = _DETECTED_ARGV
        shell_used = _DETECTED_SHELL

    command = _route_frozen_python(command, shell_used)

    # When the caller targets a specific project, honor it. Otherwise default to
    # an app-owned scratch dir (~/.gator/work) instead of the user's home/repo,
    # so transient build artifacts (node_modules, generators) don't splatter.
    if cwd:
        cwd_path = cwd
    else:
        from config import WORK_DIR

        try:
            WORK_DIR.mkdir(parents=True, exist_ok=True)
            cwd_path = str(WORK_DIR)
        except OSError:
            cwd_path = os.path.expanduser("~")

    if background:
        # Non-blocking path: start detached, return immediately. Skips the
        # output-file snapshot/diff below since the process is still running —
        # there's nothing "finished" to diff against yet.
        return _spawn_background(command, argv_prefix, shell_used, cwd_path)

    # Snapshot likely output dirs so we can report any document/image files the
    # command produces — surfaced from disk, not the model's memory (issue #87).
    _watch_dirs = watched_output_dirs(cwd_path)
    _before = snapshot_outputs(_watch_dirs)

    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv_prefix + [command],
            cwd=cwd_path,
            capture_output=True,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
            **no_window_kwargs(),
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        result = {
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "exit_code": proc.returncode,
            "shell_used": shell_used,
            "runtime_ms": elapsed_ms,
        }
        _new_files = diff_outputs(_before, _watch_dirs)
        if _new_files:
            result["output_files"] = _new_files
        if proc.returncode != 0:
            # Include the actual failure text, not just the exit code — the stall
            # banner in agent_loop.py truncates this to 160 chars, so lead with the
            # part that explains *why* the command failed. stderr is usually where
            # that lives; some tools (e.g. npm) only print the reason to stdout.
            _tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            _reason = " ".join(_tail[-3:]) if _tail else ""
            result["error"] = (
                f"Command exited with code {proc.returncode}: {_reason}"
                if _reason
                else f"Command exited with code {proc.returncode}"
            )
        return result

    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "shell_used": shell_used,
            "runtime_ms": elapsed_ms,
            "error": f"Command timed out after {timeout}s.",
        }
    except Exception as exc:
        return {
            "stdout": "",
            "stderr": "",
            "exit_code": -1,
            "shell_used": shell_used,
            "runtime_ms": 0,
            "error": str(exc),
        }


def _tool_run_shell(
    command: str,
    shell: str = "",
    cwd: str = "",
    timeout: int = 60,
    background: bool = False,
    extra_read_paths=None,
    extra_write_paths=None,
    network_hosts=None,
    _context_id: str = "",
) -> dict:
    """Run a shell command inside the OS sandbox (same launcher and policy as run_python).

    The command may use its working folder only; a project cwd, extra paths or network need the user's
    approval card. _context_id is the server-injected tab id (never supplied by the model).
    """
    _del_token, _del_pos = _find_delete_command(command)
    if _del_token is not None:
        return {
            "error": (
                f"Delete operations are blocked: matched command '{_del_token}' "
                f"at position {_del_pos}. Ask the user to run this command manually."
            ),
            "stdout": "", "stderr": "", "exit_code": -1, "shell_used": _DETECTED_SHELL, "runtime_ms": 0,
        }
    from config import load_config
    from skills.code_runner import tools as cr

    policy = load_policy()
    if policy.code_runner == "disabled":
        return _shell_error(cr._DISABLED_MSG, _DETECTED_SHELL)
    requested = cr._check_requested_access(extra_read_paths, extra_write_paths, network_hosts, policy)
    if isinstance(requested, dict):
        return _shell_error(requested["error"], _DETECTED_SHELL)
    mode, reason = cr._sandbox_mode(load_config(), policy)
    if mode == "unavailable":
        return _shell_error(cr._unavailable_message(reason, in_settings=True), _DETECTED_SHELL)
    if mode == "off":
        return _run_unsandboxed(command, shell, cwd, timeout, background)
    return _run_sandboxed(cr, command, shell, cwd, timeout, background, requested, policy, _context_id)


TOOL_DEFS = [
    {
        "name": "run_shell",
        "description": (
            "Run a shell command inside the OS sandbox (bash/sh on macOS and Linux; cmd.exe on Windows, where dir "
            "and git do not work in the sandbox). "
            "Only when the sandbox is off, the shell is auto-detected (bash/WSL, PowerShell or cmd). Returns stdout, stderr, exit_code, shell_used, runtime_ms. "
            "If the command creates document/image files (.pptx/.docx/.xlsx/.pdf/images), their real absolute paths "
            "are returned in an output_files array — report these to the user verbatim so they know where the file landed. "
            "Delete operations (rm, del, rmdir, Remove-Item, format) are blocked — tell the user to run those manually. "
            "By default the command can use only its working folder (omit cwd for scratch work) and has no network. "
            "To work in a project folder (cwd), read or write other folders, or reach the network, pass cwd, "
            "extra_read_paths, extra_write_paths or network_hosts: the call returns approval_required and the user "
            "approves in the chat; call again with exactly the same values only after the user says they approved. "
            "Inspect a project with list_dir, read_file and grep_files and change it with write_file or edit_file; "
            "use run_shell when you need a full command pipeline. "
            "For a long-running process that does not exit on its own — an LLM "
            'inference server, a dev server (`npm run dev`), a foreground `docker run`, or `ssh host "<server>"` — '
            "set background=true. It returns "
            "immediately with a pid + log_file instead of blocking until timeout. Then use check_shell_process(pid) "
            "to confirm it started (e.g. look for a 'listening on port' line in log_tail) and stop_shell_process(pid) "
            "to stop it. On Windows with the sandbox on, background=true runs the command in the sandbox after the "
            "user approves it, forwards the first localhost port the command prints, and returns url once the "
            "server prints its address (it waits up to 30s). Tell the user the url so they can open it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                },
                "shell": {
                    "type": "string",
                    "enum": ["bash", "powershell", "cmd"],
                    "description": "Override the shell (optional). With the sandbox on, Windows uses cmd.exe only (bash and powershell are refused) and macOS/Linux use bash/sh.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory. Pass the project path to operate on a real project (git, npm build in the user's repo). OMIT for scratch/build work (creating a deck, temp generators) — it then defaults to an app-owned working dir (~/.gator/work) so node_modules and build files don't splatter into the user's home or repo.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds — default 60 (optional). Ignored when background=true.",
                },
                "background": {
                    "type": "boolean",
                    "description": (
                        "Run the command detached/non-blocking instead of waiting for it to exit. Use for servers "
                        "and other long-running processes. With the sandbox on (Windows) it needs a person in a "
                        "chat tab, shows the approval card, and returns {pid, log_file, url}. Poll with "
                        "check_shell_process, stop with stop_shell_process. Default false."
                    ),
                },
                "extra_read_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute paths of existing files or folders outside the working folder the command must read. Needs the user's approval; request only what the task needs.",
                },
                "extra_write_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Absolute paths of existing folders or files outside the working folder the command must write. Needs the user's approval.",
                },
                "network_hosts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "host:port destinations the command must connect to, e.g. 'api.example.com:443'. Needs the user's approval; approval turns on outbound network for the whole run.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "check_shell_process",
        "description": (
            "Check on a process started by run_shell(background=true): whether it's still running, its exit code "
            "(once it has exited), and a tail of its log output (log_tail) so you can e.g. confirm a server printed "
            "'listening on port'. Pass the pid returned by that run_shell call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pid": {
                    "type": "integer",
                    "description": "The pid returned by a run_shell(background=true) call.",
                },
            },
            "required": ["pid"],
        },
    },
    {
        "name": "stop_shell_process",
        "description": (
            "Stop a process started by run_shell(background=true), including any child processes it spawned "
            "(e.g. a dev-server wrapper's real server process). Pass the pid returned by that run_shell call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pid": {
                    "type": "integer",
                    "description": "The pid returned by a run_shell(background=true) call.",
                },
            },
            "required": ["pid"],
        },
    },
]

TOOL_STATUS = {
    "run_shell": "Running shell command...",
    "check_shell_process": "Checking background process...",
    "stop_shell_process": "Stopping background process...",
}

TOOL_HANDLERS = {
    "run_shell": _tool_run_shell,
    "check_shell_process": _tool_check_shell_process,
    "stop_shell_process": _tool_stop_shell_process,
}
