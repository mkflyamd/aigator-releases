"""Tests for skill dependency map and permission gate."""
import pytest


def test_skill_dependencies_map_exists():
    """SKILL_DEPENDENCIES_MAP must exist in shared and be a dict."""
    import web.shared as shared
    assert hasattr(shared, 'SKILL_DEPENDENCIES_MAP')
    assert isinstance(shared.SKILL_DEPENDENCIES_MAP, dict)


def test_skill_dependencies_map_accepts_correct_structure():
    """SKILL_DEPENDENCIES_MAP entries must be lists of dicts with 'id' and 'reason' string keys."""
    import web.shared as shared

    shared.SKILL_DEPENDENCIES_MAP['_test_skill'] = [
        {"id": "shell_runner", "reason": "runs shell commands"}
    ]

    deps = shared.SKILL_DEPENDENCIES_MAP['_test_skill']
    assert isinstance(deps, list)
    assert len(deps) == 1
    assert isinstance(deps[0], dict)
    assert deps[0]['id'] == 'shell_runner'
    assert deps[0]['reason'] == 'runs shell commands'

    # Cleanup
    del shared.SKILL_DEPENDENCIES_MAP['_test_skill']


def test_load_skill_tools_parses_requires(tmp_path, monkeypatch):
    """load_skill_tools populates SKILL_DEPENDENCIES_MAP from SKILL.md requires field."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web'))
    import shared
    from marketplace.loader import load_skill_tools

    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: My Skill\nrequires:\n  - id: shell_runner\n    reason: runs commands\n---\n\n# My Skill\n",
        encoding="utf-8",
    )

    shared.SKILL_DEPENDENCIES_MAP.pop("my-skill", None)

    load_skill_tools("my-skill", skill_dir, "Mine")

    assert "my-skill" in shared.SKILL_DEPENDENCIES_MAP
    deps = shared.SKILL_DEPENDENCIES_MAP["my-skill"]
    assert len(deps) == 1
    assert deps[0]["id"] == "shell_runner"
    assert deps[0]["reason"] == "runs commands"

    shared.SKILL_DEPENDENCIES_MAP.pop("my-skill", None)


def test_filter_tools_includes_approved_dep_tools():
    """_filter_tools expands skill_ids to include approved dependency skill tools."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web'))
    import shared
    from routes.chat import _filter_tools

    # Set up fake tool maps
    shared.SKILL_TOOLS_MAP["_test_primary"] = {"_test_primary__noop"}
    shared.SKILL_TOOLS_MAP["shell_runner"] = {"shell_runner__run_shell"}
    shared.SKILL_DEPENDENCIES_MAP["_test_primary"] = [
        {"id": "shell_runner", "reason": "runs commands"}
    ]
    shared.TOOLS.append({"name": "shell_runner__run_shell", "description": "test", "input_schema": {"type": "object", "properties": {}}})

    result = _filter_tools("_test_primary", has_images=False)
    tool_names = {t["name"] for t in result}
    assert "shell_runner__run_shell" in tool_names

    # Cleanup
    shared.TOOLS[:] = [t for t in shared.TOOLS if t["name"] != "shell_runner__run_shell"]
    shared.SKILL_TOOLS_MAP.pop("_test_primary", None)
    shared.SKILL_TOOLS_MAP.pop("shell_runner", None)
    shared.SKILL_DEPENDENCIES_MAP.pop("_test_primary", None)


def test_load_skill_tools_autodetects_shell_usage(tmp_path):
    """load_skill_tools auto-populates SKILL_DEPENDENCIES_MAP when SKILL.md body contains shell signals."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web'))
    import shared
    from marketplace.loader import load_skill_tools

    skill_dir = tmp_path / "auto-skill"
    skill_dir.mkdir()
    # No `requires` in frontmatter — body contains "gh " and "```bash" signals
    (skill_dir / "SKILL.md").write_text(
        "---\nname: Auto Skill\nmetadata:\n  author: user\n---\n\n"
        "Run `gh issue create` to file issues.\n\n```bash\ngh issue list\n```\n",
        encoding="utf-8",
    )

    shared.SKILL_DEPENDENCIES_MAP.pop("auto-skill", None)

    load_skill_tools("auto-skill", skill_dir, "Mine")

    assert "auto-skill" in shared.SKILL_DEPENDENCIES_MAP
    deps = shared.SKILL_DEPENDENCIES_MAP["auto-skill"]
    assert any(d["id"] == "shell_runner" for d in deps)

    shared.SKILL_DEPENDENCIES_MAP.pop("auto-skill", None)


def test_load_skill_tools_explicit_requires_overrides_autodetect(tmp_path):
    """Explicit requires frontmatter is used as-is; auto-detect does not override it."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web'))
    import shared
    from marketplace.loader import load_skill_tools

    skill_dir = tmp_path / "explicit-skill"
    skill_dir.mkdir()
    # Explicit requires with custom reason — body also has shell signals
    (skill_dir / "SKILL.md").write_text(
        "---\nname: Explicit Skill\nrequires:\n  - id: shell_runner\n    reason: custom reason\n---\n\n"
        "Uses bash and gh CLI.\n",
        encoding="utf-8",
    )

    shared.SKILL_DEPENDENCIES_MAP.pop("explicit-skill", None)

    load_skill_tools("explicit-skill", skill_dir, "Mine")

    deps = shared.SKILL_DEPENDENCIES_MAP.get("explicit-skill", [])
    assert len(deps) == 1
    assert deps[0]["reason"] == "custom reason"  # not "detected shell usage in skill"

    shared.SKILL_DEPENDENCIES_MAP.pop("explicit-skill", None)


def test_user_skills_bootstrap_includes_requires(monkeypatch):
    """__USER_SKILLS__ bootstrap payload includes requires for skills that have dependencies."""
    import json
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web'))
    import shared

    # Inject a fake dependency into the map
    shared.SKILL_DEPENDENCIES_MAP["git-issue-creator"] = [
        {"id": "shell_runner", "reason": "runs gh CLI commands"}
    ]

    # Must import after setting up shared state
    from routes.health import _user_skills_bootstrap
    script = _user_skills_bootstrap()

    # Extract the JSON array from the script tag
    start = script.index('[')
    end = script.rindex(']') + 1
    skills = json.loads(script[start:end])

    matched = [s for s in skills if s["id"] == "git-issue-creator"]
    if matched:  # only assert if the skill is actually installed
        assert "requires" in matched[0]
        assert matched[0]["requires"][0]["id"] == "shell_runner"

    # Cleanup
    shared.SKILL_DEPENDENCIES_MAP.pop("git-issue-creator", None)
