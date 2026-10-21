import sandbox
import skills.code_runner.tools as cr
from sandbox.policy import Policy


def test_enforced_when_sandbox_works_even_if_opted_out(monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "enforced")
    assert cr._sandbox_mode({"code_runner_sandbox": "off"}, Policy()) == ("enforced", None)


def test_unavailable_fails_closed_unless_opted_out(monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "unavailable")
    monkeypatch.setattr(sandbox, "sandbox_unavailable_reason", lambda: "install bubblewrap")
    assert cr._sandbox_mode({}, Policy()) == ("unavailable", "install bubblewrap")
    assert cr._sandbox_mode({"code_runner_sandbox": "off"}, Policy()) == ("off", None)


def test_require_sandbox_ignores_the_opt_out(monkeypatch):
    monkeypatch.setattr(sandbox, "sandbox_level", lambda: "unavailable")
    monkeypatch.setattr(sandbox, "sandbox_unavailable_reason", lambda: "install bubblewrap")
    assert cr._sandbox_mode({"code_runner_sandbox": "off"}, Policy(require_sandbox=True)) == (
        "unavailable", "install bubblewrap",
    )


def test_hint_only_for_permission_and_network_errors():
    assert cr._with_sandbox_hint("ValueError: x") == "ValueError: x"
    for err in ("PermissionError: [Errno 13] Permission denied: 'C:\\\\x'",
                "OSError: [Errno 101] Network is unreachable",
                "socket.gaierror: [Errno 11001] getaddrinfo failed",
                "Error: EPERM: operation not permitted, lstat"):
        assert cr._with_sandbox_hint(err).endswith(cr._SANDBOX_HINT + "\n")


def test_runtime_paths_cover_interpreter_and_skill_dir(tmp_path, monkeypatch):
    import sys
    from pathlib import Path

    skill = tmp_path / "skill"
    skill.mkdir()
    monkeypatch.setattr(cr.shutil, "which", lambda name: None)
    paths = cr._runtime_paths(skill, None)
    assert skill.resolve() in paths
    assert any(Path(sys.executable).resolve().is_relative_to(p) for p in paths)
    assert len(paths) == len(set(paths))
    for a in paths:
        assert not any(a != b and a.is_relative_to(b) for b in paths)  # nested entries removed


def test_runtime_paths_frozen_is_bundle_dir(tmp_path, monkeypatch):
    exe = tmp_path / "backend" / "aigator-backend.exe"
    exe.parent.mkdir()
    exe.write_text("")
    monkeypatch.setattr(cr.sys, "frozen", True, raising=False)
    monkeypatch.setattr(cr.sys, "executable", str(exe))
    monkeypatch.setattr(cr.shutil, "which", lambda name: None)
    assert cr._runtime_paths(None, None) == [exe.parent.resolve()]


def test_tool_schema_and_skill_doc():
    from pathlib import Path

    props = cr.TOOL_DEFS[0]["input_schema"]["properties"]
    for name in ("extra_read_paths", "extra_write_paths", "network_hosts"):
        assert props[name]["type"] == "array"
    assert "_context_id" not in props
    assert "full read access" not in cr.TOOL_DEFS[0]["description"]
    skill_md = (Path(cr.__file__).parent / "SKILL.md").read_text(encoding="utf-8")
    assert "full read access" not in skill_md
    assert "extra_read_paths" in skill_md and "approval_required" in skill_md
