import asyncio

import pytest
from jsonschema.validators import validator_for

import app
import shared
from tool_validation import validate_tool_inputs

SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "max_results": {"type": "integer"},
        "mode": {"type": "string", "enum": ["fast", "full"]},
    },
    "required": ["query"],
}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def tool():
    shared.TOOLS.append({"name": "_t_val", "description": "x", "input_schema": SCHEMA})
    shared.TOOL_DISPATCH["_t_val"] = lambda query, max_results=5, mode="fast": {"ok": True, "n": max_results}
    yield "_t_val"
    shared.TOOLS[:] = [d for d in shared.TOOLS if d.get("name") != "_t_val"]
    shared.TOOL_DISPATCH.pop("_t_val", None)


def test_valid_input_runs(tool):
    assert _run(app.execute_tool(tool, {"query": "q", "max_results": 3})) == {"ok": True, "n": 3}


def test_wrong_type_is_rejected_with_field_and_reason(tool):
    res = _run(app.execute_tool(tool, {"query": "q", "max_results": "many"}))
    assert res["error"] == "invalid_tool_input"
    assert res["tool"] == tool
    assert res["field"] == "max_results"
    assert "integer" in res["reason"]


def test_value_outside_enum_is_rejected(tool):
    res = _run(app.execute_tool(tool, {"query": "q", "mode": "slow"}))
    assert res["error"] == "invalid_tool_input"
    assert res["field"] == "mode"


def test_null_for_an_optional_field_is_ignored(tool):
    assert _run(app.execute_tool(tool, {"query": "q", "max_results": None}))["ok"] is True


def test_unsupported_schema_fails_open():
    shared.TOOLS.append({"name": "_t_bad", "description": "x", "input_schema": {"type": "nonsense"}})
    try:
        assert validate_tool_inputs("_t_bad", {"anything": 1}) is None
    finally:
        shared.TOOLS[:] = [d for d in shared.TOOLS if d.get("name") != "_t_bad"]


def test_tool_without_schema_is_not_validated():
    assert validate_tool_inputs("_no_such_tool", {"anything": 1}) is None


def test_every_native_tool_schema_is_a_valid_schema():
    bad = []
    for d in shared.TOOLS:
        if "__" in d.get("name", ""):  # MCP tools carry third-party schemas
            continue
        schema = d.get("input_schema")
        if not isinstance(schema, dict):
            bad.append((d.get("name"), "no input_schema"))
            continue
        try:
            validator_for(schema).check_schema(schema)
        except Exception as exc:
            bad.append((d.get("name"), str(exc)[:120]))
    assert not bad, bad
