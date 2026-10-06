"""OS-level sandbox for model-written code.

One small interface over three mechanisms: Windows AppContainer
(launcher_windows), macOS Seatbelt (launcher_macos) and Linux bubblewrap
(launcher_linux). Spec: docs/superpowers/specs/2026-10-05-code-runner-sandbox-design.md.

Standard library only: tests/code_sandbox/posix_sandbox_check.py imports this
package from a bare WSL python3.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

_log = logging.getLogger(__name__)


class SandboxUnavailable(RuntimeError):
    """The platform sandbox cannot run this request; nothing was executed."""


class SandboxRunError(RuntimeError):
    """The sandboxed process may already have run when the launcher failed.

    Deliberately not a SandboxUnavailable: callers must never treat it as "nothing
    was executed" and fall back to running the code again without a sandbox."""


@dataclass(frozen=True)
class SandboxRequest:
    argv: list[str]            # command to run (python/node + script)
    cwd: Path                  # run folder; always read/write
    env: dict[str, str]        # complete child environment (already filtered)
    runtime_paths: list[Path]  # read+execute: interpreter, stdlib, site-packages, SKILL_DIR, NODE_PATH root
    read_paths: list[Path]     # extra read-only paths the user approved for this run
    write_paths: list[Path]    # extra read-write paths the user approved for this run
    network: bool              # outbound network approved for this run
    timeout: int


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


_PROBE_LOCK = threading.Lock()
_PROBE: tuple[str, str | None] | None = None


def _launcher():
    """The launcher module for this OS, or None when there is none."""
    if sys.platform == "win32":
        from . import launcher_windows as module
    elif sys.platform == "darwin":
        from . import launcher_macos as module
    elif sys.platform.startswith("linux"):
        from . import launcher_linux as module
    else:
        return None
    return module


def _probe() -> tuple[str, str | None]:
    global _PROBE
    with _PROBE_LOCK:
        if _PROBE is None:
            try:
                module = _launcher()
                if module is None:
                    reason = f"No sandbox is available for platform {sys.platform}."
                else:
                    reason = module.probe()
            except Exception as exc:  # a broken probe must fail closed, never crash
                reason = f"The sandbox check failed ({type(exc).__name__})."
            _PROBE = ("enforced", None) if reason is None else ("unavailable", reason)
            if reason is not None:
                _log.warning("code sandbox unavailable: %s", reason)
        return _PROBE


def sandbox_level() -> str:
    """'enforced' or 'unavailable'. Probed once per process."""
    return _probe()[0]


def sandbox_unavailable_reason() -> str | None:
    return _probe()[1]


def launch_sandboxed(req: SandboxRequest) -> SandboxResult:
    if sandbox_level() != "enforced":
        raise SandboxUnavailable(sandbox_unavailable_reason() or "The sandbox is unavailable.")
    return _launcher().launch(req)


def sweep_stale_grants() -> int:
    """Remove sandbox ACEs a crashed run left behind (Windows only). Never raises."""
    if sys.platform != "win32":
        return 0
    try:
        from . import launcher_windows

        return launcher_windows.sweep_stale_grants()
    except Exception as exc:
        _log.warning("sandbox: stale grant sweep failed (%s)", type(exc).__name__)
        return 0


# ── Environment allow-list ────────────────────────────────────────────────────
# Everything not listed here (every token, API key, proxy credential) is dropped.
_WINDOWS_ENV = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS",
)
_WINDOWS_RUN_DIR_ENV = ("TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE")
_POSIX_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")
# Node in an AppContainer fails with `EPERM lstat 'C:\'` unless symlinks are
# preserved (spike, 2026-10-05). NODE_OPTIONS reaches Node started by user code.
_NODE_OPTIONS_WINDOWS = "--preserve-symlinks --preserve-symlinks-main"


def build_env(parent: Mapping[str, str], run_dir: Path, node_path: str | None,
              platform: str | None = None) -> dict[str, str]:
    platform = platform or sys.platform
    if platform == "win32":
        upper = {k.upper(): v for k, v in parent.items()}
        env = {k: upper[k] for k in _WINDOWS_ENV if k in upper}
        for key in _WINDOWS_RUN_DIR_ENV:
            env[key] = str(run_dir)
        env["NODE_OPTIONS"] = _NODE_OPTIONS_WINDOWS
    else:
        env = {k: parent[k] for k in _POSIX_ENV if k in parent}
        env["HOME"] = str(run_dir)
        env["TMPDIR"] = str(run_dir)
    if node_path:
        env["NODE_PATH"] = node_path
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def telemetry_record(run_id: str, skill_id: str, level: str, network: bool,
                     extra_read: int, extra_write: int, approval: str | None) -> dict:
    """One metadata-only line per run for turn telemetry. Never paths, hosts, code or output."""
    return {
        "run_id": run_id,
        "skill_id": skill_id or "",
        "level": level,
        "network": bool(network),
        "extra_read": int(extra_read),
        "extra_write": int(extra_write),
        "approval": approval,
    }


def run_process_group(argv: list[str], cwd: Path, env: dict[str, str], timeout: int) -> SandboxResult:
    """POSIX: run in a new session and kill the whole group on timeout."""
    proc = subprocess.Popen(
        argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            for stream in (proc.stdout, proc.stderr):
                stream.close()
            proc.wait()
            out, err = b"", b""
    return SandboxResult(
        returncode=-1 if timed_out else proc.returncode,
        stdout=(out or b"").decode("utf-8", "replace"),
        stderr=(err or b"").decode("utf-8", "replace"),
        timed_out=timed_out,
    )
