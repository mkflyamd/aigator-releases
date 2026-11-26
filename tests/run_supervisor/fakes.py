"""Fake programs for the conformance suite. All are Python so they behave the same on every path and platform."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

# The viewer fakes use socketserver: http.server.HTTPServer calls socket.getfqdn() on bind, which can stall on macOS runners.
# cmd quotes a Windows path the same way everywhere; bash and WSL would mangle it.
SHELL = "cmd" if sys.platform == "win32" else ""

_PROGRAMS = {
    "slow": "import time; time.sleep(60)",
    "quick": "print('hello-run')",
    "prints_url": "print('Viewer at http://127.0.0.1:4173/p/demo/')",
    "crash_after_success": "print('Viewer at http://127.0.0.1:4173/p/demo/', flush=True); raise SystemExit(3)",
    "flood": "import sys\nfor _ in range(60):\n    sys.stdout.write('x' * 50000)\nsys.stdout.flush()",
    "ignores_stop": (
        "import signal, time\n"
        "for name in ('SIGTERM', 'SIGINT', 'SIGBREAK'):\n"
        "    if hasattr(signal, name):\n"
        "        signal.signal(getattr(signal, name), signal.SIG_IGN)\n"
        "time.sleep(60)"
    ),
    "serves_viewer": (
        "import http.server, socketserver, threading, time\n"
        "httpd = socketserver.ThreadingTCPServer(('127.0.0.1', 0), http.server.SimpleHTTPRequestHandler)\n"
        "threading.Thread(target=httpd.serve_forever, daemon=True).start()\n"
        "print(f'Viewer at http://127.0.0.1:{httpd.server_address[1]}/', flush=True)\n"
        "time.sleep(60)"
    ),
    "viewer_then_crash": (
        "import pathlib, subprocess, sys\n"
        "server = 'import http.server, socketserver; h = socketserver.ThreadingTCPServer((\"127.0.0.1\", 0), "
        "http.server.SimpleHTTPRequestHandler); print(h.server_address[1], flush=True); h.serve_forever()'\n"
        "child = subprocess.Popen([sys.executable, '-c', server], stdout=subprocess.PIPE, text=True)\n"
        "port = child.stdout.readline().strip()\n"
        "pathlib.Path(PID_FILE).write_text(str(child.pid))\n"
        "print(f'Viewer at http://127.0.0.1:{port}/', flush=True)\n"
        "raise SystemExit(3)"
    ),
    # The parent ends normally; its child has its own stdio, so nothing ties the child to the run.
    "detached_child": (
        "import subprocess, sys, pathlib\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],\n"
        "                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "pathlib.Path(PID_FILE).write_text(str(p.pid))\n"
        "print('parent done')"
    ),
    # The parent ends, but its child still holds the output pipes, so the run cannot finish on its own.
    "pipe_holder": (
        "import subprocess, sys, pathlib\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "pathlib.Path(PID_FILE).write_text(str(p.pid))\n"
        "print('parent done')"
    ),
    # A parent and a child that both stay up.
    "slow_tree": (
        "import subprocess, sys, pathlib, time\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "pathlib.Path(PID_FILE).write_text(str(p.pid))\n"
        "time.sleep(60)"
    ),
}


def command(tmp_path: Path, name: str) -> str:
    """A command line that runs the named fake program."""
    script = tmp_path / f"{name}.py"
    pid_file = tmp_path / f"{name}.pid"
    script.write_text(_PROGRAMS[name].replace("PID_FILE", repr(str(pid_file))))
    args = ""
    if sys.platform == "win32" and " " not in f"{sys.executable}{script}":
        return f"{sys.executable} {script}{args}"  # cmd.exe cannot be handed escaped quotes
    return f'"{sys.executable}" "{script}"{args}'


def child_pid(tmp_path: Path, name: str, seconds: float = 15) -> int:
    pid_file = tmp_path / f"{name}.pid"
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if pid_file.exists() and pid_file.read_text().strip():
            return int(pid_file.read_text())
        time.sleep(0.05)
    raise AssertionError("the fake program never wrote its pid")


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
        return str(pid) in out
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_for(predicate, seconds: float = 15) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False
