"""A terminal started in AI Gator that is waiting reaches chat after a wait, as a stand-in that says only what kind
of prompt it is, and a reply to it is never typed anywhere."""

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
from tests.test_remote_runner import BUDGET, World
from tests.test_remote_session_host import FAKE_KEY


class Watch:
    """The terminals the app holds that are waiting, as the runner is told of them."""

    def __init__(self):
        self.seen = []
        self.skipped = None

    def add(self, pty, project, kind=prompts.PERMISSION_APP, tool="Bash", at=0.0):
        prompt = prompts.Prompt(f"id-{pty}-{at}", kind, tool=tool if kind == prompts.PERMISSION_APP else "", at=at)
        self.seen.append(Seen(pty, project, prompt))

    def waiting(self, skip):
        self.skipped = skip
        return list(self.seen)


@pytest.fixture
def w(tmp_path):
    world = World(tmp_path)
    world.terminals = Watch()
    world.build()
    return world


APP_NOTICE = "[🐊 Gator] Needs you: permission (Bash) in Budget. Answer in AI Gator."


async def waited(w, seconds=130):
    w.clock.now += seconds
    await w.runner.tick()


async def test_a_waiting_app_terminal_gets_a_stand_in_after_two_minutes(w):
    await opened(w)
    w.channel.posted.clear()
    w.terminals.add("term-1", BUDGET, at=w.clock.now)
    await w.runner.tick()
    await waited(w, 100)
    assert w.channel.posted == []
    await waited(w, 30)
    assert w.channel.posted == [APP_NOTICE]
    await waited(w, 30)
    assert len(w.channel.posted) == 1


async def test_a_waiting_question_is_named_as_a_question_without_its_text(w):
    await opened(w)
    w.channel.posted.clear()
    w.terminals.add("term-1", BUDGET, kind=prompts.APP_ONLY, at=w.clock.now)
    await w.runner.tick()
    await waited(w)
    assert w.channel.posted == ["[🐊 Gator] Needs you: asking a question in Budget. Answer in AI Gator."]


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


async def test_a_quote_reply_to_a_stand_in_types_nothing_and_says_to_answer_in_the_app(w):
    await opened(w)
    w.terminals.add("term-1", BUDGET, at=w.clock.now)
    await w.runner.tick()
    await waited(w)
    [record] = routed(w)
    w.channel.posted.clear()
    await quote_reply(w, record["message_id"], "allow")
    assert w.channel.posted == ["[🐊 Gator] Answer this one in AI Gator."]
    assert w.host.typed == [] and w.host.delivered == []
    assert [m["message_id"] for m in routed(w)] == [record["message_id"]]


async def test_a_quote_reply_after_the_terminal_stopped_waiting_says_it_was_answered(w):
    await opened(w)
    w.terminals.add("term-1", BUDGET, at=w.clock.now)
    await w.runner.tick()
    await waited(w)
    [record] = routed(w)
    w.terminals.seen.clear()
    await w.runner.tick()
    w.channel.posted.clear()
    await quote_reply(w, record["message_id"], "allow")
    assert w.channel.posted == ["[🐊 Gator] That was already answered in AI Gator."]
    assert w.host.typed == []


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
    assert [t for t in w.channel.posted if t.startswith("[🐊 Gator] Needs you:")]


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


def test_the_real_watch_reads_the_tool_and_never_the_command(terminals):
    terminals[T1] = {"project_id": "Budget"}
    hook_files(T1, {"tool_name": "Bash", "tool_input": {"command": f"deploy --secret {FAKE_KEY}"}})
    [seen] = LocalTerminalWatch().waiting(set())
    assert (seen.pty_id, seen.project.name) == (T1, "Budget")
    assert (seen.prompt.kind, seen.prompt.tool) == (prompts.PERMISSION_APP, "Bash")
    assert seen.prompt.command == "" and seen.prompt.path == ""
    assert "deploy" not in repr(seen) and FAKE_KEY not in repr(seen)


def test_the_real_watch_reports_a_question_without_its_text(terminals):
    terminals[T1] = {"project_id": "Budget"}
    hook_files(T1, {"tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Pick the colour"}]}})
    [seen] = LocalTerminalWatch().waiting(set())
    assert seen.prompt.kind == prompts.APP_ONLY
    assert seen.prompt.question == "" and "colour" not in repr(seen)


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
