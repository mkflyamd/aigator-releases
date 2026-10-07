"""A short follow-up ("try fireworks") keeps the skills the chat was already using.

History sent by the browser is text only, so the Slack tools were not offered on a
follow-up that never said "in slack", and the model's call was rejected with
tool_not_offered. The server-side store records which tools actually ran; carry those
tools' skills forward.
"""

import asyncio
import pathlib

import app  # noqa: F401 — importing populates the skill registries at startup
import shared
from conversation_store import ConversationStore
from routes.chat import _skills_for_tools

CHAT_SRC = (pathlib.Path(__file__).parent.parent / "routes" / "chat.py").read_text(encoding="utf-8")


def _tool_turn(name, tid, result="ok"):
    return [
        {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": result}]},
    ]


def _names(messages):
    store = ConversationStore()

    async def run():
        await store.append("tab", messages)
        return await store.recent_tool_names("tab")

    return asyncio.run(run())


def test_tools_that_ran_are_reported():
    assert _names(_tool_turn("slack_search_public_and_private", "a")) == {"slack_search_public_and_private"}


def test_openai_format_tool_calls_are_reported():
    msgs = [
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "slack_search_public_and_private", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
    ]
    assert _names(msgs) == {"slack_search_public_and_private"}


def test_a_call_the_allow_list_refused_is_not_counted():
    refused = '{"error": "tool_not_offered", "tool": "slack_search_public_and_private"}'
    assert _names(_tool_turn("slack_search_public_and_private", "a", refused)) == set()


def test_a_tool_that_ran_brings_its_skill_back():
    assert "slack" in _skills_for_tools({"slack_search_public_and_private"})


def test_internal_gated_and_unknown_tools_bring_nothing_back():
    assert _skills_for_tools({"no_such_tool"}) == []
    assert not any(s.startswith("_") for s in _skills_for_tools(shared.SKILL_TOOLS_MAP.get("_always_on", set())))
    gated = {t for sid in ("shell_runner", "code_runner") for t in shared.SKILL_TOOLS_MAP.get(sid, set())}
    assert not {"shell_runner", "code_runner"} & set(_skills_for_tools(gated))


def test_the_smallest_owning_skill_is_chosen():
    both = [(sid, tools) for sid, tools in shared.SKILL_TOOLS_MAP.items() if sid.startswith("mcp-cloud-atlassian")]
    for sid, tools in both:
        for t in list(tools)[:1]:
            owners = [(len(x), s) for s, x in shared.SKILL_TOOLS_MAP.items()
                      if t in x and not s.startswith("_") and s not in ("shell_runner", "code_runner")]
            assert _skills_for_tools({t}) == [min(owners)[1]]


def test_carry_forward_uses_the_stores_tool_history():
    assert "recent_tool_names(_context_id)" in CHAT_SRC


def test_failure_banner_is_held_back_when_an_auto_activation_retry_follows():
    held = CHAT_SRC.index("_held_stall = chunk")
    sent = CHAT_SRC.index("yield _held_stall")
    retry = CHAT_SRC.index("_all_active.extend(_new_skills)")
    assert held < sent < retry, "the banner is only sent when no retry follows"
