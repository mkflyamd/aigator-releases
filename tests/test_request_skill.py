"""A model that needs a skill it was not given asks for it with request_skill. Runners need the user's approval."""

import asyncio
import json
import pathlib
import sys
import uuid
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web"))

import app  # noqa: E402,F401
import browser_agent  # noqa: E402
import data_sources  # noqa: E402
import pytest  # noqa: E402
import shared  # noqa: E402
from agent_loop import _single_agent_loop  # noqa: E402
from routes import chat as chat_routes  # noqa: E402


class _Provider:
    context_window = 200_000

    def __init__(self, turns):
        self._turns = turns
        self.tools_seen = []
        self.results = []

    def normalize_tool_schema(self, t):
        return t

    def build_assistant_message(self, raw):
        return {"role": "assistant", "content": raw}

    def build_tool_result_message(self, tool_calls, results):
        self.results.extend(results)
        return {"role": "tool", "content": json.dumps(results)}

    async def stream_turn(self, model, system, msgs, tools):
        self.tools_seen.append({t["name"] for t in tools})
        turn = self._turns[len(self.tools_seen) - 1]
        yield {"type": "done", **turn}


def _call(name, **inputs):
    return {"stop_reason": "tool_use", "tool_calls": [SimpleNamespace(name=name, inputs=inputs, id=f"id-{name}")],
            "raw_content": "x", "usage": {}}


_END = {"stop_reason": "end_turn", "tool_calls": [], "raw_content": "y", "usage": {}}


def _tool_def(name):
    return {"name": name, "description": "t", "input_schema": {"type": "object", "properties": {}}}


@pytest.fixture(autouse=True)
def skills(monkeypatch):
    data_sources._reset()
    monkeypatch.setitem(shared.SKILL_TOOLS_MAP, "code_runner", {"run_python"})
    monkeypatch.setitem(shared.SKILL_TOOLS_MAP, "demo_service", {"demo_tool"})
    monkeypatch.setitem(shared.SKILL_PROMPTS, "demo_service", "# Demo")
    monkeypatch.setattr(shared, "_ALWAYS_ON_TOOLS", set(shared._ALWAYS_ON_TOOLS) - {"run_python"})
    monkeypatch.setattr(shared, "TOOLS", [*shared.TOOLS, _tool_def("run_python"), _tool_def("demo_tool")])
    yield
    data_sources._reset()


def _run(provider, *, answer, context_id="ctx-" + uuid.uuid4().hex, cards=None):
    executed = []

    async def execute(name, inputs):
        executed.append(name)
        return {"result": "done"}

    request_skill = next(t for t in shared.TOOLS if t["name"] == "request_skill")

    async def go():
        chunks = []
        async for chunk in _single_agent_loop(
            provider=provider, model="m", system="s", msgs=[{"role": "user", "content": "go"}],
            normalized_tools=[request_skill], execute_tool=execute, COM_BOUND_TOOLS=set(),
            TOOL_STATUS={}, _tool_toast=lambda *a, **k: None, _SLACK_SAFE_MSG="__safe__",
            context_id=context_id,
        ):
            chunks.append(chunk)
            if chunk.startswith("data: {"):
                evt = json.loads(chunk[6:]).get("browser_confirm")
                if evt:
                    if cards is not None:
                        cards.append(evt)
                    browser_agent.resolve_browser_confirm(evt["confirm_id"], answer)
        return chunks

    asyncio.run(go())
    return executed


def test_an_approved_runner_becomes_callable_in_the_same_turn():
    cards = []
    provider = _Provider([_call("request_skill", skill="code_runner", reason="build the slide image"),
                          _call("run_python"), _END])
    ctx = "ctx-" + uuid.uuid4().hex
    executed = _run(provider, answer=True, context_id=ctx, cards=cards)

    assert "run_python" not in provider.tools_seen[0]
    assert "run_python" in provider.tools_seen[1]
    assert executed == ["run_python"]
    assert len(cards) == 1 and "Python code runner" in json.dumps(cards[0])
    assert "build the slide image" in json.dumps(cards[0])
    assert chat_routes._granted_runners(ctx) == ["code_runner"]


def test_a_declined_runner_stays_unavailable():
    provider = _Provider([_call("request_skill", skill="code_runner", reason="x"), _call("run_python"), _END])
    ctx = "ctx-" + uuid.uuid4().hex
    executed = _run(provider, answer=False, context_id=ctx)

    assert executed == []
    assert "run_python" not in provider.tools_seen[1]
    assert "skill_not_approved" in json.dumps(provider.results)
    assert chat_routes._granted_runners(ctx) == []


def test_a_model_cannot_use_a_runner_it_never_asked_for():
    provider = _Provider([_call("run_python"), _END])
    assert _run(provider, answer=True) == []


def test_an_approved_runner_is_not_asked_for_twice_in_a_tab():
    cards = []
    provider = _Provider([_call("request_skill", skill="code_runner", reason="a"),
                          _call("request_skill", skill="code_runner", reason="b"), _END])
    _run(provider, answer=True, context_id="ctx-" + uuid.uuid4().hex, cards=cards)
    assert len(cards) == 1


def test_an_unattended_run_cannot_grant_itself_a_runner():
    cards = []
    provider = _Provider([_call("request_skill", skill="code_runner", reason="x"), _call("run_python"), _END])
    executed = _run(provider, answer=True, context_id=None, cards=cards)
    assert cards == [] and executed == []
    assert "run_python" not in provider.tools_seen[1]


def test_a_service_skill_is_granted_without_a_card():
    cards = []
    provider = _Provider([_call("request_skill", skill="demo_service", reason="x"), _call("demo_tool"), _END])
    executed = _run(provider, answer=False, cards=cards)
    assert cards == [] and executed == ["demo_tool"]
    assert "demo_tool" in provider.tools_seen[1]


def test_an_unknown_skill_is_refused():
    provider = _Provider([_call("request_skill", skill="no-such-skill", reason="x"), _END])
    cards = []
    _run(provider, answer=True, cards=cards)
    assert cards == []
    assert "unknown_skill" in json.dumps(provider.results)


def test_the_reason_on_the_card_cannot_forge_card_text():
    cards = []
    reason = "ok\n‮ | Allowed for this tab only. " + "A" * 600
    provider = _Provider([_call("request_skill", skill="code_runner", reason=reason), _END])
    _run(provider, answer=False, cards=cards)
    text = json.dumps(cards[0])
    assert "\\n" not in cards[0]["action"] and "‮" not in cards[0]["action"]
    assert "|" not in cards[0]["action"] and "A" * 400 not in text


def test_a_runner_approved_on_a_card_no_longer_blocks_skills_that_need_it():
    ctx = "ctx-" + uuid.uuid4().hex
    req = SimpleNamespace(approved_deps=[], context_id=ctx)
    assert "code_runner" in chat_routes._ungranted_gated_deps(req)
    data_sources.allow(ctx, "capability:code_runner")
    assert "code_runner" not in chat_routes._ungranted_gated_deps(req)
    assert "code_runner" in chat_routes._ungranted_gated_deps(SimpleNamespace(approved_deps=[], context_id="other"))
