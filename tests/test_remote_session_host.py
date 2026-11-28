"""The text Gator posts to Teams comes from the agent's transcript, so secrets are redacted first."""

import json
import logging
import os

import pytest

import agent_handoff
import agent_sessions
import agent_state
from remote import prompts
from remote.commands import agent_result
from remote.session_host import HostError, LocalPtyHost, StalePrompt
from routes import terminal
from skills.code_agent import projects

FAKE_KEY = "aigator-fake-api-key"


class _Entry:
    meta = {"project_id": "demo", "agent": "claude", "session_id": "vendor-1"}


def _host_with_reply(monkeypatch, reply):
    monkeypatch.setattr(terminal, "session_owner", lambda sid: _Entry.meta)
    monkeypatch.setattr(projects, "get_project", lambda name: {"repo_path": "C:/repo/demo"})
    monkeypatch.setattr(agent_sessions, "find_session", lambda repo, agent, sid: object())
    monkeypatch.setattr(agent_sessions, "last_assistant_text", lambda rec: reply)
    monkeypatch.setattr(agent_handoff, "_configured_api_keys", lambda: [FAKE_KEY])
    return LocalPtyHost()


async def test_a_configured_key_in_the_last_assistant_message_is_redacted(monkeypatch):
    host = _host_with_reply(monkeypatch, f"The key is {FAKE_KEY} and that is all.")
    text = await host.last_message("pty-1")
    assert FAKE_KEY not in text
    assert "[REDACTED]" in text


async def test_known_token_shapes_in_the_last_assistant_message_are_redacted(monkeypatch):
    bearer = "ab12" * 6
    host = _host_with_reply(monkeypatch, f"Authorization: Bearer {bearer} and ghp_" + "a" * 30)
    text = await host.last_message("pty-1")
    assert bearer not in text
    assert "ghp_" + "a" * 30 not in text


async def test_redacted_text_is_still_split_into_parts(monkeypatch):
    host = _host_with_reply(monkeypatch, f"{FAKE_KEY} " + "x " * 3000)
    parts = agent_result("Claude", "demo", "Done.", await host.last_message("pty-1"))
    assert len(parts) == 2
    assert all(FAKE_KEY not in part for part in parts)
    assert "[REDACTED]" in parts[0]


async def test_a_transcript_that_catches_up_after_the_stop_hook_is_waited_for(monkeypatch):
    host = _host_with_reply(monkeypatch, "unused")
    monkeypatch.setattr("remote.session_host.time.sleep", lambda s: None)
    answers = iter(["", "", "the real answer"])
    monkeypatch.setattr(agent_sessions, "last_assistant_text", lambda rec: next(answers))
    assert await host.last_message("pty-1") == "the real answer"


async def test_a_transcript_with_no_reply_warns_instead_of_failing_silently(monkeypatch, caplog):
    host = _host_with_reply(monkeypatch, "unused")
    monkeypatch.setattr("remote.session_host.time.sleep", lambda s: None)
    monkeypatch.setattr(agent_sessions, "last_assistant_text", lambda rec: "")
    with caplog.at_level(logging.WARNING, logger="remote.session_host"):
        assert await host.last_message("pty-1") == ""
    assert "no assistant reply yet" in caplog.text


async def test_a_session_without_a_vendor_id_warns_instead_of_failing_silently(monkeypatch, caplog):
    host = _host_with_reply(monkeypatch, "unused")
    monkeypatch.setattr(terminal, "session_owner", lambda sid: {"project_id": "demo", "agent": "claude"})
    with caplog.at_level(logging.WARNING, logger="remote.session_host"):
        assert await host.last_message("pty-1") == ""
    assert "cannot be read" in caplog.text


async def test_an_unknown_session_record_warns(monkeypatch, caplog):
    host = _host_with_reply(monkeypatch, "unused")
    monkeypatch.setattr("remote.session_host.time.sleep", lambda s: None)
    monkeypatch.setattr(agent_sessions, "find_session", lambda repo, agent, sid: None)
    with caplog.at_level(logging.WARNING, logger="remote.session_host"):
        assert await host.last_message("pty-1") == ""
    assert "no assistant reply yet" in caplog.text


def _write_claude_transcript(path, lines):
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def _turn(role, text):
    return {"type": role, "message": {"role": role, "content": [{"type": "text", "text": text}]}}


async def test_the_reply_is_read_from_a_real_transcript_file_with_its_line_breaks(monkeypatch, tmp_path):
    transcript = tmp_path / "vendor-1.jsonl"
    _write_claude_transcript(
        transcript,
        [_turn("user", "what changed?"), _turn("assistant", "Two files changed.\n\n- a.py\n- b.py")],
    )
    monkeypatch.setattr(terminal, "session_owner", lambda sid: _Entry.meta)
    monkeypatch.setattr(projects, "get_project", lambda name: {"repo_path": "C:/repo/demo"})
    record = {"agent": "claude", "path": str(transcript)}
    monkeypatch.setattr(agent_sessions, "find_session", lambda repo, agent, sid: record)
    monkeypatch.setattr(agent_handoff, "_configured_api_keys", lambda: [])
    assert await LocalPtyHost().last_message("pty-1") == "Two files changed.\n\n- a.py\n- b.py"


def test_last_assistant_text_is_empty_while_only_the_prompt_is_in_the_transcript(tmp_path):
    transcript = tmp_path / "vendor-1.jsonl"
    _write_claude_transcript(transcript, [_turn("user", "what changed?")])
    assert agent_sessions.last_assistant_text({"agent": "claude", "path": str(transcript)}) == ""


def test_last_assistant_text_is_empty_when_the_newest_prompt_has_no_answer_yet(tmp_path):
    transcript = tmp_path / "vendor-1.jsonl"
    _write_claude_transcript(transcript, [_turn("user", "q1"), _turn("assistant", "old answer"), _turn("user", "q2")])
    assert agent_sessions.last_assistant_text({"agent": "claude", "path": str(transcript)}) == ""


async def test_the_previous_turns_reply_is_never_posted_while_the_new_one_is_still_being_written(
    monkeypatch, tmp_path
):
    transcript = tmp_path / "vendor-1.jsonl"
    _write_claude_transcript(transcript, [_turn("user", "q1"), _turn("assistant", "old answer"), _turn("user", "q2")])
    monkeypatch.setattr(terminal, "session_owner", lambda sid: _Entry.meta)
    monkeypatch.setattr(projects, "get_project", lambda name: {"repo_path": "C:/repo/demo"})
    monkeypatch.setattr(agent_sessions, "find_session", lambda repo, agent, sid: {"agent": "claude", "path": str(transcript)})
    monkeypatch.setattr(agent_handoff, "_configured_api_keys", lambda: [])
    sleeps = []

    def late_answer(seconds):
        sleeps.append(seconds)
        with transcript.open("a", encoding="utf-8") as f:
            f.write(json.dumps(_turn("assistant", "new answer")) + "\n")

    monkeypatch.setattr("remote.session_host.time.sleep", late_answer)
    assert await LocalPtyHost().last_message("pty-1") == "new answer"
    assert len(sleeps) == 1


async def test_a_prompt_that_never_gets_an_answer_posts_nothing_rather_than_the_old_reply(monkeypatch, tmp_path, caplog):
    transcript = tmp_path / "vendor-1.jsonl"
    _write_claude_transcript(transcript, [_turn("user", "q1"), _turn("assistant", "old answer"), _turn("user", "q2")])
    monkeypatch.setattr(terminal, "session_owner", lambda sid: _Entry.meta)
    monkeypatch.setattr(projects, "get_project", lambda name: {"repo_path": "C:/repo/demo"})
    monkeypatch.setattr(agent_sessions, "find_session", lambda repo, agent, sid: {"agent": "claude", "path": str(transcript)})
    monkeypatch.setattr("remote.session_host.time.sleep", lambda s: None)
    with caplog.at_level(logging.WARNING, logger="remote.session_host"):
        assert await LocalPtyHost().last_message("pty-1") == ""
    assert "no assistant reply yet" in caplog.text


async def test_a_transcript_read_error_returns_nothing_and_warns(monkeypatch, caplog):
    host = _host_with_reply(monkeypatch, "unused")

    def broken(repo, agent, sid):
        raise OSError("disk gone")

    monkeypatch.setattr(agent_sessions, "find_session", broken)
    with caplog.at_level(logging.WARNING, logger="remote.session_host"):
        assert await host.last_message("pty-1") == ""
    assert "could not read the transcript" in caplog.text


async def test_a_secret_value_on_the_line_after_its_key_is_redacted(monkeypatch):
    host = _host_with_reply(monkeypatch, "Set the value:\npassword:\nCorrectHorse99\nx-api-key:\nabcdefgh12345678")
    text = await host.last_message("pty-1")
    assert "CorrectHorse99" not in text and "abcdefgh12345678" not in text
    assert text.startswith("Set the value:\npassword:\n[REDACTED]")


def test_last_assistant_text_reads_the_newest_reply_and_previews_stay_flat(tmp_path):
    transcript = tmp_path / "vendor-1.jsonl"
    _write_claude_transcript(
        transcript,
        [_turn("user", "q1"), _turn("assistant", "old answer"), _turn("user", "q2"), _turn("assistant", "new\nanswer")],
    )
    rec = {"agent": "claude", "path": str(transcript)}
    assert agent_sessions.last_assistant_text(rec) == "new\nanswer"
    newest = json.loads(transcript.read_text(encoding="utf-8").splitlines()[-1])
    assert agent_sessions._claude_message(newest) == ("assistant", "new answer")
    assert agent_sessions._claude_message(newest, flat=False) == ("assistant", "new\nanswer")


# ---------------------------------------------------------------- answering a prompt

PTY = "0b1f3c5e-1111-4222-8333-444455556666"
BASH = {"tool_name": "Bash", "cwd": "C:/repo", "tool_input": {"command": "echo hi"}}


# The tail of a real Claude Code 2.1.283 Bash permission dialog (ANSI stripped, spaces painted as cursor moves).
BASH_DIALOG = (
    "● Bash(echo hi) ⎿  Waiting…\n"
    "────────────\nDoyouwanttoproceed?\n❯1.Yes\n2.Yes,andalwaysallowaccesstoC:\\repoduringthissession\n"
    "3.Yes,andswitchtoautomode\n4.No\n\nEsctocancel·Tabtoamend"
)
AFTER_ENTER = BASH_DIALOG + "\n●\n✢Marinating…\n*Marinating…3"
AFTER_ESC = BASH_DIALOG + "\n● Interrupted · What should Claude do instead?"
LATER_DIALOG = BASH_DIALOG.replace("echo hi", "ls") + "\n●Ran ls\nDoyouwanttocreateout.txt?\n❯1.Yes\n2.No"


class _Screen:
    def __init__(self, text):
        self.text = text
        self.last_user_input = 0.0

    def read_from(self, offset):
        end = len(self.text)
        return ("" if offset >= end else self.text[offset:]), end


@pytest.fixture
def screen(monkeypatch):
    shown = _Screen(BASH_DIALOG)
    monkeypatch.setattr(terminal, "get_pty_session", lambda pty: shown)
    return shown


@pytest.fixture
def typed(tmp_path, monkeypatch, screen):
    monkeypatch.setattr(agent_state, "STATE_DIR", tmp_path / "agent-state")
    agent_state.STATE_DIR.mkdir()
    monkeypatch.setattr(agent_handoff, "_configured_api_keys", lambda: [FAKE_KEY])
    monkeypatch.setattr(prompts, "KEY_PAUSE_SECONDS", 0)
    keys = []
    monkeypatch.setattr(terminal, "write_pty_session", lambda pty, key: keys.append((pty, key)) or True)
    return keys


def _show(payload, state="asking"):
    agent_state.set_state(PTY, state)
    (agent_state.STATE_DIR / (PTY + ".prompt")).write_text(json.dumps(payload), encoding="utf-8")


async def test_the_prompt_comes_from_the_hook_payload_and_is_redacted(typed):
    _show({"tool_name": "Bash", "tool_input": {"command": f"echo {FAKE_KEY}"}})
    shown = await LocalPtyHost().prompt(PTY)
    assert shown.kind == prompts.PERMISSION
    assert FAKE_KEY not in shown.command and "[REDACTED]" in shown.command


async def test_no_prompt_file_means_no_prompt(typed):
    assert await LocalPtyHost().prompt(PTY) is None


async def test_the_keys_are_typed_in_order_and_the_prompt_is_cleared(typed):
    _show(BASH)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    await host.answer(PTY, shown.id, (prompts.DOWN, prompts.ENTER))
    assert typed == [(PTY, prompts.DOWN), (PTY, prompts.ENTER)]
    assert agent_state.read_prompt(PTY) is None
    assert agent_state.read_states([PTY])[PTY]["state"] == "asking"


async def test_a_denied_turn_is_reported_idle_because_the_agent_fires_no_hook(typed):
    _show(BASH)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    await host.answer(PTY, shown.id, (prompts.ESCAPE,), True)
    assert typed == [(PTY, prompts.ESCAPE)]
    assert agent_state.read_states([PTY])[PTY]["state"] == "idle"
    assert agent_state.read_prompt(PTY) is None


async def test_nothing_is_typed_when_the_prompt_changed_since_it_was_shown(typed):
    _show(BASH)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    _show({**BASH, "tool_input": {"command": "rm -rf build"}})
    with pytest.raises(StalePrompt):
        await host.answer(PTY, shown.id, (prompts.ENTER,))
    assert typed == []


async def test_nothing_is_typed_when_the_same_prompt_came_up_again_later(typed):
    _show(BASH)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    path = agent_state.STATE_DIR / (PTY + ".prompt")
    later = path.stat().st_mtime + 30
    os.utime(path, (later, later))
    with pytest.raises(StalePrompt):
        await host.answer(PTY, shown.id, (prompts.ENTER,))
    assert typed == []


@pytest.mark.parametrize("state", ["working", "idle"])
async def test_nothing_is_typed_when_the_agent_is_no_longer_asking(typed, state):
    _show(BASH)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    agent_state.set_state(PTY, state)
    with pytest.raises(StalePrompt):
        await host.answer(PTY, shown.id, (prompts.ENTER,))
    assert typed == []


async def test_nothing_is_typed_when_the_prompt_was_answered_in_the_app(typed):
    _show(BASH)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    agent_state.clear_prompt(PTY)
    with pytest.raises(StalePrompt):
        await host.answer(PTY, shown.id, (prompts.ENTER,))
    assert typed == []


async def test_a_terminal_that_refuses_the_keys_is_an_error_not_a_silent_success(typed, monkeypatch):
    _show(BASH)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    monkeypatch.setattr(terminal, "write_pty_session", lambda pty, key: False)
    with pytest.raises(HostError):
        await host.answer(PTY, shown.id, (prompts.ENTER,))


@pytest.mark.parametrize("text", [AFTER_ENTER, AFTER_ESC, LATER_DIALOG, "", "Doyouwanttoproceed?\n❯1.Yes\n4.No"])
async def test_nothing_is_typed_when_the_terminal_no_longer_shows_that_dialog(typed, screen, text):
    _show(BASH)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    screen.text = text
    with pytest.raises(StalePrompt):
        await host.answer(PTY, shown.id, (prompts.ESCAPE,), True)
    assert typed == []
    assert agent_state.read_states([PTY])[PTY]["state"] == "asking"


async def test_nothing_is_typed_after_the_user_typed_at_the_terminal(typed, screen):
    _show(BASH)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    screen.last_user_input = shown.at + 1
    with pytest.raises(StalePrompt):
        await host.answer(PTY, shown.id, (prompts.ENTER,))
    assert typed == []


async def test_typing_before_the_prompt_appeared_does_not_block_the_answer(typed, screen):
    _show(BASH)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    screen.last_user_input = shown.at - 60
    await host.answer(PTY, shown.id, (prompts.ENTER,))
    assert typed == [(PTY, prompts.ENTER)]


ASK = {"tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Q?", "options": [{"label": "A"}, {"label": "B"}]}]}}


async def test_a_question_is_checked_by_terminal_input_not_by_the_permission_screen(typed, screen):
    _show(ASK)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    screen.text = "a question dialog the permission check knows nothing about"
    await host.answer(PTY, shown.id, (prompts.DOWN, prompts.ENTER))
    assert typed == [(PTY, prompts.DOWN), (PTY, prompts.ENTER)]
    _show(ASK)
    shown = await host.prompt(PTY)
    screen.last_user_input = shown.at + 1
    with pytest.raises(StalePrompt):
        await host.answer(PTY, shown.id, (prompts.ENTER,))


QUESTION_DIALOG = "Q?\n❯1.A\n2.B\n3.Typesomething.\nEntertoselect·↑/↓tonavigate·Esctocancel"


async def test_escape_cancels_a_question_only_while_its_dialog_is_the_last_thing_on_screen(typed, screen):
    _show(ASK)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    screen.text = QUESTION_DIALOG
    await host.answer(PTY, shown.id, (prompts.ESCAPE,), True)
    assert typed == [(PTY, prompts.ESCAPE)]


@pytest.mark.parametrize("after", ["\n✢Marinating…", "\n● Interrupted · What should Claude do instead?"])
async def test_escape_is_not_typed_once_something_is_painted_after_the_question(typed, screen, after):
    _show(ASK)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    screen.text = QUESTION_DIALOG + after
    with pytest.raises(StalePrompt):
        await host.answer(PTY, shown.id, (prompts.ESCAPE,), True)
    assert typed == []


async def test_a_session_that_is_gone_is_an_error(typed, monkeypatch):
    _show(BASH)
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    monkeypatch.setattr(terminal, "get_pty_session", lambda pty: None)
    with pytest.raises(HostError):
        await host.answer(PTY, shown.id, (prompts.ENTER,))


async def test_an_oversize_prompt_file_is_an_app_only_prompt_that_cannot_be_answered(typed):
    agent_state.set_state(PTY, "asking")
    (agent_state.STATE_DIR / (PTY + ".prompt")).write_text("x" * (agent_state.PROMPT_MAX_BYTES + 1), encoding="utf-8")
    shown = await LocalPtyHost().prompt(PTY)
    assert shown.kind == prompts.APP_ONLY and not shown.answerable
    message = prompts.waiting_message("a", "p", shown)
    assert "it is too large to show here" in message and prompts.OPEN_APP_QUESTION in message
    assert isinstance(prompts.resolve(shown, "allow"), prompts.Refused)


async def test_nothing_is_typed_when_the_dialog_on_screen_is_another_tool_call(typed):
    _show({**BASH, "tool_input": {"command": "rm -rf build"}})
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    with pytest.raises(StalePrompt):
        await host.answer(PTY, shown.id, (prompts.ENTER,))
    assert typed == []


async def test_the_dialog_of_the_same_tool_call_is_typed_into_even_when_the_command_wraps(typed, screen):
    long = "pytest tests/test_remote_prompt_flow.py tests/test_remote_session_host.py -k permission -x -q"
    _show({**BASH, "tool_input": {"command": long}})
    screen.text = BASH_DIALOG.replace("echo hi", "pytest tests/test_remote_prompt_flow.py\n│ tests/test_remote_session_host.py\n│ -k permission -x -q")
    host = LocalPtyHost()
    shown = await host.prompt(PTY)
    await host.answer(PTY, shown.id, (prompts.ENTER,))
    assert typed == [(PTY, prompts.ENTER)]


def _terminal_remote_did_not_start():
    from remote.service import ADOPTED, RemoteService, Session
    from remote.session_host import Project, read_prompt

    project = Project(id="Budget", name="Budget", repo_path="C:/repo")
    session = Session(
        id=f"app:{PTY}",
        pty_id=PTY,
        project=project,
        short="Budget",
        vendor_session_id=None,
        created_at=1.0,
        last_activity=1.0,
        from_chat=False,
        kind=ADOPTED,
    )
    session.prompt, session.waiting = read_prompt(PTY), True
    return RemoteService(LocalPtyHost(), default_project=lambda: project), session


async def test_an_allow_for_a_terminal_remote_did_not_start_is_typed_when_its_dialog_is_on_screen(typed):
    _show(BASH)
    service, session = _terminal_remote_did_not_start()
    result = await service.answer_session(session, "allow")
    assert result.keys == (prompts.ENTER,)
    assert typed == [(PTY, prompts.ENTER)]


async def test_an_allow_for_a_terminal_remote_did_not_start_is_not_typed_into_another_dialog(typed, screen):
    from remote.service import PromptGone

    _show(BASH)
    service, session = _terminal_remote_did_not_start()
    screen.text = LATER_DIALOG
    with pytest.raises(PromptGone):
        await service.answer_session(session, "allow")
    assert typed == []
    assert not session.waiting and session.prompt is None


async def test_an_allow_for_a_terminal_remote_did_not_start_is_not_typed_after_its_user_typed(typed, screen):
    from remote.service import PromptGone

    _show(BASH)
    service, session = _terminal_remote_did_not_start()
    screen.last_user_input = session.prompt.at + 1
    with pytest.raises(PromptGone):
        await service.answer_session(session, "allow")
    assert typed == []
