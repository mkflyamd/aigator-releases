"""Real-run checks for the POSIX launchers. Prints one JSON object.

Usage: python3 posix_sandbox_check.py linux|macos
Runs natively on Linux/macOS, or inside WSL from tests/code_sandbox/test_launcher_linux.py.
Imports only web/sandbox (standard library), so a bare python3 is enough.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "web"))

from sandbox import SandboxRequest, build_env  # noqa: E402

PROBE = r'''
import json, os, socket, sys
r = {}
def t(name, f):
    try:
        r[name] = "OK:" + str(f())[:60]
    except Exception as e:
        r[name] = "DENIED:" + type(e).__name__
t("write_run_dir", lambda: open("out.txt", "w").write("hi"))
t("read_secret", lambda: open(sys.argv[1]).read())
t("read_extra", lambda: open(sys.argv[2]).read())
t("read_secret_via_data_volume", lambda: open(sys.argv[3]).read())
t("net_external", lambda: socket.create_connection(("1.1.1.1", 443), 3).getpeername())
r["token"] = os.environ.get("GITHUB_TOKEN")
print(json.dumps(r))
'''

TREE = (
    "import subprocess, sys, time\n"
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print('started', flush=True)\n"
    "time.sleep(120)\n"
)


def main(kind: str) -> None:
    if kind == "macos":
        from sandbox import launcher_macos as launcher
        platform = "darwin"
    else:
        from sandbox import launcher_linux as launcher
        platform = "linux"
    base = Path(os.path.realpath(tempfile.mkdtemp(prefix="aigator-sandbox-check-")))
    run, secret_dir, extra_dir = base / "run", base / "secret", base / "extra"
    for d in (run, secret_dir, extra_dir):
        d.mkdir()
    (secret_dir / "s.txt").write_text("dummy-secret")
    (extra_dir / "e.txt").write_text("extra-data")
    (run / "probe.py").write_text(PROBE)
    (run / "tree.py").write_text(TREE)
    env = build_env(dict(os.environ, GITHUB_TOKEN="aigator-fake-api-key"), run, None, platform=platform)
    runtime = [Path(sys.base_prefix), Path(sys.prefix)]

    def request(argv, read_paths=(), timeout=30):
        return SandboxRequest(argv=argv, cwd=run, env=env, runtime_paths=runtime, read_paths=list(read_paths),
                              write_paths=[], network=False, timeout=timeout)

    def probe_run(read_paths=()):
        secret = secret_dir / "s.txt"
        # macOS: the same secret through the firmlinked data volume must be denied too.
        via_data = "/System/Volumes/Data" + str(secret) if kind == "macos" else str(secret)
        res = launcher.launch(request([sys.executable, str(run / "probe.py"), str(secret),
                                       str(extra_dir / "e.txt"), via_data], read_paths))
        lines = res.stdout.strip().splitlines()
        return json.loads(lines[-1]) if lines else {"rc": res.returncode, "stderr": res.stderr[-500:]}

    out = {"probe": launcher.probe(), "default": probe_run(), "with_extra": probe_run([extra_dir])}
    started = time.time()
    res = launcher.launch(request([sys.executable, str(run / "tree.py")], timeout=3))
    out["tree_kill"] = {"timed_out": res.timed_out, "elapsed": round(time.time() - started, 1)}
    time.sleep(1)
    ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    out["leftover_sleepers"] = sum(1 for line in ps.splitlines() if "time.sleep(120)" in line)
    print(json.dumps(out))


if __name__ == "__main__":
    main(sys.argv[1])
