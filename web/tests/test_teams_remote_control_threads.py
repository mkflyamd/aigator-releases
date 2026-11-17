import asyncio
import threading

import teams_remote_control as trc

def test_relay_calls_the_pty_off_the_event_loop_thread(monkeypatch):
    loop_thread = {}
    seen = {}

    def msg(i, body):
        return {"id": i, "message_type": "message", "body": body, "body_html": ""}

    batches = iter([[msg("1", "old")], [msg("2", "/code ls"), msg("1", "old")]])
    monkeypatch.setattr(trc, "_fetch_self_chat_messages", lambda: next(batches))
    monkeypatch.setattr(trc, "_baselined", False)
    monkeypatch.setattr(trc, "_last_seen_message_id", None)

    import routes.terminal as terminal
    import skills.code_agent.projects as projects

    def alive(session_id):
        seen["alive"] = threading.get_ident()
        return True

    def write(session_id, data):
        seen["write"] = threading.get_ident()
        return True

    monkeypatch.setattr(terminal, "is_pty_alive", alive)
    monkeypatch.setattr(terminal, "write_pty_session", write)
    monkeypatch.setattr(projects, "get_active_pty_session", lambda: "pty-1")

    async def run():
        loop_thread["id"] = threading.get_ident()
        await trc._poll_once()
        await trc._poll_once()

    asyncio.run(run())

    assert seen["alive"] != loop_thread["id"]
    assert seen["write"] != loop_thread["id"]
