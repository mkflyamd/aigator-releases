"""Transcript discovery/rendering, capture, snapshot store."""

import json
import os
import time

import agent_handoff as ah
import pytest

FAKE = "aigator-fake-api-key"


def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_claude_slug_matches_directory_case_insensitively(tmp_path):
    proj = tmp_path / ".claude" / "projects" / "c--users-me-pocs-app"  # lower-cased dir
    _jsonl(proj / "old.jsonl", [{"type": "user"}])
    _jsonl(proj / "new.jsonl", [{"type": "user"}])
    os.utime(proj / "old.jsonl", (1, 1))
    found = ah.find_transcript("claude", r"C:\Users\me\POCs\app", home=tmp_path)
    assert found is not None and found.name == "new.jsonl"


def test_claude_transcript_missing_returns_none(tmp_path):
    assert ah.find_transcript("claude", "/x/y", home=tmp_path) is None


def test_codex_transcript_matches_session_meta_cwd(tmp_path):
    sessions = tmp_path / ".codex" / "sessions" / "2026" / "11" / "14"
    _jsonl(sessions / "rollout-a.jsonl", [{"type": "session_meta", "payload": {"cwd": r"C:\other"}}])
    _jsonl(sessions / "rollout-b.jsonl", [{"type": "session_meta", "payload": {"cwd": "\\\\?\\C:\\Repo"}}])
    found = ah.find_transcript("codex", r"c:\repo", home=tmp_path)
    assert found is not None and found.name == "rollout-b.jsonl"


def test_other_agents_have_no_transcript(tmp_path):
    assert ah.find_transcript("crush", "/r", home=tmp_path) is None
    assert ah.find_transcript("opencode-bare", "/r", home=tmp_path) is None


def test_render_claude_keeps_turns_and_one_line_tools(tmp_path):
    f = tmp_path / "s.jsonl"
    _jsonl(f, [
        {"type": "user", "message": {"content": "fix the bug"}},
        {"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "Looking at foo.py"},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "foo.py"}},
        ]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "BIG OUTPUT"}]}},
        {"type": "attachment"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done, tests pass"}]}},
    ])
    text, last_user, last_assistant = ah.render_transcript("claude", f)
    assert "## User\nfix the bug" in text
    assert "## Assistant\nLooking at foo.py" in text
    assert '- tool Read: {"file_path": "foo.py"}' in text
    assert "BIG OUTPUT" not in text and "hmm" not in text
    assert last_user == "fix the bug" and last_assistant == "Done, tests pass"


def test_render_codex_skips_context_and_developer_messages(tmp_path):
    f = tmp_path / "rollout.jsonl"
    _jsonl(f, [
        {"type": "session_meta", "payload": {"cwd": "/r"}},
        {"type": "response_item", "payload": {"type": "message", "role": "developer",
            "content": [{"type": "input_text", "text": "<permissions instructions>"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "<environment_context>\n<cwd>/r</cwd>"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "add pins"}]}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "shell_command",
            "arguments": "{\"command\":\"ls\"}"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "Added pins"}]}},
    ])
    text, last_user, last_assistant = ah.render_transcript("codex", f)
    assert "permissions" not in text and "environment_context" not in text
    assert "## User\nadd pins" in text and "- tool shell_command:" in text
    assert last_user == "add pins" and last_assistant == "Added pins"


def test_render_bounds_to_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(ah, "SNAPSHOT_MAX_CHARS", 100)
    f = tmp_path / "s.jsonl"
    _jsonl(f, [{"type": "user", "message": {"content": "x" * 500}},
               {"type": "user", "message": {"content": "tail-marker"}}])
    text, _, _ = ah.render_transcript("claude", f)
    assert text.startswith("[earlier content omitted]") and "tail-marker" in text
    assert len(text) < 200


def test_capture_pane_strips_and_bounds(monkeypatch):
    class Fake:
        def read_from(self, offset):
            return "\x1b[31m" + "a" * 50_000 + "\x1b[0m", 50_000

    from routes import terminal
    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: Fake())
    out = ah.capture_pane("s1")
    assert len(out) == ah.CAPTURE_MAX_CHARS and "\x1b" not in out


def test_capture_pane_unknown_session_is_empty(monkeypatch):
    from routes import terminal
    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: None)
    assert ah.capture_pane("nope") == ""


def test_save_and_load_handoff_redacts_and_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(ah, "HANDOFF_DIR", tmp_path / "handoffs")
    rec = ah.save_handoff(
        source_agent="claude", project_id="demo", cwd="/r", source_kind="transcript",
        text=f"key {FAKE} here", last_user=f"use {FAKE}", last_assistant="ok", api_key=FAKE,
    )
    assert rec["redactions"] == 2
    snap = (tmp_path / "handoffs" / f"{rec['handoff_id']}.txt").read_text(encoding="utf-8")
    assert FAKE not in snap and FAKE not in rec["prompt"]
    assert str(tmp_path / "handoffs" / f"{rec['handoff_id']}.txt") in rec["prompt"]
    assert ah.load_handoff(rec["handoff_id"]) == rec


def test_load_handoff_rejects_bad_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(ah, "HANDOFF_DIR", tmp_path)
    assert ah.load_handoff("../../etc/passwd") is None
    assert ah.load_handoff("0" * 32) is None


def test_purge_expired_removes_only_old_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ah, "HANDOFF_DIR", tmp_path)
    old, new = tmp_path / "old.txt", tmp_path / "new.txt"
    old.write_text("x")
    new.write_text("y")
    os.utime(old, (time.time() - 8 * 86400,) * 2)
    assert ah.purge_expired() == 1
    assert not old.exists() and new.exists()


def test_prepare_handoff_falls_back_to_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(ah, "HANDOFF_DIR", tmp_path / "h")
    monkeypatch.setattr(ah, "_active_api_key", lambda: FAKE)
    monkeypatch.setattr(ah, "find_transcript", lambda agent, cwd, home=None: None)
    monkeypatch.setattr(ah, "capture_pane", lambda sid: f"pane {FAKE}")
    rec = ah.prepare_handoff("opencode-bare", "demo", "/r", "s1")
    assert rec["source_kind"] == "capture" and rec["redactions"] == 1


def test_prepare_handoff_empty_everything_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(ah, "HANDOFF_DIR", tmp_path / "h")
    monkeypatch.setattr(ah, "_active_api_key", lambda: None)
    monkeypatch.setattr(ah, "find_transcript", lambda agent, cwd, home=None: None)
    monkeypatch.setattr(ah, "capture_pane", lambda sid: "  ")
    with pytest.raises(ah.NothingToHandOff):
        ah.prepare_handoff("crush", "demo", "/r", "s1")
