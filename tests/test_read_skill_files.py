"""read_skill can read a skill's own reference files, and only those."""

import importlib.util
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import app  # noqa: E402,F401
import config  # noqa: E402
import pytest  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "always_on_tools_under_test",
    os.path.join(os.path.dirname(__file__), "..", "web", "skills", "_always_on", "tools.py"),
)
tools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tools)


@pytest.fixture
def skill(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    folder = root / "demo-design"
    (folder / "references").mkdir(parents=True)
    (folder / "assets").mkdir()
    (folder / "SKILL.md").write_text("---\nname: demo-design\n---\nRead references/DESIGN.md", encoding="utf-8")
    (folder / "references" / "DESIGN.md").write_text("# Design tokens", encoding="utf-8")
    (folder / "assets" / "logo.png").write_bytes(b"\x89PNG")
    (folder / "references" / "big.md").write_text("x" * (tools._SKILL_FILE_MAX_BYTES + 1), encoding="utf-8")
    (tmp_path / "secret.md").write_text("outside", encoding="utf-8")
    monkeypatch.setattr(config, "USER_SKILL_DIRS", [root])
    return folder


def test_the_guide_lists_the_files_the_skill_ships(skill):
    out = tools._tool_read_skill("demo-design")
    assert "Read references/DESIGN.md" in out["skill_guide"]
    assert "references/DESIGN.md" in out["files"] and "assets/logo.png" in out["files"]


def test_a_reference_file_is_returned(skill):
    assert tools._tool_read_skill("demo-design", file="references/DESIGN.md") == {
        "file": "references/DESIGN.md", "content": "# Design tokens",
    }


def test_a_path_outside_the_skill_is_refused(skill):
    for bad in ("../secret.md", "references/../../secret.md", str(skill.parent.parent / "secret.md")):
        out = tools._tool_read_skill("demo-design", file=bad)
        assert "content" not in out and "outside" not in str(out)


def test_a_missing_file_lists_what_exists(skill):
    out = tools._tool_read_skill("demo-design", file="references/nope.md")
    assert "error" in out and "references/DESIGN.md" in out["files"]


def test_binary_and_oversized_files_give_a_path_not_content(skill):
    assert "path" in tools._tool_read_skill("demo-design", file="assets/logo.png")
    assert "path" in tools._tool_read_skill("demo-design", file="references/big.md")
