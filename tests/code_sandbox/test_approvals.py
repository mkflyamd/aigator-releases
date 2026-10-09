import pytest

from sandbox import approvals


@pytest.fixture(autouse=True)
def _fresh():
    approvals._reset()
    yield
    approvals._reset()


R, W, H = ["C:/data"], ["C:/out"], ["api.example.com:443"]


def test_unknown_set_is_none():
    assert approvals.lookup("tab-1", R, W, H) == ("none", None)


def test_pending_then_approved_is_consumed_once():
    req = approvals.create("tab-1", R, W, H, now=100.0)
    assert approvals.lookup("tab-1", R, W, H, now=101.0) == ("pending", req)
    approvals.decide(req.id, "tab-1", True, now=102.0)
    status, got = approvals.lookup("tab-1", R, W, H, now=103.0)
    assert (status, got.id) == ("approved", req.id)
    assert approvals.lookup("tab-1", R, W, H, now=104.0) == ("none", None)


def test_exact_set_match_only():
    req = approvals.create("tab-1", R, [], [], now=100.0)
    approvals.decide(req.id, "tab-1", True, now=101.0)
    assert approvals.lookup("tab-1", R + ["C:/other"], [], [], now=102.0) == ("none", None)
    assert approvals.lookup("tab-1", [], R, [], now=102.0) == ("none", None)
    assert approvals.lookup("tab-1", ["c:/DATA"], [], [], now=102.0)[0] in ("approved", "none")


def test_other_tab_does_not_match():
    req = approvals.create("tab-1", R, W, H, now=100.0)
    approvals.decide(req.id, "tab-1", True, now=101.0)
    assert approvals.lookup("tab-2", R, W, H, now=102.0) == ("none", None)


def test_denied_reported_once():
    req = approvals.create("tab-1", R, W, H, now=100.0)
    approvals.decide(req.id, "tab-1", False, now=101.0)
    assert approvals.lookup("tab-1", R, W, H, now=102.0)[0] == "denied"
    assert approvals.lookup("tab-1", R, W, H, now=103.0) == ("none", None)


def test_expiry_after_ten_minutes():
    req = approvals.create("tab-1", R, W, H, now=100.0)
    approvals.decide(req.id, "tab-1", True, now=200.0)
    assert approvals.lookup("tab-1", R, W, H, now=100.0 + 601)[0] == "expired"


def test_decide_errors():
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide("nope", "tab-1", True)
    assert e.value.status_code == 404
    req = approvals.create("tab-1", R, W, H, now=100.0)
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide(req.id, "tab-2", True, now=101.0)
    assert e.value.status_code == 409
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide(req.id, "tab-1", True, now=100.0 + 601)
    assert e.value.status_code == 410
    req2 = approvals.create("tab-1", R, [], [], now=100.0)
    approvals.decide(req2.id, "tab-1", True, now=101.0)
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide(req2.id, "tab-1", False, now=102.0)
    assert e.value.status_code == 409


def test_run_python_request_defaults_and_scope_is_once():
    req = approvals.create("t", R, W, H, now=100.0)
    assert (req.tool, req.command, req.programs, req.saveable, req.scope) == ("run_python", "", None, False, "once")
    got = approvals.decide(req.id, "t", True, now=101.0, scope="always")
    assert got.scope == "once"


def test_run_python_can_be_allowed_for_the_task():
    req = approvals.create("t", R, W, H, now=100.0)
    assert approvals.decide(req.id, "t", True, now=101.0, scope="task").scope == "task"
    assert approvals.lookup("t", R, W, H, now=102.0)[1].scope == "task"


def test_shell_scope_task_and_always():
    req = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="git pull",
                           programs=("git",), saveable=True)
    got = approvals.decide(req.id, "t", True, now=101.0, scope="always")
    assert got.scope == "always"
    assert approvals.lookup("t", R, [], [], now=102.0, tool="run_shell", command="git pull")[1].scope == "always"


def test_shell_always_falls_back_to_task_when_not_saveable_or_not_allowed():
    a = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="python x.py", saveable=False)
    assert approvals.decide(a.id, "t", True, now=101.0, scope="always").scope == "task"
    approvals._reset()
    b = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="git pull",
                         programs=("git",), saveable=True)
    assert approvals.decide(b.id, "t", True, now=101.0, scope="always", allow_saved=False).scope == "task"


def test_shell_unknown_scope_is_once_and_deny_keeps_once():
    a = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="ls")
    assert approvals.decide(a.id, "t", True, now=101.0, scope="forever").scope == "once"
    approvals._reset()
    b = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="ls")
    got = approvals.decide(b.id, "t", False, now=101.0, scope="task")
    assert (got.status, got.scope) == ("denied", "once")


def test_lookup_is_bound_to_tool_and_shell_command():
    shell = approvals.create("t", R, [], [], now=100.0, tool="run_shell", command="git pull")
    approvals.decide(shell.id, "t", True, now=101.0)
    assert approvals.lookup("t", R, [], [], now=102.0) == ("none", None)
    assert approvals.lookup("t", R, [], [], now=102.0, tool="run_shell", command="python x.py") == ("none", None)
    py = approvals.create("t", R, [], [], now=100.0)
    approvals.decide(py.id, "t", True, now=101.0)
    assert approvals.lookup("t", R, [], [], now=102.0, tool="run_shell", command="git pull") == ("approved", shell)
    assert approvals.lookup("t", R, [], [], now=102.0, tool="run_shell", command="git pull") == ("none", None)
    assert approvals.lookup("t", R, [], [], now=102.0) == ("approved", py)
