"""macOS Seatbelt launcher (/usr/bin/sandbox-exec -p <profile>).

Not runnable on the Windows development machine: verified by build_profile
tests on every OS plus the manual release-gate smoke test on a real Mac.
Children inherit the sandbox. Paths are passed through realpath before the
profile is built (/var -> /private/var, /tmp -> /private/tmp).
"""
from __future__ import annotations

import dataclasses
import os
import subprocess
from pathlib import Path, PurePath

from . import SandboxRequest, SandboxResult, SandboxUnavailable, run_process_group

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
SYSTEM_READ_PATHS = ("/usr", "/System", "/Library", "/bin", "/private/etc")
_MACH_SERVICES = ("com.apple.system.opendirectoryd.libinfo", "com.apple.system.logger", "com.apple.logd")
_NETWORK_MACH_SERVICES = ("com.apple.dnssd.service", "com.apple.trustd", "com.apple.SystemConfiguration.configd")


def _quote(path) -> str:
    text = path if isinstance(path, str) else PurePath(path).as_posix()
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _subpaths(paths) -> str:
    return " ".join(f"(subpath {_quote(p)})" for p in paths)


def _global_names(names) -> str:
    return " ".join(f'(global-name "{n}")' for n in names)


def build_profile(req: SandboxRequest) -> str:
    read = [*SYSTEM_READ_PATHS, *req.runtime_paths, *req.read_paths]
    write = [req.cwd, *req.write_paths]
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-fork)",
        "(allow process-exec)",
        "(allow signal (target same-sandbox))",
        "(allow sysctl-read)",
        "(allow file-read-metadata)",
        f"(allow mach-lookup {_global_names(_MACH_SERVICES)})",
        f"(allow file-read* {_subpaths(read)})",
        f"(allow file-read* file-write* {_subpaths(write)})",
        '(allow file-read* file-write* (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty") (subpath "/dev/fd"))',
        '(allow file-read* (literal "/dev/random") (literal "/dev/urandom"))',
    ]
    if req.network:
        lines += [
            "(allow network-outbound)",
            "(allow system-socket)",
            f"(allow mach-lookup {_global_names(_NETWORK_MACH_SERVICES)})",
        ]
    return "\n".join(lines) + "\n"


def _real(path) -> Path:
    return Path(os.path.realpath(path))


def probe() -> str | None:
    if not os.path.exists(SANDBOX_EXEC):
        return "macOS sandbox-exec was not found at /usr/bin/sandbox-exec."
    try:
        r = subprocess.run([SANDBOX_EXEC, "-p", "(version 1)(allow default)", "/usr/bin/true"],
                           capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"macOS sandbox-exec could not run ({type(exc).__name__})."
    if r.returncode != 0:
        return "macOS sandbox-exec refused to start a sandbox on this machine."
    return None


def launch(req: SandboxRequest) -> SandboxResult:
    if not os.path.exists(SANDBOX_EXEC):
        raise SandboxUnavailable("macOS sandbox-exec was not found at /usr/bin/sandbox-exec.")
    real = dataclasses.replace(
        req,
        cwd=_real(req.cwd),
        runtime_paths=[_real(p) for p in req.runtime_paths],
        read_paths=[_real(p) for p in req.read_paths],
        write_paths=[_real(p) for p in req.write_paths],
    )
    argv = [SANDBOX_EXEC, "-p", build_profile(real), *req.argv]
    return run_process_group(argv, real.cwd, req.env, req.timeout)
