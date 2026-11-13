import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

import config
import sandbox
from sandbox import approvals, runtime_copy, saved_permissions, task_grants
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
    env_dir = Path(req.env.get("TEMP") or req.env["TMPDIR"])
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


class _FakeForwarded:
    def __init__(self, proc, log_file, on_close=None):
        self.pid = 4242
        self.url = "http://127.0.0.1:3030"
        self.listen_port = 3030
        self.forward_error = None
        self.terminated = False

    def start(self):
        return self

    def wait_ready(self, timeout):
        return True

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True


@pytest.fixture
def bg(env):
    started = []

    def fake_start(request):
        started.append(request)
        return types.SimpleNamespace(pid=4242, terminate=lambda: None)

    relay = env.tmp / "relay" / "relay.py"
    env.mp.setattr(sh, "_bg_sandbox_supported", lambda: True)
    env.mp.setattr(sh, "ForwardedProcess", _FakeForwarded)
    env.mp.setattr(sh, "_bg_log_path", lambda: env.tmp / "bg.log")
    env.mp.setattr(sandbox, "start_sandboxed", fake_start)
    env.mp.setattr(sandbox, "container_readable", lambda p: True)
    env.mp.setattr(runtime_copy, "readable_copies", lambda *a, **k: [])
    env.mp.setattr(runtime_copy, "install_relay", lambda root=None: relay)
    yield types.SimpleNamespace(started=started, relay=relay)
    sh._BG_REGISTRY.pop(4242, None)


def test_background_refused_where_the_platform_cannot_stream(env):
    env.mp.setattr(sh, "_bg_sandbox_supported", lambda: False)
    out = _run(background=True)
    assert sh._BACKGROUND_REFUSED_MSG in out["error"] and env.fake.requests == []


def test_background_asks_first_and_starts_nothing_until_approved(env, bg):
    proj = _project(env)
    first = _run("npm run dev", background=True, cwd=str(proj))
    assert first["approval_required"] is True
    assert first["_sandbox_approval"]["background"] is True
    assert bg.started == []
    approvals.decide(first["request_id"], "tab", True)
    out = _run("npm run dev", background=True, cwd=str(proj))
    assert out["url"] == "http://127.0.0.1:3030" and out["pid"] == 4242 and out["background"] is True
    assert out["_dev_server"] == {"pid": 4242, "url": "http://127.0.0.1:3030", "command": "npm run dev"}
    assert out["sandbox"] == "enforced" and "_sandbox_telemetry" in out
    assert sh._BG_REGISTRY[4242]["sandboxed"] is True
    request = bg.started[0]
    assert json.loads(request.env["AIGATOR_RELAY_COMMAND"])[-1] == "npm run dev"
    assert request.cwd == proj and request.network is False and request.timeout == 0
    assert bg.relay.parent in request.runtime_paths
    assert env.fake.requests == []


def test_background_unattended_is_refused(env, bg):
    out = _run("npm run dev", background=True, _context_id="")
    assert "cannot run unattended" in out["error"] and bg.started == []


def test_background_cap_is_enforced(env, bg):
    sh._BG_REGISTRY[7001] = {"popen": _FakeForwarded(None, ""), "command": "x", "started_at": 0, "log_file": ""}
    try:
        env.mp.setattr(sh, "_MAX_BG_PROCS", 1)
        proj = _project(env)
        first = _run("npm run dev", background=True, cwd=str(proj))
        approvals.decide(first["request_id"], "tab", True)
        out = _run("npm run dev", background=True, cwd=str(proj))
        assert out["error"] == "BACKGROUND_PROCESS_CAP_REACHED" and bg.started == []
    finally:
        sh._BG_REGISTRY.pop(7001, None)


def test_background_runtime_copy_failure_runs_nothing(env, bg):
    def boom(*a, **k):
        raise runtime_copy.RuntimeCopyError("Node is too large to copy.")

    env.mp.setattr(runtime_copy, "readable_copies", boom)
    proj = _project(env)
    first = _run("npm run dev", background=True, cwd=str(proj))
    approvals.decide(first["request_id"], "tab", True)
    out = _run("npm run dev", background=True, cwd=str(proj))
    assert "Node is too large to copy." in out["error"] and bg.started == []


def test_background_without_a_url_yet_says_so(env, bg):
    env.mp.setattr(_FakeForwarded, "wait_ready", lambda self, timeout: False)
    proj = _project(env)
    first = _run("npm run dev", background=True, cwd=str(proj))
    approvals.decide(first["request_id"], "tab", True)
    out = _run("npm run dev", background=True, cwd=str(proj))
    assert "url" not in out and "no URL yet" in out["message"] and out["pid"] == 4242
    assert out["_dev_server"]["url"] is None


def test_background_whose_port_could_not_be_forwarded_says_so(env, bg):
    env.mp.setattr(_FakeForwarded, "wait_ready", lambda self, timeout: False)
    env.mp.setattr(_FakeForwarded, "start", lambda self: setattr(self, "forward_error", "no port") or self)
    proj = _project(env)
    first = _run("npm run dev", background=True, cwd=str(proj))
    approvals.decide(first["request_id"], "tab", True)
    out = _run("npm run dev", background=True, cwd=str(proj))
    assert "could not be forwarded" in out["message"] and "check_shell_process" not in out["message"]


def test_background_that_exits_before_printing_an_address_is_an_error(env, bg):
    env.mp.setattr(_FakeForwarded, "wait_ready", lambda self, timeout: False)
    env.mp.setattr(_FakeForwarded, "poll", lambda self: 1)
    (env.tmp / "bg.log").write_text("boom: port in use", encoding="utf-8")
    proj = _project(env)
    first = _run("npm run dev", background=True, cwd=str(proj))
    approvals.decide(first["request_id"], "tab", True)
    out = _run("npm run dev", background=True, cwd=str(proj))
    assert "exited with code 1" in out["error"] and "port in use" in out["error"]


def test_stop_refuses_a_pid_that_was_not_started_by_run_shell():
    out = sh._tool_stop_shell_process(999999)
    assert out["stopped"] is False and "was not started by run_shell" in out["message"]


def test_stop_terminates_a_sandboxed_entry():
    fake = _FakeForwarded(None, "")
    sh._BG_REGISTRY[4243] = {"popen": fake, "command": "npm run dev", "sandboxed": True}
    try:
        out = sh._tool_stop_shell_process(4243)
        assert out["stopped"] is True and fake.terminated is True
    finally:
        sh._BG_REGISTRY.pop(4243, None)


def _sleeper():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])


def _record(pidfile, pid, command):
    pidfile.write_text(json.dumps({str(pid): {"command": command, "log_file": "", "started_at": 0}}))


def test_orphan_cleanup_leaves_a_pid_alone_when_the_command_does_not_match(env):
    proc = _sleeper()
    try:
        pidfile = env.tmp / "bg-pids.json"
        env.mp.setattr(sh, "_bg_pid_file", lambda: pidfile)
        _record(pidfile, proc.pid, "npm run dev")
        sh.cleanup_orphan_bg_procs()
        with pytest.raises(subprocess.TimeoutExpired):
            proc.wait(timeout=2)
    finally:
        proc.kill()
        proc.wait()


def test_orphan_cleanup_kills_a_pid_whose_command_matches(env):
    proc = _sleeper()
    try:
        pidfile = env.tmp / "bg-pids.json"
        env.mp.setattr(sh, "_bg_pid_file", lambda: pidfile)
        _record(pidfile, proc.pid, '-c "import time; time.sleep(30)"')
        sh.cleanup_orphan_bg_procs()
        proc.wait(timeout=10)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


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


def test_run_shell_path_offers_enabled_skill_shims_only(env):
    import shared
    from marketplace import state

    shared.SKILL_BIN_PATHS.update({"on-skill": "/skills/on-skill/bin", "off-skill": "/skills/off-skill/bin"})
    env.mp.setattr(state, "disabled_ids", lambda: {"off-skill"})
    try:
        _run()
    finally:
        shared.SKILL_BIN_PATHS.pop("on-skill", None)
        shared.SKILL_BIN_PATHS.pop("off-skill", None)
    path = env.fake.requests[0].env["PATH"].split(os.pathsep)
    assert path[0] == "/skills/on-skill/bin"
    assert "/skills/off-skill/bin" not in path


def test_background_gate_asks_even_with_no_paths_and_approval_is_single_use(env):
    from sandbox import approvals as sandbox_approvals

    policy = sh.load_policy()
    saved_before = saved_permissions.list_entries()
    out = sh._shell_gate(cr, "npm run dev", [], [], [], "tab", policy, background=True)
    assert out["approval_required"] is True
    assert out["message"] == sh._BG_APPROVAL_MSG and "background=true" in out["message"]
    card = out["_sandbox_approval"]
    assert card["background"] is True and card["saveable"] is False
    sandbox_approvals.decide(out["request_id"], "tab", True, scope="always")
    assert sh._shell_gate(cr, "npm run dev", [], [], [], "tab", policy, background=True) == "approved"
    again = sh._shell_gate(cr, "npm run dev", [], [], [], "tab", policy, background=True)
    assert isinstance(again, dict) and again["approval_required"] is True
    assert task_grants._GRANTS == [] and saved_permissions.list_entries() == saved_before


def test_foreground_gate_is_unchanged_when_nothing_is_requested(env):
    assert sh._shell_gate(cr, "echo hi", [], [], [], "tab", sh.load_policy()) is None
