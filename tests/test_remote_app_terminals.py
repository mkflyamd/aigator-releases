"""A terminal started in AI Gator that is waiting reaches chat after a wait with its real prompt, and a reply is typed
into it through the same guards as for a session Remote started."""

import json
import types

import pytest

import agent_handoff
import agent_state
from remote import prompts
from remote.master import Master
from remote.bystanders import LocalTerminalWatch, Seen
from routes import terminal
from tests.test_remote_chat_window import opened, say
from tests.test_remote_needs_you import FOURTH, PROJECTS, quote_reply
from tests.test_remote_prompt_flow import routed
from tests.test_remote_prompts import BASH_PERMISSION, ask, question
from tests.test_remote_runner import BUDGET, World
from tests.test_remote_session_host import FAKE_KEY

RM_BUILD = {**BASH_PERMISSION, "tool_input": {"command": "rm -rf build"}}


class Watch:
    """The terminals the app holds that are waiting, as the runner is told of them. `add` also leaves what the host
    reads when an answer is typed."""

    def __init__(self):
        self.seen = []
        self.skipped = None
        self.host = None

    def add(self, pty, project, payload=BASH_PERMISSION, at=0.0):
        prompt = prompts.parse(payload, at)
        self.seen = [s for s in self.seen if s.pty_id != pty]
        self.seen.append(Seen(pty, project, prompt, at))
        self.host.states[pty] = {"state": "asking", "at": at}
        self.host.prompts[pty] = prompt

    def waiting(self, skip):
        self.skipped = skip
        return [item for item in self.seen if item.pty_id not in skip]


@pytest.fixture
def w(tmp_path):
    world = World(tmp_path)
    world.terminals = Watch()
    world.terminals.host = world.host
    world.build()
    return world


PERMISSION = (
    "[🐊 Gator - Budget] Needs you: permission, waiting 2 min.\n"
    "Tool: Bash\nCommand: echo hi > out.txt\n\n"
    "Next:\n• `allow` to allow once.\n• `deny` to deny."
)


async def waited(w, seconds=130):
    w.clock.now += seconds
    await w.runner.tick()


async def waiting_terminal(w, pty="term-1", project=BUDGET, payload=BASH_PERMISSION):
    w.terminals.add(pty, project, payload, at=w.clock.now)
    await w.runner.tick()
    await waited(w)


async def test_a_waiting_app_terminal_is_posted_with_its_real_prompt_after_two_minutes(w):
    await opened(w)
    w.channel.posted.clear()
    w.terminals.add("term-1", BUDGET, at=w.clock.now)
    await w.runner.tick()
    await waited(w, 100)
    assert w.channel.posted == []
    await waited(w, 30)
    assert w.channel.posted == [PERMISSION]
    await waited(w, 30)
    assert len(w.channel.posted) == 1


@pytest.mark.parametrize(
    "payload",
    [
        ask(question(multi=True)),
        ask(question(), question("Second?")),
        {"tool_name": "ExitPlanMode", "tool_input": {"plan": "x"}},
        {"tool_name": "mcp__x__y", "tool_input": {}},
    ],
)
async def test_what_cannot_be_answered_in_chat_is_posted_and_says_to_open_the_app(w, payload):
    await opened(w)
    w.channel.posted.clear()
    await waiting_terminal(w, payload=payload)
    [message] = w.channel.posted
    assert message.startswith("[🐊 Gator - Budget] Needs you:") and "Open AI Gator" in message
    [record] = routed(w)
    await quote_reply(w, record["message_id"], "allow")
    assert w.host.typed == []
    assert "AI Gator" in w.channel.posted[-1]


async def test_a_question_is_posted_with_its_text_and_numbered_options_and_a_number_answers_it(w):
    await opened(w)
    w.channel.posted.clear()
    await waiting_terminal(w, payload=ask(question("Pick the colour", ("Red", "Blue"))))
    [message] = w.channel.posted
    assert "Pick the colour" in message and "`1` Red" in message and "`2` Blue" in message
    await say(w, "2")
    assert [pty for pty, _ in w.host.typed] == ["term-1"]


async def test_an_app_terminal_is_not_posted_while_remote_control_is_not_armed(w):
    Master(w.state, w.clock).disarm()
    w.terminals.add("term-1", BUDGET, at=w.clock.now)
    await w.runner.tick()
    await waited(w)
    assert w.channel.posted == []
    assert routed(w) == []


async def test_a_terminal_remote_runs_is_left_to_the_service(w):
    await opened(w)
    await say(w, "run the tests")
    await w.runner.tick()
    assert w.terminals.skipped == {"pty-1"}


async def test_only_three_app_terminals_are_posted_and_one_line_names_the_rest(w):
    await opened(w)
    w.channel.posted.clear()
    for number, project in enumerate(PROJECTS):
        w.terminals.add(f"term-{number}", project, at=w.clock.now)
    await w.runner.tick()
    await waited(w)
    assert len(routed(w)) == 3
    assert len(w.channel.posted) == 4
    assert w.channel.posted[-1].startswith("[🐊 Gator] 1 more session needs you:")


async def test_a_quote_reply_allow_is_typed_into_that_terminal_only(w):
    await opened(w)
    w.terminals.add("term-1", BUDGET, at=w.clock.now)
    w.terminals.add("term-2", PROJECTS[1], at=w.clock.now)
    await w.runner.tick()
    await waited(w)
    records = {r["session_id"]: r for r in routed(w)}
    w.channel.posted.clear()
    await quote_reply(w, records["app:term-2"]["message_id"], "allow")
    assert w.host.typed == [("term-2", (prompts.ENTER,))]
    assert w.channel.posted[0].startswith("[🐊 Gator - ") and prompts.ALLOWED in w.channel.posted[0]


async def test_an_unquoted_allow_answers_the_one_terminal_that_is_waiting(w):
    await opened(w)
    await waiting_terminal(w)
    await say(w, "allow")
    assert w.host.typed == [("term-1", (prompts.ENTER,))]


async def test_an_unquoted_deny_is_typed_as_escape(w):
    await opened(w)
    await waiting_terminal(w)
    await say(w, "deny")
    assert w.host.typed == [("term-1", (prompts.ESCAPE,))]


async def test_an_unquoted_allow_with_several_waiting_asks_which_one_and_types_nothing(w):
    await opened(w)
    w.terminals.add("term-1", BUDGET, at=w.clock.now)
    w.terminals.add("term-2", PROJECTS[1], at=w.clock.now)
    await w.runner.tick()
    await waited(w)
    w.channel.posted.clear()
    await say(w, "allow")
    assert w.host.typed == []
    assert "Which one?" in w.channel.posted[-1]


async def test_an_unquoted_allow_is_ambiguous_across_a_started_session_and_a_terminal(w):
    await opened(w)
    await say(w, "run the tests")
    w.host.states["pty-1"] = {"state": "asking", "at": w.clock.now + 5}
    w.host.prompts["pty-1"] = prompts.parse(BASH_PERMISSION, w.clock.now + 5)
    await w.runner.tick()
    await waiting_terminal(w, "term-1", PROJECTS[1])
    w.channel.posted.clear()
    await say(w, "allow")
    assert w.host.typed == []
    assert "Which one?" in w.channel.posted[-1]


async def test_a_reply_written_before_the_terminal_prompt_was_first_seen_is_not_typed(w):
    await opened(w)
    w.clock.now += 100
    await waiting_terminal(w)
    w.channel.posted.clear()
    await say(w, "allow", age=200)
    assert w.host.typed == []
    assert w.channel.posted[-1].startswith("[🐊 Gator - Budget] Not sent: that was for an earlier question.")


async def test_a_quote_reply_to_an_earlier_prompt_of_the_terminal_is_not_typed_into_the_current_one(w):
    await opened(w)
    await waiting_terminal(w)
    [record] = routed(w)
    w.clock.now += 30
    w.terminals.add("term-1", BUDGET, RM_BUILD, at=w.clock.now)
    await w.runner.tick()
    w.channel.posted.clear()
    await quote_reply(w, record["message_id"], "allow")
    assert w.host.typed == []
    assert w.channel.posted[-1].startswith("[🐊 Gator - Budget]") and "already answered" in w.channel.posted[-1]


async def test_nothing_is_typed_when_the_terminal_moved_on_after_the_prompt_was_read(w):
    await opened(w)
    await waiting_terminal(w)
    [record] = routed(w)
    w.host.prompts["term-1"] = prompts.parse(RM_BUILD, w.clock.now + 10)
    w.channel.posted.clear()
    await quote_reply(w, record["message_id"], "allow")
    assert w.host.typed == []
    assert "already answered" in w.channel.posted[-1]


async def test_a_quote_reply_after_the_terminal_stopped_waiting_says_it_was_answered(w):
    await opened(w)
    await waiting_terminal(w)
    [record] = routed(w)
    w.terminals.seen.clear()
    await w.runner.tick()
    w.channel.posted.clear()
    await quote_reply(w, record["message_id"], "allow")
    assert "already answered" in w.channel.posted[-1]
    assert w.host.typed == []


async def test_a_terminal_answered_from_chat_is_not_posted_again_while_its_state_is_unchanged(w):
    await opened(w)
    await waiting_terminal(w)
    await say(w, "allow")
    w.channel.posted.clear()
    await waited(w, 400)
    await waited(w, 400)
    assert w.channel.posted == []
    w.clock.now += 5
    w.terminals.add("term-1", BUDGET, RM_BUILD, at=w.clock.now)
    await w.runner.tick()
    await waited(w)
    assert len(w.channel.posted) == 1 and "rm -rf build" in w.channel.posted[0]


async def test_an_answered_app_terminal_frees_its_place_for_the_next(w):
    await opened(w)
    for number, project in enumerate([*PROJECTS, FOURTH]):
        w.terminals.add(f"term-{number}", project, at=w.clock.now)
    await w.runner.tick()
    await waited(w)
    w.channel.posted.clear()
    del w.terminals.seen[0]
    await w.runner.tick()
    assert len(routed(w)) == 3
    assert [t for t in w.channel.posted if t.startswith("[🐊 Gator - ") and "Needs you:" in t]


@pytest.fixture
def terminals(tmp_path, monkeypatch):
    """Hook files in a temporary state directory, over a fake terminal registry."""
    from skills.code_agent import projects

    monkeypatch.setattr(agent_state, "STATE_DIR", tmp_path / "agent-state")
    agent_state.STATE_DIR.mkdir()
    monkeypatch.setattr(agent_handoff, "_configured_api_keys", lambda: [FAKE_KEY])
    labels = {}
    monkeypatch.setattr(terminal, "live_pty_labels", lambda strict=False: labels)
    monkeypatch.setattr(terminal, "get_pty_session", lambda pty: None)
    known = {"Budget": {"name": "Budget", "repo_path": "C:/repo/budget"}}
    monkeypatch.setattr(projects, "get_project", lambda name: known.get(name))
    return labels


def hook_files(pty, payload, state="asking"):
    agent_state.set_state(pty, state)
    if payload is not None:
        (agent_state.STATE_DIR / (pty + ".prompt")).write_text(json.dumps(payload), encoding="utf-8")


T1, T2 = "aaaaaaaa-1111-4222-8333-000000000001", "aaaaaaaa-1111-4222-8333-000000000002"
T3, T4, T5 = (f"aaaaaaaa-1111-4222-8333-00000000000{n}" for n in (3, 4, 5))


def test_the_real_watch_reads_the_tool_and_the_redacted_command(terminals):
    terminals[T1] = {"project_id": "Budget"}
    hook_files(T1, {"tool_name": "Bash", "tool_input": {"command": f"deploy --secret {FAKE_KEY}"}})
    [seen] = LocalTerminalWatch().waiting(set())
    assert (seen.pty_id, seen.project.name) == (T1, "Budget")
    assert (seen.prompt.kind, seen.prompt.tool) == (prompts.PERMISSION, "Bash")
    assert seen.prompt.command.startswith("deploy --secret ") and "[REDACTED]" in seen.prompt.command
    assert FAKE_KEY not in repr(seen)
    assert seen.state_at == agent_state.read_states([T1])[T1]["at"]


def test_the_real_watch_reports_a_question_with_its_text_and_options(terminals):
    terminals[T1] = {"project_id": "Budget"}
    hook_files(T1, ask(question("Pick the colour", ("Red", "Blue"))))
    [seen] = LocalTerminalWatch().waiting(set())
    assert seen.prompt.kind == prompts.QUESTION and seen.prompt.answerable
    assert seen.prompt.question == "Pick the colour"
    assert [c.label for c in seen.prompt.choices] == ["Red", "Blue"]


def test_the_real_watch_keeps_an_app_only_prompt_app_only(terminals):
    terminals[T1] = {"project_id": "Budget"}
    hook_files(T1, ask(question(multi=True)))
    [seen] = LocalTerminalWatch().waiting(set())
    assert seen.prompt.kind == prompts.APP_ONLY and not seen.prompt.answerable


def test_the_real_watch_shows_a_terminal_that_wrote_no_prompt_as_app_only(terminals):
    terminals[T1] = {"project_id": "Budget"}
    hook_files(T1, None)
    [seen] = LocalTerminalWatch().waiting(set())
    assert seen.prompt.kind == prompts.APP_ONLY and not seen.prompt.answerable


def test_the_real_watch_skips_what_is_not_waiting_not_in_the_users_projects_or_run_by_remote(terminals):
    terminals[T1] = {"project_id": "Budget"}
    terminals[T2] = {"project_id": "Elsewhere"}
    terminals[T3] = {"project_id": "Budget", "remote_pinned": "1"}
    terminals[T4] = {"project_id": "Budget"}
    terminals[T5] = {}
    for pty in terminals:
        hook_files(pty, {"tool_name": "Bash", "tool_input": {"command": "x"}})
    hook_files(T4, None, state="working")
    assert [s.pty_id for s in LocalTerminalWatch().waiting(set())] == [T1]
    assert LocalTerminalWatch().waiting({T1}) == []


def test_the_real_watch_skips_a_terminal_the_user_typed_in_after_the_prompt(terminals, monkeypatch):
    terminals[T1] = {"project_id": "Budget"}
    hook_files(T1, {"tool_name": "Bash", "tool_input": {"command": "x"}})
    at = agent_state.read_states([T1])[T1]["at"]
    typed = types.SimpleNamespace(last_user_input=at + 5)
    monkeypatch.setattr(terminal, "get_pty_session", lambda pty: typed)
    assert LocalTerminalWatch().waiting(set()) == []
    typed.last_user_input = at - 5
    assert len(LocalTerminalWatch().waiting(set())) == 1
