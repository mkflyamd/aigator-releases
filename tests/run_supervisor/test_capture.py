import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import pytest

import fakes
from skills.shell_runner import tools as shell_tools


def _run(tmp_path, name, timeout, **kw):
    return shell_tools._run_captured(_argv(tmp_path, name), str(tmp_path), None, timeout, **kw)


def _argv(tmp_path, name):
    script = tmp_path / f"{name}.py"
    script.write_text(fakes._PROGRAMS[name].replace("PID_FILE", repr(str(tmp_path / f"{name}.pid"))))
    return [sys.executable, str(script)]


def test_output_is_captured_in_full_when_small(tmp_path):
    code, out, err = _run(tmp_path, "quick", 30)
    assert code == 0
    assert out.strip() == "hello-run"
    assert err == ""


def test_a_flood_of_output_is_capped_with_a_marker_and_never_held_whole(tmp_path, monkeypatch):
    monkeypatch.setattr(shell_tools, "_CAPTURE_CAP_CHARS", 100_000)
    code, out, _ = _run(tmp_path, "flood", 60)
    assert code == 0
    assert len(out) < 100_000 + 200
    assert out.startswith("[first ")
    assert "characters omitted]" in out.split("\n", 1)[0]
    assert out.endswith("x" * 1000)


def test_a_timeout_kills_the_tree_and_raises(tmp_path):
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run(tmp_path, "slow", 1)
    assert time.monotonic() - started < 20


def test_a_timeout_keeps_what_the_command_printed_before_it_was_killed(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        script = tmp_path / "talker.py"
        script.write_text("import time\nprint('Viewer at http://127.0.0.1:4173/', flush=True)\ntime.sleep(60)")
        shell_tools._run_captured([sys.executable, str(script)], str(tmp_path), None, 2)
    assert "http://127.0.0.1:4173/" in caught.value.output


def test_the_unsandboxed_result_for_a_timeout_carries_output_and_the_timed_out_flag(tmp_path):
    fakes._PROGRAMS["talker"] = "import time\nprint('ready', flush=True)\ntime.sleep(60)"
    result = shell_tools._run_unsandboxed(
        fakes.command(tmp_path, "talker"), fakes.SHELL, str(tmp_path), 2, False, as_typed=True)
    assert result["timed_out"] is True
    assert "ready" in result["stdout"]


def test_the_on_start_hook_gets_the_process(tmp_path):
    seen = []
    _run(tmp_path, "quick", 30, on_start=seen.append)
    assert len(seen) == 1 and hasattr(seen[0], "pid")


def test_a_child_that_outlives_its_parent_and_holds_the_pipes_ends_in_a_timeout_with_the_child_dead(tmp_path):
    argv = _argv(tmp_path, "pipe_holder")
    with pytest.raises(subprocess.TimeoutExpired):
        shell_tools._run_captured(argv, str(tmp_path), None, 3)
    pid = fakes.child_pid(tmp_path, "pipe_holder")
    assert fakes.wait_for(lambda: not fakes.alive(pid)), "the detached child survived the timeout"
