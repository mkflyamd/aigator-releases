"""Transcript discovery/rendering, capture, snapshot store."""

import json
import os
import time

import agent_handoff as ah
import generic_agent
import pytest

FAKE = "aigator-fake-api-key"
SK = "sk-" + FAKE


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


@pytest.mark.skipif(os.name != "nt", reason="Windows path spelling only exists on Windows")
def test_codex_transcript_matches_windows_cwd_spellings(tmp_path):
    sessions = tmp_path / ".codex" / "sessions" / "2026" / "11" / "14"
    _jsonl(sessions / "rollout-a.jsonl", [{"type": "session_meta", "payload": {"cwd": r"C:\other"}}])
    _jsonl(sessions / "rollout-b.jsonl", [{"type": "session_meta", "payload": {"cwd": "\\\\?\\C:\\Repo"}}])
    found = ah.find_transcript("codex", r"c:\repo", home=tmp_path)
    assert found is not None and found.name == "rollout-b.jsonl"

def test_codex_transcript_matches_session_meta_cwd(tmp_path):
    sessions = tmp_path / ".codex" / "sessions" / "2026" / "11" / "14"
    repo = tmp_path / "repo"
    _jsonl(sessions / "rollout-a.jsonl", [{"type": "session_meta", "payload": {"cwd": str(tmp_path / "other")}}])
    _jsonl(sessions / "rollout-b.jsonl", [{"type": "session_meta", "payload": {"cwd": str(repo)}}])
    found = ah.find_transcript("codex", str(repo), home=tmp_path)
    assert found is not None and found.name == "rollout-b.jsonl"


def test_codex_scan_skips_first_lines_that_are_not_objects(tmp_path):
    sessions = tmp_path / ".codex" / "sessions" / "2026" / "11" / "14"
    sessions.mkdir(parents=True)
    for name, first in (("rollout-a.jsonl", "[1,2]"), ("rollout-b.jsonl", "5"), ("rollout-c.jsonl", '"x"')):
        (sessions / name).write_text(first + "\n", encoding="utf-8")
    (sessions / "rollout-d.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": "not a dict"}) + "\n", encoding="utf-8"
    )
    _jsonl(sessions / "rollout-e.jsonl", [{"type": "session_meta", "payload": {"cwd": "/r"}}])
    for f in sessions.glob("rollout-[a-d].jsonl"):
        os.utime(f, (time.time() + 60,) * 2)  # newest first, so the scan hits them first
    found = ah.find_transcript("codex", "/r", home=tmp_path)
    assert found is not None and found.name == "rollout-e.jsonl"


def test_render_skips_json_lines_that_are_not_objects(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(
        "[1,2]\n5\n\"x\"\nnull\n"
        + json.dumps({"type": "user", "message": {"content": "keep me"}}) + "\n"
        + json.dumps({"type": "user", "message": "not a dict"}) + "\n",
        encoding="utf-8",
    )
    text, last_user, _ = ah.render_transcript("claude", f)
    assert "## User\nkeep me" in text and last_user == "keep me"
    c = tmp_path / "rollout.jsonl"
    c.write_text(
        "[1]\n7\n"
        + json.dumps({"type": "response_item", "payload": "nope"}) + "\n"
        + json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "add pins"}]}}) + "\n",
        encoding="utf-8",
    )
    text, last_user, _ = ah.render_transcript("codex", c)
    assert "## User\nadd pins" in text and last_user == "add pins"


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


def test_one_line_redacts_before_cutting_at_200():
    red = ah.Redactor([FAKE])
    out = ah._one_line("a" * 195 + FAKE, red)
    assert "aigat" not in out and out == "a" * 195 + "[REDACTED]"[:5]
    out = ah._one_line("a" * 197 + SK, ah.Redactor([SK]))
    assert "sk-" not in out


def test_clip_redacts_before_cutting_at_message_limit():
    key_across_edge = "a" * (ah.MESSAGE_MAX_CHARS - 5) + FAKE + "tail"
    out = ah._clip(key_across_edge, ah.Redactor([FAKE]))
    assert "aigat" not in out and out.endswith(" [truncated]")
    sk_across_edge = "a" * (ah.MESSAGE_MAX_CHARS - 4) + SK + "tail"
    assert "sk-" not in ah._clip(sk_across_edge, ah.Redactor([SK]))


def test_bound_redacts_before_keeping_the_tail(monkeypatch):
    monkeypatch.setattr(ah, "SNAPSHOT_MAX_CHARS", 100)
    text = "x" * 50 + FAKE + "y" * 90  # the 100-char tail starts 10 chars inside the key
    out = ah._bound(text, ah.Redactor([FAKE]))
    assert "api-key" not in out and "ke-api" not in out and out.endswith("y" * 90)
    text = "x" * 50 + SK + "y" * 90
    assert "api-key" not in ah._bound(text, ah.Redactor([SK]))


def test_render_redacts_tool_input_cut_by_the_200_char_clip(tmp_path):
    f = tmp_path / "s.jsonl"
    long_pad = "p" * 170
    _jsonl(f, [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": long_pad + " " + FAKE}},
    ]}}])
    text, _, _ = ah.render_transcript("claude", f, ah.Redactor([FAKE]))
    assert "aigat" not in text and FAKE not in text


class _FakePane:
    def __init__(self, raw):
        self.raw = raw

    def read_from(self, offset):
        return self.raw, len(self.raw)


def test_capture_pane_strips_and_bounds(monkeypatch):
    from routes import terminal
    monkeypatch.setattr(
        terminal, "get_pty_session", lambda sid: _FakePane("\x1b[31m" + "a" * 50_000 + "\x1b[0m")
    )
    out = ah.capture_pane("s1")
    assert len(out) == ah.CAPTURE_MAX_CHARS and "\x1b" not in out


@pytest.mark.parametrize("key", [FAKE, SK])
def test_capture_pane_redacts_a_key_straddling_the_tail_edge(monkeypatch, key):
    from routes import terminal

    cut = 10  # the final 36000 chars begin 10 chars into the key
    raw = "a" * 5000 + key + "b" * (ah.CAPTURE_MAX_CHARS - cut)
    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: _FakePane(raw))
    red = ah.Redactor([key])
    out = ah.capture_pane("s1", red)
    assert "api-key" not in out and "ke-api" not in out
    assert len(out) <= ah.CAPTURE_MAX_CHARS and red.count == 1


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
    assert ah.load_handoff("0" * 32 + "\n") is None
    (tmp_path / ("0" * 32 + ".json")).write_text("{}", encoding="utf-8")
    assert ah.load_handoff("0" * 32 + "\n") is None  # would resolve to the file above without fullmatch


def test_save_handoff_redacts_a_key_across_the_last_message_clip(tmp_path, monkeypatch):
    monkeypatch.setattr(ah, "HANDOFF_DIR", tmp_path / "h")
    last_user = "a" * (ah.MESSAGE_MAX_CHARS - 5) + FAKE + "tail"
    rec = ah.save_handoff(
        source_agent="claude", project_id="demo", cwd="/r", source_kind="capture",
        text="x", last_user=last_user, last_assistant=last_user, api_key=FAKE,
    )
    assert "aigat" not in rec["last_user_message"] and "aigat" not in rec["prompt"]


def test_load_handoff_treats_old_records_as_expired(tmp_path, monkeypatch):
    monkeypatch.setattr(ah, "HANDOFF_DIR", tmp_path / "h")
    rec = ah.save_handoff(
        source_agent="claude", project_id="demo", cwd="/r", source_kind="capture",
        text="hello", last_user="", last_assistant="",
    )
    record = tmp_path / "h" / f"{rec['handoff_id']}.json"
    os.utime(record, (time.time() - ah.HANDOFF_TTL_SECONDS + 3600,) * 2)
    assert ah.load_handoff(rec["handoff_id"]) == rec
    os.utime(record, (time.time() - ah.HANDOFF_TTL_SECONDS - 60,) * 2)
    assert ah.load_handoff(rec["handoff_id"]) is None


def test_purge_expired_swallows_listing_errors(monkeypatch):
    class Unreadable:
        def is_dir(self):
            return True

        def iterdir(self):
            raise PermissionError("denied")

    monkeypatch.setattr(ah, "HANDOFF_DIR", Unreadable())
    assert ah.purge_expired() == 0


def test_purge_expired_removes_only_old_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ah, "HANDOFF_DIR", tmp_path)
    old, new = tmp_path / "old.txt", tmp_path / "new.txt"
    old.write_text("x")
    new.write_text("y")
    os.utime(old, (time.time() - 8 * 86400,) * 2)
    assert ah.purge_expired() == 1
    assert not old.exists() and new.exists()


def _prepare_env(tmp_path, monkeypatch, keys=()):
    monkeypatch.setattr(ah, "HANDOFF_DIR", tmp_path / "h")
    monkeypatch.setattr(ah, "_configured_api_keys", lambda: list(keys))
    monkeypatch.setattr(ah, "_session_started_at", lambda sid: None)


def test_prepare_handoff_redacts_every_configured_key(tmp_path, monkeypatch):
    _prepare_env(tmp_path, monkeypatch, [FAKE, SK])
    monkeypatch.setattr(ah, "find_transcript", lambda agent, cwd, home=None, **kw: None)
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: red(f"one {FAKE} two {SK}"))
    rec = ah.prepare_handoff("crush", "demo", "/r", "s1")
    snap = (tmp_path / "h" / f"{rec['handoff_id']}.txt").read_text(encoding="utf-8")
    assert snap == "one [REDACTED] two [REDACTED]" and rec["redactions"] == 2


def test_prepare_handoff_falls_back_to_capture(tmp_path, monkeypatch):
    _prepare_env(tmp_path, monkeypatch, [FAKE])
    monkeypatch.setattr(ah, "find_transcript", lambda agent, cwd, home=None, **kw: None)
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: f"pane {FAKE}")
    rec = ah.prepare_handoff("opencode-bare", "demo", "/r", "s1")
    assert rec["source_kind"] == "capture" and rec["redactions"] == 1


def test_prepare_handoff_empty_everything_raises(tmp_path, monkeypatch):
    _prepare_env(tmp_path, monkeypatch)
    monkeypatch.setattr(ah, "find_transcript", lambda agent, cwd, home=None, **kw: None)
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: "  ")
    with pytest.raises(ah.NothingToHandOff):
        ah.prepare_handoff("crush", "demo", "/r", "s1")


def test_prepare_handoff_uses_transcript_and_counts_its_redactions(tmp_path, monkeypatch):
    _prepare_env(tmp_path, monkeypatch, [FAKE])
    f = tmp_path / "s.jsonl"
    _jsonl(f, [{"type": "user", "message": {"content": f"use {FAKE}"}}])
    monkeypatch.setattr(ah, "find_transcript", lambda agent, cwd, home=None, **kw: f)
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: "should not be used")
    rec = ah.prepare_handoff("claude", "demo", "/r", "s1")
    snap = (tmp_path / "h" / f"{rec['handoff_id']}.txt").read_text(encoding="utf-8")
    assert rec["source_kind"] == "transcript" and FAKE not in snap and "[REDACTED]" in snap
    assert rec["redactions"] == 2  # the snapshot line and the last-user message


def test_prepare_handoff_falls_back_to_capture_when_rendering_raises(tmp_path, monkeypatch):
    _prepare_env(tmp_path, monkeypatch)
    f = tmp_path / "s.jsonl"
    _jsonl(f, [{"type": "user", "message": {"content": "hi"}}])
    monkeypatch.setattr(ah, "find_transcript", lambda agent, cwd, home=None, **kw: f)

    def boom(agent, path, red=None):
        raise AttributeError("'list' object has no attribute 'get'")

    monkeypatch.setattr(ah, "render_transcript", boom)
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: "pane text")
    rec = ah.prepare_handoff("claude", "demo", "/r", "s1")
    assert rec["source_kind"] == "capture"


def test_prepare_handoff_passes_the_pinned_id_and_start_time_to_the_lookup(tmp_path, monkeypatch):
    import generic_agent

    _prepare_env(tmp_path, monkeypatch)
    f = tmp_path / "s.jsonl"
    _jsonl(f, [{"type": "user", "message": {"content": "this tab's work"}}])
    seen = {}

    def fake_find(agent, cwd, home=None, **kw):
        seen.update(kw)
        return f

    monkeypatch.setattr(ah, "_session_started_at", lambda sid: 100.0)
    monkeypatch.setattr(ah, "find_transcript", fake_find)
    monkeypatch.setattr(generic_agent, "pinned_session_id", lambda sid: "abc")
    assert ah.prepare_handoff("claude", "demo", "/r", "s1")["source_kind"] == "transcript"
    assert seen == {"session_id": "abc", "started_at": 100.0}


def test_prepare_handoff_reads_the_pane_when_no_transcript_is_attributable(tmp_path, monkeypatch):
    _prepare_env(tmp_path, monkeypatch)
    monkeypatch.setattr(ah, "find_transcript", lambda agent, cwd, home=None, **kw: None)
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: "pane text")
    assert ah.prepare_handoff("claude", "demo", "/r", "s1")["source_kind"] == "capture"


def _claude_dir(home, cwd="/r"):
    d = home / ".claude" / "projects" / ah._claude_slug(cwd)
    d.mkdir(parents=True)
    return d


def test_a_pinned_claude_session_beats_a_newer_transcript_from_another_session(tmp_path):
    d = _claude_dir(tmp_path)
    mine = d / "aaaa.jsonl"
    other = d / "bbbb.jsonl"
    _jsonl(mine, [{"type": "user", "message": {"content": "mine"}}])
    _jsonl(other, [{"type": "user", "message": {"content": "other tab"}}])
    os.utime(mine, (time.time() - 600,) * 2)
    assert ah.find_transcript("claude", "/r", tmp_path, session_id="aaaa") == mine
    assert ah.find_transcript("claude", "/r", tmp_path, session_id="cccc") is None


def test_an_unpinned_lookup_needs_exactly_one_transcript_since_the_session_started(tmp_path, monkeypatch):
    d = _claude_dir(tmp_path)
    one = d / "one.jsonl"
    two = d / "two.jsonl"
    _jsonl(one, [{"type": "user", "message": {"content": "x"}}])
    monkeypatch.setattr(ah, "_born", lambda f: {"one.jsonl": 1000.0, "two.jsonl": 1010.0}[f.name])
    assert ah.find_transcript("claude", "/r", tmp_path, started_at=990.0) == one
    assert ah.find_transcript("claude", "/r", tmp_path, started_at=1500.0) is None
    _jsonl(two, [{"type": "user", "message": {"content": "y"}}])
    assert ah.find_transcript("claude", "/r", tmp_path, started_at=990.0) is None
    assert ah.find_transcript("claude", "/r", tmp_path, started_at=1008.0) == two


def test_session_started_at_reads_the_pty_session(monkeypatch):
    from routes import terminal

    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: _FakePane("x"))
    assert ah._session_started_at("s1") is None
    pane = _FakePane("x")
    pane.created_at = 123.5
    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: pane)
    assert ah._session_started_at("s1") == 123.5
    monkeypatch.setattr(terminal, "get_pty_session", lambda sid: None)
    assert ah._session_started_at("s1") is None


def test_pty_session_records_its_start_time():
    from pty_session import PtySession

    class DeadPty:
        def isalive(self):
            return False

    before = time.time()
    s = PtySession(DeadPty())
    assert before <= s.created_at <= time.time()


def _crush_project(tmp_path, sessions, messages):
    from tests.test_agent_session_stores import make_crush

    make_crush(tmp_path, sessions, messages)
    return str(tmp_path)


def _crush_msgs(session, *turns):
    out = []
    for i, (role, parts) in enumerate(turns, 1):
        out.append((f"{session}-{i}", session, role, json.dumps(parts), i))
    return out


def _text(t):
    return {"type": "text", "data": {"text": t}}


def test_crush_handoff_reads_its_own_session_store_not_the_pane(tmp_path, monkeypatch):
    _prepare_env(tmp_path / "h", monkeypatch, [FAKE])
    cwd = _crush_project(
        tmp_path / "proj",
        [("s1", None, "T", 3, 100, 200)],
        _crush_msgs(
            "s1",
            ("user", [_text(f"use {FAKE} to fix the loader")]),
            ("assistant", [{"type": "tool_call", "data": {"name": "bash", "input": '{"command": "git status"}'}}]),
            ("assistant", [_text("Loader fixed.")]),
        ),
    )
    monkeypatch.setattr(ah, "_session_started_at", lambda sid: 150.0)
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: "garbled repaint frames")
    rec = ah.prepare_handoff("crush", "demo", cwd, "s1")
    snap = (tmp_path / "h" / "h" / f"{rec['handoff_id']}.txt").read_text(encoding="utf-8")
    assert rec["source_kind"] == "transcript" and "garbled" not in snap
    assert "## User\nuse [REDACTED] to fix the loader" in snap
    assert "- tool bash:" in snap and "git status" in snap
    assert "## Assistant\nLoader fixed." in snap
    assert rec["last_user_message"].startswith("use [REDACTED]")


def test_crush_handoff_picks_the_session_active_since_this_terminal_started(tmp_path, monkeypatch):
    _prepare_env(tmp_path / "h", monkeypatch)
    cwd = _crush_project(
        tmp_path / "proj",
        [("old", None, "Old", 1, 10, 20), ("mine", None, "Mine", 1, 300, 400)],
        _crush_msgs("old", ("user", [_text("an old chat")])) + _crush_msgs("mine", ("user", [_text("this tab")])),
    )
    monkeypatch.setattr(ah, "_session_started_at", lambda sid: 290.0)
    rec = ah.prepare_handoff("crush", "demo", cwd, "s1")
    snap = (tmp_path / "h" / "h" / f"{rec['handoff_id']}.txt").read_text(encoding="utf-8")
    assert "this tab" in snap and "an old chat" not in snap


def test_crush_handoff_does_not_guess_between_two_sessions_active_since_start(tmp_path, monkeypatch):
    _prepare_env(tmp_path / "h", monkeypatch)
    cwd = _crush_project(
        tmp_path / "proj",
        [("mine", None, "Mine", 1, 300, 400), ("other", None, "Other", 1, 310, 420)],
        _crush_msgs("mine", ("user", [_text("this tab")])) + _crush_msgs("other", ("user", [_text("another terminal")])),
    )
    monkeypatch.setattr(ah, "_session_started_at", lambda sid: 290.0)
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: "pane text")
    rec = ah.prepare_handoff("crush", "demo", cwd, "s1")
    assert rec["source_kind"] == "capture"


def test_crush_handoff_uses_the_session_this_terminal_resumed(tmp_path, monkeypatch):
    _prepare_env(tmp_path / "h", monkeypatch)
    cwd = _crush_project(
        tmp_path / "proj",
        [("mine", None, "Mine", 1, 10, 20), ("other", None, "Other", 1, 310, 420)],
        _crush_msgs("mine", ("user", [_text("this tab")])) + _crush_msgs("other", ("user", [_text("another terminal")])),
    )
    monkeypatch.setattr(ah, "_session_started_at", lambda sid: 290.0)
    monkeypatch.setattr(generic_agent, "linked_session_id", lambda sid: "mine" if sid == "s1" else None)
    rec = ah.prepare_handoff("crush", "demo", cwd, "s1")
    snap = (tmp_path / "h" / "h" / f"{rec['handoff_id']}.txt").read_text(encoding="utf-8")
    assert "this tab" in snap and "another terminal" not in snap


def test_crush_handoff_falls_back_to_the_pane_without_a_session_since_start(tmp_path, monkeypatch):
    _prepare_env(tmp_path / "h", monkeypatch)
    cwd = _crush_project(
        tmp_path / "proj", [("old", None, "Old", 1, 10, 20)], _crush_msgs("old", ("user", [_text("an old chat")]))
    )
    monkeypatch.setattr(ah, "_session_started_at", lambda sid: 290.0)
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: "pane text")
    assert ah.prepare_handoff("crush", "demo", cwd, "s1")["source_kind"] == "capture"


def test_crush_handoff_falls_back_to_the_pane_for_a_corrupt_database(tmp_path, monkeypatch):
    _prepare_env(tmp_path / "h", monkeypatch)
    (tmp_path / "proj" / ".crush").mkdir(parents=True)
    (tmp_path / "proj" / ".crush" / "crush.db").write_bytes(b"not a database")
    monkeypatch.setattr(ah, "capture_pane", lambda sid, red=None: "pane text")
    assert ah.prepare_handoff("crush", "demo", str(tmp_path / "proj"), "s1")["source_kind"] == "capture"
