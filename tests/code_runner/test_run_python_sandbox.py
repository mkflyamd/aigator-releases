import pytest

import sandbox
import skills.code_runner.tools as cr_mod
from sandbox import approvals
from sandbox.policy import Policy

FAKE = "aigator-fake-api-key"


@pytest.fixture
def calls(tmp_path, monkeypatch):
    import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(cr_mod, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(cr_mod, "_sandbox_mode", lambda cfg, policy: ("enforced", None))
    approvals._reset()
    seen = []

    def fake_launch(req):
        seen.append(req)
        (req.cwd / "made.txt").write_text("x")
        return sandbox.SandboxResult(returncode=0, stdout="fake-ok\n", stderr="", timed_out=False)

    monkeypatch.setattr(sandbox, "launch_sandboxed", fake_launch)
    yield seen
    approvals._reset()


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
