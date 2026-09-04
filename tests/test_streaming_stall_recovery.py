"""Tests for streaming stall recovery fixes (issue #42).

Covers:
1. idle-timeout path emits `stalled` SSE event (not plain text) + [DONE]
2. circuit breaker fires on bad_tool_streak >= 1 at the START of the next iteration
3. tool result truncation caps large results before they enter history
4. assistant message history truncation stubs large responses
"""

import asyncio
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sse_events(chunks: list[str]) -> list[dict]:
    """Parse SSE chunks into event dicts, skipping [DONE] and non-data lines."""
    events = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.startswith("data: ") and line != "data: [DONE]":
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
    return events


def _has_done(chunks: list[str]) -> bool:
    return any("data: [DONE]" in c for c in chunks)


def _collect_loop(coro_gen):
    """Collect all chunks from an async generator into a list."""
    async def _go():
        return [chunk async for chunk in coro_gen]
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_go())
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


# ── P0-1/Gap2: circuit breaker pre-empts next LLM call when bad_tool_streak >= 1 ──

def test_circuit_breaker_fires_on_streak_1_before_second_llm_call():
    """After one all-bad tool round, the loop must emit stalled + [DONE] at the
    START of the next iteration without making another LLM call."""
    from types import SimpleNamespace
    from agent_loop import _single_agent_loop

    llm_call_count = 0

    class FakeProvider:
        context_window = 200_000
        max_tools = 128
        max_tool_name_length = 64

        async def stream_turn(self, model, system, msgs, tools):
            nonlocal llm_call_count
            llm_call_count += 1
            if llm_call_count == 1:
                yield {"type": "done", "stop_reason": "tool_use", "raw_content": [],
                       "tool_calls": [SimpleNamespace(name="run_python", inputs={}, id="tc1")],
                       "usage": {"input_tokens": 10, "output_tokens": 5}}
            else:
                # Should never be reached — circuit breaker should fire first
                yield {"type": "text_delta", "text": "unexpected second call"}
                yield {"type": "done", "stop_reason": "end_turn", "raw_content": [],
                       "tool_calls": [], "usage": {"input_tokens": 10, "output_tokens": 5}}

        def normalize_tool_schema(self, t):
            return t

        def build_assistant_message(self, raw):
            return {"role": "assistant", "content": ""}

        def build_tool_result_message(self, tool_calls, results):
            return {"role": "user", "content": []}

    async def bad_execute(name, inputs, **kw):
        return {"error": "missing_required_params", "tool": name, "missing": ["code"]}

    provider = FakeProvider()
    msgs = [{"role": "user", "content": "test"}]

    chunks = _collect_loop(_single_agent_loop(
        provider=provider, model="test-model", system="sys",
        msgs=msgs, normalized_tools=[{"name": "run_python", "input_schema": {}}],
        execute_tool=bad_execute,
        COM_BOUND_TOOLS=set(), TOOL_STATUS={}, _tool_toast=lambda n, r: None,
        _SLACK_SAFE_MSG="",
    ))

    events = _sse_events(chunks)
    stalled = [e for e in events if e.get("stalled")]
    assert stalled, f"Expected stalled event, got events: {events}"
    assert _has_done(chunks), "Expected [DONE] after stalled event"
    assert llm_call_count == 1, f"LLM called {llm_call_count} times, expected 1 (circuit breaker should stop at 2nd)"


# ── P0-2: Tool result truncation ─────────────────────────────────────────────

import pytest

@pytest.fixture(autouse=False)
def isolated_outputs_dir(tmp_path, monkeypatch):
    """Redirect tool_result_truncation to a temp dir so tests don't write to ~/.gator/outputs."""
    import tool_result_truncation as _trt
    monkeypatch.setattr(_trt, "_outputs_dir", lambda: tmp_path)
    return tmp_path


def test_tool_result_truncation_caps_large_result(isolated_outputs_dir):
    from tool_result_truncation import truncate_tool_result, MAX_TOOL_RESULT_BYTES

    large = "x" * (MAX_TOOL_RESULT_BYTES + 1000)
    result = {"result": large, "ok": True}
    truncated = truncate_tool_result(result, tool_name="browser_navigate")

    assert isinstance(truncated, dict)
    assert len(truncated["result"].encode("utf-8")) < MAX_TOOL_RESULT_BYTES
    assert "truncated" in truncated["result"]
    assert "Full output saved to" in truncated["result"]


def test_tool_result_truncation_preserves_small_result(isolated_outputs_dir):
    from tool_result_truncation import truncate_tool_result

    small = {"result": "hello world", "ok": True}
    out = truncate_tool_result(small, tool_name="browser_search")
    assert out == small


def test_tool_result_truncation_caps_content_array(isolated_outputs_dir):
    from tool_result_truncation import truncate_tool_result, MAX_TOOL_RESULT_BYTES

    large = "y" * (MAX_TOOL_RESULT_BYTES + 500)
    result = {"content": [{"type": "text", "text": large}]}
    out = truncate_tool_result(result, tool_name="confluence_get_page")

    assert isinstance(out, dict)
    blocks = out.get("content", [])
    assert blocks
    assert len(blocks[0]["text"].encode("utf-8")) < MAX_TOOL_RESULT_BYTES
    assert "truncated" in blocks[0]["text"]


def test_tool_result_truncation_ignores_error_results(isolated_outputs_dir):
    from tool_result_truncation import truncate_tool_result

    err = {"error": "missing_required_params", "tool": "run_python", "missing": ["code"]}
    out = truncate_tool_result(err, tool_name="run_python")
    assert out == err


def test_tool_result_truncation_handles_string_result(isolated_outputs_dir):
    """execute_tool returns raw strings from some tools — they must be truncated too."""
    from tool_result_truncation import maybe_truncate_json_result, MAX_TOOL_RESULT_BYTES

    large = "z" * (MAX_TOOL_RESULT_BYTES + 500)
    out = maybe_truncate_json_result(large, tool_name="some_tool")
    assert isinstance(out, str)
    assert len(out.encode("utf-8")) < MAX_TOOL_RESULT_BYTES
    assert "truncated" in out
    assert "Full output saved to" in out


def test_tool_result_truncation_preserves_small_string(isolated_outputs_dir):
    from tool_result_truncation import maybe_truncate_json_result

    small = "hello"
    assert maybe_truncate_json_result(small, tool_name="some_tool") == small


def test_tool_result_truncation_returns_original_on_write_failure(tmp_path, monkeypatch):
    """If the overflow dir can't be created, the original result is returned unchanged."""
    import tool_result_truncation as _trt
    # Point to a path that can't be created (file exists where dir should be)
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setattr(_trt, "_outputs_dir", lambda: blocker / "subdir")

    from tool_result_truncation import truncate_tool_result, MAX_TOOL_RESULT_BYTES
    large = "z" * (MAX_TOOL_RESULT_BYTES + 100)
    result = {"result": large}
    out = truncate_tool_result(result, tool_name="test_tool")
    # Should return original unchanged, not raise
    assert out == result


# ── P0-3: Assistant message history truncation ───────────────────────────────

def test_bare_html_doc_stubbed_in_history():
    from conversation_store import _truncate_large_assistant_messages

    html = "<!DOCTYPE html>\n<html><head><title>Test</title></head><body><p>Hi</p></body></html>"
    msgs = [
        {"role": "user", "content": "make me an ELI5"},
        {"role": "assistant", "content": html},
        {"role": "user", "content": "next file"},
    ]
    out = _truncate_large_assistant_messages(msgs)

    assert len(out) == 3
    assert out[0] == msgs[0]
    assert out[2] == msgs[2]
    asst = out[1]["content"]
    assert isinstance(asst, str)
    assert "HTML document rendered" in asst
    assert "widget" in asst.lower()
    assert "<!DOCTYPE" not in asst


def test_fenced_html_widget_stubbed_in_history():
    from conversation_store import _truncate_large_assistant_messages

    html = "```html\n<!DOCTYPE html>\n<html><body><h1>Hello</h1></body></html>\n```"
    msgs = [{"role": "assistant", "content": html}]
    out = _truncate_large_assistant_messages(msgs)
    assert "HTML widget rendered" in out[0]["content"]
    assert "```html" not in out[0]["content"]


def test_large_code_block_stubbed_in_history():
    from conversation_store import _truncate_large_assistant_messages, MAX_ASSISTANT_MSG_BYTES

    large_code = "```python\n" + "x = 1\n" * 2000 + "```"
    assert len(large_code.encode("utf-8")) > MAX_ASSISTANT_MSG_BYTES
    msgs = [{"role": "assistant", "content": large_code}]
    out = _truncate_large_assistant_messages(msgs)
    assert "Large code/output rendered" in out[0]["content"]


def test_small_assistant_message_preserved_in_history():
    from conversation_store import _truncate_large_assistant_messages

    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "short response"},
    ]
    out = _truncate_large_assistant_messages(msgs)
    assert out == msgs


def test_markdown_prose_not_stubbed():
    from conversation_store import _truncate_large_assistant_messages

    prose = "Here is a summary:\n\n- Point 1\n- Point 2\n- Point 3\n\nConclusion: done."
    msgs = [{"role": "assistant", "content": prose}]
    out = _truncate_large_assistant_messages(msgs)
    assert out == msgs


def test_non_assistant_messages_unaffected():
    from conversation_store import _truncate_large_assistant_messages

    html = "<!DOCTYPE html><html><body></body></html>"
    msgs = [{"role": "user", "content": html}]
    out = _truncate_large_assistant_messages(msgs)
    assert out == msgs


# ── P1-1: Browser auth-wall detection ────────────────────────────────────────

def test_browser_auth_wall_detected_from_sign_in_content():
    from skills.browser.tools import _check_auth_wall

    result = {"result": "Sign in to your account to continue. Please log in."}
    err = _check_auth_wall(result)
    assert err is not None
    assert err.get("error") == "auth_wall"
    assert "hint" in err


def test_browser_auth_wall_not_triggered_on_normal_content():
    from skills.browser.tools import _check_auth_wall

    result = {"result": "Welcome to the homepage. Latest news and updates."}
    err = _check_auth_wall(result)
    assert err is None


def test_browser_empty_result_circuit_breaker():
    """_apply_browser_empty_breaker fires after _BROWSER_EMPTY_STREAK_LIMIT empty results
    for the same (context_id, url) key."""
    from app import _apply_browser_empty_breaker, _BROWSER_EMPTY_STORE, _BROWSER_EMPTY_STREAK_LIMIT

    ctx = "ctx-test-" + str(id(object()))
    url = "https://example.com/test-cb-" + str(id(object()))
    _BROWSER_EMPTY_STORE.pop((ctx, url), None)

    result = {"result": ""}
    for i in range(_BROWSER_EMPTY_STREAK_LIMIT - 1):
        out = _apply_browser_empty_breaker(result, tool_name="browser_navigate", url_key=url, context_id=ctx)
        assert out.get("error") != "empty_result", f"Should not fire before limit, iteration {i}"

    out = _apply_browser_empty_breaker(result, tool_name="browser_navigate", url_key=url, context_id=ctx)
    assert out.get("error") == "empty_result"
    assert (ctx, url) not in _BROWSER_EMPTY_STORE


def test_browser_non_empty_resets_streak():
    from app import _apply_browser_empty_breaker, _BROWSER_EMPTY_STORE

    ctx = "ctx-reset-" + str(id(object()))
    url = "https://example.com/test-reset-" + str(id(object()))
    import time as _t
    _BROWSER_EMPTY_STORE[(ctx, url)] = (1, _t.monotonic())

    out = _apply_browser_empty_breaker({"result": "some content"}, tool_name="browser_navigate", url_key=url, context_id=ctx)
    assert out.get("error") != "empty_result"
    assert (ctx, url) not in _BROWSER_EMPTY_STORE


def test_auth_wall_not_overwritten_by_empty_result_breaker():
    """Two auth_wall responses in the same context must both remain auth_wall.
    The circuit breaker must never replace a structured error with empty_result."""
    from app import _apply_browser_empty_breaker, _BROWSER_EMPTY_STORE

    ctx = "ctx-authwall-" + str(id(object()))
    url = "https://example.com/sso-" + str(id(object()))
    _BROWSER_EMPTY_STORE.pop((ctx, url), None)

    auth_wall = {"error": "auth_wall", "hint": "Sign in first."}

    first = _apply_browser_empty_breaker(auth_wall, tool_name="browser_navigate", url_key=url, context_id=ctx)
    assert first.get("error") == "auth_wall", f"First call must preserve auth_wall: {first}"
    assert (ctx, url) not in _BROWSER_EMPTY_STORE, "auth_wall must not increment the streak"

    second = _apply_browser_empty_breaker(auth_wall, tool_name="browser_navigate", url_key=url, context_id=ctx)
    assert second.get("error") == "auth_wall", f"Second call must still be auth_wall, not empty_result: {second}"


def test_browser_streak_is_context_scoped():
    """Two different contexts navigating the same URL must not share a count."""
    from app import _apply_browser_empty_breaker, _BROWSER_EMPTY_STORE, _BROWSER_EMPTY_STREAK_LIMIT

    url = "https://example.com/shared-url-" + str(id(object()))
    ctx_a = "ctx-a-" + str(id(object()))
    ctx_b = "ctx-b-" + str(id(object()))
    _BROWSER_EMPTY_STORE.pop((ctx_a, url), None)
    _BROWSER_EMPTY_STORE.pop((ctx_b, url), None)

    result = {"result": ""}
    # ctx_a gets one empty result (streak = 1, below limit)
    _apply_browser_empty_breaker(result, tool_name="browser_navigate", url_key=url, context_id=ctx_a)
    assert _BROWSER_EMPTY_STORE.get((ctx_a, url), (0,))[0] == 1

    # ctx_b should start at 0, not inherit ctx_a's count
    assert _BROWSER_EMPTY_STORE.get((ctx_b, url), (0,))[0] == 0
    out_b = _apply_browser_empty_breaker(result, tool_name="browser_navigate", url_key=url, context_id=ctx_b)
    assert out_b.get("error") != "empty_result", "ctx_b should not trip on its first attempt"
    assert _BROWSER_EMPTY_STORE.get((ctx_b, url), (0,))[0] == 1


@pytest.mark.asyncio
async def test_browser_execute_tool_fires_circuit_breaker(monkeypatch):
    """Integration test: execute_tool called twice for browser_navigate with the same
    context_id and URL, returning empty results, fires the circuit breaker on attempt 2.
    A different context_id starts at attempt 1, not attempt 2.

    Registers a fake browser_navigate handler in shared.TOOL_DISPATCH so execute_tool
    can dispatch normally without requiring a full skill/server bootstrap.
    """
    import shared
    from app import execute_tool, _BROWSER_EMPTY_STORE

    url = "https://example.com/exec-cb-" + str(id(object()))
    ctx_a = "ctx-exec-a-" + str(id(object()))
    ctx_b = "ctx-exec-b-" + str(id(object()))
    for ctx in (ctx_a, ctx_b):
        _BROWSER_EMPTY_STORE.pop((ctx, url), None)

    async def _fake_browser_navigate(url, extract_content="main text content"):
        return {"ok": True, "result": ""}

    monkeypatch.setitem(shared.TOOL_DISPATCH, "browser_navigate", _fake_browser_navigate)

    try:
        # ctx_a: first call — no error
        r1 = await execute_tool("browser_navigate", {"url": url}, context_id=ctx_a)
        assert r1.get("error") != "empty_result", f"ctx_a attempt 1 should not trip: {r1}"

        # ctx_a: second call — circuit breaker fires
        r2 = await execute_tool("browser_navigate", {"url": url}, context_id=ctx_a)
        assert r2.get("error") == "empty_result", f"ctx_a attempt 2 should trip: {r2}"

        # ctx_b: first call — must NOT trip (different context, fresh count)
        r3 = await execute_tool("browser_navigate", {"url": url}, context_id=ctx_b)
        assert r3.get("error") != "empty_result", f"ctx_b attempt 1 should not trip: {r3}"
    finally:
        for ctx in (ctx_a, ctx_b):
            _BROWSER_EMPTY_STORE.pop((ctx, url), None)
