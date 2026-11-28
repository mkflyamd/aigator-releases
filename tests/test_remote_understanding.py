"""Understanding the user: status phrases read as the reserved word, a message sent to a busy or sleeping session
is answered at once and queued, and the last step is read from the agent's transcript."""

import asyncio
import json

import agent_sessions
import pytest

from remote import commands
from tests.test_remote_chat_window import MINUTE, opened, say
from tests.test_remote_lane import asleep, woken
from tests.test_remote_runner import World, _finish


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


@pytest.mark.parametrize(
    "text",
    ["status", "status?", "Status.", "what is the status", "what's the status?", "What is status", "what’s the status"],
)
def test_status_phrases_read_as_the_status_command(text):
    assert commands.parse(f"@gator {text}") == commands.Command("status", name=None)


def test_a_status_phrase_can_name_a_session():
    assert commands.parse("@gator status budget?") == commands.Command("status", name="budget")
    assert commands.parse("@gator what is the status budget") == commands.Command("status", name="budget")


@pytest.mark.parametrize("text", ["what's the list?", "what is the list", "list?"])
def test_the_other_reserved_words_get_the_same_treatment(text):
    assert commands.parse(f"@gator {text}") == commands.Command("list")


@pytest.mark.parametrize(
    "text",
    ["what is the status of the build", "what is the plan", "what's the weather", "what is the list of tasks"],
)
def test_anything_else_is_sent_to_the_agent_as_typed(text):
    assert commands.parse(f"@gator {text}") == commands.Command("send", text=text)


async def test_a_message_to_a_working_session_gets_a_status_reply_and_is_still_sent(w):
    await opened(w)
    await say(w, "run the tests")
    w.host.steps = {"pty-1": "running tests"}
    w.clock.now += 4 * MINUTE
    w.channel.posted.clear()
    await say(w, "also update the docs")
    assert w.host.delivered == [("pty-1", "run the tests"), ("pty-1", "also update the docs")]
    [reply] = w.channel.posted
    assert "Working for 4 min. Last step: running tests." in reply
    assert "Your message is queued, so no need to resend." in reply
    assert "Next:\n• `stop` to stop it." in reply


async def test_the_busy_reply_leaves_out_the_step_when_there_is_none(w):
    await opened(w)
    await say(w, "run the tests")
    w.channel.posted.clear()
    await say(w, "also update the docs")
    [reply] = w.channel.posted
    assert "Last step" not in reply and "queued" in reply


async def test_a_message_to_an_idle_session_gets_no_status_reply(w):
    await opened(w)
    await say(w, "run the tests")
    await _finish(w, "All green.")
    w.channel.posted.clear()
    await say(w, "now the docs")
    assert w.host.delivered[-1] == ("pty-1", "now the docs")
    assert w.channel.posted == []


async def test_the_busy_reply_does_not_restart_the_turn_clock(w):
    await opened(w)
    await say(w, "run the tests")
    w.clock.now += 4 * MINUTE
    await say(w, "also update the docs")
    w.clock.now += 2 * MINUTE
    w.channel.posted.clear()
    await say(w, "and the changelog")
    [reply] = w.channel.posted
    assert "Working for 6 min." in reply


async def test_status_names_the_last_step_of_a_working_session(w):
    await opened(w)
    await say(w, "run the tests")
    w.host.steps = {"pty-1": "editing runner.py"}
    w.clock.now += 4 * MINUTE
    await say(w, "status")
    assert "Working for 4 min. Last step: editing runner.py." in w.channel.posted[-1]
    assert "Next:\n• `stop` to stop it." in w.channel.posted[-1]


async def test_a_message_to_a_waking_session_is_queued_and_sent_once_it_is_awake(w):
    gate = w.host.wake_gate = asyncio.Event()
    await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    await w.feed(w.msg(103, "@gator third task"))
    await w.feed(w.msg(104, "@gator fourth task"))
    assert w.channel.posted.count(commands.still_waking("budget", project="Budget")) == 2
    assert w.host.delivered == [("pty-1", "first task")]
    gate.set()
    await woken(w)
    assert [t for _, t in w.host.delivered] == ["first task", "second task", "third task", "fourth task"]


async def test_a_queued_message_is_dropped_when_the_wake_fails(w):
    gate = w.host.wake_gate = asyncio.Event()
    session = await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    await w.feed(w.msg(103, "@gator third task"))
    assert session.queued == ["third task"]
    w.host.wake_error = Exception("boom")
    gate.set()
    await woken(w)
    assert session.queued == []
    assert w.channel.posted[-1] == commands.queued_not_sent("budget", 1, project="Budget")


async def test_a_failed_wake_counts_every_queued_message_it_did_not_send(w):
    gate = w.host.wake_gate = asyncio.Event()
    await asleep(w)
    for n in range(102, 106):
        await w.feed(w.msg(n, f"@gator task {n}"))
    w.host.wake_error = Exception("boom")
    gate.set()
    await woken(w)
    assert w.channel.posted[-1] == commands.queued_not_sent("budget", 3, project="Budget")
    assert "3 queued messages not sent." in w.channel.posted[-1]


async def test_the_wake_queue_is_capped_and_says_so(w):
    gate = w.host.wake_gate = asyncio.Event()
    session = await asleep(w)
    for n in range(102, 102 + commands.WAKE_QUEUE_MAX + 2):
        await w.feed(w.msg(n, f"@gator task {n}"))
    assert len(session.queued) == commands.WAKE_QUEUE_MAX
    assert w.channel.posted[-1] == commands.wake_queue_full("budget", project="Budget")
    gate.set()
    await woken(w)
    await asyncio.gather(*list(w.runner._wakes))
    assert len(w.host.delivered) == 1 + commands.WAKE_QUEUE_MAX + 1


async def test_a_message_sent_as_the_wake_finishes_does_not_overtake_the_queued_ones(w):
    gate = w.host.wake_gate = asyncio.Event()
    await asleep(w)
    await w.feed(w.msg(102, "@gator second task"))
    await w.feed(w.msg(103, "@gator third task"))
    gate.set()
    await woken(w)
    await w.feed(w.msg(104, "@gator fourth task"))
    await asyncio.gather(*list(w.runner._wakes))
    assert [t for _, t in w.host.delivered] == ["first task", "second task", "third task", "fourth task"]


def _transcript(tmp_path, *entries):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return {"agent": "claude", "path": str(path)}


def _user(text):
    return {"type": "user", "message": {"content": text}}


def _tool(name, **args):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": args}]}}


def test_the_last_step_is_the_latest_tool_call_since_the_request(tmp_path):
    rec = _transcript(
        tmp_path,
        _user("run the tests"),
        _tool("Read", file_path="C:/repo/web/remote/runner.py"),
        _tool("Bash", command="pytest -q", description="running tests"),
    )
    assert agent_sessions.last_step(rec) == "running tests"


def test_a_file_tool_names_the_file(tmp_path):
    rec = _transcript(tmp_path, _user("go"), _tool("Edit", file_path="C:/repo/web/remote/runner.py"))
    assert agent_sessions.last_step(rec) == "editing runner.py"


def test_a_bare_command_is_shown_as_running_it(tmp_path):
    rec = _transcript(tmp_path, _user("go"), _tool("Bash", command="git status\nfoo"))
    assert agent_sessions.last_step(rec) == "running git status"


def test_the_agents_own_prose_is_not_a_step(tmp_path):
    note = {"type": "assistant", "message": {"content": [{"type": "text", "text": "Checking the lane code. More."}]}}
    assert agent_sessions.last_step(_transcript(tmp_path, _user("go"), note)) == ""
    rec = _transcript(tmp_path, _user("go"), _tool("Read", file_path="a.py"), note)
    assert agent_sessions.last_step(rec) == "reading a.py"


@pytest.mark.parametrize("field", ["url", "query", "pattern"])
def test_the_url_query_and_pattern_of_a_call_are_not_shown(tmp_path, field):
    rec = _transcript(tmp_path, _user("go"), _tool("WebFetch", **{field: "https://x.example/?token=abc123"}))
    assert agent_sessions.last_step(rec) == "WebFetch"


def test_a_long_step_is_cut_to_the_step_limit(tmp_path):
    rec = _transcript(tmp_path, _user("go"), _tool("Bash", command="x" * 200, description="y" * 200))
    assert len(agent_sessions.last_step(rec)) == agent_sessions.STEP_MAX


def test_a_secret_is_redacted_before_the_line_is_cut(monkeypatch, tmp_path):
    import agent_handoff

    key = "aigator-fake-api-key"
    monkeypatch.setattr(agent_handoff, "_configured_api_keys", lambda: [key])
    command = "x" * 45 + key
    assert key not in f"running {command}"[: agent_sessions.STEP_MAX] and "aigator" in f"running {command}"[:60]
    step = agent_sessions.last_step(_transcript(tmp_path, _user("go"), _tool("Bash", command=command)))
    assert "aigator" not in step and "fake-api" not in step


def test_the_transcript_record_is_found_once_per_session(monkeypatch, tmp_path):
    from remote import session_host

    rec = _transcript(tmp_path, _user("go"), _tool("Read", file_path="a.py"))
    rec |= {"id": "vendor-1"}
    found = []
    monkeypatch.setattr(agent_sessions, "find_session", lambda *key: found.append(key) or rec)
    monkeypatch.setattr(session_host, "_STEP_RECORDS", {})
    from routes import terminal
    from skills.code_agent import projects

    monkeypatch.setattr(terminal, "session_owner", lambda pty_id: {"project_id": "p", "session_id": "vendor-1"})
    monkeypatch.setattr(projects, "get_project", lambda pid: {"repo_path": "C:/repo"})
    assert session_host.LocalPtyHost._last_step("pty-1") == "reading a.py"
    assert session_host.LocalPtyHost._last_step("pty-1") == "reading a.py"
    assert len(found) == 1


def test_nothing_done_since_the_newest_request_is_no_step(tmp_path):
    rec = _transcript(tmp_path, _user("one"), _tool("Read", file_path="a.py"), _user("two"))
    assert agent_sessions.last_step(rec) == ""


def test_an_agent_without_a_claude_transcript_has_no_step(tmp_path):
    assert agent_sessions.last_step({"agent": "codex", "path": str(tmp_path / "none.jsonl")}) == ""


def _gate_deliveries(w):
    """Typing into the session waits until the test lets it through, as it does while the session is busy."""
    gate = asyncio.Event()
    real = w.host.deliver

    async def deliver(pty_id, text):
        await gate.wait()
        await real(pty_id, text)

    w.host.deliver = deliver
    return gate


async def test_a_message_to_a_busy_session_is_answered_at_once_and_does_not_stall_the_loop(w):
    await opened(w)
    await say(w, "run the tests")
    gate = _gate_deliveries(w)
    w.channel.posted.clear()
    await asyncio.wait_for(say(w, "also update the docs"), 5)
    assert "queued" in w.channel.posted[-1]
    assert w.host.delivered == [("pty-1", "run the tests")]
    await asyncio.wait_for(w.runner.tick(), 5)
    gate.set()
    await asyncio.gather(*list(w.runner._wakes))
    assert w.host.delivered[-1] == ("pty-1", "also update the docs")


async def test_messages_to_a_busy_session_are_typed_in_the_order_they_were_sent(w):
    await opened(w)
    await say(w, "run the tests")
    gate = _gate_deliveries(w)
    await say(w, "one")
    await say(w, "two")
    await say(w, "three")
    gate.set()
    await asyncio.gather(*list(w.runner._wakes))
    assert [t for _, t in w.host.delivered] == ["run the tests", "one", "two", "three"]
    assert w.runner._outbox == {}


async def test_a_queued_message_that_cannot_be_typed_says_so(w):
    from remote.session_host import HostError

    await opened(w)
    await say(w, "run the tests")

    async def refuse(pty_id, text):
        raise HostError("Someone is using that session in AI Gator right now.")

    w.host.deliver = refuse
    w.channel.posted.clear()
    await say(w, "also update the docs")
    await asyncio.gather(*list(w.runner._wakes))
    assert "queued" in w.channel.posted[0]
    assert "Someone is using that session" in w.channel.posted[-1]
