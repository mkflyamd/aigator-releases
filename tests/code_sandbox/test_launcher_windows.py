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


@pytest.fixture(autouse=True)
def _no_real_acl_reads(request, monkeypatch):
    """Unit tests never run icacls or open real files for WRITE_DAC; tests of the ACL logic patch these."""
    if "windows_container" in request.fixturenames:
        return
    monkeypatch.setattr(lw, "_dacl_aces", lambda path: None)
    monkeypatch.setattr(lw, "_can_change_acl", lambda path: True)


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
    assert lw._ledger_load() == {
        "runtime": {}, "per_run": [], "scratch": {}, "runtime_born": {}, "package_children": {},
    }


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


def test_cmdline_passes_a_raw_arg_verbatim():
    from sandbox import RawArg

    argv = ["cmd.exe", "/d", "/s", "/c", RawArg('"echo x > "C:\a b\f.txt""')]
    assert lw._cmdline(argv) == 'cmd.exe /d /s /c "echo x > "C:\a b\f.txt""'


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
    state = SimpleNamespace(grants=[], revokes=[], scrubs=[], revoke_rc=0, grant_error=None, run_error=None, runs=0,
                           reinherits=[], packages=[])
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

    def reinherit(path):
        state.reinherits.append(Path(path))
        return 0, ""

    monkeypatch.setattr(lw, "_grant", grant)
    monkeypatch.setattr(lw, "_revoke", revoke)
    monkeypatch.setattr(lw, "_reinherit", reinherit)
    monkeypatch.setattr(lw, "_site_package_dirs", lambda: list(state.packages))
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


def _scratch_req(fake, cwd):
    return SandboxRequest(argv=["cmd"], cwd=cwd, env={}, runtime_paths=[], read_paths=[], write_paths=[],
                          network=False, timeout=5, scratch_path=fake.scratch)


def test_scratch_folder_is_granted_once_and_never_per_run(fake):
    fake.scratch = fake.tmp / "work"
    (fake.scratch / "sub").mkdir(parents=True)
    lw.launch(_scratch_req(fake, fake.scratch))
    lw.launch(_scratch_req(fake, fake.scratch / "sub"))
    assert fake.grants == [(str(fake.scratch), "M")]
    assert fake.revokes == []
    assert lw._ledger_load()["per_run"] == []


def test_scratch_folder_is_granted_again_when_it_was_recreated(fake):
    fake.scratch = fake.tmp / "work"
    fake.scratch.mkdir()
    lw.launch(_scratch_req(fake, fake.scratch))
    entry = lw._ledger_load()
    sid = "S-1-15-2-9"
    entry["scratch"][sid] = [entry["scratch"][sid][0].rsplit("|", 1)[0] + "|1"]
    lw._ledger_save(entry)
    lw.launch(_scratch_req(fake, fake.scratch))
    assert fake.grants == [(str(fake.scratch), "M")] * 2


def test_failed_scratch_grant_falls_back_to_a_per_run_grant(fake, monkeypatch):
    fake.scratch = fake.tmp / "work"
    fake.scratch.mkdir()
    monkeypatch.setattr(lw, "_ensure_scratch_grant", lambda sid, path: False)
    lw.launch(_scratch_req(fake, fake.scratch))
    assert fake.grants == [(str(fake.scratch), "M")]
    assert fake.revokes == [str(fake.scratch)]


def test_shell_requests_use_their_own_profile(fake, monkeypatch):
    names = []
    monkeypatch.setattr(lw, "ensure_profile", lambda name: (names.append(name), (None, "S-1-15-2-9"))[1])
    fake.scratch = fake.tmp / "work"
    fake.scratch.mkdir()
    lw.launch(_scratch_req(fake, fake.scratch))
    lw.launch(fake.req())
    assert names == [lw.PROFILE_NAME + lw.SHELL_PROFILE_SUFFIX, lw.PROFILE_NAME]


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


# ── DACL-driven grant and revoke decisions: every OS ──────────────────────────

# Real DACL of C:\Program Files\LibreOffice as written by `icacls /save` (one line of SDDL).
PROGRAM_FILES_SDDL = (
    "D:AI(A;ID;FA;;;S-1-5-80-1)(A;CIIOID;GA;;;S-1-5-80-1)(A;ID;FA;;;SY)(A;OICIIOID;GA;;;SY)"
    "(A;ID;0x1200a9;;;BU)(A;OICIIOID;GXGR;;;BU)(A;ID;0x1200a9;;;AC)(A;OICIIOID;GXGR;;;AC)"
    "(A;ID;0x1200a9;;;S-1-15-2-2)(A;OICIIOID;GXGR;;;S-1-15-2-2)"
)
SID = "S-1-15-2-9"


def _aces(sddl):
    return lambda path: lw._parse_sddl_aces(sddl)


def test_sddl_parser_reads_types_flags_rights_and_trustee():
    aces = lw._parse_sddl_aces(PROGRAM_FILES_SDDL)
    assert ("A", frozenset({"ID"}), 0x1200A9, "AC") in aces
    kind, flags, mask, trustee = aces[7]
    assert (kind, trustee) == ("A", "AC") and flags == {"OI", "CI", "IO", "ID"} and mask & 0x80000000 and mask & 0x20000000


def test_a_folder_with_the_all_application_packages_read_ace_needs_no_grant(tmp_path, monkeypatch):
    monkeypatch.setattr(lw, "_dacl_aces", _aces(PROGRAM_FILES_SDDL))
    assert lw._container_can_read(tmp_path) is True


def test_read_access_is_not_assumed_when_the_ace_is_incomplete_denied_or_unreadable(tmp_path, monkeypatch):
    only_self = "D:(A;;0x1200a9;;;AC)"
    deny = PROGRAM_FILES_SDDL + "(D;;FR;;;AC)"
    only_inherit_only = "D:(A;OICIIO;GXGR;;;AC)"
    for sddl in (only_self, deny, only_inherit_only):
        monkeypatch.setattr(lw, "_dacl_aces", _aces(sddl))
        assert lw._container_can_read(tmp_path) is False, sddl
    monkeypatch.setattr(lw, "_dacl_aces", lambda path: None)
    assert lw._container_can_read(tmp_path) is False


def test_a_single_file_only_needs_its_own_read_ace(tmp_path, monkeypatch):
    f = tmp_path / "a.txt"
    f.write_text("x")
    monkeypatch.setattr(lw, "_dacl_aces", _aces("D:(A;;0x1200a9;;;AC)"))
    assert lw._container_can_read(f) is True


def test_revoke_treats_an_absent_ace_as_revoked_without_running_icacls(tmp_path, monkeypatch):
    monkeypatch.setattr(lw, "_dacl_aces", _aces(PROGRAM_FILES_SDDL))
    monkeypatch.setattr(lw, "_revoke", lambda path, sid: pytest.fail("nothing to revoke"))
    assert lw._revoke_ok(SID, tmp_path) is True


def test_revoke_ignores_inherited_aces_it_could_never_remove(tmp_path, monkeypatch):
    monkeypatch.setattr(lw, "_dacl_aces", _aces(f"D:(A;ID;FA;;;{SID})"))
    monkeypatch.setattr(lw, "_revoke", lambda path, sid: pytest.fail("inherited ACEs are not revoked"))
    assert lw._revoke_ok(SID, tmp_path) is True


def test_revoke_keeps_the_entry_only_while_the_ace_is_really_there(tmp_path, monkeypatch):
    monkeypatch.setattr(lw, "_dacl_aces", _aces(f"D:(A;OICI;M;;;{SID})"))
    monkeypatch.setattr(lw, "_revoke", lambda path, sid: (5, "denied"))
    assert lw._revoke_ok(SID, tmp_path) is False


def test_revoke_that_errors_but_leaves_no_ace_counts_as_done(tmp_path, monkeypatch):
    states = iter([f"D:(A;OICI;M;;;{SID})", "D:(A;ID;FA;;;SY)"])
    monkeypatch.setattr(lw, "_dacl_aces", lambda path: lw._parse_sddl_aces(next(states)))
    monkeypatch.setattr(lw, "_revoke", lambda path, sid: (1, "partial"))
    assert lw._revoke_ok(SID, tmp_path) is True


def test_a_stale_entry_with_no_ace_behind_it_is_swept_and_the_sandbox_runs(fake, monkeypatch):
    # The write-ahead ledger entry of a grant icacls refused (a folder the user does not own).
    program_files = fake.tmp / "Program Files"
    program_files.mkdir()
    lw._ledger_add_per_run("S-1-15-2-9", program_files)
    monkeypatch.setattr(lw, "_dacl_aces", _aces(PROGRAM_FILES_SDDL))
    fake.revoke_rc = 5
    lw.launch(fake.req())
    assert lw._ledger_load()["per_run"] == []
    assert fake.runs == 1


def test_a_folder_every_appcontainer_can_read_is_not_granted_or_ledgered(fake, monkeypatch):
    program_files = fake.tmp / "Program Files"
    program_files.mkdir()
    monkeypatch.setattr(lw, "_dacl_aces", lambda path: lw._parse_sddl_aces(PROGRAM_FILES_SDDL) if Path(path) == program_files else None)
    lw.launch(fake.req(read=[program_files]))
    assert str(program_files) not in [g[0] for g in fake.grants]
    assert fake.revokes == [str(fake.run)]
    assert fake.runs == 1 and lw._ledger_load()["per_run"] == []


def test_a_folder_whose_acl_the_user_cannot_change_is_refused_before_any_ledger_write(fake, monkeypatch):
    locked = fake.tmp / "locked"
    locked.mkdir()
    monkeypatch.setattr(lw, "_can_change_acl", lambda path: Path(path) != locked)
    with pytest.raises(sandbox.SandboxPathNotGrantable) as info:
        lw.launch(fake.req(read=[locked]))
    assert str(locked) in str(info.value) and info.value.paths == [str(locked)]
    assert isinstance(info.value, sandbox.SandboxUnavailable)
    assert fake.grants == [] and fake.revokes == [] and fake.runs == 0
    assert lw._ledger_load()["per_run"] == []


def test_ungrantable_paths_lists_only_what_could_never_work(tmp_path, monkeypatch):
    readable, locked, missing = tmp_path / "readable", tmp_path / "locked", tmp_path / "missing"
    readable.mkdir()
    locked.mkdir()
    monkeypatch.setattr(lw, "_container_can_read", lambda path, sid=None: Path(path) == readable)
    monkeypatch.setattr(lw, "_can_change_acl", lambda path: False)
    assert lw.ungrantable_paths([readable, locked, missing], []) == [locked]
    assert lw.ungrantable_paths([], [readable]) == [readable]  # a write path always needs a changeable ACL


def test_the_paused_message_names_the_stuck_folder_and_a_way_forward(fake, monkeypatch):
    stuck = fake.tmp / "stuck"
    stuck.mkdir()
    lw._ledger_add_per_run("S-1-15-2-9", stuck)
    monkeypatch.setattr(lw, "_dacl_aces", _aces(f"D:(A;OICI;M;;;{SID})"))
    fake.revoke_rc = 5
    with pytest.raises(sandbox.SandboxUnavailable) as info:
        lw.launch(fake.req())
    assert str(stuck) in str(info.value) and "Restarting AI Gator" in str(info.value)
    assert "Settings" not in str(info.value)


def test_request_time_check_is_a_noop_off_windows(monkeypatch):
    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    assert sandbox.ungrantable_paths([Path("/etc")], [Path("/tmp")]) == []


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


def _rx(fake, path):
    return sum(1 for g in fake.grants if g == (str(path), "RX"))


def test_a_runtime_folder_is_granted_once_while_it_is_unchanged(fake):
    skill = fake.tmp / "skill"
    skill.mkdir()
    lw.launch(fake.req(runtime=[skill]))
    lw.launch(fake.req(runtime=[skill]))
    assert _rx(fake, skill) == 1


def test_a_runtime_folder_is_granted_again_when_it_was_recreated(fake):
    skill = fake.tmp / "skill"
    skill.mkdir()
    lw.launch(fake.req(runtime=[skill]))
    data = lw._ledger_load()
    born = data["runtime_born"]["S-1-15-2-9"]
    born[os.path.normcase(str(skill))] = 1
    lw._ledger_save(data)
    lw.launch(fake.req(runtime=[skill]))
    assert _rx(fake, skill) == 2


def test_a_runtime_folder_whose_ace_vanished_is_granted_again(fake, monkeypatch):
    skill = fake.tmp / "skill"
    skill.mkdir()
    lw.launch(fake.req(runtime=[skill]))
    monkeypatch.setattr(lw, "_ace_present", lambda path, sid: False)
    lw.launch(fake.req(runtime=[skill]))
    assert _rx(fake, skill) == 2


def test_a_runtime_folder_whose_acl_cannot_be_read_stays_trusted(fake, monkeypatch):
    skill = fake.tmp / "skill"
    skill.mkdir()
    lw.launch(fake.req(runtime=[skill]))
    monkeypatch.setattr(lw, "_ace_present", lambda path, sid: None)
    lw.launch(fake.req(runtime=[skill]))
    assert _rx(fake, skill) == 1


def test_a_runtime_folder_recorded_by_an_older_ledger_is_granted_again(fake):
    skill = fake.tmp / "skill"
    skill.mkdir()
    lw._ledger_save({"runtime": {"S-1-15-2-9": [os.path.normcase(str(skill))]}, "per_run": [], "scratch": {}})
    path = lw.ledger_path()
    old = json.loads(path.read_text())
    old.pop("v")
    path.write_text(json.dumps(old))
    lw.launch(fake.req(runtime=[skill]))
    assert _rx(fake, skill) == 1


def _site(fake):
    site = fake.tmp / "site-packages"
    (site / "PIL").mkdir(parents=True)
    (site / "PIL" / "_imaging.pyd").write_text("x")
    fake.packages = [site]
    return site


def test_the_first_run_re_applies_inheritance_to_the_whole_site_packages(fake):
    site = _site(fake)
    lw.launch(fake.req(runtime=[fake.tmp]))
    assert fake.reinherits == [site]


def test_an_unchanged_site_packages_is_not_touched_again(fake):
    _site(fake)
    lw.launch(fake.req(runtime=[fake.tmp]))
    fake.reinherits.clear()
    lw.launch(fake.req(runtime=[fake.tmp]))
    assert fake.reinherits == []


def test_a_package_installed_later_is_re_inherited_by_itself(fake):
    site = _site(fake)
    lw.launch(fake.req(runtime=[fake.tmp]))
    fake.reinherits.clear()
    (site / "pptx").mkdir()
    (site / "__pycache__").mkdir()
    lw.launch(fake.req(runtime=[fake.tmp]))
    assert fake.reinherits == [site / "pptx"]


def test_a_package_replaced_in_place_is_re_inherited(fake):
    site = _site(fake)
    lw.launch(fake.req(runtime=[fake.tmp]))
    fake.reinherits.clear()
    (site / "PIL" / "new.pyd").write_text("y")
    os.utime(site / "PIL", ns=(1, 1))
    lw.launch(fake.req(runtime=[fake.tmp]))
    assert fake.reinherits == [site / "PIL"]


def test_a_site_packages_outside_the_granted_runtime_is_left_alone(fake):
    other = fake.tmp.parent / (fake.tmp.name + "-other")
    (other / "pkg").mkdir(parents=True)
    fake.packages = [other]
    runtime = fake.tmp / "runtime"
    runtime.mkdir()
    lw.launch(fake.req(runtime=[runtime]))
    assert fake.reinherits == []


def test_a_failed_refresh_does_not_stop_the_run(fake, monkeypatch):
    _site(fake)
    monkeypatch.setattr(lw, "_reinherit", lambda path: (_ for _ in ()).throw(OSError("denied")))
    lw.launch(fake.req(runtime=[fake.tmp]))
    assert fake.runs == 1


# ---- start(): long-running sandboxed process ----
from types import SimpleNamespace as _NS

from sandbox import SandboxRunError as _SandboxRunError

_STARTED = lw._Started(1, 2, 3, 4, 99)


class _Spy:
    def __init__(self, started, on_exit):
        self.started, self.on_exit = started, on_exit


def _streaming(monkeypatch, result="done"):
    lw._HELD.clear()
    monkeypatch.setattr(lw, "SandboxProcess", _Spy)
    monkeypatch.setattr(lw, "_run_contained", lambda *a, stream=False, **k: _STARTED if stream else result)


def test_start_holds_grants_until_the_process_exits(fake, monkeypatch):
    _streaming(monkeypatch)
    spy = lw.start(fake.req(write=[fake.run]))
    held = lw._ledger_load()["per_run"]
    assert held and fake.revokes == []
    spy.on_exit()
    assert len(fake.revokes) == len(held)
    assert lw._ledger_load()["per_run"] == []


def test_later_foreground_launch_leaves_held_grants_alone(fake, monkeypatch):
    _streaming(monkeypatch)
    spy = lw.start(fake.req(write=[fake.run]))
    held = {tuple(e) for e in lw._ledger_load()["per_run"]}
    assert lw.launch(fake.req(write=[fake.run])) == "done"
    assert fake.revokes == []
    assert {tuple(e) for e in lw._ledger_load()["per_run"]} == held
    spy.on_exit()
    assert lw._ledger_load()["per_run"] == []


def test_start_frees_the_profile_sid_once(fake, monkeypatch):
    _streaming(monkeypatch)
    freed = []
    monkeypatch.setattr(lw, "_api", lambda: _NS(adv=_NS(FreeSid=freed.append)))
    lw.start(fake.req(write=[fake.run]))
    assert freed == [None]


def test_start_failure_releases_everything(fake, monkeypatch):
    lw._HELD.clear()

    def boom(*a, **k):
        raise lw._run_error(True, "x")

    monkeypatch.setattr(lw, "_run_contained", boom)
    with pytest.raises(_SandboxRunError):
        lw.start(fake.req(write=[fake.run]))
    assert fake.revokes
    assert lw._ledger_load()["per_run"] == []
    assert lw._HELD == {}


# ---- SandboxProcess.terminate(): idempotent, thread-safe, safe after exit ----
import threading as _threading

_PROC, _JOB = 101, 102


def _fake_process(monkeypatch):
    """A SandboxProcess over real pipes and a fake process/job: killing the job ends the process."""
    import _winapi
    import ctypes.wintypes as wt

    exited = _threading.Event()
    calls = []

    def wait(handle, ms):
        exited.wait()
        return 0

    def exit_code(handle, ref):
        ref._obj.value = 7

    def kill(handle, code):
        calls.append(("terminate_job", handle.value))
        exited.set()

    k32 = _NS(WaitForSingleObject=wait, GetExitCodeProcess=exit_code, TerminateJobObject=kill,
              CloseHandle=lambda handle: calls.append(("close", handle.value)))
    monkeypatch.setattr(lw, "_api", lambda: _NS(k32=k32, wt=wt))
    out_rd, child_out = _winapi.CreatePipe(None, 0)
    child_in, in_wr = _winapi.CreatePipe(None, 0)
    exits = []
    proc = lw.SandboxProcess(lw._Started(_PROC, _JOB, out_rd, in_wr, 99), on_exit=lambda: exits.append(1))
    return _NS(proc=proc, exited=exited, calls=calls, exits=exits, child_out=child_out, child_in=child_in)


@pytest.mark.skipif(sys.platform != "win32", reason="SandboxProcess wraps Windows handles")
def test_terminate_from_many_threads_closes_everything_once(monkeypatch):
    import _winapi

    f = _fake_process(monkeypatch)
    try:
        threads = [_threading.Thread(target=f.proc.terminate) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        assert f.proc.wait(5) == 7
        f.proc.terminate()
        assert f.calls.count(("terminate_job", _JOB)) == 1
        assert f.calls.count(("close", _JOB)) == 1
        assert f.calls.count(("close", _PROC)) == 1
        assert f.proc.stdout.closed and f.proc.stdin.closed
        assert f.exits == [1]
    finally:
        _winapi.CloseHandle(f.child_out)
        _winapi.CloseHandle(f.child_in)


@pytest.mark.skipif(sys.platform != "win32", reason="SandboxProcess wraps Windows handles")
def test_terminate_after_the_process_exited_is_safe_and_output_stays_readable(monkeypatch):
    import _winapi

    f = _fake_process(monkeypatch)
    try:
        _winapi.WriteFile(f.child_out, b"last words")
        _winapi.CloseHandle(f.child_out)
        f.exited.set()
        assert f.proc.wait(5) == 7
        assert f.proc.poll() == 7
        assert f.calls.count(("close", _JOB)) == 1
        assert f.proc.stdout.read() == b"last words"
        f.proc.terminate()
        f.proc.terminate()
        assert f.calls.count(("close", _JOB)) == 1
        assert f.calls.count(("close", _PROC)) == 1
        assert f.proc.stdout.closed and f.proc.stdin.closed
        assert f.exits == [1]
    finally:
        _winapi.CloseHandle(f.child_in)


# ---- start() runs under its own AppContainer profile (fix round 1) ----
_SIDS = {"base": "S-1-15-2-1001", ".Shell": "S-1-15-2-1002", ".Server": "S-1-15-2-1003"}


def _per_profile(fake, monkeypatch):
    """Give each profile name its own SID and record every icacls grant/revoke with the SID it targets."""
    fake.names, fake.acl = [], []

    def ensure_profile(name):
        fake.names.append(name)
        suffix = name[len(lw.PROFILE_NAME):] or "base"
        return None, _SIDS[suffix]

    def grant(path, sid, perm):
        fake.acl.append(("grant", sid, str(path), perm))
        return 0, ""

    def revoke(path, sid):
        fake.acl.append(("revoke", sid, str(path)))
        return 0, ""

    monkeypatch.setattr(lw, "ensure_profile", ensure_profile)
    monkeypatch.setattr(lw, "_grant", grant)
    monkeypatch.setattr(lw, "_revoke", revoke)


def _sids(fake, op):
    return {entry[1] for entry in fake.acl if entry[0] == op}


def test_start_uses_the_server_profile_and_launch_selection_is_unchanged(fake, monkeypatch):
    _streaming(monkeypatch)
    _per_profile(fake, monkeypatch)
    fake.scratch = fake.tmp / "work"
    fake.scratch.mkdir()
    lw.start(_scratch_req(fake, fake.scratch))
    lw.start(fake.req())
    lw.launch(_scratch_req(fake, fake.scratch))
    lw.launch(fake.req())
    server = lw.PROFILE_NAME + lw.SERVER_PROFILE_SUFFIX
    assert fake.names == [server, server, lw.PROFILE_NAME + lw.SHELL_PROFILE_SUFFIX, lw.PROFILE_NAME]


def test_a_foreground_run_never_touches_a_held_server_grant(fake, monkeypatch):
    _streaming(monkeypatch)
    _per_profile(fake, monkeypatch)
    spy = lw.start(fake.req(write=[fake.run]))
    server_entries = [e for e in lw._ledger_load()["per_run"] if e[0] == _SIDS[".Server"]]
    assert server_entries and _sids(fake, "grant") == {_SIDS[".Server"]}
    fake.acl.clear()
    assert lw.launch(fake.req(write=[fake.run])) == "done"
    # The foreground run gets and loses its own entry; the server's SID is never granted or revoked.
    assert _sids(fake, "grant") == {_SIDS["base"]}
    assert _sids(fake, "revoke") == {_SIDS["base"]}
    assert lw._ledger_load()["per_run"] == server_entries
    fake.acl.clear()
    spy.on_exit()
    assert _sids(fake, "revoke") == {_SIDS[".Server"]}
    assert lw._ledger_load()["per_run"] == []


def test_a_foreground_run_cannot_widen_a_held_server_grant(fake, monkeypatch):
    _streaming(monkeypatch)
    _per_profile(fake, monkeypatch)
    project = fake.tmp / "project"
    project.mkdir()
    spy = lw.start(fake.req(read=[project]))
    lw.launch(fake.req(write=[project]))
    on_project = [e for e in fake.acl if e[2] == str(project)]
    assert ("grant", _SIDS[".Server"], str(project), "RX") in on_project
    assert ("grant", _SIDS["base"], str(project), "M") in on_project
    assert ("revoke", _SIDS["base"], str(project)) in on_project
    # Nothing ever gave the server's SID more than read on the project.
    assert [e for e in on_project if e[1] == _SIDS[".Server"] and e[0] == "grant"] == [
        ("grant", _SIDS[".Server"], str(project), "RX")]
    spy.on_exit()


def test_the_sweep_still_skips_a_live_servers_grants(fake, monkeypatch):
    _streaming(monkeypatch)
    _per_profile(fake, monkeypatch)
    spy = lw.start(fake.req(write=[fake.run]))
    held = lw._ledger_load()["per_run"]
    fake.acl.clear()
    assert lw.sweep_stale_grants() == 0
    assert fake.acl == []
    assert lw._ledger_load()["per_run"] == held
    spy.on_exit()
    assert lw.sweep_stale_grants() == 0
    assert lw._ledger_load()["per_run"] == []


def test_two_servers_share_the_server_profile_and_count_their_holds(fake, monkeypatch):
    _streaming(monkeypatch)
    _per_profile(fake, monkeypatch)
    first = lw.start(fake.req(write=[fake.run]))
    second = lw.start(fake.req(write=[fake.run]))
    fake.acl.clear()
    first.on_exit()
    assert _sids(fake, "revoke") == set()
    assert lw._ledger_load()["per_run"]
    second.on_exit()
    assert _sids(fake, "revoke") == {_SIDS[".Server"]}
    assert lw._ledger_load()["per_run"] == []


def test_readable_or_grantable_checks_the_server_profile(monkeypatch, tmp_path):
    names, seen = [], []
    monkeypatch.setattr(lw, "ensure_profile", lambda name: (names.append(name), (None, "S-1-15-2-77"))[1])
    monkeypatch.setattr(lw, "_api", lambda: SimpleNamespace(adv=SimpleNamespace(FreeSid=lambda p: None)))
    monkeypatch.setattr(lw, "_container_can_read", lambda path, sid: seen.append(sid) or True)
    assert lw.readable_or_grantable(tmp_path) is True
    assert names == [lw.PROFILE_NAME + lw.SERVER_PROFILE_SUFFIX]
    assert seen == ["S-1-15-2-77"]


def test_the_server_profiles_storage_is_scrubbed_like_the_others(tmp_path, monkeypatch):
    ac = tmp_path / "Packages" / (lw.PROFILE_NAME + lw.SERVER_PROFILE_SUFFIX) / "AC"
    (ac / "sub").mkdir(parents=True)
    (ac / "top.txt").write_text("leaked")
    monkeypatch.setattr(lw, "_container_folder", lambda sid: ac)
    lw._scrub_container("S-1-15-2-9")
    assert ac.is_dir() and list(ac.iterdir()) == []


def test_the_test_profile_fixture_deletes_the_server_profile_too():
    src = (Path(__file__).parents[1] / "conftest.py").read_text(encoding="utf-8")
    assert "lw.delete_profile(name + lw.SERVER_PROFILE_SUFFIX)" in src


@pytest.mark.skipif(sys.platform != "win32", reason="SandboxProcess wraps Windows handles")
def test_a_failed_wait_ends_the_tree_before_releasing_its_grants(monkeypatch, caplog):
    import _winapi
    import ctypes.wintypes as wt

    calls, waits = [], []

    def wait(handle, ms):
        waits.append(ms)
        return lw.WAIT_FAILED if len(waits) == 1 else 0

    def exit_code(handle, ref):
        ref._obj.value = 1

    k32 = _NS(WaitForSingleObject=wait, GetExitCodeProcess=exit_code,
              TerminateJobObject=lambda handle, code: calls.append(("terminate_job", handle.value)),
              CloseHandle=lambda handle: calls.append(("close", handle.value)))
    monkeypatch.setattr(lw, "_api", lambda: _NS(k32=k32, wt=wt))
    out_rd, child_out = _winapi.CreatePipe(None, 0)
    child_in, in_wr = _winapi.CreatePipe(None, 0)
    exits = []
    try:
        proc = lw.SandboxProcess(lw._Started(_PROC, _JOB, out_rd, in_wr, 99),
                                 on_exit=lambda: exits.append(list(calls)))
        assert proc.wait(5) == 1
        assert exits and ("terminate_job", _JOB) in exits[0]
        assert "waiting for a long-running process failed" in caplog.text
        proc.terminate()
    finally:
        _winapi.CloseHandle(child_out)
        _winapi.CloseHandle(child_in)
