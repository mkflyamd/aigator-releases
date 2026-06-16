import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock

GATEWAY_PROFILE = {
    "id": "gw", "name": "GW", "type": "gateway",
    "base_url": "https://llm-api.test.com/Unified",
    "api_key": "testkey", "api_key_header": "Ocp-Apim-Subscription-Key",
    "user_id": "jsmith", "models": [], "active_model": "",
}

V1_PROFILE = {
    **GATEWAY_PROFILE,
    "base_url": "https://llm-api.test.com/Unified/v1",
}


def test_normalize_tool_schema():
    from web.llm.openai_provider import OpenAIProvider
    with patch("web.llm.openai_provider.OpenAI"):
        provider = OpenAIProvider(GATEWAY_PROFILE)
    tool = {"name": "search", "description": "Search", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}
    result = provider.normalize_tool_schema(tool)
    assert result["type"] == "function"
    assert result["function"]["name"] == "search"
    assert result["function"]["parameters"] == tool["input_schema"]


def test_build_tool_result_message():
    from web.llm.openai_provider import OpenAIProvider
    from web.llm.base import ToolCall
    with patch("web.llm.openai_provider.OpenAI"):
        provider = OpenAIProvider(GATEWAY_PROFILE)
    tc = ToolCall(id="call_abc", name="search", inputs={"q": "bug"})
    msgs = provider.build_tool_result_message([tc], [{"issues": ["PROJ-1"]}])
    assert isinstance(msgs, list)
    assert len(msgs) == 1
    assert msgs[0]["role"] == "tool"
    assert msgs[0]["tool_call_id"] == "call_abc"
    assert "PROJ-1" in msgs[0]["content"]


def test_build_tool_result_message_empty_raises():
    """Empty tool_calls must raise ValueError, not return a malformed message."""
    from web.llm.openai_provider import OpenAIProvider
    with patch("web.llm.openai_provider.OpenAI"):
        provider = OpenAIProvider(GATEWAY_PROFILE)
    with pytest.raises(ValueError):
        provider.build_tool_result_message([], [])


def test_client_uses_profile_base_url():
    from web.llm.openai_provider import OpenAIProvider
    with patch("web.llm.openai_provider.OpenAI") as mock_openai:
        OpenAIProvider(GATEWAY_PROFILE)
    kwargs = mock_openai.call_args[1]
    assert "llm-api.test.com" in kwargs["base_url"]
    assert kwargs["default_headers"]["Ocp-Apim-Subscription-Key"] == "testkey"


def test_base_url_no_double_v1():
    """base_url already ending in /v1 must not produce /v1/v1."""
    from web.llm.openai_provider import OpenAIProvider
    with patch("web.llm.openai_provider.OpenAI") as mock_openai:
        OpenAIProvider(V1_PROFILE)
    kwargs = mock_openai.call_args[1]
    url = kwargs["base_url"]
    assert url.endswith("/v1"), f"Expected /v1 suffix, got: {url}"
    assert "/v1/v1" not in url, f"Double /v1 detected: {url}"


def _make_chunk(content=None, tool_calls=None, finish_reason=None, usage=None):
    """Build a minimal mock OpenAI streaming chunk."""
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason
    chunk = MagicMock()
    chunk.choices = [choice]
    chunk.usage = usage
    return chunk


def _run_stream_turn(provider, chunks):
    """Collect all events from stream_turn using mocked streaming chunks."""
    ctx_manager = MagicMock()
    ctx_manager.__enter__ = MagicMock(return_value=iter(chunks))
    ctx_manager.__exit__ = MagicMock(return_value=False)
    provider._client.chat.completions.create.return_value = ctx_manager

    async def _collect():
        events = []
        async for event in provider.stream_turn("m", "sys", [], []):
            events.append(event)
        return events

    return asyncio.get_event_loop().run_until_complete(_collect())


def test_raw_content_text_only():
    """Text-only turn: raw_content must be a single assistant message dict."""
    from web.llm.openai_provider import OpenAIProvider
    with patch("web.llm.openai_provider.OpenAI"):
        provider = OpenAIProvider(GATEWAY_PROFILE)

    chunks = [
        _make_chunk(content="Hello"),
        _make_chunk(content=" world", finish_reason="stop"),
    ]
    events = _run_stream_turn(provider, chunks)
    done = next(e for e in events if e["type"] == "done")

    assert isinstance(done["raw_content"], dict)
    assert done["raw_content"]["role"] == "assistant"
    assert done["raw_content"]["content"] == "Hello world"


def test_raw_content_tool_call():
    """Tool-use turn: raw_content must include tool_calls in OpenAI wire format."""
    from web.llm.openai_provider import OpenAIProvider
    with patch("web.llm.openai_provider.OpenAI"):
        provider = OpenAIProvider(GATEWAY_PROFILE)

    tc_delta_1 = MagicMock()
    tc_delta_1.index = 0
    tc_delta_1.id = "call_xyz"
    tc_delta_1.function = MagicMock()
    tc_delta_1.function.name = "search"
    tc_delta_1.function.arguments = '{"q": "test"}'

    tc_delta_2 = MagicMock()
    tc_delta_2.index = 0
    tc_delta_2.id = None
    tc_delta_2.function = MagicMock()
    tc_delta_2.function.name = None
    tc_delta_2.function.arguments = None

    chunks = [
        _make_chunk(tool_calls=[tc_delta_1]),
        _make_chunk(tool_calls=[tc_delta_2], finish_reason="tool_calls"),
    ]
    events = _run_stream_turn(provider, chunks)
    done = next(e for e in events if e["type"] == "done")

    assert done["stop_reason"] == "tool_use"
    msg = done["raw_content"]
    assert isinstance(msg, dict)
    assert msg["role"] == "assistant"
    assert msg["content"] is None
    assert len(msg["tool_calls"]) == 1
    tc = msg["tool_calls"][0]
    assert tc["id"] == "call_xyz"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "search"
    assert tc["function"]["arguments"] == '{"q": "test"}'
