"""Linux bubblewrap launcher (bwrap --unshare-all).

Needs the distro `bubblewrap` package and unprivileged user namespaces.
Children inherit the sandbox; --die-with-parent plus the PID namespace means
killing bwrap kills the whole tree. Paths go through realpath before the argv
is built. The root is an empty tmpfs: only the binds below exist inside.
"""
from __future__ import annotations

import dataclasses
import os
import posixpath
import shutil
import subprocess
from pathlib import Path, PurePath

from . import SandboxRequest, SandboxResult, SandboxRunError, SandboxUnavailable, run_process_group

SYSTEM_RO_PATHS = ("/usr", "/lib", "/lib32", "/lib64", "/bin", "/sbin")
ETC_RO_PATHS = (
    "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d", "/etc/alternatives", "/etc/localtime",
    "/etc/nsswitch.conf", "/etc/fonts",
)
# Resolver config and certificate stores are only visible when the user approved network access.
NETWORK_ETC_RO_PATHS = ("/etc/hosts", "/etc/resolv.conf", "/etc/ssl", "/etc/ca-certificates", "/etc/pki")
BWRAP_MISSING = (
    "bubblewrap is not installed. Install the 'bubblewrap' package "
    "(for example `sudo apt install bubblewrap` or `sudo dnf install bubblewrap`) and restart AI Gator."
)
BWRAP_BLOCKED = (
    "bubblewrap is installed but cannot create a sandbox (unprivileged user namespaces are disabled or "
    "restricted on this system). See docs/BUILD_INSTRUCTIONS.md, 'Linux: bubblewrap'."
)


def _posix(path) -> str:
    text = path if isinstance(path, str) else PurePath(path).as_posix()
    # Absolute only: a leading '-' must never be able to read as a bwrap option, and '/' is the whole disk.
    if not text.startswith("/") or text == "/":
        raise ValueError("sandbox paths must be absolute and not the filesystem root")
    return text


def _within(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip("/") + "/")


def interpreter_links(argv0: str, bound: list[str]) -> list[tuple[str, str]]:
    """(link text, link path) for each symlink on the program's path that the
    sandbox would not contain. Only real paths are bound, but a venv's python
    points through an alias folder (uv's cpython-3.13-... -> cpython-3.13.N-...)
    that must also exist inside, or the program cannot be started."""
    if "/" not in argv0:
        return []
    found: dict[str, str] = {}
    pending = [posixpath.abspath(argv0)]
    while pending and len(found) < 40:
        path = pending.pop()
        parts = path.split("/")[1:]
        prefix = ""
        for i, part in enumerate(parts):
            prefix += "/" + part
            if prefix in found or not os.path.islink(prefix):
                continue
            text = os.readlink(prefix)
            found[prefix] = text
            target = posixpath.normpath(posixpath.join(posixpath.dirname(prefix), text))
            pending.append(posixpath.join(target, *parts[i + 1:]))
            break
    return [(text, link) for link, text in found.items()
            if not any(_within(link, b) for b in bound)]


def build_argv(req: SandboxRequest, bwrap: str = "bwrap", links=()) -> list[str]:
    argv = [bwrap, "--unshare-all", "--die-with-parent", "--new-session"]
    if req.network:
        argv.append("--share-net")
    etc = (*ETC_RO_PATHS, *NETWORK_ETC_RO_PATHS) if req.network else ETC_RO_PATHS
    for path in (*SYSTEM_RO_PATHS, *etc):
        argv += ["--ro-bind-try", path, path]
    argv += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for path in (*req.runtime_paths, *req.read_paths):
        p = _posix(path)
        argv += ["--ro-bind", p, p]
    for path in req.write_paths:
        p = _posix(path)
        argv += ["--bind", p, p]
    for text, link in links:
        argv += ["--symlink", text, _posix(link)]
    cwd = _posix(req.cwd)
    argv += ["--bind", cwd, cwd, "--chdir", cwd, "--", *req.argv]
    return argv


def probe() -> str | None:
    path = shutil.which("bwrap")
    if not path:
        return BWRAP_MISSING
    try:
        r = subprocess.run([path, "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--", "true"],
                           capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"bubblewrap could not run ({type(exc).__name__})."
    if r.returncode != 0:
        return BWRAP_BLOCKED
    return None


def _real(path) -> Path:
    return Path(os.path.realpath(path))


def launch(req: SandboxRequest) -> SandboxResult:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise SandboxUnavailable(BWRAP_MISSING)
    real = dataclasses.replace(
        req,
        cwd=_real(req.cwd),
        runtime_paths=[_real(p) for p in req.runtime_paths],
        read_paths=[_real(p) for p in req.read_paths],
        write_paths=[_real(p) for p in req.write_paths],
    )
    etc = (*ETC_RO_PATHS, *NETWORK_ETC_RO_PATHS) if real.network else ETC_RO_PATHS
    bound = [str(p) for p in (real.cwd, *real.runtime_paths, *real.read_paths, *real.write_paths)]
    bound += [*SYSTEM_RO_PATHS, *etc]
    try:
        links = interpreter_links(real.argv[0], bound)
    except OSError as exc:
        raise SandboxUnavailable(f"The program's path could not be read ({type(exc).__name__}).") from exc
    try:
        argv = build_argv(real, bwrap, links)
    except ValueError as exc:
        raise SandboxUnavailable(f"A sandbox path was refused: {exc}") from exc
    try:
        return run_process_group(argv, real.cwd, req.env, req.timeout)
    except (FileNotFoundError, PermissionError) as exc:
        raise SandboxUnavailable(f"bubblewrap could not be started ({type(exc).__name__}).") from exc
    except OSError as exc:
        raise SandboxRunError(f"The sandboxed process failed ({type(exc).__name__}).") from exc
