import types
from pathlib import Path

import pytest

import config
import sandbox
from sandbox import approvals, saved_permissions, task_grants
from sandbox.policy import Policy
from skills.code_runner import tools as cr
from skills.shell_runner import tools as sh


class FakeLauncher:
    def __init__(self):
        self.requests = []
        self.result = sandbox.SandboxResult(0, "out\n", "", False)
        self.raises = None

    def __call__(self, request):
        self.requests.append(request)
        if self.raises:
            raise self.raises
        return self.result


@pytest.fixture
def env(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setattr(config, "WORK_DIR", work)
    monkeypatch.setattr(cr, "_sandbox_mode", lambda cfg, policy: ("enforced", None))
    monkeypatch.setattr(sh, "_npm_global_root", lambda: None)
    monkeypatch.setattr(sh, "load_policy", lambda: Policy())
    fake = FakeLauncher()
    monkeypatch.setattr(sandbox, "launch_sandboxed", fake)
    approvals._reset()
    task_grants._reset()
    yield types.SimpleNamespace(work=work.resolve(), fake=fake, tmp=tmp_path, mp=monkeypatch)
    approvals._reset()
    task_grants._reset()


def _project(env):
    p = env.tmp / "proj"
    p.mkdir(exist_ok=True)
    return p.resolve()


def _run(command="echo hi", **kw):
    kw.setdefault("_context_id", "tab")
    return sh._tool_run_shell(command, **kw)


def test_scratch_cwd_runs_with_no_card(env):
    r = _run()
    assert r["exit_code"] == 0 and r["stdout"] == "out\n" and "approval_required" not in r
    req = env.fake.requests[0]
    assert req.cwd == env.work and req.network is False and req.read_paths == []
    assert req.argv[-1] == "echo hi"
    assert r["sandbox"] == "enforced" and "_sandbox_telemetry" in r


def test_project_cwd_needs_a_card_then_task_grant_covers(env):
    proj = _project(env)
    r = _run(cwd=str(proj))
    assert r["approval_required"] is True and env.fake.requests == []
    card = r["_sandbox_approval"]
    assert card["tool"] == "run_shell" and card["write_paths"] == [str(proj)]
    assert card["command"] == "echo hi" and card["saveable"] is True and card["context_id"] == "tab"
    approvals.decide(card["request_id"], "tab", True, scope="task")
    task_grants.add("tab", card["read_paths"], card["write_paths"], card["network_hosts"])
    first = _run(cwd=str(proj))
    assert "approval_required" not in first and "task_approved" in str(first["_sandbox_telemetry"])
    second = _run("echo again", cwd=str(proj))
    assert "approval_required" not in second
    req = env.fake.requests[-1]
    assert req.cwd == proj and proj not in req.write_paths
    env_dir = Path(req.env["TEMP"])
    assert env_dir.parent == env.work and env_dir.name.startswith(".run-") and env_dir in req.write_paths
    assert not env_dir.exists()


def test_task_grant_does_not_cross_tabs(env):
    proj = _project(env)
    task_grants.add("tab", [], [str(proj)], [])
    assert "approval_required" in _run(cwd=str(proj), _context_id="other")


def test_saved_permission_covers_unless_policy_denies(env):
    proj = _project(env)
    saved_permissions.add([], [str(proj)], False, [])
    r = _run(cwd=str(proj))
    assert "approval_required" not in r and "saved" in str(r["_sandbox_telemetry"])
    env.mp.setattr(sh, "load_policy", lambda: Policy(saved_permissions="deny"))
    assert _run(cwd=str(proj))["approval_required"] is True


def test_saveable_follows_command_programs(env):
    git = _run("git pull", network_hosts=["github.com:443"])
    card = git["_sandbox_approval"]
    assert card["saveable"] is True and card["programs"] == ["git"] and card["network_hosts"] == ["github.com:443"]
    py = _run("python x.py", network_hosts=["github.com:443"])
    assert py["_sandbox_approval"]["saveable"] is False


def test_network_approval_runs_with_network(env):
    r = _run("git pull", network_hosts=["github.com:443"])
    approvals.decide(r["request_id"], "tab", True)
    assert "approval_required" not in _run("git pull", network_hosts=["github.com:443"])
    assert env.fake.requests[0].network is True


def test_denied_request_never_runs(env):
    r = _run("git pull", network_hosts=["github.com:443"])
    approvals.decide(r["request_id"], "tab", False)
    out = _run("git pull", network_hosts=["github.com:443"])
    assert out["error"] == cr._DENIED_MSG and env.fake.requests == []


def test_unsafe_or_missing_cwd_is_refused(env):
    assert "error" in _run(cwd=str(Path.home()))
    assert "error" in _run(cwd=str(env.tmp / "missing"))
    assert env.fake.requests == []


def test_strict_filesystem_policy_refuses_project_cwd(env):
    env.mp.setattr(sh, "load_policy", lambda: Policy(filesystem="strict"))
    assert _run(cwd=str(_project(env)))["error"] == cr._FS_REFUSED_MSG


def test_policy_disabled_and_network_deny(env):
    env.mp.setattr(sh, "load_policy", lambda: Policy(code_runner="disabled"))
    assert _run()["error"] == cr._DISABLED_MSG
    env.mp.setattr(sh, "load_policy", lambda: Policy(network="deny"))
    assert "error" in _run(network_hosts=["a.example:443"]) and env.fake.requests == []


def test_background_refused_when_enforced(env):
    env.mp.setattr(sh, "_spawn_background", lambda *a, **k: pytest.fail("must not spawn"))
    assert "error" in _run(background=True) and env.fake.requests == []


def test_delete_still_blocked_first(env):
    assert "Delete operations are blocked" in _run("rm -rf x")["error"] and env.fake.requests == []


def test_unavailable_never_runs(env):
    env.mp.setattr(cr, "_sandbox_mode", lambda cfg, policy: ("unavailable", "no sandbox here"))
    assert "error" in _run() and env.fake.requests == []


def test_launcher_failures_never_fall_back(env):
    env.mp.setattr(sh.subprocess, "run", lambda *a, **k: pytest.fail("unsandboxed run"))
    env.fake.raises = sandbox.SandboxRunError("boom")
    assert _run()["error"] == cr._RUN_ERROR_MSG
    env.fake.raises = sandbox.SandboxUnavailable("gone")
    assert "error" in _run()
    env.fake.raises = OSError("ledger")
    assert "nothing was run" in _run()["error"]


def test_result_shaping_and_hint(env):
    env.fake.result = sandbox.SandboxResult(1, "", "cat: x: Permission denied\n", False)
    r = _run("cat x")
    assert r["exit_code"] == 1 and r["error"].startswith("Command exited with code 1:")
    assert "[sandbox]" in r["stderr"]
    env.fake.result = sandbox.SandboxResult(-1, "", "", True)
    assert _run("sleep 9", timeout=1)["error"] == "Command timed out after 1s."


def test_git_cwd_error_gets_hint(env):
    env.fake.result = sandbox.SandboxResult(128, "", "fatal: Unable to read current working directory: x\n", False)
    assert "[sandbox]" in _run("git status")["stderr"]


def test_sandbox_shell_choice():
    assert sh._sandbox_shell("", is_windows=True)[1] == "cmd"
    assert sh._sandbox_shell("cmd", is_windows=True)[0][-1] == "/c"
    for bad in ("bash", "powershell"):
        assert isinstance(sh._sandbox_shell(bad, is_windows=True), str)
    for bad in ("powershell", "cmd"):
        assert isinstance(sh._sandbox_shell(bad, is_windows=False), str)
    argv, name = sh._sandbox_shell("", is_windows=False)
    assert name == sh._DETECTED_SHELL and argv == sh._DETECTED_ARGV


@pytest.mark.parametrize("scope", ["once", "always"])
def test_approval_is_bound_to_the_command(env, scope):
    git = _run("git pull", network_hosts=["github.com:443"])
    approvals.decide(git["request_id"], "tab", True, scope=scope)
    py = _run("python x.py", network_hosts=["github.com:443"])
    assert py["approval_required"] is True and py["request_id"] != git["request_id"]
    assert env.fake.requests == []
    assert "approval_required" not in _run("git pull", network_hosts=["github.com:443"])


def test_same_command_consumes_its_once_approval(env):
    r = _run("git pull", network_hosts=["github.com:443"])
    approvals.decide(r["request_id"], "tab", True)
    assert "approval_required" not in _run("git pull", network_hosts=["github.com:443"])
    assert _run("git pull", network_hosts=["github.com:443"])["approval_required"] is True


def test_run_python_approval_is_not_consumed_by_run_shell(env):
    req = approvals.create("tab", [], [], ["github.com:443"])
    approvals.decide(req.id, "tab", True)
    assert _run("git pull", network_hosts=["github.com:443"])["approval_required"] is True
    assert approvals.lookup("tab", [], [], ["github.com:443"], tool="run_python")[0] == "approved"


def test_pending_card_reused_per_command_not_shadowed(env):
    git = _run("git pull", network_hosts=["github.com:443"])
    py = _run("python x.py", network_hosts=["github.com:443"])
    assert _run("git pull", network_hosts=["github.com:443"])["request_id"] == git["request_id"]
    assert _run("python x.py", network_hosts=["github.com:443"])["request_id"] == py["request_id"]
