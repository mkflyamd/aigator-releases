import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))

import pytest


def test_basic_command_returns_stdout():
    from skills.shell_runner.tools import _tool_run_shell
    result = _tool_run_shell(command="echo hello")
    assert result.get("error") is None
    assert "hello" in result["stdout"]
    assert result["shell_used"] is not None
    assert isinstance(result["runtime_ms"], int)


def test_nonzero_exit_code_sets_exit_code():
    from skills.shell_runner.tools import _tool_run_shell
    result = _tool_run_shell(command="exit 1")
    # Either exit_code is non-zero OR error is set — both are valid
    assert result["exit_code"] != 0 or result.get("error") is not None


def test_delete_command_blocked_rm():
    from skills.shell_runner.tools import _tool_run_shell
    result = _tool_run_shell(command="rm -rf /tmp/test")
    assert "error" in result
    assert "blocked" in result["error"].lower()


def test_delete_command_blocked_del():
    from skills.shell_runner.tools import _tool_run_shell
    result = _tool_run_shell(command="del somefile.txt")
    assert "error" in result
    assert "blocked" in result["error"].lower()


def test_timeout_returns_error():
    from skills.shell_runner.tools import _tool_run_shell
    result = _tool_run_shell(command="ping -n 30 127.0.0.1", timeout=2)
    assert result.get("error") is not None
    assert "timed out" in result["error"].lower()


def test_auto_detection_finds_shell():
    from skills.shell_runner.tools import _DETECTED_SHELL
    assert _DETECTED_SHELL is not None
    assert _DETECTED_SHELL in ("bash", "powershell", "cmd")


def test_tool_contract():
    import skills.shell_runner.tools as mod
    from skills._skill_utils import validate_tool_contract
    assert validate_tool_contract(mod, "shell_runner") is True
