import asyncio
import json

import anthropic
import httpx
import pytest

from skills._always_on import tools

REJECTION = json.dumps(
    {"type": "error", "error": {"type": "invalid_request_error",
     "message": 'tool_choice: type "tool" and "any" are not supported for this model.'}}
)
PROFILE = {"api_key": "aigator-fake-api-key", "anthropic_url": "http://gateway.invalid"}


@pytest.fixture
def frame(tmp_path):
    p = tmp_path / "frame.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return str(p)


@pytest.fixture(autouse=True)
def _profile(monkeypatch):
    monkeypatch.setattr("llm.registry.get_active_profile", lambda: PROFILE)
    monkeypatch.setattr("llm.registry.get_active_model", lambda: "test-model")
    monkeypatch.setattr("llm.gateway.profile_headers", lambda profile: {})


def _fake_async_client(responses, seen):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            seen.append(dict(json["tool_choice"]))
            return responses.pop(0)

    return _Client


def _tool_use_reply():
    body = {"content": [{"type": "tool_use", "name": "analyze_frames",
                         "input": {"frames": [{"frame": "frame.png", "description": "x"}], "summary": "s"}}]}
    return httpx.Response(200, json=body)


def test_sequence_retries_with_auto_when_forced_tool_choice_rejected(monkeypatch, frame):
    seen = []
    responses = [httpx.Response(400, text=REJECTION), _tool_use_reply()]
    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client(responses, seen))
    result = asyncio.run(tools._analyze_frame_sequence([frame]))
    assert result["ok"] is True and result["summary"] == "s"
    assert seen == [{"type": "tool", "name": "analyze_frames"}, {"type": "auto"}]


def test_sequence_does_not_retry_other_errors(monkeypatch, frame):
    seen = []
    body = '{"error":{"code":"api_not_supported"}}'
    monkeypatch.setattr(httpx, "AsyncClient", _fake_async_client([httpx.Response(404, text=body)], seen))
    result = asyncio.run(tools._analyze_frame_sequence([frame]))
    assert result["ok"] is False
    assert "does not support image input" in result["error"]
    assert len(seen) == 1


def _fake_anthropic(calls, outcomes):
    class _Messages:
        def create(self, **kw):
            calls.append(kw["tool_choice"])
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    return _Client


def _bad_request(message):
    resp = httpx.Response(400, request=httpx.Request("POST", "http://gateway.invalid"))
    return anthropic.BadRequestError(message, response=resp, body=None)


def test_extract_fields_retries_with_auto_when_forced_tool_choice_rejected(monkeypatch, frame):
    block = type("B", (), {"type": "tool_use", "name": "extract_fields", "input": {"fee": "10"}})()
    reply = type("M", (), {"content": [block]})()
    calls = []
    outcomes = [_bad_request("tool_choice: type 'tool' is not supported"), reply]
    monkeypatch.setattr(anthropic, "Anthropic", _fake_anthropic(calls, outcomes))
    result = tools._extract_structured_fields([frame], ["fee"])
    assert result == {"ok": True, "task": "extract_data", "extracted": {"fee": "10"}}
    assert calls == [{"type": "tool", "name": "extract_fields"}, {"type": "auto"}]


def test_extract_fields_does_not_retry_unrelated_bad_request(monkeypatch, frame):
    calls = []
    monkeypatch.setattr(anthropic, "Anthropic", _fake_anthropic(calls, [_bad_request("prompt too long")]))
    assert tools._extract_structured_fields([frame], ["fee"]) is None
    assert len(calls) == 1
