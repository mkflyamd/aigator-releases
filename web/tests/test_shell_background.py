"""Tests for run_shell's background=True mode + check_shell_process/stop_shell_process.

Background reason: run_shell used subprocess.run(..., timeout=N), which BLOCKS
until the command exits. Launching a long-running process (a dev server, an
inference server, `docker run` in the foreground) froze the whole turn until
the timeout fired. background=True switches to a non-blocking Popen path that
returns immediately with a pid + log file; check_shell_process/stop_shell_process
poll and tear it down, mirroring Claude Code's own run_in_background design.

All "server" processes here are a portable `python -c "..."` invocation so
these tests pass on Windows AND macOS/Linux without relying on any specific
shell's builtins.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skills.shell_runner.tools import (
    _tool_run_shell,
    _tool_check_shell_process,
    _tool_stop_shell_process,
)

# Single-quoted Python source embedded in a double-quoted shell command —
# verified to survive bash/WSL, Git Bash, PowerShell, and cmd quoting alike.
_LONG_SLEEP = "python -c \"import time; print('up', flush=True); time.sleep(20)\""
_SHORT_SLEEP = "python -c \"import time; print('up', flush=True); time.sleep(2)\""


def _wait_until(predicate, timeout=10.0, interval=0.2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_background_returns_immediately_with_pid_and_log_file():
    """The whole point: background=True must NOT block for the process's
    lifetime (here 20s), and definitely not for the `timeout` param."""
    start = time.monotonic()
    result = _tool_run_shell(_LONG_SLEEP, background=True, timeout=60)
    elapsed = time.monotonic() - start

    try:
        assert "error" not in result, result
        assert result["background"] is True
        assert isinstance(result["pid"], int) and result["pid"] > 0
        assert result["log_file"] and os.path.exists(result["log_file"])
        # Returned in well under the 20s sleep and the 60s timeout.
        assert elapsed < 5.0, f"background=True blocked for {elapsed}s"
    finally:
        _tool_stop_shell_process(result["pid"])


def test_check_shell_process_reports_running_then_exit():
    result = _tool_run_shell(_SHORT_SLEEP, background=True, timeout=60)
    pid = result["pid"]
    try:
        # While alive: running=True and the log has picked up stdout.
        ok = _wait_until(
            lambda: "up" in _tool_check_shell_process(pid)["log_tail"], timeout=5
        )
        assert ok, "expected 'up' in log_tail while process is alive"
        status = _tool_check_shell_process(pid)
        assert status["running"] is True
        assert status["exit_code"] is None
        assert status["pid"] == pid

        # After it exits on its own (the sleep(2) finishes).
        ok = _wait_until(
            lambda: _tool_check_shell_process(pid)["running"] is False, timeout=10
        )
        assert ok, "process never reported running=False after it should have exited"
        status = _tool_check_shell_process(pid)
        assert status["running"] is False
        assert status["exit_code"] is not None
    finally:
        _tool_stop_shell_process(pid)


def test_stop_shell_process_kills_a_running_process():
    result = _tool_run_shell(_LONG_SLEEP, background=True, timeout=60)
    pid = result["pid"]

    ok = _wait_until(
        lambda: _tool_check_shell_process(pid)["running"] is True, timeout=5
    )
    assert ok, "process never came up"

    stop_result = _tool_stop_shell_process(pid)
    assert stop_result["stopped"] is True
    assert stop_result["pid"] == pid

    ok = _wait_until(
        lambda: _tool_check_shell_process(pid)["running"] is False, timeout=5
    )
    assert ok, "process still reported running after stop_shell_process"


def test_background_still_blocks_delete_commands():
    result = _tool_run_shell("rm -rf x", background=True)
    assert "error" in result
    assert "Delete operations are blocked" in result["error"]
    # Nothing should have been spawned — no pid/background markers on the
    # blocked-command error shape.
    assert result.get("background") is not True
    assert not result.get("pid")


def test_foreground_run_shell_unchanged():
    """background defaults to False — synchronous behavior must be untouched."""
    result = _tool_run_shell('python -c "print(1+1)"', timeout=15)
    assert "error" not in result
    assert result["exit_code"] == 0
    assert "2" in result["stdout"]
    assert "background" not in result
