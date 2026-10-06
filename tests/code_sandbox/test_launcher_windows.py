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


# ── Pure helpers added in fix round 1: every OS ──────────────────────────────

def test_env_block_is_sorted_case_insensitively_and_double_nul_terminated():
    assert lw._env_block({"b": "2", "A": "1"}) == "A=1\0b=2\0\0"
    assert lw._env_block({}) == "\0\0"


def test_cmdline_quotes_arguments_with_spaces_and_quotes():
    assert lw._cmdline(["python", "a b.py", 'say "hi"']) == 'python "a b.py" "say \\"hi\\""'


def test_icacls_is_called_by_full_system32_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(lw.subprocess, "run", lambda argv, **kw: seen.setdefault("argv", argv) and SimpleNamespace(
        returncode=0, stdout="", stderr=""))
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    lw._icacls(Path("C:/data"), "/grant")
    assert seen["argv"][0] == os.path.join(r"C:\Windows", "System32", "icacls.exe")
    monkeypatch.delenv("SystemRoot")
    assert lw._icacls_exe() == "icacls"


@pytest.mark.parametrize("bad", ["C:/a*b", "C:/a?b"])
def test_icacls_rejects_wildcard_paths(monkeypatch, bad):
    monkeypatch.setattr(lw.subprocess, "run", lambda *a, **kw: pytest.fail("icacls must not run"))
    with pytest.raises(ValueError):
        lw._icacls(Path(bad), "/grant")


def test_icacls_accepts_extended_length_prefix(monkeypatch):
    monkeypatch.setattr(lw.subprocess, "run", lambda argv, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
    lw._icacls(Path("C:/data"), "/grant")
    lw._check_icacls_path("\\\\?\\C:\\data")  # the extended-length prefix is not a wildcard


def test_covered_by_runtime_means_equal_or_inside(tmp_path):
    runtime = tmp_path / "py"
    assert lw._covered_by(runtime, [str(runtime)])
    assert lw._covered_by(runtime / "lib" / "x", [str(runtime)])
    assert not lw._covered_by(tmp_path / "python-other", [str(runtime)])
    assert not lw._covered_by(tmp_path, [str(runtime)])


def _ac_layout(tmp_path):
    """The layout GetAppContainerFolderPath really returns: Packages/<profile>/AC under LOCALAPPDATA."""
    ac = tmp_path / "Packages" / lw.PROFILE_NAME / "AC"
    (ac / "sub").mkdir(parents=True)
    (ac / "sub" / "stash.txt").write_text("leaked")
    (ac / "top.txt").write_text("leaked")
    return ac


def test_clear_container_storage_empties_ac_and_never_follows_links(tmp_path):
    ac = _ac_layout(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    try:
        os.symlink(outside, ac / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pass  # symlinks need a privilege on some Windows setups; the rest still runs
    assert lw.clear_container_storage(ac) >= 3
    assert ac.is_dir() and list(ac.iterdir()) == []
    assert (outside / "keep.txt").read_text() == "keep"
    assert lw.clear_container_storage(tmp_path / "missing") == 0


def test_scrub_clears_the_real_layout(tmp_path, monkeypatch):
    ac = _ac_layout(tmp_path)
    monkeypatch.setattr(lw, "_container_folder", lambda sid: ac)
    lw._scrub_container("S-1-15-2-9")
    assert ac.is_dir() and list(ac.iterdir()) == []


@pytest.mark.parametrize("relative", [
    "Packages/AIGator.CodeRunner",             # the profile folder itself, not its AC subfolder
    "Packages/Someone.Else/AC",                # another profile
    "Elsewhere/AIGator.CodeRunner/AC",         # not under Packages
    "Packages/AIGator.CodeRunner/Settings",    # not AC
])
def test_scrub_refuses_a_wrong_layout(tmp_path, monkeypatch, relative):
    target = tmp_path / relative
    target.mkdir(parents=True)
    (target / "keep.txt").write_text("keep")
    monkeypatch.setattr(lw, "_container_folder", lambda sid: target)
    lw._scrub_container("S-1-15-2-9")
    assert (target / "keep.txt").exists()


def test_scrub_refuses_when_ac_or_its_parent_is_a_link(tmp_path, monkeypatch):
    real = _ac_layout(tmp_path / "real")
    monkeypatch.setattr(lw, "_container_folder", lambda sid: real)
    monkeypatch.setattr(lw, "_is_link", lambda path: path == real)
    lw._scrub_container("S-1-15-2-9")
    assert (real / "top.txt").exists()
    monkeypatch.setattr(lw, "_is_link", lambda path: path == real.parent)
    lw._scrub_container("S-1-15-2-9")
    assert (real / "top.txt").exists()


def test_ledger_add_does_not_duplicate_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(lw, "ledger_path", lambda: tmp_path / "g.json")
    lw._ledger_add_per_run("S-1-15-2-9", tmp_path)
    lw._ledger_add_per_run("S-1-15-2-9", tmp_path)
    assert lw._ledger_load()["per_run"] == [["S-1-15-2-9", str(tmp_path)]]


def test_post_start_failures_are_not_reported_as_unavailable():
    # Once the process may have run, callers must not mistake the failure for "nothing executed".
    before = lw._run_error(False, "x")
    after = lw._run_error(True, "x")
    assert isinstance(before, sandbox.SandboxUnavailable)
    assert isinstance(after, sandbox.SandboxRunError)
    assert not isinstance(after, sandbox.SandboxUnavailable)


# ── launch() grant bookkeeping with mocked Win32 and icacls: every OS ────────

@pytest.fixture
def fake(tmp_path, monkeypatch):
    state = SimpleNamespace(grants=[], revokes=[], scrubs=[], revoke_rc=0, grant_error=None, run_error=None, runs=0)
    run = tmp_path / "run"
    run.mkdir()
    state.run = run
    state.tmp = tmp_path
    monkeypatch.setattr(lw, "ledger_path", lambda: tmp_path / "ledger" / "g.json")
    monkeypatch.setattr(lw, "ensure_profile", lambda name: (None, "S-1-15-2-9"))
    monkeypatch.setattr(lw, "_api", lambda: SimpleNamespace(adv=SimpleNamespace(FreeSid=lambda p: None)))
    monkeypatch.setattr(lw, "_scrub_container", lambda sid: state.scrubs.append(sid))

    def grant(path, sid, perm):
        if state.grant_error and len(state.grants) >= state.grant_error[0]:
            raise state.grant_error[1]
        state.grants.append((str(path), perm))
        return 0, ""

    def revoke(path, sid):
        state.revokes.append(str(path))
        return state.revoke_rc, ""

    def run_contained(*args, **kwargs):
        state.runs += 1
        if state.run_error:
            raise state.run_error
        return sandbox.SandboxResult(0, "", "", False)

    monkeypatch.setattr(lw, "_grant", grant)
    monkeypatch.setattr(lw, "_revoke", revoke)
    monkeypatch.setattr(lw, "_run_contained", run_contained)

    def req(runtime=(), read=(), write=(), cwd=None):
        return SandboxRequest(
            argv=["python"], cwd=cwd or run, env={}, runtime_paths=list(runtime),
            read_paths=list(read), write_paths=list(write), network=False, timeout=5,
        )

    state.req = req
    return state


def test_launch_removes_ledger_entries_when_revoke_succeeds(fake):
    lw.launch(fake.req(read=[fake.tmp]))
    assert fake.revokes == [str(fake.tmp), str(fake.run)]
    assert lw._ledger_load()["per_run"] == []


def test_launch_keeps_ledger_entry_when_revoke_fails(fake):
    fake.revoke_rc = 5
    lw.launch(fake.req())
    assert lw._ledger_load()["per_run"] == [["S-1-15-2-9", str(fake.run)]]


def test_launch_revokes_and_deledgers_everything_when_a_grant_raises(fake):
    fake.grant_error = (1, sandbox.SandboxUnavailable("no access"))
    with pytest.raises(sandbox.SandboxUnavailable):
        lw.launch(fake.req(read=[fake.tmp]))
    assert fake.revokes == [str(fake.tmp), str(fake.run)]
    assert lw._ledger_load()["per_run"] == []


def test_launch_revokes_and_deledgers_everything_when_the_run_raises(fake):
    fake.run_error = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        lw.launch(fake.req(read=[fake.tmp]))
    assert sorted(fake.revokes) == sorted([str(fake.tmp), str(fake.run)])
    assert lw._ledger_load()["per_run"] == []


def test_launch_scrubs_container_storage_before_and_after(fake):
    lw.launch(fake.req())
    assert fake.scrubs == ["S-1-15-2-9", "S-1-15-2-9"]
    fake.scrubs.clear()
    fake.run_error = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        lw.launch(fake.req())
    assert len(fake.scrubs) == 2


def test_launch_does_not_regrant_or_revoke_reads_inside_a_runtime_directory(fake):
    runtime = fake.tmp / "py"
    runtime.mkdir()
    (runtime / "lib").mkdir()
    lw.launch(fake.req(runtime=[runtime], read=[runtime / "lib", runtime]))
    assert fake.grants == [(str(runtime), "RX"), (str(fake.run), "M")]
    assert fake.revokes == [str(fake.run)]


def test_launch_refuses_a_writable_path_equal_to_a_runtime_directory(fake):
    runtime = fake.tmp / "py"
    runtime.mkdir()
    with pytest.raises(sandbox.SandboxUnavailable):
        lw.launch(fake.req(runtime=[runtime], write=[runtime]))
    assert fake.revokes == []


def test_launch_rejects_wildcard_paths_before_granting_anything(fake):
    with pytest.raises(sandbox.SandboxUnavailable):
        lw.launch(fake.req(read=[Path("C:/data*")]))
    assert fake.grants == [] and fake.revokes == []
    assert lw._ledger_load()["per_run"] == []


def test_launch_retries_stale_entries_before_running(fake):
    stale = fake.tmp / "stale"
    stale.mkdir()
    lw._ledger_add_per_run("S-1-15-2-9", stale)
    lw.launch(fake.req())
    assert str(stale) in fake.revokes
    assert fake.runs == 1
    assert lw._ledger_load()["per_run"] == []


def test_launch_fails_closed_when_a_stale_grant_cannot_be_revoked(fake):
    stale = fake.tmp / "stale"
    stale.mkdir()
    lw._ledger_add_per_run("S-1-15-2-9", stale)
    fake.revoke_rc = 5
    with pytest.raises(sandbox.SandboxUnavailable, match="could not be removed"):
        lw.launch(fake.req())
    assert fake.runs == 0 and fake.grants == []
    assert lw._ledger_load()["per_run"] == [["S-1-15-2-9", str(stale)]]


def test_a_failing_ledger_write_does_not_abort_the_remaining_revokes_or_the_scrub(fake, monkeypatch):
    def broken_remove(sid, path):
        raise OSError("disk full")

    monkeypatch.setattr(lw, "_ledger_remove_per_run", broken_remove)
    lw.launch(fake.req(read=[fake.tmp]))
    assert fake.revokes == [str(fake.tmp), str(fake.run)]
    assert len(fake.scrubs) == 2


def test_run_errors_pass_through_launch_unchanged(fake):
    fake.run_error = sandbox.SandboxRunError("started, then failed")
    with pytest.raises(sandbox.SandboxRunError):
        lw.launch(fake.req())
    assert lw._ledger_load()["per_run"] == []


def test_sweep_keeps_entries_whose_revoke_failed(fake, monkeypatch):
    other = fake.tmp / "other"
    other.mkdir()
    lw._ledger_add_per_run("S-1-15-2-9", fake.run)
    lw._ledger_add_per_run("S-1-15-2-9", other)
    monkeypatch.setattr(lw, "_revoke", lambda path, sid: (5, "denied") if Path(path) == other else (0, ""))
    assert lw.sweep_stale_grants() == 1
    assert lw._ledger_load()["per_run"] == [["S-1-15-2-9", str(other)]]


def test_sweep_drops_entries_for_paths_that_no_longer_exist(fake):
    lw._ledger_add_per_run("S-1-15-2-9", fake.tmp / "gone")
    assert lw.sweep_stale_grants() == 1
    assert lw._ledger_load()["per_run"] == []


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
        for cleanup in ("sweep", "next launch"):
            lw_mod._ledger_add_per_run(sid, layout.extra_dir)
            assert lw_mod._grant(layout.extra_dir, sid, "RX")[0] == 0
            if cleanup == "sweep":
                assert lw_mod.sweep_stale_grants() == 1
            # The next launch also retries stale entries before it runs anything, so the leftover
            # grant is gone either way and the probe must not see it.
            assert _probe(lw_mod, layout)["read_extra"].startswith("DENIED")
            assert json.loads(lw_mod.ledger_path().read_text())["per_run"] == []

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
