"""A runner (shell/code) the user approved or the chat already used must stay
offered for the rest of the chat: not only while its tool call is inside the
last 24 messages, and not only when the turn has no pinned skill."""

import asyncio
import pathlib

import app  # noqa: F401 — importing populates the skill registries at startup
import shared
from conversation_store import ConversationStore
from task_state import TaskStateStore

CHAT_SRC = (pathlib.Path(__file__).parent.parent / "web" / "routes" / "chat.py").read_text(encoding="utf-8")


def _tool_turn(name, tid):
    return [
        {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]},
    ]


def _chatter(n):
    out = []
    for i in range(n):
        out.append({"role": "user", "content": f"q{i}"})
        out.append({"role": "assistant", "content": [{"type": "text", "text": f"a{i}"}]})
    return out


def test_a_tool_run_long_ago_is_still_reported_when_the_window_is_unbounded():
    store = ConversationStore()
    msgs = [*_tool_turn("run_on_host", "t1"), *_chatter(40)]

    async def run():
        await store.append("tab", msgs)
        return (
            await store.recent_tool_names("tab"),
            await store.recent_tool_names("tab", last_n=None),
        )

    windowed, everything = asyncio.run(run())
    assert "run_on_host" not in windowed
    assert "run_on_host" in everything


def _runner_tool():
    for sid in ("shell_runner", "code_runner"):
        tools = shared.SKILL_TOOLS_MAP.get(sid)
        if tools:
            return sid, sorted(tools)[0]
    raise AssertionError("no runner skill registered")


def test_a_runner_used_in_an_earlier_turn_stays_in_play(monkeypatch):
    from routes import chat

    store = TaskStateStore()
    monkeypatch.setattr(shared, "task_state_store", store)
    monkeypatch.setattr(chat, "_granted_runners", lambda ctx: [])
    sid, tool = _runner_tool()

    assert chat._runners_in_play("tab", {tool}) == [sid]
    # Later turn: the tool call has scrolled out of the history window.
    assert chat._runners_in_play("tab", set()) == [sid]
    # Another chat is unaffected.
    assert chat._runners_in_play("other-tab", set()) == []


def test_a_granted_runner_is_in_play_without_any_tool_run(monkeypatch):
    from routes import chat

    monkeypatch.setattr(shared, "task_state_store", TaskStateStore())
    monkeypatch.setattr(chat, "_granted_runners", lambda ctx: ["shell_runner"])
    assert chat._runners_in_play("tab", set()) == ["shell_runner"]


def test_asking_about_runners_does_not_create_an_empty_tab_state(monkeypatch):
    from routes import chat

    store = TaskStateStore()
    monkeypatch.setattr(shared, "task_state_store", store)
    monkeypatch.setattr(chat, "_granted_runners", lambda ctx: [])
    chat._runners_in_play("tab", set())
    assert store.get("tab") is None


def test_runner_carry_forward_is_not_skipped_when_a_skill_is_pinned():
    call = next(l for l in CHAT_SRC.splitlines() if "_carried_runners = _runners_in_play(" in l)
    assert call.startswith("    _carried_runners"), "must sit outside the not-locked branch"
    assert "last_n=None" in CHAT_SRC
