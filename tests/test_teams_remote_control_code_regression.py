"""The legacy "/code <text>" OpenCode relay keeps working next to the "@gator" commands."""

import teams_remote_control as trc


def msg(i, body):
    return {"id": i, "message_type": "message", "body": body, "body_html": ""}


async def poll_twice(monkeypatch, second_batch):
    batches = iter([[msg("1", "old")], second_batch])
    monkeypatch.setattr(trc, "_fetch_self_chat_messages", lambda: next(batches))
    monkeypatch.setattr(trc, "_baselined", False)
    monkeypatch.setattr(trc, "_last_seen_message_id", None)

    import routes.terminal as terminal
    import skills.code_agent.projects as projects

    written = []
    monkeypatch.setattr(terminal, "is_pty_alive", lambda session_id: True)
    monkeypatch.setattr(terminal, "write_pty_session", lambda session_id, data: written.append((session_id, data)) or True)
    monkeypatch.setattr(projects, "get_active_pty_session", lambda: "pty-1")
    await trc._poll_once()
    await trc._poll_once()
    return written


async def test_code_command_is_still_typed_into_the_opencode_terminal(monkeypatch):
    written = await poll_twice(monkeypatch, [msg("2", "/code run the tests"), msg("1", "old")])
    assert written == [("pty-1", "run the tests\r")]


async def test_gator_commands_and_replies_are_never_typed_into_the_opencode_terminal(monkeypatch):
    written = await poll_twice(
        monkeypatch,
        [msg("4", "[Gator - Budget] \U0001F40A /code rm -rf"), msg("3", "@gator list"), msg("2", "@gator /code x"), msg("1", "old")],
    )
    assert written == []
