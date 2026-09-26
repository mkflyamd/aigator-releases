"""Regression checks for the Code project/agent session dropdown."""

from pathlib import Path


ROOT = Path(__file__).parent.parent
STYLE = (ROOT / "web" / "static" / "style.css").read_text(encoding="utf-8")
SCRIPT = (ROOT / "web" / "static" / "tp-code-agent.js").read_text(encoding="utf-8")


def test_project_dropdown_is_viewport_bounded_and_scrollable():
    rule = STYLE.split(".ca-project-dropdown {", 1)[1].split("}", 1)[0]
    assert "max-height: calc(100vh - 16px)" in rule
    assert "overflow-y: auto" in rule
    assert "scrollbar-width: thin" in STYLE
    assert ".ca-project-dropdown::-webkit-scrollbar" in STYLE


def test_project_dropdown_flips_above_chip_when_below_space_is_smaller():
    dropdown = SCRIPT.split("function _caShowSessionDropdown()", 1)[1].split(
        "function _caSetActiveProject", 1
    )[0]
    assert "const spaceBelow" in dropdown
    assert "const spaceAbove" in dropdown
    assert "const openBelow = spaceBelow >= spaceAbove" in dropdown
    assert "dropdown.style.maxHeight = availableHeight" in dropdown
