import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))

import pytest
from unittest.mock import patch
from pathlib import Path


@pytest.fixture(autouse=True)
def patch_outputs(tmp_path, monkeypatch):
    import config as cfg_mod
    import skills.code_runner.tools as cr_mod
    monkeypatch.setattr(cfg_mod, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(cr_mod, "OUTPUTS_DIR", tmp_path)


def test_basic_execution_returns_stdout():
    from skills.code_runner.tools import _tool_run_python
    result = _tool_run_python(code="print('hello world')")
    assert result.get("error") is None
    assert "hello world" in result["stdout"]


def test_output_file_returned(tmp_path):
    from skills.code_runner.tools import _tool_run_python
    result = _tool_run_python(code="import os\nwith open(os.path.join(OUTPUT_DIR, 'out.txt'), 'w') as f: f.write('data')")
    assert result.get("error") is None
    assert len(result["files"]) == 1
    assert result["files"][0]["name"] == "out.txt"
    assert result["files"][0]["download_url"].endswith("/out.txt")


def test_timeout_returns_error():
    from skills.code_runner.tools import _tool_run_python
    result = _tool_run_python(code="import time; time.sleep(60)", timeout=2)
    assert result.get("error") is not None
    assert "timed out" in result["error"].lower() or "timeout" in result["error"].lower()


def test_delete_op_hard_blocked():
    """os.remove / unlink / rmtree must be rejected outright — no HITL, no confirmed override."""
    from skills.code_runner.tools import _tool_run_python
    for snippet in [
        "import os\nos.remove('/some/file.txt')",
        "import os\nos.unlink('/some/file.txt')",
        "import shutil\nshutil.rmtree('/some/dir')",
        "from pathlib import Path\nPath('/some/file.txt').unlink()",
    ]:
        result = _tool_run_python(code=snippet)
        assert result.get("hitl_required") is not True, f"Should be hard error, not HITL: {snippet}"
        assert result.get("error") is not None, f"Expected error for: {snippet}"
        assert "deletion" in result["error"].lower() or "delete" in result["error"].lower()

    # confirmed=True must NOT bypass the delete block
    result = _tool_run_python(code="import os\nos.remove('/x')", confirmed=True)
    assert result.get("error") is not None


def test_destructive_op_returns_hitl_required():
    """Non-delete destructive ops still go through HITL."""
    from skills.code_runner.tools import _tool_run_python
    # subprocess.run(shell=True) is a non-delete destructive op flagged for HITL
    code = "import subprocess\nsubprocess.run(['echo', 'hi'], shell=True)"
    result = _tool_run_python(code=code)
    assert result.get("hitl_required") is True
    assert len(result["flagged_operations"]) > 0


def test_confirmed_true_skips_ast_scan():
    from skills.code_runner.tools import _tool_run_python
    code = "import os\ntry:\n    pass\nexcept: pass\nprint('done')"
    result = _tool_run_python(code=code, confirmed=True)
    assert "done" in result.get("stdout", "")


def test_syntax_error_returns_error():
    from skills.code_runner.tools import _tool_run_python
    result = _tool_run_python(code="def broken(: invalid syntax")
    assert result.get("error") is not None


def test_tool_contract():
    import skills.code_runner.tools as mod
    from skills._skill_utils import validate_tool_contract
    assert validate_tool_contract(mod, "code_runner") is True


def test_packages_empty_list_runs_normally():
    from skills.code_runner.tools import _tool_run_python
    result = _tool_run_python(code="print('hello')", packages=[])
    assert result.get("error") is None
    assert "hello" in result["stdout"]


def test_packages_known_package_no_error():
    from skills.code_runner.tools import _tool_run_python
    # pip is always available — validates the install flow runs without error
    result = _tool_run_python(code="import sys; print('ok')", packages=["pip"])
    assert result.get("error") is None
    assert "ok" in result["stdout"]


def test_packages_bad_name_returns_error():
    from skills.code_runner.tools import _tool_run_python
    result = _tool_run_python(code="print('x')", packages=["__nonexistent_pkg_xyz__"])
    assert result.get("error") is not None


def test_packages_install_timeout():
    from skills.code_runner.tools import _tool_run_python
    import subprocess
    from unittest.mock import patch
    with patch("skills.code_runner.tools.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=1)):
        result = _tool_run_python(code="print('x')", packages=["something"], _install_timeout=1)
    assert result.get("error") is not None
    assert "install timed out" in result["error"].lower()
