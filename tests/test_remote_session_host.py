"""The text Gator posts to Teams comes from the agent's transcript, so secrets are redacted first."""

import json
import logging

import agent_handoff
import agent_sessions
from remote.commands import agent_result
from remote.session_host import LocalPtyHost
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


async def test_redacted_text_still_gets_the_3500_character_truncation(monkeypatch):
    host = _host_with_reply(monkeypatch, f"{FAKE_KEY} " + "x" * 5000)
    posted = agent_result("Claude", "demo", "Done.", await host.last_message("pty-1"))
    assert FAKE_KEY not in posted
    assert "Trimmed," in posted


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
    assert agent_sessions._transcript_messages(rec)[-1] == ("assistant", "new answer")
