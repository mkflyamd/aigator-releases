"""Regression coverage for issue #41's MCP compatibility boundary."""

import asyncio
import json
import re
from types import SimpleNamespace

import pytest


def test_gateway_alias_is_legal_bounded_stable_and_collision_resistant():
    from tool_pipeline import gateway_tool_alias

    raw_connection = "plugin:atlassian:atlassian"
    first = gateway_tool_alias(raw_connection, "get:Confluence Page")
    again = gateway_tool_alias(raw_connection, "get:Confluence Page")
    other = gateway_tool_alias("plugin_atlassian_atlassian", "get:Confluence Page")

    assert first == again
    assert first != other
    assert len(first) <= 64
    assert re.fullmatch(r"[A-Za-z0-9_-]+", first)
    long_alias = gateway_tool_alias("mcp-" + "x" * 100, "tool_" + "y" * 100)
    assert len(long_alias) == 64
    assert re.fullmatch(r"[A-Za-z0-9_-]+", long_alias)


def test_gateway_alias_rejects_empty_name_and_disambiguates_existing_name():
    from tool_pipeline import ToolCompatibilityError, gateway_tool_alias

    with pytest.raises(ToolCompatibilityError, match="empty"):
        gateway_tool_alias("mcp-example", "")

    legacy = "mcp-example__search"
    alias = gateway_tool_alias("mcp-example", "search", existing_names={legacy})
    assert alias != legacy
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", alias)


def test_gateway_alias_preserves_legal_raw_suffix_for_capability_detection():
    from tool_pipeline import gateway_tool_alias

    alias = gateway_tool_alias("plugin:browser:chrome", "navigate_page")
    assert alias.endswith("__navigate_page")


def test_ambiguous_separator_alias_is_stable_regardless_of_registered_order():
    from tool_pipeline import gateway_tool_alias

    first = gateway_tool_alias("mcp-a", "b__search")
    second = gateway_tool_alias("mcp-a", "b__search", existing_names={"mcp-a__b__search"})
    assert first == second
    assert first != "mcp-a__b__search"


def test_project_schema_handles_nested_draft_and_rewrites_local_refs_without_mutation():
    from tool_pipeline import project_json_schema

    raw = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "definitions": {"Filter": {"type": "string"}},
        "properties": {
            "filter": {"$ref": "#/definitions/Filter"},
            "nested": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {"value": {"type": "string"}},
            },
        },
    }

    projected = project_json_schema(raw)

    assert "$schema" in raw
    assert "definitions" in raw
    assert "$schema" not in json.dumps(projected)
    assert "definitions" not in projected
    assert projected["properties"]["filter"]["$ref"] == "#/$defs/Filter"
    assert projected["$defs"]["Filter"] == {"type": "string"}


def test_project_schema_validates_metaschema_and_preserves_external_refs():
    from tool_pipeline import UnsupportedToolSchema, project_json_schema

    with pytest.raises(UnsupportedToolSchema):
        project_json_schema({"type": "object", "required": "not-an-array"})
    with pytest.raises(UnsupportedToolSchema):
        project_json_schema({"type": "object", "properties": []})

    external = project_json_schema({
        "type": "object",
        "properties": {"x": {"$ref": "https://example.test/schema#/definitions/X"}},
    })
    assert external["properties"]["x"]["$ref"] == "https://example.test/schema#/definitions/X"


def test_project_schema_visits_unevaluated_items():
    from tool_pipeline import project_json_schema

    projected = project_json_schema({
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "unevaluatedItems": {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "type": "string",
                },
            }
        },
    })
    assert "$schema" not in projected["properties"]["items"]["unevaluatedItems"]


def test_project_schema_quarantines_legacy_ref_with_assertion_sibling():
    from tool_pipeline import UnsupportedToolSchema, project_json_schema

    with pytest.raises(UnsupportedToolSchema, match="legacy \\$ref siblings"):
        project_json_schema({
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {
                "x": {"$ref": "#/definitions/A", "type": "integer"},
            },
            "definitions": {"A": {"type": "string"}},
        })


@pytest.mark.parametrize(
    "schema",
    [
        {"$schema": "http://json-schema.org/draft-07/schema#", "type": "array", "items": [{"type": "string"}]},
        {"$schema": "http://json-schema.org/draft-07/schema#", "type": "number", "exclusiveMinimum": True},
        {"$schema": "http://json-schema.org/draft-07/schema#", "type": "object", "dependencies": {"a": ["b"]}},
    ],
)
def test_project_schema_quarantines_dialect_sensitive_constructs(schema):
    from tool_pipeline import UnsupportedToolSchema

    with pytest.raises(UnsupportedToolSchema):
        from tool_pipeline import project_json_schema

        project_json_schema(schema)


def test_both_providers_use_shared_schema_projection():
    from llm.anthropic_provider import AnthropicProvider
    from llm.openai_provider import OpenAIProvider

    tool = {
        "name": "safe_name",
        "description": "",
        "input_schema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {"x": {"type": "string"}},
        },
    }
    anthropic = AnthropicProvider.__new__(AnthropicProvider).normalize_tool_schema(tool)
    openai = OpenAIProvider.__new__(OpenAIProvider).normalize_tool_schema(tool)

    assert "$schema" not in anthropic["input_schema"]
    assert "$schema" not in openai["function"]["parameters"]
    assert "$schema" in tool["input_schema"]


def test_prepare_tools_enforces_provider_budget_before_request():
    from tool_pipeline import ToolBudgetExceeded, prepare_tool_definitions

    class Provider:
        max_tools = 2
        max_tool_name_length = 64

        def normalize_tool_schema(self, tool):
            return tool

    tools = [
        {"name": f"tool_{i}", "description": "", "input_schema": {"type": "object"}}
        for i in range(3)
    ]
    with pytest.raises(ToolBudgetExceeded, match="3 tools.*limit is 2"):
        prepare_tool_definitions(Provider(), "model", tools)


def test_budget_selection_keeps_required_tools_and_drops_lower_priority_groups():
    from tool_pipeline import select_tools_with_budget

    tools = [{"name": name} for name in ("always", "explicit", "current", "pinned", "history")]
    selection = select_tools_with_budget(
        tools,
        max_tools=3,
        required_names={"always", "explicit"},
        priority_groups=[{"current"}, {"pinned"}, {"history"}],
    )
    assert [tool["name"] for tool in selection.tools] == ["always", "explicit", "current"]
    assert selection.omitted_names == ["pinned", "history"]


def test_budget_selection_never_silently_drops_required_tools():
    from tool_pipeline import select_tools_with_budget

    tools = [{"name": name} for name in ("explicit_a", "explicit_b", "optional")]
    selection = select_tools_with_budget(
        tools, max_tools=1, required_names={"explicit_a", "explicit_b"}, priority_groups=[]
    )
    assert selection.required_overflow
    assert selection.tools == tools


def test_failover_reapplies_smaller_provider_budget_with_required_tools_first():
    from agent_loop import _prepare_request_tools

    class FallbackProvider:
        max_tools = 2
        max_tool_name_length = 64

        def normalize_tool_schema(self, tool):
            return tool

    tools = [{"name": name} for name in ("explicit", "current", "history")]
    source, projected = _prepare_request_tools(
        FallbackProvider(), "fallback", tools, {"explicit"}
    )
    assert [tool["name"] for tool in source] == ["explicit", "current"]
    assert projected == source


def test_midturn_new_skill_tools_are_required_not_optional():
    from tool_pipeline import select_tools_with_budget

    tools = [{"name": name} for name in ("old_required", "new_skill_tool", "old_optional")]
    selection = select_tools_with_budget(
        tools,
        max_tools=2,
        required_names={"old_required", "new_skill_tool"},
        priority_groups=[{"old_optional"}],
    )
    assert [tool["name"] for tool in selection.tools] == ["old_required", "new_skill_tool"]


def test_gateway_rejection_parser_accepts_only_indexed_tool_definition_errors():
    from tool_pipeline import parse_tool_definition_error

    parsed = parse_tool_definition_error(
        ValueError("HTTP 400 tools.7.custom.input_schema: JSON schema is invalid"),
        tool_count=8,
    )
    assert parsed is not None
    assert parsed.tool_index == 7
    assert parsed.field == "input_schema"
    assert parse_tool_definition_error(ValueError("HTTP 400 bad request"), tool_count=8) is None
    assert parse_tool_definition_error(ValueError("HTTP 400 tools.9.custom.name invalid"), tool_count=8) is None
    openai = parse_tool_definition_error(
        ValueError("HTTP 400 tools[3].function.parameters invalid"), tool_count=4
    )
    assert openai is not None and openai.field == "input_schema"


def test_plugin_connection_registers_safe_alias_and_unregisters_exact_alias():
    import shared
    from mcp.manager import _register, _unregister

    conn = {
        "id": "plugin:atlassian:atlassian",
        "name": "Atlassian",
        "cached_tools": [
            {"name": "get:Confluence Page", "description": "", "input_schema": {"type": "object"}}
        ],
    }
    _unregister(conn["id"])
    try:
        _register(conn)
        aliases = shared.SKILL_TOOLS_MAP[conn["id"]]
        assert len(aliases) == 1
        alias = next(iter(aliases))
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", alias)
        assert alias in shared.TOOL_DISPATCH
        assert alias in shared.TOOL_STATUS
    finally:
        _unregister(conn["id"])

    assert alias not in shared.TOOL_DISPATCH
    assert alias not in shared.TOOL_STATUS


def test_unregister_does_not_delete_another_connection_with_shared_prefix():
    import shared
    from mcp.manager import _register, _unregister

    first = {"id": "mcp-a", "name": "A", "cached_tools": []}
    second = {
        "id": "mcp-a__b", "name": "B",
        "cached_tools": [{"name": "search", "input_schema": {"type": "object"}}],
    }
    _unregister(first["id"])
    _unregister(second["id"])
    try:
        _register(first)
        _register(second)
        alias = next(iter(shared.SKILL_TOOLS_MAP[second["id"]]))
        _unregister(first["id"])
        assert alias in shared.TOOL_DISPATCH
    finally:
        _unregister(first["id"])
        _unregister(second["id"])


def test_registration_quarantines_non_string_tool_name():
    import shared
    from mcp.manager import _register, _unregister

    conn = {"id": "mcp-bad-name", "name": "Bad", "cached_tools": [
        {"name": ["not", "a", "string"], "input_schema": {"type": "object"}},
    ]}
    _unregister(conn["id"])
    try:
        _register(conn)
        assert shared.MCP_TOOL_DIAGNOSTICS[conn["id"]]["quarantined"] == 1
    finally:
        _unregister(conn["id"])


def test_registration_quarantines_unsupported_schema_without_disabling_connection():
    import shared
    from mcp.manager import _register, _unregister

    conn = {
        "id": "mcp-mixed",
        "name": "Mixed",
        "cached_tools": [
            {"name": "good", "description": "", "input_schema": {"type": "object"}},
            {
                "name": "bad",
                "description": "",
                "input_schema": {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "type": "array",
                    "items": [{"type": "string"}],
                },
            },
        ],
    }
    _unregister(conn["id"])
    try:
        _register(conn)
        assert len(shared.SKILL_TOOLS_MAP[conn["id"]]) == 1
        report = shared.MCP_TOOL_DIAGNOSTICS[conn["id"]]
        assert report["discovered"] == 2
        assert report["usable"] == 1
        assert report["quarantined"] == 1
        assert report["issues"][0]["tool"] == "bad"
    finally:
        _unregister(conn["id"])


def test_registration_quarantines_duplicate_raw_tool_names():
    import shared
    from mcp.manager import _register, _unregister

    conn = {
        "id": "mcp-duplicate",
        "name": "Duplicate",
        "cached_tools": [
            {"name": "search", "input_schema": {"type": "object"}},
            {"name": "search", "input_schema": {"type": "object"}},
        ],
    }
    _unregister(conn["id"])
    try:
        _register(conn)
        report = shared.MCP_TOOL_DIAGNOSTICS[conn["id"]]
        assert report["usable"] == 1
        assert report["quarantined"] == 1
        assert "duplicate" in report["issues"][0]["reason"]
    finally:
        _unregister(conn["id"])


def test_google_workspace_registration_creates_service_specific_tool_groups():
    import shared
    from mcp.manager import _register, _unregister

    conn = {
        "id": "mcp-google-workspace",
        "name": "Google Workspace",
        "cached_tools": [
            {"name": "search_gmail_messages", "description": "", "input_schema": {"type": "object"}},
            {"name": "search_drive_files", "description": "", "input_schema": {"type": "object"}},
            {"name": "list_calendars", "description": "", "input_schema": {"type": "object"}},
            {"name": "get_events", "description": "", "input_schema": {"type": "object"}},
            {"name": "query_freebusy", "description": "", "input_schema": {"type": "object"}},
            {"name": "manage_event", "description": "", "input_schema": {"type": "object"}},
            {"name": "search_custom", "description": "", "input_schema": {"type": "object"}},
            {"name": "start_google_auth", "description": "", "input_schema": {"type": "object"}},
        ],
    }
    _unregister(conn["id"])
    try:
        _register(conn)
        assert len(shared.SKILL_TOOLS_MAP["g-gmail"]) == 2
        assert len(shared.SKILL_TOOLS_MAP["g-drive"]) == 2
        assert len(shared.SKILL_TOOLS_MAP["g-calendar"]) == 5
        assert len(shared.SKILL_TOOLS_MAP["g-search"]) == 2
        overlap = shared.SKILL_TOOLS_MAP["g-gmail"] & shared.SKILL_TOOLS_MAP["g-drive"]
        assert len(overlap) == 1
        assert next(iter(overlap)).endswith("__start_google_auth")
    finally:
        _unregister(conn["id"])


def test_workspace_catalog_groups_cover_all_current_service_tools():
    from tool_pipeline import _GOOGLE_SERVICE_TOOLS, _GOOGLE_SHARED_TOOLS

    service_union = set().union(*_GOOGLE_SERVICE_TOOLS.values())
    assert len(service_union) == 120
    assert service_union | _GOOGLE_SHARED_TOOLS == service_union | {"start_google_auth"}
    assert len(service_union | _GOOGLE_SHARED_TOOLS) == 121
    assert "search_gmail_messages" in _GOOGLE_SERVICE_TOOLS["g-gmail"]
    assert "get_events" in _GOOGLE_SERVICE_TOOLS["g-calendar"]
    assert "search_custom" in _GOOGLE_SERVICE_TOOLS["g-search"]


def test_workspace_status_exposes_server_generated_service_counts(monkeypatch):
    import shared
    from mcp import manager
    from mcp.manager import _register, _unregister

    conn = {
        "id": "mcp-google-workspace", "name": "Google Workspace", "transport": "http",
        "enabled": True, "url": "https://example.test/mcp",
        "cached_tools": [
            {"name": "search_gmail_messages", "input_schema": {"type": "object"}},
            {"name": "get_events", "input_schema": {"type": "object"}},
        ],
    }
    _unregister(conn["id"])
    try:
        _register(conn)
        monkeypatch.setattr(manager, "_load_connections", lambda: [conn])
        row = manager.list_with_status()[0]
        assert row["service_tool_counts"]["g-gmail"] == 1
        assert row["service_tool_counts"]["g-calendar"] == 1
    finally:
        _unregister(conn["id"])


def test_google_service_id_is_recognized_as_workspace_activation():
    from tool_pipeline import is_google_workspace_service

    assert is_google_workspace_service("g-gmail")
    assert is_google_workspace_service("g-calendar")
    assert not is_google_workspace_service("gator")


def test_google_account_context_covers_single_and_midturn_google_service():
    from routes.chat import _append_google_account_context

    initial = _append_google_account_context("system", ["g-gmail"], "person@example.test")
    midturn = _append_google_account_context("system", ["g-calendar"], "person@example.test")
    assert "user_google_email" in initial
    assert "person@example.test" in initial
    assert "user_google_email" in midturn


def test_background_selected_google_skill_bypasses_builtin_direct_router():
    import app

    assert app._background_has_nonbuiltin_skills(["g-gmail"])
    assert app._background_has_nonbuiltin_skills(["mcp-rovo-mcp"])
    assert not app._background_has_nonbuiltin_skills(["email"])


def test_google_service_filter_does_not_load_entire_workspace(monkeypatch):
    import shared
    from mcp.manager import _register, _unregister
    from routes.chat import _filter_tools

    conn = {
        "id": "mcp-google-workspace",
        "name": "Google Workspace",
        "cached_tools": [
            {"name": "search_gmail_messages", "input_schema": {"type": "object"}},
            {"name": "search_drive_files", "input_schema": {"type": "object"}},
            {"name": "list_calendars", "input_schema": {"type": "object"}},
        ],
    }
    monkeypatch.setattr(shared, "_ALWAYS_ON_TOOLS", set())
    _unregister(conn["id"])
    try:
        _register(conn)
        selected = _filter_tools(None, False, ["g-gmail"])
        assert [tool["name"] for tool in selected] == list(shared.SKILL_TOOLS_MAP["g-gmail"])
        assert "drive" not in selected[0]["name"]
        assert "calendar" not in selected[0]["name"]
    finally:
        _unregister(conn["id"])


@pytest.mark.parametrize(
    ("code", "category", "terminal"),
    [
        ("not_authed", "authentication", True),
        ("token_revoked", "authentication", True),
        ("team_access_not_granted", "permission", True),
        ("rate_limited", "transient", False),
    ],
)
def test_tool_failure_classification_preserves_meaning(code, category, terminal):
    from tool_pipeline import classify_tool_failure

    outcome = classify_tool_failure({"error": code}, tool_name="slack_search_users")
    assert outcome is not None
    assert outcome.category == category
    assert outcome.terminal is terminal
    assert code not in outcome.user_message or category == "transient"


def test_google_auth_outcome_preserves_only_the_actionable_authorization_link():
    from tool_pipeline import classify_tool_failure

    result = {
        "error": "Google authentication required. internal detail",
        "_workspace_mcp_auth": True,
        "_auth_url": "https://accounts.google.com/o/oauth2/auth?client_id=abc&state=xyz",
    }
    outcome = classify_tool_failure(result, tool_name="mcp-google-workspace__gmail_search")
    assert outcome is not None and outcome.terminal
    assert "https://accounts.google.com/o/oauth2/auth?client_id=abc&state=xyz" in outcome.user_message
    assert "internal detail" not in outcome.user_message


def test_google_auth_link_is_not_trusted_without_workspace_connection_marker():
    from tool_pipeline import classify_tool_failure

    outcome = classify_tool_failure({
        "error": "Google authentication required",
        "_auth_url": "https://accounts.google.com/o/oauth2/auth?client_id=abc",
    })
    assert outcome is not None
    assert "https://accounts.google.com" not in outcome.user_message


def test_workspace_mcp_handler_retains_actionable_oauth_link(monkeypatch):
    import shared
    from mcp.manager import _register, _unregister

    conn = {
        "id": "mcp-google-workspace", "name": "Workspace", "transport": "stdio",
        "command": "uvx", "args": ["workspace-mcp"], "env": {},
        "cached_tools": [{"name": "search_gmail_messages", "input_schema": {"type": "object"}}],
    }
    _unregister(conn["id"])
    try:
        _register(conn)
        alias = next(iter(shared.SKILL_TOOLS_MAP[conn["id"]]))
        monkeypatch.setattr(
            "mcp.manager._client_for",
            lambda *_args, **_kwargs: type("Client", (), {
                "call": lambda *_: (_ for _ in ()).throw(RuntimeError(
                    "ACTION REQUIRED https://accounts.google.com/o/oauth2/auth?client_id=abc"
                )),
                "close": lambda *_: None,
            })(),
        )
        result = shared.TOOL_DISPATCH[alias]()
        assert result["_workspace_mcp_auth"] is True
        assert result["_auth_url"].startswith("https://accounts.google.com/o/oauth2/auth?")
    finally:
        _unregister(conn["id"])


def test_recognized_failure_is_sanitized_before_model_or_telemetry_use():
    from tool_pipeline import sanitize_tool_failure

    safe = sanitize_tool_failure({
        "error": "invalid_auth secret-token=do-not-leak",
        "result": "diagnostic body with another-secret",
    }, tool_name="slack_search_users")
    assert safe is not None
    assert safe["error"] == "invalid_auth"
    assert "secret" not in json.dumps(safe).lower()


def test_unknown_slack_error_with_result_is_replaced_by_safe_message():
    import app
    import shared

    def handler():
        return {"error": "private diagnostic secret=do-not-leak", "result": "also secret=do-not-leak"}

    shared.TOOL_DISPATCH["slack_sensitive_test"] = handler
    result = asyncio.run(app.execute_tool("slack_sensitive_test", {}))
    assert result == {"result": shared._SLACK_SAFE_MSG}


def test_single_agent_surfaces_terminal_tool_message_without_second_model_call():
    from agent_loop import _single_agent_loop

    class Provider:
        context_window = 200_000

        def __init__(self):
            self.calls = 0

        def normalize_tool_schema(self, tool):
            return tool

        async def stream_turn(self, model, system, messages, tools):
            self.calls += 1
            yield {
                "type": "done",
                "stop_reason": "tool_use",
                "tool_calls": [SimpleNamespace(name="slack_search_users", inputs={}, id="t1")],
                "raw_content": [],
                "usage": {},
            }

        def build_assistant_message(self, raw):
            return {"role": "assistant", "content": raw}

        def build_tool_result_message(self, calls, results):
            return {"role": "user", "content": json.dumps(results)}

    async def execute_tool(name, inputs):
        return {"error": "team_access_not_granted"}

    async def collect():
        provider = Provider()
        chunks = []
        async for chunk in _single_agent_loop(
            provider, "model", "system", [{"role": "user", "content": "find Ada"}],
            [{"name": "slack_search_users", "description": "", "input_schema": {"type": "object"}}],
            execute_tool, set(), {}, lambda *_: None, "safe",
        ):
            chunks.append(chunk)
        return provider, chunks

    provider, chunks = asyncio.run(collect())
    assert provider.calls == 1
    assert any("Slack workspace" in chunk for chunk in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


def test_single_agent_terminal_workspace_auth_surfaces_validated_link_only():
    from agent_loop import _single_agent_loop

    class Provider:
        context_window = 200_000

        def __init__(self):
            self.calls = 0

        def normalize_tool_schema(self, tool):
            return tool

        async def stream_turn(self, model, system, messages, tools):
            self.calls += 1
            yield {
                "type": "done", "stop_reason": "tool_use",
                "tool_calls": [SimpleNamespace(name="mcp-google-workspace__search", inputs={}, id="t1")],
                "raw_content": [], "usage": {},
            }

        def build_assistant_message(self, raw):
            return {"role": "assistant", "content": raw}

        def build_tool_result_message(self, calls, results):
            return {"role": "user", "content": json.dumps(results)}

    async def execute_tool(name, inputs):
        return {
            "error": "Google authentication required. internal diagnostic",
            "_workspace_mcp_auth": True,
            "_auth_url": "https://accounts.google.com/o/oauth2/auth?client_id=abc",
        }

    async def collect():
        provider = Provider()
        chunks = []
        async for chunk in _single_agent_loop(
            provider, "model", "system", [{"role": "user", "content": "search"}],
            [{"name": "mcp-google-workspace__search", "input_schema": {"type": "object"}}],
            execute_tool, set(), {}, lambda *_: None, "safe",
        ):
            chunks.append(chunk)
        return provider, chunks

    provider, chunks = asyncio.run(collect())
    text = "".join(chunks)
    assert provider.calls == 1
    assert "https://accounts.google.com/o/oauth2/auth?client_id=abc" in text
    assert "internal diagnostic" not in text


def test_single_agent_drops_exact_rejected_tool_and_retries_once():
    from agent_loop import _single_agent_loop
    from tool_pipeline import ToolDefinitionError

    class Provider:
        context_window = 200_000

        def __init__(self):
            self.requests = []

        def normalize_tool_schema(self, tool):
            return tool

        async def stream_turn(self, model, system, messages, tools):
            self.requests.append([tool["name"] for tool in tools])
            if len(self.requests) == 1:
                raise ToolDefinitionError("gateway rejected name", tool_index=1, field="name")
            yield {
                "type": "done", "stop_reason": "end_turn", "tool_calls": [],
                "raw_content": [], "usage": {},
            }

        def build_assistant_message(self, raw):
            return {"role": "assistant", "content": raw}

    async def collect():
        provider = Provider()
        chunks = []
        tools = [
            {"name": "first", "input_schema": {"type": "object"}},
            {"name": "second", "input_schema": {"type": "object"}},
        ]
        async for chunk in _single_agent_loop(
            provider, "model", "system", [{"role": "user", "content": "go"}],
            tools, lambda *_: None, set(), {}, lambda *_: None, "safe",
        ):
            chunks.append(chunk)
        return provider, chunks

    provider, chunks = asyncio.run(collect())
    assert provider.requests == [["first", "second"], ["first"]]
    assert any("quarantined" in chunk and "second" in chunk for chunk in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


def test_gateway_rejection_after_thinking_does_not_retry_request():
    from agent_loop import _single_agent_loop
    from tool_pipeline import ToolDefinitionError

    class Provider:
        context_window = 200_000

        def __init__(self):
            self.calls = 0

        def normalize_tool_schema(self, tool):
            return tool

        async def stream_turn(self, model, system, messages, tools):
            self.calls += 1
            yield {"type": "thinking_delta", "text": "reasoning"}
            raise ToolDefinitionError("gateway rejected name", tool_index=0, field="name")

    async def collect():
        provider = Provider()
        chunks = []
        async for chunk in _single_agent_loop(
            provider, "model", "system", [{"role": "user", "content": "go"}],
            [{"name": "first", "input_schema": {"type": "object"}}],
            lambda *_: None, set(), {}, lambda *_: None, "safe",
        ):
            chunks.append(chunk)
        return provider, chunks

    provider, chunks = asyncio.run(collect())
    assert provider.calls == 1
    assert not any("quarantined" in chunk for chunk in chunks)


def test_mixed_parallel_results_do_not_force_terminal_abort():
    from agent_loop import _terminal_tool_failure

    terminal = {
        "error": "team_access_not_granted",
        "_tool_outcome": {"terminal": True, "user_message": "Reconnect Slack."},
    }
    assert _terminal_tool_failure([terminal, {"result": "useful"}]) is None


def test_terminal_plus_retryable_failure_does_not_force_terminal_abort():
    from agent_loop import _terminal_tool_failure

    terminal = {"error": "not_authed", "_tool_outcome": {"terminal": True, "retryable": False}}
    transient = {"error": "rate_limited", "_tool_outcome": {"terminal": False, "retryable": True}}
    assert _terminal_tool_failure([terminal, transient]) is None


def test_three_agent_surfaces_terminal_tool_message_without_verifier_call():
    from agent_loop import run_three_agent_loop

    class Provider:
        context_window = 200_000

        def __init__(self):
            self.calls = 0

        def normalize_tool_schema(self, tool):
            return tool

        async def stream_turn(self, model, system, messages, tools):
            self.calls += 1
            if self.calls == 1:
                yield {
                    "type": "text_delta", "text": "Use Slack.",
                }
                yield {
                    "type": "done", "stop_reason": "end_turn", "tool_calls": [],
                    "raw_content": [], "usage": {},
                }
                return
            yield {
                "type": "done", "stop_reason": "tool_use",
                "tool_calls": [SimpleNamespace(name="slack_search_users", inputs={}, id="t1")],
                "raw_content": [], "usage": {},
            }

        def build_assistant_message(self, raw):
            return {"role": "assistant", "content": raw}

        def build_tool_result_message(self, calls, results):
            return {"role": "user", "content": json.dumps(results)}

    async def execute_tool(name, inputs):
        return {"error": "team_access_not_granted"}

    async def collect():
        provider = Provider()
        chunks = []
        async for chunk in run_three_agent_loop(
            provider, "model", "system", [{"role": "user", "content": "find Ada"}],
            [{"name": "slack_search_users", "description": "", "input_schema": {"type": "object"}}],
            execute_tool, set(), {}, lambda *_: None, "safe", token_budget=0,
        ):
            chunks.append(chunk)
        return provider, chunks

    provider, chunks = asyncio.run(collect())
    assert provider.calls == 2
    assert any("Slack workspace" in chunk for chunk in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"


def test_connections_status_exposes_compatibility_counts(monkeypatch):
    from mcp import manager

    conn = {
        "id": "mcp-mixed",
        "name": "Mixed",
        "transport": "http",
        "enabled": True,
        "url": "https://example.test/mcp",
        "cached_tools": [
            {"name": "good", "input_schema": {"type": "object"}},
            {"name": "bad", "input_schema": {"type": "array", "items": [{"type": "string"}]}},
        ],
    }
    monkeypatch.setattr(manager, "_load_connections", lambda: [conn])
    rows = manager.list_with_status()
    assert rows[0]["tool_compatibility"]["discovered"] == 2
    assert rows[0]["tool_compatibility"]["usable"] == 1
    assert rows[0]["tool_compatibility"]["quarantined"] == 1


def test_connection_status_bounds_issues_and_tolerates_malformed_cached_tools(monkeypatch):
    from mcp import manager

    conn = {
        "id": "mcp-malformed", "name": "Malformed", "transport": "http", "enabled": True,
        "url": "https://example.test/mcp",
        "cached_tools": [None] * 12,
    }
    monkeypatch.setattr(manager, "_load_connections", lambda: [conn])
    rows = manager.list_with_status()
    report = rows[0]["tool_compatibility"]
    assert report["quarantined"] == 12
    assert len(report["issues"]) == 10
    assert report["omitted_issues"] == 2
    assert rows[0]["tools"] == []


def test_connections_ui_renders_quarantine_warning():
    from pathlib import Path

    source = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "tool_compatibility" in source
    assert "quarantined" in source
    assert "service_tool_counts" in source
    installer_source = Path("web/static/marketplace-pane.js").read_text(encoding="utf-8")
    assert "mcp_compatibility_warnings" in installer_source
    assert "incompatible MCP tool" in installer_source
