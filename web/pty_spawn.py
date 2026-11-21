"""Spawn a PTY and wrap it in a uniform read/write/resize/close/isalive object.

Kept free of FastAPI so the separate PTY host process can import it.
"""

import os
import sys


def _pick_windows_shell() -> str:
    """Return the best available shell on Windows.

    Prefer pwsh.exe (PowerShell 7) because its Clear-Host emits proper VT
    sequences through ConPTY so `clear` works in xterm. Fall back to the
    inbox Windows PowerShell, then cmd.exe.

    Critically, REJECT Microsoft Store app-execution-alias stubs under
    \\WindowsApps\\. When PowerShell 7 isn't installed for real, Windows still
    exposes a zero-byte pwsh.exe reparse point there that shutil.which happily
    returns. Launching it triggers the Store's package-resolution machinery,
    which on a cold first invocation can stall for many seconds - long enough to
    blow past the frontend's 30s no-output watchdog, which then kills the pane
    and the terminal opens blank. The tell-tale symptom: the FIRST terminal of a
    session is blank, but a second one (after the stub has warmed) works. Real
    powershell.exe 5.1 always exists at a fixed System32 path, so falling through
    to it is both faster and reliable. Mirrors WakeGator's rejection of the
    \\WindowsApps\\ Python stub for the same sandbox reason.
    """
    import shutil

    def _real(candidate: str) -> str | None:
        path = shutil.which(candidate)
        if not path:
            return None
        if "\\windowsapps\\" in path.lower():
            return None  # Store alias stub - slow/flaky cold-launch, skip it
        return path

    for candidate in ("pwsh.exe", "powershell.exe", "cmd.exe"):
        resolved = _real(candidate)
        if resolved:
            return resolved

    # Last resort: the inbox PowerShell at its fixed, always-present location,
    # then COMSPEC. Never returns a bare name that could re-resolve to a stub.
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    inbox_ps = os.path.join(
        system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
    )
    if os.path.exists(inbox_ps):
        return inbox_ps
    return os.environ.get("COMSPEC", "cmd.exe")


def spawn_pty(
    cols: int,
    rows: int,
    command: list[str] | None = None,
    env: dict | None = None,
    cwd: str | None = None,
):
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
            proc = PtyProcess.spawn(
                command, dimensions=(rows, cols), env=proc_env, cwd=cwd
            )
        else:
            # Prefer PowerShell 7 (pwsh.exe) — its Clear-Host emits proper VT
            # sequences through ConPTY, so `clear` actually clears the xterm
            # viewport. Fall back to Windows PowerShell 5.1, then cmd.exe.
            shell = _pick_windows_shell()
            proc_env = {**os.environ, **env} if env else None
            proc = PtyProcess.spawn(
                [shell], dimensions=(rows, cols), env=proc_env, cwd=cwd
            )
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
    def __init__(
        self,
        cols: int,
        rows: int,
        command: list[str] | None = None,
        env: dict | None = None,
        cwd: str | None = None,
    ):
        import fcntl
        import pty
        import struct
        import subprocess
        import termios

        self._pty = pty
        self._fcntl = fcntl
        self._termios = termios
        self._struct = struct

        master, slave = pty.openpty()
        # set initial size
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

        argv = command if command else [os.environ.get("SHELL", "/bin/bash")]
        proc_env = {**os.environ, **env} if env else None
        self._proc = subprocess.Popen(
            argv,
            stdin=slave,
            stdout=slave,
            stderr=slave,
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
            self._master,
            self._termios.TIOCSWINSZ,
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
