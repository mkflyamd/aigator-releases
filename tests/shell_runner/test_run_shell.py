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


def test_reports_output_file_created_in_cwd(tmp_path):
    from skills.shell_runner.tools import _tool_run_shell
    # Write a .pptx into the command's cwd; it must be surfaced in output_files.
    result = _tool_run_shell(
        command='python -c "open(\'deck.pptx\',\'wb\').write(b\'PK\')"',
        cwd=str(tmp_path),
    )
    assert result["exit_code"] == 0
    paths = [f["path"] for f in result.get("output_files", [])]
    assert any(pth.endswith("deck.pptx") for pth in paths)


def test_no_output_files_key_when_nothing_created(tmp_path):
    from skills.shell_runner.tools import _tool_run_shell
    result = _tool_run_shell(command="echo hello", cwd=str(tmp_path))
    assert result.get("error") is None
    assert "output_files" not in result


def test_default_cwd_is_app_work_dir():
    # Omitting cwd must run in the app-owned scratch dir (~/.gator/work), not the
    # user's home/repo — so build artifacts don't splatter.
    import os
    from skills.shell_runner.tools import _tool_run_shell
    from config import WORK_DIR
    result = _tool_run_shell(command='python -c "import os;print(os.getcwd())"')
    out = (result["stdout"] or "").strip()
    assert os.path.normcase(out) == os.path.normcase(str(WORK_DIR))
    assert WORK_DIR.is_dir()  # created on demand


def test_explicit_cwd_is_honored(tmp_path):
    # An explicit cwd (operating on a real project) must never be overridden.
    import os
    from skills.shell_runner.tools import _tool_run_shell
    result = _tool_run_shell(
        command='python -c "import os;print(os.getcwd())"', cwd=str(tmp_path))
    out = (result["stdout"] or "").strip()
    assert os.path.normcase(out) == os.path.normcase(str(tmp_path))


def test_timeout_returns_error():
    from skills.shell_runner.tools import _tool_run_shell
    result = _tool_run_shell(command="ping -n 30 127.0.0.1", timeout=2)
    assert result.get("error") is not None
    assert "timed out" in result["error"].lower()


def test_auto_detection_finds_shell():
    from skills.shell_runner.tools import _DETECTED_SHELL
    assert _DETECTED_SHELL is not None
    assert _DETECTED_SHELL in ("bash", "powershell", "cmd")


def test_substring_false_positives_not_blocked():
    """Issue #57: keywords must not match inside longer words or string-literal
    argument values. Words like 'perms', 'form', 'term', 'warm', 'delegated',
    'format' (as an argument) and heredoc bodies merely mentioning rm/del must
    NOT be blocked."""
    from skills.shell_runner.tools import _has_delete_command
    for cmd in [
        'gh issue create --body "delegated perms term format warm"',
        'echo "rm is dangerous"',
        'git commit -m "reformat the code"',
        'grep perms file.txt',
        'echo "this terminal is warm"',
        'gh pr comment -b "needs reformatting"',
        "cat <<EOF\nrm -rf this is just text\nEOF",
    ]:
        assert not _has_delete_command(cmd), f"Should NOT be blocked: {cmd!r}"


def test_real_deletes_still_blocked():
    """Issue #57: genuine delete invocations must still be caught."""
    from skills.shell_runner.tools import _has_delete_command
    for cmd in [
        "rm -rf /tmp/x",
        "del foo.txt",
        "sudo rm file",
        "/usr/bin/rm x",
        "rmdir d",
        "echo hi && rm bar",
    ]:
        assert _has_delete_command(cmd), f"Should be blocked: {cmd!r}"


def test_blocked_error_names_matched_token_and_position():
    """Issue #57 item 3: the blocked error must name which token matched and
    where, not just a generic message."""
    from skills.shell_runner.tools import _tool_run_shell, _find_delete_command
    result = _tool_run_shell(command="echo hi && rm bar")
    assert "error" in result
    assert "blocked" in result["error"].lower()
    assert "rm" in result["error"]
    token, pos = _find_delete_command("echo hi && rm bar")
    assert token == "rm"
    assert str(pos) in result["error"]


def test_tool_contract():
    import skills.shell_runner.tools as mod
    from skills._skill_utils import validate_tool_contract
    assert validate_tool_contract(mod, "shell_runner") is True
