"""Tests for Anthropic provider tool-schema normalization.

Regression: MCP-sourced tools can declare an older JSON Schema draft in
input_schema.$schema (Atlassian's Rovo MCP declares draft-07 on all 31 tools).
The API/gateway requires draft 2020-12 and rejects the whole request with
'400 input_schema: JSON schema is invalid' — one bad $schema poisons every
tool in the request. normalize_tool_schema must strip the declaration (the API
applies 2020-12 by default) and rewrite draft-07 `definitions` -> `$defs`.
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

from llm.anthropic_provider import AnthropicProvider


def _provider():
    return AnthropicProvider()


def test_strips_draft_07_schema_declaration():
    """An input_schema declaring draft-07 must have the $schema key removed."""
    p = _provider()
    tool = {
        "name": "getConfluencePage",
        "description": "Get a Confluence page",
        "input_schema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {"pageId": {"type": "string"}},
        },
    }
    result = p.normalize_tool_schema(tool)
    assert "$schema" not in result["input_schema"]
    # the rest of the schema is preserved
    assert result["input_schema"]["type"] == "object"
    assert result["input_schema"]["properties"]["pageId"]["type"] == "string"


def test_strips_any_draft_schema_declaration():
    """Any $schema value is stripped — the API applies 2020-12 by default."""
    p = _provider()
    for draft in (
        "http://json-schema.org/draft-07/schema#",
        "http://json-schema.org/draft-04/schema#",
        "https://json-schema.org/draft/2020-12/schema",
    ):
        tool = {
            "name": "t",
            "description": "d",
            "input_schema": {"$schema": draft, "type": "object", "properties": {}},
        }
        result = p.normalize_tool_schema(tool)
        assert "$schema" not in result["input_schema"], f"failed for draft {draft}"


def test_rewrites_definitions_to_dollar_defs():
    """draft-07 `definitions` -> 2020-12 `$defs`."""
    p = _provider()
    tool = {
        "name": "t",
        "description": "d",
        "input_schema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "definitions": {"page": {"type": "string"}},
        },
    }
    result = p.normalize_tool_schema(tool)
    assert "definitions" not in result["input_schema"]
    assert "$defs" in result["input_schema"]
    assert result["input_schema"]["$defs"]["page"]["type"] == "string"


def test_no_schema_declaration_passes_through_unchanged():
    """A tool with no $schema and no definitions is returned as-is."""
    p = _provider()
    tool = {
        "name": "read_pptx",
        "description": "Read a pptx",
        "input_schema": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    }
    result = p.normalize_tool_schema(tool)
    assert result == tool


def test_does_not_mutate_input_tool():
    """The caller's tool dict (often from a shared cache) must not be mutated."""
    p = _provider()
    tool = {
        "name": "t",
        "description": "d",
        "input_schema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {},
        },
    }
    result = p.normalize_tool_schema(tool)
    # original untouched
    assert "$schema" in tool["input_schema"]
    # result has it stripped
    assert "$schema" not in result["input_schema"]


def test_non_dict_input_schema_passes_through():
    """A tool with a missing/non-dict input_schema is returned unchanged."""
    p = _provider()
    tool = {"name": "t", "description": "d"}
    result = p.normalize_tool_schema(tool)
    assert result == tool


def test_real_rovo_tool_schema_normalizes():
    """Smoke test with a real Rovo MCP schema shape (draft-07 + anyOf)."""
    p = _provider()
    tool = {
        "name": "getConfluenceSpaces",
        "description": "Get spaces",
        "input_schema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "cloudId": {"type": "string"},
                "ids": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "number"}},
                    ],
                    "description": "Space IDs",
                },
            },
            "required": ["cloudId"],
        },
    }
    result = p.normalize_tool_schema(tool)
    # $schema stripped — the API accepts 2020-12 anyOf natively
    assert "$schema" not in result["input_schema"]
    # anyOf is valid in 2020-12, left intact
    assert "anyOf" in result["input_schema"]["properties"]["ids"]
    assert result["input_schema"]["required"] == ["cloudId"]
