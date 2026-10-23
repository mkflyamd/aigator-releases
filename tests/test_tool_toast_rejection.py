"""A rejected tool call shows a readable toast and row summary, not the raw error code."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from app import _tool_toast


def test_missing_params_toast_names_tool_and_fields():
    result = {"error": "missing_required_params", "missing": ["task"]}
    toast = _tool_toast("describe_images", result)
    assert toast == {"level": "error", "message": "Rejected describe_images: missing task"}


def test_invalid_input_toast_names_tool_and_field():
    result = {"error": "invalid_tool_input", "field": "count", "tool": "run_python"}
    toast = _tool_toast("run_python", result)
    assert toast == {"level": "error", "message": "Rejected run_python: invalid count"}


def test_other_errors_keep_their_text():
    assert _tool_toast("x", {"error": "boom"}) == {"level": "error", "message": "boom"}
