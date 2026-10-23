"""
Helper for running LibreOffice (soffice) in environments where AF_UNIX
sockets may be blocked (e.g., sandboxed VMs).  Detects the restriction
at runtime and applies an LD_PRELOAD shim if needed.

Usage:
    from office.soffice import run_soffice, get_soffice_env

    # Option 1 – run soffice directly
    result = run_soffice(["--headless", "--convert-to", "pdf", "input.docx"])

    # Option 2 – get env dict for your own subprocess calls
    env = get_soffice_env()
    subprocess.run([require_soffice(), ...], env=env)
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

NOT_INSTALLED_MESSAGE = (
    "LibreOffice is not installed on this computer, so formulas could not be recalculated here. "
    "The file was saved and its formulas calculate when it is opened in Excel."
)


class SofficeNotFound(FileNotFoundError):
    """LibreOffice is not installed (or not where we look for it)."""


def _candidate_paths() -> list[Path]:
    if sys.platform == "win32":
        roots = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("ProgramW6432"),
            os.path.join(os.environ["LOCALAPPDATA"], "Programs") if os.environ.get("LOCALAPPDATA") else None,
        ]
        return [Path(root) / "LibreOffice" / "program" / "soffice.exe" for root in roots if root]
    if sys.platform == "darwin":
        return [
            Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
            Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice",
        ]
    found = [Path("/usr/lib/libreoffice/program/soffice"), Path("/snap/bin/libreoffice")]
    found += sorted(Path("/opt").glob("libreoffice*/program/soffice"), reverse=True)
    return found


def find_soffice() -> str | None:
    """Full path of the LibreOffice launcher, or None when LibreOffice is not installed.

    PATH first, then the standard install folders; a Windows or macOS install does not put soffice on PATH."""
    for name in ("soffice", "libreoffice"):
        hit = shutil.which(name)
        if hit:
            return hit
    for path in _candidate_paths():
        if path.is_file():
            return str(path)
    return None


def require_soffice() -> str:
    path = find_soffice()
    if not path:
        raise SofficeNotFound(NOT_INSTALLED_MESSAGE)
    return path


def get_soffice_env() -> dict:
    env = os.environ.copy()
    if sys.platform != "win32":
        # Headless rendering backend for Linux/macOS; Windows has no such plugin and needs its native one.
        env["SAL_USE_VCLPLUGIN"] = "svp"

    if _needs_shim():
        shim = _ensure_shim()
        env["LD_PRELOAD"] = str(shim)

    return env


def run_soffice(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    env = get_soffice_env()
    return subprocess.run([require_soffice()] + args, env=env, **kwargs)


_CREATE_NO_WINDOW = 0x08000000
_PROFILE_LOCK = threading.Lock()


def _kill_tree(proc: subprocess.Popen) -> None:
    # soffice.exe starts soffice.bin; killing only the launcher leaves the real process running.
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True, check=False, creationflags=_CREATE_NO_WINDOW,
        )
    proc.kill()


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    kwargs = {"creationflags": _CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, errors="replace", env=get_soffice_env(), **kwargs,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def run_basic_macro(
    macro_xml: str, macro_name: str, document: str, timeout: float, profile_name: str
) -> subprocess.CompletedProcess:
    """Run a StarBasic macro on `document` in a private headless LibreOffice profile.

    The private profile keeps the macro out of the user's own LibreOffice settings and lets this run
    while they have LibreOffice open. Raises SofficeNotFound, subprocess.TimeoutExpired or OSError."""
    soffice = require_soffice()
    profile = Path(tempfile.gettempdir()) / f"gator_lo_{profile_name}_profile"
    macro_dir = profile / "user" / "basic" / "Standard"
    macro_file = macro_dir / "Module1.xba"
    base = [soffice, "--headless", "--norestore", f"-env:UserInstallation={profile.as_uri()}"]
    with _PROFILE_LOCK:
        if not (macro_file.exists() and macro_name in macro_file.read_text(encoding="utf-8")):
            if not macro_dir.exists():
                init = _run(base + ["--terminate_after_init"], 90)
                if init.returncode != 0:
                    return init
            macro_dir.mkdir(parents=True, exist_ok=True)
            macro_file.write_text(macro_xml, encoding="utf-8")
        script = f"vnd.sun.star.script:Standard.Module1.{macro_name}?language=Basic&location=application"
        return _run(base + [script, str(Path(document).absolute())], timeout)


_SHIM_SO = Path(tempfile.gettempdir()) / "lo_socket_shim.so"


def _needs_shim() -> bool:
    if not sys.platform.startswith("linux"):
        return False  # the LD_PRELOAD shim is Linux-only; Windows Python has no socket.AF_UNIX
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.close()
        return False
    except OSError:
        return True


def _ensure_shim() -> Path:
    if _SHIM_SO.exists():
        return _SHIM_SO

    src = Path(tempfile.gettempdir()) / "lo_socket_shim.c"
    src.write_text(_SHIM_SOURCE)
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-o", str(_SHIM_SO), str(src), "-ldl"],
        check=True,
        capture_output=True,
    )
    src.unlink()
    return _SHIM_SO


_SHIM_SOURCE = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>

static int (*real_socket)(int, int, int);
static int (*real_socketpair)(int, int, int, int[2]);
static int (*real_listen)(int, int);
static int (*real_accept)(int, struct sockaddr *, socklen_t *);
static int (*real_close)(int);
static int (*real_read)(int, void *, size_t);

/* Per-FD bookkeeping (FDs >= 1024 are passed through unshimmed). */
static int is_shimmed[1024];
static int peer_of[1024];
static int wake_r[1024];            /* accept() blocks reading this */
static int wake_w[1024];            /* close()  writes to this      */
static int listener_fd = -1;        /* FD that received listen()    */

__attribute__((constructor))
static void init(void) {
    real_socket     = dlsym(RTLD_NEXT, "socket");
    real_socketpair = dlsym(RTLD_NEXT, "socketpair");
    real_listen     = dlsym(RTLD_NEXT, "listen");
    real_accept     = dlsym(RTLD_NEXT, "accept");
    real_close      = dlsym(RTLD_NEXT, "close");
    real_read       = dlsym(RTLD_NEXT, "read");
    for (int i = 0; i < 1024; i++) {
        peer_of[i] = -1;
        wake_r[i]  = -1;
        wake_w[i]  = -1;
    }
}

/* ---- socket ---------------------------------------------------------- */
int socket(int domain, int type, int protocol) {
    if (domain == AF_UNIX) {
        int fd = real_socket(domain, type, protocol);
        if (fd >= 0) return fd;
        /* socket(AF_UNIX) blocked – fall back to socketpair(). */
        int sv[2];
        if (real_socketpair(domain, type, protocol, sv) == 0) {
            if (sv[0] >= 0 && sv[0] < 1024) {
                is_shimmed[sv[0]] = 1;
                peer_of[sv[0]]    = sv[1];
                int wp[2];
                if (pipe(wp) == 0) {
                    wake_r[sv[0]] = wp[0];
                    wake_w[sv[0]] = wp[1];
                }
            }
            return sv[0];
        }
        errno = EPERM;
        return -1;
    }
    return real_socket(domain, type, protocol);
}

/* ---- listen ---------------------------------------------------------- */
int listen(int sockfd, int backlog) {
    if (sockfd >= 0 && sockfd < 1024 && is_shimmed[sockfd]) {
        listener_fd = sockfd;
        return 0;
    }
    return real_listen(sockfd, backlog);
}

/* ---- accept ---------------------------------------------------------- */
int accept(int sockfd, struct sockaddr *addr, socklen_t *addrlen) {
    if (sockfd >= 0 && sockfd < 1024 && is_shimmed[sockfd]) {
        /* Block until close() writes to the wake pipe. */
        if (wake_r[sockfd] >= 0) {
            char buf;
            real_read(wake_r[sockfd], &buf, 1);
        }
        errno = ECONNABORTED;
        return -1;
    }
    return real_accept(sockfd, addr, addrlen);
}

/* ---- close ----------------------------------------------------------- */
int close(int fd) {
    if (fd >= 0 && fd < 1024 && is_shimmed[fd]) {
        int was_listener = (fd == listener_fd);
        is_shimmed[fd] = 0;

        if (wake_w[fd] >= 0) {              /* unblock accept() */
            char c = 0;
            write(wake_w[fd], &c, 1);
            real_close(wake_w[fd]);
            wake_w[fd] = -1;
        }
        if (wake_r[fd] >= 0) { real_close(wake_r[fd]); wake_r[fd]  = -1; }
        if (peer_of[fd] >= 0) { real_close(peer_of[fd]); peer_of[fd] = -1; }

        if (was_listener)
            _exit(0);                        /* conversion done – exit */
    }
    return real_close(fd);
}
"""


if __name__ == "__main__":
    import sys

    result = run_soffice(sys.argv[1:])
    sys.exit(result.returncode)
