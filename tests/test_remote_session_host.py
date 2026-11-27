"""The text Gator posts to Teams comes from the agent's transcript, so secrets are redacted first."""

import agent_handoff
import agent_sessions
from remote.commands import agent_reply
from remote.session_host import LocalPtyHost
from routes import terminal
from skills.code_agent import projects

FAKE_KEY = "aigator-fake-api-key"


class _Entry:
    meta = {"project_id": "demo", "agent": "claude", "session_id": "vendor-1"}


def _host_with_reply(monkeypatch, reply):
    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: _Entry())
    monkeypatch.setattr(projects, "get_project", lambda name: {"repo_path": "C:/repo/demo"})
    monkeypatch.setattr(agent_sessions, "find_session", lambda repo, agent, sid: object())
    monkeypatch.setattr(agent_sessions, "_transcript_messages", lambda rec: [("user", "q"), ("assistant", reply)])
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
    posted = agent_reply("Claude", "demo", await host.last_message("pty-1"))
    assert FAKE_KEY not in posted
    assert "truncated" in posted
