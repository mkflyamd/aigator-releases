# tests/marketplace/test_loader.py
import sys, pathlib, types, importlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "web"))

import pytest
from unittest.mock import patch
from pathlib import Path


def _make_fake_tools_py(tmp_path: Path, tool_name: str = "fake_tool") -> Path:
    """Write a minimal valid tools.py to a temp directory."""
    tools_py = tmp_path / "tools.py"
    tools_py.write_text(f"""
SKILL_ID = "fake-skill"
TOOL_DEFS = [{{"name": "{tool_name}", "description": "x", "input_schema": {{"type": "object", "properties": {{}}, "required": []}}}}]
TOOL_STATUS = {{"{tool_name}": "Running..."}}
def _handler(): return {{"ok": True}}
TOOL_HANDLERS = {{"{tool_name}": _handler}}
""", encoding="utf-8")
    return tools_py


def test_load_skill_tools_registers_namespaced_tool(tmp_path):
    import shared
    from marketplace.loader import load_skill_tools

    _make_fake_tools_py(tmp_path)
    result = load_skill_tools("fake-skill", tmp_path, "Verified")
    assert result["ok"] is True
    assert "fake-skill__fake_tool" in shared.TOOL_DISPATCH
    assert shared.TOOL_TIER_MAP["fake-skill"] == "Verified"
    assert any(d["name"] == "fake-skill__fake_tool" for d in shared.TOOLS)


def test_load_skill_tools_no_tools_py_is_ok(tmp_path):
    from marketplace.loader import load_skill_tools
    # tmp_path has no tools.py — SKILL.md-only skill
    result = load_skill_tools("no-tools-skill", tmp_path, "Mine")
    assert result["ok"] is True


def test_unload_removes_tools(tmp_path):
    import shared
    from marketplace.loader import load_skill_tools, unload_skill_tools

    _make_fake_tools_py(tmp_path)
    load_skill_tools("fake-skill", tmp_path, "Verified")
    assert "fake-skill__fake_tool" in shared.TOOL_DISPATCH

    unload_skill_tools("fake-skill")
    assert "fake-skill__fake_tool" not in shared.TOOL_DISPATCH
    assert "fake-skill" not in shared.TOOL_TIER_MAP
    assert "fake-skill" not in shared.INSTALLED_TOOL_MODULES


def test_reinstall_gets_fresh_module(tmp_path):
    import shared
    from marketplace.loader import load_skill_tools, unload_skill_tools

    _make_fake_tools_py(tmp_path, "tool_v1")
    load_skill_tools("fake-skill", tmp_path, "Verified")
    assert "fake-skill__tool_v1" in shared.TOOL_DISPATCH

    # Simulate upgrade: new tools.py with different tool name
    unload_skill_tools("fake-skill")
    tools_py = tmp_path / "tools.py"
    tools_py.write_text("""
SKILL_ID = "fake-skill"
TOOL_DEFS = [{"name": "tool_v2", "description": "x", "input_schema": {"type": "object", "properties": {}, "required": []}}]
TOOL_STATUS = {"tool_v2": "Running..."}
def _handler(): return {"ok": True}
TOOL_HANDLERS = {"tool_v2": _handler}
""", encoding="utf-8")
    load_skill_tools("fake-skill", tmp_path, "Verified")
    assert "fake-skill__tool_v2" in shared.TOOL_DISPATCH
    assert "fake-skill__tool_v1" not in shared.TOOL_DISPATCH


def test_bad_tools_py_logs_to_failed_skills(tmp_path):
    import shared
    from marketplace.loader import load_skill_tools

    (tmp_path / "tools.py").write_text("this is not valid python !!!", encoding="utf-8")
    result = load_skill_tools("broken-skill", tmp_path, "Community")
    assert result["ok"] is False
    assert "broken-skill" in shared.FAILED_SKILLS
