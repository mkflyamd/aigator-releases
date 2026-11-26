"""The model must learn up front which folders can never be granted, not by failing a grant."""

import importlib

tools = importlib.import_module("skills.code_runner.tools")


def _props():
    tool = next(t for t in tools.TOOL_DEFS if t["name"] == "run_python")
    return tool["input_schema"]["properties"]


def test_grant_parameters_say_which_folders_can_never_be_granted():
    for name in ("extra_read_paths", "extra_write_paths"):
        text = _props()[name]["description"]
        assert "~/.gator" in text and "OUTPUT_DIR" in text and "never" in text, name


def test_refusal_points_to_the_output_folder():
    msg = tools._not_grantable_message(["C:/Users/x/.gator/work"])
    assert "OUTPUT_DIR" in msg
