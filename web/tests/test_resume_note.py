"""A turn that stopped early or left a host command unread is described to the next turn."""

import json
import pathlib

from conversation_store import INTERRUPTED_MSG
from resume_note import resume_note

CHAT_SRC = (pathlib.Path(__file__).parent.parent / "routes" / "chat.py").read_text(encoding="utf-8")


def _call(name, tid, inp=None):
    return {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp or {}}]}


def _result(tid, payload):
    return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": json.dumps(payload)}]}


def _text(role, text):
    return {"role": role, "content": text}


def test_a_turn_that_finished_cleanly_needs_no_note():
    history = [
        _text("user", "list my files"),
        _call("list_files", "a"), _result("a", {"files": []}),
        _text("assistant", "You have no files."),
    ]
    assert resume_note(history) == ""
    assert resume_note([]) == ""


def test_an_interrupted_turn_names_the_request_and_what_already_ran():
    history = [
        _text("user", "record the demo video"),
        _call("run_shell", "a"), _result("a", {"exit_code": 0}),
        _call("read_file", "b"), _result("b", {"error": "no such file"}),
        _text("assistant", INTERRUPTED_MSG),
    ]
    note = resume_note(history)
    assert "record the demo video" in note
    assert "run_shell: ok" in note and "read_file: failed" in note
    assert "cut off before it finished" in note


def test_a_host_command_nobody_has_read_yet_is_called_out():
    history = [
        _text("user", "serve the demo folder"),
        _call("run_on_host", "a"),
        _result("a", {"status": "awaiting_user_click", "request_id": "5dddd2e1d18f41e8947ea7217a64762a"}),
        _text("assistant", "Click Run on the card."),
    ]
    note = resume_note(history)
    assert "5dddd2e1d18f41e8947ea7217a64762a" in note  # pragma: allowlist secret
    assert "host_command_result" in note


def test_a_host_command_whose_result_was_read_is_not_called_out():
    history = [
        _text("user", "serve the demo folder"),
        _call("run_on_host", "a"),
        _result("a", {"status": "awaiting_user_click", "request_id": "5dddd2e1d18f41e8947ea7217a64762a"}),
        _call("host_command_result", "b", {"request_id": "5dddd2e1d18f41e8947ea7217a64762a"}),
        _result("b", {"status": "done"}),
        _text("assistant", "It is serving."),
    ]
    assert resume_note(history) == ""


def test_only_the_last_turn_is_described():
    history = [
        _text("user", "old request"),
        _call("run_shell", "a"), _result("a", {"error": "boom"}),
        _text("assistant", INTERRUPTED_MSG),
        _text("user", "new request"),
        _text("assistant", "Done."),
    ]
    assert resume_note(history) == ""


def test_openai_style_history_is_understood():
    history = [
        _text("user", "serve the demo folder"),
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "run_on_host", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1",
         "content": json.dumps({"status": "awaiting_user_click", "request_id": "abc123"})},
    ]
    assert "abc123" in resume_note(history)


def test_the_note_is_added_to_the_system_prompt_of_the_turn():
    assert "resume_note(history_window)" in CHAT_SRC
