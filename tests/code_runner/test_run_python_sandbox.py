import pytest

import sandbox
import skills.code_runner.tools as cr_mod
from sandbox import approvals, task_grants
from sandbox.policy import Policy

FAKE = "aigator-fake-api-key"


@pytest.fixture
def calls(tmp_path, monkeypatch):
    import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(cr_mod, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(cr_mod, "_sandbox_mode", lambda cfg, policy: ("enforced", None))
    approvals._reset()
    task_grants._reset()
    seen = []

    def fake_launch(req):
        seen.append(req)
        (req.cwd / "made.txt").write_text("x")
        return sandbox.SandboxResult(returncode=0, stdout="fake-ok\n", stderr="", timed_out=False)

    monkeypatch.setattr(sandbox, "launch_sandboxed", fake_launch)
    yield seen
    approvals._reset()
    task_grants._reset()


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


def test_enforced_run_uses_launcher_with_filtered_env(calls, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", FAKE)
    result = cr_mod._tool_run_python(code="print('hi')", _context_id="tab-1")
    assert result["error"] is None and result["stdout"] == "fake-ok\n"
    assert result["sandbox"] == "enforced"
    assert [f["name"] for f in result["files"]] == ["made.txt"]
    (req,) = calls
    assert "GITHUB_TOKEN" not in req.env and FAKE not in req.env.values()
    assert req.cwd.name == result["_sandbox_telemetry"]["run_id"]
    assert req.read_paths == [] and req.write_paths == [] and req.network is False
    assert req.argv[-1].endswith("code.py")
    assert result["_sandbox_telemetry"] == {
        "run_id": req.cwd.name, "skill_id": "", "level": "enforced", "network": False,
        "extra_read": 0, "extra_write": 0, "approval": None,
    }


def test_extra_paths_need_approval_and_are_used_once(calls, data_dir):
    args = dict(code="print(1)", extra_read_paths=[str(data_dir)], network_hosts=["API.example.com:443"], _context_id="tab-1")
    first = cr_mod._tool_run_python(**args)
    assert first["approval_required"] is True and calls == []
    card = first["_sandbox_approval"]
    assert card["read_paths"] == [str(data_dir.resolve())]
    assert card["network_hosts"] == ["api.example.com:443"]
    assert card["context_id"] == "tab-1"
    assert first["_sandbox_telemetry"]["approval"] == "requested"
    assert str(data_dir) not in str(first["_sandbox_telemetry"])

    again = cr_mod._tool_run_python(**args)  # still pending: same request, no run
    assert again["request_id"] == first["request_id"] and calls == []

    approvals.decide(first["request_id"], "tab-1", True)
    ran = cr_mod._tool_run_python(**args)
    assert ran["error"] is None
    (req,) = calls
    assert req.read_paths == [data_dir.resolve()] and req.network is True
    assert ran["_sandbox_telemetry"]["approval"] == "approved"
    assert ran["_sandbox_telemetry"]["extra_read"] == 1 and ran["_sandbox_telemetry"]["network"] is True

    third = cr_mod._tool_run_python(**args)  # consumed
    assert third["approval_required"] is True and len(calls) == 1


def test_task_approval_covers_later_runs_in_the_same_tab_only(calls, data_dir):
    args = dict(code="print(1)", extra_read_paths=[str(data_dir)], network_hosts=["api.example.com:443"], _context_id="tab-1")
    first = cr_mod._tool_run_python(**args)
    approved = approvals.decide(first["request_id"], "tab-1", True, scope="task")
    task_grants.add(approved.context_id, approved.read_paths, approved.write_paths, approved.network_hosts)
    ran = cr_mod._tool_run_python(**args)
    assert ran["error"] is None and ran["_sandbox_telemetry"]["approval"] == "task_approved"
    # Not consumed: a different script with the same access, and a narrower subfolder, run without a card.
    sub = data_dir / "sub"
    sub.mkdir()
    again = cr_mod._tool_run_python(**{**args, "code": "print(2)", "extra_read_paths": [str(sub)]})
    assert again["error"] is None and again["_sandbox_telemetry"]["approval"] == "task_approved"
    assert len(calls) == 2
    # Another tab, a new host, or a wider set still needs its own card.
    assert cr_mod._tool_run_python(**{**args, "_context_id": "tab-2"})["approval_required"]
    assert cr_mod._tool_run_python(**{**args, "network_hosts": ["other.example.com:443"]})["approval_required"]
    assert cr_mod._tool_run_python(**{**args, "extra_write_paths": [str(data_dir)]})["approval_required"]
    assert len(calls) == 2
    # The next user message ends it.
    task_grants.end_for_tab("tab-1")
    assert cr_mod._tool_run_python(**args)["approval_required"] is True


def test_task_approval_is_used_without_a_tab_id_too(calls, data_dir):
    args = dict(code="1", extra_write_paths=[str(data_dir)])
    first = cr_mod._tool_run_python(**args)
    assert first["_sandbox_approval"]["context_id"] == "default"
    approved = approvals.decide(first["request_id"], "default", True, scope="task")
    task_grants.add(approved.context_id, approved.read_paths, approved.write_paths, approved.network_hosts)
    assert cr_mod._tool_run_python(**args)["_sandbox_telemetry"]["approval"] == "task_approved"
    task_grants.end_for_tab("default")  # what the next user message does
    assert cr_mod._tool_run_python(**args)["approval_required"] is True


def test_different_set_or_tab_needs_new_approval(calls, data_dir, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    first = cr_mod._tool_run_python(code="1", extra_read_paths=[str(data_dir)], _context_id="tab-1")
    approvals.decide(first["request_id"], "tab-1", True)
    assert cr_mod._tool_run_python(code="1", extra_read_paths=[str(data_dir), str(other)], _context_id="tab-1")["approval_required"]
    assert cr_mod._tool_run_python(code="1", extra_read_paths=[str(data_dir)], _context_id="tab-2")["approval_required"]
    assert calls == []


def test_confirmed_true_does_not_bypass_the_approval(calls, data_dir):
    result = cr_mod._tool_run_python(code="1", extra_read_paths=[str(data_dir)], confirmed=True, _context_id="tab-1")
    assert result["approval_required"] is True and calls == []


def test_flagged_ops_do_not_consume_an_approval(calls, data_dir):
    args = dict(code="import os\nos.system('echo hi')\n", extra_read_paths=[str(data_dir)], _context_id="tab-1")
    first = cr_mod._tool_run_python(**{**args, "code": "print(1)"})
    approvals.decide(first["request_id"], "tab-1", True)
    assert cr_mod._tool_run_python(**args)["hitl_required"] is True  # approval still valid
    ran = cr_mod._tool_run_python(confirmed=True, **args)
    assert ran["error"] is None and len(calls) == 1


def test_denied_and_expired_return_fixed_errors(calls, data_dir):
    args = dict(code="1", extra_write_paths=[str(data_dir)], _context_id="tab-1")
    req = cr_mod._tool_run_python(**args)
    approvals.decide(req["request_id"], "tab-1", False)
    denied = cr_mod._tool_run_python(**args)
    assert denied["error"] == cr_mod._DENIED_MSG
    assert denied["_sandbox_telemetry"]["approval"] == "denied"
    req2 = cr_mod._tool_run_python(**args)
    approvals._REQUESTS[req2["request_id"]].created_at -= 601
    expired = cr_mod._tool_run_python(**args)
    assert expired["error"] == cr_mod._EXPIRED_MSG
    assert expired["_sandbox_telemetry"]["approval"] == "expired"
    assert calls == []


def test_never_grantable_path_is_refused_without_a_card(calls):
    import pathlib

    result = cr_mod._tool_run_python(code="1", extra_read_paths=[str(pathlib.Path.home() / ".ssh")], _context_id="tab-1")
    assert "can never be granted" in result["error"]
    assert "approval_required" not in result and approvals._REQUESTS == {} and calls == []


def test_policy_disabled_network_deny_and_strict(calls, data_dir, monkeypatch):
    monkeypatch.setattr(cr_mod, "load_policy", lambda: Policy(code_runner="disabled"))
    assert cr_mod._tool_run_python(code="1")["error"] == cr_mod._DISABLED_MSG
    monkeypatch.setattr(cr_mod, "load_policy", lambda: Policy(network="deny"))
    assert cr_mod._tool_run_python(code="1", network_hosts=["a.example.com:443"])["error"] == cr_mod._NETWORK_REFUSED_MSG
    monkeypatch.setattr(cr_mod, "load_policy", lambda: Policy(filesystem="strict"))
    assert cr_mod._tool_run_python(code="1", extra_read_paths=[str(data_dir)])["error"] == cr_mod._FS_REFUSED_MSG
    assert approvals._REQUESTS == {} and calls == []


def test_unavailable_fails_closed(calls, monkeypatch):
    monkeypatch.setattr(cr_mod, "_sandbox_mode", lambda cfg, policy: ("unavailable", "install bubblewrap"))
    result = cr_mod._tool_run_python(code="print(1)")
    assert "install bubblewrap" in result["error"] and calls == []


def test_launcher_unavailable_at_launch_time(calls, monkeypatch):
    def refuse(req):
        raise sandbox.SandboxUnavailable("profile creation failed")

    monkeypatch.setattr(sandbox, "launch_sandboxed", refuse)
    result = cr_mod._tool_run_python(code="print(1)")
    assert "profile creation failed" in result["error"] and result["sandbox"] == "enforced"


@pytest.mark.parametrize("exc", [
    sandbox.SandboxRunError("The sandboxed process failed (OSError)."),
    OSError("ledger write failed: C:\\Users\\someone\\secret-dir"),
])
def test_post_start_and_os_errors_fail_closed_without_rerunning(calls, monkeypatch, exc):
    launches, plain_runs = [], []

    def broken(req):
        launches.append(req)
        raise exc

    real_run = cr_mod.subprocess.run

    def watch_run(cmd, *a, **kw):
        if isinstance(cmd, list) and cmd and str(cmd[-1]).endswith("code.py"):
            plain_runs.append(cmd)
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(sandbox, "launch_sandboxed", broken)
    monkeypatch.setattr(cr_mod.subprocess, "run", watch_run)
    result = cr_mod._tool_run_python(code="print(1)")
    assert result["error"] and result["sandbox"] == "enforced" and result["stdout"] == ""
    assert "secret-dir" not in result["error"]
    assert len(launches) == 1 and plain_runs == []


def test_permission_error_gets_the_hint(calls, monkeypatch):
    monkeypatch.setattr(sandbox, "launch_sandboxed", lambda req: sandbox.SandboxResult(
        1, "", "PermissionError: [Errno 13] Permission denied: 'x'", False))
    result = cr_mod._tool_run_python(code="open('x')")
    assert "extra_read_paths" in result["error"]


def test_launcher_timeout(calls, monkeypatch):
    monkeypatch.setattr(sandbox, "launch_sandboxed", lambda req: sandbox.SandboxResult(-1, "", "", True))
    result = cr_mod._tool_run_python(code="1", timeout=3)
    assert "timed out after 3s" in result["error"] and result["files"] == [] and result["sandbox"] == "enforced"


def test_off_mode_marks_results(tmp_path, monkeypatch):
    import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(cr_mod, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(cr_mod, "_sandbox_mode", lambda cfg, policy: ("off", None))
    result = cr_mod._tool_run_python(code="print('plain')")
    assert result["error"] is None and result["sandbox"] == "off"
    assert result["_sandbox_telemetry"]["level"] == "off"


# --- fix round 1 -----------------------------------------------------------

def _bad_skill_ids():
    import pathlib

    home = pathlib.Path.home()
    return [str(home), str(home / ".ssh"), "..\\..", "../../..", "C:/", "a/b", "a\\b", "a\0b", " ", "C:foo"]


@pytest.mark.parametrize("skill_id", _bad_skill_ids())
def test_hostile_skill_id_is_rejected_before_anything_runs(calls, skill_id):
    result = cr_mod._tool_run_python(code="print(1)", skill_id=skill_id)
    assert "skill_id" in result["error"]
    assert "_sandbox_telemetry" not in result and calls == []


def test_find_skill_dir_ignores_absolute_and_traversal_ids():
    import pathlib

    assert cr_mod._find_skill_dir(str(pathlib.Path.home())) is None
    assert cr_mod._find_skill_dir("..") is None
    assert cr_mod._find_skill_dir("../skills") is None


@pytest.mark.parametrize("target", ["ssh", "root", "home", "gator"])
def test_runtime_path_backstop_refuses_protected_skill_dir(calls, monkeypatch, target):
    import pathlib

    home = pathlib.Path.home()
    path = {"ssh": home / ".ssh", "root": pathlib.Path(home.anchor), "home": home, "gator": home / ".gator"}[target]
    monkeypatch.setattr(cr_mod, "_find_skill_dir", lambda sid: path)
    result = cr_mod._tool_run_python(code="print(1)", skill_id="some-skill")
    assert result["error"] and result["sandbox"] == "enforced" and calls == []


def test_runtime_path_backstop_refuses_protected_npm_root(calls, monkeypatch):
    import pathlib

    class Done:
        stdout = str(pathlib.Path.home())

    monkeypatch.setattr(cr_mod.Path, "is_dir", lambda self: True)
    real_run = cr_mod.subprocess.run
    monkeypatch.setattr(cr_mod.subprocess, "run", lambda cmd, *a, **k: Done() if cmd == "npm root -g" else real_run(cmd, *a, **k))
    result = cr_mod._tool_run_python(code="print(1)")
    assert result["error"] and calls == []


def test_real_builtin_skill_lands_in_runtime_paths(calls):
    from sandbox.paths import is_within

    result = cr_mod._tool_run_python(code="print(1)", skill_id="code_runner")
    assert result["error"] is None and result["_sandbox_telemetry"]["skill_id"] == "code_runner"
    (req,) = calls
    skill = (cr_mod._BUILTIN_SKILLS_DIR / "code_runner").resolve()
    assert any(is_within(skill, p) for p in req.runtime_paths)


def test_default_runtime_paths_hold_interpreter_but_no_user_folders(calls):
    import pathlib
    import sys

    from sandbox.paths import is_within

    cr_mod._tool_run_python(code="print(1)")
    (req,) = calls
    assert any(is_within(pathlib.Path(sys.executable).resolve(), p) for p in req.runtime_paths)
    assert not any(is_within(pathlib.Path.home() / ".ssh", p) or p == pathlib.Path.home() for p in req.runtime_paths)


@pytest.mark.parametrize("pkg", ["requests", "numpy>=1.2", "pkg[extra]==1.0", "a.b-c_d~=2.0,<3"])
def test_plain_requirements_reach_pip(calls, monkeypatch, pkg):
    seen = []
    monkeypatch.setattr(cr_mod, "_install_packages", lambda packages, t: seen.append(packages))
    result = cr_mod._tool_run_python(code="print(1)", packages=[pkg])
    assert result["error"] is None and seen == [[pkg]]


@pytest.mark.parametrize("pkg", ["-e .", "--index-url=https://x/simple", "git+https://x/y", "./local", "pkg @ https://x",
                                 "a b", "pkg;python_version<'3'", "..\\evil", "http://x/y.whl", "-r reqs.txt", "", "pkg\n--index-url=x",
                                 # pip reads these as local archive files, not index names
                                 "x.whl", "pkg-1.0-py3-none-any.WHL", "x.zip", "x.tar.gz", "x.TGZ", "x.tar.bz2"])
def test_unsafe_requirements_are_refused_without_running(calls, monkeypatch, pkg):
    monkeypatch.setattr(cr_mod, "_install_packages", lambda packages, t: pytest.fail("pip must not run"))
    result = cr_mod._tool_run_python(code="print(1)", packages=[pkg])
    assert "package" in result["error"].lower() and calls == []


def test_non_list_or_non_string_packages_are_refused(calls):
    assert cr_mod._tool_run_python(code="1", packages="requests --index-url=x")["error"]
    assert cr_mod._tool_run_python(code="1", packages=[["requests"]])["error"]
    assert calls == []


def test_pip_gets_no_input_and_separator_and_retry_uses_the_validated_list(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(cr_mod, "_missing_packages", lambda packages: ["pkgx"])
    cmds = []

    def fake_run(cmd, *a, **k):
        cmds.append(list(cmd))
        return SimpleNamespace(returncode=1, stdout="", stderr="No module named pip")

    monkeypatch.setattr(cr_mod.subprocess, "run", fake_run)
    err = cr_mod._install_packages(["pkgx", "already-installed"], 5)
    assert err and "pkgx" in err["error"]
    pip_cmds = [c for c in cmds if "pip" in c and "install" in c]
    assert len(pip_cmds) == 2
    for cmd in pip_cmds:
        assert cmd[cmd.index("install") + 1:] == ["--no-input", "--", "pkgx"]


def test_policy_refusals_also_apply_when_opted_out(tmp_path, data_dir, monkeypatch):
    import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(cr_mod, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(cr_mod, "_sandbox_mode", lambda cfg, policy: ("off", None))
    approvals._reset()
    ran = []
    real_run = cr_mod.subprocess.run
    monkeypatch.setattr(cr_mod.subprocess, "run", lambda cmd, *a, **k: (ran.append(cmd) if isinstance(cmd, list) and str(cmd[-1]).endswith("code.py") else None) or real_run(cmd, *a, **k))

    monkeypatch.setattr(cr_mod, "load_policy", lambda: Policy(network="deny"))
    assert cr_mod._tool_run_python(code="print(1)", network_hosts=["a.example.com:443"])["error"] == cr_mod._NETWORK_REFUSED_MSG
    monkeypatch.setattr(cr_mod, "load_policy", lambda: Policy(filesystem="strict"))
    assert cr_mod._tool_run_python(code="print(1)", extra_read_paths=[str(data_dir)])["error"] == cr_mod._FS_REFUSED_MSG
    monkeypatch.setattr(cr_mod, "load_policy", lambda: Policy())
    import pathlib

    refused = cr_mod._tool_run_python(code="print(1)", extra_read_paths=[str(pathlib.Path.home() / ".ssh")])
    assert "can never be granted" in refused["error"]
    assert ran == [] and approvals._REQUESTS == {}

    allowed = cr_mod._tool_run_python(code="print('plain')", extra_read_paths=[str(data_dir)], network_hosts=["a.example.com:443"])
    assert allowed["error"] is None and allowed["sandbox"] == "off" and "approval_required" not in allowed
    assert len(ran) == 1


# --- final review fixes ------------------------------------------------------

@pytest.mark.parametrize("skill_id", [{}, [], 0, False, "skill.", "skill ", "a."])
def test_non_string_or_trailing_dot_skill_id_is_rejected_cleanly(calls, skill_id):
    result = cr_mod._tool_run_python(code="print(1)", skill_id=skill_id)
    assert "skill_id" in result["error"]
    assert "_sandbox_telemetry" not in result and calls == []


def test_every_runtime_path_goes_through_the_backstop(calls, monkeypatch):
    import pathlib

    fake_node = pathlib.Path.home() / "node"  # its folder (the home folder) would become a runtime grant
    monkeypatch.setattr(cr_mod.shutil, "which", lambda name, *a, **k: str(fake_node) if name == "node" else None)
    result = cr_mod._tool_run_python(code="print(1)")
    assert "runtime folder is not allowed" in result["error"] and result["sandbox"] == "enforced" and calls == []
