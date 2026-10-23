import importlib
import inspect

import jsonschema
import pytest

from skills._skill_utils import validate_tool_contract
from tests.demo_media_ops.helpers import make_video

tools = importlib.import_module("skills.gator-demo-recorder.tools")


def test_tool_contract_is_valid():
    assert tools.SKILL_ID == "gator-demo-recorder"
    assert validate_tool_contract(tools, "gator-demo-recorder")


@pytest.mark.parametrize("tool", tools.TOOL_DEFS, ids=lambda t: t["name"])
def test_schema_matches_handler_signature(tool):
    jsonschema.Draft202012Validator.check_schema(tool["input_schema"])
    params = inspect.signature(tools.TOOL_HANDLERS[tool["name"]]).parameters
    props = tool["input_schema"]["properties"]
    assert set(props) == set(params)
    for name in tool["input_schema"]["required"]:
        assert params[name].default is inspect.Parameter.empty
    for name, p in params.items():
        assert p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD


def test_handlers_return_error_dict_not_exception(project):
    pid, _ = project
    result = tools.TOOL_HANDLERS["demo_inspect_frames"](
        source="source/recording.mp4", times_sec=[390, 405], project_id=pid)
    assert result["error"] == "out_of_range"
    assert result["duration_sec"] == pytest.approx(62.2, abs=0.2)
    assert tools.TOOL_HANDLERS["demo_media_manifest"](project_id="nope")["error"] == "project_not_found"


def test_replace_through_tool_layer(project):
    pid, folder = project
    make_video(folder / "source" / "fix.mp4", 8, color="red")
    result = tools.TOOL_HANDLERS["demo_replace_interval"](
        start_sec=20, end_sec=25, insert_source="source/fix.mp4", project_id=pid)
    assert "error" not in result
    assert result["inserted_from"]["rel"] == "source/fix.mp4"
