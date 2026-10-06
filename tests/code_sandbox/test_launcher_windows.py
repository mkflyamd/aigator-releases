import json
import os
import socket
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import sandbox
from sandbox import SandboxRequest, build_env
from sandbox import launcher_windows as lw

FAKE = "aigator-fake-api-key"


# ── Pure helpers: every OS ───────────────────────────────────────────────────

def test_ace_spec_uses_inheritance_only_for_directories():
    assert lw.ace_spec("S-1-15-2-1", "RX", True) == "*S-1-15-2-1:(OI)(CI)RX"
    assert lw.ace_spec("S-1-15-2-1", "M", False) == "*S-1-15-2-1:M"


def test_acl_grants_split_runtime_from_per_run():
    req = SandboxRequest(
        argv=["python"], cwd=Path("C:/run"), env={}, runtime_paths=[Path("C:/py")],
        read_paths=[Path("C:/data")], write_paths=[Path("C:/out")], network=False, timeout=5,
    )
    runtime, per_run = lw.acl_grants(req)
    assert runtime == [(Path("C:/py"), "RX")]
    assert per_run == [(Path("C:/data"), "RX"), (Path("C:/out"), "M"), (Path("C:/run"), "M")]


def test_ledger_round_trip_and_corrupt_file(tmp_path, monkeypatch):
    ledger = tmp_path / "g.json"
    monkeypatch.setattr(lw, "ledger_path", lambda: ledger)
    lw._ledger_add_per_run("S-1-15-2-9", tmp_path)
    assert lw._ledger_load()["per_run"] == [["S-1-15-2-9", str(tmp_path)]]
    lw._ledger_remove_per_run("S-1-15-2-9", tmp_path)
    assert lw._ledger_load()["per_run"] == []
    ledger.write_text("not json")
    assert lw._ledger_load() == {"runtime": {}, "per_run": []}


def test_sweep_revokes_and_clears_ledger_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(lw, "ledger_path", lambda: tmp_path / "g.json")
    revoked = []
    monkeypatch.setattr(lw, "_revoke", lambda path, sid: revoked.append((str(path), sid)) or (0, ""))
    lw._ledger_add_per_run("S-1-15-2-9", tmp_path)
    assert lw.sweep_stale_grants() == 1
    assert revoked == [(str(tmp_path), "S-1-15-2-9")]
    assert lw._ledger_load()["per_run"] == []


def test_package_sweep_is_noop_off_windows(monkeypatch):
    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    assert sandbox.sweep_stale_grants() == 0


def test_app_sweeps_stale_grants_at_startup():
    app_src = (Path(__file__).parents[2] / "web" / "app.py").read_text(encoding="utf-8")
    assert "_sandbox.sweep_stale_grants" in app_src


# ── Real AppContainer runs: Windows only ─────────────────────────────────────

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
t("net_external", lambda: socket.create_connection(("1.1.1.1", 443), 3).getpeername())
t("net_loopback", lambda: socket.create_connection(("127.0.0.1", int(sys.argv[3])), 3).getpeername())
r["token"] = os.environ.get("GITHUB_TOKEN")
r["encoding"] = os.environ.get("PYTHONIOENCODING")
print(json.dumps(r))
'''

def _runtime():
    return sorted({Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}, key=str)


@pytest.fixture
def layout(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (tmp_path / "secret").mkdir()
    (tmp_path / "secret" / "s.txt").write_text("dummy-secret")
    (tmp_path / "extra").mkdir()
    (tmp_path / "extra" / "e.txt").write_text("extra-data")
    (run / "probe.py").write_text(PROBE, encoding="utf-8")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    yield SimpleNamespace(
        run=run, secret=tmp_path / "secret" / "s.txt", extra_dir=tmp_path / "extra",
        extra=tmp_path / "extra" / "e.txt", port=listener.getsockname()[1],
    )
    listener.close()


def _probe(lw_mod, layout, read_paths=(), network=False):
    env = build_env(dict(os.environ, GITHUB_TOKEN=FAKE), layout.run, None)
    req = SandboxRequest(
        argv=[sys.executable, str(layout.run / "probe.py"), str(layout.secret), str(layout.extra), str(layout.port)],
        cwd=layout.run, env=env, runtime_paths=_runtime(), read_paths=list(read_paths),
        write_paths=[], network=network, timeout=60,
    )
    res = lw_mod.launch(req)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


@pytest.mark.real_sandbox
@pytest.mark.skipif(sys.platform != "win32", reason="AppContainer is Windows only")
class TestRealAppContainer:
    def test_default_run_is_contained(self, windows_container, layout):
        r = _probe(windows_container, layout)
        assert r["write_run_dir"].startswith("OK")
        assert r["read_secret"].startswith("DENIED")
        assert r["read_extra"].startswith("DENIED")
        assert r["net_external"].startswith("DENIED")
        assert r["net_loopback"].startswith("DENIED")
        assert r["token"] is None
        assert r["encoding"] == "utf-8"

    def test_extra_read_grant_applies_to_one_run_only(self, windows_container, layout):
        assert _probe(windows_container, layout, read_paths=[layout.extra_dir])["read_extra"] == "OK:extra-data"
        assert _probe(windows_container, layout)["read_extra"].startswith("DENIED")
        assert json.loads(windows_container.ledger_path().read_text())["per_run"] == []

    def test_sweep_removes_grants_left_by_a_crash(self, windows_container, layout):
        lw_mod = windows_container
        psid, sid = lw_mod.ensure_profile(lw_mod.PROFILE_NAME)
        lw_mod._api().adv.FreeSid(psid)
        lw_mod._ledger_add_per_run(sid, layout.extra_dir)
        assert lw_mod._grant(layout.extra_dir, sid, "RX")[0] == 0
        assert _probe(lw_mod, layout)["read_extra"] == "OK:extra-data"
        assert lw_mod.sweep_stale_grants() == 1
        assert _probe(lw_mod, layout)["read_extra"].startswith("DENIED")

    def test_timeout_kills_the_process_tree(self, windows_container, tmp_path):
        import psutil

        run = tmp_path / "run"
        run.mkdir()
        (run / "tree.py").write_text(
            "import subprocess, sys, time\n"
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
            "open('child.pid', 'w').write(str(p.pid))\n"
            "print('started', flush=True)\n"
            "time.sleep(120)\n",
            encoding="utf-8",
        )
        res = windows_container.launch(SandboxRequest(
            argv=[sys.executable, str(run / "tree.py")], cwd=run, env=build_env(os.environ, run, None),
            runtime_paths=_runtime(), read_paths=[], write_paths=[], network=False, timeout=10,
        ))
        assert res.timed_out and res.returncode == -1
        time.sleep(1)
        assert not psutil.pid_exists(int((run / "child.pid").read_text()))

    def test_network_capability_only_when_approved(self, windows_container, layout):
        try:
            socket.create_connection(("1.1.1.1", 443), 3).close()
        except OSError:
            pytest.skip("this machine cannot reach 1.1.1.1:443")
        assert _probe(windows_container, layout, network=True)["net_external"].startswith("OK")
        assert _probe(windows_container, layout)["net_external"].startswith("DENIED")

    def test_overhead_after_runtime_grants_exist(self, windows_container, layout):
        _probe(windows_container, layout)
        started = time.monotonic()
        _probe(windows_container, layout)
        elapsed = time.monotonic() - started
        print(f"sandboxed probe run took {elapsed:.1f}s")
        assert elapsed < 15
