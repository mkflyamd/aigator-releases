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

    result = _tool_run_python(
        code="import os\nwith open(os.path.join(OUTPUT_DIR, 'out.txt'), 'w') as f: f.write('data')"
    )
    assert result.get("error") is None
    assert len(result["files"]) == 1
    assert result["files"][0]["name"] == "out.txt"
    assert result["files"][0]["download_url"].endswith("/out.txt")


def test_timeout_returns_error():
    from skills.code_runner.tools import _tool_run_python

    result = _tool_run_python(code="import time; time.sleep(60)", timeout=2)
    assert result.get("error") is not None
    assert (
        "timed out" in result["error"].lower() or "timeout" in result["error"].lower()
    )


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
        assert result.get("hitl_required") is not True, (
            f"Should be hard error, not HITL: {snippet}"
        )
        assert result.get("error") is not None, f"Expected error for: {snippet}"
        assert (
            "deletion" in result["error"].lower() or "delete" in result["error"].lower()
        )

    # confirmed=True must NOT bypass the delete block
    result = _tool_run_python(code="import os\nos.remove('/x')", confirmed=True)
    assert result.get("error") is not None


def test_bare_remove_not_blocked():
    """Issue #76: bare .remove()/.discard()/item-del on arbitrary objects (list,
    set, lxml Element, python-pptx XML) are in-memory edits, not filesystem
    deletes, and must NOT be blocked. Receiver type is unknowable from AST, so
    only module-qualified deletes (os/shutil) and Path(...).unlink/rmdir block."""
    from skills.code_runner.tools import _ast_scan

    for snippet in [
        "lst = [1, 2, 3]\nlst.remove(2)",
        "parent.remove(child)",
        "paragraph._p.remove(run._r)",
        "xml_slides.remove(slide_element)",
        "s = {1, 2}\ns.discard(1)",
        "d = {'a': 1}\ndel d['a']",
    ]:
        blocked, _ = _ast_scan(snippet)
        assert not blocked, (
            f"Should NOT be blocked (in-memory edit): {snippet!r} -> {blocked}"
        )


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


def test_find_skill_dir_resolves_bundled_plugin_skill(tmp_path, monkeypatch):
    """Finding #4 (2026-08-07 milestone review): bundled plugin skills live
    at PLUGINS_DIR/cache/{source}/{plugin_id}/{version}/{skill_dir}, never
    at a flat root/{skill_id} path, and register under a namespaced id
    ({plugin_id}__{relpath}, see marketplace.installer.namespaced_skill_id).
    _find_skill_dir must resolve that namespaced id back to its on-disk dir
    so run_python(skill_id=...) can add a bundled skill's tools.py to
    sys.path."""
    import config as cfg_mod
    import skills.code_runner.tools as cr_mod

    skill_dir = (
        tmp_path
        / "cache"
        / "claude-plugins-official"
        / "amd-skills"
        / "1.0"
        / "skills"
        / "a"
    )
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: a\n---\nDo a.", encoding="utf-8")

    monkeypatch.setattr(cfg_mod, "PLUGINS_DIR", tmp_path)
    monkeypatch.setattr(cr_mod, "PLUGINS_DIR", tmp_path)

    found = cr_mod._find_skill_dir("amd-skills__skills-a")
    assert found == skill_dir


def test_find_skill_dir_flat_root_still_resolves(tmp_path, monkeypatch):
    """Existing flat-root resolution (USER_SKILL_DIRS / root / skill_id) must
    be unaffected by the plugin-cache fallback added for finding #4."""
    import config as cfg_mod
    import skills.code_runner.tools as cr_mod

    flat_root = tmp_path / "installed"
    skill_dir = flat_root / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\n---\nHi.", encoding="utf-8"
    )

    monkeypatch.setattr(cfg_mod, "PLUGINS_DIR", tmp_path / "no-such-plugins-dir")
    monkeypatch.setattr(cr_mod, "PLUGINS_DIR", tmp_path / "no-such-plugins-dir")
    monkeypatch.setattr(cr_mod, "USER_SKILL_DIRS", [flat_root])

    found = cr_mod._find_skill_dir("my-skill")
    assert found == skill_dir


def test_find_skill_dir_unknown_id_returns_none(tmp_path, monkeypatch):
    import config as cfg_mod
    import skills.code_runner.tools as cr_mod

    monkeypatch.setattr(cfg_mod, "PLUGINS_DIR", tmp_path)
    monkeypatch.setattr(cr_mod, "PLUGINS_DIR", tmp_path)
    assert cr_mod._find_skill_dir("does-not-exist") is None


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

    with patch(
        "skills.code_runner.tools.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=1),
    ):
        result = _tool_run_python(
            code="print('x')", packages=["something"], _install_timeout=1
        )
    assert result.get("error") is not None
    assert "install timed out" in result["error"].lower()


# --- forensic logging (issue: failed run_python code/stderr unrecoverable after restart) ---


def test_forensic_files_written_on_success(tmp_path):
    """code.py + stdout.log + stderr.log land on disk so the exact executed
    script and full output survive a server restart."""
    from skills.code_runner.tools import _tool_run_python

    result = _tool_run_python(code="print('forensic-success')")
    assert result["error"] is None
    run_dirs = list(tmp_path.iterdir())
    assert len(run_dirs) == 1, f"expected one run_dir, got {run_dirs}"
    run_dir = run_dirs[0]
    assert (run_dir / "code.py").exists()
    assert (run_dir / "stdout.log").exists()
    assert (run_dir / "stderr.log").exists()
    code_src = (run_dir / "code.py").read_text(encoding="utf-8")
    assert "print('forensic-success')" in code_src
    # preamble (OUTPUT_DIR injection) is also captured
    assert "OUTPUT_DIR" in code_src
    assert "forensic-success" in (run_dir / "stdout.log").read_text(encoding="utf-8")


def test_forensic_files_written_on_error_exit(tmp_path):
    """Full stderr is persisted even though the tool result only returns stderr[:500]."""
    from skills.code_runner.tools import _tool_run_python

    long_trace = "x" * 2000  # longer than the 500-char truncation in the returned error
    result = _tool_run_python(
        code=f"import sys; sys.stderr.write('T-{long_trace}\\n'); raise SystemExit(1)"
    )
    assert result["error"] is not None
    run_dir = next(tmp_path.iterdir())
    stderr_log = (run_dir / "stderr.log").read_text(encoding="utf-8")
    assert long_trace in stderr_log, "full stderr must be on disk, not truncated"
    assert "Code exited with code 1" in result["error"]


def test_forensic_files_excluded_from_files_array(tmp_path):
    """code.py / stdout.log / stderr.log are for the user/dev, not model outputs —
    they must not appear in the returned files[] array."""
    from skills.code_runner.tools import _tool_run_python

    result = _tool_run_python(
        code="import os\nwith open(os.path.join(OUTPUT_DIR,'out.txt'),'w') as f: f.write('data')"
    )
    assert result["error"] is None
    names = {f["name"] for f in result["files"]}
    assert names == {"out.txt"}, f"forensic files leaked into result: {names}"


def test_forensic_files_written_on_timeout(tmp_path):
    """Timeout kills the subprocess but partial stdout/stderr (if any) and the
    code.py are still recoverable on disk."""
    from skills.code_runner.tools import _tool_run_python

    result = _tool_run_python(code="import time; time.sleep(60)", timeout=2)
    assert result["error"] is not None
    assert "timed out" in result["error"].lower()
    run_dir = next(tmp_path.iterdir())
    assert (run_dir / "code.py").exists()
    assert "time.sleep(60)" in (run_dir / "code.py").read_text(encoding="utf-8")
    # stderr.log is written (possibly empty) even on timeout
    assert (run_dir / "stderr.log").exists()
    assert (run_dir / "stdout.log").exists()
    # timeout result carries no files (subprocess was killed before writing outputs)
    assert result["files"] == []


def test_forensic_paths_returned_to_model_on_failure(tmp_path):
    """On failure the result includes a `forensic` block pointing at the full
    code.py + stderr.log on disk, so the model can read the complete traceback
    instead of guessing from the stderr[:500] truncation in the error string."""
    from skills.code_runner.tools import _tool_run_python

    result = _tool_run_python(code="x = does_not_exist  # NameError")
    assert result["error"] is not None
    f = result["forensic"]
    assert f["run_id"]
    # absolute on-disk paths
    assert f["code_path"].endswith("code.py")
    assert f["stderr_path"].endswith("stderr.log")
    # download URLs (served by /api/files/{run_id}/{filename})
    assert f["code_url"].endswith("/code.py")
    assert f["stderr_url"].endswith("/stderr.log")
    # the files the forensic paths point at actually exist
    from pathlib import Path

    assert Path(f["code_path"]).exists()
    assert Path(f["stderr_path"]).exists()
    # and the stderr.log holds the full traceback, not truncated
    assert "NameError" in Path(f["stderr_path"]).read_text(encoding="utf-8")
