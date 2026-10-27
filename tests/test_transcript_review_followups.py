"""Regression tests for the PR #91 review follow-ups."""

import os
import re
import sys
import uuid
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import app  # noqa: E402
import data_sources  # noqa: E402
import shared  # noqa: E402
from routes.chat import ChatRequest, _blocked_gated_deps, _filter_tools  # noqa: E402
from skills._m365 import file_transfer as ft  # noqa: E402
from skills.teams import transcripts  # noqa: E402

APP_JS = os.path.join(os.path.dirname(__file__), "..", "web", "static", "app.js")


def _tool_names(tools):
    return {t.get("name") for t in tools}


# 1. A runner chosen directly is gated like one pulled in as a dependency.

def test_a_runner_chosen_directly_is_blocked_until_approved():
    req = ChatRequest(message="hi", context_id="ctx-" + uuid.uuid4().hex)
    blocked = _blocked_gated_deps(["shell_runner"], req)
    assert [(sid, dep["id"]) for sid, dep in blocked] == [("shell_runner", "shell_runner")]
    assert blocked[0][1]["reason"]


def test_an_approved_runner_is_not_blocked():
    ctx = "ctx-" + uuid.uuid4().hex
    data_sources.allow(ctx, "capability:shell_runner")
    assert _blocked_gated_deps(["shell_runner"], ChatRequest(message="hi", context_id=ctx)) == []


def test_an_unapproved_runner_chosen_directly_offers_no_runner_tools():
    offered = _tool_names(_filter_tools(None, False, ["code_runner", "shell_runner"], unapproved_deps=["code_runner", "shell_runner"]))
    assert "run_python" not in offered and "run_shell" not in offered
    approved = _tool_names(_filter_tools(None, False, ["code_runner", "shell_runner"], unapproved_deps=[]))
    assert "run_python" in approved and "run_shell" in approved


# 2. A scheduled run dispatches a direct intent only for an approved skill.

def test_a_direct_intent_for_an_unapproved_skill_is_not_dispatched():
    intent = {"skill": "code_runner", "tool": "run_python"}
    assert not app._direct_intent_in_approved_skills(intent, ["email"], "run this")
    assert app._direct_intent_in_approved_skills(intent, ["email", "code_runner"], "run this")


def test_a_direct_intent_for_a_tool_of_an_approved_skill_is_dispatched():
    tool = sorted(shared.SKILL_TOOLS_MAP["calendar"])[0]
    assert app._direct_intent_in_approved_skills({"skill": "other", "tool": tool}, ["calendar"], "x")


# 3. Opaque Graph ids are encoded.

class _RecordingGC:
    def __init__(self):
        self.paths = []

    def get(self, path, **kw):
        self.paths.append(path)
        return {"value": []}

    def get_text(self, path, **kw):
        self.paths.append(path)
        return "WEBVTT"


def test_transcript_ids_are_url_encoded(monkeypatch):
    beta = transcripts._tx_load("transcript_beta")
    gc = _RecordingGC()
    monkeypatch.setattr(beta, "get_graph_client", lambda: gc)
    beta.list_transcripts("b!dr/ive", "01A/B?x=1")
    beta.fetch_transcript_content("b!dr/ive", "01A/B?x=1", "t/../id?y")
    for path in gc.paths:
        assert "01A/B" not in path and "?" not in path
        assert "/drives/b%21dr%2Five/items/01A%2FB%3Fx%3D1/media/transcripts" in path
    assert gc.paths[1].endswith("/t%2F..%2Fid%3Fy/content")


# 4. A schedule that needs a runner names it on the approval card and stores it on the job.

async def _card_and_inputs(inputs):
    import asyncio
    import agent_loop
    from browser_agent import resolve_browser_confirm

    cards, q = [], asyncio.Queue()

    async def execute_tool(name, args):
        return {"ok": True}

    run, _, _ = agent_loop._make_tool_runner(
        execute_tool, frozenset(), {}, lambda n, r: None, "safe", context_id="tab-a", offered_names=None
    )

    async def answer():
        while True:
            evt = await asyncio.wait_for(q.get(), 5)
            if evt["kind"] == "browser_confirm":
                cards.append(evt)
                resolve_browser_confirm(evt["confirm_id"], False)
                return

    tc = SimpleNamespace(id="c1", name="schedule_task", inputs=inputs)
    await asyncio.gather(run(tc, q), answer())
    return cards[0]["action"]


async def test_a_schedule_whose_skill_needs_a_runner_discloses_and_stores_it(monkeypatch):
    monkeypatch.setitem(shared.SKILL_PROMPTS, "needs-runner-skill", "steps")
    monkeypatch.setitem(shared.SKILL_DEPENDENCIES_MAP, "needs-runner-skill", [{"id": "code_runner", "reason": "x"}])
    inputs = {
        "name": "Nightly", "prompt": "Run the nightly job.", "trigger_type": "cron", "cron_hour": 9,
        "skills": ["needs-runner-skill"],
    }
    action = await _card_and_inputs(inputs)
    assert inputs["skills"] == ["needs-runner-skill", "code_runner"]
    assert "run code or commands on your computer" in action
    assert "code_runner (needed by needs-runner-skill)" in action


async def test_a_schedule_without_a_runner_need_has_no_runner_line():
    inputs = {"name": "Mail", "prompt": "Check the inbox.", "trigger_type": "cron", "cron_hour": 9, "skills": ["email"]}
    action = await _card_and_inputs(inputs)
    assert "run code or commands" not in action
    assert "code_runner" not in inputs["skills"]


# 5 and 6. The approved retry re-sends the exact request; a reconnecting stream is not finished.

def _app_js():
    with open(APP_JS, encoding="utf-8-sig") as f:
        return f.read()


def test_the_approved_retry_resends_the_exact_posted_body():
    src = _app_js()
    assert "_permissionResendPayload = _postBody;" in src
    assert src.index("_permissionResendPayload = _postBody;") < src.index("fetch('/api/chat', {\r\n" if "\r\n" in src else "fetch('/api/chat', {\n", src.index("const _postBody"))
    assert not re.search(r"let _permissionResendPayload = \{", src)


def test_a_reconnecting_event_source_does_not_finish_the_stream():
    src = _app_js()
    start = src.index("es.onerror = () => {", src.index("/api/chat/stream/"))
    body = src[start:start + 600]
    closed = body.index("if (es.readyState === EventSource.CLOSED) {")
    assert body.index("_streamOver = true;") > closed
    assert body.index("_isStreaming = false;") > closed


# 7 and 8. Event times are read in UTC; a failed lookup is not reported as "no transcript".

VTT = b"WEBVTT"


class _EventGC:
    def __init__(self, event):
        self.event = event
        self.kwargs = []

    def get(self, path, params=None, **kw):
        self.kwargs.append(kw)
        return self.event


class _Err(Exception):
    def __init__(self, status_code):
        super().__init__(f"Graph API {status_code}")
        self.status_code = status_code


def _rec(item="i1", drive="d1", has=True):
    return SimpleNamespace(
        drive_id=drive, item_id=item, title="Sync", original_name="x.mp4", has_transcript=has,
        share_url="s", web_url="https://sp/x", created_at="2026-10-19T15:40:00Z",
    )


@pytest.fixture
def wired(monkeypatch):
    state = SimpleNamespace(recs=[_rec()], listing=lambda d, i: [], gc=None)
    state.gc = _EventGC({
        "subject": "Sync",
        "start": {"dateTime": "2026-10-19T15:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-10-19T15:34:00.0000000", "timeZone": "UTC"},
        "onlineMeeting": {"joinUrl": "https://teams/l/meetup-join/19%3ameeting_abc%40thread.v2/0"},
    })
    recording = SimpleNamespace(
        chat_id_from_join_url=lambda url: "19:meeting_abc@thread.v2" if url else None,
        resolve_recordings_from_chat=lambda chat: state.recs,
    )
    beta = SimpleNamespace(list_transcripts=lambda d, i: state.listing(d, i))
    monkeypatch.setattr(transcripts, "_tx_load", lambda name: {"transcript_recording": recording, "transcript_beta": beta}[name])
    monkeypatch.setattr(transcripts, "_graph", lambda: state.gc)
    return state


def test_the_event_is_requested_in_utc(wired):
    transcripts._tool_find_meeting_transcripts("EV1")
    assert wired.gc.kwargs[0]["extra_headers"] == {"Prefer": 'outlook.timezone="UTC"'}


def test_a_naive_time_is_read_in_its_own_zone_not_assumed_utc():
    la = transcripts._tx_parse_dt({"dateTime": "2026-10-19T08:00:00", "timeZone": "America/Los_Angeles"})
    assert la.utcoffset().total_seconds() == -7 * 3600
    assert transcripts._tx_parse_dt({"dateTime": "2026-10-19T08:00:00", "timeZone": "UTC"}).utcoffset().total_seconds() == 0
    assert transcripts._tx_parse_dt({"dateTime": "2026-10-19T08:00:00", "timeZone": "No Such Zone"}) is None


def test_a_missing_transcript_listing_is_no_transcript(wired):
    def gone(d, i):
        raise _Err(404)

    wired.listing = gone
    out = transcripts._tool_find_meeting_transcripts("EV1")
    assert "no_transcript" in out["status"] and "error" not in out


@pytest.mark.parametrize("status", [401, 403, 429, 0])
def test_a_failed_listing_is_reported_as_a_failure_not_no_transcript(wired, status):
    def broken(d, i):
        raise _Err(status)

    wired.listing = broken
    out = transcripts._tool_find_meeting_transcripts("EV1")
    assert out["error"] == "transcript_lookup_failed"
    assert "status" not in out
    assert "do not say there is no transcript" in out["hint"]


def test_a_recording_that_could_not_be_opened_is_a_failure_not_no_transcript(wired):
    wired.recs = [_rec(item="", drive="")]
    out = transcripts._tool_find_meeting_transcripts("EV1")
    assert out["error"] == "transcript_lookup_failed"


def test_a_found_transcript_is_still_returned_when_another_recording_failed(wired):
    wired.recs = [_rec(item="bad"), _rec(item="good")]

    def listing(d, i):
        if i == "bad":
            raise _Err(429)
        return [{"id": "T1", "createdDateTime": "2026-10-19T15:40:00Z"}]

    wired.listing = listing
    out = transcripts._tool_find_meeting_transcripts("EV1")
    assert "error" not in out
    assert any(r["transcripts"] for r in out["recordings"])


# 9. An existing file counts as saved only when it is the whole file.

class _ExistingGC:
    def __init__(self, size):
        self.size = size

    def get(self, path, params=None, **kw):
        if "/root:/" in path and path.endswith("m.vtt"):
            return {"id": "f", "name": "m.vtt", "size": self.size, "webUrl": "https://od/m.vtt"}
        return {"id": "folder", "folder": {}}


def test_an_existing_file_of_the_source_size_is_exists():
    out = ft.store(_ExistingGC(3), ft.bytes_source("m.vtt", b"abc"), "Documents")
    assert out["status"] == "exists"


def test_an_existing_file_of_another_size_is_an_error():
    out = ft.store(_ExistingGC(1), ft.bytes_source("m.vtt", b"abc"), "Documents")
    assert out["status"] == "error" and out["error"] == "existing_file_size_mismatch"


# 10. The recording scan follows the chat's older pages.

def _msg(n):
    return {"messagetype": "RichText/Media_CallRecording", "composetime": f"2026-10-{n:02d}T10:00:00Z", "content": f"rec{n}"}


def test_the_recording_scan_follows_older_pages(monkeypatch):
    rec = transcripts._tx_load("transcript_recording")
    pages = {
        "p1": {"messages": [_msg(19)], "_metadata": {"backwardLink": "p2"}},
        "p2": {"messages": [_msg(12)], "_metadata": {"backwardLink": "p3"}},
        "p3": {"messages": [_msg(5)], "_metadata": {}},
    }
    fetched = []

    def fake_get(url, token):
        key = "p1" if "messages?pageSize" in url else url
        fetched.append(key)
        return pages[key]

    fake_rc = SimpleNamespace(get_auth=lambda: ("tok", "https://msg"), _get=fake_get)
    monkeypatch.setattr(rec, "_load_skype", lambda: fake_rc)
    monkeypatch.setattr(rec, "_RECORDING_MSGTYPE", "RichText/Media_CallRecording")
    monkeypatch.setattr(rec, "_parse_recording_message", lambda content: (f"https://share/{content}", content, f"{content}.mp4", True))
    found = rec._scan_chat_for_recordings("19:meeting_abc@thread.v2")
    assert fetched == ["p1", "p2", "p3"]
    assert [f[1] for f in found] == ["rec19", "rec12", "rec5"]


def test_the_recording_scan_stops_at_the_page_cap(monkeypatch):
    rec = transcripts._tx_load("transcript_recording")
    calls = []

    def fake_get(url, token):
        calls.append(url)
        return {"messages": [], "_metadata": {"backwardLink": "again"}}

    monkeypatch.setattr(rec, "_load_skype", lambda: SimpleNamespace(get_auth=lambda: ("t", "https://msg"), _get=fake_get))
    rec._scan_chat_for_recordings("c", max_pages=4)
    assert len(calls) == 4
