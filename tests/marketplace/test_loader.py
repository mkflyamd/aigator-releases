# tests/marketplace/test_loader.py
import inspect
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))

import pytest
from pathlib import Path

from marketplace import installer, state
from marketplace import tool_sandbox


def _tools_py(tool_name="fake_tool", body="return {'ok': True}"):
    return (
        f'TOOL_DEFS = [{{"name": "{tool_name}", "description": "x", "input_schema": {{"type": "object", "properties": {{}}, "required": []}}}}]\n'
        f'TOOL_STATUS = {{"{tool_name}": "Running..."}}\n'
        f"def _handler(): {body}\n"
        f'TOOL_HANDLERS = {{"{tool_name}": _handler}}\n'
    )


def _described(tool_name="fake_tool"):
    return {
        "ok": True,
        "defs": [{"name": tool_name, "description": "x", "input_schema": {"type": "object", "properties": {}, "required": []}}],
        "status": {tool_name: "Running..."},
    }


@pytest.fixture(autouse=True)
def _clean_installed_index():
    """The installed-skills index is a file under the session home: reset it so one test's entries (e.g. disabled) do not leak."""
    installer.save_installed([])
    yield
    installer.save_installed([])


@pytest.fixture
def described(monkeypatch):
    """Make describe_skill_tools return a canned answer instead of launching anything."""
    box = {"value": _described(), "calls": []}

    def fake(skill_id, skill_dir, perms):
        box["calls"].append((skill_id, perms))
        return box["value"]

    monkeypatch.setattr(tool_sandbox, "describe_skill_tools", fake)
    return box


@pytest.fixture
def skill_folder(make_skill_dir):
    return make_skill_dir({"tools.py": _tools_py()}, name="fake-skill")


def test_load_skill_tools_registers_namespaced_tool(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools

    result = load_skill_tools("fake-skill", skill_folder, "Verified")
    assert result["ok"] is True
    assert "fake-skill__fake_tool" in shared.TOOL_DISPATCH
    assert shared.TOOL_TIER_MAP["fake-skill"] == "Verified"
    entry = next(d for d in shared.TOOLS if d["name"] == "fake-skill__fake_tool")
    assert entry["description"] == "[Verified] x"
    assert shared.TOOL_STATUS["fake-skill__fake_tool"] == "Running..."
    assert "fake-skill__fake_tool" in shared.SKILL_TOOLS_MAP["fake-skill"]


def test_registered_handler_is_the_sandbox_stub(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools

    load_skill_tools("fake-skill", skill_folder, "Verified")
    fn = shared.TOOL_DISPATCH["fake-skill__fake_tool"]
    params = list(inspect.signature(fn).parameters.values())
    assert len(params) == 1 and params[0].annotation in (dict, "dict")
    assert not inspect.iscoroutinefunction(fn)


def test_tools_py_is_never_executed_in_the_app_process(make_skill_dir, described):
    from marketplace.loader import load_skill_tools

    skill = make_skill_dir(
        {"tools.py": "open(__file__ + '.ran', 'w').write('x')\n" + _tools_py()}, name="fake-skill"
    )
    load_skill_tools("fake-skill", skill, "Community")
    assert not (skill / "tools.py.ran").exists()
    assert "_marketplace_skill_fake_skill" not in sys.modules


def test_describe_runs_with_the_approved_permissions(skill_folder, described):
    from marketplace.loader import load_skill_tools
    from marketplace.permissions import Permissions

    installer.save_installed([{"id": "fake-skill", "version": "1.0"}])
    perms = Permissions(network=("api.example.com",))
    state.record_approval("fake-skill", perms.to_dict())
    load_skill_tools("fake-skill", skill_folder, "Community")
    assert described["calls"][0] == ("fake-skill", perms)


def test_load_skill_tools_no_tools_py_is_ok(tmp_path):
    from marketplace.loader import load_skill_tools

    result = load_skill_tools("no-tools-skill", tmp_path, "Mine")
    assert result["ok"] is True


def test_a_disabled_skill_does_not_load(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools

    installer.save_installed([{"id": "fake-skill", "version": "1.0", "disabled": True}])
    result = load_skill_tools("fake-skill", skill_folder, "Verified")
    assert result == {"ok": False, "error": "skill is disabled"}
    assert "fake-skill__fake_tool" not in shared.TOOL_DISPATCH
    assert described["calls"] == []


def test_unload_removes_tools(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools, unload_skill_tools

    load_skill_tools("fake-skill", skill_folder, "Verified")
    assert "fake-skill__fake_tool" in shared.TOOL_DISPATCH

    unload_skill_tools("fake-skill")
    assert "fake-skill__fake_tool" not in shared.TOOL_DISPATCH
    assert not any(d["name"].startswith("fake-skill__") for d in shared.TOOLS)
    assert "fake-skill" not in shared.TOOL_TIER_MAP
    assert "fake-skill" not in shared.INSTALLED_TOOL_MODULES


def test_reinstall_gets_the_new_tool_list(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools, unload_skill_tools

    described["value"] = _described("tool_v1")
    load_skill_tools("fake-skill", skill_folder, "Verified")
    assert "fake-skill__tool_v1" in shared.TOOL_DISPATCH

    unload_skill_tools("fake-skill")
    described["value"] = _described("tool_v2")
    load_skill_tools("fake-skill", skill_folder, "Verified")
    assert "fake-skill__tool_v2" in shared.TOOL_DISPATCH
    assert "fake-skill__tool_v1" not in shared.TOOL_DISPATCH


def test_a_failed_describe_is_recorded_and_registers_nothing(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools

    described["value"] = {"ok": False, "error": "tool contract mismatch (tools defined but no handler)"}
    result = load_skill_tools("broken-skill", skill_folder, "Community")
    assert result["ok"] is False
    assert "contract mismatch" in shared.FAILED_SKILLS["broken-skill"]
    assert not any(d["name"].startswith("broken-skill__") for d in shared.TOOLS)


def test_a_successful_load_clears_an_earlier_failure(skill_folder, described):
    import shared
    from marketplace.loader import load_skill_tools

    shared.FAILED_SKILLS["fake-skill"] = "old"
    load_skill_tools("fake-skill", skill_folder, "Community")
    assert "fake-skill" not in shared.FAILED_SKILLS


def test_end_to_end_the_registered_tool_runs_tools_py_in_the_sandbox_path(make_skill_dir, passthrough_sandbox):
    import shared
    from marketplace.loader import load_skill_tools

    src = (
        'TOOL_DEFS = [{"name": "add", "description": "adds", "input_schema": {"type": "object", "properties": {}}}]\n'
        'TOOL_STATUS = {"add": "Adding"}\n'
        "def add(a, b): return {'sum': a + b}\n"
        'TOOL_HANDLERS = {"add": add}\n'
    )
    skill = make_skill_dir({"tools.py": src}, name="fake-skill")
    installer.save_installed([{"id": "fake-skill", "version": "1.0"}])
    assert load_skill_tools("fake-skill", skill, "Community")["ok"] is True
    assert shared.TOOL_DISPATCH["fake-skill__add"]({"a": 2, "b": 3}) == {"sum": 5}
    assert len(passthrough_sandbox.requests) == 2  # one describe, one call


def test_bad_tools_py_logs_to_failed_skills(make_skill_dir, passthrough_sandbox):
    import shared
    from marketplace.loader import load_skill_tools

    skill = make_skill_dir({"tools.py": "this is not valid python !!!"}, name="broken-skill")
    result = load_skill_tools("broken-skill", skill, "Community")
    assert result["ok"] is False
    assert "broken-skill" in shared.FAILED_SKILLS
