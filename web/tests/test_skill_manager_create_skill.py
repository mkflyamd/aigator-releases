"""create_skill must support bundling supporting files (scripts, reference
docs) alongside SKILL.md — previously the tool only accepted a single
SKILL.md body, so any self-authored skill needing a helper script had no
self-register path and fell back to unregistered manual file writes
(missing from installed-skills.json, invisible in the Marketplace UI).

Also guards the trust boundary this unlocks: a Mine skill is guidance-only
by design (its installed-skills.json entry hardcodes has_tools=False), so
bundling a file named tools.py — which _load_skill_modules()/load_skill_tools()
would otherwise register as live, callable tools — must be rejected rather
than silently letting a self-created skill grant itself new executable tools
with no marketplace consent/tier gate.
"""
import importlib

import pytest


@pytest.fixture
def skill_manager_tools(tmp_path, monkeypatch):
    monkeypatch.setattr("config.INSTALLED_SKILLS_DIR", tmp_path)
    monkeypatch.setattr("marketplace.installer.INSTALLED_SKILLS_DIR", tmp_path)
    import skills.skill_manager.tools as m

    importlib.reload(m)
    yield m
    importlib.reload(m)  # restore real INSTALLED_SKILLS_DIR-bound module state


def test_create_skill_without_files_still_works(skill_manager_tools, tmp_path):
    result = skill_manager_tools._tool_create_skill(
        "simple-skill", "Simple Skill", "Do the thing."
    )
    assert result.get("ok") is True
    assert result["files"] == []
    assert (tmp_path / "mine" / "simple-skill" / "SKILL.md").exists()


def test_create_skill_bundles_supporting_files(skill_manager_tools, tmp_path):
    result = skill_manager_tools._tool_create_skill(
        "weekly-account-update",
        "Weekly Account Update",
        "See scripts/build_blocks.py for the block helpers.",
        files=[
            {"path": "scripts/build_blocks.py", "content": "def esc(s): return s\n"},
        ],
    )
    assert result.get("ok") is True, result
    assert result["files"] == ["scripts/build_blocks.py"]
    skill_dir = tmp_path / "mine" / "weekly-account-update"
    assert (skill_dir / "SKILL.md").exists()
    bundled = skill_dir / "scripts" / "build_blocks.py"
    assert bundled.exists()
    assert bundled.read_text(encoding="utf-8") == "def esc(s): return s\n"

    entries = skill_manager_tools.load_installed()
    entry = next(e for e in entries if e["id"] == "weekly-account-update")
    assert entry["tier"] == "Mine"
    assert entry["has_tools"] is False


def test_create_skill_rejects_tools_py_bundle(skill_manager_tools, tmp_path):
    result = skill_manager_tools._tool_create_skill(
        "sneaky-skill",
        "Sneaky Skill",
        "Nothing to see here.",
        files=[{"path": "tools.py", "content": "TOOL_DEFS = []\n"}],
    )
    assert "error" in result
    assert "reserved filename" in result["error"]
    # Rejected BEFORE any write — no half-created skill directory left behind.
    assert not (tmp_path / "mine" / "sneaky-skill").exists()


def test_create_skill_rejects_nested_tools_py_bundle(skill_manager_tools, tmp_path):
    result = skill_manager_tools._tool_create_skill(
        "sneaky-skill-2",
        "Sneaky Skill 2",
        "Nothing to see here.",
        files=[{"path": "scripts/tools.py", "content": "TOOL_DEFS = []\n"}],
    )
    assert "error" in result
    assert "reserved filename" in result["error"]


def test_create_skill_rejects_path_traversal(skill_manager_tools, tmp_path):
    result = skill_manager_tools._tool_create_skill(
        "traversal-skill",
        "Traversal Skill",
        "Nothing to see here.",
        files=[{"path": "../../evil.py", "content": "pwned = True\n"}],
    )
    assert "error" in result
    assert not (tmp_path / "mine" / "traversal-skill").exists()


def test_create_skill_rejects_absolute_path(skill_manager_tools, tmp_path):
    result = skill_manager_tools._tool_create_skill(
        "absolute-skill",
        "Absolute Skill",
        "Nothing to see here.",
        files=[{"path": "/etc/passwd", "content": "pwned\n"}],
    )
    assert "error" in result
    assert not (tmp_path / "mine" / "absolute-skill").exists()
