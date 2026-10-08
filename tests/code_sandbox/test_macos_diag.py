import dataclasses
import glob
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from sandbox import SandboxRequest, build_env
from sandbox import launcher_macos as lm

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")

EXTRAS = {
    "real profile": "",
    "+ all mach-lookup": "(allow mach-lookup)",
    "+ all file-read": "(allow file-read*)",
    "+ ipc-posix-shm": "(allow ipc-posix-shm)",
    "+ process-info": "(allow process-info*)",
    "+ iokit-open": "(allow iokit-open)",
    "+ user-preference-read": "(allow user-preference-read)",
    "+ file-ioctl": "(allow file-ioctl)",
    "+ all of the above": "(allow mach-lookup)(allow file-read*)(allow ipc-posix-shm)(allow process-info*)"
                          "(allow iokit-open)(allow user-preference-read)(allow file-ioctl)",
}


def _run(profile, argv, cwd, env):
    r = subprocess.run([lm.SANDBOX_EXEC, "-p", profile, *argv], cwd=cwd, env=env, capture_output=True,
                       text=True, timeout=30)
    return r.returncode, r.stdout.strip()[-200:], r.stderr.strip()[-400:]


def test_macos_seatbelt_diagnostics():
    base = Path(os.path.realpath(tempfile.mkdtemp(prefix="aigator-diag-")))
    run = base / "run"
    run.mkdir()
    env = build_env(dict(os.environ), run, None, platform="darwin")
    runtime = [Path(os.path.realpath(p)) for p in (sys.base_prefix, sys.prefix)]
    req = SandboxRequest(argv=[sys.executable, "-c", "print(1)"], cwd=run, env=env, runtime_paths=runtime,
                         read_paths=[], write_paths=[], network=False, timeout=30)
    profile = lm.build_profile(dataclasses.replace(req))
    out = [f"sys.executable={sys.executable}", f"realpath={os.path.realpath(sys.executable)}",
           f"base_prefix={sys.base_prefix}", f"prefix={sys.prefix}", "PROFILE:", profile]
    started = time.time()
    for argv in (["/usr/bin/true"], ["/bin/echo", "hi"], [sys.executable, "-c", "print(1)"],
                 [os.path.realpath(sys.executable), "-c", "print(1)"]):
        out.append(f"RUN {argv}: {_run(profile, argv, run, env)}")
    for name, extra in EXTRAS.items():
        out.append(f"VARIANT {name}: {_run(profile + extra + chr(10), [sys.executable, '-c', 'print(1)'], run, env)}")
    since = int(time.time() - started) + 30
    for cmd in (["log", "show", "--last", f"{since}s", "--style", "compact", "--predicate",
                 'sender == "Sandbox" OR eventMessage CONTAINS "deny" OR eventMessage CONTAINS "Sandbox:"'],
                ["sudo", "-n", "log", "show", "--last", f"{since}s", "--style", "compact", "--predicate",
                 'eventMessage CONTAINS "deny" OR eventMessage CONTAINS "Sandbox:"']):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            out.append(f"LOG {cmd[:2]} rc={r.returncode}:\n" + "\n".join(r.stdout.splitlines()[-60:]) + r.stderr[-300:])
        except Exception as exc:
            out.append(f"LOG {cmd[:2]} failed: {type(exc).__name__}")
    reports = sorted(glob.glob(os.path.expanduser("~/Library/Logs/DiagnosticReports/*")), key=os.path.getmtime)
    for rp in reports[-2:]:
        try:
            out.append(f"CRASH {rp}:\n" + Path(rp).read_text(errors="replace")[:2500])
        except OSError as exc:
            out.append(f"CRASH {rp} unreadable: {type(exc).__name__}")
    pytest.fail("\n".join(out))
