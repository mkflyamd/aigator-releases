"""A status line says when its phase began, so the page can show how long it has been running."""

import json
import pathlib

import agent_loop

SRC = (pathlib.Path(__file__).parent.parent / "agent_loop.py").read_text(encoding="utf-8")
APP_JS = (pathlib.Path(__file__).parent.parent / "static" / "app.js").read_text(encoding="utf-8")


def _payload(chunk: str) -> dict:
    assert chunk.startswith("data: ") and chunk.endswith("\n\n")
    return json.loads(chunk[len("data: "):])


def test_a_status_event_carries_the_time_its_phase_began():
    event = _payload(agent_loop._sse_status("Searching Jira...", started_at=1000.5))
    assert event == {"status": "Searching Jira...", "started_at": 1000.5}


def test_a_status_event_defaults_to_now():
    event = _payload(agent_loop._sse_status("Searching Jira..."))
    assert isinstance(event["started_at"], float)


def test_both_loops_send_status_through_the_helper():
    assert "json.dumps({'status': evt['status']})" not in SRC
    assert SRC.count("_sse_status(evt[\"status\"])") == 2


def test_the_page_times_the_running_phase_without_more_events():
    assert "Taking longer than usual" in APP_JS
    assert "msg.started_at" in APP_JS
