"""A model-side safety refusal (stop_reason 'refusal', no text) must not look like a silent turn."""

import asyncio
import json

import app  # noqa: F401 — populates registries
import agent_loop


class _StubProvider:
    def __init__(self, stop_reason, text):
        self._stop_reason = stop_reason
        self._text = text

    async def stream_turn(self, model, system, msgs, tools):
        if self._text:
            yield {"type": "text_delta", "text": self._text}
        yield {
            "type": "done",
            "stop_reason": self._stop_reason,
            "text": self._text,
            "usage": {"input_tokens": 5, "output_tokens": 0},
            "tool_calls": [],
            "raw_content": [{"type": "text", "text": self._text}] if self._text else [],
        }

    def build_assistant_message(self, raw_content):
        return {"role": "assistant", "content": raw_content}


def _run(provider):
    async def go():
        out = []
        async for chunk in agent_loop._single_agent_loop(
            provider, "claude-sonnet-5", "sys", [{"role": "user", "content": "hi"}], [],
            lambda *a, **k: {}, set(), {}, lambda *a, **k: None, "safe",
        ):
            if chunk.startswith("data: {"):
                out.append(json.loads(chunk[6:]))
        return out

    return asyncio.run(go())


def _tokens(events):
    return [e["token"] for e in events if "token" in e]


def test_a_refusal_with_no_text_tells_the_user():
    tokens = _tokens(_run(_StubProvider("refusal", "")))
    assert len(tokens) == 1 and "declined" in tokens[0]


def test_a_normal_empty_end_turn_adds_nothing():
    assert _tokens(_run(_StubProvider("end_turn", ""))) == []


def test_a_refusal_that_has_text_is_not_doubled():
    tokens = _tokens(_run(_StubProvider("refusal", "I can't help with that.")))
    assert tokens == ["I can't help with that."]
